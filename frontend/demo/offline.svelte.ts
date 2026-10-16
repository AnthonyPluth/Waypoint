export const offline = $state({ checked: false, setUp: false, hasCopy: false, savedAt: null as number | null, off: true, damaged: false, supported: false, reason: "Unavailable in the static demo", declined: true, failed: false, trips: [] as { id: number | null; name: string }[] });
export async function refreshOffline(): Promise<void> {}
export async function syncSavedTrip(): Promise<void> {}
export async function saveTripCopy(_loaded?: unknown): Promise<void> {}
export async function removeOffline(): Promise<void> {}
export async function turnOnOffline(): Promise<null> { return null; }
export async function switchSaving(_on: boolean): Promise<void> {}
export function clearOnDenied(): void {}
export const askAboutOffline = (): boolean => false;
export const offlineWorking = (): boolean => false;
