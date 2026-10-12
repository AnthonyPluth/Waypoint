// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("$lib/map", async (original) => ({ ...(await original<typeof import("$lib/map")>()), loadCountries: async () => [] }));

import { api } from "$lib/api";
import type { TripPlaces } from "$lib/api-types";
import { segment, trip } from "../../test/fixtures";
import RouteReplay from "./RouteReplay.svelte";

const places: TripPlaces = {
  airports: [
    { code: "MSP", city: "Minneapolis", latitude: 44.8848, longitude: -93.2223 },
    { code: "SFO", city: "San Francisco", latitude: 37.6213, longitude: -122.379 },
  ],
  cities: [],
  stays: [],
};
const there = segment({ id: 1, origin: "MSP", destination: "SFO", start_local: "2025-12-05T08:00", start_zone: "America/Chicago", end_local: "2025-12-05T10:30", end_zone: "America/Los_Angeles" });
const home = segment({ id: 2, origin: "SFO", destination: "MSP", start_local: "2025-12-11T13:00", start_zone: "America/Los_Angeles", end_local: "2025-12-11T18:50", end_zone: "America/Chicago" });
const after = Date.parse("2026-01-15T12:00:00Z");
const during = Date.parse("2025-12-08T12:00:00Z");
const region = () => screen.queryByRole("region", { name: "Route replay" });
const reduced = () => vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() }));

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockResolvedValue(places as never);
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: false, media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("RouteReplay", () => {
  it("shows the route inline for a trip that has ended and has two located stops, and plays it once", async () => {
    render(RouteReplay, { trip: trip([there, home]), now: after });
    expect(await screen.findByRole("region", { name: "Route replay" })).toBeTruthy();
    expect(vi.mocked(api)).toHaveBeenCalledWith("/api/trips/1/places");
    expect(await screen.findByRole("button", { name: "Pause" })).toBeTruthy();
    expect(screen.getByRole("slider", { name: "Position along the route" })).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    const items = within(screen.getByRole("list", { name: "Stops in order" })).getAllByRole("listitem").map((li) => li.textContent);
    expect(items[0]).toContain("Minneapolis (MSP), Dec 5, 2025");
    expect(items.at(-1)).toContain("Back in Minneapolis (MSP), Dec 11, 2025");
  });

  it("with reduced motion shows the whole route and the list, with nothing playing", async () => {
    reduced();
    render(RouteReplay, { trip: trip([there, home]), now: after });
    expect(await screen.findByRole("region", { name: "Route replay" })).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByRole("list", { name: "Stops in order" })).toBeTruthy();
  });

  it("is absent for a trip still going and does not ask for coordinates", async () => {
    render(RouteReplay, { trip: trip([there, home]), now: during });
    await Promise.resolve();
    expect(region()).toBeNull();
    expect(vi.mocked(api)).not.toHaveBeenCalled();
  });

  it("is absent for a trip that has not started", () => {
    render(RouteReplay, { trip: trip([there, home]), now: Date.parse("2025-11-01T12:00:00Z") });
    expect(region()).toBeNull();
    expect(vi.mocked(api)).not.toHaveBeenCalled();
  });

  it("is absent when fewer than two stops have coordinates", async () => {
    vi.mocked(api).mockResolvedValue({ airports: [places.airports[0]], cities: [], stays: [] } as never);
    render(RouteReplay, { trip: trip([there, home]), now: after });
    await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalled());
    await Promise.resolve();
    expect(region()).toBeNull();
  });

  it("is absent for a single stay, without asking", () => {
    const stay = segment({ id: 3, kind: "hotel", origin: "Inn", destination: "San Francisco", start_local: "2025-12-05T15:00", start_zone: "America/Los_Angeles", end_local: "2025-12-08T11:00", end_zone: "America/Los_Angeles" });
    render(RouteReplay, { trip: trip([stay]), now: after });
    expect(region()).toBeNull();
    expect(vi.mocked(api)).not.toHaveBeenCalled();
  });

  it("is absent when the coordinates can't be loaded or come back malformed", async () => {
    vi.mocked(api).mockRejectedValue(new Error("down"));
    const first = render(RouteReplay, { trip: trip([there, home]), now: after });
    await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalled());
    await Promise.resolve();
    expect(region()).toBeNull();
    first.unmount();
    vi.mocked(api).mockResolvedValue({ id: 1, name: "x", segments: [] } as never);
    render(RouteReplay, { trip: trip([there, home]), now: after });
    await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalledTimes(2));
    await Promise.resolve();
    expect(region()).toBeNull();
  });
});
