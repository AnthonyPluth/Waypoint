import { geoBounds, geoDistance, geoEqualEarth, geoPath, type GeoProjection } from "d3-geo";
import type { Geometry } from "geojson";
import type { Segment, Trip, TripPlaces } from "./api-types";
import { instant, isPast } from "./trips";

export type Kind = Segment["kind"];
export type Stop = { name: string; latitude: number; longitude: number; from: string; to: string; via: Kind | null; back: boolean };
export type Leg = { d: string; flight: boolean };
type Visit = Omit<Stop, "back"> & { exact?: boolean };
type Point = { name: string; latitude: number; longitude: number; exact?: boolean };

export const MIN_SPAN_DEGREES = 10;
export const SAME_PLACE_KM = 30;
export const MIN_MS = 6000;
export const MAX_MS = 12000;
export const PER_STOP_MS = 2000;

const EARTH_KM = 6371;
const key = (text: string | null | undefined): string => (text ?? "").trim().toLowerCase();
const head = (text: string): string => text.split(",")[0].trim();

export const replayMs = (stops: number): number => Math.min(MAX_MS, Math.max(MIN_MS, stops * PER_STOP_MS));

export const distanceKm = (a: Point, b: Point): number => geoDistance([a.longitude, a.latitude], [b.longitude, b.latitude]) * EARTH_KM;

function finder(places: TripPlaces) {
  const airports = new Map(places.airports.map((a) => [a.code.toUpperCase(), a]));
  const cities = new Map(places.cities.map((c) => [key(c.city), c]));
  const airport = (code: string | null): Point | null => {
    const found = airports.get((code ?? "").trim().toUpperCase());
    return found ? { name: found.city, latitude: found.latitude, longitude: found.longitude } : null;
  };
  const city = (text: string | null): Point | null => {
    const found = cities.get(key(text)) ?? cities.get(key(head(text ?? "")));
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
  const add = (p: Point | null, from: string, to: string, via: Kind | null) => { if (p) out.push({ ...p, from, to, via }); };
  for (const s of live) {
    if (s.kind === "flight") {
      add(airport(s.origin), s.start_local, s.start_local, null);
      add(airport(s.destination), s.end_local, s.end_local, "flight");
    } else if (s.kind === "hotel") {
      add(stay(s, s.destination) ?? city(s.destination), s.start_local, s.end_local, null);
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

export function stopsOf(trip: Trip, places: TripPlaces): Stop[] {
  const merged: Visit[] = [];
  for (const v of visitsOf(trip, places)) {
    const last = merged.at(-1);
    if (last && samePlace(last, v)) {
      if (v.to > last.to) last.to = v.to;
      if (v.from < last.from) last.from = v.from;
      last.via ??= v.via;
    } else merged.push({ ...v });
  }
  return merged.map((v, i) => ({ ...v, back: i > 0 && merged.slice(0, i).some((e) => samePlace(e, v)) }));
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

export const stopLine = (stop: Stop, year: number): string => `${stop.back ? "Back in " : ""}${stop.name}, ${stopDates(stop, year)}`;

const lonLat = (s: Point): [number, number] => [s.longitude, s.latitude];

export function legsOf(stops: Stop[], projection: GeoProjection): Leg[] {
  const path = geoPath(projection);
  const out: Leg[] = [];
  for (let i = 1; i < stops.length; i++) {
    const d = path({ type: "LineString", coordinates: [lonLat(stops[i - 1]), lonLat(stops[i])] });
    if (d) out.push({ d, flight: stops[i].via === "flight" });
  }
  return out;
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

export function positions(stops: Stop[], projection: GeoProjection): { x: number; y: number }[] {
  return stops.map((s) => {
    const at = projection(lonLat(s));
    return { x: at?.[0] ?? 0, y: at?.[1] ?? 0 };
  });
}

export const legProgress = (leg: number, stops: number, progress: number): number => Math.min(1, Math.max(0, progress * (stops - 1) - leg));

export const reached = (stop: number, stops: number, progress: number): boolean => stop === 0 || progress * (stops - 1) >= stop - 1e-9;

export const activeStop = (stops: number, progress: number): number => Math.min(stops - 1, Math.max(0, Math.floor(progress * (stops - 1) + 1e-9)));
