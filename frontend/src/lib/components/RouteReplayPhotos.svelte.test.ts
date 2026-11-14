// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("$lib/map", async (original) => ({ ...(await original<typeof import("$lib/map")>()), loadCountries: async () => [], loadDetailedCountries: async () => [], loadFineCountries: async () => [] }));

import { api } from "$lib/api";
import type { PhotoCluster, TripPhoto, TripPhotos, TripPlaces } from "$lib/api-types";
import { segment, trip } from "../../test/fixtures";
import RouteReplay from "./RouteReplay.svelte";

const places: TripPlaces = {
  home: null,
  airports: [
    { code: "MSP", city: "Minneapolis", latitude: 44.8848, longitude: -93.2223 },
    { code: "SFO", city: "San Francisco", latitude: 37.6213, longitude: -122.379 },
  ],
  cities: [],
  stays: [],
  roads: { legs: [], interstates: [] },
  boundaries: [],
};
const there = segment({ id: 1, origin: "MSP", destination: "SFO", start_local: "2025-12-05T08:00", start_zone: "America/Chicago", end_local: "2025-12-05T10:30", end_zone: "America/Los_Angeles" });
const home = segment({ id: 2, origin: "SFO", destination: "MSP", start_local: "2025-12-11T13:00", start_zone: "America/Los_Angeles", end_local: "2025-12-11T18:50", end_zone: "America/Chicago" });
const after = Date.parse("2026-01-15T12:00:00Z");
const during = Date.parse("2025-12-08T12:00:00Z");

const cluster: PhotoCluster = { latitude: 37.8, longitude: -122.4, count: 2, first: "2025-12-07T10:00", last: "2025-12-07T12:00", cover: 1, inferred: false };
const shot = (id: number, extra: Partial<TripPhoto> = {}): TripPhoto => ({
  id, person_id: 1, trip_id: 1, kind: "image", taken_local: "2025-12-07T10:00", zone: "America/Los_Angeles", latitude: 37.8, longitude: -122.4, location_source: "exif",
  segment_id: 2, match: "place", distance_km: 2, cluster: 0, removed_at: null, ...extra,
});
const reply = (clusters: PhotoCluster[], photos: TripPhoto[] = [shot(1), shot(2)]): TripPhotos => ({ photos, clusters, counts: { total: photos.length, located: photos.length, inferred: 0, far: 0 }, people: [] });
const pin = () => screen.queryByRole("button", { name: /^2 photos/ });

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockResolvedValue(places as never);
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("RouteReplay with photos", () => {
  it("adds the pins to the route of a trip that has ended, in the same section", async () => {
    render(RouteReplay, { trip: trip([there, home]), now: after, photos: reply([cluster]) });
    const region = await screen.findByRole("region", { name: "Route replay" });
    await waitFor(() => expect(region.querySelectorAll("[data-pin]")).toHaveLength(1));
    expect(screen.getByRole("list", { name: "Stops in order" })).toBeTruthy();
  });

  it("shows a map of just the pins for a trip with photos and no route, with no places request and no controls", async () => {
    render(RouteReplay, { trip: trip([], { id: 4 }), now: after, photos: reply([cluster]) });
    const region = await screen.findByRole("region", { name: "Trip photo map" });
    expect(region.querySelectorAll("[data-pin]")).toHaveLength(1);
    expect(screen.queryByRole("region", { name: "Route replay" })).toBeNull();
    expect(screen.queryByRole("slider")).toBeNull();
    expect(screen.queryByRole("button", { name: "Play" })).toBeNull();
    expect(vi.mocked(api)).not.toHaveBeenCalled();
  });

  it("shows the pins alone for a trip still going, which has no route replay yet", async () => {
    render(RouteReplay, { trip: trip([there, home]), now: during, photos: reply([cluster]) });
    expect(await screen.findByRole("region", { name: "Trip photo map" })).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Stops in order" })).toBeNull();
    expect(vi.mocked(api)).not.toHaveBeenCalled();
  });

  it("waits for the stops before drawing, so the pins-only map never flashes before the route", async () => {
    let answer: (found: TripPlaces) => void = () => {};
    vi.mocked(api).mockReturnValue(new Promise((resolve) => { answer = resolve as never; }));
    render(RouteReplay, { trip: trip([there, home]), now: after, photos: reply([cluster]) });
    await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalled());
    expect(screen.queryByRole("region")).toBeNull();
    answer(places);
    expect(await screen.findByRole("region", { name: "Route replay" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Trip photo map" })).toBeNull();
  });

  it("falls back to the pins alone when the stops can't be placed or the request fails", async () => {
    vi.mocked(api).mockRejectedValue(new Error("down"));
    render(RouteReplay, { trip: trip([there, home]), now: after, photos: reply([cluster]) });
    expect(await screen.findByRole("region", { name: "Trip photo map" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: /^2 photos/ })).toBeTruthy();
  });

  it("draws nothing for photos with no cluster, and nothing before the photos have loaded", async () => {
    const { rerender } = render(RouteReplay, { trip: trip([], { id: 4 }), now: after, photos: null });
    expect(screen.queryByRole("region")).toBeNull();
    await rerender({ photos: reply([], [shot(1, { cluster: null, latitude: null, longitude: null })]) });
    expect(screen.queryByRole("region")).toBeNull();
    await rerender({ photos: reply([cluster]) });
    expect(await screen.findByRole("region", { name: "Trip photo map" })).toBeTruthy();
    expect(pin()).toBeTruthy();
  });

  it("drops the pins, and a map with no route, when the next read of the reply has no clusters", async () => {
    const { rerender } = render(RouteReplay, { trip: trip([], { id: 4 }), now: after, photos: reply([cluster]) });
    expect(await screen.findByRole("region", { name: "Trip photo map" })).toBeTruthy();
    await rerender({ photos: reply([], []) });
    expect(screen.queryByRole("region")).toBeNull();
  });

  it("is the same page as a trip with no photos when the viewer can see none, for a trip with a route", async () => {
    const plain = render(RouteReplay, { trip: trip([there, home]), now: after });
    await screen.findByRole("region", { name: "Route replay" });
    const before = plain.container.innerHTML;
    plain.unmount();
    const none = render(RouteReplay, { trip: trip([there, home]), now: after, photos: reply([], []) });
    await screen.findByRole("region", { name: "Route replay" });
    expect(none.container.innerHTML).toBe(before);
  });

  it("with reduced motion shows every pin lit", async () => {
    render(RouteReplay, { trip: trip([there, home]), now: after, photos: reply([cluster]) });
    const region = await screen.findByRole("region", { name: "Route replay" });
    await waitFor(() => expect(region.querySelector("[data-pin]")).toBeTruthy());
    expect(region.querySelector<HTMLElement>("[data-pin]")!.dataset.lit).toBe("true");
  });
});
