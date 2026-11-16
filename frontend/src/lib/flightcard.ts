import type { FlightStatus, Segment } from "./api-types";
import { liveChip, type Chip } from "./status";
import { clock, dayIn, dayLabel, daysBetween, dayShiftWords, flightEvidence, flightProgress, instant, seatsInOrder } from "./trips";

export const LIVE_STATUS_STARTS_DAYS = 3;
export const BOARDING_MINUTES = 40;

const DAY_MS = 86_400_000;
const MINUTE_MS = 60_000;

export type CardState = "scheduled" | "boarding" | "delayed" | "in-the-air" | "landed" | "cancelled" | "diverted";
export type Source = "live" | "booking";
export type Fact = { label: string; value: string | null; abbreviated: string | null; source: Source };
export type Stamp = { local: string; zone: string; time: string; zoneName: string; original: string | null; tone: "plain" | "late" | "gone"; later: string; laterWords: string };

export type FlightCardView = {
  state: CardState;
  noLive: boolean;
  pill: Chip | null;
  number: string;
  carrier: string;
  provider: string;
  duration: string;
  origin: string;
  destination: string;
  depart: Stamp;
  arrive: Stamp;
  updated: string | null;
  sentence: string;
  side: "Departure" | "Arrival";
  sideCode: string;
  facts: Fact[];
  progress: number | null;
  name: string;
};

export type FlightCardInput = {
  segment: Segment;
  status: FlightStatus | undefined;
  liveOn: boolean;
  now: number;
  online: boolean;
  city: (code: string) => string;
};

const locale = () => (typeof navigator !== "undefined" && navigator.language) || "en-US";

export const wallClock = (local: string): string => clock(local).replace(/\b([AP])M\b/, (_, half: string) => `${half.toLowerCase()}m`);

export function zoneName(zone: string, at: number): string {
  try {
    return new Intl.DateTimeFormat(locale(), { timeZone: zone, timeZoneName: "short" }).formatToParts(new Date(at)).find((p) => p.type === "timeZoneName")?.value ?? "";
  } catch {
    return "";
  }
}

const plural = (n: number, word: string): string => `${n} ${word}${n === 1 ? "" : "s"}`;

export function inWords(ms: number): string {
  const minutes = Math.max(1, Math.round(ms / MINUTE_MS));
  const hours = Math.floor(minutes / 60);
  if (!hours) return plural(minutes, "minute");
  return minutes % 60 ? `${plural(hours, "hour")} ${plural(minutes % 60, "minute")}` : plural(hours, "hour");
}

export function lengthOf(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "";
  const minutes = Math.round(ms / MINUTE_MS);
  const hours = Math.floor(minutes / 60);
  if (!hours) return `${minutes}m`;
  return minutes % 60 ? `${hours}h ${minutes % 60}m` : `${hours}h`;
}

