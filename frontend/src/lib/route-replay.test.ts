import { describe, expect, it } from "vitest";
import type { TripPlaces } from "./api-types";
import { activeStop, canReplay, legProgress, legsOf, maxStops, positions, reached, replayMs, routeProjection, stopDates, stopLine, stopsOf, worthLocating, type Stop } from "./route-replay";
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
};
const out = segment({ id: 1, origin: "MSP", destination: "SFO", start_local: "2025-12-05T08:00", start_zone: "America/Chicago", end_local: "2025-12-05T10:30", end_zone: "America/Los_Angeles" });
const stay = segment({ id: 2, kind: "hotel", origin: "Bayview Inn", destination: "San Francisco", start_local: "2025-12-05T15:00", start_zone: "America/Los_Angeles", end_local: "2025-12-11T11:00", end_zone: "America/Los_Angeles" });
const back = segment({ id: 3, origin: "SFO", destination: "MSP", start_local: "2025-12-11T13:00", start_zone: "America/Los_Angeles", end_local: "2025-12-11T18:50", end_zone: "America/Chicago" });
const names = (stops: Stop[]) => stops.map((s) => s.name);

describe("stopsOf", () => {
  it("puts the stops in time order and merges a stay into the airport city it follows", () => {
    const stops = stopsOf(trip([back, stay, out]), places);
    expect(names(stops)).toEqual(["Minneapolis", "San Francisco", "Minneapolis"]);
    expect(stops.map((s) => [s.from.slice(0, 10), s.to.slice(0, 10)])).toEqual([["2025-12-05", "2025-12-05"], ["2025-12-05", "2025-12-11"], ["2025-12-11", "2025-12-11"]]);
    expect(stops.map((s) => s.back)).toEqual([false, false, true]);
    expect(stops.map((s) => s.via)).toEqual([null, "flight", "flight"]);
  });

  it("skips stops with no coordinates and keeps the rest in order", () => {
    const unknown = segment({ id: 4, kind: "hotel", origin: "Nowhere Inn", destination: "Nowhereville", start_local: "2025-12-06T15:00", start_zone: "America/Los_Angeles", end_local: "2025-12-07T11:00", end_zone: "America/Los_Angeles" });
    const noWhere = segment({ id: 5, kind: "hotel", origin: "Quay Lodge", destination: null, start_local: "2025-12-07T15:00", start_zone: "America/Los_Angeles", end_local: "2025-12-08T11:00", end_zone: "America/Los_Angeles" });
    const rental = segment({ id: 6, kind: "car", origin: "SFO airport", destination: "SFO airport", start_local: "2025-12-05T12:00", start_zone: "America/Los_Angeles", end_local: "2025-12-11T12:00", end_zone: "America/Los_Angeles" });
    const lost = segment({ id: 7, origin: "ZZZ", destination: "SFO", start_local: "2025-12-12T08:00", start_zone: "America/Los_Angeles", end_local: "2025-12-12T09:00", end_zone: "America/Los_Angeles" });
    expect(names(stopsOf(trip([out, unknown, noWhere, rental, stay, lost]), places))).toEqual(["Minneapolis", "San Francisco"]);
  });

  it("leaves out cancelled bookings and parking", () => {
    const cancelled = segment({ id: 4, kind: "hotel", status: "cancelled", origin: "Vine Inn", destination: "Napa", start_local: "2025-12-06T15:00", start_zone: "America/Los_Angeles", end_local: "2025-12-07T11:00", end_zone: "America/Los_Angeles" });
    const lot = segment({ id: 5, kind: "parking", origin: "Napa Lot", destination: "Napa", start_local: "2025-12-04T15:00", start_zone: "America/Chicago", end_local: "2025-12-05T07:00", end_zone: "America/Chicago" });
    expect(names(stopsOf(trip([out, cancelled, lot]), places))).toEqual(["Minneapolis", "San Francisco"]);
  });

  it("treats a stay in a nearby city as a separate stop and a train as other travel", () => {
    const napa = segment({ id: 4, kind: "hotel", origin: "Vine Inn", destination: "Napa, CA", start_local: "2025-12-06T15:00", start_zone: "America/Los_Angeles", end_local: "2025-12-08T11:00", end_zone: "America/Los_Angeles" });
    const stops = stopsOf(trip([out, napa]), places);
    expect(names(stops)).toEqual(["Minneapolis", "San Francisco", "Napa"]);
    expect(stops[2].via).toBeNull();
    const ride = segment({ id: 5, kind: "train", origin: "Napa", destination: "San Francisco", start_local: "2025-12-08T12:00", start_zone: "America/Los_Angeles", end_local: "2025-12-08T14:00", end_zone: "America/Los_Angeles" });
    const all = stopsOf(trip([out, napa, ride]), places);
    expect(names(all)).toEqual(["Minneapolis", "San Francisco", "Napa", "San Francisco"]);
    expect(all[3].via).toBe("train");
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
    expect(stopLine(stops[0], 2025)).toBe("Minneapolis, Dec 5");
    expect(stopLine(stops[1], 2025)).toMatch(/^San Francisco, Dec 5\s*[–-]\s*11$/);
    expect(stopLine(stops[2], 2025)).toBe("Back in Minneapolis, Dec 11");
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
    expect(canReplay(trip([out]), "2026-01-01", { airports: [places.airports[0]], cities: [] })).toBe(false);
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

  it("spreads the legs evenly over the playback", () => {
    expect([0, 0.25, 0.5, 0.75, 1].map((p) => legProgress(0, 3, p))).toEqual([0, 0.5, 1, 1, 1]);
    expect([0, 0.25, 0.5, 0.75, 1].map((p) => legProgress(1, 3, p))).toEqual([0, 0, 0, 0.5, 1]);
    expect([0, 0.49, 0.5, 1].map((p) => reached(1, 3, p))).toEqual([false, false, true, true]);
    expect(reached(0, 3, 0)).toBe(true);
    expect([0, 0.49, 0.5, 0.99, 1].map((p) => activeStop(3, p))).toEqual([0, 0, 1, 1, 2]);
  });

  it("plays for between six and twelve seconds", () => {
    expect([2, 3, 4, 6, 9].map(replayMs)).toEqual([6000, 6000, 8000, 12000, 12000]);
  });
});
