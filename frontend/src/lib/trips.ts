import type { FlightStatus, LoyaltyEntry, Segment, Trip } from "./api-types";
import { countryName } from "./stats";

export type Traveler = Segment["travelers"][number];

const LOCAL = /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)/;
const locale = () => (typeof navigator !== "undefined" && navigator.language) || "en-US";

export const viewerZone = (): string => Intl.DateTimeFormat().resolvedOptions().timeZone;

function offsetAt(ms: number, zone: string): number {
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: zone, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric", second: "numeric" })
    .formatToParts(new Date(ms)).map((x) => [x.type, Number(x.value)]));
  return Math.round((Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second) - Math.floor(ms / 1000) * 1000) / 60000);
}

function utcOf(local: string): number {
  const m = LOCAL.exec(local);
  if (!m) return NaN;
  return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
}

export function instant(local: string, zone: string): number {
  const guess = utcOf(local);
  if (Number.isNaN(guess)) return NaN;
  const first = offsetAt(guess, zone);
  const t = guess - first * 60000;
  const second = offsetAt(t, zone);
  return second === first ? t : guess - second * 60000;
}

export function dayIn(ms: number, zone: string): string {
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit" })
    .formatToParts(new Date(ms)).map((x) => [x.type, x.value]));
  return `${p.year}-${p.month}-${p.day}`;
}

const asUtc = (local: string) => new Date(utcOf(local));

export const clock = (local: string): string => asUtc(local).toLocaleTimeString(locale(), { timeZone: "UTC", hour: "numeric", minute: "2-digit" });
const yearOf = (local: string): number => Number(local.slice(0, 4));
export const dayLabel = (local: string, withYear = yearOf(local) !== new Date().getFullYear()): string =>
  asUtc(local).toLocaleDateString(locale(), { timeZone: "UTC", weekday: "short", month: "short", day: "numeric", ...(withYear && { year: "numeric" }) });
export const dayOf = (s: Pick<Segment, "kind">, local: string): string => dayLabel(local, s.kind === "visit" || undefined);
export const sameDay = (s: Pick<Segment, "start_local" | "end_local">): boolean => s.start_local.slice(0, 10) === s.end_local.slice(0, 10);
export const dateLabel = (day: string): string => asUtc(`${day}T00:00`).toLocaleDateString(locale(), { timeZone: "UTC", month: "short", day: "numeric", year: "numeric" });

export function until(ms: number): string {
  const mins = Math.round(ms / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins} min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return mins % 60 ? `${hours} h ${mins % 60} min` : `${hours} h`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"}${hours % 24 ? ` ${hours % 24} h` : ""}`;
}

export const untimed = (s: Segment): boolean => s.details.time_unknown === "yes";

export const startAt = (s: Segment): number => instant(s.start_local, s.start_zone);
export const endAt = (s: Segment): number => instant(s.end_local, s.end_zone);

const FLIGHT_NUMBER = /^([A-Z0-9]{2,3}?)0*(\d{1,4}[A-Z]?)$/;

export function flightKey(number: string | undefined | null): string | null {
  const found = FLIGHT_NUMBER.exec((number ?? "").replace(/[\s-]/g, "").toUpperCase());
  return found ? `${found[1]}${found[2]}` : null;
}

export type Card = { id: string; segments: Segment[]; lead: Segment; cancelled: boolean; timesDiffer: boolean };

const groupKey = (s: Segment): string | null => {
  const number = s.kind === "flight" ? flightKey(s.details.flight_number) : null;
  return number ? [number, s.start_local.slice(0, 10), (s.origin ?? "").toUpperCase(), (s.destination ?? "").toUpperCase()].join("|") : null;
};

export const timesDiffer = (bookings: Segment[]): boolean =>
  new Set(bookings.filter((s) => s.status !== "cancelled" && !untimed(s)).map((s) => `${s.start_local}|${s.end_local}`)).size > 1;

