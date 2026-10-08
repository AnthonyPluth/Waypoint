import type { LoyaltyEntry, Segment, Trip } from "./api-types";

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
export const dayLabel = (local: string): string => asUtc(local).toLocaleDateString(locale(), { timeZone: "UTC", weekday: "short", month: "short", day: "numeric" });
export const dateLabel = (day: string): string => asUtc(`${day}T00:00`).toLocaleDateString(locale(), { timeZone: "UTC", month: "short", day: "numeric", year: "numeric" });

export function placeTime(local: string, zone: string, mine: string = viewerZone()): { text: string; yours: string | null } {
  const text = clock(local);
  const at = instant(local, zone);
  if (Number.isNaN(at) || offsetAt(at, zone) === offsetAt(at, mine)) return { text, yours: null };
  const yours = new Intl.DateTimeFormat(locale(), { timeZone: mine, hour: "numeric", minute: "2-digit", timeZoneName: "short" }).format(new Date(at));
  const sameDay = dayIn(at, mine) === local.slice(0, 10);
  return { text, yours: sameDay ? yours : `${new Intl.DateTimeFormat(locale(), { timeZone: mine, month: "short", day: "numeric" }).format(new Date(at))}, ${yours}` };
}

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

export type NextUp = { trip: Trip; segment: Segment; bookings: Segment[]; state: "now" | "next" };

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

export const isPast = (trip: Trip, today: string): boolean => !!trip.end_date && trip.end_date < today;

export const KIND_ORDER: Segment["kind"][] = ["flight", "hotel", "car", "train", "cruise"];
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
    if ((segment.kind === "hotel" || segment.kind === "car" || segment.kind === "cruise") && segment.end_local.slice(0, 10) !== segment.start_local.slice(0, 10)) {
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
  const booker = segment.kind !== "hotel" || (traveler.person_id !== null && traveler.person_id === segment.booked_by);
  if (traveler.person_id === null) return booker ? { state: "unmatched" } : null;
  const entry = loyalty.find((m) => m.person_id === traveler.person_id && m.program === program);
  return entry ? { state: "found", entry } : booker ? { state: "none", program } : null;
}

export function headline(s: Segment): string {
  const route = [s.origin, s.destination].filter(Boolean).join(" → ");
  if (s.kind === "flight") return route || "Flight";
  if (s.kind === "train") return route || "Train";
  if (s.kind === "hotel") return s.origin || s.provider || "Hotel stay";
  if (s.kind === "cruise") return [s.details.ship || s.provider, s.origin].filter(Boolean).join(" · ") || "Cruise";
  return [s.provider, s.origin].filter(Boolean).join(" · ") || "Car rental";
}

export function subline(s: Segment): string {
  const d = s.details;
  const parts = s.kind === "flight" ? [[s.provider, d.flight_number].filter(Boolean).join(" "), d.terminal && `Terminal ${d.terminal}`, d.seat && `Seat ${d.seat}`, d.cabin]
    : s.kind === "hotel" ? [d.address, d.room]
      : s.kind === "car" ? [d.car_class, d.address] : s.kind === "cruise" ? [s.details.ship ? s.provider : null, d.room && `Cabin ${d.room}`, d.deck && `Deck ${d.deck}`] : [s.provider, d.seat && `Seat ${d.seat}`, d.cabin];
  return parts.filter(Boolean).join(" · ");
}

export const START_WORD: Record<Segment["kind"], string> = { flight: "Departs", hotel: "Check-in", car: "Pick-up", train: "Departs", cruise: "Embarks" };
export const END_WORD: Record<Segment["kind"], string> = { flight: "Arrives", hotel: "Check-out", car: "Drop-off", train: "Arrives", cruise: "Disembarks" };

export function when(word: string, ms: number): string {
  if (ms >= 60_000) return `${word} in ${until(ms)}`;
  return word === "Departs" ? "Departing now" : word === "Arrives" ? "Arriving now" : `${word} now`;
}

export const CHECK_IN_WINDOW_HOURS = 24;
const CHECK_IN_WINDOW_MS = CHECK_IN_WINDOW_HOURS * 3_600_000;

const PAST_WORD: Record<Segment["kind"], string> = { flight: "Landed", hotel: "Checked out", car: "Dropped off", train: "Arrived", cruise: "Disembarked" };

export function routeProgress(s: Segment, now: number): number {
  const from = startAt(s), to = endAt(s);
  if (untimed(s) || Number.isNaN(from) || Number.isNaN(to)) return 0;
  if (to <= from) return now >= to ? 1 : 0;
  return Math.min(1, Math.max(0, (now - from) / (to - from)));
}

export function passHeadline(s: Segment, now: number): string {
  if (s.status === "cancelled") return "Cancelled";
  const from = startAt(s), to = endAt(s);
  if (untimed(s) || Number.isNaN(from) || Number.isNaN(to)) return "Time not recorded";
  if (s.kind !== "flight") {
    if (now < from) return when(START_WORD[s.kind], from - now);
    return now < to ? when(END_WORD[s.kind], to - now) : PAST_WORD[s.kind];
  }
  if (now < from - CHECK_IN_WINDOW_MS) return `Check-in opens in ${until(from - CHECK_IN_WINDOW_MS - now)}`;
  if (now < from) return `Check-in is open, departs in ${until(from - now)}`;
  return now < to ? `Under way, arrives in ${until(to - now)}` : PAST_WORD.flight;
}
