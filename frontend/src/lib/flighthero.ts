import type { Segment } from "./api-types";
import { LIVE_STATUS_STARTS_DAYS, minutesBetween, shortDay, stamp, type FlightCardView, type Stamp } from "./flightcard";
import { instant, membershipFor } from "./trips";

export type HeroTone = "primary" | "success" | "signal";
export type HeroTop = { text: string; tone: HeroTone; pill: boolean; plane: boolean; dot: boolean };
export type HeroFact = { label: string; value: string | null; mono: boolean };
export type HeroSeat = { name: string; initials: string; seat: string | null; unmatched: boolean };
export type HeroQuiet = { late: string; struck: string | null; text: string; onTime: boolean };
export type HeroLeg = { segment: Segment; view: FlightCardView };
export type HeroConnection = { legs: HeroLeg[]; index: number };
export type HeroStage = "before" | "during";
export type HeroRoute = { origin: string; depart: Stamp; destination: string; arrive: Stamp };
export type HeroArc = { progress: number | null; stops: number[]; note: string | null };
export type HeroThen = { label: string; number: string; text: string; time: string; terminal: string | null; connect: string | null; hurry: boolean; late: boolean };
export type HeroView = {
  carrierLine: string;
  top: HeroTop | null;
  sentence: string;
  big: string;
  bigTime: string;
  quiet: HeroQuiet;
  facts: HeroFact[];
  seats: HeroSeat[];
  nobody: boolean;
  landed: boolean;
  cancelled: boolean;
  was: string | null;
  route: HeroRoute;
  arc: HeroArc;
  then: HeroThen | null;
  stage: HeroStage | null;
};

export const SHORT_CONNECTION_MINUTES = 45;

const DAY_MS = 86_400_000;
const HOUR_MS = 3_600_000;
const MINUTE_MS = 60_000;

export const upper = (time: string): string => time.replace(/\b([ap])m\b/, (_, half: string) => `${half.toUpperCase()}M`);

export function countdown(ms: number): string {
  if (ms >= DAY_MS) {
    const days = Math.floor(ms / DAY_MS);
    return `In ${days} ${days === 1 ? "day" : "days"}`;
  }
  if (ms >= HOUR_MS) {
    const hours = Math.floor(ms / HOUR_MS);
    return `In ${hours} ${hours === 1 ? "hour" : "hours"}`;
  }
  return `In ${Math.max(1, Math.round(ms / MINUTE_MS))} min`;
}

export function timeLeft(ms: number): string {
  const minutes = Math.round(ms / MINUTE_MS);
  if (minutes < 1) return "Landing";
  const hours = Math.floor(minutes / 60);
  if (!hours) return `${minutes} min left`;
  return `${hours} h ${String(minutes % 60).padStart(2, "0")} m left`;
}

export function earlyLate(minutes: number): { text: string; tone: HeroTone } {
  if (minutes === 0) return { text: "On time", tone: "success" };
  return minutes < 0 ? { text: `${-minutes} min early`, tone: "success" } : { text: `${minutes} min late`, tone: "signal" };
}

const longUpdated = (updated: string | null): string | null => (updated ? updated.replace(/(\d+) min ago/, (_, n: string) => `${n} ${n === "1" ? "minute" : "minutes"} ago`) : null);

export function seatsValue(seats: string[]): string {
  return seats.length > 2 ? `${seats[0]} +${seats.length - 1}` : seats.join(", ");
}

const initialsOf = (name: string): string => name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");

const waitWords = (ms: number): string => {
  const minutes = Math.max(0, Math.round(ms / MINUTE_MS));
  const hours = Math.floor(minutes / 60);
  return hours ? `${hours} h ${String(minutes % 60).padStart(2, "0")} min` : `${minutes} min`;
};

export function connectionStage(c: HeroConnection | null | undefined): HeroStage | null {
  if (!c || c.legs.length < 2 || c.index < 0 || c.index >= c.legs.length) return null;
  if (c.legs.some((l) => l.view.state === "cancelled" || l.view.state === "diverted")) return null;
  if (c.legs[c.index].view.state !== "scheduled") return null;
  if (c.index === 0) return "before";
  return c.legs[c.index - 1].view.state === "landed" ? "during" : null;
}