export function bookingCards(segments: Segment[]): Card[] {
  const cards: Card[] = [];
  const byKey = new Map<string, Segment[]>();
  for (const segment of segments) {
    const key = groupKey(segment);
    const into = key ? byKey.get(key) : undefined;
    if (into) { into.push(segment); continue; }
    const group = [segment];
    if (key) byKey.set(key, group);
    cards.push({ id: String(segment.id), segments: group, lead: segment, cancelled: false, timesDiffer: false });
  }
  for (const card of cards) {
    const live = card.segments.filter((s) => s.status !== "cancelled");
    card.lead = live[0] ?? card.segments[0];
    card.cancelled = live.length === 0;
    card.timesDiffer = timesDiffer(card.segments);
  }
  return cards;
}

export type Booked = { trip: Trip; segment: Segment; bookings: Segment[] };
export type NextUp = Booked & { state: "now" | "next"; alongside: Booked[] };

const BACKGROUND_KINDS: Segment["kind"][] = ["hotel", "car", "parking"];
export const isBackground = (s: Segment): boolean => BACKGROUND_KINDS.includes(s.kind);

export function nextUp(trips: Trip[], now: number): NextUp | null {
  const live: Booked[] = trips.flatMap((trip) => bookingCards(trip.segments).flatMap((card) => {
    const bookings = card.segments.filter((s) => s.status !== "cancelled" && !untimed(s) && endAt(s) > now);
    return bookings.length ? [{ trip, segment: bookings[0], bookings }] : [];
  }));
  const byStart = (a: Booked, b: Booked) => startAt(a.segment) - startAt(b.segment) || a.segment.id - b.segment.id;
  const byEnd = (a: Booked, b: Booked) => endAt(a.segment) - endAt(b.segment) || a.segment.id - b.segment.id;
  const started = live.filter((x) => startAt(x.segment) <= now);
  const alongside = started.filter((x) => isBackground(x.segment)).sort(byEnd);
  const going = started.filter((x) => !isBackground(x.segment)).sort(byStart)[0];
  if (going) return { ...going, state: "now", alongside };
  const coming = live.filter((x) => startAt(x.segment) > now).sort(byStart)[0];
  if (coming) return { ...coming, state: "next", alongside };
  const [held, ...rest] = alongside;
  return held ? { ...held, state: "now", alongside: rest } : null;
}

export const isPast = (trip: Trip, today: string): boolean => !!trip.end_date && trip.end_date < today;

export const KIND_ORDER: Segment["kind"][] = ["flight", "hotel", "car", "train", "cruise", "parking", "visit"];
export function tripKinds(trip: Trip): Segment["kind"][] {
  const live = trip.segments.filter((s) => s.status !== "cancelled");
  const held = new Set((live.length ? live : trip.segments).map((s) => s.kind));
  return KIND_ORDER.filter((k) => held.has(k));
}

export function splitTrips(trips: Trip[], today: string): { upcoming: Trip[]; past: Trip[] } {
  const key = (t: Trip) => t.start_date ?? "9999-12-31";
  const upcoming = trips.filter((t) => !isPast(t, today)).sort((a, b) => key(a).localeCompare(key(b)));
  const past = trips.filter((t) => isPast(t, today)).sort((a, b) => key(b).localeCompare(key(a)));
  return { upcoming, past };
}

export const featuredTrip = (trips: Trip[], next: NextUp | null, today: string): Trip | null =>
  next?.trip ?? splitTrips(trips, today).upcoming[0] ?? null;

export type DayItem = { segment: Segment; bookings: Segment[]; role: "start" | "end" };
export type Day = { date: string; items: DayItem[] };

