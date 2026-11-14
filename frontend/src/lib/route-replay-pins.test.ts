import { geoEqualEarth } from "d3-geo";
import { describe, expect, it } from "vitest";
import type { PhotoCluster, TripPlaces } from "$lib/api-types";
import { segment, trip } from "../test/fixtures";
import { MIN_SPAN_DEGREES, pinFraction, pinLit, pinSize, pinsOf, positions, routeProjection, spreadPins, stopPosition, stopsOf } from "./route-replay";

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
const flights = [
  segment({ id: 1, origin: "MSP", destination: "SFO", start_local: "2025-12-05T08:00", start_zone: "America/Chicago", end_local: "2025-12-05T10:30", end_zone: "America/Los_Angeles" }),
  segment({ id: 2, origin: "SFO", destination: "MSP", start_local: "2025-12-11T13:00", start_zone: "America/Los_Angeles", end_local: "2025-12-11T18:50", end_zone: "America/Chicago" }),
];
const stops = stopsOf(trip(flights), places);

const cluster = (extra: Partial<PhotoCluster> = {}): PhotoCluster => ({ latitude: 37.8, longitude: -122.4, count: 12, first: "2025-12-07T10:00", last: "2025-12-08T18:00", cover: 5, inferred: false, ...extra });

describe("pinSize", () => {
  it("is 16 px for one photo and grows 4 px with each doubling", () => {
    expect([1, 2, 4, 8, 16].map(pinSize)).toEqual([16, 20, 24, 28, 32]);
  });

  it("stops at 40 px however many photos there are", () => {
    expect(pinSize(2 ** 6)).toBe(40);
    expect(pinSize(100_000)).toBe(40);
  });

  it("treats an empty or negative count as one photo", () => {
    expect([0, -3].map(pinSize)).toEqual([16, 16]);
  });
});

describe("pinsOf", () => {
  const clusters = [
    cluster({ latitude: 37.8, longitude: -122.4, count: 40, first: "2025-12-07T10:00" }),
    cluster({ latitude: 44.9, longitude: -93.2, count: 3, first: "2025-12-05T09:00", inferred: true }),
    cluster({ latitude: 38.0, longitude: -122.0, count: 1, first: "2025-12-07T09:00" }),
  ];
  const projection = routeProjection(stops, 960, 520, undefined, undefined, geoEqualEarth, clusters);

  it("puts each pin where its cluster projects and sizes it from the count", () => {
    const pins = pinsOf(clusters, projection);
    for (const pin of pins) {
      const at = projection([clusters[pin.index].longitude, clusters[pin.index].latitude]);
      expect([pin.x, pin.y]).toEqual(at);
      expect(pin.size).toBe(pinSize(clusters[pin.index].count));
      expect(pin.count).toBe(clusters[pin.index].count);
    }
  });

  it("is hollow only where every photo is placed from the itinerary", () => {
    const pins = pinsOf(clusters, projection);
    expect(pins.map((p) => [p.index, p.inferred])).toEqual([[1, true], [2, false], [0, false]]);
  });

  it("orders pins by their first photo's time, which is the tab order", () => {
    expect(pinsOf(clusters, projection).map((p) => p.index)).toEqual([1, 2, 0]);
  });

  it("marks the clusters it is told hold far photos", () => {
    expect(pinsOf(clusters, projection, new Set([2])).map((p) => [p.index, p.far])).toEqual([[1, false], [2, true], [0, false]]);
  });

  it("is empty for no clusters", () => {
    expect(pinsOf([], projection)).toEqual([]);
  });
});

describe("routeProjection with clusters", () => {
  it("fits a far cluster inside the map together with the stops", () => {
    const far = cluster({ latitude: -33.9, longitude: 151.2 });
    const without = routeProjection(stops, 960, 520);
    const withFar = routeProjection(stops, 960, 520, undefined, undefined, geoEqualEarth, [far]);
    const at = withFar([far.longitude, far.latitude])!;
    expect(at[0]).toBeGreaterThanOrEqual(0);
    expect(at[0]).toBeLessThanOrEqual(960);
    expect(at[1]).toBeGreaterThanOrEqual(0);
    expect(at[1]).toBeLessThanOrEqual(520);
    for (const spot of positions(stops, withFar)) {
      expect(spot.x).toBeGreaterThanOrEqual(0);
      expect(spot.x).toBeLessThanOrEqual(960);
    }
    expect(withFar.scale()).toBeLessThan(without.scale());
  });

  it("leaves the projection exactly as it was when there are no clusters", () => {
    const a = routeProjection(stops, 960, 520);
    const b = routeProjection(stops, 960, 520, undefined, undefined, geoEqualEarth, []);
    expect([b.scale(), b.translate()]).toEqual([a.scale(), a.translate()]);
  });

  it("fits clusters alone when there are no stops", () => {
    const spread = [cluster({ latitude: 44.0, longitude: -73.0 }), cluster({ latitude: 43.0, longitude: -72.0 })];
    const projection = routeProjection([], 960, 520, undefined, undefined, geoEqualEarth, spread);
    for (const c of spread) {
      const at = projection([c.longitude, c.latitude])!;
      expect(at[0]).toBeGreaterThan(0);
      expect(at[0]).toBeLessThan(960);
      expect(at[1]).toBeGreaterThan(0);
      expect(at[1]).toBeLessThan(520);
    }
  });

  it("gives a single cluster a fixed regional zoom, the same wherever it is", () => {
    const one = (latitude: number, longitude: number) => routeProjection([], 960, 520, undefined, undefined, geoEqualEarth, [cluster({ latitude, longitude })]);
    const here = one(44, -73);
    const there = one(44, 10);
    expect(here.scale()).toBeCloseTo(there.scale(), 6);
    const edge = here([-73 + MIN_SPAN_DEGREES / 2, 44])!;
    expect(edge[0]).toBeGreaterThan(480);
    expect(edge[0]).toBeLessThan(960 - 100 + 1);
  });
});

