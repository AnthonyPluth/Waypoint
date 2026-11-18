// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));

import { api } from "$lib/api";
import type { TripPlaces } from "$lib/api-types";
import { app } from "$lib/app.svelte";
import { segment, state, trip } from "../../test/fixtures";
import PastTripCard from "./PastTripCard.svelte";

const TODAY = "2026-10-05";
const DENVER = { latitude: 39.74, longitude: -104.99 };
const SALT_LAKE = { latitude: 40.76, longitude: -111.89 };

const places = (more: Partial<TripPlaces> = {}): TripPlaces => ({
  home: null, airports: [], cities: [], stays: [{ segment_id: 1, ...DENVER, precision: "city" }, { segment_id: 2, ...SALT_LAKE, precision: "city" }],
  ...more,
});
const stay = (id: number, tripId: number, name: string, start: string, end: string) => segment({ id, trip_id: tripId, kind: "hotel", origin: name, destination: name, start_local: start, end_local: end });
const driven = (id = 9) => trip([stay(id * 10 + 1, id, "Denver", "2026-09-03T15:00", "2026-09-05T10:00"), stay(id * 10 + 2, id, "Salt Lake City", "2026-09-05T15:00", "2026-09-08T10:00")], { id, name: `Road trip ${id}`, start_date: "2026-09-03", end_date: "2026-09-08" });

const answer = (stays = places().stays, airports: TripPlaces["airports"] = []) => vi.mocked(api).mockImplementation(async (path) => {
  if (String(path).endsWith("/places")) return places({ stays, airports }) as never;
  throw new Error("down");
});
const asked = (prefix: string) => vi.mocked(api).mock.calls.filter(([path]) => String(path).startsWith(prefix));
const legs = (container: HTMLElement) => [...container.querySelectorAll("svg g[fill='none'] path")].map((p) => p.getAttribute("d") ?? "");
const numbers = (d: string) => (d.match(/-?\d+\.\d/g) ?? []).map(Number);

beforeEach(() => { vi.mocked(api).mockReset(); });
afterEach(() => { app.state = null; });

describe("the route on a Past trips card with no photos", () => {
  it("draws a drive as a straight line between its stops, inside the tile", async () => {
    answer(places().stays.map((s, i) => ({ ...s, segment_id: 91 + i })));
    const { container } = render(PastTripCard, { trip: driven(9), today: TODAY });
    await waitFor(() => expect(legs(container)).toHaveLength(1));
    const [x1, y1, cx, cy, x2, y2] = numbers(legs(container)[0]);
    expect(cx).toBeCloseTo((x1 + x2) / 2, 0);
    expect(cy).toBeCloseTo((y1 + y2) / 2, 0);
    for (const v of [x1, x2]) { expect(v).toBeGreaterThanOrEqual(0); expect(v).toBeLessThanOrEqual(400); }
    for (const v of [y1, y2]) { expect(v).toBeGreaterThanOrEqual(0); expect(v).toBeLessThanOrEqual(200); }
  });

  it("draws a flight as its arc, and never asks the server for roads or MapKit for anything", async () => {
    app.state = state({ mapkit: true });
    const flown = trip([segment({ id: 1, trip_id: 8, kind: "flight", origin: "JFK", destination: "LHR", start_local: "2026-09-03T19:00", end_local: "2026-09-04T07:00" })], { id: 8, name: "Out and back", start_date: "2026-09-03", end_date: "2026-09-10" });
    answer([], [{ code: "JFK", city: "New York", latitude: 40.64, longitude: -73.78 }, { code: "LHR", city: "London", latitude: 51.47, longitude: -0.45 }]);
    const { container } = render(PastTripCard, { trip: flown, today: TODAY });
    await waitFor(() => expect(container.querySelector("svg path.stroke-map-route")).not.toBeNull());
    await new Promise((r) => setTimeout(r, 80));
    expect(asked("/api/driving-routes")).toHaveLength(0);
    expect(asked("/api/mapkit")).toHaveLength(0);
    expect(screen.getAllByTestId("route-tile")).toHaveLength(1);
  });

  it("looks up each card's places and nothing else, with MapKit on or off", async () => {
    for (const mapkit of [true, false]) {
      app.state = state({ mapkit });
      vi.mocked(api).mockClear();
      answer(places().stays.map((s, i) => ({ ...s, segment_id: 91 + i })));
      const { container, unmount } = render(PastTripCard, { trip: driven(9), today: TODAY });
      await waitFor(() => expect(legs(container)).toHaveLength(1));
      await new Promise((r) => setTimeout(r, 60));
      expect(vi.mocked(api).mock.calls.map(([path]) => String(path))).toEqual(["/api/trips/9/places"]);
      unmount();
    }
  });
});
