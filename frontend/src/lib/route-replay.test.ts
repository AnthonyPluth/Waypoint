import { describe, expect, it } from "vitest";
import type { TripPlaces } from "./api-types";
import { activeStop, cameraAt, canReplay, legProgress, labelLit, legsOf, localRuns, maxStops, planeAt, positions, reached, replayMs, routeProjection, stopDates, stopLine, stopsOf, worthLocating, type Stop } from "./route-replay";
import { segment, trip } from "../test/fixtures";

const places: TripPlaces = {
  airports: [
    { code: "MSP", city: "Minneapolis", latitude: 44.8848, longitude: -93.2223 },
    { code: "SFO", city: "San Francisco", latitude: 37.6213, longitude: -122.379 },
    { code: "OAK", city: "Oakland", latitude: 37.7213, longitude: -122.2208 },
  ],
  cities: [
    { city: "san francisco", latitude: 37.6213, longitude: -122.379 },
    { city: "napa", latitude: 38.2975, longitude: -122.2869 },
  ],
  stays: [],
  roads: { legs: [], interstates: [] },
  boundaries: [],
};
const out = segment({ id: 1, origin: "MSP", destination: "SFO", start_local: "2025-12-05T08:00", start_zone: "America/Chicago", end_local: "2025-12-05T10:30", end_zone: "America/Los_Angeles" });
const stay = segment({ id: 2, kind: "hotel", origin: "Bayview Inn", destination: "San Francisco", start_local: "2025-12-05T15:00", start_zone: "America/Los_Angeles", end_local: "2025-12-11T11:00", end_zone: "America/Los_Angeles" });
const back = segment({ id: 3, origin: "SFO", destination: "MSP", start_local: "2025-12-11T13:00", start_zone: "America/Los_Angeles", end_local: "2025-12-11T18:50", end_zone: "America/Chicago" });
const names = (stops: Stop[]) => stops.map((s) => s.name);

