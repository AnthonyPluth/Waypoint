import { geoArea, geoBounds, geoDistance, geoInterpolate, type GeoProjection } from "d3-geo";
import type { Feature, FeatureCollection, Geometry } from "geojson";
import type { GeometryCollection, Topology } from "topojson-specification";
import type { StatsAirport, StatsFlights, StatsMapTrip, StatsPlacePoint, StatsRoute, StatsStayPin, StatsVisit } from "./api-types";

export type LonLat = [number, number];
export type Dot = { code: string; name: string; city: string | null; visits: number; latitude: number; longitude: number; r: number; label: string };
export type Arc = { key: string; a: string; b: string; flights: number; from: LonLat; to: LonLat; width: number; label: string; trips: StatsMapTrip[] };

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

export const dotRadius = (visits: number, most: number): number => 3 + 6 * Math.sqrt(Math.max(visits, 1) / Math.max(most, 1));

export const arcWidth = (flights: number, most: number): number => 1 + 3 * Math.sqrt(Math.max(flights, 1) / Math.max(most, 1));

export const placed = (a: StatsAirport): a is StatsAirport & { latitude: number; longitude: number } => a.latitude !== null && a.longitude !== null;

export function dots(airports: StatsAirport[]): Dot[] {
  const known = airports.filter(placed);
  const most = Math.max(0, ...known.map((a) => a.visits));
  const out: Dot[] = [];
  for (const a of known) {
    const place = [a.city, a.name === a.code ? null : a.name].filter(Boolean).join(" · ");
    out.push({
      code: a.code, name: a.name, city: a.city, visits: a.visits, latitude: a.latitude, longitude: a.longitude, r: dotRadius(a.visits, most),
      label: `${a.code}${place ? ` · ${place}` : ""}: ${plural(a.visits, "visit", "visits")}`,
    });
  }
  return out.sort((x, y) => y.visits - x.visits || x.code.localeCompare(y.code));
}

export function arcs(routes: StatsRoute[]): Arc[] {
  const most = Math.max(0, ...routes.map((r) => r.flights));
  const out: Arc[] = [];
  for (const r of routes) {
    if (r.a_latitude === null || r.a_longitude === null || r.b_latitude === null || r.b_longitude === null) continue;
    out.push({ key: `${r.a}-${r.b}`, a: r.a, b: r.b, flights: r.flights, from: [r.a_longitude, r.a_latitude], to: [r.b_longitude, r.b_latitude], width: arcWidth(r.flights, most), label: `${r.a} – ${r.b}: ${plural(r.flights, "flight", "flights")}`, trips: r.trips });
  }
  return out.sort((x, y) => x.flights - y.flights);
}

export const ARC_SAMPLES = 48;

export function greatCircle(from: LonLat, to: LonLat, samples = ARC_SAMPLES): LonLat[] {
  const along = geoInterpolate(from, to);
  return Array.from({ length: samples + 1 }, (_, i) => along(i / samples) as LonLat);
}

export type Bounds = { west: number; south: number; east: number; north: number };

export function flownBounds(flights: StatsFlights, pins: StatsStayPin[] = [], more: { latitude: number; longitude: number }[] = []): Bounds | null {
  const geometries: Geometry[] = [];
  for (const p of [...pins, ...more]) geometries.push({ type: "Point", coordinates: [p.longitude, p.latitude] });
  for (const a of flights.airports) if (placed(a)) geometries.push({ type: "Point", coordinates: [a.longitude, a.latitude] });
  for (const r of flights.routes) {
    if (r.a_latitude === null || r.a_longitude === null || r.b_latitude === null || r.b_longitude === null) continue;
    geometries.push({ type: "LineString", coordinates: [[r.a_longitude, r.a_latitude], [r.b_longitude, r.b_latitude]] });
  }
  if (geometries.length === 0) return null;
  const [[west, south], [east, north]] = geoBounds({ type: "GeometryCollection", geometries });
  return [west, south, east, north].every(Number.isFinite) ? { west, south, east, north } : null;
}

export function visitedFeatureIds<F extends { id?: string | number }>(
  points: [number, number][], features: F[], contains: (f: F, lonLat: [number, number]) => boolean,
): Set<string | number> {
  const out = new Set<string | number>();
  for (const p of points) {
    const f = features.find((x) => x.id !== undefined && contains(x, p));
    if (f?.id !== undefined) out.add(f.id);
  }
  return out;
}

