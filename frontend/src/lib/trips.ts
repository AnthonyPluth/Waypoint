// What the trip screens work out from the API's trips: which segment is next, a trip's days, how a place's time reads
// beside yours, and which membership a booking's traveller would use. Times are wall-clock times at the place, shown as
// they are; an instant is worked out only to compare and count down, never to store.
import type { LoyaltyEntry, Segment, Trip } from "./api-types";

export type Traveler = Segment["travelers"][number];

const LOCAL = /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)/;
const locale = () => (typeof navigator !== "undefined" && navigator.language) || "en-US";

/** The zone this browser is in: the viewer's own. */
export const viewerZone = (): string => Intl.DateTimeFormat().resolvedOptions().timeZone;

/** The UTC offset (minutes) a zone has at an instant. */
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

/** The moment a wall-clock time at a place is (epoch ms), for comparing and counting down. NaN for text that isn't one. */
export function instant(local: string, zone: string): number {
  const guess = utcOf(local);
  if (Number.isNaN(guess)) return NaN;
  const first = offsetAt(guess, zone);
  const t = guess - first * 60000;
  const second = offsetAt(t, zone);
  return second === first ? t : guess - second * 60000;
}

/** A day's date as it's written ("2026-11-20") for an instant in a zone: the viewer's today, for sorting trips. */
export function dayIn(ms: number, zone: string): string {
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit" })
    .formatToParts(new Date(ms)).map((x) => [x.type, x.value]));
  return `${p.year}-${p.month}-${p.day}`;
}

const asUtc = (local: string) => new Date(utcOf(local));

/** "7:00 PM", as written at the place. */
export const clock = (local: string): string => asUtc(local).toLocaleTimeString(locale(), { timeZone: "UTC", hour: "numeric", minute: "2-digit" });
/** "Fri, Nov 20". */
export const dayLabel = (local: string): string => asUtc(local).toLocaleDateString(locale(), { timeZone: "UTC", weekday: "short", month: "short", day: "numeric" });
/** "Nov 20, 2026". */
export const dateLabel = (day: string): string => asUtc(`${day}T00:00`).toLocaleDateString(locale(), { timeZone: "UTC", month: "short", day: "numeric", year: "numeric" });

/** A place's time with, when your zone's offset then is different, what it is for you in brackets: `{ text: "7:00 PM",
 *  yours: "4:00 PM PST" }`. The place's time is never converted; `yours` is only a second reading of the same moment. */
export function placeTime(local: string, zone: string, mine: string = viewerZone()): { text: string; yours: string | null } {
  const text = clock(local);
  const at = instant(local, zone);
  if (Number.isNaN(at) || offsetAt(at, zone) === offsetAt(at, mine)) return { text, yours: null };
  const yours = new Intl.DateTimeFormat(locale(), { timeZone: mine, hour: "numeric", minute: "2-digit", timeZoneName: "short" }).format(new Date(at));
  const sameDay = dayIn(at, mine) === local.slice(0, 10);
  return { text, yours: sameDay ? yours : `${new Intl.DateTimeFormat(locale(), { timeZone: mine, month: "short", day: "numeric" }).format(new Date(at))}, ${yours}` };
}

/** How long until a moment (or "now"): "45 min", "5 h 20 min", "2 days 3 h". */
export function until(ms: number): string {
  const mins = Math.round(ms / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins} min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return mins % 60 ? `${hours} h ${mins % 60} min` : `${hours} h`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"}${hours % 24 ? ` ${hours % 24} h` : ""}`;
}

/** An imported flight whose file gave no times: it has a day but no times, and no duration. */
export const untimed = (s: Segment): boolean => s.details.time_unknown === "yes";

export const startAt = (s: Segment): number => instant(s.start_local, s.start_zone);
export const endAt = (s: Segment): number => instant(s.end_local, s.end_zone);

// ------------------------------------------------------------------------------------------ one card per flight

const FLIGHT_NUMBER = /^([A-Z0-9]{2,3}?)0*(\d{1,4}[A-Z]?)$/;

/** A flight number as one flight has it however it's written (carrier code and number, no spaces or leading zeros, upper
 *  case), as the server's `flight_key`: "AA 4001", "aa4001" and "AA04001" are all AA4001. Null for text that isn't one. */
export function flightKey(number: string | undefined | null): string | null {
  const found = FLIGHT_NUMBER.exec((number ?? "").replace(/[\s-]/g, "").toUpperCase());
  return found ? `${found[1]}${found[2]}` : null;
}

/** One card on a screen: a booking, or the bookings of one flight (each keeps its own segment, with its code, travellers
 *  and edits). `lead` is the one whose details the card shows: the first that isn't cancelled. */
