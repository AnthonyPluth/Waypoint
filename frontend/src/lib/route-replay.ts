import { geoBounds, geoDistance, geoEqualEarth, type GeoProjection } from "d3-geo";
import type { Geometry } from "geojson";
import type { Segment, Trip, TripPlaces } from "./api-types";
import { instant, isPast } from "./trips";

export type Kind = Segment["kind"];
export type StopKind = "airport" | "stay" | "place";
export type Stop = { name: string; city: string; code: string | null; kind: StopKind; latitude: number; longitude: number; from: string; to: string; via: Kind | null; back: boolean };
export type Spot = { x: number; y: number };
export type Vehicle = "plane" | "car" | "boat";
export type Leg = { d: string; flight: boolean; vehicle: Vehicle; from: Spot; control: Spot; to: Spot };
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
export const STATIC_MOVER_PX = 16;
export const MIN_MS = 6000;
export const MAX_MS = 12000;
export const PER_STOP_MS = 2000;
export const LABEL_HOLD_MS = 1750;

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

export function maxStops(trip: Trip): number {
  return trip.segments.filter((s) => s.status !== "cancelled").reduce((n, s) => {
    if (s.kind === "parking") return n;
    if (s.kind === "flight" || s.kind === "train") return n + 2;
    if (s.kind === "cruise") return n + 2 + s.itinerary.length;
    return n + 1;
  }, 0);
}

export const worthLocating = (trip: Trip, today: string): boolean => isPast(trip, today) && maxStops(trip) >= 2;

function visitsOf(trip: Trip, places: TripPlaces): Visit[] {
  const { airport, city, stay } = finder(places);
  const live = trip.segments.filter((s) => s.status !== "cancelled" && s.kind !== "parking")
    .sort((a, b) => instant(a.start_local, a.start_zone) - instant(b.start_local, b.start_zone) || a.id - b.id);
  const out: Visit[] = [];
  const add = (p: Point | null, from: string, to: string, via: Kind | null) => {
    if (p) out.push({ ...p, city: p.city ?? p.name, code: p.code ?? null, kind: p.kind ?? "place", from, to, via });
  };
  for (const s of live) {
    if (s.kind === "flight") {
      add(airport(s.origin), s.start_local, s.start_local, null);
      add(airport(s.destination), s.end_local, s.end_local, "flight");
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
  if (stop.kind === "stay") return key(stop.city) === key(stop.name) ? `Stay in ${stop.name}` : `Stay: ${stop.name}, ${stop.city}`;
  return stop.name;
}

export const stopLine = (stop: Stop, year: number): string => `${stop.back ? "Back in " : ""}${stopTitle(stop)}, ${stopDates(stop, year)}`;

const lonLat = (s: Point): [number, number] => [s.longitude, s.latitude];

export function legsOf(stops: Stop[], projection: GeoProjection): Leg[] {
  const spots = positions(stops, projection);
  const out: Leg[] = [];
  for (let i = 1; i < stops.length; i++) {
    const from = spots[i - 1], to = spots[i];
    const flight = stops[i].via === "flight";
    const length = Math.hypot(to.x - from.x, to.y - from.y);
    const bow = length * (flight ? BOW : LOCAL_BOW);
    const control = length === 0 ? from : { x: (from.x + to.x) / 2 + ((to.y - from.y) / length) * bow, y: (from.y + to.y) / 2 - ((to.x - from.x) / length) * bow };
    const vehicle: Vehicle = flight ? "plane" : stops[i].via === "cruise" ? "boat" : "car";
    out.push({ vehicle, d: `M${from.x.toFixed(1)},${from.y.toFixed(1)} Q${control.x.toFixed(1)},${control.y.toFixed(1)} ${to.x.toFixed(1)},${to.y.toFixed(1)}`, flight, from, control, to });
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

export function routeProjection(stops: Stop[], width: number, height: number, padding = { x: 100, y: 76 }): GeoProjection {
  const points = stops.map(lonLat);
  const geometries: Geometry[] = [{ type: "MultiPoint", coordinates: points }];
  for (let i = 1; i < points.length; i++) geometries.push({ type: "LineString", coordinates: [points[i - 1], points[i]] });
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

export function cameraAt(stops: Stop[], spots: Spot[], width: number, height: number, progress: number): Box {
  const full: Box = { x: 0, y: 0, w: width, h: height };
  const units = progress * (stops.length - 1);
  let best = 0;
  let target = full;
  for (const run of localRuns(stops)) {
    if (units < run.from || units > run.to) continue;
    const share = Math.min(smooth((units - run.from) / ZOOM_UNITS), smooth((run.to - units) / ZOOM_UNITS));
    if (share <= best) continue;
    const area = spots.slice(run.from, run.to + 1);
    const xs = area.map((p) => p.x), ys = area.map((p) => p.y);
    const w = Math.min(width, Math.max(width * MIN_ZOOM_SHARE, (Math.max(...xs) - Math.min(...xs)) * 1.6, ((Math.max(...ys) - Math.min(...ys)) * 1.6 * width) / height));
    const h = (w * height) / width;
    const cx = (Math.max(...xs) + Math.min(...xs)) / 2, cy = (Math.max(...ys) + Math.min(...ys)) / 2;
    best = share;
    target = { x: Math.min(width - w, Math.max(0, cx - w / 2)), y: Math.min(height - h, Math.max(0, cy - h / 2)), w, h };
  }
  return { x: full.x + (target.x - full.x) * best, y: full.y + (target.y - full.y) * best, w: width + (target.w - width) * best, h: height + (target.h - height) * best };
}
