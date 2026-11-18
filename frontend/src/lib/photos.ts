import type { Person, Segment, Trip, TripPhoto, TripPhotos } from "./api-types";
import { clock, dayLabel, daysBetween, headline } from "./trips";

export type PhotoDay = { day: string; photos: TripPhoto[] };

export const STRIP_SIZE = 10;
export const PAGE_SIZE = 48;

export const localDay = (p: Pick<TripPhoto, "taken_local">): string => p.taken_local.slice(0, 10);

export function byDay(photos: TripPhoto[]): PhotoDay[] {
  const days = new Map<string, TripPhoto[]>();
  for (const p of photos) {
    const day = localDay(p);
    const found = days.get(day);
    if (found) found.push(p);
    else days.set(day, [p]);
  }
  return [...days].sort(([a], [b]) => a.localeCompare(b)).map(([day, list]) => ({ day, photos: list }));
}

export const isInferred = (p: Pick<TripPhoto, "location_source">): boolean => p.location_source === "inferred";
export const isFar = (p: Pick<TripPhoto, "match">): boolean => p.match === "far";

export const FROM_ITINERARY = "From the itinerary";
export const FAR_FROM_BOOKINGS = "Far from the trip’s bookings";

export const thumbnailUrl = (id: number): string => `/api/photos/${id}/thumbnail`;
export const previewUrl = (id: number): string => `/api/photos/${id}/preview`;
export const originalUrl = (id: number): string => `/api/photos/${id}/original`;

export const kilometres = (km: number | null): string => `${Math.round(km ?? 0).toLocaleString("en-US")} km`;

export const zoneCity = (zone: string | null): string => (zone ? (zone.split("/").pop() ?? zone).replaceAll("_", " ") : "");

export function placeOf(p: Pick<TripPhoto, "taken_local">, s: Segment | undefined): string {
  if (!s) return "";
  if (s.kind === "hotel") return s.destination || s.origin || headline(s);
  if (s.kind === "flight" || s.kind === "train") return (p.taken_local <= s.start_local ? s.origin : s.destination) || headline(s);
  if (s.kind === "visit") return headline(s);
  return s.origin || s.destination || headline(s);
}

export const personName = (people: Person[], id: number): string => {
  const found = people.find((who) => who.id === id);
  return found ? found.first_name || found.display_name : "";
};

export const fullName = (people: Person[], id: number): string => people.find((who) => who.id === id)?.display_name ?? "";

export function tileLabel(p: TripPhoto, segment: Segment | undefined, owner: string): string {
  const place = placeOf(p, segment);
  const parts = [p.kind === "video" ? "Video" : "Photo", clock(p.taken_local)];
  if (place && !isFar(p)) parts.push(isInferred(p) ? place : `near ${place}`);
  if (owner) parts.push(`${owner}’s library`);
  if (isInferred(p)) parts.push("place from the itinerary");
  if (isFar(p)) parts.push(`${kilometres(p.distance_km)} from every booking`);
  return parts.join(", ");
}

export function dayCaption(trip: Pick<Trip, "start_date">, group: PhotoDay, segments: Map<number, Segment>): string {
  const places: string[] = [];
  let far = 0;
  for (const p of group.photos) {
    if (isFar(p)) { far++; continue; }
    const place = placeOf(p, p.segment_id === null ? undefined : segments.get(p.segment_id));
    if (place && !places.includes(place)) places.push(place);
  }
  const where = [places.join(", "), far ? `${places.length ? "and " : ""}${far} far away` : ""].filter(Boolean).join(", ");
  const count = `${group.photos.length} ${group.photos.length === 1 ? "photo" : "photos"}`;
  const day = trip.start_date ? `Day ${daysBetween(`${trip.start_date}T00:00`, `${group.day}T00:00`) + 1}` : "";
  return [day, where, count].filter(Boolean).join(" · ");
}

