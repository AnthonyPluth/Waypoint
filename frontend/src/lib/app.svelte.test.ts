// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({ api: vi.fn(), newPage: vi.fn() }));
vi.mock("./offline.svelte", () => ({ syncSavedTrip: vi.fn() }));

import { api, newPage } from "./api";
import * as offlineModule from "./offline.svelte";
import { app, boot, checkIn, editing, refreshState, route, setQuery, whenBooted } from "./app.svelte";
import type { AppState } from "./types";

const state = (extra: Partial<AppState> = {}): AppState =>
  ({ version: "1.0", database: "sqlite", user: null, last_backup: null, review_count: 0, person_id: null, ...extra });
beforeEach(() => {
  vi.mocked(api).mockReset(); vi.mocked(newPage).mockClear();
  app.state = null; app.bootError = ""; app.sessionExpired = false;
});
afterEach(() => { vi.useRealTimers(); document.body.innerHTML = ""; });

describe("routing", () => {
  const go = async (hash: string) => { location.hash = hash; window.dispatchEvent(new HashChangeEvent("hashchange")); };

  it("reads the page and sub-page from the hash", async () => {
    await go("#settings/data");
    expect(route).toMatchObject({ page: "settings", sub: "data" });
  });

  it("ignores a query string, which belongs to the page's filters", async () => {
    await go("#upcoming?q=paris");
    expect(route).toMatchObject({ page: "upcoming", sub: "", query: "q=paris" });
  });

  it("setQuery changes the address without leaving the page", async () => {
    await go("#upcoming");
    setQuery("q=rome");
    expect(location.hash).toBe("#upcoming?q=rome");
    expect(route.query).toBe("q=rome");
  });

  it("opens Upcoming when there's no hash, and cancels the old page's reads on every change", async () => {
    await go("#settings");
    vi.mocked(newPage).mockClear();
    await go("");
    expect(route.page).toBe("upcoming");
    expect(newPage).toHaveBeenCalled();
  });
});

describe("editing", () => {
  it("is true while a field has focus, so a redraw doesn't discard what you typed", () => {
    document.body.innerHTML = `<input id="f">`;
    expect(editing()).toBe(false);
    document.getElementById("f")!.focus();
    expect(editing()).toBe(true);
  });

  it("is true while an editor is open", () => {
    document.body.innerHTML = `<div data-editor></div>`;
    expect(editing()).toBe(true);
  });
});

describe("session expiry", () => {
  const signedOut = (background: boolean) =>
    window.dispatchEvent(new CustomEvent("waypoint:signed-out", { cancelable: true, detail: { background } }));

  it("lets api send you to sign in when nothing's being edited", () => {
    expect(signedOut(false)).toBe(true);
    expect(app.sessionExpired).toBe(false);
  });

  it("keeps you on the page, with the banner, while you're editing or when Waypoint was only checking in", () => {
    expect(signedOut(true)).toBe(false);
    expect(app.sessionExpired).toBe(true);
    app.sessionExpired = false;
    document.body.innerHTML = `<div data-editor></div>`;
    expect(signedOut(false)).toBe(false);
    expect(app.sessionExpired).toBe(true);
  });
});

describe("state", () => {
  it("refreshState keeps the reply across page changes", async () => {
    vi.mocked(api).mockResolvedValue(state({ version: "1" }));
    await refreshState();
    expect(app.state?.version).toBe("1");
    expect(api).toHaveBeenCalledWith("/api/state", { keep: true });
    await refreshState(true);
    expect(api).toHaveBeenLastCalledWith("/api/state", { keep: true, background: true });
  });
});

describe("boot", () => {
  it("shows why when Waypoint can't be reached, and doesn't start anything", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.mocked(api).mockRejectedValue(new Error("Failed to fetch"));
    await boot();
    expect(app.bootError).toBe("Failed to fetch");
  });

  it("knows the connection is gone when the request never reached Waypoint", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.mocked(api).mockRejectedValue(Object.assign(new Error("Can’t reach Waypoint."), { status: 0 }));
    await boot();
    expect(app.offline).toBe(true);
    vi.mocked(api).mockRejectedValue(Object.assign(new Error("Server error"), { status: 500 }));
    await boot();
    expect(app.offline).toBe(false);
  });

  it("loads state once, and runs whenBooted callbacks", async () => {
    vi.mocked(api).mockResolvedValue(state());
    const early = vi.fn();
    whenBooted(early);
    expect(early).not.toHaveBeenCalled();
    await boot();
    expect(app.bootError).toBe("");
    expect(early).toHaveBeenCalledOnce();
    const late = vi.fn();
    whenBooted(late);
    expect(late).toHaveBeenCalledOnce();
    await boot();
    expect(early).toHaveBeenCalledOnce();
  });

  it("saves the current trip each time it loads online", async () => {
    vi.mocked(api).mockResolvedValue(state());
    vi.mocked(offlineModule.syncSavedTrip).mockClear();
    await boot();
    expect(offlineModule.syncSavedTrip).toHaveBeenCalledTimes(1);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(offlineModule.syncSavedTrip).toHaveBeenCalledTimes(2);
    window.dispatchEvent(new Event("online"));
    expect(offlineModule.syncSavedTrip).toHaveBeenCalledTimes(3);
  });
});

describe("checking in", () => {
  it("picks up changes every minute without sending you to sign in", async () => {
    vi.mocked(api).mockResolvedValue(state());
    await boot();
    vi.mocked(api).mockClear();
    checkIn();
    expect(api).toHaveBeenCalledWith("/api/state", { keep: true, background: true });
  });

  it("checks in on coming back to the tab, but not once signed out", async () => {
    vi.mocked(api).mockResolvedValue(state());
    await boot();
    vi.mocked(api).mockClear();
    document.dispatchEvent(new Event("visibilitychange"));
    expect(api).toHaveBeenCalledWith("/api/state", { keep: true, background: true });
    vi.mocked(api).mockClear();
    app.sessionExpired = true;
    document.dispatchEvent(new Event("visibilitychange"));
    checkIn();
    expect(api).not.toHaveBeenCalled();
  });
});
