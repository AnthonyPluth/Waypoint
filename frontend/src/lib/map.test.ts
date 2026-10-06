import { geoContains } from "d3-geo";
import { describe, expect, it } from "vitest";
import type { StatsAirport, StatsFlights, StatsRoute, StatsStayPin } from "./api-types";
import { arcs, clampPan, dots, fitBox, flownBounds, IDENTITY, loadStates, MAP_HEIGHT, MAP_WIDTH, mapData, pieces, pins, visitedFeatureIds, visitedPoints, worldProjection, zoomAt } from "./map";

const airport = (code: string, visits: number, latitude: number | null, longitude: number | null, city: string | null = null): StatsAirport =>
  ({ code, name: code, city, country: "XX", visits, latitude, longitude });
const route = (a: StatsRoute["a"], b: string, flights: number, from: [number, number] | null, to: [number, number] | null): StatsRoute => ({
  a, b, flights, distance_km: 1, a_latitude: from?.[0] ?? null, a_longitude: from?.[1] ?? null, b_latitude: to?.[0] ?? null, b_longitude: to?.[1] ?? null, trips: [],
});
const flights = (airports: StatsAirport[], routes: StatsRoute[]): StatsFlights => ({ airports, routes } as StatsFlights);

const LAX: [number, number] = [33.9425, -118.4081];
const NRT: [number, number] = [35.772, 140.3929];
const JFK: [number, number] = [40.6398, -73.7789];
const projection = worldProjection();

