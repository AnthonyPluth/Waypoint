import type { FlightStatus, FlightStatusList, Segment } from "./api-types";
import { errMsg } from "./act";
import { apiCall } from "./contract";
import { endAt, instant, startAt, untimed } from "./trips";

export const flightStatus = $state({ list: null as FlightStatusList | null, problem: "" });

export const LIVE_EVERY = 60_000;
const AHEAD = 24 * 3_600_000;
const AFTER = 6 * 3_600_000;
const AGAIN_AFTER = 5_000;
const FINAL = new Set(["landed", "cancelled", "diverted"]);

export async function loadFlightStatus(): Promise<void> {
  try { flightStatus.list = await apiCall<"GET /api/flight-status">("/api/flight-status"); flightStatus.problem = ""; }
  catch (err) { flightStatus.problem = errMsg(err); }
}

export async function refreshFlightStatus(segmentId: number): Promise<void> {
  let got: FlightStatusList;
  try { got = await apiCall<"POST /api/flight-status/{id}">(`/api/flight-status/${segmentId}`, { method: "POST", failed: "Couldn’t refresh the status" }); }
  catch (err) { await loadFlightStatus(); throw err; }
  const others = (flightStatus.list?.statuses ?? []).filter((s) => s.segment_id !== segmentId);
  flightStatus.list = { ...got, statuses: [...others, ...got.statuses] };
}

export const statusFor = (segmentId: number): FlightStatus | undefined =>
  flightStatus.list?.statuses.find((s) => s.segment_id === segmentId);

export function liveFlight(s: Segment, now: number): boolean {
  if (s.kind !== "flight" || s.status === "cancelled" || untimed(s)) return false;
  const status = statusFor(s.id);
  if (status && FINAL.has(status.state)) return false;
  const lands = status?.arr_estimated ? instant(status.arr_estimated, status.arr_zone) : NaN;
  return now >= startAt(s) - AHEAD && now <= Math.max(endAt(s), Number.isNaN(lands) ? 0 : lands) + AFTER;
}

export function watchFlightStatus(segments: () => Segment[]): () => void {
  let last = 0;
  const reread = (force: boolean) => {
    const now = Date.now();
    if (document.visibilityState === "hidden" || flightStatus.list?.enabled === false) return;
    if (!force && now - last < AGAIN_AFTER) return;
    if (!segments().some((s) => liveFlight(s, now))) return;
    last = now;
    void loadFlightStatus();
  };
  const back = () => reread(false);
  const timer = setInterval(() => reread(true), LIVE_EVERY);
  window.addEventListener("focus", back);
  document.addEventListener("visibilitychange", back);
  return () => {
    clearInterval(timer);
    window.removeEventListener("focus", back);
    document.removeEventListener("visibilitychange", back);
  };
}
