// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./contract", () => ({ apiCall: vi.fn() }));

import { apiCall } from "./contract";
import { api } from "./api";
import { ignoreFailure } from "./act";
import { ago, clearSaved, expiryOf, isSavedCopy, savedList } from "./offline";
import { clearOnDenied, offline, refreshOffline, switchSaving, syncSavedTrip } from "./offline.svelte";
import { hasSavedTrip, lock, savedInfos, setUp, unlock } from "./offline-vault";
import { installDevice, type Device } from "../test/webauthn";
import { segment, trip } from "../test/fixtures";

const SECRET = "CANARY-Offline-Booking-3318";
let device: Device;
type Held = ReturnType<typeof trip>;
let projection: { trips: { trip: Held; messages: unknown[] }[] };

const tripEnding = (day: string, name = "Trip to Springfield", id = 1) =>
  ({ ...trip([segment({ confirmation: SECRET, start_local: `${day}T10:00`, end_local: `${day}T18:00` })]), name, id });
const copyOf = (t: Held) => ({ trip: t, messages: [] });

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
  vi.setSystemTime(new Date(2026, 10, 20, 9, 0));
  device = installDevice();
  projection = { trips: [copyOf(tripEnding("2026-11-22"))] };
  vi.mocked(apiCall).mockReset();
  vi.mocked(apiCall).mockImplementation((async () => projection) as never);
  Object.assign(offline, { checked: false, setUp: false, hasCopy: false, savedAt: null, off: false, damaged: false, supported: true, reason: "", declined: false });
});
afterEach(() => { lock(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

type Saved = { savedAt: number; trip: { id: number; name: string }; messages: unknown[] };
async function savedAll() {
  return (await unlock()) as Saved[];
}
async function saved() {
  const [only] = await savedAll();
  return only;
}

describe("saving the current trip", () => {
  it("saves nothing, and asks the server for nothing, before Face ID is set up on the device", async () => {
    await syncSavedTrip();
    expect(apiCall).not.toHaveBeenCalled();
    expect(device.writes).toEqual([]);
    expect(device.files.size).toBe(0);
  });

  it("saves the projection on load, encrypted, through the vault's own files only", async () => {
    await setUp();
    const asked = device.calls.get;
    await syncSavedTrip();
    expect(apiCall).toHaveBeenCalledWith("/api/offline");
    expect(device.writes.map((w) => w.url).sort()).toEqual(["/offline-vault/keys", "/offline-vault/trip/1"]);
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
    projection = { trips: [copyOf({ ...tripEnding("2026-11-23", "Second trip"), segments: [] })] };
    await syncSavedTrip();
    const copy = await saved();
    expect(copy.trip.name).toBe("Second trip");
    expect(JSON.stringify(copy)).not.toContain(SECRET);
    expect(device.files.size).toBe(2);
  });

  it("drops the saved copy when the person no longer has a trip to save", async () => {
    await setUp();
    await syncSavedTrip();
    expect(await hasSavedTrip()).toBe(true);
    projection = { trips: [] };
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
    await expect(clearSaved()).rejects.toThrow("Couldn’t remove the saved trips from this device.");
    expect(tries).toBe(2);
  });
});

describe("the saved copy's helpers", () => {
  it("expires at the end of the third day after the trip's last day, on the device's clock", () => {
    expect(expiryOf({ trip: tripEnding("2026-11-22") })).toBe(new Date(2026, 10, 26).getTime());
    expect(expiryOf({ trip: { ...tripEnding("2026-11-22"), end_date: null, start_date: null } })).toBeNull();
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
    expect(isSavedCopy({ trips: [] })).toBe(false);
    expect(isSavedCopy({ savedAt: 1, messages: [], trip: null })).toBe(false);
    expect(isSavedCopy({ name: "x", segments: [] })).toBe(false);
    expect(isSavedCopy(null)).toBe(false);
  });
});

describe("saving several trips", () => {
  const SOON = tripEnding("2026-12-05", "Soon trip", 2);
  const UNDER_WAY = tripEnding("2026-11-21", "Under way", 1);
  const FAR = tripEnding("2027-03-04", "Far trip", 3);
  const urls = () => [...device.files.keys()].filter((u) => u.startsWith("/offline-vault/trip")).sort();

  it("saves each trip as its own encrypted copy, with the server's order and every trip's name for the status", async () => {
    await setUp();
    projection = { trips: [copyOf(UNDER_WAY), copyOf(SOON), copyOf(FAR)] };
    await syncSavedTrip();
    expect(urls()).toEqual(["/offline-vault/trip/1", "/offline-vault/trip/2", "/offline-vault/trip/3"]);
    expect(device.appears("Far trip")).toBe(false);
    expect(device.appears(SECRET)).toBe(false);
    expect((await savedAll()).map((c) => c.trip.name)).toEqual(["Under way", "Soon trip", "Far trip"]);
    expect(offline.trips).toEqual([{ id: 1, name: "Under way" }, { id: 2, name: "Soon trip" }, { id: 3, name: "Far trip" }]);
    expect(offline.hasCopy).toBe(true);
  });

  it("keeps the server's order after an unlock: the trip under way first, even with a higher number", async () => {
    await setUp();
    projection = { trips: [copyOf(tripEnding("2026-11-21", "Under way", 10)), copyOf(tripEnding("2026-11-22", "Soon trip", 2))] };
    await syncSavedTrip();
    expect((await savedAll()).map((c) => c.trip.name)).toEqual(["Under way", "Soon trip"]);
    lock();
    await refreshOffline();
    expect(offline.trips.map((t) => t.id)).toEqual([10, 2]);
  });

  it("saves the next upcoming trip however far out it is, alone", async () => {
    await setUp();
    projection = { trips: [copyOf(FAR)] };
    await syncSavedTrip();
    expect((await savedAll()).map((c) => c.trip.name)).toEqual(["Far trip"]);
    expect(offline.trips).toEqual([{ id: 3, name: "Far trip" }]);
    expect((await savedInfos())[0].expiresAt).toBe(new Date(2027, 2, 8).getTime());
  });

  it("sets each trip's own time to run out, 3 days after that trip ends", async () => {
    await setUp();
    projection = { trips: [copyOf(UNDER_WAY), copyOf(FAR)] };
    await syncSavedTrip();
    expect(await savedInfos()).toEqual([
      { savedAt: Date.now(), expiresAt: new Date(2026, 10, 25).getTime(), tripId: 1 },
      { savedAt: Date.now(), expiresAt: new Date(2027, 2, 8).getTime(), tripId: 3 },
    ]);
  });

  it("clears only the trip whose time has come, and keeps the rest until theirs", async () => {
    await setUp();
    projection = { trips: [copyOf(UNDER_WAY), copyOf(SOON), copyOf(FAR)] };
    await syncSavedTrip();
    await vi.advanceTimersByTimeAsync(new Date(2026, 10, 25, 0, 0, 1).getTime() - Date.now());
    expect(urls()).toEqual(["/offline-vault/trip/2", "/offline-vault/trip/3"]);
    expect(offline.hasCopy).toBe(true);
    expect(offline.trips.map((t) => t.id)).toEqual([2, 3]);
    await vi.advanceTimersByTimeAsync(new Date(2026, 11, 9, 0, 0, 1).getTime() - Date.now());
    expect((await savedAll()).map((c) => c.trip.name)).toEqual(["Far trip"]);
    expect(offline.trips.map((t) => t.id)).toEqual([3]);
    await vi.advanceTimersByTimeAsync(new Date(2027, 2, 8, 0, 0, 1).getTime() - Date.now());
    expect(await hasSavedTrip()).toBe(false);
    expect(offline.hasCopy).toBe(false);
    expect(offline.trips).toEqual([]);
  });

  it("clears trips that ran out while the app was closed, when the app next looks, and keeps the others", async () => {
    await setUp();
    projection = { trips: [copyOf(UNDER_WAY), copyOf(FAR)] };
    await syncSavedTrip();
    lock();
    vi.setSystemTime(new Date(2026, 10, 27, 9, 0));
    await refreshOffline();
    expect(offline.trips.map((t) => t.id)).toEqual([3]);
    expect(urls()).toEqual(["/offline-vault/trip/3"]);
  });

  it("replaces the whole set on the next save, so a trip that is no longer wanted is gone", async () => {
    await setUp();
    projection = { trips: [copyOf(UNDER_WAY), copyOf(FAR)] };
    await syncSavedTrip();
    projection = { trips: [copyOf(SOON)] };
    await syncSavedTrip();
    expect(urls()).toEqual(["/offline-vault/trip/2"]);
    expect((await savedAll()).map((c) => c.trip.name)).toEqual(["Soon trip"]);
  });

  it("clears every trip on sign-out, 401 and 403 and when saving is turned off", async () => {
    await setUp();
    projection = { trips: [copyOf(UNDER_WAY), copyOf(SOON), copyOf(FAR)] };
    await syncSavedTrip();
    await clearSaved();
    expect(urls()).toEqual([]);
    await syncSavedTrip();
    expect(urls().length).toBe(3);
    await switchSaving(false);
    expect(urls()).toEqual([]);
    expect(offline.trips).toEqual([]);
  });

  it("clears every trip when a request answers 401 online", async () => {
    clearOnDenied();
    await setUp();
    projection = { trips: [copyOf(UNDER_WAY), copyOf(FAR)] };
    await syncSavedTrip();
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response("{}", { status: 401 }))));
    vi.stubGlobal("location", { href: "", pathname: "/", hash: "" });
    await api("/api/trips").catch(ignoreFailure);
    expect(urls()).toEqual([]);
    expect(offline.hasCopy).toBe(false);
    expect(offline.trips).toEqual([]);
  });

  it("names the saved trips for a sentence, or counts them when the names aren't known yet", () => {
    expect(savedList([{ name: "A" }, { name: "B" }])).toBe("“A”, “B”");
    expect(savedList([{ name: "A" }, { name: "" }])).toBe("2 trips");
    expect(savedList([{ name: "" }])).toBe("1 trip");
  });
});
