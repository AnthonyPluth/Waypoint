import { describe, expect, it } from "vitest";
import { cameraAt, inView, legsOf, moverAt, planeAt, positions, retraceFor, roadFor, roadShapes, roadsShown, routeProjection, shieldsOf, MAX_SHIELDS, type Roads, type Stop } from "./route-replay";

const stopAt = (name: string, latitude: number, longitude: number, via: Stop["via"] = null, kind: Stop["kind"] = "stay"): Stop =>
  ({ name, city: name, code: null, kind, latitude, longitude, from: "2025-12-05T15:00", to: "2025-12-06T11:00", via, back: false });
const denver = stopAt("Denver", 39.74, -104.99), saltLake = stopAt("Salt Lake City", 40.76, -111.89);
const drive = { from_segment_id: 1, to_segment_id: 2, refs: ["I-25", "I-80"], points: [[39.77, -105.0], [40.2, -105.0], [41.2, -107.5], [40.75, -111.85]] };
const roads: Roads = { legs: [drive], interstates: [{ ref: "I-25", points: [[39.0, -105.0], [40.2, -105.0]] }, { ref: "I-80", points: [[41.2, -107.5], [40.75, -111.85]] }] };
const none: Roads = { legs: [], interstates: [] };
const project = (set: Stop[], r: Roads = roads) => routeProjection(set, 960, 520, undefined, r);
const distanceToPath = (p: { x: number; y: number }, pts: { x: number; y: number }[]) => Math.min(...pts.slice(1).map((b, i) => {
  const a = pts[i], dx = b.x - a.x, dy = b.y - a.y, span = dx * dx + dy * dy;
  const u = span === 0 ? 0 : Math.min(1, Math.max(0, ((p.x - a.x) * dx + (p.y - a.y) * dy) / span));
  return Math.hypot(p.x - (a.x + u * dx), p.y - (a.y + u * dy));
}));

describe("legs that follow the interstates", () => {
  it("matches a road to the two stops it starts and ends beside, in that direction only", () => {
    expect(roadFor(denver, saltLake, roads)).toBe(drive);
    expect(roadFor(saltLake, denver, roads)).toBeNull();
    expect(roadFor(denver, stopAt("Elsewhere", 35, -90), roads)).toBeNull();
    expect(roadFor(denver, { ...saltLake, via: "flight" }, roads)).toBeNull();
    expect(roadFor(denver, { ...saltLake, via: "train" }, roads)).toBeNull();
    expect(roadFor(denver, saltLake, none)).toBeNull();
    expect(roadFor(denver, saltLake, { legs: [{ ...drive, points: [[39.77, -105.0]] }], interstates: [] })).toBeNull();
  });

  it("takes the closer of two roads between the same stops", () => {
    const near = { ...drive, from_segment_id: 7, points: [[39.74, -104.99], [40.0, -108.0], [40.76, -111.89]] };
    expect(roadFor(denver, saltLake, { legs: [drive, near], interstates: [] })).toBe(near);
  });

  it("draws a road leg as a line through the road's points, joined to both stops, and keeps the curve for the rest", () => {
    const set = [stopAt("Boise", 43.6, -116.2), denver, saltLake];
    const [first, second] = legsOf(set, project(set), roads);
    expect(first.road).toBeNull();
    expect(first.d).toContain("Q");
    expect(first.refs).toEqual([]);
    expect(second.d).not.toContain("Q");
    expect(second.d.match(/L/g)).toHaveLength(5);
    expect(second.refs).toEqual(["I-25", "I-80"]);
    expect(second.vehicle).toBe("car");
    expect(second.road?.points[0]).toEqual(second.from);
    expect(second.road?.points.at(-1)).toEqual(second.to);
  });

  it("falls back to the curve with no road, and never roads a flight", () => {
    const set = [denver, saltLake];
    const [curved] = legsOf(set, project(set, none));
    expect(curved.road).toBeNull();
    expect(curved.d).toContain("Q");
    const [flight] = legsOf([denver, { ...saltLake, via: "flight" }], project(set), roads);
    expect(flight.road).toBeNull();
    expect(flight.vehicle).toBe("plane");
  });

  it("moves a car along the road from one stop to the other, pointing the way it drives", () => {
    const set = [denver, saltLake];
    const [leg] = legsOf(set, project(set), roads);
    const start = moverAt(leg, 0), end = moverAt(leg, 1), mid = moverAt(leg, 0.5);
    expect(start).toMatchObject({ x: leg.from.x, y: leg.from.y });
    expect(end.x).toBeCloseTo(leg.to.x);
    expect(end.y).toBeCloseTo(leg.to.y);
    expect(distanceToPath(mid, leg.road!.points)).toBeLessThan(0.01);
    expect(distanceToPath(mid, [leg.from, leg.to])).toBeGreaterThan(5);
    expect(Math.cos((moverAt(leg, 0.9).angle * Math.PI) / 180)).toBeLessThan(0);
    expect(moverAt(leg, -1)).toMatchObject({ x: leg.from.x });
  });

  it("moves along the curve when the leg has no road", () => {
    const set = [denver, saltLake];
    const [leg] = legsOf(set, project(set, none));
    expect(moverAt(leg, 0.5)).toEqual(planeAt(leg, 0.5));
  });

  it("fits the road, not only the stops, inside the map", () => {
    const set = [denver, saltLake];
    const bulge: Roads = { legs: [{ ...drive, points: [[39.77, -105.0], [48.0, -108.0], [40.75, -111.85]] }], interstates: [] };
    for (const [lat, lon] of bulge.legs[0].points) {
      const at = project(set, bulge)([lon, lat])!;
      expect(at[0]).toBeGreaterThanOrEqual(0);
      expect(at[0]).toBeLessThanOrEqual(960);
      expect(at[1]).toBeGreaterThanOrEqual(0);
      expect(at[1]).toBeLessThanOrEqual(520);
    }
  });

  it("zooms out far enough to take in the road of a local run", () => {
    const set = [stopAt("Denver airport", 39.86, -104.67, "flight", "airport"), denver, saltLake];
    const winding: Roads = { legs: [{ ...drive, points: [[39.77, -105.0], [43.0, -108.0], [40.75, -111.85]] }], interstates: [] };
    const projection = project(set, winding);
    const withRoad = legsOf(set, projection, winding);
    const spots = positions(set, projection);
    const held = cameraAt(set, spots, 960, 520, 0.75, withRoad);
    expect(held.w).toBeGreaterThan(cameraAt(set, spots, 960, 520, 0.75).w);
    for (const p of withRoad[1].road!.points) {
      expect(p.x).toBeGreaterThanOrEqual(held.x - 1);
      expect(p.x).toBeLessThanOrEqual(held.x + held.w + 1);
      expect(p.y).toBeGreaterThanOrEqual(held.y - 1);
      expect(p.y).toBeLessThanOrEqual(held.y + held.h + 1);
    }
  });
});