export type Card = { id: string; segments: Segment[]; lead: Segment; cancelled: boolean; timesDiffer: boolean };

const groupKey = (s: Segment): string | null => {
  const number = s.kind === "flight" ? flightKey(s.details.flight_number) : null;
  return number ? [number, s.start_local.slice(0, 10), (s.origin ?? "").toUpperCase(), (s.destination ?? "").toUpperCase()].join("|") : null;
};

/** Whether the bookings that aren't cancelled don't agree on when the flight leaves or lands. */
export const timesDiffer = (bookings: Segment[]): boolean =>
  new Set(bookings.filter((s) => s.status !== "cancelled" && !untimed(s)).map((s) => `${s.start_local}|${s.end_local}`)).size > 1;

/** A trip's segments as cards: the bookings of one flight (the same flight number, local departure date and airports) are one
 *  card; a stay, a rental, a train, a flight with no number or one nobody else booked is a card of its own. In the order the
 *  segments come. `timesDiffer`: the bookings that aren't cancelled don't agree on when it leaves or lands, so the card
 *  shows each booking's times rather than picking one. */
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

export type NextUp = { trip: Trip; segment: Segment; bookings: Segment[]; state: "now" | "next" };

/** The segment the Upcoming page leads with, among every trip you can see. One under way (a flight in the air, a rental
 *  out) leads: "now". Otherwise the one that starts soonest: "next". A hotel stay under way doesn't push the day's flight
 *  aside; it leads only when nothing else is left. Cancelled segments, ones that are over and ones with no times (there's nothing to count down to) never lead. A flight on
 *  several bookings is one: `segment` is the first, `bookings` all of them. */
export function nextUp(trips: Trip[], now: number): NextUp | null {
  const live = trips.flatMap((trip) => bookingCards(trip.segments).flatMap((card) => {
    const bookings = card.segments.filter((s) => s.status !== "cancelled" && !untimed(s) && endAt(s) > now);
    return bookings.length ? [{ trip, segment: bookings[0], bookings }] : [];
  }));
  const by = (a: { segment: Segment }, b: { segment: Segment }) => startAt(a.segment) - startAt(b.segment);
  const started = live.filter((x) => startAt(x.segment) <= now).sort(by);
  const going = started.find((x) => x.segment.kind !== "hotel");
  if (going) return { ...going, state: "now" };
  const coming = live.filter((x) => startAt(x.segment) > now).sort(by)[0];
  if (coming) return { ...coming, state: "next" };
  return started[0] ? { ...started[0], state: "now" } : null;
}

/** A trip is over once its last day is before today (a trip with no dates yet isn't). */
export const isPast = (trip: Trip, today: string): boolean => !!trip.end_date && trip.end_date < today;

/** Your trips split into those still to come or under way (soonest first) and those over (latest first). */
export function splitTrips(trips: Trip[], today: string): { upcoming: Trip[]; past: Trip[] } {
  const key = (t: Trip) => t.start_date ?? "9999-12-31";
  const upcoming = trips.filter((t) => !isPast(t, today)).sort((a, b) => key(a).localeCompare(key(b)));
  const past = trips.filter((t) => isPast(t, today)).sort((a, b) => key(b).localeCompare(key(a)));
  return { upcoming, past };
}

/** The trip the page after Next up shows: the one it's about, else the first one still to come. */
export const featuredTrip = (trips: Trip[], next: NextUp | null, today: string): Trip | null =>
  next?.trip ?? splitTrips(trips, today).upcoming[0] ?? null;

export type DayItem = { segment: Segment; bookings: Segment[]; role: "start" | "end" };
export type Day = { date: string; items: DayItem[] };

/** A trip's days, in order, each with what happens on it: a card on its start day (a flight on two bookings once, with
 *  `bookings` naming both), and a stay or rental's end on its last. Days with nothing on them are left out. Cancelled
 *  segments stay (struck through on the page). */
export function tripDays(trip: Trip): Day[] {
  const days = new Map<string, DayItem[]>();
  const put = (date: string, item: DayItem) => days.set(date, [...(days.get(date) ?? []), item]);
  for (const { lead: segment, segments: bookings } of bookingCards(trip.segments)) {
    put(segment.start_local.slice(0, 10), { segment, bookings, role: "start" });
    if ((segment.kind === "hotel" || segment.kind === "car") && segment.end_local.slice(0, 10) !== segment.start_local.slice(0, 10)) {
      put(segment.end_local.slice(0, 10), { segment, bookings, role: "end" });
    }
  }
  return [...days].sort(([a], [b]) => a.localeCompare(b)).map(([date, items]) => ({
    date, items: items.sort((a, b) => (a.role === "end" ? a.segment.end_local : a.segment.start_local).localeCompare(b.role === "end" ? b.segment.end_local : b.segment.start_local)),
  }));
}

