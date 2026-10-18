// @vitest-environment jsdom
import { geoMercator, geoEquirectangular } from "d3-geo";
import { flushSync } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { covers, grown, landFor, type LandView } from "./land.svelte";
import type { Country } from "./map";

const square = (name: string, west: number, south: number, east: number, north: number): Country =>
  ({ type: "Feature", id: name, properties: { name }, geometry: { type: "Polygon", coordinates: [[[west, south], [west, north], [east, north], [east, south], [west, south]]] } });

const coarseSet = [square("Quick", -180, -80, 180, 80)];
const mediumSet = [square("Near", -82, 28, -68, 42), square("Far", 100, -10, 110, 0)];
const fineSet = [square("Near", -82, 28, -68, 42), square("Far", 100, -10, 110, 0)];

const loadDetailed = vi.fn(async () => mediumSet);
const loadFine = vi.fn(async () => fineSet);

vi.mock("./map", async (original) => ({
  ...(await original<typeof import("./map")>()),
  loadCountries: async () => coarseSet,
  loadDetailedCountries: () => loadDetailed(),
  loadFineCountries: () => loadFine(),
}));

const region = () => geoMercator().fitExtent([[0, 0], [600, 400]], { type: "Polygon", coordinates: [[[-80, 30], [-80, 40], [-70, 40], [-70, 30], [-80, 30]]] });
const world = () => geoEquirectangular().fitExtent([[0, 0], [960, 500]], { type: "Sphere" });

let stop = () => {};
function mount(view: LandView) {
  let current = $state(view);
  let land!: ReturnType<typeof landFor>;
  stop = $effect.root(() => { land = landFor(() => current); });
  flushSync();
  return { land, set: (v: LandView) => { current = v; flushSync(); } };
}

const settle = async () => { await vi.advanceTimersByTimeAsync(400); flushSync(); await vi.advanceTimersByTimeAsync(0); flushSync(); };

beforeEach(() => { vi.useFakeTimers(); loadDetailed.mockClear(); loadFine.mockClear(); });
afterEach(() => { stop(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("landFor", () => {
  it("draws the quick outlines at once and never loads more at world scale", async () => {
    const { land } = mount({ projection: world(), width: 960, height: 500 });
    await settle();
    expect(land.detail).toBe("coarse");
    expect(land.features).toBe(coarseSet);
    expect(loadDetailed).not.toHaveBeenCalled();
    expect(loadFine).not.toHaveBeenCalled();
  });

  it("starts with the quick outlines on a region, then swaps in the fine ones, clipped to the view, after the page is idle", async () => {
    const { land } = mount({ projection: region(), width: 600, height: 400 });
    expect(land.detail).toBe("fine");
    await vi.advanceTimersByTimeAsync(0);
    flushSync();
    expect(land.features).toBe(coarseSet);
    expect(loadFine).not.toHaveBeenCalled();
    await settle();
    expect(loadFine).toHaveBeenCalledTimes(1);
    expect(loadDetailed).not.toHaveBeenCalled();
    expect(land.features.map((c) => c.properties?.name)).toEqual(["Near"]);
  });

  it("keeps the same outlines while the view moves inside the area already cut, and cuts again beyond it", async () => {
    const p = region();
    const { land, set } = mount({ projection: p, width: 600, height: 400 });
    await settle();
    const first = land.features;
    set({ projection: p, width: 600, height: 400, box: { x: 20, y: 10, w: 560, h: 380 } });
    expect(land.features).toBe(first);
    set({ projection: p, width: 600, height: 400, box: { x: 4000, y: 10, w: 560, h: 380 } });
    expect(land.features).not.toBe(first);
  });

  it("does not load anything finer on a data-saver connection", async () => {
    vi.stubGlobal("navigator", { connection: { saveData: true } });
    const { land } = mount({ projection: region(), width: 600, height: 400 });
    await settle();
    expect(loadFine).not.toHaveBeenCalled();
    expect(land.features).toBe(coarseSet);
  });

  it("loads the middle detail once for a continent and reuses it", async () => {
    const continent = geoMercator().fitExtent([[0, 0], [960, 500]], { type: "Polygon", coordinates: [[[-100, 10], [-100, 60], [60, 60], [60, 10], [-100, 10]]] });
    const { land, set } = mount({ projection: continent, width: 960, height: 500 });
    expect(land.detail).toBe("medium");
    await settle();
    expect(loadDetailed).toHaveBeenCalledTimes(1);
    set({ projection: continent, width: 960, height: 500, zoom: 1.0001 });
    await settle();
    expect(loadDetailed).toHaveBeenCalledTimes(1);
  });
});

describe("windows", () => {
  it("covers a window inside another and not one that sticks out", () => {
    const outer = { west: -10, south: -10, east: 10, north: 10 };
    expect(covers(outer, { west: -5, south: -5, east: 5, north: 5 })).toBe(true);
    expect(covers(outer, { west: -5, south: -5, east: 11, north: 5 })).toBe(false);
    expect(covers(null, outer)).toBe(false);
    expect(covers(outer, null)).toBe(false);
  });

  it("grows by its own size on every side and stays on the globe", () => {
    expect(grown({ west: 0, south: 80, east: 10, north: 88 })).toEqual({ west: -10, south: 72, east: 20, north: 90 });
  });
});
