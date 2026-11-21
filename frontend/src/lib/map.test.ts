import { geoContains, geoMercator } from "d3-geo";
import { describe, expect, it } from "vitest";
import type { StatsAirport, StatsFlights, StatsPlacePoint, StatsRoute, StatsStayPin, StatsVisit } from "./api-types";
import { MAP_HEIGHT, MAP_WIDTH, worldProjection } from "./review-map";
import { arcs, clipToWindow, COARSE_FROM_KM, countrySources, detailFor, dots, flownBounds, greatCircle, kmPerPixel, loadCountries, loadDetailedCountries, loadStates, MEDIUM_FROM_KM, pins, splitAtAntimeridian, stateAt, stateSources, toOverlays, visitedFeatureIds, visitedPoints, visitedStateTrips, windowOf } from "./map";

const airport = (code: string, visits: number, latitude: number | null, longitude: number | null, city: string | null = null): StatsAirport =>
  ({ code, name: code, city, country: "XX", visits, latitude, longitude });
const route = (a: StatsRoute["a"], b: string, flights: number, from: [number, number] | null, to: [number, number] | null): StatsRoute => ({
  a, b, flights, distance_km: 1, a_latitude: from?.[0] ?? null, a_longitude: from?.[1] ?? null, b_latitude: to?.[0] ?? null, b_longitude: to?.[1] ?? null, trips: [],
});

const LAX: [number, number] = [33.9425, -118.4081];
const NRT: [number, number] = [35.772, 140.3929];
const JFK: [number, number] = [40.6398, -73.7789];