describe("the map's arcs and dots", () => {
  it("draws a trans-Pacific route as pieces at the edges, with no stripe across the map", () => {
    const [arc] = arcs([route("LAX", "NRT", 2, LAX, NRT)], projection);
    const parts = pieces(arc.d);
    expect(parts.length).toBeGreaterThan(1);
    for (const part of parts) {
      const xs = [...part.matchAll(/[ML,]?(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/g)].map((m) => Number(m[1]));
      expect(Math.max(...xs) - Math.min(...xs)).toBeLessThan(MAP_WIDTH * 0.5);
    }
  });

  it("draws a route that stays on one side as a single piece", () => {
    const [arc] = arcs([route("JFK", "LAX", 1, JFK, LAX)], projection);
    expect(pieces(arc.d)).toHaveLength(1);
  });

  it("draws the most flown route thickest and on top, and leaves out a route with an unknown end", () => {
    const out = arcs([route("JFK", "LAX", 1, JFK, LAX), route("LAX", "NRT", 4, LAX, NRT), route("JFK", "ZZZ", 3, JFK, null)], projection);
    expect(out.map((a) => a.key)).toEqual(["JFK-LAX", "LAX-NRT"]);
    expect(out[1].width).toBeGreaterThan(out[0].width);
    expect(out[1].width).toBe(4);
    expect(out[1].label).toBe("LAX – NRT: 4 flights");
    expect(out[0].label).toBe("JFK – LAX: 1 flight");
  });

  it("sizes an airport visited many times above one visited once, and names them", () => {
    const out = dots([airport("JFK", 40, ...JFK, "New York"), airport("LAX", 1, ...LAX, "Los Angeles")], projection);
    expect(out.map((d) => d.code)).toEqual(["JFK", "LAX"]);
    expect(out[0].r).toBeCloseTo(9);
    expect(out[1].r).toBeGreaterThan(3);
    expect(out[1].r).toBeLessThan(out[0].r);
    expect(out[0].label).toBe("JFK · New York: 40 visits");
    expect(out[1].label).toBe("LAX · Los Angeles: 1 visit");
  });

  it("draws the one airport an itinerary visits many times as one dot, and leaves out an airport with no coordinates", () => {
    const out = dots([airport("ORD", 12, 41.9742, -87.9073), airport("XYZ", 3, null, null)], projection);
    expect(out).toHaveLength(1);
    expect(out[0].visits).toBe(12);
    expect(out[0].x).toBeGreaterThan(0);
    expect(out[0].x).toBeLessThan(MAP_WIDTH);
    expect(out[0].y).toBeLessThan(MAP_HEIGHT);
  });

  it("draws nothing for no routes at all", () => {
    expect(mapData(flights([], []), projection)).toEqual({ dots: [], arcs: [] });
  });
});

describe("zoom and pan", () => {
  it("zooms around a point and keeps the world covering the map", () => {
    const t = zoomAt(IDENTITY, 2, 0, 0);
    expect(t).toEqual({ k: 2, x: 0, y: 0 });
    const mid = zoomAt(IDENTITY, 2, MAP_WIDTH / 2, MAP_HEIGHT / 2);
    expect(mid.x).toBe(-MAP_WIDTH / 2);
    expect(zoomAt(IDENTITY, 0.5, 100, 100)).toEqual(IDENTITY);
    expect(zoomAt(IDENTITY, 100, 0, 0).k).toBe(8);
  });

  it("won't drag the world off the screen", () => {
    expect(clampPan({ k: 2, x: 500, y: 500 })).toEqual({ k: 2, x: 0, y: 0 });
    expect(clampPan({ k: 2, x: -5000, y: -5000 })).toEqual({ k: 2, x: -MAP_WIDTH, y: -MAP_HEIGHT });
  });
});

describe("visited countries", () => {
  it("shades the countries that hold an airport, once each", () => {
    const features = [{ id: "840" }, { id: "392" }, { id: "250" }];
    const contains = (f: { id: string }, [lon]: [number, number]) => (f.id === "840" ? lon < 0 : f.id === "392" && lon > 100);
    const ids = visitedFeatureIds(visitedPoints([airport("JFK", 1, ...JFK), airport("LAX", 1, ...LAX), airport("NRT", 1, ...NRT), airport("XYZ", 1, null, null)], []), features, contains);
    expect([...ids].sort()).toEqual(["392", "840"]);
  });
});

describe("framing what was flown", () => {
  const at = (code: string, latitude: number | null, longitude: number | null, visits = 1): StatsAirport => ({ code, name: code, city: null, country: null, visits, latitude, longitude });
  const route = (a: StatsAirport, b: StatsAirport): StatsRoute => ({ a: a.code, b: b.code, flights: 1, distance_km: 1, a_latitude: a.latitude, a_longitude: a.longitude, b_latitude: b.latitude, b_longitude: b.longitude, trips: [] });
  const only = (airports: StatsAirport[], routes: StatsRoute[] = []) => ({ airports, routes }) as unknown as StatsFlights;
  const hnl = at("HNL", 21.32, -157.92), lih = at("LIH", 21.98, -159.34), ogg = at("OGG", 20.9, -156.43);
  const jfk = at("JFK", 40.64, -73.78), nrt = at("NRT", 35.77, 140.39);

  it("zooms in on a region and centres it, never closer than the limit", () => {
    const hawaii = { airports: [hnl, lih, ogg], routes: [route(hnl, lih), route(hnl, ogg)] } as StatsFlights;
    const t = fitBox(flownBounds(hawaii, worldProjection()));
    expect(t.k).toBeGreaterThan(3);
    expect(t.k).toBeLessThanOrEqual(8);
    const p = worldProjection()([-157.9, 21.3])!;
    const [x, y] = [t.x + t.k * p[0], t.y + t.k * p[1]];
    expect(x).toBeGreaterThan(MAP_WIDTH * 0.25);
    expect(x).toBeLessThan(MAP_WIDTH * 0.75);
    expect(y).toBeGreaterThan(MAP_HEIGHT * 0.25);
    expect(y).toBeLessThan(MAP_HEIGHT * 0.75);
  });

  it("shows the whole world when the flights span it, or when there are none, and does not zoom to a lone airport's point", () => {
    expect(fitBox(flownBounds({ airports: [jfk, nrt], routes: [route(jfk, nrt)] } as StatsFlights, worldProjection()))).toEqual(IDENTITY);
    expect(fitBox(flownBounds(only([]), worldProjection()))).toEqual(IDENTITY);
    expect(flownBounds(only([at("ZZZ", null, null)]), worldProjection())).toBeNull();
    const lone = fitBox(flownBounds(only([hnl]), worldProjection()));
    expect(lone.k).toBeGreaterThan(1);
    expect(lone.k).toBeLessThan(8);
  });

  it("keeps the framed map covering its box", () => {
    const t = fitBox(flownBounds({ airports: [hnl, lih], routes: [route(hnl, lih)] } as StatsFlights, worldProjection()));
    expect(clampPan(t)).toEqual(t);
  });
});

const stay = (city: string, latitude: number, longitude: number, nights = 3): StatsStayPin =>
  ({ city, country: "XX", latitude, longitude, stays: 1, nights, trips: [{ trip_id: 4, name: "Trip to " + city, start: "2026-06-02", end: "2026-06-05" }] });
const LONDON: [number, number] = [51.47, -0.45];

describe("where you stayed", () => {
  it("puts a pin at each city, labelled with its stays and nights, and carries its trips", () => {
    const [pin] = pins([stay("London", ...LONDON, 6)], projection);
    expect(pin.label).toBe("London: 1 stay, 6 nights");
    expect(pin.trips).toEqual([{ trip_id: 4, name: "Trip to London", start: "2026-06-02", end: "2026-06-05" }]);
    expect(pin.x).toBeGreaterThan(0);
  });

  it("counts a stay's city among the places you've been, beside the airports", () => {
    expect(visitedPoints([airport("JFK", 1, ...JFK), airport("XYZ", 1, null, null)], [stay("London", ...LONDON)])).toEqual([[JFK[1], JFK[0]], [LONDON[1], LONDON[0]]]);
  });

  it("frames the stays too, and a trip with only stays", () => {
    const only = { airports: [], routes: [] } as unknown as StatsFlights;
    expect(flownBounds(only, projection)).toBeNull();
    expect(flownBounds(only, projection, [stay("London", ...LONDON)])).not.toBeNull();
  });
});

describe("the US states", () => {
  it("finds the state a place is in, from the bundled outlines", async () => {
    const states = await loadStates();
    expect(states.length).toBeGreaterThanOrEqual(51);
    const hnl: [number, number] = [-157.92, 21.32], jfk: [number, number] = [JFK[1], JFK[0]];
    const ids = visitedFeatureIds([hnl, jfk, [-0.45, 51.47]], states, (f, p) => geoContains(f, p));
    expect([...ids].map((id) => states.find((x) => x.id === id)?.properties?.name).sort()).toEqual(["Hawaii", "New York"]);
  });
});
