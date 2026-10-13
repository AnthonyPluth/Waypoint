import { geoMercator } from "d3-geo";
import { describe, expect, it } from "vitest";
import { look, MAP_TILE_SIZE, MAX_MAP_ZOOM } from "./basemap";

const projection = geoMercator().scale(1000).translate([480, 260]);
const full = { x: 0, y: 0, w: 960, h: 520 };

describe("look", () => {
  it("centres on the middle of the box and zooms so the box fills the map", () => {
    const seen = look(full, projection, 960);
    expect(seen.center[0]).toBeCloseTo(0, 6);
    expect(seen.center[1]).toBeCloseTo(0, 6);
    expect(seen.zoom).toBeCloseTo(Math.log2((2 * Math.PI * 1000) / MAP_TILE_SIZE), 9);
    expect(seen.box).toEqual(full);
  });

  it("zooms in by one level for each halving of the box, and out when the map is narrower", () => {
    const base = look(full, projection, 960).zoom;
    expect(look({ x: 240, y: 130, w: 480, h: 260 }, projection, 960).zoom).toBeCloseTo(base + 1, 9);
    expect(look(full, projection, 480).zoom).toBeCloseTo(base - 1, 9);
    expect(look(full, projection, 1920).zoom).toBeCloseTo(base + 1, 9);
  });

  it("follows the box's centre, not the whole picture's", () => {
    const seen = look({ x: 480, y: 130, w: 480, h: 260 }, projection, 960);
    expect(seen.center).toEqual(projection.invert!([720, 260]));
  });

  it("puts a place on the same pixel the overlay draws it, whatever the camera", () => {
    for (const box of [full, { x: 100, y: 60, w: 480, h: 260 }, { x: 520, y: 200, w: 120, h: 65 }]) {
      const cssWidth = 800;
      const seen = look(box, projection, cssWidth);
      const world = MAP_TILE_SIZE * 2 ** seen.zoom;
      const at = (lon: number, lat: number) => ({ x: ((lon + 180) / 360) * world, y: (0.5 - Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360)) / (2 * Math.PI)) * world });
      const mid = at(seen.center[0], seen.center[1]);
      for (const place of [[-93.2, 44.9], [-74, 40.7], [2.3, 48.9]] as [number, number][]) {
        const drawn = projection(place)!;
        const shown = at(place[0], place[1]);
        const k = cssWidth / seen.box.w;
        expect(shown.x - mid.x + cssWidth / 2).toBeCloseTo((drawn[0] - seen.box.x) * k, 4);
        expect(shown.y - mid.y + (cssWidth * seen.box.h) / seen.box.w / 2).toBeCloseTo((drawn[1] - seen.box.y) * k, 4);
      }
    }
  });

  it("never zooms past the level where the tiles run out, widening the view around the same centre instead", () => {
    const tight = { x: 470, y: 255, w: 4, h: 2.17 };
    const seen = look(tight, projection, 960);
    expect(seen.zoom).toBe(MAX_MAP_ZOOM);
    expect(seen.box.w).toBeGreaterThan(tight.w);
    expect(seen.box.h / seen.box.w).toBeCloseTo(tight.h / tight.w, 9);
    expect(seen.box.x + seen.box.w / 2).toBeCloseTo(tight.x + tight.w / 2, 9);
    expect(seen.box.y + seen.box.h / 2).toBeCloseTo(tight.y + tight.h / 2, 9);
    expect(look(seen.box, projection, 960).zoom).toBeCloseTo(MAX_MAP_ZOOM, 9);
  });

  it("falls back to 0, 0 for a projection that can't be inverted", () => {
    const flat = Object.assign((p: [number, number]) => p, { scale: () => 100 }) as never;
    expect(look(full, flat, 960).center).toEqual([0, 0]);
  });
});
