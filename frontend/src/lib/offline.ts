import type { Offline } from "./api-types";
import { apiCall } from "./contract";
import { clearTrip, isSavingOff, isSetUp, save, savedInfo, setSavingOff, type SavedInfo } from "./offline-vault";

export const KEEP_DAYS_AFTER_TRIP = 3;
const LONGEST_TIMER = 2 ** 31 - 1;

export type SavedCopy = Offline & { savedAt: number };

export function expiryOf(copy: Pick<Offline, "trip">): number | null {
  const last = copy.trip?.end_date ?? copy.trip?.start_date;
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

async function expire(): Promise<void> {
  try {
    await clearSaved();
    onExpired();
  } catch (err) {
    console.error(err);
  }
}

export function watchExpiry(info: SavedInfo | null): void {
  if (expiryTimer) clearTimeout(expiryTimer);
  expiryTimer = null;
  if (!info || info.expiresAt === null) return;
  expiryTimer = setTimeout(() => { void expire(); }, Math.min(Math.max(0, info.expiresAt - Date.now()), LONGEST_TIMER));
}

let inFlight: Promise<SavedInfo | null> | null = null;
let clears = 0;

export async function clearSaved(): Promise<void> {
  watchExpiry(null);
  clears++;
  await inFlight?.catch(() => null);
  try {
    await clearTrip();
  } catch {
    try { await clearTrip(); } catch { throw new Error("Couldn’t remove the saved trip from this device."); }
  }
}

export async function dropIfExpired(info: SavedInfo | null): Promise<boolean> {
  if (!info || info.expiresAt === null || Date.now() < info.expiresAt) return false;
  await clearSaved();
  return true;
}

async function replaceSaved(): Promise<SavedInfo | null> {
  if (!(await isSetUp()) || (await isSavingOff())) return null;
  const before = clears;
  const projection = await apiCall<"GET /api/offline">("/api/offline");
  if (clears !== before) return null;
  if (!projection.trip) { watchExpiry(null); await clearTrip(); return null; }
  const info: SavedInfo = { savedAt: Date.now(), expiresAt: expiryOf(projection) };
  const copy: SavedCopy = { ...projection, savedAt: info.savedAt };
  if (!(await save(copy, info))) return null;
  watchExpiry(info);
  return info;
}

export function saveCurrentTrip(): Promise<SavedInfo | null> {
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

export { savedInfo };
