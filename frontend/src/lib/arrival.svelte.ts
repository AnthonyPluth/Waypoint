import type { Segment } from "./api-types";
import { inShell, shellArrivalHere, shellPendingArrival, type ShellArrival } from "./offline-shell";
import { endAt } from "./trips";

export const ARRIVAL_EVENT = "waypointarrival";
export const TARGET_LIFETIME = 120_000;

export const arrival = $state({
  target: null as (ShellArrival & { at: number }) | null,
  here: null as ShellArrival | null,
  dismissed: null as number | null,
});

let checks = 0;

export function openable(s: Segment, now: number): boolean {
  if (s.status === "cancelled") return false;
  if (s.kind === "parking") return s.gate_code?.state === "ready" && endAt(s) > now;
  return (s.kind === "car" || s.kind === "hotel") && !!s.confirmation?.trim();
}

export function pendingFor(tripId: number, now = Date.now()): number | null {
  const target = arrival.target;
  if (!target || now - target.at > TARGET_LIFETIME) return null;
  return target.tripId === tripId ? target.segmentId : null;
}

export function settleTarget(): void {
  arrival.target = null;
}

function showTrip(tripId: number): void {
  const wanted = `#trip/${tripId}`;
  const now = location.hash;
  if (now === wanted || now.startsWith(`${wanted}?`) || now.startsWith(`${wanted}/`)) return;
  location.hash = wanted;
}

export async function takePendingArrival(): Promise<void> {
  if (!inShell()) return;
  let found: ShellArrival | null;
  try { found = await shellPendingArrival(); } catch { return; }
  if (!found) return;
  arrival.target = { ...found, at: Date.now() };
  showTrip(found.tripId);
}

export function listenForArrival(): () => void {
  if (!inShell()) return () => {};
  const asked = () => void takePendingArrival();
  window.addEventListener(ARRIVAL_EVENT, asked);
  asked();
  return () => window.removeEventListener(ARRIVAL_EVENT, asked);
}

export async function checkArrivalHere(): Promise<void> {
  if (!inShell()) return;
  const mine = ++checks;
  let found: ShellArrival | null;
  try { found = await shellArrivalHere(); } catch {
    if (mine === checks) arrival.here = null;
    return;
  }
  if (mine !== checks) return;
  arrival.here = found;
  if (found === null || (arrival.dismissed !== null && arrival.dismissed !== found.segmentId)) arrival.dismissed = null;
}

export function openBooking(segmentId: number, tripId: number): void {
  arrival.target = { segmentId, tripId, at: Date.now() };
  showTrip(tripId);
}

export function dismissArrival(segmentId: number): void {
  arrival.dismissed = segmentId;
}

export function resetArrival(): void {
  checks++;
  arrival.target = null;
  arrival.here = null;
  arrival.dismissed = null;
}
