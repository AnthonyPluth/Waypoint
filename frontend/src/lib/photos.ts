import type { Person, PhotoCluster, Segment, Trip, TripPhoto } from "./api-types";
import { datesOf } from "./route-replay";
import { clock, daysBetween, headline } from "./trips";

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

export const clusterOf = (p: Pick<TripPhoto, "cluster">, clusters: PhotoCluster[]): PhotoCluster | null =>
  p.cluster === null ? null : clusters[p.cluster] ?? null;

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

export type ClusterInfo = { index: number; cluster: PhotoCluster; place: string; far: number; farKm: number | null; first: TripPhoto | null };

const noun = (n: number): string => `${n} ${n === 1 ? "photo" : "photos"}`;

export function clusterInfos(photos: TripPhoto[], clusters: PhotoCluster[], segments: Map<number, Segment>): ClusterInfo[] {
  const members = new Map<number, TripPhoto[]>();
  for (const p of photos) {
    if (p.cluster === null) continue;
    const list = members.get(p.cluster);
    if (list) list.push(p);
    else members.set(p.cluster, [p]);
  }
  return clusters.map((cluster, index) => {
    const list = (members.get(index) ?? []).slice().sort((a, b) => a.taken_local.localeCompare(b.taken_local) || a.id - b.id);
    const tally = new Map<string, number>();
    for (const p of list) {
      if (isFar(p)) continue;
      const place = placeOf(p, p.segment_id === null ? undefined : segments.get(p.segment_id));
      if (place) tally.set(place, (tally.get(place) ?? 0) + 1);
    }
    const place = [...tally].sort((a, b) => b[1] - a[1])[0]?.[0] ?? "";
    const far = list.filter(isFar);
    const km = far.map((p) => p.distance_km).filter((d): d is number => d !== null);
    return { index, cluster, place, far: far.length, farKm: km.length ? Math.min(...km) : null, first: list[0] ?? null };
  });
}

export const clusterAway = (info: ClusterInfo): boolean => info.far > 0 && info.far >= info.cluster.count;

export function clusterTitle(info: ClusterInfo): string {
  const { cluster, place } = info;
  let what = noun(cluster.count);
  if (clusterAway(info)) what += `, ${kilometres(info.farKm)} from every booking`;
  else {
    if (cluster.inferred) what += " placed from the itinerary";
    if (place) what += ` near ${place}`;
    if (info.far > 0) what += `, ${info.far} of them ${kilometres(info.farKm)} from every booking`;
  }
  return what;
}

export const clusterName = (info: ClusterInfo, year: number): string =>
  [clusterTitle(info), datesOf(info.cluster.first, info.cluster.last, year)].filter(Boolean).join(", ");

export function clusterCaption(info: ClusterInfo, year: number): string {
  const { cluster, place } = info;
  const dates = datesOf(cluster.first, cluster.last, year, true);
  const where = clusterAway(info) ? `${kilometres(info.farKm)} from every booking` : place ? `${cluster.inferred ? "from the itinerary, " : ""}near ${place}` : cluster.inferred ? "placed from the itinerary" : "";
  return [dates, where].filter(Boolean).join(" · ");
}

export const clusterCount = (info: ClusterInfo): string => noun(info.cluster.count);

export const firstOfCluster = (photos: TripPhoto[], index: number): TripPhoto | null =>
  photos.filter((p) => p.cluster === index).sort((a, b) => a.taken_local.localeCompare(b.taken_local) || a.id - b.id)[0] ?? null;

export const unlocated = (photos: TripPhoto[]): number => photos.filter((p) => p.cluster === null).length;
