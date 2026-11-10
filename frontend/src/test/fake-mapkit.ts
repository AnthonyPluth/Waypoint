import type { Maps, Mk, MkAnnotation, MkCoordinate, MkEvent, MkOverlay } from "$lib/mapkit";

export type FakeAnnotation = MkAnnotation & { factory: () => HTMLElement; options: Record<string, unknown> };
export type FakeOverlay = MkOverlay & { options: { style?: FakeStyle } };
export type FakeStyle = { options: Record<string, unknown> };
export type FakeRect = { x: number; y: number; width: number; height: number };

export class FakeMap {
  annotations = new Set<FakeAnnotation>();
  overlays = new Set<FakeOverlay>();
  rects: FakeRect[] = [];
  destroyed = false;
  constructor(readonly host: HTMLElement, readonly options: Record<string, unknown>) { fake.maps.push(this); }
  addAnnotation(a: FakeAnnotation) { if (fake.broken) throw new Error("MapKit failed"); this.annotations.add(a); }
  removeAnnotation(a: FakeAnnotation) { this.annotations.delete(a); }
  addOverlay(o: FakeOverlay) { if (fake.broken) throw new Error("MapKit failed"); this.overlays.add(o); }
  removeOverlay(o: FakeOverlay) { this.overlays.delete(o); }
  setVisibleMapRectAnimated(rect: object, animate: boolean) { this.rects.push({ ...(rect as FakeRect), animate } as FakeRect); }
  destroy() { this.destroyed = true; }
}

const listeners = new Map<string, Set<(e: MkEvent) => void>>();

export const fake = {
  maps: [] as FakeMap[],
  inits: [] as { authorizationCallback: (done: (token: string) => void) => void; language?: string }[],
  broken: false,
  last: (): FakeMap => fake.maps[fake.maps.length - 1],
  emit: (type: string, event: MkEvent = {}) => { for (const l of [...(listeners.get(type) ?? [])]) l(event); },
  listening: (type: string) => listeners.get(type)?.size ?? 0,
  reset: () => { fake.maps = []; fake.inits = []; fake.broken = false; listeners.clear(); },
};

export const fakeMk: Mk = {
  init: (options) => { fake.inits.push(options); },
  addEventListener: (type, l) => { (listeners.get(type) ?? listeners.set(type, new Set()).get(type)!).add(l); },
  removeEventListener: (type, l) => { listeners.get(type)?.delete(l); },
  Map: Object.assign(FakeMap as unknown as Mk["Map"], { ColorSchemes: { Dark: "dark" } }),
  FeatureVisibility: { Hidden: "hidden" },
  Coordinate: class { constructor(readonly latitude: number, readonly longitude: number) {} } as unknown as Mk["Coordinate"],
  MapRect: class {
    constructor(readonly x: number, readonly y: number, readonly width: number, readonly height: number) {
      for (const v of [x, y, width, height]) if (!(v >= 0 && v <= 1)) throw new RangeError(`MapRect values are normalized to 0..1, got ${v}`);
      if (y + height > 1) throw new RangeError("MapRect reaches outside the world");
    }
  } as unknown as Mk["MapRect"],
  // Like real MapKit JS for a factory-made annotation: once added, it stays on the map until removeAnnotation. `visible` is kept
  // as a field but hides nothing here, so code that relies on it to take something down fails its tests.
  Annotation: class {
    visible = true;
    constructor(public coordinate: MkCoordinate, readonly factory: () => HTMLElement, readonly options: Record<string, unknown> = {}) { this.visible = options.visible !== false; }
  } as unknown as Mk["Annotation"],
  PolylineOverlay: class {
    constructor(public points: MkCoordinate[], readonly options: { style?: object } = {}) {}
  } as unknown as Mk["PolylineOverlay"],
  Style: class { constructor(readonly options: Record<string, unknown>) {} } as unknown as Mk["Style"],
};

export const fakeMaps = (): Maps & { fail(): void; watching(): number } => {
  const failures = new Set<() => void>();
  return { mk: fakeMk, onFailure: (l) => { failures.add(l); return () => { failures.delete(l); }; }, fail: () => { for (const l of [...failures]) l(); }, watching: () => failures.size };
};
