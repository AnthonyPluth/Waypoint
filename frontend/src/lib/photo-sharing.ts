import type { Person, PhotoGrantPerson, PhotoGrantTrip, PhotoPrefsBody, PhotoSharing, PhotoSharingBody } from "./api-types";
import { apiCall } from "./contract";
import { clock, dayLabel } from "./trips";

export type Scope = "only_me" | "trip";

export const COULDNT_CHECK = "Couldn’t check your libraries";

export const plural = (n: number, one: string, many: string): string => `${n.toLocaleString()} ${n === 1 ? one : many}`;

export const unsharedOf = (p: PhotoGrantPerson): PhotoGrantTrip[] => p.trips.filter((t) => t.state !== "shared");

export const photosOf = (trips: PhotoGrantTrip[]): number | null =>
  trips.some((t) => t.count === null) ? null : trips.reduce((sum, t) => sum + (t.count ?? 0), 0);

export const isStale = (err: unknown): boolean => (err as { status?: unknown } | null)?.status === 409;

export type Who = { mine: boolean; first: string; own: string; subject: string; joins: string; shares: string; only: string; library: string };

export function whoIs(personId: number, me: number | null, people: Person[]): Who {
  const found = people.find((p) => p.id === personId);
  const name = found?.display_name ?? "Someone";
  const first = found?.first_name ?? name.split(" ")[0];
  const mine = personId === me;
  return {
    mine, first, own: mine ? "your" : `${first}’s`, subject: mine ? "you" : first, joins: mine ? "you join" : `${first} joins`,
    shares: mine ? "you share" : `${first} shares`, only: mine ? "Only me" : `Only ${first}`, library: mine ? "your library" : `${first}’s library`,
  };
}

export const sharedWith = (scope: Scope, who: Who | null = null): string => (scope === "trip" ? "everyone on this trip" : who && !who.mine ? `${who.first} only` : "you only");

export const stateOf = (personId: number, tripId: number) =>
  apiCall<"GET /api/trips/{id}/photo-sharing">(`/api/trips/${tripId}/photo-sharing?person_id=${personId}`, { keep: true });

export const shareBody = (personId: number, s: PhotoSharing, scope: Scope): PhotoSharingBody => ({
  person_id: personId, scope, window: s.window ?? undefined, audience: s.audience, sources: s.sources, count_token: s.count_token,
  ...(s.changed !== null && { expected_changed: s.changed }),
});

export const shareAllBody = (p: PhotoGrantPerson, scope?: Scope): PhotoPrefsBody => ({
  ...(scope && { default_scope: scope }),
  share_all: true, sources: p.sources, count_token: p.count_token,
  windows: Object.fromEntries(p.eligible.map((t) => [String(t.trip_id), t.window])), audiences: Object.fromEntries(p.eligible.map((t) => [String(t.trip_id), t.audience])),
});

export function widenTitle(who: Who, count: number | null): string {
  return count === null ? `Show ${who.own} photos to everyone on this trip?` : `Show ${who.own} ${plural(count, "photo", "photos")} to everyone on this trip?`;
}

export function allTitle(who: Who, p: PhotoGrantPerson, photos: number | null): string {
  if (!p.eligible.length) return `Show ${who.own} photos on trips ${who.joins} later to everyone on them?`;
  const trips = plural(p.eligible.length, "trip", "trips");
  return photos === null ? `Show ${who.own} photos to everyone on ${trips}?` : `Show ${who.own} ${plural(photos, "photo", "photos")} to everyone on ${trips}?`;
}

export type ResumeKind = "resume" | "connect";

export const resumeTitle = (library: string, kind: ResumeKind): string => (kind === "connect" ? `${library} is connected. Resume it now?` : `Resume ${library}?`);

export function resumeText(who: Who, kind: ResumeKind, count: number, trips: number): string {
  const lead = who.mine ? "Your" : `${who.first}’s`;
  const where = `everyone on ${plural(trips, "trip", "trips")}`;
  const state = kind === "connect" ? "is connected and paused, until you confirm this" : "is paused";
  const effect = count
    ? `Resuming it shows ${plural(count, "photo", "photos")} from it to everyone on ${trips === 1 ? "that trip" : "those trips"}: in the gallery, on the map, in the replay and in the trip’s counts.`
    : "Resuming it adds no new photos to those trips, but they are shared with everyone, so Waypoint asks first.";
  return `${lead} library ${state}, because ${who.shares} photos with ${where}. ${effect} Nothing changes in Immich.`;
}

export const resumeStale = "Your trips changed meanwhile, so what’s below is new. Check it, then press Resume again.";

export const resumeUnchecked = "Your trips changed meanwhile, and Waypoint couldn’t check them again, so what’s below may be out of date.";

export const resumeSettled = "Your trips changed meanwhile and nothing needs confirming now, so nothing was resumed. Press Resume again.";

export const stopTitle = (who: Who): string => `Stop sharing ${who.own} photos on this trip?`;

export function stopText(who: Who, tripName: string, count: number | null): string {
  const lead = who.mine ? "Your" : `${who.first}’s`;
  return `${lead} ${count ? `${plural(count, "photo", "photos")} leave` : "photos leave"} ${tripName} right away, for everyone: the gallery, the map, the replay and the trip’s counts. Nothing changes in Immich, and you can share them again later.`;
}

export const widenText = (who: Who, tripName: string): string => `Everyone else on ${tripName} will see ${who.own} photos there, on the map and in the counts too.`;

export const narrowedToast = (who: Who, where: string): string => `Now only ${who.subject} see${who.mine ? "" : "s"} ${who.own} photos on ${where}.`;

export const photosTitle = (who: Who): string => (who.mine ? "Your photos on this trip" : `${who.first}’s photos on this trip`);

export const MAX_REMOVED = 500;

export const REMOVE = "Remove from this trip";

export const removeText = (who: Who, count = 1): string => (who.mine ? REMOVE : `Remove ${who.first}’s ${count === 1 ? "photo" : "photos"} from this trip`);

export function removedToast(who: Who, count: number, tripName: string): string {
  if (who.mine) return count === 1 ? `Removed from ${tripName}.` : `${count} photos removed from ${tripName}.`;
  return count === 1 ? `Removed ${who.first}’s photo from ${tripName}.` : `${count} of ${who.first}’s photos removed from ${tripName}.`;
}

export const removedTitle = (n: number): string => `Removed from this trip (${n})`;

export const removedList = (who: Who): string => (who.mine ? "Photos you removed from this trip" : `${who.first}’s photos removed from this trip`);

export const putBackLabel = (p: { kind: "image" | "video"; taken_local: string }): string =>
  `Put back the ${p.kind === "video" ? "video" : "photo"} from ${dayLabel(p.taken_local)}, ${clock(p.taken_local)}`;

export const removedThumbnail = (tripId: number, photoId: number): string => `/api/trips/${tripId}/photo-exclusions/${photoId}/thumbnail`;

export function toggled(selected: ReadonlySet<number>, id: number, max = MAX_REMOVED): Set<number> {
  const next = new Set(selected);
  if (next.has(id)) next.delete(id);
  else if (next.size < max) next.add(id);
  return next;
}
