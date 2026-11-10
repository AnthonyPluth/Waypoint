import { apiCall } from "$lib/contract";

export type MkCoordinate = { latitude: number; longitude: number };
export type MkAnnotation = { coordinate: MkCoordinate; visible: boolean };
export type MkOverlay = { points: MkCoordinate[] };
export type MkMap = {
  addAnnotation(annotation: MkAnnotation): void;
  removeAnnotation(annotation: MkAnnotation): void;
  addOverlay(overlay: MkOverlay): void;
  removeOverlay(overlay: MkOverlay): void;
  setVisibleMapRectAnimated(rect: object, animate: boolean): void;
  destroy(): void;
};
export type MkRoute = { path?: MkCoordinate[][] };
export type MkDirectionsRequest = { origin: MkCoordinate; destination: MkCoordinate; transportType: unknown };
export type MkDirections = {
  route(request: MkDirectionsRequest, callback: (error: unknown, response?: { routes?: MkRoute[] } | null) => void): number;
  cancel?(id: number): void;
};
export type MkEvent = { status?: string };
export type Mk = {
  init(options: { authorizationCallback: (done: (token: string) => void) => void; language?: string }): void;
  addEventListener(type: string, listener: (event: MkEvent) => void): void;
  removeEventListener(type: string, listener: (event: MkEvent) => void): void;
  Map: { new (host: HTMLElement, options: Record<string, unknown>): MkMap; ColorSchemes: { Dark: unknown } };
  FeatureVisibility: { Hidden: unknown };
  Coordinate: new (latitude: number, longitude: number) => MkCoordinate;
  MapRect: new (x: number, y: number, width: number, height: number) => object;
  Annotation: new (coordinate: MkCoordinate, factory: () => HTMLElement, options?: Record<string, unknown>) => MkAnnotation;
  PolylineOverlay: new (points: MkCoordinate[], options?: { style?: object }) => MkOverlay;
  Style: new (options: Record<string, unknown>) => object;
  // Absent in an old MapKit; callers must cope without it.
  Directions?: { new (options?: Record<string, unknown>): MkDirections; Transport: { Automobile: unknown } };
};
export type Maps = { mk: Mk; onFailure(listener: () => void): () => void };

export const LOAD_MS = 6000;

declare global {
  interface Window { mapkit?: Mk }
}

let session: Promise<Maps | null> | null = null;

function scriptAt(src: string, timeoutMs: number): Promise<Mk | null> {
  return new Promise((resolve) => {
    const tag = document.createElement("script");
    const done = (found: Mk | null) => { clearTimeout(timer); tag.onload = null; tag.onerror = null; resolve(found); };
    const timer = setTimeout(() => { tag.remove(); done(null); }, timeoutMs);
    const nonce = document.querySelector<HTMLScriptElement>("script[nonce]")?.nonce;
    if (nonce) tag.nonce = nonce;
    tag.crossOrigin = "anonymous";
    tag.async = true;
    tag.onload = () => done(window.mapkit ?? null);
    tag.onerror = () => { tag.remove(); done(null); };
    tag.src = src;
    document.head.append(tag);
  });
}

async function start(): Promise<{ maps: Maps | null; remember: boolean }> {
  const first = await apiCall<"GET /api/mapkit/token">("/api/mapkit/token").catch(() => null);
  if (first?.enabled !== true || !first.script) return { maps: null, remember: first?.enabled === false };
  const mk = window.mapkit ?? (await scriptAt(first.script, LOAD_MS));
  if (!mk) return { maps: null, remember: false };
  const listeners = new Set<() => void>();
  const fail = () => { for (const l of [...listeners]) l(); };
  try {
    mk.init({
      authorizationCallback: (done) => {
        apiCall<"GET /api/mapkit/token">("/api/mapkit/token").then(
          (next) => { if (next?.enabled === true && next.token) done(next.token); else fail(); },
          fail,
        );
      },
      language: typeof navigator !== "undefined" ? navigator.language : undefined,
    });
    mk.addEventListener("error", fail);
  } catch {
    return { maps: null, remember: false };
  }
  return { maps: { mk, onFailure: (l) => { listeners.add(l); return () => { listeners.delete(l); }; } }, remember: true };
}

export function loadMapkit(): Promise<Maps | null> {
  if (session) return session;
  const attempt = start().then(({ maps, remember }) => {
    if (!remember && session === attempt) session = null;
    return maps;
  });
  session = attempt;
  return attempt;
}

export const forgetMapkit = (): void => { session = null; };
