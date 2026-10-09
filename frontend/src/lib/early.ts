import { ignoreFailure } from "./act";
import { apiCall } from "./contract";
import { loadFlightStatus } from "./flightstatus.svelte";

type TripsReply = Awaited<ReturnType<typeof apiCall<"GET /api/trips">>>;

const EARLY_PAGES = ["upcoming", "trips"];
export const EARLY_FRESH_MS = 10_000;
let early: { page: string; trips: Promise<TripsReply>; at: number } | null = null;

export function startEarly(page: string): void {
  if (early || !EARLY_PAGES.includes(page)) return;
  const trips = apiCall<"GET /api/trips">("/api/trips");
  trips.catch(ignoreFailure);
  early = { page, trips, at: Date.now() };
  if (page === "upcoming") void loadFlightStatus();
}

export function dropEarly(): void {
  early = null;
}

export function takeEarlyTrips(page: string): Promise<TripsReply> | null {
  if (!early || early.page !== page) return null;
  const taken = early;
  early = null;
  return Date.now() - taken.at <= EARLY_FRESH_MS ? taken.trips : null;
}
