// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./contract", () => ({ apiCall: vi.fn() }));
vi.mock("./api", () => ({ api: vi.fn(), onDenied: vi.fn() }));

import { apiCall } from "./contract";
import { onDenied } from "./api";
import { clearSaved } from "./offline";
import { clearOnDenied, offline, offlineWorking, refreshOffline, removeOffline, switchSaving, syncSavedTrip, turnOnOffline, askAboutOffline } from "./offline.svelte";
import { inOldShell, inShell, shellBridge, shellLoad, shellStatus } from "./offline-shell";
import { installShell, type FakeShell } from "../test/fake-shell";
import { segment, trip } from "../test/fixtures";

const copy = (id: number, name: string, savedAt: number) => ({ savedAt, messages: [], trip: { ...trip([segment({ start_local: "2026-11-22T10:00", end_local: "2026-11-22T18:00" })]), id, name } });
const SAVED_AT = Date.UTC(2026, 10, 20, 7, 0);
const reset = () => Object.assign(offline, { syncing: false, oldApp: false, checked: false, setUp: false, hasCopy: false, savedAt: null, off: false, damaged: false, supported: true, reason: "", declined: false, failed: false, trips: [] });

beforeEach(() => { reset(); vi.mocked(apiCall).mockReset(); vi.mocked(onDenied).mockReset(); });
afterEach(() => { vi.unstubAllGlobals(); });

describe("the shell marker", () => {
  it("is the native offline handler on window.webkit, and nothing else", () => {
    expect(inShell()).toBe(false);
    vi.stubGlobal("webkit", { messageHandlers: { waypointUnauthorized: { postMessage: vi.fn() } } });
    expect(inShell()).toBe(false);
    vi.stubGlobal("webkit", { messageHandlers: { waypointOffline: {} } });
    expect(inShell()).toBe(false);
    expect(shellBridge({})).toBeNull();
    installShell();
    expect(inShell()).toBe(true);
  });
});

