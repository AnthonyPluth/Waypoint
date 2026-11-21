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
const over = (fg: string, bg: string, alpha: number) =>
  "#" + [1, 3, 5].map((i) => Math.round(alpha * parseInt(fg.slice(i, i + 2), 16) + (1 - alpha) * parseInt(bg.slice(i, i + 2), 16)).toString(16).padStart(2, "0")).join("");
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

describe("the dark palette", () => {
  it("is the only palette", () => {
    expect(css).not.toContain("prefers-color-scheme");
    expect(tokens.get("background")).toBe("#0d0c12");
    expect(root).toContain("color-scheme: dark");
  });
  it("is the raised slate: a card, hairline, header strip and secondary fill lighter than the page", () => {
    expect(tokens.get("card")).toBe("#1a1922");
    expect(tokens.get("border")).toBe("#2e2d38");
    expect(tokens.get("card-header")).toBe("#201f2a");
    for (const fill of ["secondary", "muted", "accent", "surface-3"]) expect(tokens.get(fill)).toBe("#262531");
    expect(contrast(resolve("card"), resolve("background"))).toBeGreaterThanOrEqual(1.1);
    expect(contrast(resolve("card-header"), resolve("card"))).toBeGreaterThanOrEqual(1.03);
    expect(contrast(resolve("secondary"), resolve("card"))).toBeGreaterThanOrEqual(1.1);
    expect(contrast(resolve("border"), resolve("card"))).toBeGreaterThanOrEqual(1.1);
  });
  it.each(["foreground", "muted-foreground", "label"])("keeps %s at WCAG AA on the card, its header strip and the secondary fill", (text) => {
    for (const surface of ["card", "card-header", "secondary"]) {
      expect(contrast(resolve(text), resolve(surface))).toBeGreaterThanOrEqual(4.5);
    }
  });
  it.each(["ok", "warn", "bad", "info", "quiet"])("keeps %s chip text at WCAG AA contrast on its own background and on the surfaces", (tone) => {
    const ink = resolve(`status-${tone}-ink`);
    expect(contrast(ink, resolve(`status-${tone}-soft`))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(ink, resolve("card"))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(ink, resolve("background"))).toBeGreaterThanOrEqual(4.5);
  });
  it.each(["card", "card-header", "popover"])("keeps the featured trip pill's ink at WCAG AA on primary/15 over %s, with or without the stub's primary/8 under it", (surface) => {
    const base = resolve(surface);
    for (const under of [base, over(resolve("primary"), base, 0.08)]) {
      expect(contrast(resolve("primary-ink"), over(resolve("primary"), under, 0.15))).toBeGreaterThanOrEqual(4.5);
    }
  });
  it("keeps the secondary trip pill's grey at WCAG AA on the secondary fill", () => {
    expect(contrast(resolve("muted-foreground"), resolve("secondary"))).toBeGreaterThanOrEqual(4.5);
  });
  it("keeps white text at WCAG AA on the destructive badge over the card and the page", () => {
    for (const surface of ["card", "background"]) {
      expect(contrast("#ffffff", over(resolve("destructive"), resolve(surface), 0.6))).toBeGreaterThanOrEqual(4.5);
    }
  });
  it("keeps body and muted text readable on the surfaces", () => {
    for (const surface of ["background", "card", "card-header", "surface-3"]) {
      expect(contrast(resolve("foreground"), resolve(surface))).toBeGreaterThanOrEqual(7);
      expect(contrast(resolve("muted-foreground"), resolve(surface))).toBeGreaterThanOrEqual(4.5);
    }
  });
  it.each(["label", "muted-foreground"])("keeps the %s grey at 4.5:1 on the page and the card", (grey) => {
    expect(contrast(resolve(grey), resolve("background"))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(resolve(grey), resolve("card"))).toBeGreaterThanOrEqual(4.5);
  });
  it.each(["flight", "stay", "car", "train", "cruise", "parking"])("draws the %s kind colour at 3:1 on the card", (kind) => {
    expect(contrast(resolve(`kind-${kind}`), resolve("card"))).toBeGreaterThanOrEqual(3);
  });
  it.each(["car", "stay"])("keeps the %s kind colour apart from every status colour", (kind) => {
    const own = resolve(`kind-${kind}`).toLowerCase();
    for (const status of ["primary", "success", "signal", "destructive"]) {
      expect(own).not.toBe(resolve(status).toLowerCase());
    }
  });
  it("gives the flight and car kinds values of their own", () => {
    expect(tokens.get("kind-flight")).toMatch(/^#[0-9a-f]{6}$/i);
    expect(tokens.get("kind-car")).toMatch(/^#[0-9a-f]{6}$/i);
  });
  it.each(["chart-1", "chart-2", "chart-3", "chart-4"])("draws %s legibly on the card and the page", (series) => {
    expect(contrast(resolve(series), resolve("card"))).toBeGreaterThanOrEqual(3);
    expect(contrast(resolve(series), resolve("background"))).toBeGreaterThanOrEqual(3);
  });
  it.each(["map-route", "map-airport", "map-stay", "map-visited", "map-photo"])("draws %s legibly on the sea and the land", (mark) => {
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
    const afterSwitch = reduced.slice(reduced.indexOf("}\n}") + 3);
    expect(afterSwitch.trim()).toBe("");
    expect(reduced).not.toMatch(/@keyframes|\banimation:|\btransition:/);
  });
});
