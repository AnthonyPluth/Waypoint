import { describe, expect, it } from "vitest";
import { BOUNDARY_MIN_SCALE, NO_BOUNDARIES, boundariesShown, boundaryShapes, inView, routeProjection, type Boundaries, type Stop } from "./route-replay";

const stopAt = (name: string, latitude: number, longitude: number, kind: Stop["kind"] = "stay"): Stop =>
  ({ name, city: name, code: null, kind, latitude, longitude, from: "2025-12-05T15:00", to: "2025-12-06T11:00", via: null, back: false });
const denver = stopAt("Denver", 39.74, -104.99), saltLake = stopAt("Salt Lake City", 40.76, -111.89), sydney = stopAt("Sydney", -33.9, 151.2, "airport");
const lines: Boundaries = [
  { points: [[37.0, -109.05], [41.0, -109.05]] },
  { points: [[41.0, -111.05], [41.0, -104.05]] },
  { points: [[45.0, -75.0], [44.0, -73.4]] },
];
const project = (set: Stop[]) => routeProjection(set, 960, 520);

describe("the state lines layer", () => {
  const projection = project([denver, saltLake]);
  const shapes = boundaryShapes(lines, projection);

  it("projects each line with the extent it covers", () => {
    expect(shapes).toHaveLength(3);
    expect(shapes[0].d.startsWith("M")).toBe(true);
    expect(shapes[0].d.match(/L/g)).toHaveLength(1);
    for (const s of shapes) {
      expect(s.right).toBeGreaterThanOrEqual(s.left);
      expect(s.bottom).toBeGreaterThanOrEqual(s.top);
    }
  });

  it("skips a line with fewer than two points", () => {
    expect(boundaryShapes([{ points: [[40, -100]] }, { points: [] }], projection)).toEqual([]);
    expect(boundaryShapes(NO_BOUNDARIES, projection)).toEqual([]);
  });

  it("keeps only the lines within the camera", () => {
    const near = { x: shapes[0].left - 15, y: shapes[0].bottom - 15, w: 30, h: 30 };
    expect(shapes.filter((s) => inView(s, near))).toEqual([shapes[0]]);
    expect(shapes.filter((s) => inView(s, { x: 0, y: 0, w: 960, h: 520 }))).toEqual(shapes.slice(0, 2));
    expect(shapes.filter((s) => inView(s, { x: -500, y: -500, w: 10, h: 10 }))).toEqual([]);
  });

  it("shows the lines on a map of the United States and when the camera is close, not on a map of the world", () => {
    expect(boundariesShown(projection, 1)).toBe(true);
    expect(boundariesShown(projection, 0.3)).toBe(true);
    const world = project([sydney, denver, saltLake]);
    expect(world.scale()).toBeLessThan(BOUNDARY_MIN_SCALE);
    expect(boundariesShown(world, 1)).toBe(false);
    expect(boundariesShown(world, 0.25)).toBe(true);
  });

  it("hides them when the camera is wide enough that the map is too coarse to carry them", () => {
    const wide = project([denver, stopAt("Boston", 42.36, -71.06)]);
    expect(boundariesShown(wide, 1)).toBe(wide.scale() >= BOUNDARY_MIN_SCALE);
    expect(boundariesShown(wide, 10)).toBe(false);
  });
});

describe("the state lines on long flights", () => {
  const seattle = stopAt("Seattle", 47.45, -122.31, "airport"), miami = stopAt("Miami", 25.79, -80.29, "airport");
  const portland = stopAt("Portland", 43.65, -70.31, "airport"), sanDiego = stopAt("San Diego", 32.73, -117.19, "airport");

  it("shows at the full view of a coast-to-coast flight at phone, tablet and desktop widths", () => {
    for (const [width, height] of [[600, 640], [960, 520]]) {
      for (const pair of [[seattle, miami], [sanDiego, portland]]) {
        const projection = routeProjection(pair, width, height);
        expect(projection.scale(), `${pair[0].name} ${width}`).toBeGreaterThan(BOUNDARY_MIN_SCALE);
        expect(boundariesShown(projection, 1)).toBe(true);
      }
    }
  });

  it("keeps a line that runs through the middle of the flight in view", () => {
    const projection = routeProjection([seattle, miami], 960, 520);
    const middle = boundaryShapes([{ points: [[44.0, -100.0], [30.0, -100.0]] }], projection);
    expect(middle.filter((s) => inView(s, { x: 0, y: 0, w: 960, h: 520 }))).toHaveLength(1);
  });
});