describe("stopsOf", () => {
  it("puts the stops in time order and keeps the hotel and the return flight as stops of their own", () => {
    const stops = stopsOf(trip([back, stay, out]), places);
    expect(names(stops)).toEqual(["Minneapolis", "San Francisco", "Bayview Inn", "San Francisco", "Minneapolis"]);
    expect(stops.map((s) => s.kind)).toEqual(["airport", "airport", "stay", "airport", "airport"]);
    expect(stops.map((s) => [s.from.slice(0, 10), s.to.slice(0, 10)])).toEqual([["2025-12-05", "2025-12-05"], ["2025-12-05", "2025-12-05"], ["2025-12-05", "2025-12-11"], ["2025-12-11", "2025-12-11"], ["2025-12-11", "2025-12-11"]]);
    expect(stops.map((s) => s.back)).toEqual([false, false, false, true, true]);
    expect(stops.map((s) => s.via)).toEqual([null, "flight", null, null, "flight"]);
  });

  it("merges only consecutive duplicates: a connection's airport once, a hotel never into an airport", () => {
    const hop = segment({ id: 4, origin: "SFO", destination: "OAK", start_local: "2025-12-05T12:00", start_zone: "America/Los_Angeles", end_local: "2025-12-05T13:00", end_zone: "America/Los_Angeles" });
    expect(names(stopsOf(trip([out, hop]), places))).toEqual(["Minneapolis", "San Francisco", "Oakland"]);
    const kinds = stopsOf(trip([out, stay]), places).map((s) => s.kind);
    expect(kinds).toEqual(["airport", "airport", "stay"]);
  });

  it("skips stops with no coordinates and keeps the rest in order", () => {
    const unknown = segment({ id: 4, kind: "hotel", origin: "Nowhere Inn", destination: "Nowhereville", start_local: "2025-12-06T15:00", start_zone: "America/Los_Angeles", end_local: "2025-12-07T11:00", end_zone: "America/Los_Angeles" });
    const noWhere = segment({ id: 5, kind: "hotel", origin: "Quay Lodge", destination: null, start_local: "2025-12-07T15:00", start_zone: "America/Los_Angeles", end_local: "2025-12-08T11:00", end_zone: "America/Los_Angeles" });
    const rental = segment({ id: 6, kind: "car", origin: "SFO airport", destination: "SFO airport", start_local: "2025-12-05T12:00", start_zone: "America/Los_Angeles", end_local: "2025-12-11T12:00", end_zone: "America/Los_Angeles" });
    const lost = segment({ id: 7, origin: "ZZZ", destination: "SFO", start_local: "2025-12-12T08:00", start_zone: "America/Los_Angeles", end_local: "2025-12-12T09:00", end_zone: "America/Los_Angeles" });
    expect(names(stopsOf(trip([out, unknown, noWhere, rental, stay, lost]), places))).toEqual(["Minneapolis", "San Francisco", "Bayview Inn", "San Francisco"]);
  });

  it("leaves out cancelled bookings and parking", () => {
    const cancelled = segment({ id: 4, kind: "hotel", status: "cancelled", origin: "Vine Inn", destination: "Napa", start_local: "2025-12-06T15:00", start_zone: "America/Los_Angeles", end_local: "2025-12-07T11:00", end_zone: "America/Los_Angeles" });
    const lot = segment({ id: 5, kind: "parking", origin: "Napa Lot", destination: "Napa", start_local: "2025-12-04T15:00", start_zone: "America/Chicago", end_local: "2025-12-05T07:00", end_zone: "America/Chicago" });
    expect(names(stopsOf(trip([out, cancelled, lot]), places))).toEqual(["Minneapolis", "San Francisco"]);
  });

  it("treats a stay in a nearby city as a separate stop and a train as other travel", () => {
    const napa = segment({ id: 4, kind: "hotel", origin: "Vine Inn", destination: "Napa, CA", start_local: "2025-12-06T15:00", start_zone: "America/Los_Angeles", end_local: "2025-12-08T11:00", end_zone: "America/Los_Angeles" });
    const stops = stopsOf(trip([out, napa]), places);
    expect(names(stops)).toEqual(["Minneapolis", "San Francisco", "Vine Inn"]);
    expect(stops[2].via).toBeNull();
    const ride = segment({ id: 5, kind: "train", origin: "Napa", destination: "San Francisco", start_local: "2025-12-08T12:00", start_zone: "America/Los_Angeles", end_local: "2025-12-08T14:00", end_zone: "America/Los_Angeles" });
    const all = stopsOf(trip([out, napa, ride]), places);
    expect(names(all)).toEqual(["Minneapolis", "San Francisco", "Vine Inn", "San Francisco"]);
    expect(all[3].via).toBe("train");
  });

  it("places a stay in a town with no airport at its stored point", () => {
    const town = segment({ id: 4, kind: "hotel", origin: "Mill Inn", destination: "Longmont", start_local: "2025-12-06T15:00", start_zone: "America/Denver", end_local: "2025-12-08T11:00", end_zone: "America/Denver" });
    expect(names(stopsOf(trip([out, town]), places))).toEqual(["Minneapolis", "San Francisco"]);
    const stops = stopsOf(trip([out, town]), { ...places, stays: [{ segment_id: 4, latitude: 40.1672, longitude: -105.1019, precision: "city" }] });
    expect(names(stops)).toEqual(["Minneapolis", "San Francisco", "Mill Inn"]);
    expect([stops[2].latitude, stops[2].longitude]).toEqual([40.1672, -105.1019]);
  });

  it("keeps two stays in one city as two stops when their stored points are far apart, and as one when they are near", () => {
    const first = segment({ id: 4, kind: "hotel", origin: "North Inn", destination: "Boulder", start_local: "2025-12-06T15:00", start_zone: "America/Denver", end_local: "2025-12-07T11:00", end_zone: "America/Denver" });
    const second = segment({ id: 5, kind: "hotel", origin: "South Inn", destination: "Boulder", start_local: "2025-12-07T15:00", start_zone: "America/Denver", end_local: "2025-12-08T11:00", end_zone: "America/Denver" });
    const far = { ...places, stays: [{ segment_id: 4, latitude: 40.0251, longitude: -105.3487, precision: "zip" as const }, { segment_id: 5, latitude: 39.5, longitude: -104.9, precision: "zip" as const }] };
    expect(names(stopsOf(trip([first, second]), far))).toEqual(["North Inn", "South Inn"]);
    const near = { ...places, stays: [{ segment_id: 4, latitude: 40.0251, longitude: -105.3487, precision: "zip" as const }, { segment_id: 5, latitude: 40.0402, longitude: -105.2514, precision: "zip" as const }] };
    expect(names(stopsOf(trip([first, second]), near))).toEqual(["North Inn"]);
  });

  it("uses a stored point before the city lookup, and the city lookup when there is none", () => {
    const napa = segment({ id: 4, kind: "hotel", origin: "Vine Inn", destination: "Napa, CA", start_local: "2025-12-06T15:00", start_zone: "America/Los_Angeles", end_local: "2025-12-08T11:00", end_zone: "America/Los_Angeles" });
    const withPoint = { ...places, stays: [{ segment_id: 4, latitude: 38.5, longitude: -122.5, precision: "zip" as const }] };
    expect(stopsOf(trip([out, napa]), withPoint).at(-1)?.latitude).toBe(38.5);
    expect(stopsOf(trip([out, napa]), places).at(-1)?.latitude).toBe(38.2975);
  });

  it("places a car, a train arrival and a cruise embarkation at their stored points, and a port of call by its city", () => {
    const la = "America/Los_Angeles";
    const car = segment({ id: 4, kind: "car", origin: "Depot One", destination: "Depot Two", start_local: "2025-12-06T09:00", start_zone: la, end_local: "2025-12-06T18:00", end_zone: la });
    const ride = segment({ id: 5, kind: "train", origin: "Napa", destination: "Sacramento", start_local: "2025-12-07T09:00", start_zone: la, end_local: "2025-12-07T11:00", end_zone: la });
    const cruise = segment({ id: 6, kind: "cruise", origin: "Pier 9", destination: "Pier 9", start_local: "2025-12-09T16:00", start_zone: la, end_local: "2025-12-13T07:00", end_zone: la,
      itinerary: [{ name: "Napa", zone: la, arrive_local: "2025-12-11T08:00", depart_local: "2025-12-11T17:00" }] });
    const stays = [
      { segment_id: 4, latitude: 36.6, longitude: -121.9, precision: "zip" as const },
      { segment_id: 5, latitude: 38.58, longitude: -121.49, precision: "city" as const },
      { segment_id: 6, latitude: 33.77, longitude: -118.19, precision: "city" as const },
    ];
    const stops = stopsOf(trip([car, ride, cruise]), { ...places, stays });
    expect(stops.map((s) => [s.latitude, s.longitude])).toEqual([[36.6, -121.9], [38.2975, -122.2869], [38.58, -121.49], [33.77, -118.19], [38.2975, -122.2869]]);
    expect(names(stops)).toEqual(["Depot Two", "Napa", "Sacramento", "Pier 9", "Napa"]);
    expect(stops.map((s) => s.via)).toEqual([null, null, "train", null, "cruise"]);
  });

  it("reads a cruise's ports in order", () => {
    const cruise = segment({ id: 4, kind: "cruise", origin: "San Francisco", destination: "San Francisco", start_local: "2025-12-06T16:00", start_zone: "America/Los_Angeles", end_local: "2025-12-13T07:00", end_zone: "America/Los_Angeles",
      itinerary: [{ name: "Napa", zone: "America/Los_Angeles", arrive_local: "2025-12-08T08:00", depart_local: "2025-12-08T17:00" }, { name: "Nowhere", zone: "UTC", arrive_local: "2025-12-09T08:00", depart_local: null }] });
    const stops = stopsOf(trip([cruise]), places);
    expect(names(stops)).toEqual(["San Francisco", "Napa", "San Francisco"]);
    expect(stops[1].via).toBe("cruise");
  });
});

