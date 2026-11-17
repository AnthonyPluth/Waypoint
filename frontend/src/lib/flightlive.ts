import type { Segment } from "./api-types";
import { flightCardView, inWords, lateWords, minutesBetween, shortDay, wallClock, type FlightCardInput, type FlightCardView } from "./flightcard";
import { instant } from "./trips";

const MINUTE_MS = 60_000;
const HOUR_MS = 3_600_000;
const DAY_MS = 86_400_000;

export type Dot = "done" | "now" | "next";
export type Step = { title: string; note: string; when: string; at: string; dot: Dot; later?: string; laterWords?: string };
export type SeatRow = { name: string; first: string; seat: string; cabin: string };

export type FlightLiveView = {
  card: FlightCardView;
  headline: string;
  detailPhone: string;
  detailDesktop: string;
  steps: Step[];
  facts: FlightCardView["facts"];
  note: string;
  seats: SeatRow[];
  title: string;
  scheduledDepart: string;
  scheduledArrive: string;
  percent: number | null;
  updated: string;
};

const plural = (n: number, word: string): string => `${n} ${word}${n === 1 ? "" : "s"}`;

export function awayWords(ms: number): string {
  if (ms < DAY_MS) return inWords(ms);
  const days = Math.floor(ms / DAY_MS);
  const hours = Math.floor((ms % DAY_MS) / HOUR_MS);
  return hours ? `${plural(days, "day")} ${plural(hours, "hour")}` : plural(days, "day");
}

export function timeLeft(ms: number): string {
  const minutes = Math.max(1, Math.round(ms / MINUTE_MS));
  const hours = Math.floor(minutes / 60);
  if (!hours) return `${minutes} m`;
  return minutes % 60 ? `${hours} h ${minutes % 60} m` : `${hours} h`;
}

function seatRows(s: Segment): SeatRow[] {
  const cabin = s.details.cabin?.trim() ?? "";
  const named = s.travelers.filter((t) => t.name);
  const booked = s.details.seat?.trim() ?? "";
  return named.map((t) => ({ name: t.name, first: t.name.split(/\s+/)[0], seat: t.seat?.trim() || (named.length === 1 ? booked : ""), cabin }));
}

export function flightLiveView(input: FlightCardInput): FlightLiveView {
  const card = flightCardView(input);
  const { segment: s, now, city } = input;
  const st = card.live;
  const { state } = card;
  const toDepart = card.depAt - now;
  const toLand = card.arrAt - now;
  const gate = card.facts.find((f) => f.label === "Gate")?.value ?? null;
  const origin = city(card.origin);
  const destination = city(card.destination);

  const scheduledDepart = wallClock(st?.dep_scheduled ?? s.start_local);
  const scheduledArrive = wallClock(st?.arr_scheduled ?? s.end_local);

  const arrivedBy = st?.arr_actual
    ? lateWords(minutesBetween(instant(st.arr_actual, st.arr_zone), instant(st.arr_scheduled ?? s.end_local, st.arr_scheduled ? st.arr_zone : s.end_zone)))
    : "";

  const headline = (() => {
    switch (state) {
      case "scheduled":
      case "delayed": return toDepart >= MINUTE_MS ? `Departs in ${awayWords(toDepart)}` : "Departing now";
      case "boarding": return gate ? `Boarding now at gate ${gate}` : "Boarding now";
      case "in-the-air": return toLand >= MINUTE_MS ? `Landing in ${inWords(toLand)}` : "Landing now";
      case "landed": return arrivedBy ? `Landed ${arrivedBy}` : "Landed";
      case "cancelled": return "Cancelled";
      case "diverted": return "Diverted";
    }
  })();

  const departed = st?.dep_actual
    ? `Departed ${lateWords(minutesBetween(instant(st.dep_actual, st.dep_zone), instant(st.dep_scheduled ?? s.start_local, st.dep_scheduled ? st.dep_zone : s.start_zone)))}.`
    : "";
  const expectedLate = state === "in-the-air" && st?.arr_estimated && st.arr_scheduled
    ? `Expected to land ${lateWords(minutesBetween(instant(st.arr_estimated, st.arr_zone), instant(st.arr_scheduled, st.arr_zone)))}.`
    : "";
  const expectedAt = state === "in-the-air" && toLand >= MINUTE_MS ? `Expected ${card.arrive.time}${card.arrive.zoneName ? ` ${card.arrive.zoneName}` : ""} at ${destination}.` : "";
  const airborne = state === "in-the-air";
  const detailPhone = airborne ? [expectedAt, departed].filter(Boolean).join(" ") : state === "landed" ? "" : card.sentence;
  const detailDesktop = airborne ? [departed, expectedLate].filter(Boolean).join(" ") : detailPhone;

  const departStep = (title: string, dot: Dot): Step => ({ title, note: `Scheduled ${scheduledDepart}`, when: card.depart.time, at: card.depart.local, dot });
  const landStep = (title: string, dot: Dot): Step => ({ title, note: `Scheduled ${scheduledArrive}`, when: card.arrive.time, at: card.arrive.local, dot, later: card.arrive.later, laterWords: card.arrive.laterWords });
  const inTheAir = (): Step => ({ title: "In the air", note: toLand >= MINUTE_MS ? `${timeLeft(toLand)} flight time left` : "Landing now", when: "now", at: "", dot: "now" });
  const steps: Step[] = (() => {
    switch (state) {
      case "scheduled":
      case "delayed": return [departStep(`Departs ${origin}`, "next"), landStep(`Lands in ${destination}`, "next")];
      case "boarding": return [departStep(`Departs ${origin}`, "now"), landStep(`Lands in ${destination}`, "next")];
      case "in-the-air": return [departStep(`Departed ${origin}`, "done"), inTheAir(), landStep(`Lands in ${destination}`, "next")];
      case "landed": return [departStep(`Departed ${origin}`, "done"), landStep(`Landed in ${destination}`, "done")];
      case "cancelled": return [
        { title: `Was due to depart ${origin}`, note: `Scheduled ${scheduledDepart}`, when: "", at: "", dot: "next" },
        { title: `Was due to land in ${destination}`, note: `Scheduled ${scheduledArrive}`, when: "", at: "", dot: "next" },
      ];
      case "diverted": return [departStep(`Departed ${origin}`, "done"), inTheAir(), ...(card.divertedTo ? [landStep(`Lands in ${destination}`, "next")] : [])];
    }
  })();

  return {
    card, headline, detailPhone, detailDesktop, steps, scheduledDepart, scheduledArrive,
    facts: card.facts.filter((f) => !["Seat", "Seats", "Cabin"].includes(f.label)),
    note: airborne && card.side === "Arrival" ? "The belt appears after landing." : "",
    seats: seatRows(s),
    title: [card.provider, s.start_local ? shortDay(s.start_local) : ""].filter(Boolean).join(" · "),
    percent: card.progress === null ? null : Math.round(card.progress * 100),
    updated: card.updated === "Updated just now" ? "Updated less than a minute ago" : card.updated ?? "",
  };
}
