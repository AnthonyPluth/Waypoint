import { geoBounds, geoDistance, geoEqualEarth, type GeoProjection } from "d3-geo";
import type { Geometry } from "geojson";
import type { Segment, Trip, TripPlaces } from "./api-types";
import { countryName } from "./stats";
import { instant, isPast } from "./trips";

export type Kind = Segment["kind"];
export type StopKind = "airport" | "stay" | "place" | "home";
export type Stop = { name: string; city: string; code: string | null; kind: StopKind; latitude: number; longitude: number; from: string; to: string; via: Kind | null; back: boolean };
export type Spot = { x: number; y: number };
export type Vehicle = "plane" | "car" | "boat";
export type Roads = TripPlaces["roads"];
export type Boundaries = TripPlaces["boundaries"];
export type Track = { points: Spot[]; along: number[] };
export type Leg = { d: string; flight: boolean; vehicle: Vehicle; from: Spot; control: Spot; to: Spot; road: Track | null; refs: string[] };
export type RoadShape = { ref: string; d: string; left: number; top: number; right: number; bottom: number; length: number; mid: Spot };
export type Extent = { left: number; top: number; right: number; bottom: number };
export type BoundaryShape = Extent & { d: string };
export type Shield = { ref: string; x: number; y: number };
export type Box = { x: number; y: number; w: number; h: number };
type Visit = Omit<Stop, "back"> & { exact?: boolean };
type Point = { name: string; city?: string; code?: string | null; kind?: StopKind; latitude: number; longitude: number; exact?: boolean };

export const MIN_SPAN_DEGREES = 10;
export const SAME_PLACE_KM = 30;
export const CROWDED_PX = 14;
export const NUDGE_PX = 13;
export const BOW = 0.22;
export const LOCAL_BOW = 0.1;
export const ZOOM_UNITS = 0.35;
export const MIN_ZOOM_SHARE = 0.25;
export const MIN_MS = 6000;
export const MAX_MS = 60000;
export const PER_STOP_MS = 2000;
export const LABEL_HOLD_MS = 1750;
export const SCRUB_STEPS = 4000;
export const NO_ROADS: Roads = { legs: [], interstates: [] };
export const ROAD_MATCH_KM = 90;
export const RETRACE_KM = 48.3;
export const RETRACE_MIN_SHARE = 0.5;
export const RETRACE_WHOLE_SHARE = 0.9;
export const ROAD_MIN_SCALE = 800;
export const NO_BOUNDARIES: Boundaries = [];
export const BOUNDARY_MIN_SCALE = 500;
export const SHIELD_GAP = 150;
export const MAX_SHIELDS = 8;
export const HEADING_UNITS = 6;

const EARTH_KM = 6371;
const key = (text: string | null | undefined): string => (text ?? "").trim().toLowerCase();
const head = (text: string): string => text.split(",")[0].trim();

export const replayMs = (stops: number): number => Math.min(MAX_MS, Math.max(MIN_MS, stops * PER_STOP_MS));

export const distanceKm = (a: Point, b: Point): number => geoDistance([a.longitude, a.latitude], [b.longitude, b.latitude]) * EARTH_KM;

function finder(places: TripPlaces) {
  const airports = new Map(places.airports.map((a) => [a.code.toUpperCase(), a]));
  const cities = new Map(places.cities.map((c) => [key(c.city), c]));
  const airportCities = new Map(places.airports.map((a) => [key(a.city), a]));
  const airport = (code: string | null): Point | null => {
    const found = airports.get((code ?? "").trim().toUpperCase());
    return found ? { name: found.city, code: found.code.toUpperCase(), kind: "airport", latitude: found.latitude, longitude: found.longitude } : null;
  };
  const city = (text: string | null): Point | null => {
    const found = cities.get(key(text)) ?? cities.get(key(head(text ?? ""))) ?? airportCities.get(key(text)) ?? airportCities.get(key(head(text ?? "")));
    return found && text ? { name: head(text), latitude: found.latitude, longitude: found.longitude } : null;
  };
  const stored = new Map(places.stays.map((p) => [p.segment_id, p]));
  const stay = (s: Segment, text: string | null): Point | null => {
    const found = stored.get(s.id);
    return found ? { name: head(text ?? "") || head(s.origin ?? "") || "Stay", latitude: found.latitude, longitude: found.longitude, exact: true } : null;
  };
  return { airport, city, stay };
}

