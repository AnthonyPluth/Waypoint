import type { Segment, Trip, TripPlaces } from "./api-types";
import { daysBetween, dayParts, placeOf, splitTrips } from "./trips";

const AIRPORT_CODE = /^[A-Za-z]{3}$/;

const head = (text: string): string => text.split(",")[0].trim();
const live = (trip: Trip): Segment[] => trip.segments.filter((s) => s.status !== "cancelled");

function placesOf(s: Segment): (string | null)[] {
  if (s.kind === "flight" || s.kind === "train") return [s.origin, s.destination];
  if (s.kind === "hotel") return [s.destination ?? placeOf(s.details.address)];
  if (s.kind === "cruise") return [s.origin, s.destination, ...s.itinerary.map((p) => p.name)];
  if (s.kind === "visit") return [s.destination];
  if (s.kind === "car") return [s.origin, s.destination];
  return [];
}

export function tripCities(trip: Trip, places: TripPlaces | null = null): number {
  const airports = new Map((places?.airports ?? []).map((a) => [a.code.toUpperCase(), a.city]));
  const found = new Set<string>();
  for (const s of live(trip)) {
    for (const raw of placesOf(s)) {
      const text = head(raw ?? "");
      if (!text) continue;
      const city = AIRPORT_CODE.test(text) ? airports.get(text.toUpperCase()) ?? text.toUpperCase() : text;
      found.add(city.toLowerCase());
    }
  }
  return found.size;
}

export type Totals = { nights: number; bookings: number; cities: number };

export const tripTotals = (trip: Trip, places: TripPlaces | null = null): Totals => ({
  nights: Math.max(0, daysBetween(trip.start_date && `${trip.start_date}T00:00`, trip.end_date && `${trip.end_date}T00:00`)),
  bookings: live(trip).length,
  cities: tripCities(trip, places),
});

export function laterTrips(trips: Trip[], featured: Trip, today: string): Trip[] {
  const upcoming = splitTrips(trips, today).upcoming.filter((t) => t.start_date && t.start_date >= today);
  const after = upcoming.findIndex((t) => t.id === featured.id);
  return upcoming.filter((t, i) => t.id !== featured.id && (after < 0 || i > after));
}

export function startsIn(trip: Trip, today: string): string {
  const days = daysBetween(`${today}T00:00`, trip.start_date && `${trip.start_date}T00:00`);
  if (days <= 0) return "Starting today";
  return days === 1 ? "Tomorrow" : `In ${days} days`;
}

export function laterLine(trip: Trip, today: string): string {
  const nights = tripTotals(trip).nights;
  const tail = trip.destination || (nights > 0 ? `${nights} ${nights === 1 ? "night" : "nights"}` : "");
  return tail ? `${startsIn(trip, today)} · ${tail}` : startsIn(trip, today);
}

export const dateTile = (trip: Trip): { month: string; day: string } => {
  const parts = dayParts(trip.start_date ?? "");
  return { month: parts.month, day: parts.day };
};

export const usablePlaces = (found: unknown): found is TripPlaces => {
  const p = found as Partial<TripPlaces> | null | undefined;
  return !!p && Array.isArray(p.airports) && Array.isArray(p.cities) && Array.isArray(p.stays)
    && Array.isArray(p.roads?.legs) && Array.isArray(p.roads?.interstates) && Array.isArray(p.boundaries);
};
