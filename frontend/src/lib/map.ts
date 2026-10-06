import { geoContains, geoEqualEarth, geoPath, type GeoProjection } from "d3-geo";
import type { Feature, FeatureCollection, Geometry } from "geojson";
import type { GeometryCollection, Topology } from "topojson-specification";
import type { StatsAirport, StatsFlights, StatsMapTrip, StatsRoute, StatsStayPin } from "./api-types";

export const MAP_WIDTH = 960;
export const MAP_HEIGHT = 500;

export type Dot = { code: string; name: string; city: string | null; visits: number; x: number; y: number; r: number; label: string };
export type Arc = { key: string; a: string; b: string; flights: number; d: string; width: number; label: string; trips: StatsMapTrip[] };

export function worldProjection(width = MAP_WIDTH, height = MAP_HEIGHT): GeoProjection {
  return geoEqualEarth().fitExtent([[4, 4], [width - 4, height - 4]], { type: "Sphere" });
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

export const dotRadius = (visits: number, most: number): number => 3 + 6 * Math.sqrt(Math.max(visits, 1) / Math.max(most, 1));

export const arcWidth = (flights: number, most: number): number => 1 + 3 * Math.sqrt(Math.max(flights, 1) / Math.max(most, 1));

const placed = (a: StatsAirport): a is StatsAirport & { latitude: number; longitude: number } => a.latitude !== null && a.longitude !== null;

export function dots(airports: StatsAirport[], projection: GeoProjection): Dot[] {
  const known = airports.filter(placed);
  const most = Math.max(0, ...known.map((a) => a.visits));
  const out: Dot[] = [];
  for (const a of known) {
    const at = projection([a.longitude, a.latitude]);
    if (!at) continue;
    const place = [a.city, a.name === a.code ? null : a.name].filter(Boolean).join(" · ");
    out.push({
      code: a.code, name: a.name, city: a.city, visits: a.visits, x: at[0], y: at[1], r: dotRadius(a.visits, most),
      label: `${a.code}${place ? ` · ${place}` : ""}: ${plural(a.visits, "visit", "visits")}`,
    });
  }
  return out.sort((x, y) => y.visits - x.visits || x.code.localeCompare(y.code));
}

export function arcPath(r: StatsRoute, path: ReturnType<typeof geoPath>): string | null {
  if (r.a_latitude === null || r.a_longitude === null || r.b_latitude === null || r.b_longitude === null) return null;
  return path({ type: "LineString", coordinates: [[r.a_longitude, r.a_latitude], [r.b_longitude, r.b_latitude]] });
}

export function arcs(routes: StatsRoute[], projection: GeoProjection): Arc[] {
  const path = geoPath(projection);
  const most = Math.max(0, ...routes.map((r) => r.flights));
  const out: Arc[] = [];
  for (const r of routes) {
    const d = arcPath(r, path);
    if (!d) continue;
    out.push({ key: `${r.a}-${r.b}`, a: r.a, b: r.b, flights: r.flights, d, width: arcWidth(r.flights, most), label: `${r.a} – ${r.b}: ${plural(r.flights, "flight", "flights")}`, trips: r.trips });
  }
  return out.sort((x, y) => x.flights - y.flights);
}

export function mapData(flights: StatsFlights, projection: GeoProjection = worldProjection()): { dots: Dot[]; arcs: Arc[] } {
  return { dots: dots(flights.airports, projection), arcs: arcs(flights.routes, projection) };
}

export const pieces = (d: string): string[] => d.split(/(?=M)/).filter(Boolean);

export type Transform = { k: number; x: number; y: number };
export const IDENTITY: Transform = { k: 1, x: 0, y: 0 };
export const MAX_ZOOM = 8;

export function zoomAt(t: Transform, factor: number, px: number, py: number, width = MAP_WIDTH, height = MAP_HEIGHT): Transform {
  const k = Math.min(MAX_ZOOM, Math.max(1, t.k * factor));
  return clampPan({ k, x: px - ((px - t.x) / t.k) * k, y: py - ((py - t.y) / t.k) * k }, width, height);
}

export function flownBounds(flights: StatsFlights, projection: GeoProjection, pins: StatsStayPin[] = []): [[number, number], [number, number]] | null {
  const geometries: Geometry[] = [];
  for (const p of pins) geometries.push({ type: "Point", coordinates: [p.longitude, p.latitude] });
  for (const a of flights.airports) if (placed(a)) geometries.push({ type: "Point", coordinates: [a.longitude, a.latitude] });
  for (const r of flights.routes) {
    if (r.a_latitude === null || r.a_longitude === null || r.b_latitude === null || r.b_longitude === null) continue;
    geometries.push({ type: "LineString", coordinates: [[r.a_longitude, r.a_latitude], [r.b_longitude, r.b_latitude]] });
  }
  if (geometries.length === 0) return null;
  const [[x0, y0], [x1, y1]] = geoPath(projection).bounds({ type: "GeometryCollection", geometries });
  return Number.isFinite(x0) && Number.isFinite(y0) && Number.isFinite(x1) && Number.isFinite(y1) ? [[x0, y0], [x1, y1]] : null;
}

export function fitBox(box: [[number, number], [number, number]] | null, padding = 0.15, width = MAP_WIDTH, height = MAP_HEIGHT): Transform {
  if (!box) return IDENTITY;
  const [[x0, y0], [x1, y1]] = box;
  const w = Math.max(x1 - x0, width / 6) * (1 + 2 * padding), h = Math.max(y1 - y0, height / 6) * (1 + 2 * padding);
  const k = Math.min(MAX_ZOOM, width / w, height / h);
  if (k < 1.2) return IDENTITY;
  return clampPan({ k, x: width / 2 - k * ((x0 + x1) / 2), y: height / 2 - k * ((y0 + y1) / 2) }, width, height);
}

export function clampPan(t: Transform, width = MAP_WIDTH, height = MAP_HEIGHT): Transform {
  return { k: t.k, x: Math.min(0, Math.max(width - width * t.k, t.x)), y: Math.min(0, Math.max(height - height * t.k, t.y)) };
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

export function visitedPoints(airports: StatsAirport[], pins: StatsStayPin[]): [number, number][] {
  return [...airports.filter(placed).map((a): [number, number] => [a.longitude, a.latitude]), ...pins.map((p): [number, number] => [p.longitude, p.latitude])];
}

export type Pin = { key: string; city: string; stays: number; nights: number; x: number; y: number; label: string; trips: StatsMapTrip[] };

export function pins(stays: StatsStayPin[], projection: GeoProjection): Pin[] {
  const out: Pin[] = [];
  for (const p of stays) {
    const at = projection([p.longitude, p.latitude]);
    if (!at) continue;
    out.push({ key: `${p.city}-${p.country ?? ""}`, city: p.city, stays: p.stays, nights: p.nights, x: at[0], y: at[1], trips: p.trips,
      label: `${p.city}: ${plural(p.stays, "stay", "stays")}, ${plural(p.nights, "night", "nights")}` });
  }
  return out;
}

export type Country = Feature<Geometry, { name?: string }> & { id?: string | number };

export async function loadCountries(): Promise<Country[]> {
  const [{ feature }, atlas] = await Promise.all([import("topojson-client"), import("world-atlas/countries-110m.json")]);
  const topology = atlas.default as unknown as Topology<{ countries: GeometryCollection<{ name?: string }> }>;
  return (feature(topology, topology.objects.countries) as FeatureCollection<Geometry, { name?: string }>).features as Country[];
}

export async function loadStates(): Promise<Country[]> {
  const [{ feature }, atlas] = await Promise.all([import("topojson-client"), import("us-atlas/states-10m.json")]);
  const topology = atlas.default as unknown as Topology<{ states: GeometryCollection<{ name?: string }> }>;
  return (feature(topology, topology.objects.states) as FeatureCollection<Geometry, { name?: string }>).features as Country[];
}

export const US_ID = "840";

export function outlinePaths(countries: Country[], points: [number, number][], projection: GeoProjection): { d: string; visited: boolean }[] {
  const path = geoPath(projection);
  const visited = visitedFeatureIds(points, countries, (f, p) => geoContains(f, p));
  return countries.map((c) => ({ d: path(c) ?? "", visited: visited.has(c.id ?? "") }));
}