describe("the text of a stop", () => {
  const stops = stopsOf(trip([out, stay, back]), places);

  it("names the city and the dates there, in the place's own days", () => {
    expect(stopLine(stops[0], 2025)).toBe("Minneapolis (MSP), Dec 5");
    expect(stopLine(stops[2], 2025)).toMatch(/^Stay: Bayview Inn, San Francisco, Dec 5\s*[–-]\s*11$/);
    expect(stopLine(stops[4], 2025)).toBe("Back in Minneapolis (MSP), Dec 11");
  });

  it("adds the year only when it is not the current one", () => {
    expect(stopDates(stops[0], 2026)).toBe("Dec 5, 2025");
    expect(stopDates({ ...stops[0], from: "bad", to: "bad" }, 2025)).toBe("");
  });
});

describe("whether a trip can be replayed", () => {
  const past = trip([out, stay, back]);

  it("needs the trip to have ended and two located stops", () => {
    expect(past.end_date).toBe("2025-12-11");
    expect(canReplay(past, "2026-01-01", places)).toBe(true);
    expect(canReplay(past, "2025-12-11", places)).toBe(false);
    expect(canReplay(past, "2025-12-01", places)).toBe(false);
    expect(canReplay(past, "2026-01-01", null)).toBe(false);
    expect(canReplay(trip([stay]), "2026-01-01", places)).toBe(false);
    expect(canReplay(trip([out]), "2026-01-01", { airports: [places.airports[0]], cities: [], stays: [], roads: { legs: [], interstates: [] }, boundaries: [] })).toBe(false);
  });

  it("counts the most stops a trip could have before asking for coordinates", () => {
    expect(maxStops(trip([stay]))).toBe(1);
    expect(maxStops(trip([out, stay]))).toBe(3);
    expect(maxStops(trip([segment({ id: 9, kind: "parking" })]))).toBe(0);
    expect(worthLocating(trip([stay]), "2027-01-01")).toBe(false);
    expect(worthLocating(trip([out]), "2027-01-01")).toBe(true);
    expect(worthLocating(trip([out]), "2025-12-05")).toBe(false);
  });
});