describe("the map's arcs and dots", () => {
  it("draws a great circle between the ends of a route, from one to the other", () => {
    const line = greatCircle([LAX[1], LAX[0]], [NRT[1], NRT[0]]);
    expect(line[0]).toEqual([LAX[1], LAX[0]]);
    expect(line[line.length - 1][0]).toBeCloseTo(NRT[1]);
    expect(line[line.length - 1][1]).toBeCloseTo(NRT[0]);
    expect(Math.max(...line.map((p) => p[1]))).toBeGreaterThan(NRT[0] + 5);
  });

  it("draws the most flown route thickest and on top, and leaves out a route with an unknown end", () => {
    const out = arcs([route("JFK", "LAX", 1, JFK, LAX), route("LAX", "NRT", 4, LAX, NRT), route("JFK", "ZZZ", 3, JFK, null)]);
    expect(out.map((a) => a.key)).toEqual(["JFK-LAX", "LAX-NRT"]);
    expect(out[1].width).toBeGreaterThan(out[0].width);
    expect(out[1].width).toBe(4);
    expect(out[1].label).toBe("LAX – NRT: 4 flights");
    expect(out[0].label).toBe("JFK – LAX: 1 flight");
    expect(out[1].from).toEqual([LAX[1], LAX[0]]);
    expect(out[1].to).toEqual([NRT[1], NRT[0]]);
  });

  it("sizes an airport visited many times above one visited once, and names them", () => {
    const out = dots([airport("JFK", 40, ...JFK, "New York"), airport("LAX", 1, ...LAX, "Los Angeles")]);
    expect(out.map((d) => d.code)).toEqual(["JFK", "LAX"]);
    expect(out[0].r).toBeCloseTo(9);
    expect(out[1].r).toBeGreaterThan(3);
    expect(out[1].r).toBeLessThan(out[0].r);
    expect(out[0].label).toBe("JFK · New York: 40 visits");
    expect(out[1].label).toBe("LAX · Los Angeles: 1 visit");
  });

  it("draws the one airport an itinerary visits many times as one dot, and leaves out an airport with no coordinates", () => {
    const out = dots([airport("ORD", 12, 41.9742, -87.9073), airport("XYZ", 3, null, null)]);
    expect(out).toHaveLength(1);
    expect(out[0].visits).toBe(12);
    expect([out[0].latitude, out[0].longitude]).toEqual([41.9742, -87.9073]);
  });

  it("draws nothing for no routes at all", () => {
    expect(dots([])).toEqual([]);
    expect(arcs([])).toEqual([]);
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

  it("boxes the places flown, as a latitude and longitude box", () => {
    const box = flownBounds({ airports: [hnl, lih, ogg], routes: [route(hnl, lih), route(hnl, ogg)] } as StatsFlights)!;
    expect(box.west).toBeCloseTo(-159.34);
    expect(box.east).toBeCloseTo(-156.43);
    expect(box.south).toBeLessThan(20.95);
    expect(box.north).toBeGreaterThan(21.9);
  });

  it("boxes nothing when there is nothing placed, and a lone airport as a point", () => {
    expect(flownBounds(only([]))).toBeNull();
    expect(flownBounds(only([at("ZZZ", null, null)]))).toBeNull();
    expect(flownBounds(only([hnl]))).toEqual({ west: -157.92, south: 21.32, east: -157.92, north: 21.32 });
  });

  it("boxes a route across the antimeridian the short way round", () => {
    const box = flownBounds(only([], [route(at("SYD", -33.9, 151.2), at("LAX", 33.9, -118.4))]))!;
    expect(box.west).toBeGreaterThan(box.east);
  });
});

const stay = (city: string, latitude: number, longitude: number, nights = 3): StatsStayPin =>
  ({ city, country: "XX", latitude, longitude, stays: 1, nights, trips: [{ trip_id: 4, name: "Trip to " + city, start: "2026-06-02", end: "2026-06-05" }] });
const LONDON: [number, number] = [51.47, -0.45];

describe("where you stayed", () => {
  it("puts a pin at each city, labelled with its stays and nights, and carries its trips", () => {
    const [pin] = pins([stay("London", ...LONDON, 6)]);
    expect(pin.label).toBe("London: 1 stay, 6 nights");
    expect(pin.trips).toEqual([{ trip_id: 4, name: "Trip to London", start: "2026-06-02", end: "2026-06-05" }]);
    expect([pin.latitude, pin.longitude]).toEqual(LONDON);
  });

  it("keeps two pins in one city apart, each with its own key", () => {
    const got = pins([stay("Boulder", 40.0251, -105.3487, 2), stay("Boulder", 40.0402, -105.2514, 1)]);
    expect(got.map((p) => p.label)).toEqual(["Boulder: 1 stay, 2 nights", "Boulder: 1 stay, 1 night"]);
    expect(new Set(got.map((p) => p.key)).size).toBe(2);
  });

  it("counts a stay's city among the places you've been, beside the airports", () => {
    expect(visitedPoints([airport("JFK", 1, ...JFK), airport("XYZ", 1, null, null)], [stay("London", ...LONDON)])).toEqual([[JFK[1], JFK[0]], [LONDON[1], LONDON[0]]]);
    expect(visitedPoints([], [], [{ latitude: NRT[0], longitude: NRT[1] }])).toEqual([[NRT[1], NRT[0]]]);
  });

  it("frames the stays too, and a trip with only stays", () => {
    const only = { airports: [], routes: [] } as unknown as StatsFlights;
    expect(flownBounds(only)).toBeNull();
    expect(flownBounds(only, [stay("London", ...LONDON)])).not.toBeNull();
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

  it("handles the Aleutian islands that cross the antimeridian, in the shape test and in the outline handed to MapKit", async () => {
    const states = await loadStates();
    const alaska = state("Alaska", ...states)!;
    expect(geoContains(alaska, [-176.64, 51.88])).toBe(true);
    expect(geoContains(alaska, [172.9, 52.9])).toBe(true);
    expect(stateAt([172.9, 52.9], states, (f, p) => geoContains(f, p))).toBe(alaska);
    const rings = toOverlays(alaska);
    expect(rings.length).toBeGreaterThan(1);
    const lons = rings.flatMap((ring) => ring.map((p) => p[0]));
    expect(Math.min(...lons)).toBeLessThan(-170);
    expect(Math.max(...lons)).toBeGreaterThan(170);
  });

  it("boxes an Alaska trip so it is on screen", () => {
    const at = (kind: string, lat: number, lon: number) => spot(kind, "x", lat, lon);
    const ports = flownBounds(none, [], [at("port", 58.3, -134.4), at("port", 59.46, -135.31)])!;
    expect([ports.west, ports.east]).toEqual([-135.31, -134.4]);
    expect([ports.south, ports.north]).toEqual([58.3, 59.46]);
    const past = flownBounds(none, [], [visit("AK")])!;
    expect([past.west, past.south]).toEqual([-149.9003, 61.2181]);
  });
});

describe("how much map detail a view needs", () => {
  const region = (west: number, south: number, east: number, north: number) =>
    geoMercator().fitExtent([[0, 0], [600, 400]], { type: "Polygon", coordinates: [[[west, south], [west, north], [east, north], [east, south], [west, south]]] });

  it("asks for the quick outlines at world scale, more across a continent and the most across a region", () => {
    expect(detailFor(kmPerPixel(worldProjection(), MAP_WIDTH, MAP_HEIGHT))).toBe("coarse");
    expect(detailFor(kmPerPixel(region(-125, 25, -65, 50), 600, 400))).toBe("fine");
    expect(detailFor(COARSE_FROM_KM)).toBe("coarse");
    expect(detailFor(COARSE_FROM_KM - 0.1)).toBe("medium");
    expect(detailFor(MEDIUM_FROM_KM)).toBe("medium");
    expect(detailFor(MEDIUM_FROM_KM - 0.1)).toBe("fine");
  });

  it("measures a pixel in kilometres, and says so when the centre is off the map", () => {
    expect(kmPerPixel(region(-80, 30, -70, 40), 600, 400)).toBeGreaterThan(1);
    expect(kmPerPixel(region(-80, 30, -70, 40), 600, 400)).toBeLessThan(4);
    expect(kmPerPixel({ invert: () => null } as never, 600, 400)).toBe(Infinity);
  });

  it("keeps only the outlines that reach the window", async () => {
    const countries = await loadCountries();
    const projection = region(-10, 35, 30, 60);
    const window = windowOf(projection, { x: 0, y: 0, w: 600, h: 400 });
    expect(window).not.toBeNull();
    const names = clipToWindow(countries, window).map((c) => c.properties?.name);
    expect(names).toContain("France");
    expect(names).toContain("Germany");
    expect(names).not.toContain("Brazil");
    expect(names).not.toContain("Australia");
    expect(clipToWindow(countries, null)).toHaveLength(countries.length);
  });

  it("drops the far islands of a country that is partly in the window", async () => {
    const detailed = await loadDetailedCountries();
    const window = windowOf(region(-10, 35, 30, 60), { x: 0, y: 0, w: 600, h: 400 });
    const france = (cs: typeof detailed) => cs.find((c) => c.properties?.name === "France")!.geometry;
    const whole = france(detailed);
    const clipped = france(clipToWindow(detailed, window));
    expect(whole.type).toBe("MultiPolygon");
    expect(clipped.type).toBe("MultiPolygon");
    expect((clipped as { coordinates: unknown[] }).coordinates.length).toBeLessThan((whole as { coordinates: unknown[] }).coordinates.length);
  });

  it("drops a polygon bigger than a hemisphere, which no country is, even when the window is null", () => {
    const real = { type: "Feature", id: "A", properties: { name: "Real" }, geometry: { type: "Polygon", coordinates: [[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]] } } as never;
    const wholeWorld = { type: "Polygon", coordinates: [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]] };
    const bogus = { type: "Feature", id: "B", properties: { name: "Bogus" }, geometry: { type: "MultiPolygon", coordinates: [wholeWorld.coordinates, [[[20, 0], [20, 10], [30, 10], [30, 0], [20, 0]]]] } } as never;
    expect(clipToWindow([real, bogus], null).map((c) => (c.geometry as { coordinates: unknown[] }).coordinates.length)).toEqual([1, 1]);
    const onlyBogus = { type: "Feature", id: "C", properties: { name: "Only" }, geometry: wholeWorld } as never;
    expect(clipToWindow([onlyBogus], null)).toEqual([]);
  });

  it("does not clip a window that spans the world, and the detailed sets keep every country", async () => {
    expect(windowOf(worldProjection(), { x: 0, y: 0, w: MAP_WIDTH, h: MAP_HEIGHT })).toBeNull();
    const [quick, medium] = await Promise.all([loadCountries(), loadDetailedCountries()]);
    const ids = (cs: typeof quick) => new Set(cs.map((c) => String(c.id)));
    expect([...ids(quick)].every((id) => ids(medium).has(id))).toBe(true);
  });
});

describe("what the map hands MapKit", () => {
  it("turns a polygon, with its holes, and a multipolygon into rings of longitude and latitude", () => {
    const ring = [[0, 0], [4, 0], [4, 4], [0, 0]];
    const hole = [[1, 1], [2, 1], [2, 2], [1, 1]];
    expect(toOverlays({ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [ring, hole] } })).toEqual([ring, hole]);
    expect(toOverlays({ type: "Feature", properties: {}, geometry: { type: "MultiPolygon", coordinates: [[ring], [hole]] } })).toEqual([ring, hole]);
    expect(toOverlays({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [0, 0] } })).toEqual([]);
  });

  it("splits a ring that jumps across the antimeridian so no edge spans the map", () => {
    const crossing: [number, number][] = [[170, 60], [180, 60], [-180, 60], [-170, 60], [-170, 70], [-180, 70], [180, 70], [170, 70], [170, 60]];
    const rings = splitAtAntimeridian(crossing);
    expect(rings).toHaveLength(2);
    for (const ring of rings) {
      expect(ring[0]).toEqual(ring[ring.length - 1]);
      for (let i = 1; i < ring.length; i++) expect(Math.abs(ring[i]![0] - ring[i - 1]![0])).toBeLessThan(180);
      expect(ring.every((p) => p[0] >= -180 && p[0] <= 180)).toBe(true);
    }
    const lons = rings.map((ring) => [Math.min(...ring.map((p) => p[0])), Math.max(...ring.map((p) => p[0]))]);
    expect(lons).toContainEqual([170, 180]);
    expect(lons).toContainEqual([-180, -170]);
  });

  it("splits a ring drawn past 180 degrees, and drops rings with no area", () => {
    const rings = splitAtAntimeridian([[175, 0], [185, 0], [185, 5], [175, 5], [175, 0]]);
    expect(rings).toHaveLength(2);
    expect(rings.every((ring) => ring.every((p) => p[0] >= -180 && p[0] <= 180))).toBe(true);
    expect(splitAtAntimeridian([[0, 0], [1, 1], [2, 2], [0, 0]])).toEqual([]);
    expect(splitAtAntimeridian([[0, 0], [1, 0]])).toEqual([]);
  });

  it("keeps a ring that runs along the pole, as Antarctica does, in one piece", () => {
    const ring: [number, number][] = [[-180, -85], [180, -85], [180, -90], [-180, -90], [-180, -85]];
    expect(splitAtAntimeridian(ring)).toEqual([ring]);
  });

  it("gives MapKit no full-width ring for the countries that cross 180 degrees", async () => {
    const countries = await loadDetailedCountries();
    for (const name of ["Russia", "Fiji"]) {
      const found = countries.find((c) => c.properties?.name === name)!;
      for (const ring of toOverlays(found)) {
        for (let i = 1; i < ring.length; i++) expect(Math.abs(ring[i]![0] - ring[i - 1]![0])).toBeLessThan(180);
      }
    }
  });

  it("lists the trips of each place that shades a country: the airport's routes, the stays and the past visits", () => {
    const trip = (id: number) => ({ trip_id: id, name: `Trip ${id}`, start: "2026-07-01", end: "2026-07-08" });
    const flown = { airports: [airport("JFK", 1, ...JFK), airport("XYZ", 1, null, null)], routes: [{ ...route("JFK", "LAX", 1, JFK, LAX), trips: [trip(1)] }] } as unknown as StatsFlights;
    const sources = countrySources(flown, [{ ...stay("London", ...LONDON), trips: [trip(2)] }], [{ country: "JP", state: null, latitude: NRT[0], longitude: NRT[1], trips: [trip(3)] }]);
    expect(sources.map((s) => [s.point, s.trips.map((x) => x.trip_id)])).toEqual([
      [[JFK[1], JFK[0]], [1]], [[LONDON[1], LONDON[0]], [2]], [[NRT[1], NRT[0]], [3]],
    ]);
  });
});