export function daysFor(days: PhotoDay[], from: number, size = PAGE_SIZE): number {
  let count = 0;
  let to = from;
  while (to < days.length && count < size) {
    count += days[to].photos.length;
    to++;
  }
  return to;
}

const noun = (n: number): string => `${n} ${n === 1 ? "photo" : "photos"}`;

export const HERO_PHOTOS = 3;
export const HERO_PHOTOS_WIDE = 7;
export const DAY_PHOTOS = 6;
export const DAY_PHOTOS_WIDE = 12;
export const FIRST_DAYS = 3;

export type HeroPhotos = Pick<TripPhotos, "photos" | "best">;

export function heroOf(reply: HeroPhotos | null, wide = false): number[] {
  if (!reply) return [];
  const seen = new Set(reply.photos.map((p) => p.id));
  const ids = [...new Set(reply.best)].filter((id) => seen.has(id));
  if (wide && ids.length >= HERO_PHOTOS_WIDE) return ids.slice(0, HERO_PHOTOS_WIDE);
  return ids.length >= HERO_PHOTOS ? ids.slice(0, HERO_PHOTOS) : [];
}

export const hasGps = (p: Pick<TripPhoto, "latitude" | "longitude" | "location_source">): boolean => p.latitude !== null && p.longitude !== null && !isInferred(p);

const inTime = (a: TripPhoto, b: TripPhoto): number => a.taken_local.localeCompare(b.taken_local) || a.id - b.id;

export function dayCover(photos: TripPhoto[]): TripPhoto | null {
  const sorted = photos.slice().sort(inTime);
  return sorted.find(hasGps) ?? sorted[0] ?? null;
}

export function leadWithCover(photos: TripPhoto[]): TripPhoto[] {
  const sorted = photos.slice().sort(inTime);
  const cover = dayCover(sorted);
  return cover ? [cover, ...sorted.filter((p) => p.id !== cover.id)] : [];
}

export function dayPlace(photos: TripPhoto[], segments: Map<number, Segment>): string {
  const tally = new Map<string, number>();
  for (const p of photos.slice().sort(inTime)) {
    if (isFar(p)) continue;
    const place = placeOf(p, p.segment_id === null ? undefined : segments.get(p.segment_id));
    if (place) tally.set(place, (tally.get(place) ?? 0) + 1);
  }
  return [...tally].sort((a, b) => b[1] - a[1])[0]?.[0] ?? "";
}

export type PastDay = { day: string; label: string; place: string; photos: TripPhoto[]; shown: TripPhoto[]; more: number };

export const dayWords = (day: string): string => dayLabel(`${day}T00:00`, false).replace(/^([^,]+),\s*/, "$1 ");

export function pastDays(photos: TripPhoto[], leftOut: ReadonlySet<number>, segments: Map<number, Segment>, perDay = DAY_PHOTOS): PastDay[] {
  return byDay(photos.filter((p) => !leftOut.has(p.id))).map(({ day, photos: list }) => {
    const ordered = leadWithCover(list);
    return { day, label: dayWords(day), place: dayPlace(list, segments), photos: ordered, shown: ordered.slice(0, perDay), more: Math.max(0, ordered.length - perDay) };
  });
}

export const dayPhotoCount = (day: Pick<PastDay, "photos">): string => noun(day.photos.length);

export function dayTileName(day: Pick<PastDay, "label" | "place" | "more">, n: number, last: boolean, p?: Pick<TripPhoto, "kind" | "match" | "location_source">): string {
  const word = p?.kind === "video" ? "Video" : "Photo";
  const lead = last && day.more > 0 ? `${word} ${n} and ${day.more} more` : `${word} ${n}`;
  const notes = p ? [isFar(p) ? "far from every booking" : "", isInferred(p) ? "place from the itinerary" : ""] : [];
  return [lead, day.label, day.place, ...notes].filter(Boolean).join(", ");
}

export const heroCaption = (trip: Pick<Trip, "destination">, dates: string): string => [dates, trip.destination].filter(Boolean).join(" · ");