const liveOf = (trip: Trip): Segment[] => trip.segments.filter((s) => s.status !== "cancelled");

const byCountries = (trip: Trip): boolean => {
  const live = liveOf(trip).filter((s) => s.kind !== "parking");
  return live.length > 0 && live.every((s) => s.kind === "visit");
};

const dateOrder = (a: Segment, b: Segment): number => a.start_local.localeCompare(b.start_local) || a.end_local.localeCompare(b.end_local) || a.id - b.id;

export function maxStops(trip: Trip): number {
  const countries = byCountries(trip);
  return liveOf(trip).reduce((n, s) => {
    if (s.kind === "visit") return countries ? n + 1 : n;
    if (s.kind === "parking") return n;
    if (s.kind === "flight" || s.kind === "train") return n + 2;
    if (s.kind === "cruise") return n + 2 + s.itinerary.length;
    return n + 1;
  }, 0);
}

export const isRoadTrip = (trip: Trip): boolean => !trip.segments.some((s) => s.status !== "cancelled" && (s.kind === "flight" || s.kind === "train" || s.kind === "cruise"));

export const worthLocating = (trip: Trip, today: string): boolean => isPast(trip, today) && maxStops(trip) >= 2;

function visitsOf(trip: Trip, places: TripPlaces): Visit[] {
  const { airport, city, stay } = finder(places);
  const countries = byCountries(trip);
  const live = liveOf(trip).filter((s) => s.kind !== "parking" && (s.kind !== "visit" || countries))
    .sort((a, b) => (countries ? dateOrder(a, b) : instant(a.start_local, a.start_zone) - instant(b.start_local, b.start_zone) || a.id - b.id));
  const out: Visit[] = [];
  const add = (p: Point | null, from: string, to: string, via: Kind | null) => {
    if (p) out.push({ ...p, city: p.city ?? p.name, code: p.code ?? null, kind: p.kind ?? "place", from, to, via });
  };
  for (const s of live) {
    if (s.kind === "flight") {
      add(airport(s.origin), s.start_local, s.start_local, null);
      add(airport(s.destination), s.end_local, s.end_local, "flight");
    } else if (s.kind === "visit") {
      add(stay(s, countryName(s.destination ?? "")), s.start_local, s.end_local, null);
    } else if (s.kind === "hotel") {
      const found = stay(s, s.destination) ?? city(s.destination);
      add(found && { ...found, kind: "stay", city: found.name, name: head(s.origin ?? "") || found.name }, s.start_local, s.end_local, null);
    } else if (s.kind === "car") {
      add(stay(s, s.destination ?? s.origin) ?? city(s.destination) ?? city(s.origin), s.start_local, s.end_local, null);
    } else if (s.kind === "train") {
      add(city(s.origin), s.start_local, s.start_local, null);
      add(stay(s, s.destination) ?? city(s.destination), s.end_local, s.end_local, "train");
    } else {
      add(stay(s, s.origin) ?? city(s.origin), s.start_local, s.start_local, null);
      for (const port of s.itinerary) add(city(port.name), port.arrive_local ?? s.start_local, port.depart_local ?? port.arrive_local ?? s.end_local, "cruise");
      add(city(s.destination), s.end_local, s.end_local, "cruise");
    }
  }
  return out;
}

const samePlace = (a: Point, b: Point): boolean =>
  a.exact && b.exact ? distanceKm(a, b) < SAME_PLACE_KM : key(a.name) === key(b.name) || distanceKm(a, b) < SAME_PLACE_KM;

const sameStop = (a: Visit, b: Visit): boolean => {
  if (a.kind === "airport" && b.kind === "airport") return a.code === b.code;
  if (a.kind === b.kind || a.kind === "place" || b.kind === "place") return samePlace(a, b);
  return false;
};

function wrapAtHome(merged: Visit[], trip: Trip, places: TripPlaces): void {
  const first = merged[0], last = merged.at(-1);
  if (!places.home || !first || !last || !isRoadTrip(trip)) return;
  const { city, latitude, longitude } = places.home;
  const at: Visit = { name: city, city, code: null, kind: "home", latitude, longitude, from: "", to: "", via: null };
  if (!samePlace(at, first)) merged.unshift({ ...at, from: first.from, to: first.from });
  if (!samePlace(at, last)) merged.push({ ...at, from: last.to, to: last.to });
}

