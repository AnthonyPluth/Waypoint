import { describe, expect, it } from "vitest";
import type { Stop } from "./route-replay";
import { cardLegs, cardSpots, project, type Frame } from "./card-map";

const stop = (name: string, latitude: number, longitude: number, extra: Partial<Stop> = {}): Stop => ({ name, city: name, code: null, kind: "stay", latitude, longitude, from: "2026-09-03", to: "2026-09-04", via: null, ...extra });
const DENVER = stop("Denver", 39.74, -104.99);
const SALT_LAKE = stop("Salt Lake City", 40.76, -111.89);
const frame = (extra: Partial<Frame> = {}): Frame => ({ center: { latitude: 40.27, longitude: -108.43 }, zoom: 5, width: 352, height: 168, ...extra });

describe("projecting a place onto Apple's snapshot", () => {
  it("puts the centre in the middle of the image", () => {
    const at = project({ latitude: 40.27, longitude: -108.43 }, frame());
    expect(at.x).toBeCloseTo(176, 6);
    expect(at.y).toBeCloseTo(84, 6);
  });

  it("is Web Mercator on a 256 px world that doubles with each zoom level", () => {
    const origin = { center: { latitude: 0, longitude: 0 }, zoom: 1, width: 100, height: 100 };
    expect(project({ latitude: 0, longitude: 90 }, frame(origin)).x - 50).toBeCloseTo((90 / 360) * 512, 6);
    expect(project({ latitude: 0, longitude: -90 }, frame(origin)).x - 50).toBeCloseTo((-90 / 360) * 512, 6);
    const flat = { ...origin, zoom: 0 };
    expect(50 - project({ latitude: 45, longitude: 0 }, frame(flat)).y).toBeCloseTo(256 * (Math.log(Math.tan(Math.PI / 4 + Math.PI / 8)) / (2 * Math.PI)), 6);
    expect(project({ latitude: 45, longitude: 0 }, frame({ ...flat, zoom: 3 })).y - 50).toBeCloseTo((project({ latitude: 45, longitude: 0 }, frame(flat)).y - 50) * 8, 6);
  });

  it("stretches north-south the way Mercator does: a degree of latitude is taller far from the equator", () => {
    const south = frame({ center: { latitude: 10, longitude: 0 }, zoom: 6 }), north = frame({ center: { latitude: 60, longitude: 0 }, zoom: 6 });
    const tall = (f: Frame) => project({ latitude: f.center.latitude - 1, longitude: 0 }, f).y - project({ latitude: f.center.latitude + 1, longitude: 0 }, f).y;
    expect(tall(north)).toBeGreaterThan(tall(south) * 1.9);
  });

  it("keeps a place away from the poles on the map", () => {
    expect(Number.isFinite(project({ latitude: 90, longitude: 0 }, frame()).y)).toBe(true);
  });

  it("puts the stops the server fitted inside the card, with room round them", () => {
    for (const at of cardSpots([DENVER, SALT_LAKE], frame())) {
      expect(at.x).toBeGreaterThanOrEqual(28);
      expect(at.x).toBeLessThanOrEqual(352 - 28);
      expect(at.y).toBeGreaterThanOrEqual(28);
      expect(at.y).toBeLessThanOrEqual(168 - 28);
    }
  });

  it("puts east to the right of west and north above south", () => {
    const [denver, saltLake] = cardSpots([DENVER, SALT_LAKE], frame());
    expect(denver.x).toBeGreaterThan(saltLake.x);
    expect(saltLake.y).toBeLessThan(denver.y);
  });
});

describe("the legs of a card's route", () => {
  const spots = (stops: Stop[]) => cardSpots(stops, frame());
  const road: number[][] = [[39.74, -104.99], [40.0, -107.0], [40.3, -109.0], [40.76, -111.89]];

  it("draws a drive with no stored road as a straight line between its stops", () => {
    const [leg] = cardLegs([DENVER, SALT_LAKE], spots([DENVER, SALT_LAKE]), new Map(), frame());
    expect(leg.flight).toBe(false);
    const [from, to] = spots([DENVER, SALT_LAKE]);
    expect(leg.d).toBe(`M${from.x.toFixed(1)},${from.y.toFixed(1)} L${to.x.toFixed(1)},${to.y.toFixed(1)}`);
  });

  it("draws the stored Apple road for a drive, projected point by point", () => {
    const [leg] = cardLegs([DENVER, SALT_LAKE], spots([DENVER, SALT_LAKE]), new Map([["39.7400,-104.9900>40.7600,-111.8900", road]]), frame());
    expect(leg.d.match(/[ML]/g)).toHaveLength(road.length);
    const first = project({ latitude: road[0][0], longitude: road[0][1] }, frame());
    expect(leg.d.startsWith(`M${first.x.toFixed(1)},${first.y.toFixed(1)} L`)).toBe(true);
    expect(leg.flight).toBe(false);
  });

  it("uses the road only for its exact drive, not another leg", () => {
    const third = stop("Boise", 43.6, -116.2);
    const stops = [DENVER, SALT_LAKE, third];
    const legs = cardLegs(stops, spots(stops), new Map([["39.7400,-104.9900>40.7600,-111.8900", road]]), frame());
    expect(legs[0].d.match(/L/g)).toHaveLength(road.length - 1);
    expect(legs[1].d.match(/[ML]/g)).toHaveLength(2);
  });

  it("draws a flight as an arc in the route colour's leg, bowed off the straight line", () => {
    const stops = [stop("Denver", 39.74, -104.99, { kind: "airport", code: "DEN" }), stop("Salt Lake City", 40.76, -111.89, { kind: "airport", code: "SLC", via: "flight" })];
    const [leg] = cardLegs(stops, spots(stops), new Map([["39.7400,-104.9900>40.7600,-111.8900", road]]), frame());
    expect(leg.flight).toBe(true);
    expect(leg.d).toContain(" Q");
  });
});