describe("stopPosition", () => {
  it("is the stop itself for a time within the stay", () => {
    expect(stopPosition(stops, "2025-12-07T10:00")).toBe(1);
  });

  it("is the first stop for a time before the trip and the last after it", () => {
    expect(stopPosition(stops, "2025-12-01T10:00")).toBe(0);
    expect(stopPosition(stops, "2025-12-20T10:00")).toBe(2);
  });

  it("falls along the leg between two stops for a time between them", () => {
    const at = stopPosition(stops, "2025-12-11T15:00");
    expect(at).toBeGreaterThan(1);
    expect(at).toBeLessThan(2);
    expect(at).toBeCloseTo(1 + 2 / (5 + 50 / 60), 3);
  });

  it("is zero with no stops", () => {
    expect(stopPosition([], "2025-12-07T10:00")).toBe(0);
  });
});

describe("pinLit", () => {
  const stay = cluster({ first: "2025-12-07T10:00" });
  const road = cluster({ first: "2025-12-11T15:00" });

  it("lights a pin when the replay reaches the stop its first photo was taken at", () => {
    expect(pinLit(stay, stops, 0.49)).toBe(false);
    expect(pinLit(stay, stops, 0.5)).toBe(true);
    expect(pinLit(stay, stops, 1)).toBe(true);
  });

  it("lights a pin for a photo taken on the road part of the way along that leg", () => {
    expect(pinLit(road, stops, 0.67)).toBe(false);
    expect(pinLit(road, stops, 0.68)).toBe(true);
  });

  it("has a photo from before the trip lit from the start", () => {
    expect(pinLit(cluster({ first: "2025-12-01T08:00" }), stops, 0)).toBe(true);
  });

  it("is always lit when there is no route to replay", () => {
    expect(pinLit(stay, [], 0)).toBe(true);
    expect(pinLit(stay, stops.slice(0, 1), 0)).toBe(true);
  });
});

describe("pinFraction", () => {
  it("is the pin's place within the visible box, as percentages", () => {
    expect(pinFraction({ x: 300, y: 100 }, { x: 100, y: 0, w: 400, h: 200 })).toEqual({ left: 50, top: 50 });
  });

  it("falls outside 0 to 100 for a pin the camera has zoomed past", () => {
    expect(pinFraction({ x: 50, y: 100 }, { x: 100, y: 0, w: 400, h: 200 }).left).toBeLessThan(0);
  });
});

describe("spreadPins", () => {
  const apart = (a: { x: number; y: number }, b: { x: number; y: number }) => Math.max(Math.abs(a.x - b.x), Math.abs(a.y - b.y));

  it("leaves pins that already have room where they are", () => {
    const pins = [{ x: 10, y: 10, reach: 12 }, { x: 100, y: 10, reach: 12 }];
    expect(spreadPins(pins)).toEqual(pins);
  });

  it("pushes overlapping pins apart until their square buttons no longer overlap, without moving the input", () => {
    const pins = [{ x: 50, y: 50, reach: 12 }, { x: 56, y: 50, reach: 12 }, { x: 50, y: 58, reach: 14 }];
    const out = spreadPins(pins);
    expect(pins[1].x).toBe(56);
    for (const [i, j] of [[0, 1], [0, 2], [1, 2]]) expect(apart(out[i], out[j])).toBeGreaterThanOrEqual(out[i].reach + out[j].reach - 0.5);
  });

  it("separates pins stacked on one point and keeps each pin's other fields", () => {
    const out = spreadPins([{ x: 5, y: 5, reach: 12, id: "a" }, { x: 5, y: 5, reach: 12, id: "b" }]);
    expect(out.map((p) => p.id)).toEqual(["a", "b"]);
    expect(apart(out[0], out[1])).toBeGreaterThanOrEqual(23.9);
  });

  it("is empty for no pins", () => {
    expect(spreadPins([])).toEqual([]);
  });
});
