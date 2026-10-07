import type { Segment, SegmentBody, SegmentEdit } from "./api-types";
import { instant, untimed } from "./trips";

export type Kind = Segment["kind"];
export const KINDS: [Kind, string][] = [["flight", "Flight"], ["hotel", "Hotel"], ["car", "Car rental"], ["train", "Train"], ["cruise", "Cruise"]];

export const MAX_PORTS = 40;

export const ADDRESS_LIMIT = 300;

export const DETAILS: Record<Kind, [string, string][]> = {
  flight: [["flight_number", "Flight number"], ["terminal", "Terminal"], ["gate", "Gate"], ["cabin", "Cabin"]],
  hotel: [["address", "Address"], ["room", "Room"], ["phone", "Phone"]],
  car: [["address", "Pick-up address"], ["car_class", "Car class"], ["phone", "Phone"]],
  train: [["cabin", "Class"]],
  cruise: [["ship", "Ship"], ["room", "Cabin"], ["deck", "Deck"], ["address", "Terminal address"], ["phone", "Phone"]],
};

export const SEAT_LIMIT = 10;

export const SEATED: Kind[] = ["flight", "train"];

export const seatKey = (who: number | string): string => (typeof who === "number" ? `p${who}` : `n${who}`);

export type PortDraft = { name: string; zone: string; arrive: string; depart: string };

export type Draft = {
  id: number | null;
  tripId: number | null;
  kind: Kind;
  status: Segment["status"];
  provider: string;
  confirmation: string;
  origin: string;
  destination: string;
  start_local: string;
  end_local: string;
  start_zone: string;
  end_zone: string;
  details: Record<string, string>;
  itinerary: PortDraft[];
  manage_url: string;
  seats: Record<string, string>;
  people: number[];
  printed: string[];
  untimed?: [string, string];
};

export const blank = (tripId: number | null = null): Draft => ({
  id: null, tripId, kind: "flight", status: "confirmed", provider: "", confirmation: "", origin: "", destination: "", start_local: "", end_local: "",
  start_zone: "", end_zone: "", details: {}, itinerary: [], manage_url: "", seats: {}, people: [], printed: [],
});

export const draftOf = (s: Segment): Draft => ({
  id: s.id, tripId: s.trip_id, kind: s.kind, status: s.status, provider: s.provider ?? "", confirmation: s.confirmation ?? "", origin: s.origin ?? "",
  destination: s.destination ?? "", start_local: s.start_local, end_local: s.end_local,
  start_zone: s.kind === "flight" ? "" : s.start_zone, end_zone: s.kind === "flight" ? "" : s.end_zone,
  details: { ...s.details }, itinerary: s.itinerary.map((p) => ({ name: p.name, zone: p.zone, arrive: p.arrive_local ?? "", depart: p.depart_local ?? "" })), manage_url: s.manage_url ?? "",
  seats: Object.fromEntries(s.travelers.flatMap((t) => {
    const seat = t.seat ?? (s.travelers.length === 1 ? s.details.seat : undefined);
    return seat ? [[seatKey(t.person_id ?? t.name), seat]] : [];
  })),
  people: s.travelers.flatMap((t) => (t.person_id === null ? [] : [t.person_id])),
  printed: s.travelers.flatMap((t) => (t.person_id === null ? [t.name] : [])),
  ...(untimed(s) && { untimed: [s.start_local, s.end_local] as [string, string] }),
});

const AIRPORT = /^[A-Za-z]{3}$/;
const LOCAL = /^\d{4}-\d\d-\d\dT\d\d:\d\d/;

