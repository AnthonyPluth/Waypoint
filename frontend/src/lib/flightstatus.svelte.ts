import type { FlightStatus, FlightStatusList } from "./api-types";
import { errMsg } from "./act";
import { apiCall } from "./contract";

export const flightStatus = $state({ list: null as FlightStatusList | null, problem: "" });

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
