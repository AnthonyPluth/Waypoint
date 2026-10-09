import { hasSavedTrip, isSetUp, remove, save, setUp, support, VaultError } from "./offline-vault";

export const offline = $state({
  checked: false,
  setUp: false,
  hasCopy: false,
  damaged: false,
  supported: true,
  reason: "",
  declined: false,
});

export async function refreshOffline(): Promise<void> {
  const found = await support();
  offline.supported = found.ok;
  offline.reason = found.ok ? "" : found.reason;
  try {
    offline.setUp = await isSetUp();
    offline.hasCopy = offline.setUp && (await hasSavedTrip());
    offline.damaged = false;
  } catch {
    offline.setUp = false;
    offline.hasCopy = false;
    offline.damaged = true;
  }
  offline.checked = true;
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
  return null;
}

export async function saveTripCopy(trip: unknown): Promise<void> {
  if (!offline.setUp) return;
  try {
    if (await save(trip)) offline.hasCopy = true;
  } catch {
    console.error("Couldn’t save the offline copy");
  }
}

export async function removeOffline(): Promise<void> {
  await remove();
  await refreshOffline();
}

export const askAboutOffline = (): boolean => offline.checked && offline.supported && !offline.setUp && !offline.damaged && !offline.declined;
