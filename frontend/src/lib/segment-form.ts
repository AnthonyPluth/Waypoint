import type { Person, Segment, SegmentBody, SegmentEdit } from "./api-types";
import { isUsState } from "./countries";
import { amountText, toMinor } from "./money";
import { instant, untimed } from "./trips";

export type Kind = Segment["kind"];
export const KINDS: [Kind, string][] = [["flight", "Flight"], ["hotel", "Hotel"], ["car", "Car rental"], ["train", "Train"], ["cruise", "Cruise"], ["parking", "Parking"], ["visit", "Past trip (country and dates only)"]];

export const MAX_PORTS = 40;

export const ADDRESS_LIMIT = 300;

export const DETAILS: Record<Kind, [string, string][]> = {
  flight: [["flight_number", "Flight number"], ["terminal", "Terminal"], ["cabin", "Cabin"]],
  hotel: [["address", "Address"], ["room", "Room"], ["phone", "Phone"]],
  car: [["car_class", "Car class"], ["phone", "Phone"]],
  train: [["cabin", "Class"], ["address", "Station address"]],
  cruise: [["ship", "Ship"], ["room", "Cabin"], ["deck", "Deck"], ["address", "Terminal address"], ["phone", "Phone"]],
  parking: [["address", "Address"], ["space_type", "Space type (covered, economy, valet)"], ["vehicle", "Vehicle (make and colour)"], ["notes", "Notes"]],
  visit: [],
};

export const SEAT_LIMIT = 10;

export const DEFAULT_CURRENCY = "USD";

export const SEATED: Kind[] = ["flight", "train"];
export const FOR_EVERYONE: Kind[] = ["hotel", "car", "parking"];

export const seatKey = (who: number | string): string => (typeof who === "number" ? `p${who}` : `n${who}`);

export const MAX_VISITS = 20;

export type VisitRow = { destination: string; start_local: string; end_local: string; state?: string };

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
  cost: string;
  currency: string;
  costSource: "email" | "manual" | null;
  untimed?: [string, string];
  pickup?: string;
  addressField?: boolean;
  more?: VisitRow[];
};

export const visitRows = (d: Draft): VisitRow[] => [{ destination: d.destination, start_local: d.start_local, end_local: d.end_local, state: d.details.state ?? "" }, ...(d.more ?? [])];

export const nextVisitRow = (previous: VisitRow): VisitRow => ({ destination: "", start_local: previous.end_local, end_local: previous.end_local });

export const blank = (tripId: number | null = null, currency = DEFAULT_CURRENCY): Draft => ({
  id: null, tripId, kind: "flight", status: "confirmed", provider: "", confirmation: "", origin: "", destination: "", start_local: "", end_local: "",
  start_zone: "", end_zone: "", details: {}, itinerary: [], manage_url: "", seats: {}, people: [], printed: [], cost: "", currency, costSource: null,
});

export const blankFor = (people: Person[], me: number | null | undefined, tripId: number | null = null, currency = DEFAULT_CURRENCY): Draft => ({
  ...blank(tripId, currency), people: people.some((p) => p.id === me) ? [me as number] : [],
});

export const draftOf = (s: Segment, currency = DEFAULT_CURRENCY): Draft => ({
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
  cost: s.price ? amountText(s.price.amount_minor, s.price.currency) : "", currency: s.price?.currency ?? currency, costSource: s.price?.source ?? null,
  ...(untimed(s) && { untimed: [s.start_local, s.end_local] as [string, string] }),
  ...(s.kind === "car" && { pickup: s.origin ?? "", addressField: differs(s.details.address, s.origin) }),
});

const AIRPORT = /^[A-Za-z]{3}$/;
const LOCAL = /^\d{4}-\d\d-\d\dT\d\d:\d\d/;

export type Issue = { field: string; message: string };

export function visitIssues(row: VisitRow): Issue[] {
  const found: Issue[] = [];
  if (!/^[A-Za-z]{2}$/.test(row.destination.trim())) found.push({ field: "country", message: "Choose the country" });
  else if (row.destination.trim().toUpperCase() === "US" && (row.state ?? "").trim() && !isUsState(row.state?.trim().toUpperCase() ?? "")) found.push({ field: "state", message: "Choose one of the states, or leave the state blank" });
  if (!LOCAL.test(row.start_local)) found.push({ field: "first", message: "Enter the first day you were there" });
  if (!LOCAL.test(row.end_local)) found.push({ field: "last", message: "Enter the last day you were there" });
  else if (LOCAL.test(row.start_local) && row.end_local < row.start_local) found.push({ field: "last", message: "The last day can’t be before the first" });
  return found;
}

export const visitProblem = (row: VisitRow): string | null => visitIssues(row)[0]?.message ?? null;

export const MAX_FLIGHT_HOURS = 30;

export function longFlightWarning(start: string, end: string, startZone: string | null, endZone: string | null): string | null {
  if (!startZone || !endZone || !LOCAL.test(start) || !LOCAL.test(end)) return null;
  const hours = (instant(end, endZone) - instant(start, startZone)) / 3_600_000;
  if (!(hours > MAX_FLIGHT_HOURS)) return null;
  const length = hours >= 48 ? `${Math.floor(hours / 24)} days` : `${Math.floor(hours)} hours`;
  return `This flight is ${length} long. Check the times.`;
}

