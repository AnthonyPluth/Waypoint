// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));

import { api } from "$lib/api";
import type { FlightStatusList } from "$lib/api-types";
import { segment } from "../test/fixtures";
import { LIVE_EVERY, flightStatus, liveFlight, loadFlightStatus, refreshFlightStatus, statusFor, watchFlightStatus } from "./flightstatus.svelte";

const reply = { enabled: true, month: "2026-11", used: 3, limit: 400, paused: null, statuses: [{ segment_id: 4, state: "landed" }] };

beforeEach(() => { vi.mocked(api).mockReset(); flightStatus.list = null; flightStatus.problem = ""; });

describe("the flight status the app holds", () => {
  it("loads the list, and finds a segment’s status in it", async () => {
    vi.mocked(api).mockResolvedValue(reply);
    await loadFlightStatus();
    expect(api).toHaveBeenCalledWith("/api/flight-status");
    expect(statusFor(4)?.state).toBe("landed");
    expect(statusFor(5)).toBeUndefined();
  });

  it("keeps what it had, and says why, when it can’t load", async () => {
    vi.mocked(api).mockResolvedValueOnce(reply);
    await loadFlightStatus();
    vi.mocked(api).mockRejectedValueOnce(new Error("offline"));
    await loadFlightStatus();
    expect(flightStatus.problem).toBe("offline");
    expect(flightStatus.list?.used).toBe(3);
  });

  it("refreshes from nothing held too", async () => {
    vi.mocked(api).mockResolvedValue(reply);
    await refreshFlightStatus(4);
    expect(flightStatus.list?.statuses).toHaveLength(1);
  });
});

const DEPARTS = Date.UTC(2026, 10, 21, 0, 0);
const LANDS = Date.UTC(2026, 10, 21, 7, 10);
const HOUR = 3_600_000;
const flight = segment({ id: 4 });
const late = (state: string, arr_estimated: string | null = null) => ({ ...reply, statuses: [{ segment_id: 4, state, arr_estimated, arr_zone: "Europe/London" }] }) as unknown as FlightStatusList;

describe("which flights are live", () => {
  it("is a flight from a day before it leaves to six hours after it lands", () => {
    expect(liveFlight(flight, DEPARTS - 25 * HOUR)).toBe(false);
    expect(liveFlight(flight, DEPARTS - 24 * HOUR)).toBe(true);
    expect(liveFlight(flight, DEPARTS + HOUR)).toBe(true);
    expect(liveFlight(flight, LANDS + 6 * HOUR)).toBe(true);
    expect(liveFlight(flight, LANDS + 7 * HOUR)).toBe(false);
  });

  it("stays live while it is expected later, and not once it is over", () => {
    flightStatus.list = late("delayed", "2026-11-21T10:10");
    expect(liveFlight(flight, LANDS + 8 * HOUR)).toBe(true);
    for (const state of ["landed", "cancelled", "diverted"]) {
      flightStatus.list = late(state);
      expect(liveFlight(flight, DEPARTS)).toBe(false);
    }
  });

  it("isn’t a stay, a cancelled flight or one without times", () => {
    expect(liveFlight(segment({ id: 4, kind: "hotel" }), DEPARTS)).toBe(false);
    expect(liveFlight(segment({ id: 4, status: "cancelled" }), DEPARTS)).toBe(false);
    expect(liveFlight(segment({ id: 4, details: { flight_number: "EX 101", time_unknown: "yes" } }), DEPARTS)).toBe(false);
  });
});

describe("watching the stored status", () => {
  let stop = () => {};
  let hidden = false;
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    hidden = false;
    vi.spyOn(document, "visibilityState", "get").mockImplementation(() => (hidden ? "hidden" : "visible"));
    vi.mocked(api).mockResolvedValue({ ...reply, statuses: [] });
  });
  afterEach(() => { stop(); vi.useRealTimers(); vi.restoreAllMocks(); });
  const reads = () => vi.mocked(api).mock.calls.filter(([path]) => path === "/api/flight-status").length;

  it("re-reads it every minute while a flight is near, and never asks the provider", async () => {
    vi.setSystemTime(DEPARTS - 2 * HOUR);
    stop = watchFlightStatus(() => [flight]);
    await vi.advanceTimersByTimeAsync(3 * LIVE_EVERY);
    expect(reads()).toBe(3);
    expect(vi.mocked(api).mock.calls.every(([path, opts]) => path === "/api/flight-status" && !opts)).toBe(true);
  });

  it("shows a delay the server found without a reload", async () => {
    vi.setSystemTime(DEPARTS - 10 * 60_000);
    await loadFlightStatus();
    stop = watchFlightStatus(() => [flight]);
    vi.mocked(api).mockResolvedValue(late("delayed"));
    await vi.advanceTimersByTimeAsync(LIVE_EVERY);
    expect(statusFor(4)?.state).toBe("delayed");
  });

  it("doesn’t poll for a flight far ahead or long over, or while the page is hidden", async () => {
    for (const at of [DEPARTS - 3 * 24 * HOUR, LANDS + 24 * HOUR]) {
      vi.setSystemTime(at);
      stop = watchFlightStatus(() => [flight]);
      await vi.advanceTimersByTimeAsync(5 * LIVE_EVERY);
      window.dispatchEvent(new Event("focus"));
      stop();
    }
    vi.setSystemTime(DEPARTS);
    hidden = true;
    stop = watchFlightStatus(() => [flight]);
    await vi.advanceTimersByTimeAsync(5 * LIVE_EVERY);
    expect(reads()).toBe(0);
  });

  it("re-reads it when the app comes back to the front or the window gets focus, once for both", async () => {
    vi.setSystemTime(DEPARTS + HOUR);
    stop = watchFlightStatus(() => [flight]);
    hidden = true;
    document.dispatchEvent(new Event("visibilitychange"));
    expect(reads()).toBe(0);
    hidden = false;
    document.dispatchEvent(new Event("visibilitychange"));
    window.dispatchEvent(new Event("focus"));
    expect(reads()).toBe(1);
    await vi.advanceTimersByTimeAsync(10_000);
    window.dispatchEvent(new Event("focus"));
    expect(reads()).toBe(2);
  });

  it("stops when the page goes, and when live status is off", async () => {
    vi.setSystemTime(DEPARTS);
    stop = watchFlightStatus(() => [flight]);
    stop();
    window.dispatchEvent(new Event("focus"));
    await vi.advanceTimersByTimeAsync(3 * LIVE_EVERY);
    expect(reads()).toBe(0);
    flightStatus.list = { ...reply, enabled: false } as unknown as FlightStatusList;
    stop = watchFlightStatus(() => [flight]);
    await vi.advanceTimersByTimeAsync(3 * LIVE_EVERY);
    expect(reads()).toBe(0);
  });
});
