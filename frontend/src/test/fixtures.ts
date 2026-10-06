import type { LoyaltyEntry, Segment, Trip } from "$lib/api-types";
import type { AppState } from "$lib/types";

export const state = (extra: Partial<AppState> = {}): AppState => ({
  version: "1.2.3", database: "sqlite", user: { name: "Ada Lovelace", email: "ada@example.com" }, last_backup: null, review_count: 0, person_id: 1, ...extra,
});

export const segment = (extra: Partial<Segment> = {}): Segment => ({
  id: 1, trip_id: 1, kind: "flight", status: "confirmed", confirmation: "KQ7M2X", provider: "American Airlines",
  start_local: "2026-11-20T19:00", start_zone: "America/New_York", end_local: "2026-11-21T07:10", end_zone: "Europe/London",
  origin: "JFK", destination: "LHR", details: { flight_number: "AA 101", terminal: "8" }, manage_url: null, source: "email", booked_by: 1,
  locked_fields: [], check_times: false, travelers: [{ id: 1, person_id: 1, name: "Jane Doe", seat: null }], itinerary: [], logo: null, logo_label: null, has_email: false, links: { app: null, directions: null, call: null }, ...extra,
});

export const trip = (segments: Segment[], extra: Partial<Trip> = {}): Trip => ({
  id: 1, name: "Trip to London", start_date: segments[0]?.start_local.slice(0, 10) ?? null, end_date: segments.at(-1)?.end_local.slice(0, 10) ?? null,
  destination: "London", notes: null, auto: true, booked_by: 1, segments, ...extra,
});

export const membership = (extra: Partial<LoyaltyEntry> = {}): LoyaltyEntry => ({
  id: 11, person_id: 1, kind: "airline", program: "American AAdvantage", masked: "••••4567", readable: true, expiry: null, notes: null, ...extra,
});