function knownZone(zone: string): boolean {
  try { new Intl.DateTimeFormat("en-US", { timeZone: zone }); return true; } catch { return false; }
}

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
  const stay = d.kind === "hotel";
  if (stay && !d.start_zone.trim() && !(d.details.address ?? "").trim()) return "Enter the time zone of the stay (for example America/New_York), or its address to work it out from";
  if (!flight && !stay && !d.start_zone.trim()) return "Enter the time zone of the place (for example America/New_York)";
  for (const zone of [d.start_zone.trim(), stay ? "" : d.end_zone.trim()]) {
    if (zone && !knownZone(zone)) return `The time zone “${zone.slice(0, 40)}” isn’t one Waypoint knows (use a name like America/New_York)`;
  }
  const startZone = d.start_zone.trim(), endZone = stay ? startZone : d.end_zone.trim() || startZone;
  if (startZone && endZone && instant(d.end_local, endZone) < instant(d.start_local, startZone)) {
    return "This ends before it starts (times are compared at their own places’ zones)";
  }
  if ((d.details.address ?? "").trim().length > ADDRESS_LIMIT) return `The address can be at most ${ADDRESS_LIMIT} characters`;
  if (d.kind === "cruise") {
    if (d.itinerary.length > MAX_PORTS) return `Add at most ${MAX_PORTS} ports of call`;
    for (const [i, p] of d.itinerary.entries()) {
      if (!p.name.trim()) return `Name port ${i + 1}`;
      if (!p.zone.trim()) return `Enter the time zone of ${p.name.trim().slice(0, 40)} (for example America/Nassau)`;
      if (!knownZone(p.zone.trim())) return `The time zone “${p.zone.trim().slice(0, 40)}” of ${p.name.trim().slice(0, 40)} isn’t one Waypoint knows (use a name like America/Nassau)`;
      for (const [word, at] of [["arrival", p.arrive], ["departure", p.depart]]) if (at && !LOCAL.test(at)) return `Enter ${p.name.trim().slice(0, 40)}’s ${word} as a date and time`;
      if (p.arrive && p.depart && instant(p.depart, p.zone.trim()) < instant(p.arrive, p.zone.trim())) return `${p.name.trim().slice(0, 40)}: the ship can’t leave before it arrives`;
    }
  }
  for (const seat of Object.values(d.seats)) if (seat.trim().length > SEAT_LIMIT) return `A seat is at most ${SEAT_LIMIT} characters`;
  if (d.manage_url.trim() && !/^https?:\/\//i.test(d.manage_url.trim())) return "The manage link must start with https:// or http://";
  if (d.people.length + d.printed.length === 0) return "Choose who’s travelling";
  return null;
}

const text = (v: string): string | null => v.trim() || null;

export function body(d: Draft): SegmentBody & SegmentEdit {
  const flight = d.kind === "flight";
  const shown = new Set(DETAILS[d.kind].map(([key]) => key));
  const details: Record<string, string> = Object.fromEntries(Object.entries(d.details).filter(([key]) => !shown.has(key)));
  for (const [key] of DETAILS[d.kind]) if (d.details[key]?.trim()) details[key] = d.details[key].trim();
  if (d.untimed && d.untimed[0] === d.start_local && d.untimed[1] === d.end_local) details.time_unknown = "yes";
  else delete details.time_unknown;
  const startZone = d.start_zone.trim(), endZone = d.end_zone.trim() || startZone;
  const seated = SEATED.includes(d.kind);
  if (seated && d.people.length + d.printed.length === 1) delete details.seat;
  const seat = (who: number | string) => (seated ? { seat: d.seats[seatKey(who)]?.trim() || null } : {});
  return {
    kind: d.kind, status: d.status, provider: text(d.provider), confirmation: text(d.confirmation),
    origin: flight ? d.origin.trim().toUpperCase() : text(d.origin), destination: flight ? d.destination.trim().toUpperCase() : text(d.destination),
    start_local: d.start_local, end_local: d.end_local,
    ...(flight ? { ...(startZone && { start_zone: startZone }), ...(d.end_zone.trim() && { end_zone: d.end_zone.trim() }) }
      : d.kind === "hotel" ? { start_zone: startZone || null }
        : { start_zone: startZone, end_zone: endZone }),
    details, manage_url: text(d.manage_url),
    ...(flight || d.kind !== "cruise" ? {} : { itinerary: d.itinerary.map((p) => ({ name: p.name.trim(), zone: p.zone.trim(), arrive_local: p.arrive || null, depart_local: p.depart || null })) }),
    travelers: [...d.people.map((id) => ({ person_id: id, ...seat(id) })), ...d.printed.map((name) => ({ person_id: null, name, ...seat(name) }))],
  };
}
