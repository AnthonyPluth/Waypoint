import { ignoreFailure } from "./act";
import { apiCall } from "./contract";
import { loadFlightStatus } from "./flightstatus.svelte";

type TripsReply = Awaited<ReturnType<typeof apiCall<"GET /api/trips">>>;

const EARLY_PAGES = ["upcoming", "trips"];
let early: { page: string; trips: Promise<TripsReply> } | null = null;

export function startEarly(page: string): void {
  if (early || !EARLY_PAGES.includes(page)) return;
  const trips = apiCall<"GET /api/trips">("/api/trips");
  trips.catch(ignoreFailure);
  early = { page, trips };
  if (page === "upcoming") void loadFlightStatus();
}

export function dropEarly(): void {
  early = null;
}

export function takeEarlyTrips(page: string): Promise<TripsReply> | null {
  if (!early || early.page !== page) return null;
  const { trips } = early;
  early = null;
  return trips;
}
