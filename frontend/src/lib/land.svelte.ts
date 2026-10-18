import type { GeoProjection } from "d3-geo";
import { clipToWindow, detailFor, kmPerPixel, loadCountries, loadDetailedCountries, loadFineCountries, windowOf, type Country, type Detail, type Window } from "./map";

export type LandView = { projection: GeoProjection; width: number; height: number; box?: { x: number; y: number; w: number; h: number }; zoom?: number };

export type Land = { readonly features: Country[]; readonly detail: Detail };

const EXPAND = 1;

const savingData = (): boolean => (navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData === true;

export function whenIdle(run: () => void): () => void {
  if (typeof requestIdleCallback === "function") {
    const handle = requestIdleCallback(run, { timeout: 3000 });
    return () => cancelIdleCallback(handle);
  }
  const timer = setTimeout(run, 300);
  return () => clearTimeout(timer);
}

export const covers = (outer: Window | null, inner: Window | null): boolean =>
  outer !== null && inner !== null && outer.west <= inner.west && outer.east >= inner.east && outer.south <= inner.south && outer.north >= inner.north;

export const grown = (w: Window): Window => {
  const x = (w.east - w.west) * EXPAND;
  const y = (w.north - w.south) * EXPAND;
  return { west: w.west - x, east: w.east + x, south: Math.max(-90, w.south - y), north: Math.min(90, w.north + y) };
};

export function landFor(view: () => LandView): Land {
  let coarse = $state.raw<Country[]>([]);
  let medium = $state.raw<Country[] | null>(null);
  let fine = $state.raw<Country[] | null>(null);
  const wanted = $derived.by((): Detail => {
    const v = view();
    return detailFor(kmPerPixel(v.projection, v.width, v.height) / (v.zoom ?? 1));
  });

  $effect(() => {
    let gone = false;
    loadCountries().then((c) => { if (!gone) coarse = c; }, () => {});
    return () => { gone = true; };
  });

  $effect(() => {
    const detail = wanted;
    if (detail === "coarse" || savingData()) return;
    if ((detail === "medium" ? medium : fine) !== null) return;
    let gone = false;
    const stop = whenIdle(() => {
      const load = detail === "medium" ? loadDetailedCountries : loadFineCountries;
      load().then((set) => { if (gone) return; if (detail === "medium") medium = set; else fine = set; }, () => {});
    });
    return () => { gone = true; stop(); };
  });

  let clipped: { source: Country[]; window: Window | null; result: Country[] } | null = null;
  const features = $derived.by((): Country[] => {
    const v = view();
    const set = wanted === "coarse" ? null : wanted === "fine" ? (fine ?? medium) : (medium ?? fine);
    if (!set || set.length === 0) return coarse;
    const need = windowOf(v.projection, v.box ?? { x: 0, y: 0, w: v.width, h: v.height });
    if (clipped && clipped.source === set && (clipped.window === null || covers(clipped.window, need))) return clipped.result;
    const window = need ? grown(need) : null;
    clipped = { source: set, window, result: clipToWindow(set, window) };
    return clipped.result;
  });

  return { get features() { return features; }, get detail() { return wanted; } };
}