export function tripDays(trip: Trip): Day[] {
  const days = new Map<string, DayItem[]>();
  const put = (date: string, item: DayItem) => days.set(date, [...(days.get(date) ?? []), item]);
  for (const { lead: segment, segments: bookings } of bookingCards(trip.segments)) {
    put(segment.start_local.slice(0, 10), { segment, bookings, role: "start" });
    if ((segment.kind === "hotel" || segment.kind === "car" || segment.kind === "cruise" || segment.kind === "parking") && segment.end_local.slice(0, 10) !== segment.start_local.slice(0, 10)) {
      put(segment.end_local.slice(0, 10), { segment, bookings, role: "end" });
    }
  }
  return [...days].sort(([a], [b]) => a.localeCompare(b)).map(([date, items]) => ({ date, items: inDayOrder(items) }));
}

function inDayOrder(items: DayItem[]): DayItem[] {
  const at = (i: DayItem) => (i.role === "end" ? i.segment.end_local : i.segment.start_local);
  const live = (i: DayItem) => i.segment.status !== "cancelled";
  const departures = items.filter((i) => i.role === "start" && (i.segment.kind === "flight" || i.segment.kind === "train") && live(i)).map(at);
  const returns = items.filter((i) => i.role === "end" && i.segment.kind === "car" && live(i)).map(at);
  const earliest = (...times: string[]) => times.reduce((a, b) => (b < a ? b : a));
  const key = (i: DayItem): [string, number] => {
    if (i.role === "end" && i.segment.kind === "hotel" && live(i)) return [earliest(at(i), ...departures, ...returns), 0];
    if (i.role === "end" && i.segment.kind === "car" && live(i)) return [earliest(at(i), ...departures), 1];
    return [at(i), 2];
  };
  return [...items].sort((a, b) => {
    const [ka, ra] = key(a), [kb, rb] = key(b);
    return ka.localeCompare(kb) || ra - rb || at(a).localeCompare(at(b));
  });
}

const BRANDS: [string, RegExp, string][] = [
  ["flight", /\balaska\b/i, "Alaska Mileage Plan"], ["flight", /\bamerican\b/i, "American AAdvantage"], ["flight", /\bdelta\b/i, "Delta SkyMiles"],
  ["flight", /\bjetblue\b/i, "JetBlue TrueBlue"], ["flight", /\bsouthwest\b/i, "Southwest Rapid Rewards"], ["flight", /\bunited\b/i, "United MileagePlus"],
  ["hotel", /\bhilton\b/i, "Hilton Honors"], ["hotel", /\bhyatt\b/i, "Hyatt World of Hyatt"], ["hotel", /\b(ihg|holiday inn|intercontinental|crowne plaza)\b/i, "IHG One Rewards"],
  ["hotel", /\b(marriott|bonvoy|sheraton|westin|ritz)\b/i, "Marriott Bonvoy"], ["hotel", /\bwyndham\b/i, "Wyndham Rewards"],
  ["cruise", /\bcarnival\b/i, "Carnival Rewards (formerly VIFP Club)"], ["cruise", /\bcelebrity\b/i, "Celebrity Captain's Club"], ["cruise", /\bcunard\b/i, "Cunard World Club"],
  ["cruise", /\bdisney\b/i, "Disney Castaway Club"], ["cruise", /\bholland america\b/i, "Holland America Mariner Society"], ["cruise", /\bmsc\b/i, "MSC Voyagers Club"],
  ["cruise", /\bnorwegian\b|\bncl\b/i, "Norwegian Latitudes Rewards"], ["cruise", /\boceania\b/i, "Oceania Club"], ["cruise", /\bprincess\b/i, "Princess Captain's Circle"],
  ["cruise", /\broyal caribbean\b|\brcl\b|\brcci\b/i, "Royal Caribbean Crown & Anchor Society"], ["cruise", /\bvirgin voyages\b/i, "Virgin Voyages Sailing Club"],
  ["car", /\bavis\b/i, "Avis Preferred"], ["car", /\benterprise\b/i, "Enterprise Plus"], ["car", /\bhertz\b/i, "Hertz Gold Plus Rewards"], ["car", /\bnational\b/i, "National Emerald Club"],
];

