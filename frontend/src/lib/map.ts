// The travel map's maths: turning /api/stats' airports and routes into dots and arcs on a projection, with no map
// service involved. The country outlines are bundled (world-atlas, Natural Earth, public domain) and drawn by the component.
import { geoContains, geoEqualEarth, geoPath, type GeoProjection } from "d3-geo";
import type { Feature, FeatureCollection, Geometry } from "geojson";
import type { GeometryCollection, Topology } from "topojson-specification";
import type { StatsAirport, StatsFlights, StatsMapTrip, StatsRoute, StatsStayPin } from "./api-types";

export const MAP_WIDTH = 960;
export const MAP_HEIGHT = 500;

export type Dot = { code: string; name: string; city: string | null; visits: number; x: number; y: number; r: number; label: string };
export type Arc = { key: string; a: string; b: string; flights: number; d: string; width: number; label: string; trips: StatsMapTrip[] };

/** A projection that keeps the whole world in the map's box. */
export function worldProjection(width = MAP_WIDTH, height = MAP_HEIGHT): GeoProjection {
  return geoEqualEarth().fitExtent([[4, 4], [width - 4, height - 4]], { type: "Sphere" });
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** A dot's radius grows with the square root of its visits (so area follows the count), from 3 up to 9. */
export const dotRadius = (visits: number, most: number): number => 3 + 6 * Math.sqrt(Math.max(visits, 1) / Math.max(most, 1));

/** An arc's width: 1 for a route flown once, up to 4 for the most flown. */
export const arcWidth = (flights: number, most: number): number => 1 + 3 * Math.sqrt(Math.max(flights, 1) / Math.max(most, 1));

/** An airport with a place on the map: Waypoint knows its coordinates. */
const placed = (a: StatsAirport): a is StatsAirport & { latitude: number; longitude: number } => a.latitude !== null && a.longitude !== null;

/** The dots, most visited first: one per airport with coordinates, sized by visits. */
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

/** One route's great-circle path. d3's path follows the great circle between the two points and cuts it where it crosses
 *  the antimeridian, so a trans-Pacific route is two pieces, one at each edge, never a stripe across the map. */
export function arcPath(r: StatsRoute, path: ReturnType<typeof geoPath>): string | null {
  if (r.a_latitude === null || r.a_longitude === null || r.b_latitude === null || r.b_longitude === null) return null;
  return path({ type: "LineString", coordinates: [[r.a_longitude, r.a_latitude], [r.b_longitude, r.b_latitude]] });
}

/** The arcs, most flown last (drawn on top): one per route whose two airports are both known. */
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

/** What the map draws for some flights. */
export function mapData(flights: StatsFlights, projection: GeoProjection = worldProjection()): { dots: Dot[]; arcs: Arc[] } {
  return { dots: dots(flights.airports, projection), arcs: arcs(flights.routes, projection) };
}

/** The pieces of an SVG path, one per "M": a route cut at the antimeridian has two. */
export const pieces = (d: string): string[] => d.split(/(?=M)/).filter(Boolean);

export type Transform = { k: number; x: number; y: number };
export const IDENTITY: Transform = { k: 1, x: 0, y: 0 };
export const MAX_ZOOM = 8;

/** Zoom by `factor` around the point (px, py) of the map's box, keeping that point still and the map covering its box. */
export function zoomAt(t: Transform, factor: number, px: number, py: number, width = MAP_WIDTH, height = MAP_HEIGHT): Transform {
  const k = Math.min(MAX_ZOOM, Math.max(1, t.k * factor));
  return clampPan({ k, x: px - ((px - t.x) / t.k) * k, y: py - ((py - t.y) / t.k) * k }, width, height);
}

/** The box (in the map's own units) around everything flown and stayed in: every airport with coordinates, every route's path and every stay's pin, or null when
 *  there is nothing to show. */
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

/** The zoom and pan that frame a box, centred, with `padding` (a fraction of the box) around it and never closer than
 *  MAX_ZOOM; a box that is most of the map (or none) is the whole world. A very small box (one airport) is given a minimum
 *  size so the map doesn't zoom right in on a point. */
export function fitBox(box: [[number, number], [number, number]] | null, padding = 0.15, width = MAP_WIDTH, height = MAP_HEIGHT): Transform {
  if (!box) return IDENTITY;
  const [[x0, y0], [x1, y1]] = box;
  const w = Math.max(x1 - x0, width / 6) * (1 + 2 * padding), h = Math.max(y1 - y0, height / 6) * (1 + 2 * padding);
  const k = Math.min(MAX_ZOOM, width / w, height / h);
  if (k < 1.2) return IDENTITY;
  return clampPan({ k, x: width / 2 - k * ((x0 + x1) / 2), y: height / 2 - k * ((y0 + y1) / 2) }, width, height);
}

/** Keep the zoomed map covering its box: you can't drag the world off the screen. */
export function clampPan(t: Transform, width = MAP_WIDTH, height = MAP_HEIGHT): Transform {
  return { k: t.k, x: Math.min(0, Math.max(width - width * t.k, t.x)), y: Math.min(0, Math.max(height - height * t.k, t.y)) };
}

/** The ISO country codes' outlines that contain one of these airports: the countries shaded as visited. Needs the outlines
 *  (GeoJSON features), so it lives with the data the component loads. */
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

/** Where you've been, as [longitude, latitude]: every airport flown with coordinates, and every city stayed in. */
export function visitedPoints(airports: StatsAirport[], pins: StatsStayPin[]): [number, number][] {
  return [...airports.filter(placed).map((a): [number, number] => [a.longitude, a.latitude]), ...pins.map((p): [number, number] => [p.longitude, p.latitude])];
}

/** A stay's pin on the map. */
export type Pin = { key: string; city: string; stays: number; nights: number; x: number; y: number; label: string; trips: StatsMapTrip[] };

/** The pins, most nights first, each at its city's place; the label names the city and what was spent there. */
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

/** The bundled country outlines, fetched as a separate download (the world-atlas data and topojson-client are big). */
export async function loadCountries(): Promise<Country[]> {
  const [{ feature }, atlas] = await Promise.all([import("topojson-client"), import("world-atlas/countries-110m.json")]);
  const topology = atlas.default as unknown as Topology<{ countries: GeometryCollection<{ name?: string }> }>;
  return (feature(topology, topology.objects.countries) as FeatureCollection<Geometry, { name?: string }>).features as Country[];
}

/** The bundled US state outlines (us-atlas, from the Census Bureau, public domain), a separate download from the countries. */
export async function loadStates(): Promise<Country[]> {
  const [{ feature }, atlas] = await Promise.all([import("topojson-client"), import("us-atlas/states-10m.json")]);
  const topology = atlas.default as unknown as Topology<{ states: GeometryCollection<{ name?: string }> }>;
  return (feature(topology, topology.objects.states) as FeatureCollection<Geometry, { name?: string }>).features as Country[];
}

/** The United States' id in the country outlines (ISO 3166-1 numeric): shaded by state instead, once the states are drawn. */
export const US_ID = "840";

/** Each country's outline as an SVG path, with whether one of these places is in it. */
export function outlinePaths(countries: Country[], points: [number, number][], projection: GeoProjection): { d: string; visited: boolean }[] {
  const path = geoPath(projection);
  const visited = visitedFeatureIds(points, countries, (f, p) => geoContains(f, p));
  return countries.map((c) => ({ d: path(c) ?? "", visited: visited.has(c.id ?? "") }));
}