export function updatedWords(fetchedAt: string, now: number): string {
  const fetched = Date.parse(fetchedAt);
  if (Number.isNaN(fetched)) return "";
  const minutes = Math.max(0, Math.floor((now - fetched) / MINUTE_MS));
  if (minutes < 1) return "Updated just now";
  if (minutes < 60) return `Updated ${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  return hours < 24 ? `Updated ${hours} h ago` : `Updated ${Math.floor(hours / 24)} d ago`;
}

export function flightNumber(raw: string | undefined): string {
  const text = (raw ?? "").trim().toUpperCase();
  const found = /^([A-Z0-9]{2})\s*0*(\d{1,4}[A-Z]?)$/.exec(text);
  return found ? `${found[1]} ${found[2]}` : text;
}

const CABIN_ON_PHONE: Record<string, string> = { economy: "Econ", "premium economy": "Prem Econ" };
export const cabinOnPhone = (cabin: string): string => CABIN_ON_PHONE[cabin.trim().toLowerCase()] ?? cabin;

const stamp = (local: string, zone: string, tone: Stamp["tone"] = "plain", original: string | null = null, from: string | null = null): Stamp => {
  const days = from ? daysBetween(from, local) : 0;
  return {
    local, zone, time: wallClock(local), zoneName: zoneName(zone, instant(local, zone)), original, tone,
    later: days ? `${days > 0 ? "+" : "−"}${plural(Math.abs(days), "day")}` : "", laterWords: days ? dayShiftWords(from, local) : "",
  };
};

const shortDay = (local: string): string => dayLabel(local, false).replace(/,/g, "");

const minutesBetween = (later: number, earlier: number): number => Math.round((later - earlier) / MINUTE_MS);

const lateWords = (minutes: number): string => (minutes === 0 ? "on time" : `${plural(Math.abs(minutes), "minute")} ${minutes < 0 ? "early" : "late"}`);

export function flightCardView(input: FlightCardInput): FlightCardView {
  const { segment: s, status: st, liveOn, now, online, city } = input;
  const dayStart = s.start_local;
  const bookedDep = instant(s.start_local, s.start_zone);
  const bookedArr = instant(s.end_local, s.end_zone);
  const evidence = s.status === "cancelled" ? "cancelled" : flightEvidence(st, now, online);
  const liveDep = st ? st.dep_actual ?? st.dep_estimated : null;
  const liveArr = st ? st.arr_actual ?? st.arr_estimated : null;
  const depLocal = liveDep ?? s.start_local;
  const depZone = liveDep && st ? st.dep_zone : s.start_zone;
  const arrLocal = liveArr ?? s.end_local;
  const arrZone = liveArr && st ? st.arr_zone : s.end_zone;
  const depAt = instant(depLocal, depZone);
  const arrAt = instant(arrLocal, arrZone);

  const gate = st?.dep_gate ?? null;
  const state: CardState = (() => {
    if (evidence === "cancelled") return "cancelled";
    if (evidence === "diverted") return "diverted";
    if (evidence === "landed") return "landed";
    if (evidence === "departed") return "in-the-air";
    if (evidence === "delayed") return "delayed";
    if (now >= bookedArr) return "landed";
    if (now >= bookedDep) return "in-the-air";
    if (st && gate && now >= depAt - BOARDING_MINUTES * MINUTE_MS && now < depAt) return "boarding";
    return "scheduled";
  })();

  const noLive = state === "scheduled" && !st && liveOn && bookedDep - now > LIVE_STATUS_STARTS_DAYS * DAY_MS;
  const number = flightNumber(s.details.flight_number);
  const provider = s.provider ?? "";
  const origin = s.origin ?? "—";
  const divertedTo = state === "diverted" && st?.destination && st.destination !== s.destination ? st.destination : null;
  const destination = divertedTo ?? s.destination ?? "—";
  const isToday = dayIn(now, s.start_zone) === s.start_local.slice(0, 10);
  const lateBy = st?.delay_minutes ?? null;

  let depart = stamp(depLocal, depZone);
  let arrive = stamp(arrLocal, arrZone, "plain", null, dayStart);
  if (state === "delayed") {
    const moved = depLocal !== s.start_local;
    const arrMoved = !!liveArr && arrLocal !== s.end_local;
    depart = stamp(depLocal, depZone, "late", moved ? wallClock(s.start_local) : null);
    arrive = stamp(arrLocal, arrZone, "late", arrMoved ? wallClock(s.end_local) : null, dayStart);
  } else if (state === "cancelled") {
    depart = stamp(s.start_local, s.start_zone, "gone");
    arrive = stamp(s.end_local, s.end_zone, "gone", null, dayStart);
  } else if (state === "diverted") {
    arrive = stamp(arrLocal, arrZone, "late", null, dayStart);
  }

  const gone = state === "cancelled";
  const flown = st?.dep_actual && st.arr_actual && state === "landed" ? instant(st.arr_actual, st.arr_zone) - instant(st.dep_actual, st.dep_zone) : NaN;
  const duration = gone ? "" : lengthOf(Number.isNaN(flown) ? bookedArr - bookedDep : flown);

  const updated = st ? updatedWords(st.fetched_at, now) || null : null;
  const when = isToday ? `at ${depart.time}` : `${shortDay(depLocal)} at ${depart.time}`;
  const whereTo = city(destination);
  const lands = state === "in-the-air" ? arrAt - now : NaN;
  const landing = `${arrive.time}${lands >= MINUTE_MS ? `, in ${inWords(lands)}` : ""}`;
  const landedOn = dayIn(now, arrZone) === arrLocal.slice(0, 10) ? "" : `${shortDay(arrLocal)} `;
  const early = st?.arr_actual ? lateWords(minutesBetween(instant(st.arr_actual, st.arr_zone), instant(st.arr_scheduled ?? s.end_local, st.arr_scheduled ? st.arr_zone : s.end_zone))) : "";
  const carrierWord = provider || "the airline";
  const delayWords = lateBy ? `, ${plural(lateBy, "minute")} late` : "";

  const sentence = (() => {
    if (noLive) return `Live status starts ${plural(LIVE_STATUS_STARTS_DAYS, "day")} before departure. Until then these are the times on your booking.`;
    switch (state) {
      case "scheduled": return `Your flight to ${whereTo} departs ${shortDay(depLocal)} at ${depart.time}.`;
      case "boarding": return `Boarding now at gate ${gate}. Your flight departs at ${depart.time}.`;
      case "delayed": return `Your flight now departs ${when}${delayWords}.`;
      case "in-the-air": return `Landing in ${whereTo} at ${landing}.`;
      case "landed": return `Landed ${landedOn}at ${arrive.time}${early ? `, ${early}` : ""}.`;
      case "cancelled": return `This flight${isToday ? "" : ` on ${shortDay(s.start_local)}`} was cancelled. Contact ${carrierWord} about rebooking.`;
      case "diverted": return divertedTo ? `Diverted to ${whereTo} (${divertedTo}), expected to land at ${arrive.time}.` : `This flight was diverted, expected to land at ${arrive.time}.`;
    }
  })();

  const pill: Chip | null = (() => {
    if (noLive) return null;
    switch (state) {
      case "scheduled": return { label: "Scheduled", tone: "quiet" };
      case "boarding": return { label: "Boarding", tone: "info" };
      case "delayed": return liveChip({ state: "delayed", delay_minutes: lateBy });
      case "in-the-air": return { label: "In the air", tone: "info" };
      case "landed": return { label: "Landed", tone: "ok" };
      case "cancelled": return { label: "Cancelled", tone: "bad" };
      case "diverted": return { label: "Diverted", tone: "bad" };
    }
  })();

  const seat = seatsInOrder(s.details.seat || s.travelers.map((t) => t.seat).filter(Boolean).join(", "));
  const cabin = s.details.cabin?.trim() || null;
  const arrivalSide = state === "in-the-air" || state === "landed" || state === "diverted";
  const lastKnown = state !== "cancelled" && state !== "diverted";
  const live = (value: string | null | undefined, on = lastKnown): Fact["value"] => (on && value ? value : null);
  const seatFact: Fact = { label: seat.includes(",") ? "Seats" : "Seat", value: seat || null, abbreviated: null, source: "booking" };
  const facts: Fact[] = arrivalSide
    ? [
      { label: "Terminal", value: live(st?.arr_terminal, state !== "diverted"), abbreviated: null, source: "live" },
      { label: "Gate", value: live(st?.arr_gate, state !== "diverted"), abbreviated: null, source: "live" },
      { label: "Belt", value: null, abbreviated: null, source: "live" },
      seatFact,
    ]
    : (() => {
      const liveTerminal = live(st?.dep_terminal);
      const bookedTerminal = state === "cancelled" ? null : s.details.terminal?.trim() || null;
      return [
        { label: "Terminal", value: liveTerminal ?? bookedTerminal, abbreviated: null, source: liveTerminal || !bookedTerminal ? "live" : "booking" } satisfies Fact,
        { label: "Gate", value: live(gate), abbreviated: null, source: "live" } satisfies Fact,
        seatFact,
        { label: "Cabin", value: cabin, abbreviated: cabin ? cabinOnPhone(cabin) : null, source: "booking" } satisfies Fact,
      ];
    })();

  const planeShown = state !== "cancelled";
  const progress = !planeShown ? null : state === "landed" || state === "in-the-air" || state === "diverted" ? flightProgress(s, now, st, online) : 0;

  const lead = [number || "Flight", `${city(origin)} to ${city(destination)}`];
  const tail = (() => {
    if (noLive) return "scheduled, no live status yet";
    switch (state) {
      case "scheduled": return `scheduled, departs ${shortDay(depLocal)} at ${depart.time}`;
      case "boarding": return `boarding at gate ${gate}, departs ${depart.time}`;
      case "delayed": return `${lateBy ? `delayed ${plural(lateBy, "minute")}, now` : "delayed, now"} departs ${depart.time}`;
      case "in-the-air": return `in the air, lands ${arrive.time}${lands >= MINUTE_MS ? ` in ${inWords(lands)}` : ""}`;
      case "landed": return `landed ${landedOn}${arrive.time}${early ? `, ${early}` : ""}`;
      case "cancelled": return "cancelled";
      case "diverted": return `diverted, expected to land ${arrive.time}`;
    }
  })();

  return {
    state, noLive, pill, number, carrier: number.slice(0, 2), provider, duration, origin, destination, depart, arrive, updated, sentence,
    side: arrivalSide ? "Arrival" : "Departure", sideCode: arrivalSide ? destination : origin, facts, progress, name: [...lead, tail].join(", "),
  };
}

const ARC = { x0: 2, x1: 50, x2: 98, y0: 38, y1: -16, y2: 38, height: 40, pixels: 46 };

export function arcPoint(progress: number): { left: number; top: number } {
  const t = Math.min(1, Math.max(0, progress));
  const a = (1 - t) * (1 - t), b = 2 * t * (1 - t), c = t * t;
  return { left: a * ARC.x0 + b * ARC.x1 + c * ARC.x2, top: (a * ARC.y0 + b * ARC.y1 + c * ARC.y2) * (ARC.pixels / ARC.height) };
}

export function arcHeading(progress: number, width: number): number {
  const t = Math.min(1, Math.max(0, progress));
  const dx = 2 * (1 - t) * (ARC.x1 - ARC.x0) + 2 * t * (ARC.x2 - ARC.x1);
  const dy = 2 * (1 - t) * (ARC.y1 - ARC.y0) + 2 * t * (ARC.y2 - ARC.y1);
  return Math.round((Math.atan2(dy * (ARC.pixels / ARC.height), dx * (width / 100)) * 180) / Math.PI);
}

export function arcTravelled(progress: number): string {
  const t = Math.min(1, Math.max(0, progress));
  const a = (1 - t) * (1 - t), b = 2 * t * (1 - t), c = t * t;
  const round = (n: number) => Math.round(n * 100) / 100;
  const end = { x: a * ARC.x0 + b * ARC.x1 + c * ARC.x2, y: a * ARC.y0 + b * ARC.y1 + c * ARC.y2 };
  return `M${ARC.x0} ${ARC.y0} Q${round(ARC.x0 + t * (ARC.x1 - ARC.x0))} ${round(ARC.y0 + t * (ARC.y1 - ARC.y0))} ${round(end.x)} ${round(end.y)}`;
}