export function programFor(segment: Segment): string | null {
  const provider = segment.provider ?? "";
  const hit = provider ? BRANDS.find(([kind, re]) => kind === segment.kind && re.test(provider)) : undefined;
  return hit ? hit[2] : null;
}

export type Membership =
  | { state: "found"; entry: LoyaltyEntry }
  | { state: "none"; program: string }
  | { state: "unmatched" }
  | null;

export function membershipFor(segment: Segment, traveler: Traveler, loyalty: LoyaltyEntry[]): Membership {
  const program = programFor(segment);
  if (!program) return null;
  if (segment.kind === "flight") return traveler.person_id === null ? { state: "unmatched" } : null;
  const booker = (segment.kind !== "hotel" && segment.kind !== "car") || (traveler.person_id !== null && traveler.person_id === segment.booked_by);
  if (traveler.person_id === null) return booker ? { state: "unmatched" } : null;
  const entry = loyalty.find((m) => m.person_id === traveler.person_id && m.program === program);
  return entry ? { state: "found", entry } : booker ? { state: "none", program } : null;
}

export const UNNAMED_TRAVELLER = "Unnamed traveller";

const travellerKey = (who: Traveler): string => (who.person_id === null ? `name:${who.name.trim().toLowerCase()}` : `person:${who.person_id}`);

export type TripTraveller = { key: string; name: string };

export function tripTravellers(segments: Segment[]): TripTraveller[] {
  const seen = new Map<string, TripTraveller>();
  for (const s of segments) {
    if (s.status === "cancelled") continue;
    for (const who of s.travelers) {
      const key = travellerKey(who);
      if (!seen.has(key)) seen.set(key, { key, name: who.name.trim() || UNNAMED_TRAVELLER });
    }
  }
  return [...seen.values()];
}

export const showTripTravellers = (everyone: TripTraveller[], viewer: number | null): boolean =>
  everyone.length > 1 || (everyone.length === 1 && (viewer === null || everyone[0].key !== `person:${viewer}`));

const LISTS_NO_TRAVELLERS: Segment["kind"][] = ["hotel", "car", "parking"];

export function showBookingTravellers(s: Segment, everyone: TripTraveller[]): boolean {
  if (s.kind === "flight" || s.kind === "cruise") return true;
  if (LISTS_NO_TRAVELLERS.includes(s.kind)) return false;
  if (s.status === "cancelled" || s.travelers.some((who) => who.seat)) return true;
  const here = new Set(s.travelers.map(travellerKey));
  return here.size !== everyone.length || everyone.some((who) => !here.has(who.key));
}

export function loyaltyNumbers(s: Segment, loyalty: LoyaltyEntry[]): LoyaltyEntry[] {
  const found = s.travelers.flatMap((who) => {
    const m = membershipFor(s, who, loyalty);
    return m?.state === "found" ? [m.entry] : [];
  });
  return found.filter((entry, i) => found.findIndex((e) => e.id === entry.id) === i);
}

export function headline(s: Segment): string {
  const route = [s.origin, s.destination].filter(Boolean).join(" → ");
  if (s.kind === "flight") return route || "Flight";
  if (s.kind === "train") return route || "Train";
  if (s.kind === "hotel") return s.origin || s.provider || "Hotel stay";
  if (s.kind === "parking") return s.origin || s.provider || "Parking";
  if (s.kind === "visit") return s.destination ? countryName(s.destination) : "A visit";
  if (s.kind === "cruise") return [s.details.ship || s.provider, s.origin].filter(Boolean).join(" · ") || "Cruise";
  return [s.provider, s.origin].filter(Boolean).join(" · ") || "Car rental";
}

const COUNTRIES = /^(usa|us|u\.s\.a\.|united states( of america)?)$/i;
const POSTAL_CODE = "\\d{5}(?:-\\d{4})?|[A-Z]{1,2}\\d[A-Z\\d]? ?\\d[A-Z]{2}|[A-Z]\\d[A-Z] ?\\d[A-Z]\\d";
const POSTAL_PART = new RegExp(`^(${POSTAL_CODE}|\\d{4,6})$`, "i");
const POSTAL_SUFFIX = new RegExp(`\\s+(${POSTAL_CODE})$`, "i");
const POSTAL_PREFIX = /^\d{4,6}\s+/;
const STREET_NUMBER = /^\d/;

