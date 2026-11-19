// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ARRIVAL_EVENT, TARGET_LIFETIME, arrival, checkArrivalHere, dismissArrival, listenForArrival, openBooking, openable, pendingFor, resetArrival, settleTarget, takePendingArrival } from "./arrival.svelte";
import { installShell, type FakeShell } from "../test/fake-shell";
import { segment } from "../test/fixtures";

let shell: FakeShell;
const reply = (type: string, segmentId: number | null, tripId: number | null) => shell.replies.set(type, { version: 1, segmentId, tripId });
const asked = (type: string) => shell.posts.filter((p) => p.type === type).length;

beforeEach(() => { resetArrival(); location.hash = "#upcoming"; shell = installShell(); });
afterEach(() => { vi.unstubAllGlobals(); });

describe("the arrival the app hands over after a tap on the notification", () => {
  it("opens the booking’s trip and remembers which booking, from ids alone", async () => {
    reply("pendingArrival", 5, 7);
    await takePendingArrival();
    expect(location.hash).toBe("#trip/7");
    expect(pendingFor(7)).toBe(5);
    expect(pendingFor(8)).toBeNull();
    expect(arrival.target).toEqual({ segmentId: 5, tripId: 7, at: expect.any(Number) });
  });

  it("leaves the page alone when the trip is already open, and does nothing when there is no arrival", async () => {
    location.hash = "#trip/7?segment=5";
    reply("pendingArrival", 5, 7);
    await takePendingArrival();
    expect(location.hash).toBe("#trip/7?segment=5");
    reply("pendingArrival", null, null);
    settleTarget();
    await takePendingArrival();
    expect(arrival.target).toBeNull();
    expect(location.hash).toBe("#trip/7?segment=5");
  });

  it("leaves the flight details of the trip for the trip page, so its code can open, and keeps every address of the trip page", async () => {
    reply("pendingArrival", 5, 7);
    for (const there of ["#trip/7/flight/34", "#trip/7/flight/34?x=1", "#trip/8/flight/34", "#trip/8", "#trips", "#upcoming"]) {
      location.hash = there;
      await takePendingArrival();
      expect(location.hash).toBe("#trip/7");
    }
    for (const stay of ["#trip/7", "#trip/7?segment=5", "#trip/7/other", "#trip/7/flight", "#trip/7/flight/x"]) {
      location.hash = stay;
      await takePendingArrival();
      expect(location.hash).toBe(stay);
    }
    openBooking(6, 7);
    expect(location.hash).toBe("#trip/7/flight/x");
    location.hash = "#trip/7/flight/9";
    openBooking(6, 7);
    expect(location.hash).toBe("#trip/7");
  });

  it("forgets the arrival once its trip page has used it, and after two minutes", async () => {
    reply("pendingArrival", 5, 7);
    await takePendingArrival();
    expect(pendingFor(7, Date.now() + TARGET_LIFETIME + 1)).toBeNull();
    settleTarget();
    expect(pendingFor(7)).toBeNull();
  });

  it("asks at start and again when the app says an arrival is waiting, and not at all in a browser", async () => {
    reply("pendingArrival", null, null);
    const stop = listenForArrival();
    await vi.waitFor(() => expect(asked("pendingArrival")).toBe(1));
    reply("pendingArrival", 5, 7);
    window.dispatchEvent(new Event(ARRIVAL_EVENT));
    await vi.waitFor(() => expect(arrival.target?.segmentId).toBe(5));
    expect(asked("pendingArrival")).toBe(2);
    stop();
    window.dispatchEvent(new Event(ARRIVAL_EVENT));
    expect(asked("pendingArrival")).toBe(2);
    vi.unstubAllGlobals();
    const none = listenForArrival();
    await takePendingArrival();
    none();
    expect(asked("pendingArrival")).toBe(2);
  });

  it("ignores a reply that is not two ids", async () => {
    for (const bad of [{ version: 1, segmentId: 5, tripId: null }, { version: 1, segmentId: "5", tripId: 7 }, { version: 2, segmentId: 5, tripId: 7 }, { version: 1, segmentId: 0, tripId: 7 }, { version: 1, segmentId: 1.5, tripId: 7 }, null]) {
      shell.replies.set("pendingArrival", bad);
      await takePendingArrival();
      expect(arrival.target).toBeNull();
    }
  });
});

