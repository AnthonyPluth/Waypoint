// Live flight status: what GET /api/flight-status says (the household's calls this month, why fetching is paused if it is,
// and the status of each of your flights that has one), shared by the segment cards and Settings. Times in a status are
// wall-clock times at the airports (2026-11-20T19:50, in `dep_zone`): they're shown as they are, never converted.
import type { FlightStatus, FlightStatusList } from "./api-types";
import { errMsg } from "./act";
import { apiCall } from "./contract";

export const flightStatus = $state({ list: null as FlightStatusList | null, problem: "" });

export async function loadFlightStatus(): Promise<void> {
  try { flightStatus.list = await apiCall<"GET /api/flight-status">("/api/flight-status"); flightStatus.problem = ""; }
  catch (err) { flightStatus.problem = errMsg(err); }
}

/** Fetch this segment's status now (the server holds a recent answer, and counts a call when it fetches); the reply
 *  carries this segment's status and the month's count, which replace what's held. Throws what the server said. */
export async function refreshFlightStatus(segmentId: number): Promise<void> {
  const got = await apiCall<"POST /api/flight-status/{id}">(`/api/flight-status/${segmentId}`, { method: "POST", failed: "Couldn’t refresh the status" });
  const others = (flightStatus.list?.statuses ?? []).filter((s) => s.segment_id !== segmentId);
  flightStatus.list = { ...got, statuses: [...others, ...got.statuses] };
}

export const statusFor = (segmentId: number): FlightStatus | undefined =>
  flightStatus.list?.statuses.find((s) => s.segment_id === segmentId);
