import { describe, expect, it } from "vitest";
import { frameOf, FRAME_PADDING, MIN_SPAN_DEGREES, unwrapped } from "./stats-mapkit";

describe("framing the Stats map", () => {
  it("shows the whole world when there is nothing to frame", () => {
    expect(frameOf(null)).toEqual({ x: 0, y: 0, width: 1, height: 1 });
  });

  it("frames a region with room round it, centred on it", () => {
    const r = frameOf({ west: -159.34, south: 20.9, east: -156.43, north: 21.98 });
    const span = 159.34 - 156.43;
    expect(r.width).toBeCloseTo((span * (1 + 2 * FRAME_PADDING)) / 360, 4);
    expect(r.x + r.width / 2).toBeCloseTo((-157.885 + 180) / 360, 3);
    expect(r.height).toBeGreaterThan(0);
    expect(r.y + r.height).toBeLessThan(1);
  });

  it("never frames closer than city level, whatever the places are", () => {
    const lone = frameOf({ west: -157.92, south: 21.32, east: -157.92, north: 21.32 });
    expect(lone.width).toBeCloseTo((MIN_SPAN_DEGREES * (1 + 2 * FRAME_PADDING)) / 360, 4);
    expect(lone.height).toBeGreaterThan(0.001);
  });

  it("frames a trip across the antimeridian the short way round", () => {
    const r = frameOf({ west: 151.2, south: -33.9, east: -118.4, north: 33.9 });
    expect(r.width).toBeLessThan(0.8);
    expect(r.x).toBeGreaterThan(0.8);
  });

  it("shows the whole width when the places span the world, and keeps inside the map", () => {
    const r = frameOf({ west: -179, south: -89, east: 179, north: 89 });
    expect(r.width).toBe(1);
    expect(r.y).toBeGreaterThanOrEqual(0);
    expect(r.y + r.height).toBeLessThanOrEqual(1);
  });
});

describe("drawing an arc across the map", () => {
  it("keeps the longitudes of a line across the antimeridian running on, so it isn't drawn back across the map", () => {
    const out = unwrapped([[170, 0], [178, 1], [-176, 2], [-170, 3]]);
    expect(out.map((p) => p[0])).toEqual([170, 178, 184, 190]);
    expect(out.map((p) => p[1])).toEqual([0, 1, 2, 3]);
  });

  it("leaves a line that stays on one side alone, and one going the other way round", () => {
    expect(unwrapped([[-10, 0], [10, 1]]).map((p) => p[0])).toEqual([-10, 10]);
    expect(unwrapped([[-170, 0], [-178, 1], [176, 2]]).map((p) => p[0])).toEqual([-170, -178, -184]);
  });
});
