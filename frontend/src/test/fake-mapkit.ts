import type { Maps, Mk, MkAnnotation, MkCoordinate, MkDirectionsRequest, MkEvent, MkOverlay } from "$lib/mapkit";

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

export type DirectionsMode = "ok" | "error" | "empty" | "hang" | "throw";
export type DirectionsCall = { origin: MkCoordinate; destination: MkCoordinate; transportType: unknown };

export const windingPath = (from: MkCoordinate, to: MkCoordinate, steps = 12): MkCoordinate[][] => {
  const part: MkCoordinate[] = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const wave = Math.sin(t * Math.PI * 3) * 0.05 * Math.min(1, Math.hypot(to.latitude - from.latitude, to.longitude - from.longitude));
    part.push({ latitude: from.latitude + (to.latitude - from.latitude) * t + wave, longitude: from.longitude + (to.longitude - from.longitude) * t - wave });
  }
  return [part.slice(0, 7), part.slice(7)];
};

const listeners = new Map<string, Set<(e: MkEvent) => void>>();

export const fake = {
  maps: [] as FakeMap[],
  inits: [] as { authorizationCallback: (done: (token: string) => void) => void; language?: string }[],
  broken: false,
  directions: { mode: "ok" as DirectionsMode, calls: [] as DirectionsCall[], cancelled: [] as number[] },
  last: (): FakeMap => fake.maps[fake.maps.length - 1],
  emit: (type: string, event: MkEvent = {}) => { for (const l of [...(listeners.get(type) ?? [])]) l(event); },
  listening: (type: string) => listeners.get(type)?.size ?? 0,
  reset: () => { fake.maps = []; fake.inits = []; fake.broken = false; fake.directions = { mode: "ok", calls: [], cancelled: [] }; listeners.clear(); },
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
  Annotation: class {
    visible = true;
    constructor(public coordinate: MkCoordinate, readonly factory: () => HTMLElement, readonly options: Record<string, unknown> = {}) { this.visible = options.visible !== false; }
  } as unknown as Mk["Annotation"],
  PolylineOverlay: class {
    constructor(public points: MkCoordinate[], readonly options: { style?: object } = {}) {}
  } as unknown as Mk["PolylineOverlay"],
  Style: class { constructor(readonly options: Record<string, unknown>) {} } as unknown as Mk["Style"],
  Directions: Object.assign(
    class {
      route(request: MkDirectionsRequest, callback: (error: unknown, response?: { routes?: { path?: MkCoordinate[][] }[] } | null) => void): number {
        const { mode } = fake.directions;
        if (mode === "throw") throw new Error("Directions failed");
        fake.directions.calls.push({ origin: request.origin, destination: request.destination, transportType: request.transportType });
        const id = fake.directions.calls.length;
        if (mode === "hang") return id;
        setTimeout(() => {
          if (mode === "error") callback(new Error("Directions error"), null);
          else if (mode === "empty") callback(null, { routes: [] });
          else callback(null, { routes: [{ path: windingPath(request.origin, request.destination) }] });
        }, 0);
        return id;
      }
      cancel(id: number): void { fake.directions.cancelled.push(id); }
    },
    { Transport: { Automobile: "automobile", Walking: "walking" } },
  ) as unknown as NonNullable<Mk["Directions"]>,
};

export const fakeMaps = (): Maps & { fail(): void; watching(): number } => {
  const failures = new Set<() => void>();
  return { mk: fakeMk, onFailure: (l) => { failures.add(l); return () => { failures.delete(l); }; }, fail: () => { for (const l of [...failures]) l(); }, watching: () => failures.size };
};
