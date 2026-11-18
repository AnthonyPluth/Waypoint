import { geoContains, geoEqualEarth, geoPath, type GeoProjection } from "d3-geo";
import type { StatsAirport, StatsFlights, StatsRoute } from "./api-types";
import { arcWidth, dotRadius, placed, visitedFeatureIds, type Country } from "./map";

export const MAP_WIDTH = 960;
export const MAP_HEIGHT = 500;

export function worldProjection(width = MAP_WIDTH, height = MAP_HEIGHT): GeoProjection {
  return geoEqualEarth().fitExtent([[4, 4], [width - 4, height - 4]], { type: "Sphere" });
}

export type ReviewDot = { code: string; visits: number; x: number; y: number; r: number };
export type ReviewArc = { flights: number; d: string; width: number };

function dots(airports: StatsAirport[], projection: GeoProjection): ReviewDot[] {
  const known = airports.filter(placed);
  const most = Math.max(0, ...known.map((a) => a.visits));
  const out: ReviewDot[] = [];
  for (const a of known) {
    const at = projection([a.longitude, a.latitude]);
    if (!at) continue;
    out.push({ code: a.code, visits: a.visits, x: at[0], y: at[1], r: dotRadius(a.visits, most) });
  }
  return out.sort((x, y) => y.visits - x.visits || x.code.localeCompare(y.code));
}

function arcPath(r: StatsRoute, path: ReturnType<typeof geoPath>): string | null {
  if (r.a_latitude === null || r.a_longitude === null || r.b_latitude === null || r.b_longitude === null) return null;
  return path({ type: "LineString", coordinates: [[r.a_longitude, r.a_latitude], [r.b_longitude, r.b_latitude]] });
}

function arcs(routes: StatsRoute[], projection: GeoProjection): ReviewArc[] {
  const path = geoPath(projection);
  const most = Math.max(0, ...routes.map((r) => r.flights));
  const out: ReviewArc[] = [];
  for (const r of routes) {
    const d = arcPath(r, path);
    if (d) out.push({ flights: r.flights, d, width: arcWidth(r.flights, most) });
  }
  return out.sort((x, y) => x.flights - y.flights);
}

export function mapData(flights: StatsFlights, projection: GeoProjection = worldProjection()): { dots: ReviewDot[]; arcs: ReviewArc[] } {
  return { dots: dots(flights.airports, projection), arcs: arcs(flights.routes, projection) };
}

export function outlinePaths(countries: Country[], points: [number, number][], projection: GeoProjection): { d: string; visited: boolean }[] {
  const path = geoPath(projection);
  const visited = visitedFeatureIds(points, countries, (f, p) => geoContains(f, p));
  return countries.map((c) => ({ d: path(c) ?? "", visited: visited.has(c.id ?? "") }));
}