function knownZone(zone: string): boolean {
  try { new Intl.DateTimeFormat("en-US", { timeZone: zone }); return true; } catch { return false; }
}

const place = (kind: Kind, hotel: string, parking: string, other: string) => (kind === "hotel" ? hotel : kind === "parking" ? parking : other);

export function issues(d: Draft): Issue[] {
  const found: Issue[] = [];
  const add = (field: string, message: string) => found.push({ field, message });
  if (d.kind === "visit") {
    const rows = visitRows(d);
    if (rows.length > MAX_VISITS) add("visits", `Add at most ${MAX_VISITS} countries`);
    for (const [i, row] of rows.entries()) {
      for (const one of visitIssues(row)) add(`${one.field}-${i}`, rows.length > 1 ? `Country ${i + 1}: ${one.message}` : one.message);
    }
    if (d.people.length + d.printed.length === 0) add("travelers", "Choose who’s travelling");
    return found;
  }
  const flight = d.kind === "flight";
  if (flight) {
    if (!AIRPORT.test(d.origin.trim())) add("origin", "Choose the airport it leaves from: search by city or name, or enter its three-letter code like JFK");
    if (!AIRPORT.test(d.destination.trim())) add("destination", "Choose the airport it arrives at: search by city or name, or enter its three-letter code like LHR");
  } else if (d.kind === "hotel" && !d.origin.trim()) {
    add("origin", "Enter the hotel’s name");
  } else if (d.kind === "parking" && !d.origin.trim()) {
    add("origin", "Enter the lot’s name");
  }
  const stay = d.kind === "hotel" || d.kind === "parking";
  const startOk = LOCAL.test(d.start_local), endOk = LOCAL.test(d.end_local);
  if (!startOk) add("start", place(d.kind, "Enter the check-in date and time", "Enter the entry date and time", "Enter when it starts"));
  if (!endOk) add("end", place(d.kind, "Enter the check-out date and time", "Enter the exit date and time", "Enter when it ends"));
  let zonesKnown = true;
  if (stay && !d.start_zone.trim() && !(d.details.address ?? "").trim()) add("start_zone", "Enter the time zone of the stay (for example America/New_York), or its address to work it out from");
  if (d.kind === "cruise" && !d.start_zone.trim()) add("start_zone", "Enter the time zone of the place (for example America/New_York)");
  for (const [field, zone] of [["start_zone", d.start_zone.trim()], ["end_zone", stay ? "" : d.end_zone.trim()]]) {
    if (zone && !knownZone(zone)) {
      zonesKnown = false;
      add(field, `The time zone “${zone.slice(0, 40)}” isn’t one Waypoint knows (use a name like America/New_York)`);
    }
  }
  const startZone = d.start_zone.trim(), endZone = stay ? startZone : d.end_zone.trim() || startZone;
  if (startOk && endOk && zonesKnown && startZone && endZone && instant(d.end_local, endZone) < instant(d.start_local, startZone)) {
    add("end", "This ends before it starts (times are compared at their own places’ zones)");
  }
  if ((d.details.address ?? "").trim().length > ADDRESS_LIMIT) add("address", `The address can be at most ${ADDRESS_LIMIT} characters`);
  if (d.kind === "cruise") {
    if (d.itinerary.length > MAX_PORTS) add("ports", `Add at most ${MAX_PORTS} ports of call`);
    for (const [i, p] of d.itinerary.entries()) {
      const name = p.name.trim().slice(0, 40);
      if (!p.name.trim()) add(`port-${i}-name`, `Name port ${i + 1}`);
      if (!p.zone.trim()) add(`port-${i}-zone`, `Enter the time zone of ${name} (for example America/Nassau)`);
      else if (!knownZone(p.zone.trim())) add(`port-${i}-zone`, `The time zone “${p.zone.trim().slice(0, 40)}” of ${name} isn’t one Waypoint knows (use a name like America/Nassau)`);
      for (const [word, at, key] of [["arrival", p.arrive, "arrive"], ["departure", p.depart, "depart"]]) if (at && !LOCAL.test(at)) add(`port-${i}-${key}`, `Enter ${name}’s ${word} as a date and time`);
      if (p.arrive && p.depart && LOCAL.test(p.arrive) && LOCAL.test(p.depart) && p.zone.trim() && knownZone(p.zone.trim()) && instant(p.depart, p.zone.trim()) < instant(p.arrive, p.zone.trim())) add(`port-${i}-depart`, `${name}: the ship can’t leave before it arrives`);
    }
  }
  for (const [key, seat] of Object.entries(d.seats)) if (seat.trim().length > SEAT_LIMIT) add(`seat-${key}`, `A seat is at most ${SEAT_LIMIT} characters`);
  if (d.manage_url.trim() && !/^https?:\/\//i.test(d.manage_url.trim())) add("manage_url", "The manage link must start with https:// or http://");
  if (d.cost.trim()) {
    if (!/^[A-Za-z]{3}$/.test(d.currency.trim())) add("currency", "Enter the cost’s currency as a three-letter code like USD");
    else if (toMinor(d.cost, d.currency.trim().toUpperCase()) === null) add("cost", "Enter the cost as an amount like 1240.00");
  }
  if (!FOR_EVERYONE.includes(d.kind) && d.people.length + d.printed.length === 0) add("travelers", "Choose who’s travelling");
  return found;
}

export const problem = (d: Draft): string | null => issues(d)[0]?.message ?? null;

export const STAYS: Kind[] = ["hotel", "parking"];

export const inMore = (field: string, kind: Kind): boolean => ["manage_url", "cost", "currency"].includes(field) || (field === "address" && !STAYS.includes(kind));

export const hasMore = (d: Draft): boolean =>
  d.status !== "confirmed" || (d.kind === "flight" && (!!d.provider.trim() || !!d.confirmation.trim())) || !!d.manage_url.trim() || !!d.cost.trim() || d.costSource !== null || DETAILS[d.kind].some(([key]) => !(key === "address" && STAYS.includes(d.kind)) && (d.details[key] ?? "").trim()) || (d.kind === "car" && !!d.addressField);

export const differs = (address: string | undefined, origin: string | null | undefined): boolean =>
  !!address?.trim() && address.trim().split(/\s+/).join(" ").toLowerCase() !== (origin ?? "").trim().split(/\s+/).join(" ").toLowerCase();

export const SAME_AS_PICKUP = "Same as pick-up";

export function carAddress(address: string | undefined, origin: string, previous: string | undefined): string | null {
  const kept = (address ?? "").trim();
  const place = origin.trim();
  if (kept && (previous === undefined || kept !== previous.trim())) return kept;
  return place || null;
}

const text = (v: string): string | null => v.trim() || null;

export function priceOf(d: Pick<Draft, "cost" | "currency">): { amount_minor: number; currency: string } | null {
  const currency = d.currency.trim().toUpperCase();
  const amount = d.cost.trim() ? toMinor(d.cost, currency) : null;
  return amount === null ? null : { amount_minor: amount, currency };
}

export const visitBodies = (d: Draft): (SegmentBody & SegmentEdit)[] =>
  visitRows(d).map(({ state, ...row }) => {
    const details = Object.fromEntries(Object.entries(d.details).filter(([key]) => key !== "state"));
    return body({ ...d, ...row, details: state?.trim() ? { ...details, state: state.trim() } : details, more: [] });
  });

export function body(d: Draft): SegmentBody & SegmentEdit {
  const flight = d.kind === "flight";
  const shown = new Set(DETAILS[d.kind].map(([key]) => key));
  const details: Record<string, string> = Object.fromEntries(Object.entries(d.details).filter(([key]) => !shown.has(key)));
  for (const [key] of DETAILS[d.kind]) if (d.details[key]?.trim()) details[key] = d.details[key].trim();
  if (d.kind === "car") {
    const address = carAddress(d.details.address, d.origin, d.pickup);
    if (address) details.address = address;
    else delete details.address;
  }
  if (d.untimed && d.untimed[0] === d.start_local && d.untimed[1] === d.end_local) details.time_unknown = "yes";
  else delete details.time_unknown;
  if (d.kind === "visit" && d.destination.trim().toUpperCase() !== "US") delete details.state;
  const startZone = d.start_zone.trim(), endZone = d.end_zone.trim() || startZone;
  const seated = SEATED.includes(d.kind);
  if (seated && d.people.length + d.printed.length === 1) delete details.seat;
  const seat = (who: number | string) => (seated ? { seat: d.seats[seatKey(who)]?.trim() || null } : {});
  return {
    kind: d.kind, status: d.status, provider: text(d.provider), confirmation: text(d.confirmation),
    origin: d.kind === "visit" ? null : flight ? d.origin.trim().toUpperCase() : text(d.origin), destination: flight || d.kind === "visit" ? d.destination.trim().toUpperCase() : text(d.destination) ?? (d.kind === "car" ? text(d.origin) : null),
    start_local: d.start_local, end_local: d.end_local,
    ...(flight || d.kind === "car" || d.kind === "train" ? { ...(startZone && { start_zone: startZone }), ...(d.end_zone.trim() && { end_zone: d.end_zone.trim() }) }
      : d.kind === "visit" ? {}
        : d.kind === "hotel" || d.kind === "parking" ? { start_zone: startZone || null }
        : { start_zone: startZone, end_zone: endZone }),
    details, manage_url: text(d.manage_url), ...(d.cost.trim() || d.costSource ? { price: priceOf(d) } : {}),
    ...(flight || d.kind !== "cruise" ? {} : { itinerary: d.itinerary.map((p) => ({ name: p.name.trim(), zone: p.zone.trim(), arrive_local: p.arrive || null, depart_local: p.depart || null })) }),
    ...(FOR_EVERYONE.includes(d.kind) ? {} : { travelers: [...d.people.map((id) => ({ person_id: id, ...seat(id) })), ...d.printed.map((name) => ({ person_id: null, name, ...seat(name) }))] }),
  };
}
