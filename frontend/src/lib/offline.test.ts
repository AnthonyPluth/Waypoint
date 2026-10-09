// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./contract", () => ({ apiCall: vi.fn() }));

import { apiCall } from "./contract";
import { api } from "./api";
import { ignoreFailure } from "./act";
import { ago, clearSaved, expiryOf, isSavedCopy } from "./offline";
import { clearOnDenied, offline, refreshOffline, switchSaving, syncSavedTrip } from "./offline.svelte";
import { hasSavedTrip, lock, setUp, unlock } from "./offline-vault";
import { installDevice, type Device } from "../test/webauthn";
import { segment, trip } from "../test/fixtures";

const SECRET = "CANARY-Offline-Booking-3318";
let device: Device;
let projection: { trip: ReturnType<typeof trip> | null; messages: unknown[] };

const tripEnding = (day: string, name = "Trip to Springfield") =>
  ({ ...trip([segment({ confirmation: SECRET, start_local: `${day}T10:00`, end_local: `${day}T18:00` })]), name });

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
  vi.setSystemTime(new Date(2026, 10, 20, 9, 0));
  device = installDevice();
  projection = { trip: tripEnding("2026-11-22"), messages: [] };
  vi.mocked(apiCall).mockReset();
  vi.mocked(apiCall).mockImplementation((async () => projection) as never);
  Object.assign(offline, { checked: false, setUp: false, hasCopy: false, savedAt: null, off: false, damaged: false, supported: true, reason: "", declined: false });
});
afterEach(() => { lock(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

async function saved() {
  return (await unlock()) as { savedAt: number; trip: { name: string }; messages: unknown[] };
}

describe("saving the current trip", () => {
  it("saves nothing, and asks the server for nothing, before Face ID is set up on the device", async () => {
    await syncSavedTrip();
    expect(apiCall).not.toHaveBeenCalled();
    expect(device.writes).toEqual([]);
    expect(device.files.size).toBe(0);
  });

  it("saves the projection on load, encrypted, through the vault's two files only", async () => {
    await setUp();
    const asked = device.calls.get;
    await syncSavedTrip();
    expect(apiCall).toHaveBeenCalledWith("/api/offline");
    expect(device.writes.map((w) => w.url).sort()).toEqual(["/offline-vault/keys", "/offline-vault/trip"]);
    expect([...device.files.keys()].every((url) => url.startsWith("/offline-vault/"))).toBe(true);
    expect(device.appears(SECRET)).toBe(false);
    expect(device.appears("Springfield")).toBe(false);
    expect(device.calls.get).toBe(asked);
    expect(offline.hasCopy).toBe(true);
    const copy = await saved();
    expect(copy.trip.name).toBe("Trip to Springfield");
    expect(copy.savedAt).toBe(Date.now());
  });

  it("replaces the saved copy wholesale and never merges", async () => {
    await setUp();
    await syncSavedTrip();
    projection = { trip: { ...tripEnding("2026-11-23", "Second trip"), segments: [] }, messages: [] };
    await syncSavedTrip();
    const copy = await saved();
    expect(copy.trip.name).toBe("Second trip");
    expect(JSON.stringify(copy)).not.toContain(SECRET);
    expect(device.files.size).toBe(2);
  });

  it("drops the saved copy when the person no longer has a current trip", async () => {
    await setUp();
    await syncSavedTrip();
    expect(await hasSavedTrip()).toBe(true);
    projection = { trip: null, messages: [] };
    await syncSavedTrip();
    expect(await hasSavedTrip()).toBe(false);
    expect(offline.hasCopy).toBe(false);
  });

  it("keeps the old copy when the server can't be reached", async () => {
    await setUp();
    await syncSavedTrip();
    vi.mocked(apiCall).mockRejectedValue(new Error("Failed to fetch"));
    vi.spyOn(console, "error").mockImplementation(() => {});
    await syncSavedTrip();
    expect(await hasSavedTrip()).toBe(true);
    expect((await saved()).trip.name).toBe("Trip to Springfield");
  });

  it("makes one request when asked twice at once", async () => {
    await setUp();
    await Promise.all([syncSavedTrip(), syncSavedTrip()]);
    expect(apiCall).toHaveBeenCalledTimes(1);
  });
});

describe("switching saving off", () => {
  it("clears the copy, keeps the setup, and saves nothing while it is off", async () => {
    await setUp();
    await syncSavedTrip();
    await switchSaving(false);
    expect(offline.off).toBe(true);
    expect(await hasSavedTrip()).toBe(false);
    vi.mocked(apiCall).mockClear();
    await syncSavedTrip();
    expect(apiCall).not.toHaveBeenCalled();
    expect(await hasSavedTrip()).toBe(false);
    await refreshOffline();
    expect(offline.setUp).toBe(true);
    expect(offline.off).toBe(true);
  });

  it("keeps the switch in the vault's own files, not in the browser's storage", async () => {
    await setUp();
    await switchSaving(false);
    expect(device.fields("/offline-vault/keys").off).toBe(true);
    expect(device.writes.every((w) => w.url.startsWith("/offline-vault/"))).toBe(true);
  });

  it("saves again, at once, when it is switched back on", async () => {
    await setUp();
    await switchSaving(false);
    await switchSaving(true);
    expect(offline.off).toBe(false);
    expect(await hasSavedTrip()).toBe(true);
    expect(device.fields("/offline-vault/keys").off).toBeUndefined();
  });
});

describe("clearing", () => {
  const reply = (status: number) => Promise.resolve(new Response("{}", { status }));

  for (const status of [401, 403]) {
    it(`clears the copy when a request answers ${status} online`, async () => {
      clearOnDenied();
      await setUp();
      await syncSavedTrip();
      vi.stubGlobal("fetch", vi.fn(() => reply(status)));
      vi.stubGlobal("location", { href: "", pathname: "/", hash: "" });
      await api("/api/trips").catch(ignoreFailure);
      expect(await hasSavedTrip()).toBe(false);
      expect(offline.hasCopy).toBe(false);
    });
  }

  it("leaves the copy alone when a request fails for another reason", async () => {
    clearOnDenied();
    await setUp();
    await syncSavedTrip();
    vi.stubGlobal("fetch", vi.fn(() => reply(500)));
    await api("/api/trips").catch(ignoreFailure);
    expect(await hasSavedTrip()).toBe(true);
  });

  it("clears the copy 3 days after the trip ends, and not before", async () => {
    await setUp();
    await syncSavedTrip();
    const end = new Date(2026, 10, 22, 23, 59).getTime();
    const gone = new Date(2026, 10, 26, 0, 0).getTime();
    await vi.advanceTimersByTimeAsync(end + 3 * 86_400_000 - Date.now());
    expect(await hasSavedTrip()).toBe(true);
    await vi.advanceTimersByTimeAsync(gone - Date.now() + 1000);
    expect(await hasSavedTrip()).toBe(false);
    expect(offline.hasCopy).toBe(false);
  });

  it("clears a copy that ran out while the app was closed, when the app next looks", async () => {
    await setUp();
    await syncSavedTrip();
    lock();
    vi.setSystemTime(new Date(2026, 10, 27, 9, 0));
    await refreshOffline();
    expect(offline.hasCopy).toBe(false);
    expect(await hasSavedTrip()).toBe(false);
  });
});

describe("clearing while a save is under way", () => {
  it("is not undone by a save that was already asking the server", async () => {
    await setUp();
    await syncSavedTrip();
    let release!: (v: unknown) => void;
    vi.mocked(apiCall).mockImplementation((() => new Promise((r) => { release = r; })) as never);
    const saving = syncSavedTrip();
    await vi.advanceTimersByTimeAsync(0);
    const clearing = clearSaved();
    release(projection);
    await Promise.all([saving, clearing]);
    expect(await hasSavedTrip()).toBe(false);
  });

  it("says so, after one retry, when the device won't let the copy go", async () => {
    await setUp();
    await syncSavedTrip();
    const real = device.cacheStorage.open.getMockImplementation()!;
    let tries = 0;
    device.cacheStorage.open.mockImplementation((async () => ({ ...(await real()), delete: async () => { tries++; throw new Error("busy"); } })) as never);
    await expect(clearSaved()).rejects.toThrow("Couldn’t remove the saved trip from this device.");
    expect(tries).toBe(2);
  });
});

describe("the saved copy's helpers", () => {
  it("expires at the end of the third day after the trip's last day, on the device's clock", () => {
    expect(expiryOf({ trip: tripEnding("2026-11-22") })).toBe(new Date(2026, 10, 26).getTime());
    expect(expiryOf({ trip: null })).toBeNull();
  });

  it("says how long ago", () => {
    const now = Date.now();
    expect(ago(now, now)).toBe("just now");
    expect(ago(now - 5 * 60_000, now)).toBe("5 min ago");
    expect(ago(now - 2 * 3_600_000, now)).toBe("2 h ago");
    expect(ago(now - 72 * 3_600_000, now)).toBe("3 days ago");
  });

  it("recognises a saved copy", () => {
    expect(isSavedCopy({ savedAt: 1, messages: [], trip: tripEnding("2026-11-22") })).toBe(true);
    expect(isSavedCopy({ savedAt: 1, messages: [], trip: null })).toBe(false);
    expect(isSavedCopy({ name: "x", segments: [] })).toBe(false);
    expect(isSavedCopy(null)).toBe(false);
  });
});
