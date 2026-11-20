import type { Segment } from "./api-types";
import { LIVE_STATUS_STARTS_DAYS, minutesBetween, shortDay, type FlightCardView } from "./flightcard";
import { instant } from "./trips";

export type HeroTone = "primary" | "success" | "signal";
export type HeroTop = { text: string; tone: HeroTone; pill: boolean; plane: boolean; dot: boolean };
export type HeroFact = { label: string; value: string | null; mono: boolean };
export type HeroSeat = { name: string; initials: string; seat: string };
export type HeroQuiet = { late: string; struck: string | null; text: string; onTime: boolean };
export type HeroView = {
  carrierLine: string;
  top: HeroTop | null;
  sentence: string;
  big: string;
  bigTime: string;
  quiet: HeroQuiet;
  facts: HeroFact[];
  seats: HeroSeat[];
  landed: boolean;
  cancelled: boolean;
  was: string | null;
};

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

export function heroView(v: FlightCardView, segment: Segment, city: (code: string) => string, now: number, travellers = false): HeroView {
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
        return v.live ? { late: "", struck: null, text: shortDay(v.depart.local), onTime: true } : { late: "", struck: null, text: `${shortDay(v.depart.local)} · Times from your booking.`, onTime: false };
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

  const seats: HeroSeat[] = travellers ? segment.travelers.flatMap((t) => (t.seat ? [{ name: t.name, initials: initialsOf(t.name), seat: t.seat }] : [])) : [];

  const was = v.divertedTo ? segment.destination ?? null : null;
  return { carrierLine, top, sentence, big, bigTime, quiet, facts, seats: seats.length > 1 ? seats : [], landed: arrived, cancelled: v.state === "cancelled", was };
}
