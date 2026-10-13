import type { GeoProjection } from "d3-geo";
import type { Box } from "$lib/route-replay";

export const MAX_MAP_ZOOM = 10;
export const MAP_TILE_SIZE = 512;
export const TILES_PATH = "/api/map/tiles";
export const ATTRIBUTION_LINK = "https://www.openstreetmap.org/copyright";

export type Look = { box: Box; center: [number, number]; zoom: number };

export function look(box: Box, projection: GeoProjection, cssWidth: number): Look {
  const circumference = 2 * Math.PI * projection.scale();
  let zoom = Math.log2((circumference * cssWidth) / (box.w * MAP_TILE_SIZE));
  let seen = box;
  if (zoom > MAX_MAP_ZOOM) {
    const grow = 2 ** (zoom - MAX_MAP_ZOOM);
    const w = box.w * grow, h = box.h * grow;
    seen = { x: box.x + box.w / 2 - w / 2, y: box.y + box.h / 2 - h / 2, w, h };
    zoom = MAX_MAP_ZOOM;
  }
  const at = projection.invert?.([seen.x + seen.w / 2, seen.y + seen.h / 2]) ?? [0, 0];
  return { box: seen, center: [at[0], at[1]], zoom };
}
