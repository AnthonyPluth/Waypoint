export const BRIDGE_HANDLER = "waypointOffline";
export const BRIDGE_VERSION = 1;
const UNAUTHORIZED_HANDLER = "waypointUnauthorized";

export type ShellRequest = { type: "status" } | { type: "load" } | { type: "setSaving"; on: boolean } | { type: "remove" };
export type ShellTrip = { id: number; name: string };
export type ShellStatus = { version: typeof BRIDGE_VERSION; saving: boolean; syncing: boolean; lastSaveFailed: boolean; savedAt: number | null; trips: ShellTrip[] };
export type ShellLoad = { version: typeof BRIDGE_VERSION; trips: unknown[] };

type Bridge = { postMessage: (message: ShellRequest) => Promise<unknown> };

export function shellBridge(scope: unknown = globalThis): Bridge | null {
  const handlers = (scope as { webkit?: { messageHandlers?: Record<string, unknown> } }).webkit?.messageHandlers;
  const found = handlers?.[BRIDGE_HANDLER] as Partial<Bridge> | undefined;
  return typeof found?.postMessage === "function" ? (found as Bridge) : null;
}

export const inShell = (): boolean => shellBridge() !== null;

export function inOldShell(scope: unknown = globalThis): boolean {
  if (shellBridge(scope) !== null) return false;
  const found = scope as { webkit?: { messageHandlers?: Record<string, unknown> }; Capacitor?: { isNativePlatform?: () => boolean } };
  return found.webkit?.messageHandlers?.[UNAUTHORIZED_HANDLER] !== undefined || found.Capacitor?.isNativePlatform?.() === true;
}

async function ask(message: ShellRequest): Promise<unknown> {
  const bridge = shellBridge();
  if (!bridge) throw new Error("Not running in the Waypoint app.");
  return bridge.postMessage(message);
}

function readStatus(reply: unknown): ShellStatus {
  const r = reply as Partial<ShellStatus> | null;
  const trips = r?.trips;
  if (!r || typeof r !== "object" || r.version !== BRIDGE_VERSION || typeof r.saving !== "boolean"
    || !(r.syncing === undefined || typeof r.syncing === "boolean") || !(r.lastSaveFailed === undefined || typeof r.lastSaveFailed === "boolean")
    || !(r.savedAt === null || typeof r.savedAt === "number")
    || !Array.isArray(trips) || !trips.every((t) => !!t && typeof t.id === "number" && typeof t.name === "string")) {
    throw new Error("The app sent an unreadable offline status.");
  }
  return { version: BRIDGE_VERSION, saving: r.saving, syncing: r.syncing === true, lastSaveFailed: r.lastSaveFailed === true, savedAt: r.savedAt, trips: trips.map((t) => ({ id: t.id, name: t.name })) };
}

export const shellStatus = async (): Promise<ShellStatus> => readStatus(await ask({ type: "status" }));
export const shellSetSaving = async (on: boolean): Promise<ShellStatus> => readStatus(await ask({ type: "setSaving", on }));
export const shellRemove = async (): Promise<ShellStatus> => readStatus(await ask({ type: "remove" }));

export async function shellLoad(): Promise<unknown[]> {
  const reply = (await ask({ type: "load" })) as Partial<ShellLoad> | null;
  if (!reply || reply.version !== BRIDGE_VERSION || !Array.isArray(reply.trips)) {
    throw new Error("The app sent unreadable saved trips.");
  }
  return reply.trips;
}