export function stopPositions(legs: FlightCardView[]): number[] {
  const stops = legs.length - 1;
  if (stops !== 1) return Array.from({ length: stops }, (_, i) => (i + 1) / legs.length);
  const [first, second] = legs.map((l) => Math.max(1, l.arrAt - l.depAt));
  return [Math.min(0.7, Math.max(0.3, first / (first + second)))];
}

function overConnection(base: HeroView, c: HeroConnection, stage: HeroStage, city: (code: string) => string, now: number): HeroView {
  const { legs, index } = c;
  const here = legs[index].view;
  const last = legs[legs.length - 1].view;
  const first = legs[0];
  const stops = legs.slice(0, -1).map((l) => l.view.destination);
  const positions = stopPositions(legs.map((l) => l.view));
  const where = city(last.destination) || last.destination;
  const route: HeroRoute = {
    origin: first.view.origin, depart: first.view.depart, destination: last.destination,
    arrive: stamp(last.arrive.local, last.arrive.zone, last.arrive.tone, last.arrive.original, first.segment.start_local),
  };
  if (stage === "before") {
    const next = legs[index + 1].view;
    const wait = Math.max(0, next.depAt - here.arrAt);
    return {
      ...base, stage, sentence: `Your flights to ${where}`, route,
      arc: { progress: base.arc.progress, stops: positions, note: `${stops.length} ${stops.length === 1 ? "stop" : "stops"}, ${stops.join(", ")}` },
      then: { label: `Then, at ${here.destination}`, number: next.number || "Flight", text: "departs", time: upper(next.depart.time), terminal: next.facts.find((f) => f.label === "Terminal")?.value ?? null,
              connect: waitWords(wait), hurry: wait < SHORT_CONNECTION_MINUTES * MINUTE_MS, late: next.state === "delayed" },
    };
  }
  const earlier = legs[index - 1].view;
  const note = base.quiet.text.includes(" · ") ? base.quiet.text.slice(base.quiet.text.indexOf(" · ") + 3) : "";
  return {
    ...base, stage, sentence: `Your connection to ${where}`, route,
    top: { text: `Departs in ${waitWords(here.depAt - now)}`, tone: "primary", pill: false, plane: false, dot: false },
    quiet: { ...base.quiet, text: [`Leg ${index + 1} of ${legs.length}`, note].filter(Boolean).join(" · ") },
    arc: { progress: positions[index - 1], stops: positions, note: `At ${earlier.destination}` },
    then: { label: "Earlier", number: earlier.number || "Flight", text: `landed at ${earlier.destination}`, time: upper(earlier.arrive.time), terminal: null, connect: null, hurry: false, late: false },
  };
}