function addressParts(address: string | undefined): string[] {
  const parts = (address ?? "").split(/[,\n]/).map((p) => p.trim()).filter(Boolean);
  if (parts.length > 1 && COUNTRIES.test(parts[parts.length - 1])) parts.pop();
  return parts.filter((p) => !POSTAL_PART.test(p));
}

export function cityState(address: string | undefined): string {
  const parts = addressParts(address);
  if (parts.length < 2) return "";
  const last = parts[parts.length - 1].replace(POSTAL_SUFFIX, "");
  if (parts.length === 2) return STREET_NUMBER.test(parts[0]) ? last : `${parts[0]}, ${last}`;
  const city = parts[parts.length - 2].replace(POSTAL_PREFIX, "");
  return `${city}, ${last}`;
}

const squash = (v: string | null | undefined): string => (v ?? "").split(/\s+/).filter(Boolean).join(" ").toLowerCase();

export const samePlace = (a: string | null | undefined, b: string | null | undefined): boolean => squash(a) !== "" && squash(a) === squash(b);

export const extraAddress = (s: Pick<Segment, "kind" | "origin" | "details">): string | undefined =>
  s.kind === "car" && samePlace(s.details.address, s.origin) ? undefined : s.details.address;

export const placeOf = (address: string | undefined): string => cityState(address) || (address ?? "").trim();

export function upcomingTitle(s: Segment): string {
  return s.kind === "hotel" && s.hotel_brand ? s.hotel_brand : headline(s);
}