describe("in the iPhone app", () => {
  let shell: FakeShell;
  beforeEach(() => { shell = installShell({ trips: [copy(1, "Trip to London", SAVED_AT), copy(2, "Trip to Paris", SAVED_AT)], savedAt: SAVED_AT }); });

  it("is supported and takes its settings state from the bridge, with no vault and no server call", async () => {
    await refreshOffline();
    expect(shell.posts).toEqual([{ type: "status" }]);
    expect(offline).toMatchObject({ checked: true, supported: true, reason: "", setUp: true, off: false, damaged: false, hasCopy: true, savedAt: SAVED_AT });
    expect(offline.trips).toEqual([{ id: 1, name: "Trip to London" }, { id: 2, name: "Trip to Paris" }]);
    expect(offlineWorking()).toBe(true);
    expect(askAboutOffline()).toBe(false);
    expect(apiCall).not.toHaveBeenCalled();
  });

  it("reads the optional syncing and lastSaveFailed flags, and treats a missing one as false", async () => {
    shell.syncing = true; shell.lastSaveFailed = true;
    await refreshOffline();
    expect(offline).toMatchObject({ syncing: true, failed: true, hasCopy: true });
    expect(offlineWorking()).toBe(false);
    shell.replies.set("status", { version: 1, saving: true, savedAt: SAVED_AT, trips: [{ id: 1, name: "Trip to London" }] });
    await refreshOffline();
    expect(offline).toMatchObject({ syncing: false, failed: false });
    expect(await shellStatus()).toMatchObject({ syncing: false, lastSaveFailed: false });
    shell.replies.set("status", { version: 1, saving: true, syncing: "yes", savedAt: null, trips: [] });
    await refreshOffline();
    expect(offline.damaged).toBe(true);
    shell.replies.set("status", { version: 1, saving: true, lastSaveFailed: 1, savedAt: null, trips: [] });
    await refreshOffline();
    expect(offline).toMatchObject({ damaged: true, syncing: false });
  });

  it("shows saving switched off, with nothing saved", async () => {
    shell.saving = false; shell.trips = [];
    await refreshOffline();
    expect(offline).toMatchObject({ supported: true, setUp: true, off: true, hasCopy: false, savedAt: null, trips: [] });
    expect(offlineWorking()).toBe(false);
  });

  it("marks the copy damaged when the app's reply is unreadable, and never invents trips", async () => {
    for (const bad of [null, "x", { version: 2, saving: true, savedAt: null, trips: [] }, { version: 1, saving: "yes", savedAt: null, trips: [] }, { version: 1, saving: true, savedAt: "now", trips: [] }, { version: 1, saving: true, savedAt: 1, trips: [{ id: "1", name: "x" }] }]) {
      shell.replies.set("status", bad);
      await refreshOffline();
      expect(offline).toMatchObject({ checked: true, damaged: true, hasCopy: false, trips: [] });
    }
    shell.replies.set("status", Promise.reject(new Error("gone")));
    await refreshOffline();
    expect(offline.damaged).toBe(true);
  });

  it("loads the saved trips over the bridge", async () => {
    const loaded = await shellLoad();
    expect(shell.posts).toEqual([{ type: "load" }]);
    expect(loaded).toEqual(shell.trips);
    shell.replies.set("load", { version: 2, trips: [] });
    await expect(shellLoad()).rejects.toThrow("unreadable");
    shell.replies.set("load", { version: 1, trips: "no" });
    await expect(shellLoad()).rejects.toThrow("unreadable");
    shell.replies.set("status", { version: 3 });
    await expect(shellStatus()).rejects.toThrow("unreadable");
  });

  it("turns saving off through the bridge and shows nothing saved", async () => {
    await refreshOffline();
    await switchSaving(false);
    expect(shell.posts.at(-1)).toEqual({ type: "setSaving", on: false });
    expect(offline).toMatchObject({ off: true, hasCopy: false, savedAt: null, trips: [] });
    await switchSaving(true);
    expect(shell.posts.at(-1)).toEqual({ type: "setSaving", on: true });
    expect(offline.off).toBe(false);
    expect(apiCall).not.toHaveBeenCalled();
  });

  it("turns saving on from the offline setup, without a device check", async () => {
    shell.saving = false;
    expect(await turnOnOffline()).toBeNull();
    expect(shell.posts).toEqual([{ type: "setSaving", on: true }]);
    expect(offline).toMatchObject({ setUp: true, off: false });
    shell.replies.set("setSaving", null);
    expect((await turnOnOffline())?.code).toBe("failed");
  });

  it("removes the saved trips with Remove, and clears them when the session is denied", async () => {
    await refreshOffline();
    await removeOffline();
    expect(shell.posts.at(-1)).toEqual({ type: "remove" });
    expect(offline).toMatchObject({ hasCopy: false, savedAt: null, trips: [], setUp: true });
    shell.trips = [copy(1, "Trip to London", SAVED_AT)];
    clearOnDenied();
    await vi.mocked(onDenied).mock.calls[0][0]();
    expect(shell.posts.at(-1)).toEqual({ type: "remove" });
    expect(shell.trips).toEqual([]);
    expect(offline.hasCopy).toBe(false);
    shell.trips = [copy(1, "Trip to London", SAVED_AT)];
    await clearSaved();
    expect(shell.trips).toEqual([]);
  });

  it("leaves syncing to the app, and only re-reads the status", async () => {
    await syncSavedTrip();
    expect(shell.posts).toEqual([{ type: "status" }]);
    expect(apiCall).not.toHaveBeenCalled();
    expect(offline.hasCopy).toBe(true);
  });
});

describe("in an installed app too old for the bridge", () => {
  it("is recognised by the older app's own handler or Capacitor, and never when the bridge is there", () => {
    expect(inOldShell({})).toBe(false);
    expect(inOldShell({ webkit: { messageHandlers: { waypointUnauthorized: {} } } })).toBe(true);
    expect(inOldShell({ Capacitor: { isNativePlatform: () => true } })).toBe(true);
    expect(inOldShell({ Capacitor: { isNativePlatform: () => false } })).toBe(false);
    expect(inOldShell({ webkit: { messageHandlers: { waypointUnauthorized: {}, waypointOffline: { postMessage: () => {} } } } })).toBe(false);
  });

  it("marks the app as old, keeps the vault untouched and offers nothing", async () => {
    vi.stubGlobal("webkit", { messageHandlers: { waypointUnauthorized: { postMessage: vi.fn() } } });
    await refreshOffline();
    expect(offline).toMatchObject({ checked: true, oldApp: true, supported: false, setUp: false });
    expect(apiCall).not.toHaveBeenCalled();
  });
});

describe("in a browser, with no marker", () => {
  it("leaves the browser path as it was: no bridge call, the vault decides", async () => {
    const post = vi.fn();
    vi.stubGlobal("webkit", undefined);
    await refreshOffline();
    expect(post).not.toHaveBeenCalled();
    expect(inShell()).toBe(false);
    expect(offline.setUp).toBe(false);
    expect(offline.checked).toBe(true);
    expect(offline.oldApp).toBe(false);
    await expect(shellStatus()).rejects.toThrow("Not running in the Waypoint app");
  });
});
