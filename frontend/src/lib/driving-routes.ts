import { ignoreFailure } from "./act";
import { apiCall } from "./contract";
import type { Mk, MkDirections, MkRoute } from "./mapkit";
import { driveKey, type Roads, type SavedLeg, type Stop } from "./route-replay";

export type LatLon = { latitude: number; longitude: number };
export type RoutePath = number[][];

export const ROUTE_TIMEOUT_MS = 6000;
export const LOOKUP_TIMEOUT_MS = 3000;
export const ROUTE_PARALLEL = 4;
const PRECISION = 4;
export const SERVER_MAX_POINTS = 10000;
export const SERVER_MAX_DRIVES = 30;
export const CARD_POINTS = 300;
export const CARD_TRIPS = 12;
export const CARD_WAIT_MS = 40;
const NO_SAVED: SavedRoutes = new Map();

export type SavedRoutes = ReadonlyMap<string, RoutePath>;

const found = new Map<string, RoutePath>();
const forCards = new Map<number, Promise<SavedRoutes>>();
const queued: { trip: number; resolve: (routes: SavedRoutes) => void }[] = [];
let queuedTimer: ReturnType<typeof setTimeout> | undefined;
const onServer = new Set<string>();
const sharing = new Set<string>();
const pending = new Map<string, Promise<RoutePath | null>>();
const waiting: (() => void)[] = [];
let running = 0;
let generation = 0;

const round = (n: number): string => n.toFixed(PRECISION);
const keyOf = driveKey;
const tripKey = (trip: number, key: string): string => `${trip}:${key}`;

export const clearRouteCache = (): void => {
  generation++;
  found.clear();
  onServer.clear();
  sharing.clear();
  pending.clear();
  forCards.clear();
  clearTimeout(queuedTimer);
  for (const waiting of queued.splice(0)) waiting.resolve(NO_SAVED);
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

export type Drive = { from: LatLon; to: LatLon };

const isPath = (path: unknown): path is RoutePath =>
  Array.isArray(path) && path.length >= 2 && path.every((p) => Array.isArray(p) && p.length === 2 && Number.isFinite(p[0]) && Number.isFinite(p[1]));

export function thin(path: RoutePath, limit = SERVER_MAX_POINTS): RoutePath {
  if (path.length <= limit) return path;
  return Array.from({ length: limit }, (_, i) => path[Math.round((i * (path.length - 1)) / (limit - 1))]);
}

async function fromServer(trip: number, drives: Drive[], born: number): Promise<void> {
  const asked = drives.slice(0, SERVER_MAX_DRIVES);
  const query = asked.map((d) => `drive=${round(d.from.latitude)},${round(d.from.longitude)},${round(d.to.latitude)},${round(d.to.longitude)}`).join("&");
  try {
    const reply = await apiCall<"GET /api/trips/{id}/driving-routes">(`/api/trips/${trip}/driving-routes?${query}`, { background: true });
    if (born !== generation || !Array.isArray(reply?.routes)) return;
    for (const route of reply.routes) {
      if (!isCoordinate(route?.start) || !isCoordinate(route?.end) || !isPath(route.path)) continue;
      const key = keyOf(route.start, route.end);
      if (!found.has(key)) found.set(key, route.path);
      onServer.add(tripKey(trip, key));
    }
  } catch {
    ignoreFailure();
  }
}

function share(trip: number, from: LatLon, to: LatLon, path: RoutePath, key: string, born: number): void {
  const mine = tripKey(trip, key);
  if (onServer.has(mine) || sharing.has(mine)) return;
  sharing.add(mine);
  const body = { start: { latitude: Number(round(from.latitude)), longitude: Number(round(from.longitude)) }, end: { latitude: Number(round(to.latitude)), longitude: Number(round(to.longitude)) }, path: thin(path) };
  apiCall<"PUT /api/trips/{id}/driving-routes">(`/api/trips/${trip}/driving-routes`, { method: "PUT", body, background: true }).then(
    () => { if (born === generation) { sharing.delete(mine); onServer.add(mine); forCards.delete(trip); } },
    () => { if (born === generation) sharing.delete(mine); },
  );
}

function withinTime(job: Promise<void>, ms: number): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    void job.then(() => { clearTimeout(timer); resolve(); });
  });
}

