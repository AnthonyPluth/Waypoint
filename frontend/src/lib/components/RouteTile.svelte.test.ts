// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("$lib/mapkit", () => ({ loadMapkit: vi.fn() }));

import { api } from "$lib/api";
import type { TripPlaces } from "$lib/api-types";
import { app } from "$lib/app.svelte";
import { clearRouteCache } from "$lib/driving-routes";
import { loadMapkit } from "$lib/mapkit";
import { segment, state, trip } from "../../test/fixtures";
import PastTripCard from "./PastTripCard.svelte";

const TODAY = "2026-10-05";
const DENVER = { latitude: 39.74, longitude: -104.99 };
const SALT_LAKE = { latitude: 40.76, longitude: -111.89 };
const road = [[39.74, -104.99], [40.2, -105.0], [41.9, -107.5], [41.5, -110.0], [40.76, -111.89]];

const places = (more: Partial<TripPlaces> = {}): TripPlaces => ({
  home: null, airports: [], cities: [], stays: [{ segment_id: 1, ...DENVER, precision: "city" }, { segment_id: 2, ...SALT_LAKE, precision: "city" }],
  roads: { legs: [], interstates: [] }, boundaries: [], ...more,
});
const stay = (id: number, tripId: number, name: string, start: string, end: string) => segment({ id, trip_id: tripId, kind: "hotel", origin: name, destination: name, start_local: start, end_local: end });
const driven = (id = 9) => trip([stay(id * 10 + 1, id, "Denver", "2026-09-03T15:00", "2026-09-05T10:00"), stay(id * 10 + 2, id, "Salt Lake City", "2026-09-05T15:00", "2026-09-08T10:00")], { id, name: `Road trip ${id}`, start_date: "2026-09-03", end_date: "2026-09-08" });

const saved = (id: number, path = road) => ({ trip_id: id, routes: [{ start: DENVER, end: SALT_LAKE, path }] });
const answer = (id: number, routes: unknown, stays = places().stays.map((s, i) => ({ ...s, segment_id: id * 10 + 1 + i }))) => vi.mocked(api).mockImplementation(async (path) => {
  const url = String(path);
  if (url.endsWith("/places")) return places({ stays }) as never;
  if (url.startsWith("/api/driving-routes")) return routes as never;
  throw new Error("down");
});
const asked = (prefix: string) => vi.mocked(api).mock.calls.filter(([path]) => String(path).startsWith(prefix));
const legs = (container: HTMLElement) => [...container.querySelectorAll("svg g[fill='none'] path")].map((p) => p.getAttribute("d") ?? "");
const numbers = (d: string) => (d.match(/-?\d+\.\d/g) ?? []).map(Number);

beforeEach(() => { vi.mocked(api).mockReset(); vi.mocked(loadMapkit).mockReset(); clearRouteCache(); });
afterEach(() => { vi.useRealTimers(); app.state = null; });

