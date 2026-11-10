import type { Mk, MkDirections } from "./mapkit";

export type LatLon = { latitude: number; longitude: number };
export type RoutePath = number[][];

export const ROUTE_TIMEOUT_MS = 6000;
export const ROUTE_PARALLEL = 4;
const PRECISION = 4;

const found = new Map<string, RoutePath>();
const pending = new Map<string, Promise<RoutePath | null>>();
const waiting: (() => void)[] = [];
let running = 0;

const round = (n: number): string => n.toFixed(PRECISION);
const keyOf = (a: LatLon, b: LatLon): string => `${round(a.latitude)},${round(a.longitude)}>${round(b.latitude)},${round(b.longitude)}`;

export const clearRouteCache = (): void => { found.clear(); pending.clear(); waiting.length = 0; running = 0; };

function giveUp(directions: MkDirections | undefined, id: number): void {
  try {
    directions?.cancel?.(id);
  } catch {
    return;
  }
}

function ask(mk: Mk, from: LatLon, to: LatLon, timeoutMs: number): Promise<RoutePath | null> {
  return new Promise((resolve) => {
    let finished = false;
    let id: number | undefined;
    let directions: MkDirections | undefined;
    const finish = (value: RoutePath | null) => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      resolve(value);
    };
    const timer = setTimeout(() => {
      if (id !== undefined) giveUp(directions, id);
      finish(null);
    }, timeoutMs);
    try {
      const Directions = mk.Directions;
      if (!Directions) { finish(null); return; }
      directions = new Directions();
      id = directions.route(
        { origin: new mk.Coordinate(from.latitude, from.longitude), destination: new mk.Coordinate(to.latitude, to.longitude), transportType: Directions.Transport.Automobile },
        (error, response) => {
          if (error) { finish(null); return; }
          const path: RoutePath = [];
          for (const part of response?.routes?.[0]?.path ?? []) for (const c of part) if (Number.isFinite(c.latitude) && Number.isFinite(c.longitude)) path.push([c.latitude, c.longitude]);
          finish(path.length >= 2 ? path : null);
        },
      );
    } catch {
      finish(null);
    }
  });
}

function slot(): Promise<void> {
  if (running < ROUTE_PARALLEL) { running++; return Promise.resolve(); }
  return new Promise((resolve) => { waiting.push(() => { running++; resolve(); }); });
}

function release(): void {
  running--;
  waiting.shift()?.();
}

export function drivingRoute(mk: Mk, from: LatLon, to: LatLon, timeoutMs = ROUTE_TIMEOUT_MS): Promise<RoutePath | null> {
  const key = keyOf(from, to);
  const have = found.get(key);
  if (have) return Promise.resolve(have);
  const inFlight = pending.get(key);
  if (inFlight) return inFlight;
  const job = slot().then(() => ask(mk, from, to, timeoutMs)).then((path) => {
    release();
    pending.delete(key);
    if (path) found.set(key, path);
    return path;
  });
  pending.set(key, job);
  return job;
}
