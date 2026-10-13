import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { mapStyle } from "./basemap-style";

const origin = "https://waypoint.example";
const style = mapStyle(origin);
const bundled = fileURLToPath(new URL("../../../waypoint/static/map/", import.meta.url));

const fontsOf = (value: unknown): string[] => {
  if (typeof value === "string") return value.startsWith("Noto Sans") ? [value] : [];
  return Array.isArray(value) ? value.flatMap(fontsOf) : [];
};

describe("mapStyle", () => {
  it("draws from the page's own origin alone", () => {
    const addresses = JSON.stringify(style).match(/https?:\/\/[^"/]+/g) ?? [];
    expect(new Set(addresses)).toEqual(new Set([origin]));
    expect(style.glyphs).toBe(`${origin}/map/fonts/{fontstack}/{range}.pbf`);
    expect(style.sprite).toBe(`${origin}/map/sprites/dark`);
    expect(style.sources.protomaps).toEqual({ type: "vector", url: `pmtiles://${origin}/api/map/tiles` });
  });

  it("uses only the fonts, glyph ranges and sprite that ship with Waypoint", () => {
    const fonts = new Set(style.layers.flatMap((l) => fontsOf((l as { layout?: Record<string, unknown> }).layout?.["text-font"])));
    expect(fonts.size).toBeGreaterThan(0);
    for (const font of fonts) {
      for (const range of ["0-255", "256-511", "8192-8447"]) expect(existsSync(`${bundled}fonts/${font}/${range}.pbf`), `${font} ${range}`).toBe(true);
    }
    for (const file of ["dark.json", "dark.png", "dark@2x.json", "dark@2x.png"]) expect(existsSync(`${bundled}sprites/${file}`), file).toBe(true);
  });

  it("has the dark flavor's layers on the one source", () => {
    expect(style.layers.length).toBeGreaterThan(40);
    expect(new Set(style.layers.map((l) => (l as { source?: string }).source).filter(Boolean))).toEqual(new Set(["protomaps"]));
  });
});
