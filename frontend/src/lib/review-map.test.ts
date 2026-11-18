import { describe, expect, it } from "vitest";
import type { StatsFlights, StatsRoute } from "./api-types";
import { MAP_WIDTH, mapData, worldProjection } from "./review-map";

const route = (a: string, b: string, flights: number, from: [number, number] | null, to: [number, number] | null): StatsRoute => ({
  a, b, flights, distance_km: 1, a_latitude: from?.[0] ?? null, a_longitude: from?.[1] ?? null, b_latitude: to?.[0] ?? null, b_longitude: to?.[1] ?? null, trips: [],
});
const LAX: [number, number] = [33.9425, -118.4081];
const NRT: [number, number] = [35.772, 140.3929];
const JFK: [number, number] = [40.6398, -73.7789];
const pieces = (d: string): string[] => d.split(/(?=M)/).filter(Boolean);
const projection = worldProjection();
const flown = (routes: StatsRoute[]) => ({ airports: [], routes }) as unknown as StatsFlights;

describe("the Year in Review card's map", () => {
  it("draws a trans-Pacific route as pieces at the edges, with no stripe across the map", () => {
    const [arc] = mapData(flown([route("LAX", "NRT", 2, LAX, NRT)]), projection).arcs;
    const parts = pieces(arc.d);
    expect(parts.length).toBeGreaterThan(1);
    for (const part of parts) {
      const xs = [...part.matchAll(/[ML,]?(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/g)].map((m) => Number(m[1]));
      expect(Math.max(...xs) - Math.min(...xs)).toBeLessThan(MAP_WIDTH * 0.5);
    }
  });

  it("draws a route that stays on one side as a single piece", () => {
    const [arc] = mapData(flown([route("JFK", "LAX", 1, JFK, LAX)]), projection).arcs;
    expect(pieces(arc.d)).toHaveLength(1);
  });

  it("draws the most flown route last and thickest, leaves out a route with an unknown end, and sizes the airports", () => {
    const data = mapData({
      airports: [{ code: "JFK", name: "JFK", city: null, country: "US", visits: 40, latitude: JFK[0], longitude: JFK[1] }, { code: "LAX", name: "LAX", city: null, country: "US", visits: 1, latitude: LAX[0], longitude: LAX[1] }, { code: "XYZ", name: "XYZ", city: null, country: null, visits: 3, latitude: null, longitude: null }],
      routes: [route("LAX", "NRT", 4, LAX, NRT), route("JFK", "LAX", 1, JFK, LAX), route("JFK", "ZZZ", 3, JFK, null)],
    } as unknown as StatsFlights, projection);
    expect(data.arcs.map((a) => a.flights)).toEqual([1, 4]);
    expect(data.arcs[1].width).toBe(4);
    expect(data.dots.map((d) => d.code)).toEqual(["JFK", "LAX"]);
    expect(data.dots[0].r).toBeCloseTo(9);
    expect(data.dots[1].r).toBeLessThan(data.dots[0].r);
  });

  it("draws nothing for no routes at all", () => {
    expect(mapData(flown([]), projection)).toEqual({ dots: [], arcs: [] });
  });
});