describe("the route on a Past trips card with no photos", () => {
  it("follows the saved road for a drive, inside the tile, where it used to be an arc", async () => {
    answer(9, { trips: [saved(9)] });
    const { container } = render(PastTripCard, { trip: driven(), today: TODAY });
    await waitFor(() => expect(legs(container)[0]).not.toContain("Q"));
    const [d] = legs(container);
    expect(d.match(/L/g)).toHaveLength(road.length + 1);
    const [x, y] = [numbers(d).filter((_, i) => i % 2 === 0), numbers(d).filter((_, i) => i % 2 === 1)];
    expect(Math.min(...x)).toBeGreaterThanOrEqual(0);
    expect(Math.max(...x)).toBeLessThanOrEqual(400);
    expect(Math.min(...y)).toBeGreaterThanOrEqual(0);
    expect(Math.max(...y)).toBeLessThanOrEqual(200);
  });

  it("fits the tile to a road that bulges well past the straight line between the stops", async () => {
    const wide = [[39.74, -104.99], [47.0, -108.0], [47.0, -111.0], [40.76, -111.89]];
    answer(9, { trips: [saved(9, wide)] });
    const { container } = render(PastTripCard, { trip: driven(), today: TODAY });
    await waitFor(() => expect(legs(container)[0]).not.toContain("Q"));
    const ys = numbers(legs(container)[0]).filter((_, i) => i % 2 === 1);
    expect(Math.min(...ys)).toBeGreaterThanOrEqual(44 - 1);
    expect(Math.max(...ys)).toBeLessThanOrEqual(200 - 44 + 1);
  });

  it("keeps the arc when the trip has no saved route, when the lookup fails and when it answers nonsense", async () => {
    for (const reply of [{ trips: [] }, { trips: [{ trip_id: 9, routes: [{ start: DENVER, end: SALT_LAKE, path: [[1, 2]] }] }] }, { nope: true }, null]) {
      clearRouteCache();
      answer(9, reply);
      const { container, unmount } = render(PastTripCard, { trip: driven(), today: TODAY });
      await waitFor(() => expect(asked("/api/driving-routes")).toHaveLength(1));
      await waitFor(() => expect(legs(container)).toHaveLength(1));
      await new Promise((r) => setTimeout(r, 20));
      expect(legs(container)[0]).toContain("Q");
      unmount();
      vi.mocked(api).mockClear();
    }
    clearRouteCache();
    vi.mocked(api).mockImplementation(async (path) => { if (String(path).endsWith("/places")) return places({ stays: places().stays.map((s, i) => ({ ...s, segment_id: 91 + i })) }) as never; throw new Error("down"); });
    const { container } = render(PastTripCard, { trip: driven(), today: TODAY });
    await waitFor(() => expect(asked("/api/driving-routes")).toHaveLength(1));
    await new Promise((r) => setTimeout(r, 20));
    expect(legs(container)[0]).toContain("Q");
  });

  it("draws a flight as its arc and a drive as its road on the same card", async () => {
    const mixed = trip([
      stay(91, 9, "Denver", "2026-09-03T15:00", "2026-09-05T10:00"), stay(92, 9, "Salt Lake City", "2026-09-05T15:00", "2026-09-06T10:00"),
      segment({ id: 93, trip_id: 9, kind: "flight", origin: "SLC", destination: "LHR", start_local: "2026-09-06T12:00", end_local: "2026-09-07T06:00" }),
    ], { id: 9, name: "Mixed", start_date: "2026-09-03", end_date: "2026-09-08" });
    vi.mocked(api).mockImplementation(async (path) => {
      const url = String(path);
      if (url.endsWith("/places")) return places({ stays: [{ segment_id: 91, ...DENVER, precision: "city" }, { segment_id: 92, ...SALT_LAKE, precision: "city" }], airports: [{ code: "SLC", city: "Salt Lake City", latitude: 40.79, longitude: -111.98 }, { code: "LHR", city: "London", latitude: 51.47, longitude: -0.45 }] }) as never;
      if (url.startsWith("/api/driving-routes")) return { trips: [saved(9)] } as never;
      throw new Error("down");
    });
    const { container } = render(PastTripCard, { trip: mixed, today: TODAY });
    await waitFor(() => expect(legs(container).some((d) => !d.includes("Q"))).toBe(true));
    const flight = container.querySelector("svg path.stroke-map-route")!;
    expect(flight.getAttribute("d")).toContain("Q");
    const drive = legs(container)[0];
    expect(drive).not.toContain("Q");
    expect(drive.match(/L/g)?.length).toBeGreaterThan(2);
  });

  it("never asks MapKit, and never asks the server about a trip with no drive", async () => {
    answer(9, { trips: [saved(9)] });
    const flown = trip([segment({ id: 1, trip_id: 8, kind: "flight", origin: "JFK", destination: "LHR", start_local: "2026-09-03T19:00", end_local: "2026-09-04T07:00" })], { id: 8, name: "Out and back", start_date: "2026-09-03", end_date: "2026-09-10" });
    vi.mocked(api).mockImplementation(async (path) => {
      if (String(path).endsWith("/places")) return places({ stays: [], airports: [{ code: "JFK", city: "New York", latitude: 40.64, longitude: -73.78 }, { code: "LHR", city: "London", latitude: 51.47, longitude: -0.45 }] }) as never;
      throw new Error("down");
    });
    const { container } = render(PastTripCard, { trip: flown, today: TODAY });
    await waitFor(() => expect(container.querySelector("svg path.stroke-map-route")).not.toBeNull());
    await new Promise((r) => setTimeout(r, 80));
    expect(asked("/api/driving-routes")).toHaveLength(0);
    expect(loadMapkit).not.toHaveBeenCalled();
    expect(asked("/api/mapkit")).toHaveLength(0);
  });

  it("asks the server for every card's routes in one request, not one per card", async () => {
    const ids = [11, 12, 13, 14, 15];
    vi.mocked(api).mockImplementation(async (path) => {
      const url = String(path);
      const id = Number(/trips\/(\d+)\/places/.exec(url)?.[1]);
      if (id) return places({ stays: places().stays.map((s, i) => ({ ...s, segment_id: id * 10 + 1 + i })) }) as never;
      if (url.startsWith("/api/driving-routes")) return { trips: ids.map((t) => saved(t)) } as never;
      throw new Error("down");
    });
    const views = ids.map((id) => render(PastTripCard, { trip: driven(id), today: TODAY }));
    await waitFor(() => expect(views.every((v) => legs(v.container).length === 1 && !legs(v.container)[0].includes("Q"))).toBe(true));
    expect(asked("/api/driving-routes")).toHaveLength(1);
    expect(asked("/api/driving-routes")[0][0]).toBe(`/api/driving-routes?${ids.map((t) => `trip=${t}`).join("&")}`);
    expect(asked("/api/trips/")).toHaveLength(ids.length);
    expect(screen.getAllByTestId("route-tile")).toHaveLength(ids.length);
  });

  it("draws arcs and reads nothing saved while MapKit is switched off, so turning it off stops the saved roads being used", async () => {
    app.state = state({ mapkit: false });
    answer(9, { trips: [saved(9)] });
    const { container } = render(PastTripCard, { trip: driven(), today: TODAY });
    await waitFor(() => expect(legs(container)).toHaveLength(1));
    await new Promise((r) => setTimeout(r, 80));
    expect(asked("/api/driving-routes")).toHaveLength(0);
    expect(legs(container)[0]).toContain("Q");
  });
});
