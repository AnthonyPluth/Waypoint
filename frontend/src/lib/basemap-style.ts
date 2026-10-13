import { layers, namedFlavor } from "@protomaps/basemaps";
import type { LayerSpecification, StyleSpecification } from "maplibre-gl";
import { TILES_PATH } from "$lib/basemap";

export function mapStyle(origin: string): StyleSpecification {
  return {
    version: 8,
    glyphs: `${origin}/map/fonts/{fontstack}/{range}.pbf`,
    sprite: `${origin}/map/sprites/dark`,
    sources: { protomaps: { type: "vector", url: `pmtiles://${origin}${TILES_PATH}` } },
    layers: layers("protomaps", namedFlavor("dark"), { lang: "en" }) as LayerSpecification[],
  };
}