export function visitedPoints(airports: StatsAirport[], pins: StatsStayPin[], visits: { latitude: number; longitude: number }[] = []): [number, number][] {
  return [...visits.map((v): [number, number] => [v.longitude, v.latitude]), ...airports.filter(placed).map((a): [number, number] => [a.longitude, a.latitude]), ...pins.map((p): [number, number] => [p.longitude, p.latitude])];
}

export type StateSource = { point: [number, number]; trips: StatsMapTrip[] };

export function stateSources(flights: StatsFlights, stays: StatsStayPin[], points: StatsPlacePoint[], visits: StatsVisit[]): StateSource[] {
  const touching = (code: string) => flights.routes.filter((r) => r.a === code || r.b === code).flatMap((r) => r.trips);
  return [
    ...flights.airports.filter(placed).map((a): StateSource => ({ point: [a.longitude, a.latitude], trips: touching(a.code) })),
    ...stays.map((p): StateSource => ({ point: [p.longitude, p.latitude], trips: p.trips })),
    ...points.map((p): StateSource => ({ point: [p.longitude, p.latitude], trips: p.trips })),
    ...visits.filter((v) => v.country === "US" && v.state).map((v): StateSource => ({ point: [v.longitude, v.latitude], trips: v.trips })),
  ];
}

const SHORE_DEGREES = 0.03;
const SHORE_RING: [number, number][] = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]];

const extents = new WeakMap<object, [[number, number], [number, number]]>();

function nearExtent(f: Feature<Geometry>, point: [number, number]): boolean {
  let box = extents.get(f);
  if (!box) { box = geoBounds(f); extents.set(f, box); }
  const [[west, south], [east, north]] = box;
  if (point[1] < south - SHORE_DEGREES || point[1] > north + SHORE_DEGREES) return false;
  return west <= east ? point[0] >= west - SHORE_DEGREES && point[0] <= east + SHORE_DEGREES : point[0] >= west - SHORE_DEGREES || point[0] <= east + SHORE_DEGREES;
}

export function stateAt<F extends Feature<Geometry> & { id?: string | number }>(point: [number, number], states: F[], contains: (f: F, lonLat: [number, number]) => boolean): F | undefined {
  const inside = states.find((f) => f.id !== undefined && contains(f, point));
  if (inside) return inside;
  const close = states.filter((f) => f.id !== undefined && nearExtent(f, point));
  for (const [dx, dy] of SHORE_RING) {
    const near = close.find((f) => contains(f, [point[0] + dx * SHORE_DEGREES, point[1] + dy * SHORE_DEGREES]));
    if (near) return near;
  }
  return undefined;
}

export function visitedStateTrips<F extends Feature<Geometry> & { id?: string | number }>(
  sources: StateSource[], states: F[], contains: (f: F, lonLat: [number, number]) => boolean,
): Map<string | number, StatsMapTrip[]> {
  const out = new Map<string | number, StatsMapTrip[]>();
  for (const s of sources) {
    const f = stateAt(s.point, states, contains);
    if (f?.id === undefined) continue;
    const kept = out.get(f.id) ?? [];
    for (const t of s.trips) if (!kept.some((k) => k.trip_id === t.trip_id && k.start === t.start)) kept.push(t);
    out.set(f.id, kept);
  }
  for (const trips of out.values()) trips.sort((a, b) => a.start.localeCompare(b.start) || a.trip_id - b.trip_id);
  return out;
}

export type Pin = { key: string; city: string; stays: number; nights: number; latitude: number; longitude: number; label: string; trips: StatsMapTrip[] };

export function pins(stays: StatsStayPin[]): Pin[] {
  return stays.map((p) => ({
    key: `${p.city}-${p.country ?? ""}-${p.latitude}-${p.longitude}`, city: p.city, stays: p.stays, nights: p.nights, latitude: p.latitude, longitude: p.longitude, trips: p.trips,
    label: `${p.city}: ${plural(p.stays, "stay", "stays")}, ${plural(p.nights, "night", "nights")}`,
  }));
}

