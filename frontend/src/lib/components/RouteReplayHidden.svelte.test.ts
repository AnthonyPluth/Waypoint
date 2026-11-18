// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("$lib/map", async (original) => ({ ...(await original<typeof import("$lib/map")>()), loadCountries: async () => [], loadDetailedCountries: async () => [], loadFineCountries: async () => [] }));
vi.mock("$lib/mapkit", async (original) => ({ ...(await original<typeof import("$lib/mapkit")>()), loadMapkit: vi.fn() }));

import { api } from "$lib/api";
import type { TripPlaces } from "$lib/api-types";
import { app } from "$lib/app.svelte";
import { loadMapkit } from "$lib/mapkit";
import { fake, fakeMaps } from "../../test/fake-mapkit";
import { segment, state, trip } from "../../test/fixtures";
import RouteReplay from "./RouteReplay.svelte";

const places: TripPlaces = {
  home: null,
  airports: [
    { code: "MSP", city: "Minneapolis", latitude: 44.8848, longitude: -93.2223 },
    { code: "SFO", city: "San Francisco", latitude: 37.6213, longitude: -122.379 },
  ],
  cities: [], stays: [],
};
const there = segment({ id: 1, origin: "MSP", destination: "SFO", start_local: "2025-12-05T08:00", start_zone: "America/Chicago", end_local: "2025-12-05T10:30", end_zone: "America/Los_Angeles" });
const home = segment({ id: 2, origin: "SFO", destination: "MSP", start_local: "2025-12-11T13:00", start_zone: "America/Los_Angeles", end_local: "2025-12-11T18:50", end_zone: "America/Chicago" });
const after = Date.parse("2026-01-15T12:00:00Z");

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockResolvedValue(places as never);
  fake.reset();
  vi.mocked(loadMapkit).mockReset();
  vi.mocked(loadMapkit).mockImplementation(async () => fakeMaps());
  app.state = state({ mapkit: true } as never);
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
});
afterEach(() => { app.state = null; vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("RouteReplay when it is not shown", () => {
  it("reports how many stops it can place and draws nothing and builds no map", async () => {
    const onstops = vi.fn();
    render(RouteReplay, { trip: trip([there, home]), now: after, shown: false, onstops });
    await waitFor(() => expect(Math.max(...onstops.mock.calls.map(([n]) => n))).toBeGreaterThanOrEqual(2));
    expect(screen.queryByRole("region")).toBeNull();
    expect(screen.queryByRole("application")).toBeNull();
    expect(fake.maps).toHaveLength(0);
  });

  it("draws the map once it is shown, from the one MapKit session the app shares", async () => {
    const shared = trip([there, home]);
    const { rerender } = render(RouteReplay, { trip: shared, now: after, shown: false });
    await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalled());
    expect(fake.maps).toHaveLength(0);
    await rerender({ shown: true });
    expect(await screen.findByRole("region", { name: "Route replay" })).toBeTruthy();
    expect(fake.maps.length).toBeGreaterThanOrEqual(1);
    expect(loadMapkit).toHaveBeenCalledOnce();
  });

  it("draws the compact trip map on Apple's map, and lets it go on to the full replay", async () => {
    const shared = trip([there, home]);
    const { rerender } = render(RouteReplay, { trip: shared, now: after, shown: true, compact: true });
    expect(await screen.findByRole("group", { name: "Trip map" })).toBeTruthy();
    expect(document.querySelector("[data-mapkit]")).toBeTruthy();
    expect(fake.maps).toHaveLength(1);
    await rerender({ shown: true, compact: false });
    await waitFor(() => expect(document.querySelector("[data-mapkit]")!.getAttribute("role")).toBe("img"));
  });

  it("reports no stops, and offers nothing, when there is no key, however many stops the trip has", async () => {
    app.state = state({ mapkit: false });
    const onstops = vi.fn();
    render(RouteReplay, { trip: trip([there, home]), now: after, shown: false, onstops });
    await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 30));
    expect(Math.max(0, ...onstops.mock.calls.map(([n]) => n))).toBe(0);
    expect(loadMapkit).not.toHaveBeenCalled();
  });

  it("reports no stops once Apple's map is known not to load", async () => {
    vi.mocked(loadMapkit).mockResolvedValue(null);
    const onstops = vi.fn();
    render(RouteReplay, { trip: trip([there, home]), now: after, shown: false, onstops });
    await waitFor(() => expect(loadMapkit).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 30));
    expect(onstops.mock.calls.at(-1)?.[0]).toBe(0);
  });

  it("reports no stops for a trip with nothing to place", async () => {
    const onstops = vi.fn();
    render(RouteReplay, { trip: trip([]), now: after, shown: false, onstops });
    await waitFor(() => expect(onstops).toHaveBeenCalledWith(0));
    await new Promise((r) => setTimeout(r, 30));
    expect(Math.max(...onstops.mock.calls.map(([n]) => n))).toBe(0);
  });
});
