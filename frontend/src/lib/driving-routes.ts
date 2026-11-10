import type { Mk, MkDirections, MkRoute } from "./mapkit";

export type LatLon = { latitude: number; longitude: number };
export type RoutePath = number[][];

export const ROUTE_TIMEOUT_MS = 6000;
export const ROUTE_PARALLEL = 4;
const PRECISION = 4;

const found = new Map<string, RoutePath>();
const pending = new Map<string, Promise<RoutePath | null>>();
const waiting: (() => void)[] = [];
let running = 0;
let generation = 0;

const round = (n: number): string => n.toFixed(PRECISION);
const keyOf = (a: LatLon, b: LatLon): string => `${round(a.latitude)},${round(a.longitude)}>${round(b.latitude)},${round(b.longitude)}`;

export const clearRouteCache = (): void => {
  generation++;
  found.clear();
  pending.clear();
  running = 0;
  for (const resume of waiting.splice(0)) resume();
};

const isCoordinate = (c: unknown): c is LatLon =>
  typeof c === "object" && c !== null && Number.isFinite((c as LatLon).latitude) && Number.isFinite((c as LatLon).longitude);

function flatten(path: unknown): RoutePath | null {
  if (!Array.isArray(path)) return null;
  const out: RoutePath = [];
  for (const item of path) {
    if (isCoordinate(item)) out.push([item.latitude, item.longitude]);
    else {
      const inner = Array.isArray(item) ? flatten(item) : null;
      if (!inner) return null;
      out.push(...inner);
    }
  }
  return out;
}

export function parseRoute(route: MkRoute | null | undefined): RoutePath | null {
  if (!route) return null;
  let path: RoutePath | null = [];
  if (route.path !== undefined) path = flatten(route.path);
  if (path && path.length === 0 && Array.isArray(route.steps)) {
    for (const step of route.steps) {
      const part = flatten(step?.path ?? []);
      if (!part) return null;
      path.push(...part);
    }
  }
  return path && path.length >= 2 ? path : null;
}

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
          finish(parseRoute(response?.routes?.[0]));
        },
      );
    } catch {
      finish(null);
    }
  });
}

function slot(): Promise<void> {
  if (running < ROUTE_PARALLEL) { running++; return Promise.resolve(); }
  return new Promise((resolve) => { waiting.push(resolve); });
}

function release(): void {
  const next = waiting.shift();
  if (next) next();
  else running--;
}

export function drivingRoute(mk: Mk, from: LatLon, to: LatLon, timeoutMs = ROUTE_TIMEOUT_MS): Promise<RoutePath | null> {
  const key = keyOf(from, to);
  const have = found.get(key);
  if (have) return Promise.resolve(have);
  const inFlight = pending.get(key);
  if (inFlight) return inFlight;
  const born = generation;
  const job = slot().then(() => (born === generation ? ask(mk, from, to, timeoutMs) : null)).then((path) => {
    if (born !== generation) return null;
    release();
    pending.delete(key);
    if (path) found.set(key, path);
    return path;
  });
  pending.set(key, job);
  return job;
}