export function seatsInOrder(seats: string): string {
  return [...new Set(seats.split(",").map((x) => x.trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" })).join(", ");
}

export function subline(s: Segment, condensed = false): string {
  const d = s.details;
  const parts = s.kind === "flight" ? [[s.provider, d.flight_number].filter(Boolean).join(" "), d.aircraft, d.terminal && `Terminal ${d.terminal}`, d.seat && `Seat ${seatsInOrder(d.seat)}`, condensed ? null : d.cabin]
    : s.kind === "hotel" ? [condensed ? placeOf(d.address) : d.address, d.room]
      : s.kind === "car" ? [d.car_class, condensed ? placeOf(extraAddress(s)) : extraAddress(s)] : s.kind === "parking" ? [d.space_type, condensed ? placeOf(d.address) : d.address] : s.kind === "cruise" ? [s.details.ship ? s.provider : null, d.room && `Cabin ${d.room}`, d.deck && `Deck ${d.deck}`] : [s.provider, d.seat && `Seat ${seatsInOrder(d.seat)}`, d.cabin];
  return parts.filter(Boolean).join(" · ");
}

export const START_WORD: Record<Segment["kind"], string> = { flight: "Departs", hotel: "Check-in", car: "Pick-up", train: "Departs", cruise: "Embarks", parking: "Entry", visit: "From" };
export const END_WORD: Record<Segment["kind"], string> = { flight: "Arrives", hotel: "Check-out", car: "Drop-off", train: "Arrives", cruise: "Disembarks", parking: "Exit", visit: "To" };

export function when(word: string, ms: number): string {
  if (ms >= 60_000) return `${word} in ${until(ms)}`;
  return word === "Departs" ? "Departing now" : word === "Arrives" ? "Arriving now" : `${word} now`;
}

export const CHECK_IN_WINDOW_HOURS = 24;
const CHECK_IN_WINDOW_MS = CHECK_IN_WINDOW_HOURS * 3_600_000;

export function checkInOpen(s: Segment, now: number): boolean {
  const from = startAt(s);
  return s.kind === "flight" && s.status !== "cancelled" && !untimed(s) && !Number.isNaN(from) && from - CHECK_IN_WINDOW_MS <= now && now < from;
}

export function appWord(s: Segment, now: number, mobile: boolean): string {
  if (checkInOpen(s, now)) return "Check in";
  return mobile ? "Open in app" : "Manage booking";
}

export function vendorLink(s: Segment, mobile: boolean): { href: string; label: string } | null {
  if (!mobile || s.links.app || !s.links.open) return null;
  return { href: s.links.open, label: s.links.open_kind === "website" ? "Open website" : "Open in app" };
}

const PAST_WORD: Record<Segment["kind"], string> = { flight: "Landed", hotel: "Checked out", car: "Dropped off", train: "Arrived", cruise: "Disembarked", parking: "Exited", visit: "Visited" };

export function routeProgress(s: Segment, now: number): number {
  const from = startAt(s), to = endAt(s);
  if (untimed(s) || Number.isNaN(from) || Number.isNaN(to)) return 0;
  if (to <= from) return now >= to ? 1 : 0;
  return Math.min(1, Math.max(0, (now - from) / (to - from)));
}

export const LIVE_STALE_HOURS = 3;
const LIVE_STALE_MS = LIVE_STALE_HOURS * 3_600_000;

export type FlightEvidence = "landed" | "cancelled" | "diverted" | "delayed" | "departed" | "scheduled";

export function flightEvidence(live: Pick<FlightStatus, "state" | "fetched_at"> | null | undefined, now: number, online = true): FlightEvidence {
  if (!live || !online) return "scheduled";
  if (live.state === "landed" || live.state === "cancelled") return live.state;
  const fetched = Date.parse(live.fetched_at);
  if (Number.isNaN(fetched) || now - fetched > LIVE_STALE_MS) return "scheduled";
  return live.state === "scheduled" ? "scheduled" : live.state;
}

const lead = (word: string, ms: number, soon: string): string => (ms >= 60_000 ? `${word} ${until(ms)}` : soon);

export function passHeadline(s: Segment, now: number, live?: FlightStatus | null, online = true): string {
  if (s.status === "cancelled") return "Cancelled";
  const from = startAt(s), to = endAt(s);
  if (untimed(s) || Number.isNaN(from) || Number.isNaN(to)) return "Time not recorded";
  if (s.kind !== "flight") {
    if (now < from) return when(START_WORD[s.kind], from - now);
    return now < to ? when(END_WORD[s.kind], to - now) : PAST_WORD[s.kind];
  }
  const evidence = flightEvidence(live, now, online);
  if (evidence === "landed") return "Landed";
  if (evidence === "cancelled") return "Cancelled by the airline";
  if (evidence === "diverted") return "Diverted";
  if (live && evidence === "delayed") {
    const late = live.delay_minutes ? `Delayed ${live.delay_minutes} min` : "Delayed";
    const expected = live.dep_estimated ? instant(live.dep_estimated, live.dep_zone) : NaN;
    if (!Number.isNaN(expected) && expected > now) return `${late}, ${lead("expected to leave in", expected - now, "expected to leave now")}`;
    if (now < from) return `${late}, ${lead("scheduled departure in", from - now, "scheduled departure now")}`;
    return `${late}, not yet confirmed as departed`;
  }
  if (live && evidence === "departed") {
    const expected = live.arr_estimated ? instant(live.arr_estimated, live.arr_zone) : to;
    const arrival = Number.isNaN(expected) ? to : expected;
    return arrival > now ? `Departed, ${lead("expected to arrive in", arrival - now, "expected to arrive now")}` : "Departed, arrival not yet confirmed";
  }
  if (now < from - CHECK_IN_WINDOW_MS) return `Check-in usually opens in ${until(from - CHECK_IN_WINDOW_MS - now)}`;
  if (now < from) return `Check-in usually open, ${lead("scheduled departure in", from - now, "scheduled departure now")}`;
  if (now < to) return lead("Scheduled arrival in", to - now, "Scheduled arrival now");
  return "Scheduled arrival time passed";
}