describe("the interstate layer", () => {
  const projection = project([denver, saltLake]);
  const shapes = roadShapes(roads.interstates, projection);

  it("projects each road line with its extent and middle", () => {
    expect(shapes.map((s) => s.ref)).toEqual(["I-25", "I-80"]);
    expect(shapes[0].d.startsWith("M")).toBe(true);
    expect(shapes[0].right).toBeGreaterThanOrEqual(shapes[0].left);
    expect(shapes[0].length).toBeGreaterThan(0);
    expect(roadShapes([{ ref: "I-1", points: [[40, -100]] }], projection)).toEqual([]);
  });

  it("keeps only the lines within the camera", () => {
    expect(shapes.every((s) => inView(s, { x: 0, y: 0, w: 960, h: 520 }))).toBe(true);
    expect(inView(shapes[0], { x: shapes[0].right + 50, y: shapes[0].bottom + 50, w: 100, h: 100 })).toBe(false);
    expect(inView(shapes[0], { x: shapes[0].left - 10, y: shapes[0].top - 10, w: 20, h: 20 })).toBe(true);
  });

  it("draws the roads only when the map is close enough to read them", () => {
    expect(roadsShown(projection, 1)).toBe(true);
    const world = routeProjection([stopAt("Sydney", -33.9, 151.2), denver], 960, 520);
    expect(roadsShown(world, 1)).toBe(false);
    expect(roadsShown(world, 0.1)).toBe(true);
  });

  it("labels a few roads, each well apart from the others", () => {
    const box = { x: 0, y: 0, w: 960, h: 520 };
    expect(shieldsOf(shapes, box, 1).map((s) => s.ref).sort()).toEqual(["I-25", "I-80"]);
    expect(shieldsOf([...shapes, { ...shapes[0] }], box, 1)).toHaveLength(2);
    const many = Array.from({ length: 30 }, (_, i) => ({ ...shapes[0], ref: `I-${i}`, mid: { x: 20 + i * 30, y: 20 + (i % 3) * 200 } }));
    expect(shieldsOf(many, box, 1).length).toBeLessThanOrEqual(MAX_SHIELDS);
    expect(shieldsOf([{ ...shapes[0], mid: { x: 2, y: 2 } }], box, 1)).toEqual([]);
  });
});

