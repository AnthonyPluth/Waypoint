// The form for adding or editing a segment by hand: what it holds, what it checks before anything is sent (in the words
// the person reads), and the request it makes. The server checks again; this is so a slip is caught before a round trip.
import type { Segment, SegmentBody, SegmentEdit } from "./api-types";
import { instant } from "./trips";

export type Kind = Segment["kind"];
export const KINDS: [Kind, string][] = [["flight", "Flight"], ["hotel", "Hotel"], ["car", "Car rental"], ["train", "Train"]];

/** The details each kind has room for, as the segment stores them. */
export const DETAILS: Record<Kind, [string, string][]> = {
  flight: [["flight_number", "Flight number"], ["terminal", "Terminal"], ["seat", "Seat"], ["cabin", "Cabin"]],
  hotel: [["address", "Address"], ["room", "Room"], ["phone", "Phone"]],
  car: [["address", "Pick-up address"], ["car_class", "Car class"], ["phone", "Phone"]],
  train: [["seat", "Seat"], ["cabin", "Class"]],
};

export type Draft = {
  id: number | null;            // null: a new segment
  tripId: number | null;        // the trip it goes in (null: Waypoint groups it)
  kind: Kind;
  status: Segment["status"];
  provider: string;
  confirmation: string;
  origin: string;               // a flight's airport code; a stay's or rental's place
  destination: string;
  start_local: string;          // YYYY-MM-DDTHH:MM, as a date-and-time field gives it
  end_local: string;
  start_zone: string;
  end_zone: string;
  details: Record<string, string>;
  manage_url: string;
  people: number[];             // travellers who are in People
  printed: string[];            // travellers known only by the name on the booking, kept as they are
};

export const blank = (tripId: number | null = null): Draft => ({
  id: null, tripId, kind: "flight", status: "confirmed", provider: "", confirmation: "", origin: "", destination: "", start_local: "", end_local: "",
  start_zone: "", end_zone: "", details: {}, manage_url: "", people: [], printed: [],
});

/** A draft of what's there, to edit. A flight's zones come from its airports, so they start empty (only what's typed is sent). */
export const draftOf = (s: Segment): Draft => ({
  id: s.id, tripId: s.trip_id, kind: s.kind, status: s.status, provider: s.provider ?? "", confirmation: s.confirmation ?? "", origin: s.origin ?? "",
  destination: s.destination ?? "", start_local: s.start_local, end_local: s.end_local,
  start_zone: s.kind === "flight" ? "" : s.start_zone, end_zone: s.kind === "flight" ? "" : s.end_zone,
  details: { ...s.details }, manage_url: s.manage_url ?? "",
  people: s.travelers.flatMap((t) => (t.person_id === null ? [] : [t.person_id])),
  printed: s.travelers.flatMap((t) => (t.person_id === null ? [t.name] : [])),
});

const AIRPORT = /^[A-Za-z]{3}$/;
const LOCAL = /^\d{4}-\d\d-\d\dT\d\d:\d\d/;

function knownZone(zone: string): boolean {
  try { new Intl.DateTimeFormat("en-US", { timeZone: zone }); return true; } catch { return false; }   // an unknown zone throws
}

/** What's wrong with the form, as one sentence for the person, or null when it can be sent. */
export function problem(d: Draft): string | null {
  const flight = d.kind === "flight";
  if (flight) {
    if (!AIRPORT.test(d.origin.trim())) return "A flight’s origin is an airport code like JFK";
    if (!AIRPORT.test(d.destination.trim())) return "A flight’s destination is an airport code like LHR";
  } else if (d.kind === "hotel" && !d.origin.trim()) {
    return "Enter the hotel’s name";
  }
  if (!LOCAL.test(d.start_local)) return d.kind === "hotel" ? "Enter the check-in date and time" : "Enter when it starts";
  if (!LOCAL.test(d.end_local)) return d.kind === "hotel" ? "Enter the check-out date and time" : "Enter when it ends";
  // A flight's zones come from its airports unless given; anything else needs one (the end's is the start's if left empty).
  if (!flight && !d.start_zone.trim()) return "Enter the time zone of the place (for example America/New_York)";
  for (const zone of [d.start_zone.trim(), d.end_zone.trim()]) {
    if (zone && !knownZone(zone)) return `The time zone “${zone.slice(0, 40)}” isn’t one Waypoint knows (use a name like America/New_York)`;
  }
  const startZone = d.start_zone.trim(), endZone = d.end_zone.trim() || startZone;
  // Compared only when both zones are known: a flight's arrival can be earlier on the clock than its departure.
  if (startZone && endZone && instant(d.end_local, endZone) < instant(d.start_local, startZone)) {
    return "This ends before it starts (times are compared at their own places’ zones)";
  }
  if (d.manage_url.trim() && !/^https?:\/\//i.test(d.manage_url.trim())) return "The manage link must start with https:// or http://";
  if (d.people.length + d.printed.length === 0) return "Choose who’s travelling";
  return null;
}

const text = (v: string): string | null => v.trim() || null;

/** The request the form makes: a flight's zones only if typed. */
export function body(d: Draft): SegmentBody & SegmentEdit {
  const flight = d.kind === "flight";
  const shown = new Set(DETAILS[d.kind].map(([key]) => key));
  const details: Record<string, string> = Object.fromEntries(Object.entries(d.details).filter(([key]) => !shown.has(key)));   // an email's other details stay as they are
  for (const [key] of DETAILS[d.kind]) if (d.details[key]?.trim()) details[key] = d.details[key].trim();
  const startZone = d.start_zone.trim(), endZone = d.end_zone.trim() || startZone;
  return {
    kind: d.kind, status: d.status, provider: text(d.provider), confirmation: text(d.confirmation),
    origin: flight ? d.origin.trim().toUpperCase() : text(d.origin), destination: flight ? d.destination.trim().toUpperCase() : text(d.destination),
    start_local: d.start_local, end_local: d.end_local,
    ...(flight ? { ...(startZone && { start_zone: startZone }), ...(d.end_zone.trim() && { end_zone: d.end_zone.trim() }) } : { start_zone: startZone, end_zone: endZone }),
    details, manage_url: text(d.manage_url),
    travelers: [...d.people.map((id) => ({ person_id: id })), ...d.printed.map((name) => ({ person_id: null, name }))],
  };
}