describe("the camera and the timeline", () => {
  const stops = stopsOf(trip([out, stay, back]), places);
  const far: Stop[] = [{ ...stops[0], name: "Auckland", latitude: -37, longitude: 174.8 }, { ...stops[1], latitude: 37.6, longitude: -122.4 }];

  it("fits every stop inside the map", () => {
    for (const set of [stops, far]) {
      const projection = routeProjection(set, 960, 520);
      for (const p of positions(set, projection)) {
        expect(p.x).toBeGreaterThanOrEqual(0);
        expect(p.x).toBeLessThanOrEqual(960);
        expect(p.y).toBeGreaterThanOrEqual(0);
        expect(p.y).toBeLessThanOrEqual(520);
      }
    }
  });

  it("does not zoom in past a regional view for stops close together", () => {
    const near: Stop[] = [{ ...stops[1], name: "A", latitude: 37.7, longitude: -122.4 }, { ...stops[1], name: "B", latitude: 37.74, longitude: -122.38 }];
    const [a, b] = positions(near, routeProjection(near, 960, 520));
    expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeLessThan(200);
  });

  it("draws one arc between each pair of stops, flights apart from other travel", () => {
    const napa = { ...stops[1], name: "Napa", latitude: 38.3, longitude: -122.3, via: null };
    const set = [...stops.slice(0, 2), napa];
    const legs = legsOf(set, routeProjection(set, 960, 520));
    expect(legs.map((l) => l.flight)).toEqual([true, false]);
    expect(legs.every((l) => l.d.startsWith("M"))).toBe(true);
  });

  it("draws the return flight as its own arc, bowed away from the way out, with a stay marker beside the airport", () => {
    const set = stopsOf(trip([out, stay, back]), places);
    const projection = routeProjection(set, 960, 520);
    const legs = legsOf(set, projection);
    expect(legs).toHaveLength(4);
    expect(legs.map((l) => l.flight)).toEqual([true, false, false, true]);
    const there = legs[0], home = legs[3];
    expect(home.d).not.toBe(there.d);
    const axis = (c: { x: number; y: number }) => Math.sign((there.to.x - there.from.x) * (c.y - there.from.y) - (there.to.y - there.from.y) * (c.x - there.from.x));
    expect(axis(there.control)).toBe(-axis(home.control));
    const spots = positions(set, projection);
    expect(Math.hypot(spots[2].x - spots[1].x, spots[2].y - spots[1].y)).toBeGreaterThan(5);
  });

  it("moves a plane along a flight arc, pointing the way it flies", () => {
    const set = stopsOf(trip([out, back]), places);
    const [there, home] = legsOf(set, routeProjection(set, 960, 520));
    const start = planeAt(there, 0), end = planeAt(there, 1), mid = planeAt(there, 0.5);
    expect([start.x, start.y]).toEqual([there.from.x, there.from.y]);
    expect(end.x).toBeCloseTo(there.to.x);
    expect(end.y).toBeCloseTo(there.to.y);
    expect(mid.x).toBeCloseTo((there.from.x + 2 * there.control.x + there.to.x) / 4);
    const heading = (a: number) => Math.cos((a * Math.PI) / 180);
    expect(Math.sign(heading(planeAt(there, 0.5).angle))).toBe(Math.sign(there.to.x - there.from.x));
    expect(Math.sign(heading(planeAt(home, 0.5).angle))).toBe(Math.sign(home.to.x - home.from.x));
    expect(Math.sign(heading(planeAt(there, 0.5).angle))).not.toBe(Math.sign(heading(planeAt(home, 0.5).angle)));
  });

  it("lights a stop's label as the path reaches it, holds it, then lets every one go, the last included", () => {
    expect([0, 0.05, 0.3, 0.6].map((p) => labelLit(0, 3, p, false))).toEqual([true, true, false, false]);
    expect([0.2, 0.5, 0.6, 0.9].map((p) => labelLit(1, 3, p, false))).toEqual([false, true, true, false]);
    expect(labelLit(1, 3, 0.9, false)).toBe(false);
    expect(labelLit(1, 3, 0.9, true)).toBe(true);
    expect([0.5, 1].map((p) => labelLit(2, 3, p, false))).toEqual([false, false]);
    expect(labelLit(2, 3, 1, true)).toBe(false);
  });

  it("spreads the legs evenly over the playback", () => {
    expect([0, 0.25, 0.5, 0.75, 1].map((p) => legProgress(0, 3, p))).toEqual([0, 0.5, 1, 1, 1]);
    expect([0, 0.25, 0.5, 0.75, 1].map((p) => legProgress(1, 3, p))).toEqual([0, 0, 0, 0.5, 1]);
    expect([0, 0.49, 0.5, 1].map((p) => reached(1, 3, p))).toEqual([false, false, true, true]);
    expect(reached(0, 3, 0)).toBe(true);
    expect([0, 0.49, 0.5, 0.99, 1].map((p) => activeStop(3, p))).toEqual([0, 0, 1, 1, 2]);
  });

  it("plays for between six seconds and a minute, two seconds a stop", () => {
    expect([2, 3, 4, 6, 9, 12, 20, 30, 40].map(replayMs)).toEqual([6000, 6000, 8000, 12000, 18000, 24000, 40000, 60000, 60000]);
  });

  it("gives a 25-stop trip's labels their full hold, one at a time", () => {
    const stops = 25;
    const lit = (p: number) => Array.from({ length: stops - 1 }, (_, i) => labelLit(i, stops, p, false));
    for (let i = 0; i < stops - 1; i++) {
      expect(labelLit(i, stops, (i + 0.01) / (stops - 1), false)).toBe(true);
      expect(labelLit(i, stops, (i + 0.82) / (stops - 1), false)).toBe(true);
      expect(labelLit(i, stops, (i + 0.86) / (stops - 1), false)).toBe(false);
    }
    for (let step = 0; step < 1000; step++) expect(lit(step / 1000).filter(Boolean).length).toBeLessThanOrEqual(1);
  });
});

