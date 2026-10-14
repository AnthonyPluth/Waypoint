import { describe, expect, it } from "vitest";
import type { TripPlaces } from "$lib/api-types";
import { isRoadTrip, legsOf, positions, replayMs, routeProjection, stopLine, stopTitle, stopsOf, worthLocating } from "./route-replay";
import { segment, trip } from "../test/fixtures";

const home = { city: "Springfield", latitude: 39.8, longitude: -89.65 };
const places: TripPlaces = {
  home,
  airports: [
    { code: "MSP", city: "Minneapolis", latitude: 44.8848, longitude: -93.2223 },
    { code: "SFO", city: "San Francisco", latitude: 37.6213, longitude: -122.379 },
  ],
  cities: [],
  stays: [
    { segment_id: 1, latitude: 38.63, longitude: -90.2, precision: "city" },
    { segment_id: 2, latitude: 36.16, longitude: -86.78, precision: "city" },
    { segment_id: 3, latitude: 39.78, longitude: -89.64, precision: "city" },
    { segment_id: 5, latitude: 39.79, longitude: -89.66, precision: "city" },
  ],
  roads: { legs: [], interstates: [] },
  boundaries: [],
};
const zone = "America/Chicago";
const first = segment({ id: 1, kind: "hotel", origin: "Arch Inn", destination: "St. Louis", start_local: "2025-12-05T15:00", start_zone: zone, end_local: "2025-12-06T11:00", end_zone: zone });
const second = segment({ id: 2, kind: "hotel", origin: "Music Row Inn", destination: "Nashville", start_local: "2025-12-06T15:00", start_zone: zone, end_local: "2025-12-08T11:00", end_zone: zone });
const near = segment({ id: 3, kind: "hotel", origin: "Capitol Inn", destination: "Springfield", start_local: "2025-12-05T15:00", start_zone: zone, end_local: "2025-12-06T11:00", end_zone: zone });
const lastNear = segment({ id: 5, kind: "hotel", origin: "Lincoln Inn", destination: "Springfield", start_local: "2025-12-08T15:00", start_zone: zone, end_local: "2025-12-09T11:00", end_zone: zone });
const flight = segment({ id: 4, origin: "MSP", destination: "SFO", start_local: "2025-12-05T08:00", start_zone: zone, end_local: "2025-12-05T10:30", end_zone: "America/Los_Angeles" });
const names = (stops: ReturnType<typeof stopsOf>) => stops.map((s) => s.name);

describe("a road trip with a Home", () => {
  it("starts and ends at Home, visits the stops in order, and the last Home is the first one again", () => {
    const stops = stopsOf(trip([second, first]), places);
    expect(names(stops)).toEqual(["Springfield", "Arch Inn", "Music Row Inn", "Springfield"]);
    expect(stops.map((s) => s.kind)).toEqual(["home", "stay", "stay", "home"]);
    expect(stops.map((s) => s.via)).toEqual([null, null, null, null]);
  });

  it("dates Home by the day the trip left and the day it came back", () => {
    const stops = stopsOf(trip([first, second]), places);
    expect([stops[0].from, stops[0].to].map((d) => d.slice(0, 10))).toEqual(["2025-12-05", "2025-12-05"]);
    expect([stops[3].from, stops[3].to].map((d) => d.slice(0, 10))).toEqual(["2025-12-08", "2025-12-08"]);
    expect(stopTitle(stops[0])).toBe("Springfield");
    expect(stopLine(stops[3], 2025)).toBe("Springfield, Dec 8");
  });

  it("counts Home in the stops and in the replay's length", () => {
    const stops = stopsOf(trip([first, second]), places);
    expect(stops).toHaveLength(4);
    expect(replayMs(stops.length)).toBe(8000);
    expect(replayMs(stopsOf(trip([first, second]), { ...places, home: null }).length)).toBe(6000);
  });

  it("is still not worth locating with one stop, as before", () => {
    expect(worthLocating(trip([first]), "2027-01-01")).toBe(false);
  });

  it("draws every leg, to and from Home, straight when no road data covers it", () => {
    const stops = stopsOf(trip([first, second]), places);
    const projection = routeProjection(stops, 960, 520);
    const legs = legsOf(stops, projection);
    expect(legs).toHaveLength(3);
    expect(legs.every((l) => l.vehicle === "car" && !l.flight && l.road === null)).toBe(true);
    expect(positions(stops, projection)).toHaveLength(4);
  });

  it("uses the road data for a leg from Home when some covers it", () => {
    const stops = stopsOf(trip([first, second]), places);
    const roads = { legs: [{ from_segment_id: 0, to_segment_id: 1, refs: ["I-55"], points: [[39.8, -89.65], [39.2, -89.9], [38.63, -90.2]] }], interstates: [] };
    expect(legsOf(stops, routeProjection(stops, 960, 520, undefined, roads), roads)[0].refs).toEqual(["I-55"]);
  });

  it("leaves out the Home stop at an end that is already the home city", () => {
    expect(names(stopsOf(trip([near, second]), places))).toEqual(["Capitol Inn", "Music Row Inn", "Springfield"]);
    expect(names(stopsOf(trip([first, lastNear]), places))).toEqual(["Springfield", "Arch Inn", "Lincoln Inn"]);
    expect(names(stopsOf(trip([near]), places))).toEqual(["Capitol Inn"]);
  });
});

describe("a trip Home does not touch", () => {
  it("is unchanged with a flight, a train or a cruise, and cancelled ones don't count", () => {
    const train = segment({ id: 6, kind: "train", origin: "St. Louis", destination: "Nashville", start_local: "2025-12-07T09:00", start_zone: zone, end_local: "2025-12-07T15:00", end_zone: zone });
    const cruise = segment({ id: 7, kind: "cruise", origin: "Miami", destination: "Miami", start_local: "2025-12-07T09:00", start_zone: zone, end_local: "2025-12-10T15:00", end_zone: zone });
    for (const other of [flight, train, cruise]) {
      expect(isRoadTrip(trip([first, other]))).toBe(false);
      expect(stopsOf(trip([first, other]), places).some((s) => s.kind === "home")).toBe(false);
    }
    const cancelled = segment({ id: 8, origin: "MSP", destination: "SFO", status: "cancelled", start_local: "2025-12-05T08:00", start_zone: zone, end_local: "2025-12-05T10:30", end_zone: zone });
    expect(isRoadTrip(trip([first, second, cancelled]))).toBe(true);
    expect(names(stopsOf(trip([first, second, cancelled]), places))).toEqual(["Springfield", "Arch Inn", "Music Row Inn", "Springfield"]);
  });

  it("is unchanged with no Home", () => {
    expect(names(stopsOf(trip([first, second]), { ...places, home: null }))).toEqual(["Arch Inn", "Music Row Inn"]);
  });

  it("adds nothing when no stop has coordinates", () => {
    expect(stopsOf(trip([first, second]), { ...places, stays: [] })).toEqual([]);
  });
});