// ------------------------------------------------------------------------------------------ loyalty

// [what the booking is, a word of the provider's name, the program]: matched on whole words, and only for that kind of booking.
const BRANDS: [string, RegExp, string][] = [
  ["flight", /\balaska\b/i, "Alaska Mileage Plan"], ["flight", /\bamerican\b/i, "American AAdvantage"], ["flight", /\bdelta\b/i, "Delta SkyMiles"],
  ["flight", /\bjetblue\b/i, "JetBlue TrueBlue"], ["flight", /\bsouthwest\b/i, "Southwest Rapid Rewards"], ["flight", /\bunited\b/i, "United MileagePlus"],
  ["hotel", /\bhilton\b/i, "Hilton Honors"], ["hotel", /\bhyatt\b/i, "Hyatt World of Hyatt"], ["hotel", /\b(ihg|holiday inn|intercontinental|crowne plaza)\b/i, "IHG One Rewards"],
  ["hotel", /\b(marriott|bonvoy|sheraton|westin|ritz)\b/i, "Marriott Bonvoy"], ["hotel", /\bwyndham\b/i, "Wyndham Rewards"],
  ["car", /\bavis\b/i, "Avis Preferred"], ["car", /\benterprise\b/i, "Enterprise Plus"], ["car", /\bhertz\b/i, "Hertz Gold Plus Rewards"], ["car", /\bnational\b/i, "National Emerald Club"],
];

/** The program a booking's provider belongs to (its name as printed: "American Airlines" → "American AAdvantage"), or null
 *  when Waypoint can't tell (a train, an airline it has no program for). */
export function programFor(segment: Segment): string | null {
  const provider = segment.provider ?? "";
  const hit = provider ? BRANDS.find(([kind, re]) => kind === segment.kind && re.test(provider)) : undefined;
  return hit ? hit[2] : null;
}

export type Membership =
  | { state: "found"; entry: LoyaltyEntry }
  | { state: "none"; program: string }     // the booking's program is known, and they've no number for it
  | { state: "unmatched" }                 // the traveller is a printed name, not yet matched to a person
  | null;                                  // nothing to say (the provider's program isn't known)

/** The membership one traveller would use on one booking, from the household's list. */
export function membershipFor(segment: Segment, traveler: Traveler, loyalty: LoyaltyEntry[]): Membership {
  const program = programFor(segment);
  if (!program) return null;
  if (traveler.person_id === null) return { state: "unmatched" };
  const entry = loyalty.find((m) => m.person_id === traveler.person_id && m.program === program);
  return entry ? { state: "found", entry } : { state: "none", program };
}

// ------------------------------------------------------------------------------------------ wording

/** What a segment is called: a flight or train by its route, a stay by its hotel, a rental by its company. */
export function headline(s: Segment): string {
  const route = [s.origin, s.destination].filter(Boolean).join(" → ");
  if (s.kind === "flight") return route || "Flight";
  if (s.kind === "train") return route || "Train";
  if (s.kind === "hotel") return s.origin || s.provider || "Hotel stay";
  return [s.provider, s.origin].filter(Boolean).join(" · ") || "Car rental";
}

/** The line under a headline: the flight number and terminal, a stay's address, a rental's class. */
export function subline(s: Segment): string {
  const d = s.details;
  const parts = s.kind === "flight" ? [[s.provider, d.flight_number].filter(Boolean).join(" "), d.terminal && `Terminal ${d.terminal}`, d.seat && `Seat ${d.seat}`, d.cabin]
    : s.kind === "hotel" ? [d.address, d.room]
      : s.kind === "car" ? [d.car_class, d.address] : [s.provider, d.seat && `Seat ${d.seat}`, d.cabin];
  return parts.filter(Boolean).join(" · ");
}

/** What happens at a segment's start and end, in words. */
export const START_WORD: Record<Segment["kind"], string> = { flight: "Departs", hotel: "Check-in", car: "Pick-up", train: "Departs" };
export const END_WORD: Record<Segment["kind"], string> = { flight: "Arrives", hotel: "Check-out", car: "Drop-off", train: "Arrives" };

/** "Departs in 5 h", or in the last minute "Departing now" (never "Departs in now"). */
export function when(word: string, ms: number): string {
  if (ms >= 60_000) return `${word} in ${until(ms)}`;
  return word === "Departs" ? "Departing now" : word === "Arrives" ? "Arriving now" : `${word} now`;
}