export function drivingRoutes(mk: Mk, trip: number | null, drives: Drive[], timeoutMs = ROUTE_TIMEOUT_MS): Promise<RoutePath | null>[] {
  const missing = drives.filter((d) => { const key = keyOf(d.from, d.to); return !found.has(key) && !pending.has(key); });
  const born = generation;
  const lookup = trip === null || missing.length === 0 ? Promise.resolve() : withinTime(fromServer(trip, missing, born), LOOKUP_TIMEOUT_MS);
  return drives.map((d) => lookup.then(() => (born === generation ? drivingRoute(mk, d.from, d.to, timeoutMs, trip) : null)));
}

export function drivingRoute(mk: Mk, from: LatLon, to: LatLon, timeoutMs = ROUTE_TIMEOUT_MS, trip: number | null = null): Promise<RoutePath | null> {
  const key = keyOf(from, to);
  const born = generation;
  return find(mk, from, to, timeoutMs, key).then((path) => {
    if (path && trip !== null && born === generation) share(trip, from, to, path, key, born);
    return path;
  });
}

function find(mk: Mk, from: LatLon, to: LatLon, timeoutMs: number, key: string): Promise<RoutePath | null> {
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

export const isDrive = (from: Pick<Stop, "latitude" | "longitude">, to: Pick<Stop, "latitude" | "longitude" | "via">): boolean =>
  to.via === null && (from.latitude !== to.latitude || from.longitude !== to.longitude);

export const hasDrive = (stops: Stop[]): boolean => stops.some((s, i) => i > 0 && isDrive(stops[i - 1], s));

async function flushCards(batch: typeof queued, born: number): Promise<void> {
  for (let i = 0; i < batch.length; i += CARD_TRIPS) {
    const chunk = batch.slice(i, i + CARD_TRIPS);
    const wanted = new Set(chunk.map((c) => c.trip));
    const got = new Map<number, Map<string, RoutePath>>();
    let ok = false;
    try {
      const reply = await apiCall<"GET /api/driving-routes">(`/api/driving-routes?${[...wanted].map((t) => `trip=${t}`).join("&")}`, { keep: true, background: true });
      if (Array.isArray(reply?.trips)) {
        ok = true;
        for (const entry of reply.trips) {
          if (!wanted.has(entry?.trip_id) || !Array.isArray(entry.routes)) continue;
          const saved = new Map<string, RoutePath>();
          for (const route of entry.routes) {
            if (isCoordinate(route?.start) && isCoordinate(route?.end) && isPath(route.path)) saved.set(keyOf(route.start, route.end), thin(route.path, CARD_POINTS));
          }
          got.set(entry.trip_id, saved);
        }
      }
    } catch {
      ignoreFailure();
    }
    for (const waiting of chunk) {
      if (!ok && born === generation) forCards.delete(waiting.trip);
      waiting.resolve(born === generation ? (got.get(waiting.trip) ?? NO_SAVED) : NO_SAVED);
    }
  }
}

export function savedRoutes(trip: number): Promise<SavedRoutes> {
  const have = forCards.get(trip);
  if (have) return have;
  const born = generation;
  const job = new Promise<SavedRoutes>((resolve) => {
    queued.push({ trip, resolve });
    clearTimeout(queuedTimer);
    queuedTimer = setTimeout(() => void flushCards(queued.splice(0), born), CARD_WAIT_MS);
  });
  forCards.set(trip, job);
  return job;
}

export function savedRoads(stops: Stop[], saved: SavedRoutes): Roads {
  const legs: SavedLeg[] = [];
  for (let i = 1; i < stops.length; i++) {
    const key = keyOf(stops[i - 1], stops[i]);
    const path = isDrive(stops[i - 1], stops[i]) ? saved.get(key) : undefined;
    if (path) legs.push({ from_segment_id: 0, to_segment_id: 0, points: path, refs: [], key });
  }
  return { legs, interstates: [] };
}
