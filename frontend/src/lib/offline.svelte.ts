import { onDenied } from "./api";
import { clearSaved, dropExpired, resumeSaving, saveCurrentTrip, savedInfos, stopSaving, watchExpiry, whenExpired } from "./offline";
import { isSavingOff, isSetUp, remove, setUp, support, VaultError } from "./offline-vault";

export type KnownTrip = { id: number | null; name: string };

export const offline = $state({
  checked: false,
  setUp: false,
  hasCopy: false,
  savedAt: null as number | null,
  off: false,
  damaged: false,
  supported: true,
  reason: "",
  declined: false,
  failed: false,
  trips: [] as KnownTrip[],
});

export const offlineWorking = (): boolean =>
  offline.checked && offline.supported && !offline.damaged && offline.setUp && !offline.off && !offline.failed && offline.hasCopy && offline.savedAt !== null;

function forgetTrips(): void {
  offline.trips = [];
}

export async function refreshOffline(): Promise<void> {
  const found = await support();
  offline.supported = found.ok;
  offline.reason = found.ok ? "" : found.reason;
  try {
    offline.setUp = await isSetUp();
    offline.off = offline.setUp && (await isSavingOff());
    let infos = offline.setUp ? await savedInfos() : [];
    infos = await dropExpired(infos);
    watchExpiry(infos);
    offline.hasCopy = infos.length > 0;
    offline.savedAt = infos.length ? Math.max(...infos.map((i) => i.savedAt)) : null;
    if (infos.length === 0) forgetTrips();
    else offline.trips = infos.map((i) => ({ id: i.tripId ?? null, name: offline.trips.find((t) => t.id === (i.tripId ?? null))?.name ?? "" }));
    offline.damaged = false;
  } catch {
    offline.setUp = false;
    offline.off = false;
    offline.hasCopy = false;
    offline.savedAt = null;
    forgetTrips();
    offline.damaged = true;
  }
  offline.checked = true;
}

function forgetCopy(): void {
  offline.hasCopy = false;
  offline.savedAt = null;
  forgetTrips();
}

whenExpired(() => { void refreshOffline(); });

export function clearOnDenied(): void {
  onDenied(async () => { await clearSaved(); forgetCopy(); });
}

export async function turnOnOffline(): Promise<VaultError | null> {
  try {
    await setUp();
  } catch (err) {
    const failure = err instanceof VaultError ? err : new VaultError("failed", "The device check didn’t work.");
    if (failure.code === "unsupported") { offline.supported = false; offline.reason = failure.message; }
    return failure;
  }
  await refreshOffline();
  void syncSavedTrip();
  return null;
}

export async function syncSavedTrip(): Promise<void> {
  try {
    const info = await saveCurrentTrip();
    if (info) { offline.hasCopy = true; offline.savedAt = info.savedAt; offline.trips = info.trips; offline.failed = false; }
    else { offline.failed = false; await refreshOffline(); }
  } catch {
    offline.failed = true;
    console.error("Couldn’t save the offline copy");
  }
}

export const saveTripCopy = (_loaded?: unknown): Promise<void> => syncSavedTrip();

export async function switchSaving(on: boolean): Promise<void> {
  if (on) { await resumeSaving(); offline.off = false; await syncSavedTrip(); return; }
  await stopSaving();
  offline.off = true;
  offline.failed = false;
  forgetCopy();
}

export async function removeOffline(): Promise<void> {
  await remove();
  offline.failed = false;
  await refreshOffline();
}

export const askAboutOffline = (): boolean => offline.checked && offline.supported && !offline.setUp && !offline.damaged && !offline.declined;