describe("legs that go back over a road already drawn", () => {
  const parkCity = stopAt("Park City", 40.65, -111.5);
  const again = stopAt("Denver", 39.7, -104.95);
  const house = (latitude: number, longitude: number) => stopAt("Springfield", latitude, longitude, null, "home");
  const inner = (points: { x: number; y: number }[]) => points.slice(1, -1).map((p) => [p.x, p.y]);

  it("goes back over the line of the way out, reversed, instead of a curve", () => {
    const set = [denver, saltLake, again];
    const [out, back] = legsOf(set, project(set), roads);
    expect(back.road).not.toBeNull();
    expect(back.d).not.toContain("Q");
    expect(back.vehicle).toBe("car");
    expect(back.refs).toEqual(["I-80", "I-25"]);
    expect(inner(back.road!.points)).toEqual(inner(out.road!.points).reverse());
  });

  it("drives the reused line in the other direction, ending at the stop it returns to", () => {
    const set = [denver, saltLake, again];
    const [out, back] = legsOf(set, project(set), roads);
    const there = moverAt(out, 0.5), here = moverAt(back, 0.5);
    expect(Math.cos(((there.angle - here.angle) * Math.PI) / 180)).toBeLessThan(-0.9);
    expect(moverAt(back, 0)).toMatchObject({ x: back.from.x, y: back.from.y });
    expect(moverAt(back, 1).x).toBeCloseTo(back.to.x);
    expect(moverAt(back, 1).y).toBeCloseTo(back.to.y);
    expect(distanceToPath(here, back.road!.points)).toBeLessThan(0.01);
  });

  it("follows just the stretch of the line between a nearby stop and where the trip was", () => {
    const set = [denver, saltLake, parkCity];
    const [out, hop] = legsOf(set, project(set), roads);
    expect(hop.road).not.toBeNull();
    expect(hop.d).not.toContain("Q");
    expect(hop.refs).toEqual([]);
    expect(hop.road!.along.at(-1)).toBeLessThan(out.road!.along.at(-1)! / 3);
    for (const p of inner(hop.road!.points)) expect(distanceToPath({ x: p[0], y: p[1] }, out.road!.points)).toBeLessThan(0.01);
  });

  it("returns home over the way out when home sits beside it, and still curves the way there", () => {
    const set = [house(39.9, -104.7), denver, saltLake, house(39.9, -104.7)];
    const [first, , last] = legsOf(set, project(set), roads);
    expect(first.road).toBeNull();
    expect(first.d).toContain("Q");
    expect(last.road).not.toBeNull();
    expect(last.d).not.toContain("Q");
    expect(last.refs).toEqual(["I-80", "I-25"]);
  });

  it("prefers a road the server sent for the leg over retracing", () => {
    const sent = { from_segment_id: 2, to_segment_id: 3, refs: ["I-70"], points: [[40.75, -111.85], [41.5, -108.0], [39.77, -105.0]] };
    const set = [denver, saltLake, again];
    const [, back] = legsOf(set, project(set, { legs: [drive, sent], interstates: [] }), { legs: [drive, sent], interstates: [] });
    expect(back.refs).toEqual(["I-70"]);
    expect(back.road!.points).toHaveLength(5);
  });

  it("keeps a curve for a new route, a faraway stop, a flight, a train and a cruise", () => {
    const far = stopAt("Boise", 43.6, -116.2), off = stopAt("Wichita", 37.7, -97.3);
    for (const [stop, via] of [[far, null], [off, null], [parkCity, "flight"], [parkCity, "train"], [parkCity, "cruise"]] as const) {
      const set = [denver, saltLake, { ...stop, via }];
      const last = legsOf(set, project(set), roads)[1];
      expect(last.road, `${stop.name} ${via}`).toBeNull();
      expect(last.d, `${stop.name} ${via}`).toContain("Q");
    }
  });

  it("finds nothing to retrace when nothing has been drawn, when the stops are too close together or on different lines", () => {
    expect(retraceFor(saltLake, denver, [])).toBeNull();
    expect(retraceFor(denver, { ...denver, name: "Next door" }, [{ points: drive.points, refs: [] }])).toBeNull();
    expect(retraceFor(saltLake, denver, [{ points: [[10, 10], [11, 11]], refs: [] }])).toBeNull();
    expect(retraceFor(saltLake, denver, [{ points: [[39.77, -105.0], [39.77, -105.0]], refs: [] }])).toBeNull();
  });

  it("takes the closer of two lines to retrace", () => {
    const near = { points: [[39.74, -104.99], [40.0, -108.0], [40.76, -111.89]], refs: ["I-70"] };
    expect(retraceFor(saltLake, denver, [{ points: drive.points, refs: ["I-25"] }, near])?.refs).toEqual(["I-70"]);
  });
});
