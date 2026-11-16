// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("$lib/map", async (original) => ({ ...(await original<typeof import("$lib/map")>()), loadCountries: async () => [], loadDetailedCountries: async () => [], loadFineCountries: async () => [] }));
vi.mock("$lib/mapkit", async (original) => ({ ...(await original<typeof import("$lib/mapkit")>()), loadMapkit: vi.fn(async () => null) }));

import { api } from "$lib/api";
import type { TripPlaces } from "$lib/api-types";
import { app } from "$lib/app.svelte";
import { loadMapkit } from "$lib/mapkit";
import { segment, state, trip } from "../../test/fixtures";
import RouteReplay from "./RouteReplay.svelte";

const places: TripPlaces = {
  home: null,
  airports: [
    { code: "MSP", city: "Minneapolis", latitude: 44.8848, longitude: -93.2223 },
    { code: "SFO", city: "San Francisco", latitude: 37.6213, longitude: -122.379 },
  ],
  cities: [], stays: [], roads: { legs: [], interstates: [] }, boundaries: [],
};
const there = segment({ id: 1, origin: "MSP", destination: "SFO", start_local: "2025-12-05T08:00", start_zone: "America/Chicago", end_local: "2025-12-05T10:30", end_zone: "America/Los_Angeles" });
const home = segment({ id: 2, origin: "SFO", destination: "MSP", start_local: "2025-12-11T13:00", start_zone: "America/Los_Angeles", end_local: "2025-12-11T18:50", end_zone: "America/Chicago" });
const after = Date.parse("2026-01-15T12:00:00Z");

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockResolvedValue(places as never);
  vi.mocked(loadMapkit).mockClear();
  app.state = state({ mapkit: true } as never);
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
});
afterEach(() => { app.state = null; vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("RouteReplay when it is not shown", () => {
  it("reports how many stops it can place and draws nothing, and loads no Apple script", async () => {
    const onstops = vi.fn();
    render(RouteReplay, { trip: trip([there, home]), now: after, shown: false, onstops });
    await waitFor(() => expect(Math.max(...onstops.mock.calls.map(([n]) => n))).toBeGreaterThanOrEqual(2));
    expect(screen.queryByRole("region")).toBeNull();
    expect(loadMapkit).not.toHaveBeenCalled();
  });

  it("draws the map, and asks for Apple's script, once it is shown", async () => {
    const { rerender } = render(RouteReplay, { trip: trip([there, home]), now: after, shown: false });
    await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalled());
    expect(loadMapkit).not.toHaveBeenCalled();
    await rerender({ trip: trip([there, home]), now: after, shown: true });
    expect(await screen.findByRole("region", { name: "Route replay" })).toBeTruthy();
    expect(loadMapkit).toHaveBeenCalledOnce();
  });

  it("reports no stops for a trip with nothing to place", async () => {
    const onstops = vi.fn();
    render(RouteReplay, { trip: trip([]), now: after, shown: false, onstops });
    await waitFor(() => expect(onstops).toHaveBeenCalledWith(0));
    await new Promise((r) => setTimeout(r, 30));
    expect(Math.max(...onstops.mock.calls.map(([n]) => n))).toBe(0);
  });
});