export function heroView(v: FlightCardView, segment: Segment, city: (code: string) => string, now: number, travellers = false, connection: HeroConnection | null = null): HeroView {
  const where = city(v.destination) || v.destination;
  const carrierLine = [v.provider, v.number].filter(Boolean).join(" ") || "Flight";
  const arrived = v.state === "landed";
  const actual = v.live?.arr_actual ?? null;
  const scheduled = v.live?.arr_scheduled ?? null;
  const arrZone = v.live?.arr_zone ?? segment.end_zone;
  const landedBy = arrived && actual ? minutesBetween(instant(actual, arrZone), instant(scheduled ?? segment.end_local, scheduled ? arrZone : segment.end_zone)) : null;
  const updated = longUpdated(v.updated);

  const top: HeroTop | null = (() => {
    switch (v.state) {
      case "boarding": return { text: "Boarding", tone: "primary", pill: false, plane: false, dot: true };
      case "delayed": return { text: "Delayed", tone: "signal", pill: true, plane: false, dot: false };
      case "cancelled": return { text: "Cancelled", tone: "signal", pill: true, plane: false, dot: false };
      case "diverted": return { text: "Diverted", tone: "signal", pill: true, plane: false, dot: false };
      case "in-the-air": return { text: timeLeft(v.arrAt - now), tone: "primary", pill: false, plane: true, dot: false };
      case "landed": return landedBy === null ? null : { ...earlyLate(landedBy), pill: false, plane: false, dot: false };
      default: return { text: countdown(v.depAt - now), tone: "primary", pill: false, plane: false, dot: false };
    }
  })();

  const sentence = (() => {
    switch (v.state) {
      case "boarding": return `Boarding now, to ${where}`;
      case "in-the-air": return `In the air to ${where}`;
      case "landed": return `You are in ${where}`;
      case "diverted": return v.divertedTo ? `Diverted to ${city(v.divertedTo) || v.divertedTo}` : "Diverted";
      default: return `Your flight to ${where}`;
    }
  })();

  const big = (() => {
    switch (v.state) {
      case "in-the-air":
      case "diverted": return `Lands ${upper(v.arrive.time)}`;
      case "landed": return `Landed ${upper(v.arrive.time)}`;
      case "cancelled": return "Cancelled";
      default: return `Departs ${upper(v.depart.time)}`;
    }
  })();
  const bigTime = big.startsWith("Cancelled") ? "" : upper(big.split(" ").slice(1).join(" "));

  const delay = v.live?.delay_minutes ?? null;
  const quiet: HeroQuiet = (() => {
    switch (v.state) {
      case "delayed": return { late: delay ? `${delay} min late` : "Running late", struck: v.depart.original ? upper(v.depart.original) : null, text: "", onTime: false };
      case "scheduled": {
        if (v.noLive) return { late: "", struck: null, text: `${shortDay(v.depart.local)} · Times from your booking. Live status starts ${LIVE_STATUS_STARTS_DAYS} ${LIVE_STATUS_STARTS_DAYS === 1 ? "day" : "days"} before.`, onTime: false };
        if (v.live) return { late: "", struck: null, text: shortDay(v.depart.local), onTime: true };
        const cached = v.facts.some((f) => f.source === "live" && f.value);
        return { late: "", struck: null, text: `${shortDay(v.depart.local)} · ${cached && updated ? updated : "Times from your booking."}`, onTime: false };
      }
      case "boarding": return { late: "", struck: null, text: shortDay(v.depart.local), onTime: true };
      case "cancelled": return { late: "", struck: null, text: v.sentence, onTime: false };
      case "diverted": return { late: "", struck: null, text: [v.divertedTo ? `Was headed to ${city(segment.destination ?? "") || segment.destination}` : "Where it lands isn’t known yet.", updated].filter(Boolean).join(" · "), onTime: false };
      default: return { late: "", struck: null, text: updated ?? `${shortDay(v.arrive.local)} · Times from your booking.`, onTime: false };
    }
  })();

  const seat = v.facts.find((f) => f.label === "Seat" || f.label === "Seats");
  const seatList = (seat?.value ?? "").split(",").map((x) => x.trim()).filter(Boolean);
  const names = v.state === "in-the-air" || arrived || v.state === "diverted" ? ["Arrival term", "Arrival gate", "Bag claim"] : [];
  const facts: HeroFact[] = v.facts.slice(0, 3).map((f, i) => (f === seat
    ? { label: f.label, value: seatList.length ? seatsValue(seatList) : null, mono: true }
    : { label: names[i] ?? f.label, value: f.value, mono: false }));

  const seats: HeroSeat[] = travellers ? segment.travelers.map((t) => ({ name: t.name, initials: initialsOf(t.name), seat: t.seat, unmatched: membershipFor(segment, t, [])?.state === "unmatched" })) : [];

  const was = v.divertedTo ? segment.destination ?? null : null;
  const plain: HeroView = {
    carrierLine, top, sentence, big, bigTime, quiet, facts, seats, nobody: travellers && segment.travelers.length === 0, landed: arrived, cancelled: v.state === "cancelled", was,
    route: { origin: v.origin, depart: v.depart, destination: v.destination, arrive: v.arrive }, arc: { progress: v.progress, stops: [], note: null }, then: null, stage: null,
  };
  const stage = connectionStage(connection);
  return connection && stage ? overConnection(plain, connection, stage, city, now) : plain;
}