export function countrySources(flights: StatsFlights, stays: StatsStayPin[], visits: StatsVisit[]): StateSource[] {
  const touching = (code: string) => flights.routes.filter((r) => r.a === code || r.b === code).flatMap((r) => r.trips);
  return [
    ...flights.airports.filter(placed).map((a): StateSource => ({ point: [a.longitude, a.latitude], trips: touching(a.code) })),
    ...stays.map((p): StateSource => ({ point: [p.longitude, p.latitude], trips: p.trips })),
    ...visits.map((v): StateSource => ({ point: [v.longitude, v.latitude], trips: v.trips })),
  ];
}

export type Country = Feature<Geometry, { name?: string }> & { id?: string | number };

async function outlines(file: Promise<{ default: unknown }>): Promise<Country[]> {
  const [{ feature }, atlas] = await Promise.all([import("topojson-client"), file]);
  const topology = atlas.default as Topology<{ countries: GeometryCollection<{ name?: string }> }>;
  return (feature(topology, topology.objects.countries) as FeatureCollection<Geometry, { name?: string }>).features as Country[];
}

export const loadCountries = (): Promise<Country[]> => outlines(import("world-atlas/countries-110m.json"));

export const loadDetailedCountries = (): Promise<Country[]> => outlines(import("world-atlas/countries-50m.json"));

export const loadFineCountries = (): Promise<Country[]> => outlines(import("world-atlas/countries-10m.json"));

export type Detail = "coarse" | "medium" | "fine";

export const COARSE_FROM_KM = 35;
export const MEDIUM_FROM_KM = 12;

export const detailFor = (kmPerPixel: number): Detail => (kmPerPixel >= COARSE_FROM_KM ? "coarse" : kmPerPixel >= MEDIUM_FROM_KM ? "medium" : "fine");

const EARTH_KM = 6371;

export function kmPerPixel(projection: GeoProjection, width: number, height: number): number {
  const a = projection.invert?.([width / 2 - 0.5, height / 2]);
  const b = projection.invert?.([width / 2 + 0.5, height / 2]);
  return a && b ? geoDistance(a, b) * EARTH_KM : Infinity;
}

export type Window = { west: number; south: number; east: number; north: number };

export function windowOf(projection: GeoProjection, box: { x: number; y: number; w: number; h: number }): Window | null {
  if (!projection.invert) return null;
  const at = [0, 0.5, 1];
  const corners = at.flatMap((u) => at.map((v) => projection.invert!([box.x + box.w * u, box.y + box.h * v])));
  if (corners.some((c) => !c || !Number.isFinite(c[0]) || !Number.isFinite(c[1]))) return null;
  const lons = corners.map((c) => c![0]);
  const lats = corners.map((c) => c![1]);
  const west = Math.min(...lons);
  const east = Math.max(...lons);
  if (east - west > 170) return null;
  const pad = 0.1;
  const spanX = (east - west) * pad;
  const spanY = (Math.max(...lats) - Math.min(...lats)) * pad;
  return { west: west - spanX, south: Math.min(...lats) - spanY, east: east + spanX, north: Math.max(...lats) + spanY };
}

type PolygonFacts = { box: [[number, number], [number, number]]; real: boolean };

const factsOfPolygon = new WeakMap<object, PolygonFacts>();

function polygonFacts(coordinates: number[][][]): PolygonFacts {
  let facts = factsOfPolygon.get(coordinates);
  if (!facts) {
    const polygon = { type: "Polygon" as const, coordinates };
    facts = { box: geoBounds(polygon), real: geoArea(polygon) <= 2 * Math.PI };
    factsOfPolygon.set(coordinates, facts);
  }
  return facts;
}

const meets = (box: [[number, number], [number, number]], w: Window): boolean => {
  const [[west, south], [east, north]] = box;
  if (west > east) return true;
  return east >= w.west && west <= w.east && north >= w.south && south <= w.north;
};

const wanted = (coordinates: number[][][], window: Window | null): boolean => {
  const facts = polygonFacts(coordinates);
  return facts.real && (window === null || meets(facts.box, window));
};

export function clipToWindow(countries: Country[], window: Window | null): Country[] {
  const out: Country[] = [];
  for (const c of countries) {
    const g = c.geometry;
    if (g.type === "Polygon") {
      if (wanted(g.coordinates, window)) out.push(c);
    } else if (g.type === "MultiPolygon") {
      const kept = g.coordinates.filter((poly) => wanted(poly, window));
      if (kept.length === g.coordinates.length) out.push(c);
      else if (kept.length) out.push({ ...c, geometry: { type: "MultiPolygon", coordinates: kept } });
    } else out.push(c);
  }
  return out;
}

