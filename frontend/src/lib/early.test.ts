// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({ api: vi.fn(), newPage: vi.fn() }));
vi.mock("./flightstatus.svelte", () => ({ loadFlightStatus: vi.fn() }));

import { api } from "./api";
import { dropEarly, EARLY_FRESH_MS, startEarly, takeEarlyTrips } from "./early";
import { loadFlightStatus } from "./flightstatus.svelte";

beforeEach(() => {
  vi.useRealTimers();
  dropEarly();
  vi.mocked(api).mockReset().mockResolvedValue({ trips: [] });
  vi.mocked(loadFlightStatus).mockReset();
});

describe("starting the first reads early", () => {
  it("reads the trips and the flight status for Upcoming, once", async () => {
    startEarly("upcoming");
    startEarly("upcoming");
    expect(api).toHaveBeenCalledTimes(1);
    expect(api).toHaveBeenCalledWith("/api/trips");
    expect(loadFlightStatus).toHaveBeenCalledTimes(1);
    expect(await takeEarlyTrips("upcoming")).toEqual({ trips: [] });
  });

  it("reads only the trips for the Trips page", () => {
    startEarly("trips");
    expect(api).toHaveBeenCalledWith("/api/trips");
    expect(loadFlightStatus).not.toHaveBeenCalled();
  });

  it.each(["stats", "settings", "people", "review", "trip"])("reads nothing for %s", (page) => {
    startEarly(page);
    expect(api).not.toHaveBeenCalled();
    expect(takeEarlyTrips(page)).toBeNull();
  });
});

describe("taking the early read", () => {
  it("hands it over once, and only to the page that asked for it", () => {
    startEarly("upcoming");
    expect(takeEarlyTrips("trips")).toBeNull();
    expect(takeEarlyTrips("upcoming")).not.toBeNull();
    expect(takeEarlyTrips("upcoming")).toBeNull();
  });

  it("is dropped when the page changes, so a cancelled read is never waited on", () => {
    startEarly("upcoming");
    dropEarly();
    expect(takeEarlyTrips("upcoming")).toBeNull();
  });

  it("gives the page the failure, and leaves nothing unhandled when nobody takes it", async () => {
    vi.mocked(api).mockRejectedValue(new Error("down"));
    startEarly("upcoming");
    await expect(takeEarlyTrips("upcoming")).rejects.toThrow("down");
    dropEarly();
    startEarly("trips");
    await Promise.resolve();
  });

  it("is not used once it is old, so a slow or retried start never shows stale trips", () => {
    vi.useFakeTimers();
    startEarly("upcoming");
    vi.advanceTimersByTime(EARLY_FRESH_MS + 1);
    expect(takeEarlyTrips("upcoming")).toBeNull();
    startEarly("upcoming");
    vi.advanceTimersByTime(EARLY_FRESH_MS);
    expect(takeEarlyTrips("upcoming")).not.toBeNull();
  });
});
