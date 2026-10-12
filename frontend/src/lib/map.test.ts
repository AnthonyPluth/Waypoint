import { geoContains, geoPath } from "d3-geo";
import { describe, expect, it } from "vitest";
import type { StatsAirport, StatsFlights, StatsPlacePoint, StatsRoute, StatsStayPin, StatsVisit } from "./api-types";
import { arcs, clampPan, dots, fitBox, flownBounds, IDENTITY, loadStates, MAP_HEIGHT, MAP_WIDTH, mapData, pieces, pins, stateAt, stateSources, visitedFeatureIds, visitedPoints, visitedStateTrips, worldProjection, zoomAt } from "./map";

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

  it("keeps two pins in one city apart, each with its own key", () => {
    const got = pins([stay("Boulder", 40.0251, -105.3487, 2), stay("Boulder", 40.0402, -105.2514, 1)], projection);
    expect(got.map((p) => p.label)).toEqual(["Boulder: 1 stay, 2 nights", "Boulder: 1 stay, 1 night"]);
    expect(new Set(got.map((p) => p.key)).size).toBe(2);
  });

  it("counts a stay's city among the places you've been, beside the airports", () => {
    expect(visitedPoints([airport("JFK", 1, ...JFK), airport("XYZ", 1, null, null)], [stay("London", ...LONDON)])).toEqual([[JFK[1], JFK[0]], [LONDON[1], LONDON[0]]]);
    expect(visitedPoints([], [], [{ latitude: NRT[0], longitude: NRT[1] }])).toEqual([[NRT[1], NRT[0]]]);
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

describe("Alaska", () => {
  const trip = (id: number) => ({ trip_id: id, name: `Trip ${id}`, start: "2026-07-01", end: "2026-07-08" });
  const state = (name: string, ...rest: Awaited<ReturnType<typeof loadStates>>) => rest.find((x) => x.properties?.name === name);
  const shaded = async (sources: ReturnType<typeof stateSources>) => {
    const states = await loadStates();
    const found = visitedStateTrips(sources, states, (f, p) => geoContains(f, p));
    return { names: [...found.keys()].map((id) => states.find((x) => x.id === id)?.properties?.name).sort(), found, states };
  };
  const none = { airports: [], routes: [] } as unknown as StatsFlights;
  const spot = (kind: string, name: string, latitude: number, longitude: number): StatsPlacePoint => ({ kind, name, latitude, longitude, trips: [trip(3)] });
  const visit = (state: string | null, latitude = 61.2181, longitude = -149.9003): StatsVisit => ({ country: "US", state, latitude, longitude, trips: [trip(5)] });

  it("shades Alaska for an airport in each corner of it, even Ketchikan's, which the coarse outline puts just off shore", async () => {
    const states = await loadStates();
    const alaska = state("Alaska", ...states)!;
    expect(geoContains(alaska, [-131.7112, 55.3541])).toBe(false);
    for (const [code, lat, lon] of [["ANC", 61.1741, -149.9981], ["FAI", 64.8154, -147.8567], ["JNU", 58.3547, -134.5785], ["KTN", 55.3541, -131.7112], ["SIT", 57.0468, -135.3611]] as const) {
      const flown = { airports: [airport(code, 1, lat, lon)], routes: [] } as unknown as StatsFlights;
      expect((await shaded(stateSources(flown, [], [], []))).names, code).toEqual(["Alaska"]);
    }
  });

  it("shades Alaska for a hotel, a rental, a train, a port of call and a past trip with the state AK", async () => {
    for (const source of [
      { stays: [stay("Anchorage", 61.22, -149.8578)] }, { stays: [stay("Anchorage", 61.2181, -149.9003)] },
      { points: [spot("car", "Fairbanks", 64.8378, -147.7164)] }, { points: [spot("train", "Seward", 60.1042, -149.4422)] },
      { points: [spot("port", "Skagway", 59.4583, -135.3139)] }, { points: [spot("port", "Ketchikan", 55.3422, -131.6461)] },
      { visits: [visit("AK")] },
    ]) {
      const { stays = [], points = [], visits = [] } = source as { stays?: StatsStayPin[]; points?: StatsPlacePoint[]; visits?: StatsVisit[] };
      expect((await shaded(stateSources(none, stays, points, visits))).names).toEqual(["Alaska"]);
    }
  });

  it("shades no state for a US past trip without one, a country centroid, a point offshore or a cruise with nothing placed", async () => {
    expect((await shaded(stateSources(none, [], [], [visit(null, 39.05, -95.67)]))).names).toEqual([]);
    expect((await shaded(stateSources(none, [], [], [{ ...visit("AK"), country: "CA" }]))).names).toEqual([]);
    expect((await shaded(stateSources(none, [], [], []))).names).toEqual([]);
    expect((await shaded(stateSources(none, [], [spot("port", "Mid-Pacific", 30, -150)], []))).names).toEqual([]);
  });

  it("lists, for the shaded state, the trips of everything that shaded it, once each", async () => {
    const both = [spot("port", "Juneau", 58.3019, -134.4197), spot("port", "Skagway", 59.4583, -135.3139), { ...spot("car", "Fairbanks", 64.8378, -147.7164), trips: [trip(3), trip(9)] }];
    const { found, states } = await shaded(stateSources(none, [], both, [visit("AK")]));
    expect(found.get(state("Alaska", ...states)!.id!)?.map((t) => t.trip_id)).toEqual([3, 5, 9]);
  });

  it("handles the Aleutian islands that cross the antimeridian, in the shape test and in the drawn outline", async () => {
    const states = await loadStates();
    const alaska = state("Alaska", ...states)!;
    expect(geoContains(alaska, [-176.64, 51.88])).toBe(true);
    expect(geoContains(alaska, [172.9, 52.9])).toBe(true);
    expect(stateAt([172.9, 52.9], states, (f, p) => geoContains(f, p))).toBe(alaska);
    const parts = pieces(geoPath(worldProjection())(alaska) ?? "");
    expect(parts.length).toBeGreaterThan(1);
    const xs = parts.flatMap((part) => [...part.matchAll(/[ML,]?(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/g)].map((m) => Number(m[1])));
    expect(Math.min(...xs)).toBeLessThan(MAP_WIDTH * 0.2);
    expect(Math.max(...xs)).toBeGreaterThan(MAP_WIDTH * 0.8);
  });

  it("frames an Alaska trip so it is on screen, and for a trip that also has the lower 48 shows the world, which panning covers", () => {
    const at = (kind: string, lat: number, lon: number) => spot(kind, "x", lat, lon);
    for (const [more, visits] of [[[at("port", 58.3, -134.4), at("port", 59.46, -135.31)], []], [[], [visit("AK")]]] as const) {
      const box = flownBounds(none, worldProjection(), [], [...more, ...visits]);
      const t = fitBox(box);
      expect(t.k).toBeGreaterThan(1.2);
      const p = worldProjection()([-134.4, 58.3])!;
      const [x, y] = [t.x + t.k * p[0], t.y + t.k * p[1]];
      expect(x).toBeGreaterThan(0);
      expect(x).toBeLessThan(MAP_WIDTH);
      expect(y).toBeGreaterThan(0);
      expect(y).toBeLessThan(MAP_HEIGHT);
      expect(clampPan(t)).toEqual(t);
    }
    const both = fitBox(flownBounds(flights([airport("SEA", 1, 47.45, -122.31), airport("ANC", 1, 61.17, -150)], []), worldProjection(), [stay("Miami", 25.76, -80.19)]));
    for (const [lat, lon] of [[47.45, -122.31], [61.17, -150], [25.76, -80.19]]) {
      const p = worldProjection()([lon, lat])!;
      const [x, y] = [both.x + both.k * p[0], both.y + both.k * p[1]];
      expect(x).toBeGreaterThan(0);
      expect(x).toBeLessThan(MAP_WIDTH);
      expect(y).toBeGreaterThan(0);
      expect(y).toBeLessThan(MAP_HEIGHT);
    }
    const alaska = worldProjection()([-150, 61.17])!;
    const farEast = clampPan({ k: 4, x: -1e6, y: 1e6 });
    const farWest = clampPan({ k: 4, x: 1e6, y: -1e6 });
    expect(farWest.x + 4 * alaska[0]).toBeGreaterThan(0);
    expect(farEast.x + 4 * alaska[0]).toBeLessThan(MAP_WIDTH);
  });
});
