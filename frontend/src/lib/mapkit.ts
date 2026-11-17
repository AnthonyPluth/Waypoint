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
export type MkRoute = { path?: unknown; steps?: { path?: unknown }[] };
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
  Directions?: { new (options?: Record<string, unknown>): MkDirections; Transport: { Automobile: unknown } };
};
export type Maps = { mk: Mk; failed(): boolean; onFailure(listener: () => void): () => void };

export const LOAD_MS = 6000;
export const RETRY_MS = 30000;

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
  let timer: ReturnType<typeof setTimeout> | undefined;
  const silent = new Promise<null>((resolve) => { timer = setTimeout(() => resolve(null), LOAD_MS); });
  const first = await Promise.race([apiCall<"GET /api/mapkit/token">("/api/mapkit/token", { keep: true, background: true }).catch(() => null), silent]);
  clearTimeout(timer);
  if (first?.enabled !== true || !first.script) return { maps: null, remember: first?.enabled === false };
  const mk = window.mapkit ?? (await scriptAt(first.script, LOAD_MS));
  if (!mk) return { maps: null, remember: false };
  const listeners = new Set<() => void>();
  let failedAt: number | null = null;
  const failed = () => failedAt !== null && Date.now() - failedAt < RETRY_MS;
  const fail = () => { failedAt = Date.now(); for (const l of [...listeners]) l(); };
  const recover = () => { failedAt = null; };
  try {
    mk.init({
      authorizationCallback: (done) => {
        apiCall<"GET /api/mapkit/token">("/api/mapkit/token", { keep: true, background: true }).then(
          (next) => { if (next?.enabled === true && next.token) { recover(); done(next.token); } else fail(); },
          fail,
        );
      },
      language: typeof navigator !== "undefined" ? navigator.language : undefined,
    });
    mk.addEventListener("error", fail);
    mk.addEventListener("configuration-change", (event) => { if (event.status === "Initialized") recover(); });
  } catch {
    return { maps: null, remember: false };
  }
  return { maps: { mk, failed, onFailure: (l) => {
    listeners.add(l);
    if (failed()) queueMicrotask(() => { if (listeners.has(l)) l(); });
    return () => { listeners.delete(l); };
  } }, remember: true };
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

export const PRELOAD_MS = 4000;
let preloaded = false;

export function preloadMapkit(): () => void {
  let idle: number | undefined;
  const run = () => {
    if (preloaded) return;
    preloaded = true;
    void loadMapkit();
  };
  const timer = setTimeout(() => {
    if (typeof window.requestIdleCallback === "function") idle = window.requestIdleCallback(run, { timeout: 5000 });
    else run();
  }, PRELOAD_MS);
  return () => { clearTimeout(timer); if (idle !== undefined) window.cancelIdleCallback(idle); };
}

export const forgetPreload = (): void => { preloaded = false; };
