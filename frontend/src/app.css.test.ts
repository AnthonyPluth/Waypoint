import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("./app.css", import.meta.url), "utf8");
const root = css.slice(css.indexOf(":root {"), css.indexOf("}", css.indexOf(":root {")));
const tokens = new Map([...root.matchAll(/--([\w-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));

function resolve(name: string): string {
  let value = tokens.get(name);
  for (let hops = 0; value?.startsWith("var("); hops++) {
    if (hops > 5) throw new Error(`--${name} loops`);
    value = tokens.get(value.slice(6, -1));
  }
  if (!value || !/^#[0-9a-f]{6}$/i.test(value)) throw new Error(`--${name} is not a hex colour: ${value}`);
  return value;
}

const channel = (v: number) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => channel(parseInt(hex.slice(i, i + 2), 16) / 255));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

describe("the dark palette", () => {
  it("is the only palette", () => {
    expect(css).not.toContain("prefers-color-scheme");
    expect(tokens.get("background")).toBe("#07090e");
    expect(root).toContain("color-scheme: dark");
  });
  it.each(["ok", "warn", "bad", "info", "quiet"])("keeps %s chip text at WCAG AA contrast on its own background and on the surfaces", (tone) => {
    const ink = resolve(`status-${tone}-ink`);
    expect(contrast(ink, resolve(`status-${tone}-soft`))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(ink, resolve("card"))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(ink, resolve("background"))).toBeGreaterThanOrEqual(4.5);
  });
  it("keeps body and muted text readable on the surfaces", () => {
    for (const surface of ["background", "card", "surface-3"]) {
      expect(contrast(resolve("foreground"), resolve(surface))).toBeGreaterThanOrEqual(7);
      expect(contrast(resolve("muted-foreground"), resolve(surface))).toBeGreaterThanOrEqual(4.5);
    }
  });
  it.each(["chart-1", "chart-2", "chart-3", "chart-4"])("draws %s legibly on the card and the page", (series) => {
    expect(contrast(resolve(series), resolve("card"))).toBeGreaterThanOrEqual(3);
    expect(contrast(resolve(series), resolve("background"))).toBeGreaterThanOrEqual(3);
  });
  it.each(["map-route", "map-airport", "map-stay", "map-visited"])("draws %s legibly on the sea and the land", (mark) => {
    expect(contrast(resolve(mark), resolve("map-sea"))).toBeGreaterThanOrEqual(3);
    expect(contrast(resolve(mark), resolve("map-land"))).toBeGreaterThanOrEqual(3);
  });
  it("tells the land from the sea and its borders from the land", () => {
    expect(contrast(resolve("map-land"), resolve("map-sea"))).toBeGreaterThanOrEqual(1.1);
    expect(contrast(resolve("map-border"), resolve("map-land"))).toBeGreaterThanOrEqual(1.3);
  });
});

describe("motion", () => {
  const reduced = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"));
  it("switches every animation and transition off under prefers-reduced-motion", () => {
    expect(reduced).toMatch(/\*, ::before, ::after \{[^}]*animation-duration: 0\.01ms !important/);
    expect(reduced).toMatch(/transition-duration: 0\.01ms !important/);
    expect(reduced).toMatch(/animation-iteration-count: 1 !important/);
  });
  it("puts no animation outside that switch", () => {
    expect(css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)") + reduced.length)).toBe("");
  });
});