export async function loadStates(): Promise<Country[]> {
  const [{ feature }, atlas] = await Promise.all([import("topojson-client"), import("us-atlas/states-10m.json")]);
  const topology = atlas.default as unknown as Topology<{ states: GeometryCollection<{ name?: string }> }>;
  return (feature(topology, topology.objects.states) as FeatureCollection<Geometry, { name?: string }>).features as Country[];
}

export const US_ID = "840";

const POLE = 89.99;
const SLIVER = 1e-9;

const atPole = (p: LonLat) => Math.abs(p[1]) >= POLE;
const area = (ring: LonLat[]) => {
  let sum = 0;
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i]!;
    const b = ring[(i + 1) % ring.length]!;
    sum += a[0] * b[1] - b[0] * a[1];
  }
  return Math.abs(sum) / 2;
};

function clipLon(points: LonLat[], bound: number, keepGreater: boolean): LonLat[] {
  const inside = (p: LonLat) => (keepGreater ? p[0] >= bound : p[0] <= bound);
  const out: LonLat[] = [];
  for (let i = 0; i < points.length; i++) {
    const cur = points[i]!;
    const prev = points[(i + points.length - 1) % points.length]!;
    const cross = (): LonLat => {
      const t = (bound - prev[0]) / (cur[0] - prev[0]);
      return [bound, prev[1] + t * (cur[1] - prev[1])];
    };
    if (inside(cur)) {
      if (!inside(prev)) out.push(cross());
      out.push(cur);
    } else if (inside(prev)) out.push(cross());
  }
  return out;
}

export function splitAtAntimeridian(ring: LonLat[]): LonLat[][] {
  const open: LonLat[] = [];
  for (const p of ring) {
    const last = open[open.length - 1];
    if (!last || last[0] !== p[0] || last[1] !== p[1]) open.push([p[0], p[1]]);
  }
  const first = open[0];
  const end = open[open.length - 1];
  if (first && end && open.length > 1 && first[0] === end[0] && first[1] === end[1]) open.pop();
  if (open.length < 3) return [];

  const unwound: LonLat[] = [];
  let shift = 0;
  let wrapped = false;
  for (const p of open) {
    const last = unwound[unwound.length - 1];
    if (last && !atPole(p) && !atPole(open[unwound.length - 1]!)) {
      const raw = p[0] + shift;
      if (raw - last[0] > 180) { shift -= 360; wrapped = true; }
      else if (last[0] - raw > 180) { shift += 360; wrapped = true; }
    }
    unwound.push([p[0] + shift, p[1]]);
  }

  const lons = unwound.map((p) => p[0]);
  if (!wrapped && Math.min(...lons) >= -180 && Math.max(...lons) <= 180) {
    return area(unwound) > SLIVER ? [[...unwound, unwound[0]!]] : [];
  }

  const turns = Math.round((unwound[0]![0] - unwound[unwound.length - 1]![0]) / 360);
  if (turns !== 0) {
    const mean = unwound.reduce((sum, p) => sum + p[1], 0) / unwound.length;
    const pole = mean >= 0 ? 90 : -90;
    unwound.push([unwound[unwound.length - 1]![0], pole], [unwound[0]![0], pole]);
  }

  const pieces: LonLat[][] = [];
  const low = Math.floor((Math.min(...unwound.map((p) => p[0])) + 180) / 360);
  const high = Math.floor((Math.max(...unwound.map((p) => p[0])) + 180) / 360);
  for (let slot = low; slot <= high; slot++) {
    const lo = -180 + 360 * slot;
    const hi = 180 + 360 * slot;
    const kept = clipLon(clipLon(unwound, lo, true), hi, false).map((p): LonLat => [p[0] - 360 * slot, p[1]]);
    if (kept.length >= 3 && area(kept) > SLIVER) pieces.push([...kept, kept[0]!]);
  }
  return pieces;
}

export function toOverlays(feature: Feature<Geometry>): LonLat[][] {
  const g = feature.geometry;
  if (g.type === "Polygon") return g.coordinates.flatMap((ring) => splitAtAntimeridian(ring.map((p) => [p[0], p[1]] as LonLat)));
  if (g.type === "MultiPolygon") return g.coordinates.flatMap((poly) => poly.flatMap((ring) => splitAtAntimeridian(ring.map((p) => [p[0], p[1]] as LonLat))));
  return [];
}