describe("the check for the booking you are at", () => {
  it("keeps the one booking the app named", async () => {
    reply("arrivalHere", 5, 7);
    await checkArrivalHere();
    expect(arrival.here).toEqual({ segmentId: 5, tripId: 7 });
  });

  it("holds a dismissal until the app says you are somewhere else, then lets the next arrival show", async () => {
    reply("arrivalHere", 5, 7);
    await checkArrivalHere();
    dismissArrival(5);
    await checkArrivalHere();
    expect(arrival.dismissed).toBe(5);
    reply("arrivalHere", null, null);
    await checkArrivalHere();
    expect(arrival.here).toBeNull();
    expect(arrival.dismissed).toBeNull();
  });

  it("lets a dismissed booking show again once the app has named a different one", async () => {
    reply("arrivalHere", 5, 7);
    await checkArrivalHere();
    dismissArrival(5);
    reply("arrivalHere", 8, 7);
    await checkArrivalHere();
    expect(arrival.dismissed).toBeNull();
    reply("arrivalHere", 5, 7);
    await checkArrivalHere();
    expect(arrival.dismissed).toBeNull();
    expect(arrival.here).toEqual({ segmentId: 5, tripId: 7 });
  });

  it("shows no card when the check fails, and keeps a dismissal through it", async () => {
    reply("arrivalHere", 5, 7);
    await checkArrivalHere();
    dismissArrival(5);
    shell.replies.set("arrivalHere", { version: 1, segmentId: "x" });
    await checkArrivalHere();
    expect(arrival.here).toBeNull();
    expect(arrival.dismissed).toBe(5);
  });

  it("lets the latest answer win when two checks overlap", async () => {
    const through = (answer: Promise<unknown>) => vi.stubGlobal("webkit", { messageHandlers: { waypointOffline: { postMessage: vi.fn(() => answer) } } });
    let release: (value: unknown) => void = () => {};
    through(new Promise((resolve) => { release = resolve; }));
    const older = checkArrivalHere();
    through(Promise.resolve({ version: 1, segmentId: 6, tripId: 7 }));
    await checkArrivalHere();
    release({ version: 1, segmentId: 5, tripId: 7 });
    await older;
    expect(arrival.here).toEqual({ segmentId: 6, tripId: 7 });
  });

  it("asks nothing in a browser", async () => {
    vi.unstubAllGlobals();
    await checkArrivalHere();
    expect(arrival.here).toBeNull();
    expect(asked("arrivalHere")).toBe(0);
  });
});

describe("which bookings have a code to open", () => {
  const NOW = Date.parse("2026-12-01T12:00:00Z");
  const lot = segment({ id: 1, kind: "parking", start_local: "2026-12-01T09:00", end_local: "2026-12-05T18:00", start_zone: "America/Denver", end_zone: "America/Denver", gate_code: { state: "ready", day: "2026-10-16" } });

  it("is a parking booking with a ready code that has not ended, or a rental or stay with a confirmation number", () => {
    expect(openable(lot, NOW)).toBe(true);
    expect(openable({ ...lot, gate_code: null }, NOW)).toBe(false);
    expect(openable({ ...lot, gate_code: { state: "choose", day: null } }, NOW)).toBe(false);
    expect(openable(lot, Date.parse("2026-12-06T12:00:00Z"))).toBe(false);
    expect(openable({ ...lot, status: "cancelled" }, NOW)).toBe(false);
    expect(openable(segment({ kind: "car", confirmation: "AB12" }), NOW)).toBe(true);
    expect(openable(segment({ kind: "hotel", confirmation: " " }), NOW)).toBe(false);
    expect(openable(segment({ kind: "car", confirmation: null }), NOW)).toBe(false);
    expect(openable(segment({ kind: "flight", confirmation: "AB12" }), NOW)).toBe(false);
  });
});

describe("opening a booking from the card", () => {
  it("goes to its trip and hands the booking to the trip page", () => {
    location.hash = "#upcoming";
    openBooking(5, 7);
    expect(location.hash).toBe("#trip/7");
    expect(pendingFor(7)).toBe(5);
  });
});
