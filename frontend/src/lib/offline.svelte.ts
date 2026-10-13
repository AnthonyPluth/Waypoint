import { onDenied } from "./api";
import { clearSaved, dropIfExpired, resumeSaving, saveCurrentTrip, savedInfo, stopSaving, watchExpiry, whenExpired } from "./offline";
import { isSavingOff, isSetUp, remove, setUp, support, VaultError } from "./offline-vault";

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
  tripId: null as number | null,
  tripName: "",
});

function forgetTrip(): void {
  offline.tripId = null;
  offline.tripName = "";
}

export async function refreshOffline(): Promise<void> {
  const found = await support();
  offline.supported = found.ok;
  offline.reason = found.ok ? "" : found.reason;
  try {
    offline.setUp = await isSetUp();
    offline.off = offline.setUp && (await isSavingOff());
    let info = offline.setUp ? await savedInfo() : null;
    if (await dropIfExpired(info)) info = null;
    watchExpiry(info);
    offline.hasCopy = info !== null;
    offline.savedAt = info ? info.savedAt : null;
    if (!info) forgetTrip();
    offline.damaged = false;
  } catch {
    offline.setUp = false;
    offline.off = false;
    offline.hasCopy = false;
    offline.savedAt = null;
    forgetTrip();
    offline.damaged = true;
  }
  offline.checked = true;
}

whenExpired(() => { offline.hasCopy = false; offline.savedAt = null; forgetTrip(); });

export function clearOnDenied(): void {
  onDenied(async () => { await clearSaved(); offline.hasCopy = false; offline.savedAt = null; forgetTrip(); });
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
    if (info) { offline.hasCopy = true; offline.savedAt = info.savedAt; offline.tripId = info.tripId; offline.tripName = info.tripName; offline.failed = false; }
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
  offline.hasCopy = false;
  offline.savedAt = null;
  offline.failed = false;
  forgetTrip();
}

export async function removeOffline(): Promise<void> {
  await remove();
  offline.failed = false;
  await refreshOffline();
}

export const askAboutOffline = (): boolean => offline.checked && offline.supported && !offline.setUp && !offline.damaged && !offline.declined;
