import type { OfflineTrip } from "./api-types";
import { apiCall } from "./contract";
import { clearTrip, dropTrips, isSavingOff, isSetUp, saveAll, savedInfos, setSavingOff, type SavedInfo } from "./offline-vault";

export const KEEP_DAYS_AFTER_TRIP = 3;
const LONGEST_TIMER = 2 ** 31 - 1;

export type SavedCopy = OfflineTrip & { savedAt: number };
export type SavedTrip = { id: number; name: string };
export type SavedNow = { savedAt: number; trips: SavedTrip[] };

export function expiryOf(copy: Pick<OfflineTrip, "trip">): number | null {
  const last = copy.trip.end_date ?? copy.trip.start_date;
  if (!last) return null;
  const [y, m, d] = last.split("-").map(Number);
  return new Date(y, m - 1, d + 1 + KEEP_DAYS_AFTER_TRIP).getTime();
}

export function isSavedCopy(v: unknown): v is SavedCopy {
  const copy = v as Partial<SavedCopy> | null;
  return !!copy && typeof copy === "object" && typeof copy.savedAt === "number" && Array.isArray(copy.messages)
    && !!copy.trip && Array.isArray(copy.trip.segments) && typeof copy.trip.name === "string";
}

export function ago(savedAt: number, now: number): string {
  const minutes = Math.max(0, Math.round((now - savedAt) / 60_000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

let expiryTimer: ReturnType<typeof setTimeout> | null = null;
let onExpired: () => void = () => {};

export function whenExpired(fn: () => void): void {
  onExpired = fn;
}

const nextExpiry = (infos: SavedInfo[]): number | null => infos.reduce<number | null>((soonest, i) => (i.expiresAt === null || (soonest !== null && soonest <= i.expiresAt) ? soonest : i.expiresAt), null);

async function expire(): Promise<void> {
  try {
    const left = await dropExpired(await savedInfos());
    watchExpiry(left);
    onExpired();
  } catch (err) {
    console.error(err);
  }
}

export function watchExpiry(infos: SavedInfo[]): void {
  if (expiryTimer) clearTimeout(expiryTimer);
  expiryTimer = null;
  const at = nextExpiry(infos);
  if (at === null) return;
  expiryTimer = setTimeout(() => { void expire(); }, Math.min(Math.max(0, at - Date.now()), LONGEST_TIMER));
}

let inFlight: Promise<SavedNow | null> | null = null;
let clears = 0;

export async function clearSaved(): Promise<void> {
  watchExpiry([]);
  clears++;
  await inFlight?.catch(() => null);
  try {
    await clearTrip();
  } catch {
    try { await clearTrip(); } catch { throw new Error("Couldn’t remove the saved trips from this device."); }
  }
}

export async function dropExpired(infos: SavedInfo[]): Promise<SavedInfo[]> {
  const now = Date.now();
  const over = (i: SavedInfo) => i.expiresAt !== null && now >= i.expiresAt;
  const gone = infos.filter(over);
  if (gone.length === 0) return infos;
  if (gone.some((i) => i.tripId === undefined)) {
    await clearSaved();
    return [];
  }
  await dropTrips(gone.map((i) => i.tripId as number));
  return infos.filter((i) => !over(i));
}

async function replaceSaved(): Promise<SavedNow | null> {
  if (!(await isSetUp()) || (await isSavingOff())) return null;
  const before = clears;
  const projection = await apiCall<"GET /api/offline">("/api/offline");
  if (clears !== before) return null;
  if (projection.trips.length === 0) { watchExpiry([]); await clearTrip(); return null; }
  const savedAt = Date.now();
  const items = projection.trips.map((one) => {
    const info: SavedInfo = { savedAt, expiresAt: expiryOf(one), tripId: one.trip.id };
    const copy: SavedCopy = { ...one, savedAt };
    return { value: copy, info };
  });
  if (!(await saveAll(items))) return null;
  watchExpiry(items.map((i) => i.info));
  return { savedAt, trips: projection.trips.map((one) => ({ id: one.trip.id, name: one.trip.name })) };
}

export function saveCurrentTrip(): Promise<SavedNow | null> {
  inFlight ??= replaceSaved().finally(() => { inFlight = null; });
  return inFlight;
}

export async function stopSaving(): Promise<void> {
  await setSavingOff(true);
  await clearSaved();
}

export async function resumeSaving(): Promise<void> {
  await setSavingOff(false);
}

export { savedInfos };

export function savedList(trips: { name: string }[]): string {
  if (trips.every((t) => t.name)) return trips.map((t) => `“${t.name}”`).join(", ");
  return trips.length === 1 ? "1 trip" : `${trips.length} trips`;
}

export const WHEN_SAVED = "Your trips under way or starting within a week, and your next upcoming trip, are saved when you open Waypoint online.";
export const ONLY_THESE = "Only trips under way or starting within a week, and your next upcoming trip, are saved.";