describe("the local legs and the camera", () => {
  const la = "America/Los_Angeles";
  const hotelNear = segment({ id: 4, kind: "hotel", origin: "Vine Inn", destination: "Napa, CA", start_local: "2025-12-06T15:00", start_zone: la, end_local: "2025-12-08T11:00", end_zone: la });
  const cruise = segment({ id: 5, kind: "cruise", origin: "San Francisco", destination: "San Francisco", start_local: "2025-12-09T16:00", start_zone: la, end_local: "2025-12-13T07:00", end_zone: la,
    itinerary: [{ name: "Napa", zone: la, arrive_local: "2025-12-11T08:00", depart_local: "2025-12-11T17:00" }] });

  it("gives a car to a leg on the ground, a boat to a cruise leg and a plane to a flight", () => {
    const set = stopsOf(trip([out, hotelNear, cruise]), places);
    const legs = legsOf(set, routeProjection(set, 960, 520));
    expect(legs.map((l) => l.vehicle)).toEqual(["plane", "car", "car", "boat", "boat"]);
    expect(legs.every((l) => l.d.startsWith("M"))).toBe(true);
  });

  it("finds the local run after each flight, up to the next flight", () => {
    const set = stopsOf(trip([out, stay, back]), places);
    expect(localRuns(set)).toEqual([{ from: 1, to: 3 }]);
    expect(localRuns(stopsOf(trip([out, back]), places))).toEqual([]);
  });

  it("zooms in after a flight lands, holds, and is back at the whole map before the next flight and at both ends", () => {
    const set = stopsOf(trip([out, hotelNear, back]), places);
    const projection = routeProjection(set, 960, 520);
    const spots = positions(set, projection);
    const at = (p: number) => cameraAt(set, spots, 960, 520, p);
    const whole = { x: 0, y: 0, w: 960, h: 520 };
    expect(at(0)).toEqual(whole);
    expect(at(1)).toEqual(whole);
    const units = set.length - 1;
    const held = at((1 + 0.5) / units);
    expect(held.w).toBeLessThan(960 * 0.5);
    expect(held.h / held.w).toBeCloseTo(520 / 960);
    expect(at(1 / units + 0.01).w).toBeGreaterThan(held.w);
    expect(at((units - 1) / units).w).toBeCloseTo(960);
    expect(held.x).toBeGreaterThanOrEqual(0);
    expect(held.x + held.w).toBeLessThanOrEqual(960);
  });
});