export function stopsOf(trip: Trip, places: TripPlaces): Stop[] {
  const merged: Visit[] = [];
  for (const v of visitsOf(trip, places)) {
    const last = merged.at(-1);
    if (last && sameStop(last, v)) {
      const upgrade = last.kind === "place" && v.kind !== "place";
      const { from, to, via } = last;
      Object.assign(last, upgrade ? v : {});
      last.from = from < v.from ? from : v.from;
      last.to = to > v.to ? to : v.to;
      last.via = via ?? v.via;
    } else merged.push({ ...v });
  }
  wrapAtHome(merged, trip, places);
  return merged.map((v, i) => ({ ...v, back: i > 0 && merged.slice(0, i).some((e) => e.kind === v.kind && sameStop(e, v)) }));
}

export const canReplay = (trip: Trip, today: string, places: TripPlaces | null): boolean =>
  places !== null && worthLocating(trip, today) && stopsOf(trip, places).length >= 2;

const locale = () => (typeof navigator !== "undefined" && navigator.language) || "en-US";

export function stopDates(stop: Stop, year: number): string {
  const first = Date.parse(`${stop.from.slice(0, 10)}T00:00:00Z`), last = Date.parse(`${stop.to.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(first) || Number.isNaN(last)) return "";
  const sameYear = new Date(first).getUTCFullYear() === year && new Date(last).getUTCFullYear() === year;
  const format = new Intl.DateTimeFormat(locale(), { timeZone: "UTC", month: "short", day: "numeric", ...(sameYear ? {} : { year: "numeric" }) });
  return first === last ? format.format(first) : format.formatRange(first, last);
}

export function stopTitle(stop: Stop): string {
  if (stop.kind === "airport") return `${stop.name} (${stop.code})`;
  if (stop.kind === "home") return stop.name;
  if (stop.kind === "stay") return key(stop.city) === key(stop.name) ? `Stay in ${stop.name}` : `Stay: ${stop.name}, ${stop.city}`;
  return stop.name;
}

export const stopLine = (stop: Stop, year: number): string => `${stop.back ? "Back in " : ""}${stopTitle(stop)}, ${stopDates(stop, year)}`;

const lonLat = (s: Point): [number, number] => [s.longitude, s.latitude];

const km = (at: number[], s: Stop): number => geoDistance([at[1], at[0]], [s.longitude, s.latitude]) * EARTH_KM;

export function roadFor(from: Stop, to: Stop, roads: Roads): Roads["legs"][number] | null {
  if (to.via !== null) return null;
  let best: Roads["legs"][number] | null = null;
  let nearest = Infinity;
  for (const leg of roads.legs) {
    const start = leg.points[0], end = leg.points.at(-1);
    if (leg.points.length < 2 || !start || !end) continue;
    const a = km(start, from), b = km(end, to);
    if (a <= ROAD_MATCH_KM && b <= ROAD_MATCH_KM && a + b < nearest) {
      best = leg;
      nearest = a + b;
    }
  }
  return best;
}

type Drawn = { points: number[][]; refs: string[] };
type Located = { index: number; share: number; km: number; at: number[] };
type Retraced = { points: number[][]; refs: string[]; gap: number };

const KM_PER_DEGREE = 111.195;

function locate(points: number[][], stop: Stop): Located | null {
  const scale = Math.cos((stop.latitude * Math.PI) / 180);
  let best: Located | null = null;
  for (let k = 0; k < points.length - 1; k++) {
    const [lat1, lon1] = points[k], [lat2, lon2] = points[k + 1];
    const ax = (lon1 - stop.longitude) * scale, ay = lat1 - stop.latitude, dx = (lon2 - lon1) * scale, dy = lat2 - lat1;
    const span = dx * dx + dy * dy;
    const share = span === 0 ? 0 : Math.min(1, Math.max(0, -(ax * dx + ay * dy) / span));
    const km = Math.hypot(ax + dx * share, ay + dy * share) * KM_PER_DEGREE;
    if (!best || km < best.km) best = { index: k, share, km, at: [lat1 + (lat2 - lat1) * share, lon1 + (lon2 - lon1) * share] };
  }
  return best;
}

const lengthKm = (points: number[][]): number => points.slice(1).reduce((sum, p, i) => sum + geoDistance([points[i][1], points[i][0]], [p[1], p[0]]) * EARTH_KM, 0);

function sectionOf(line: Drawn, from: Stop, to: Stop): Retraced | null {
  const a = locate(line.points, from), b = locate(line.points, to);
  if (!a || !b || Math.max(a.km, b.km) > RETRACE_KM) return null;
  const forward = a.index < b.index || (a.index === b.index && a.share <= b.share);
  const [low, high] = forward ? [a, b] : [b, a];
  const walk = [low.at, ...line.points.slice(low.index + 1, high.index + 1), high.at];
  const points = (forward ? walk : walk.reverse()).filter((p, i, all) => i === 0 || p[0] !== all[i - 1][0] || p[1] !== all[i - 1][1]);
  const km = lengthKm(points);
  if (km <= 0 || km < RETRACE_MIN_SHARE * distanceKm(from, to)) return null;
  const whole = km >= RETRACE_WHOLE_SHARE * lengthKm(line.points);
  return { points, refs: whole ? (forward ? line.refs : [...line.refs].reverse()) : [], gap: a.km + b.km };
}

export function retraceFor(from: Stop, to: Stop, drawn: Drawn[]): Retraced | null {
  if (to.via !== null) return null;
  let best: Retraced | null = null;
  for (const line of drawn) {
    const found = sectionOf(line, from, to);
    if (found && (!best || found.gap < best.gap)) best = found;
  }
  return best;
}

function trackOf(from: Spot, road: number[][], to: Spot, projection: GeoProjection): Track {
  const points = [from];
  for (const [lat, lon] of road) {
    const at = projection([lon, lat]);
    if (at) points.push({ x: at[0], y: at[1] });
  }
  points.push(to);
  const along = [0];
  for (let i = 1; i < points.length; i++) along.push(along[i - 1] + Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y));
  return { points, along };
}

const polyline = (points: Spot[]): string => points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");

export function legsOf(stops: Stop[], projection: GeoProjection, roads: Roads = NO_ROADS): Leg[] {
  const spots = positions(stops, projection);
  const out: Leg[] = [];
  const drawn: Drawn[] = [];
  for (let i = 1; i < stops.length; i++) {
    const from = spots[i - 1], to = spots[i];
    const flight = stops[i].via === "flight";
    const length = Math.hypot(to.x - from.x, to.y - from.y);
    const bow = length * (flight ? BOW : LOCAL_BOW);
    const control = length === 0 ? from : { x: (from.x + to.x) / 2 + ((to.y - from.y) / length) * bow, y: (from.y + to.y) / 2 - ((to.x - from.x) / length) * bow };
    const vehicle: Vehicle = flight ? "plane" : stops[i].via === "cruise" ? "boat" : "car";
    const found = roadFor(stops[i - 1], stops[i], roads);
    if (found) drawn.push({ points: found.points, refs: found.refs });
    const line = found ?? retraceFor(stops[i - 1], stops[i], drawn);
    const road = line ? trackOf(from, line.points, to, projection) : null;
    const curve = `M${from.x.toFixed(1)},${from.y.toFixed(1)} Q${control.x.toFixed(1)},${control.y.toFixed(1)} ${to.x.toFixed(1)},${to.y.toFixed(1)}`;
    out.push({ vehicle, d: road ? polyline(road.points) : curve, flight, from, control, to, road, refs: line ? line.refs : [] });
  }
  return out;
}

export function planeAt(leg: Leg, t: number): { x: number; y: number; angle: number } {
  const u = 1 - t;
  const x = u * u * leg.from.x + 2 * u * t * leg.control.x + t * t * leg.to.x;
  const y = u * u * leg.from.y + 2 * u * t * leg.control.y + t * t * leg.to.y;
  const dx = 2 * u * (leg.control.x - leg.from.x) + 2 * t * (leg.to.x - leg.control.x);
  const dy = 2 * u * (leg.control.y - leg.from.y) + 2 * t * (leg.to.y - leg.control.y);
  return { x, y, angle: (Math.atan2(dy, dx) * 180) / Math.PI };
}

export function moverAt(leg: Leg, t: number): { x: number; y: number; angle: number } {
  if (!leg.road) return planeAt(leg, t);
  const { points, along } = leg.road;
  const total = along[along.length - 1];
  const at = (d: number): Spot => {
    const target = Math.min(total, Math.max(0, d));
    let k = 1;
    while (k < points.length - 1 && along[k] < target) k++;
    const span = along[k] - along[k - 1];
    const u = span === 0 ? 0 : (target - along[k - 1]) / span;
    return { x: points[k - 1].x + (points[k].x - points[k - 1].x) * u, y: points[k - 1].y + (points[k].y - points[k - 1].y) * u };
  };
  const here = total * Math.min(1, Math.max(0, t));
  const ahead = at(here + HEADING_UNITS), behind = at(here - HEADING_UNITS), now = at(here);
  return { x: now.x, y: now.y, angle: (Math.atan2(ahead.y - behind.y, ahead.x - behind.x) * 180) / Math.PI };
}

export function routeProjection(stops: Stop[], width: number, height: number, padding = { x: 100, y: 76 }, roads: Roads = NO_ROADS): GeoProjection {
  const points = stops.map(lonLat);
  const geometries: Geometry[] = [{ type: "MultiPoint", coordinates: points }];
  for (let i = 1; i < points.length; i++) {
    const found = roadFor(stops[i - 1], stops[i], roads);
    geometries.push({ type: "LineString", coordinates: found ? [points[i - 1], ...found.points.map(([lat, lon]) => [lon, lat]), points[i]] : [points[i - 1], points[i]] });
  }
  const [[west, south], [east, north]] = geoBounds({ type: "GeometryCollection", geometries });
  const spanLon = ((east - west) % 360 + 360) % 360, spanLat = north - south;
  if (spanLon < MIN_SPAN_DEGREES || spanLat < MIN_SPAN_DEGREES) {
    const lon = west + spanLon / 2, lat = (north + south) / 2, half = MIN_SPAN_DEGREES / 2;
    geometries.push({ type: "MultiPoint", coordinates: [[lon - half, Math.max(-80, lat - half)], [lon + half, Math.min(80, lat + half)]] });
  }
  return geoEqualEarth().fitExtent([[padding.x, padding.y], [width - padding.x, height - padding.y]], { type: "GeometryCollection", geometries });
}

export function positions(stops: Stop[], projection: GeoProjection): Spot[] {
  const raw = stops.map((s) => {
    const at = projection(lonLat(s));
    return { x: at?.[0] ?? 0, y: at?.[1] ?? 0 };
  });
  return raw.map((p, i) => {
    if (stops[i].kind !== "stay") return p;
    const crowd = raw.slice(0, i).filter((q) => Math.hypot(p.x - q.x, p.y - q.y) < CROWDED_PX).length;
    if (crowd === 0) return p;
    const angle = -Math.PI / 4 + (crowd - 1) * (Math.PI / 2);
    return { x: p.x + NUDGE_PX * Math.cos(angle), y: p.y + NUDGE_PX * Math.sin(angle) };
  });
}

export const legProgress = (leg: number, stops: number, progress: number): number => Math.min(1, Math.max(0, progress * (stops - 1) - leg));

export const reached = (stop: number, stops: number, progress: number): boolean => stop === 0 || progress * (stops - 1) >= stop - 1e-9;

export const activeStop = (stops: number, progress: number): number => Math.min(stops - 1, Math.max(0, Math.floor(progress * (stops - 1) + 1e-9)));

export function labelLit(stop: number, stops: number, progress: number, held: boolean): boolean {
  if (stop === stops - 1 || !reached(stop, stops, progress)) return false;
  if (held && progress < 1 && stop === activeStop(stops, progress)) return true;
  const hold = Math.min(0.85, LABEL_HOLD_MS / (replayMs(stops) / (stops - 1)));
  return progress * (stops - 1) - stop < hold;
}

export type LocalRun = { from: number; to: number };

export function localRuns(stops: Stop[]): LocalRun[] {
  const runs: LocalRun[] = [];
  for (let k = 0; k < stops.length - 1; k++) {
    if (stops[k].via !== "flight" || stops[k + 1].via === "flight") continue;
    let m = k + 1;
    while (m + 1 < stops.length && stops[m + 1].via !== "flight") m++;
    runs.push({ from: k, to: m });
    k = m - 1;
  }
  return runs;
}

const smooth = (t: number): number => {
  const c = Math.min(1, Math.max(0, t));
  return c * c * (3 - 2 * c);
};

export function roadShapes(lines: Roads["interstates"], projection: GeoProjection): RoadShape[] {
  const out: RoadShape[] = [];
  for (const line of lines) {
    const points: Spot[] = [];
    for (const [lat, lon] of line.points) {
      const at = projection([lon, lat]);
      if (at) points.push({ x: at[0], y: at[1] });
    }
    if (points.length < 2) continue;
    const along = [0];
    for (let i = 1; i < points.length; i++) along.push(along[i - 1] + Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y));
    const half = along[along.length - 1] / 2;
    const k = Math.max(1, along.findIndex((a) => a >= half));
    const xs = points.map((p) => p.x), ys = points.map((p) => p.y);
    out.push({ ref: line.ref, d: polyline(points), left: Math.min(...xs), top: Math.min(...ys), right: Math.max(...xs), bottom: Math.max(...ys), length: along[along.length - 1], mid: points[k] });
  }
  return out;
}

export function boundaryShapes(lines: Boundaries, projection: GeoProjection): BoundaryShape[] {
  const out: BoundaryShape[] = [];
  for (const line of lines) {
    const points: Spot[] = [];
    for (const [lat, lon] of line.points) {
      const at = projection([lon, lat]);
      if (at) points.push({ x: at[0], y: at[1] });
    }
    if (points.length < 2) continue;
    const xs = points.map((p) => p.x), ys = points.map((p) => p.y);
    out.push({ d: polyline(points), left: Math.min(...xs), top: Math.min(...ys), right: Math.max(...xs), bottom: Math.max(...ys) });
  }
  return out;
}

export const boundariesShown = (projection: GeoProjection, zoom: number): boolean => projection.scale() / zoom >= BOUNDARY_MIN_SCALE;

export const roadsShown = (projection: GeoProjection, zoom: number): boolean => projection.scale() / zoom >= ROAD_MIN_SCALE;

export const inView = (shape: Extent, box: Box): boolean => shape.right >= box.x && shape.left <= box.x + box.w && shape.bottom >= box.y && shape.top <= box.y + box.h;

export function shieldsOf(shapes: RoadShape[], box: Box, zoom: number): Shield[] {
  const gap = SHIELD_GAP * zoom;
  const out: Shield[] = [];
  for (const shape of [...shapes].sort((a, b) => b.length - a.length)) {
    if (out.length >= MAX_SHIELDS) break;
    const { x, y } = shape.mid;
    if (x < box.x + 12 * zoom || x > box.x + box.w - 12 * zoom || y < box.y + 12 * zoom || y > box.y + box.h - 12 * zoom) continue;
    if (out.some((s) => Math.hypot(s.x - x, s.y - y) < (s.ref === shape.ref ? gap : gap / 2))) continue;
    out.push({ ref: shape.ref, x, y });
  }
  return out;
}

export function cameraAt(stops: Stop[], spots: Spot[], width: number, height: number, progress: number, legs: Leg[] = []): Box {
  const full: Box = { x: 0, y: 0, w: width, h: height };
  const units = progress * (stops.length - 1);
  let best = 0;
  let target = full;
  for (const run of localRuns(stops)) {
    if (units < run.from || units > run.to) continue;
    const share = Math.min(smooth((units - run.from) / ZOOM_UNITS), smooth((run.to - units) / ZOOM_UNITS));
    if (share <= best) continue;
    const area = [...spots.slice(run.from, run.to + 1), ...legs.slice(run.from, run.to).flatMap((l) => l.road?.points ?? [])];
    const xs = area.map((p) => p.x), ys = area.map((p) => p.y);
    const w = Math.min(width, Math.max(width * MIN_ZOOM_SHARE, (Math.max(...xs) - Math.min(...xs)) * 1.6, ((Math.max(...ys) - Math.min(...ys)) * 1.6 * width) / height));
    const h = (w * height) / width;
    const cx = (Math.max(...xs) + Math.min(...xs)) / 2, cy = (Math.max(...ys) + Math.min(...ys)) / 2;
    best = share;
    target = { x: Math.min(width - w, Math.max(0, cx - w / 2)), y: Math.min(height - h, Math.max(0, cy - h / 2)), w, h };
  }
  return { x: full.x + (target.x - full.x) * best, y: full.y + (target.y - full.y) * best, w: width + (target.w - width) * best, h: height + (target.h - height) * best };
}
