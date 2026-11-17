// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import { createRawSnippet } from "svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));

import { api } from "$lib/api";
import { forgetAirportZones } from "$lib/airport-zones";
import type { FlightStatus, Segment } from "$lib/api-types";
import { arcPoint, arcTravelled, BOARDING_MINUTES, LIVE_STATUS_STARTS_DAYS } from "$lib/flightcard";
import { instant } from "$lib/trips";
import { segment } from "../../test/fixtures";
import FlightCard from "./FlightCard.svelte";

const DEN = "America/Denver";
const AIRPORTS: Record<string, object> = {
  DEN: { code: "DEN", name: "Denver International Airport", city: "Denver", country: "US", zone: DEN },
  GJT: { code: "GJT", name: "Grand Junction Regional Airport", city: "Grand Junction", country: "US", zone: DEN },
  MTJ: { code: "MTJ", name: "Montrose Regional Airport", city: "Montrose", country: "US", zone: DEN },
  JFK: { code: "JFK", name: "John F. Kennedy International Airport", city: "New York", country: "US", zone: "America/New_York" },
  LHR: { code: "LHR", name: "Heathrow Airport", city: "London", country: "GB", zone: "Europe/London" },
};

const booked = segment({
  id: 3, provider: "Example Air", origin: "DEN", destination: "GJT", start_local: "2025-06-12T09:40", start_zone: DEN, end_local: "2025-06-12T10:52", end_zone: DEN,
  details: { flight_number: "EA 214", cabin: "Economy" }, travelers: [{ id: 1, person_id: null, name: "Jane Doe", seat: "12A" }],
});
const at = (local: string) => instant(local, DEN);
const status = (now: number, minutesAgo: number, extra: Partial<FlightStatus> = {}): FlightStatus => ({
  segment_id: 3, state: "scheduled", origin: "DEN", destination: "GJT", dep_scheduled: "2025-06-12T09:40", dep_estimated: null, dep_actual: null, dep_zone: DEN,
  dep_terminal: null, dep_gate: null, arr_scheduled: "2025-06-12T10:52", arr_estimated: null, arr_actual: null, arr_zone: DEN, arr_terminal: null, arr_gate: null,
  delay_minutes: null, fetched_at: new Date(now - minutesAgo * 60_000).toISOString(), ...extra,
});

type Case = { name: string; now: number; status?: FlightStatus; label: string; pill: string | null; sentence: string; times: [string, string]; facts: [string, string][]; updated: string | null };
const mk = (now: number, minutesAgo: number, extra: Partial<FlightStatus>) => status(now, minutesAgo, extra);
const NOW = {
  scheduled: at("2025-06-09T08:00"), boarding: at("2025-06-12T09:15"), delayed: at("2025-06-12T08:50"), air: at("2025-06-12T10:14"),
  landed: at("2025-06-12T10:55"), cancelled: at("2025-06-12T08:30"), diverted: at("2025-06-12T10:20"), none: at("2025-06-02T08:00"),
};
const CASES: Case[] = [
  { name: "scheduled", now: NOW.scheduled, status: mk(NOW.scheduled, 4, { dep_terminal: "B" }), label: "EA 214, Denver to Grand Junction, scheduled, departs Thu Jun 12 at 9:40 am",
    pill: "Scheduled", sentence: "", times: ["9:40 am", "10:52 am"], updated: "Updated 4 min ago",
    facts: [["Terminal", "B"], ["Gate", "—Not known yet"], ["Seat", "12A"], ["Cabin", "Economy"]] },
  { name: "boarding", now: NOW.boarding, status: mk(NOW.boarding, 2, { dep_terminal: "B", dep_gate: "B14" }), label: "EA 214, Denver to Grand Junction, boarding at gate B14, departs 9:40 am",
    pill: "Boarding", sentence: "", times: ["9:40 am", "10:52 am"], updated: "Updated 2 min ago",
    facts: [["Terminal", "B"], ["Gate", "B14"], ["Seat", "12A"], ["Cabin", "Economy"]] },
  { name: "delayed", now: NOW.delayed, label: "EA 214, Denver to Grand Junction, delayed 35 minutes, now departs 10:15 am",
    status: mk(NOW.delayed, 4, { state: "delayed", dep_estimated: "2025-06-12T10:15", arr_estimated: "2025-06-12T11:27", dep_terminal: "B", dep_gate: "B14", delay_minutes: 35 }),
    pill: "Delayed 35 min", sentence: "", times: ["Originally 9:40 am 10:15 am", "Originally 10:52 am 11:27 am"], updated: "Updated 4 min ago",
    facts: [["Terminal", "B"], ["Gate", "B14"], ["Seat", "12A"], ["Cabin", "Economy"]] },
  { name: "in the air", now: NOW.air, label: "EA 214, Denver to Grand Junction, in the air, lands 10:52 am in 38 minutes",
    status: mk(NOW.air, 1, { state: "departed", dep_actual: "2025-06-12T09:46", arr_estimated: "2025-06-12T10:52", arr_terminal: "1", arr_gate: "A3" }),
    pill: "In the air", sentence: "Lands in 38 minutes.", times: ["9:46 am", "10:52 am"], updated: "Updated 1 min ago",
    facts: [["Terminal", "1"], ["Gate", "A3"], ["Belt", "—Not known yet"], ["Seat", "12A"]] },
  { name: "landed", now: NOW.landed, label: "EA 214, Denver to Grand Junction, landed 10:49 am, 3 minutes early",
    status: mk(NOW.landed, 1, { state: "landed", dep_actual: "2025-06-12T09:46", arr_actual: "2025-06-12T10:49", arr_terminal: "1", arr_gate: "A3" }),
    pill: "Landed", sentence: "3 minutes early.", times: ["9:46 am", "10:49 am"], updated: "Updated 1 min ago",
    facts: [["Terminal", "1"], ["Gate", "A3"], ["Belt", "—Not known yet"], ["Seat", "12A"]] },
  { name: "cancelled", now: NOW.cancelled, status: mk(NOW.cancelled, 12, { state: "cancelled", dep_gate: "B14" }), label: "EA 214, Denver to Grand Junction, cancelled",
    pill: "Cancelled", sentence: "Contact Example Air about rebooking.", times: ["9:40 am", "10:52 am"], updated: "Updated 12 min ago",
    facts: [["Terminal", "—Not known yet"], ["Gate", "—Not known yet"], ["Seat", "12A"], ["Cabin", "Economy"]] },
  { name: "diverted", now: NOW.diverted, label: "EA 214, Denver to Montrose, diverted, expected to land 10:41 am",
    status: mk(NOW.diverted, 3, { state: "diverted", destination: "MTJ", dep_actual: "2025-06-12T09:46", arr_estimated: "2025-06-12T10:41", arr_gate: "C2" }),
    pill: "Diverted", sentence: "Was headed to Grand Junction.", times: ["9:46 am", "10:41 am"], updated: "Updated 3 min ago",
    facts: [["Terminal", "—Not known yet"], ["Gate", "—Not known yet"], ["Belt", "—Not known yet"], ["Seat", "12A"]] },
  { name: "scheduled with no live data", now: NOW.none, label: "EA 214, Denver to Grand Junction, scheduled, no live status yet", pill: null,
    sentence: "Live status starts 1 day before departure. Until then these are the times on your booking.", times: ["9:40 am", "10:52 am"], updated: null,
    facts: [["Terminal", "—Not known yet"], ["Gate", "—Not known yet"], ["Seat", "12A"], ["Cabin", "Economy"]] },
];

const draw = (c: { segment?: Segment; now: number; status?: FlightStatus }, extra: Record<string, unknown> = {}) =>
  render(FlightCard, { segment: c.segment ?? booked, status: c.status, liveOn: true, now: c.now, ...extra });
const times = (card: HTMLElement) => [...card.querySelectorAll("[data-code]")].map((code) => {
  const spans = code.parentElement?.querySelectorAll("span.font-mono") ?? [];
  return [spans[0]?.querySelector("s")?.textContent, spans[0]?.querySelector("time")?.textContent, spans[1]?.textContent].filter(Boolean).join(" ").replace(/\s+/g, " ");
});
const facts = (card: HTMLElement) => [...card.querySelectorAll("[data-facts] > div")].map((f) => [f.querySelector("dt")?.textContent?.trim(), f.querySelector("dd")?.textContent?.replace(/\s+/g, " ").trim()]);

beforeEach(() => {
  forgetAirportZones();
  vi.mocked(api).mockReset().mockImplementation(async (path: string) => {
    const found = AIRPORTS[path.split("/").pop() ?? ""];
    if (!found) throw new Error("No such airport");
    return found;
  });
});

describe("the flight card in eight states", () => {
  it.each(CASES)("shows $name", async (c) => {
    draw(c);
    const card = await screen.findByRole("article", { name: c.label });
    expect(card).toBeInTheDocument();
    if (c.pill) expect(within(card).getByText(c.pill)).toBeInTheDocument();
    else expect(card.querySelector("[data-tone]")).toBeNull();
    if (c.sentence) expect(within(card).getByText(c.sentence)).toBeInTheDocument();
    else expect(card.querySelector("[data-sentence]")).toBeNull();
    expect(times(card)).toEqual(c.times.map((t) => `${t} MDT`));
    expect(facts(card)).toEqual(c.facts.map(([label, value]) => [label, value]));
    if (c.updated) expect(within(card).getByText(c.updated)).toBeInTheDocument();
    else expect(card.textContent).not.toMatch(/Updated/);
  });

  it("never repeats the state, the time or the gate in a sentence", async () => {
    for (const c of CASES.slice(0, 3)) {
      const { unmount } = draw(c);
      expect((await screen.findByRole("article")).querySelector("[data-sentence]")).toBeNull();
      unmount();
    }
  });

  it("puts the date of the side it shows in the eyebrow when that is not today, and nothing when it is", async () => {
    draw(CASES[0]);
    await waitFor(() => expect(screen.getByRole("article").querySelector(".eyebrow")).toHaveTextContent("Departure · Denver · Thu Jun 12"));
  });

  it("uses the tones of the status chip: quiet, info, warn, ok and bad", () => {
    const tone = (c: Case) => { const { container, unmount } = draw(c); const chip = container.querySelector("[data-tone]")?.getAttribute("data-tone"); unmount(); return chip; };
    expect(CASES.slice(0, 7).map(tone)).toEqual(["quiet", "info", "warn", "info", "ok", "bad", "bad"]);
  });

  it("is an article, not a link or a button, until the live status view exists", async () => {
    draw(CASES[0]);
    const card = await screen.findByRole("article");
    expect(card.tagName).toBe("ARTICLE");
    expect(within(card).queryByRole("link")).toBeNull();
    expect(within(card).queryByRole("button")).toBeNull();
  });
});

describe("times", () => {
  it("strikes the original through above the new one in amber, and reads it as Originally", async () => {
    draw(CASES[2]);
    const card = await screen.findByRole("article");
    const [dep, arr] = [...card.querySelectorAll("[data-code]")].map((code) => code.parentElement?.querySelector("span.font-mono") as HTMLElement);
    expect(dep).toHaveClass("text-signal-ink");
    expect(dep.querySelector("s")).toHaveTextContent("Originally 9:40 am");
    expect(dep.querySelector("s")?.querySelector(".sr-only")).toHaveTextContent("Originally");
    expect(dep.querySelector("time")).toHaveTextContent("10:15 am");
    expect(arr.querySelector("s")).toHaveTextContent("Originally 10:52 am");
    expect(arr.querySelector("time")).toHaveTextContent("11:27 am");
  });

  it("strikes a cancelled flight’s times and leaves them grey", async () => {
    draw(CASES[5]);
    const card = await screen.findByRole("article");
    const [dep] = [...card.querySelectorAll("[data-code]")].map((code) => code.parentElement?.querySelector("span.font-mono") as HTMLElement);
    expect(dep).toHaveClass("line-through", "text-muted-foreground");
  });

  it("shows each time at its own airport with its zone, never converted, and says when the arrival is a day later", async () => {
    const overnight = segment({ id: 4, provider: "American Airlines", origin: "JFK", destination: "LHR", start_local: "2026-11-20T19:00", start_zone: "America/New_York", end_local: "2026-11-21T07:10", end_zone: "Europe/London", details: { flight_number: "AA 101" } });
    draw({ segment: overnight, now: instant("2026-11-20T12:00", "America/New_York") });
    const card = await screen.findByRole("article", { name: /^AA 101, New York to London, scheduled, departs Fri Nov 20 at 7:00 pm$/ });
    expect(times(card)).toEqual(["7:00 pm EST", "7:10 am GMT · +1 day, 1 day later on the calendar than departure"]);
    expect(within(card).getByText(/, 1 day later on the calendar than departure/)).toHaveClass("sr-only");
  });

  it("puts each time in a time element with its wall-clock value", async () => {
    draw(CASES[0]);
    const card = await screen.findByRole("article");
    expect([...card.querySelectorAll("time")].map((t) => t.getAttribute("datetime"))).toEqual(["2025-06-12T09:40", "2025-06-12T10:52"]);
  });
});

describe("the four facts", () => {
  it("marks each as from live status or from the booking, with names a reader hears", async () => {
    draw(CASES[0]);
    const card = await screen.findByRole("article");
    const rows = [...card.querySelectorAll("[data-facts] > div")].map((f) => [f.querySelector("dt")?.textContent?.trim(), f.querySelector("dt [role='img']")?.getAttribute("aria-label")]);
    expect(rows).toEqual([["Terminal", "From live status"], ["Gate", "From live status"], ["Seat", "From the booking"], ["Cabin", "From the booking"]]);
    expect(within(card).getAllByRole("img", { name: "From live status" })).toHaveLength(2);
    expect(within(card).getAllByRole("img", { name: "From the booking" })).toHaveLength(2);
  });

  it("takes the arrival side in the air and once landed, and the departure side before", async () => {
    for (const [c, side, labels] of [[CASES[0], "Departure · Denver", "Terminal Gate Seat Cabin"], [CASES[3], "Arrival · Grand Junction", "Terminal Gate Belt Seat"], [CASES[4], "Arrival · Grand Junction", "Terminal Gate Belt Seat"]] as const) {
      const { unmount } = draw(c);
      const card = await screen.findByRole("article");
      await waitFor(() => expect(card.querySelector(".eyebrow")).toHaveTextContent(side));
      expect(facts(card).map(([label]) => label).join(" ")).toBe(labels);
      unmount();
    }
  });

  it("shows a dash with the hidden words Not known yet for each fact it doesn’t hold, and never leaves a row out", async () => {
    draw(CASES[7]);
    const card = await screen.findByRole("article");
    const unknown = [...card.querySelectorAll("[data-facts] dd")].filter((dd) => dd.textContent?.includes("Not known yet"));
    expect(unknown).toHaveLength(2);
    for (const dd of unknown) {
      expect(dd.querySelector("[aria-hidden='true']")).toHaveTextContent("—");
      expect(dd.querySelector(".sr-only")).toHaveTextContent("Not known yet");
    }
    expect(card.querySelectorAll("[data-facts] > div")).toHaveLength(4);
  });

  it("falls back to the booking’s terminal, marked as from the booking, and to the live one when there is one", async () => {
    const withTerminal = { ...booked, details: { ...booked.details, terminal: "T2" } };
    const { unmount } = draw({ segment: withTerminal, now: NOW.none });
    let card = await screen.findByRole("article");
    const first = card.querySelector("[data-facts] > div");
    expect(first).toHaveTextContent("T2");
    expect(within(first as HTMLElement).getByRole("img", { name: "From the booking" })).toBeInTheDocument();
    unmount();
    draw({ segment: withTerminal, now: NOW.scheduled, status: CASES[0].status });
    card = await screen.findByRole("article");
    expect(card.querySelector("[data-facts] > div")).toHaveTextContent("B");
    expect(within(card.querySelector("[data-facts] > div") as HTMLElement).getByRole("img", { name: "From live status" })).toBeInTheDocument();
  });

  it("spells the cabin out in full at every width", async () => {
    draw(CASES[0]);
    const card = await screen.findByRole("article");
    expect(facts(card)[3]).toEqual(["Cabin", "Economy"]);
    expect(card.querySelector("[data-facts]")).toHaveClass("flex-wrap");
  });

  it("lets a cabin of several words wrap in its column instead of overflowing", async () => {
    draw({ segment: { ...booked, details: { ...booked.details, cabin: "Premium Economy" } }, now: NOW.none });
    const card = await screen.findByRole("article");
    expect(facts(card)[3]).toEqual(["Cabin", "Premium Economy"]);
    const value = card.querySelectorAll("[data-facts] dd")[3];
    expect(value).toHaveClass("break-words");
    expect(value).not.toHaveClass("whitespace-nowrap");
  });

  it("lists every traveller’s seat in order", async () => {
    const two = { ...booked, travelers: [{ id: 1, person_id: null, name: "Jane Doe", seat: "12B" }, { id: 2, person_id: null, name: "Sam Doe", seat: "12A" }] };
    draw({ segment: two, now: NOW.none });
    expect(facts(await screen.findByRole("article"))[2]).toEqual(["Seats", "12A, 12B"]);
  });
});

describe("what the card says without live data", () => {
  it("has no Updated line and no pill, and names the window as a constant", async () => {
    expect(LIVE_STATUS_STARTS_DAYS).toBe(1);
    draw(CASES[7]);
    const card = await screen.findByRole("article");
    expect(card.querySelector("[data-updated]")).toBeNull();
    expect(card.querySelector("[data-tone]")).toBeNull();
    expect(within(card).getByText(/^Live status starts 1 day before departure\./)).toBeInTheDocument();
  });

  it("says Scheduled instead once the flight is inside the window, with nothing invented", async () => {
    draw({ now: at("2025-06-11T12:00") });
    const card = await screen.findByRole("article");
    expect(within(card).getByText("Scheduled")).toBeInTheDocument();
    expect(card.querySelector("[data-updated]")).toBeNull();
    expect(card.textContent).not.toMatch(/Delayed|Boarding|gate B/);
    expect(facts(card).slice(0, 2)).toEqual([["Terminal", "—Not known yet"], ["Gate", "—Not known yet"]]);
  });

  it("says Scheduled and no window when live status is off", async () => {
    draw({ now: NOW.none }, { liveOn: false });
    const card = await screen.findByRole("article");
    expect(within(card).getByText("Scheduled")).toBeInTheDocument();
    expect(card.querySelector("[data-sentence]")).toBeNull();
    await waitFor(() => expect(card.querySelector(".eyebrow")).toHaveTextContent("Thu Jun 12"));
  });

  it("falls back to the booked times for a flight in the air or landed, with no Updated line", async () => {
    draw({ now: NOW.air });
    let card = await screen.findByRole("article");
    expect(within(card).getByText("In the air")).toBeInTheDocument();
    expect(card.querySelector("[data-updated]")).toBeNull();
    expect(facts(card)[2]).toEqual(["Belt", "—Not known yet"]);
    card.remove();
    draw({ now: NOW.landed });
    card = (await screen.findAllByRole("article")).at(-1) as HTMLElement;
    expect(within(card).getByText("Landed")).toBeInTheDocument();
  });

  it("puts the day on a landed flight from an earlier day", async () => {
    draw({ now: at("2025-06-14T09:00") });
    await waitFor(() => expect(screen.getByRole("article").querySelector(".eyebrow")).toHaveTextContent("Arrival · Grand Junction · Thu Jun 12"));
  });
});

describe("a stored status that is too old to trust", () => {
  it("shows the booked times and sentence, not the old estimate, when it is over three hours old", async () => {
    const old = status(at("2025-06-12T11:00"), 300, { state: "delayed", dep_estimated: "2025-06-12T10:15", arr_estimated: "2025-06-12T11:27", delay_minutes: 35 });
    draw({ now: at("2025-06-12T11:00"), status: old });
    const card = await screen.findByRole("article");
    expect(within(card).getByText("Landed")).toBeInTheDocument();
    expect(times(card)).toEqual(["9:40 am MDT", "10:52 am MDT"]);
    expect(card.textContent).not.toContain("11:27");
    expect(within(card).getByText("Updated 5 h ago")).toBeInTheDocument();
  });

  it("does the same when the device is offline", async () => {
    draw({ now: NOW.delayed, status: CASES[2].status }, { online: false });
    const card = await screen.findByRole("article");
    expect(times(card)).toEqual(["9:40 am MDT", "10:52 am MDT"]);
    expect(card.textContent).not.toMatch(/Originally|Delayed/);
    expect(facts(card).slice(0, 2)).toEqual([["Terminal", "B"], ["Gate", "B14"]]);
    expect(within(card).getByText("Updated 4 min ago")).toBeInTheDocument();
  });
});

describe("when live updates are paused", () => {
  it("says so in one quiet line, with or without a stored status, and says nothing otherwise", async () => {
    const until = new Date(Date.UTC(2025, 5, 13, 15, 30)).toISOString();
    const first = draw(CASES[0], { paused: { until, reason: "rate" } });
    let card = await screen.findByRole("article");
    expect(card.querySelector("[data-paused]")).toHaveAttribute("role", "status");
    expect(card.querySelector("[data-paused]")).toHaveTextContent(/^Live updates paused until .+ \(rate limit\)$/);
    first.unmount();
    draw(CASES[7], { paused: { until, reason: "limit" } });
    card = await screen.findByRole("article");
    expect(card.querySelector("[data-paused]")).toHaveTextContent(/\(monthly limit\)$/);
  });

  it("shows no line when nothing is paused", async () => {
    draw(CASES[0]);
    expect((await screen.findByRole("article")).querySelector("[data-paused]")).toBeNull();
  });
});

describe("a delay past midnight", () => {
  it("marks the new departure as a later day and names the day in the eyebrow", async () => {
    const late = { ...booked, start_local: "2025-06-12T23:40", end_local: "2025-06-13T00:52" };
    const now = at("2025-06-12T22:00");
    draw({ segment: late, now, status: status(now, 2, { state: "delayed", dep_scheduled: "2025-06-12T23:40", dep_estimated: "2025-06-13T00:30", arr_scheduled: "2025-06-13T00:52", arr_estimated: "2025-06-13T01:42", delay_minutes: 50 }) });
    const card = await screen.findByRole("article");
    expect(times(card)[0]).toBe("Originally 11:40 pm 12:30 am MDT · +1 day, 1 day later on the calendar than departure");
    await waitFor(() => expect(card.querySelector(".eyebrow")).toHaveTextContent("Departure · Denver · Fri Jun 13"));
  });
});

describe("the traveled line", () => {
  it("ends where the plane is, for any progress", async () => {
    for (const progress of [0.55, 1]) {
      const [x, y] = arcTravelled(progress).split(" ").slice(-2).map(Number);
      const point = arcPoint(progress);
      expect(x).toBeCloseTo(point.left, 1);
      expect(y * (46 / 40)).toBeCloseTo(point.top, 0);
    }
  });

  it("is drawn to the plane on the card", async () => {
    draw(CASES[3]);
    const card = await screen.findByRole("article");
    const [x] = (card.querySelector("[data-travelled]")?.getAttribute("d") ?? "").split(" ").slice(-2).map(Number);
    expect(`${x.toFixed(1)}%`).toBe(`${arcPoint(Number(card.getAttribute("data-progress"))).left.toFixed(1)}%`);
  });
});

describe("the eyebrow and a diversion with no airport", () => {
  it("says only the side and the city when the flight is today", async () => {
    draw(CASES[1]);
    await waitFor(() => expect(screen.getByRole("article").querySelector(".eyebrow")?.textContent?.trim()).toBe("Departure · Denver"));
  });

  it("says where it lands is not known when a diverted status names no other airport", async () => {
    draw({ now: NOW.diverted, status: mk(NOW.diverted, 3, { state: "diverted", destination: "GJT", dep_actual: "2025-06-12T09:46" }) });
    const card = await screen.findByRole("article");
    expect(within(card).getByText("Where it lands isn’t known yet.")).toBeInTheDocument();
  });
});

describe("boarding", () => {
  it("starts BOARDING_MINUTES before departure, needs a gate and a live status, and ends at departure", async () => {
    expect(BOARDING_MINUTES).toBe(40);
    const gate = (now: number, extra: Partial<FlightStatus> = { dep_gate: "B14" }) => status(now, 1, extra);
    const state = async (now: number, st: FlightStatus | undefined) => { const { unmount } = draw({ now, status: st }); const got = (await screen.findByRole("article")).getAttribute("data-state"); unmount(); return got; };
    expect(await state(at("2025-06-12T09:00"), gate(at("2025-06-12T09:00")))).toBe("boarding");
    expect(await state(at("2025-06-12T08:59"), gate(at("2025-06-12T08:59")))).toBe("scheduled");
    expect(await state(at("2025-06-12T09:15"), gate(at("2025-06-12T09:15"), {}))).toBe("scheduled");
    expect(await state(at("2025-06-12T09:15"), undefined)).toBe("scheduled");
    expect(await state(at("2025-06-12T09:40"), gate(at("2025-06-12T09:40")))).toBe("in-the-air");
  });
});

describe("what a reader and a screen get", () => {
  it("hides the arc, the plane and the mark tile from assistive technology, and names the card by one phrase", async () => {
    draw(CASES[3]);
    const card = await screen.findByRole("article");
    expect(card.querySelector("[data-arc]")).toHaveAttribute("aria-hidden", "true");
    expect(card.querySelector("[data-arc] [data-plane]")).not.toBeNull();
    expect(card.querySelector("span.bg-avatar-1")).toHaveAttribute("aria-hidden", "true");
    expect(card.querySelector("span.bg-avatar-1")).toHaveTextContent("EA");
    expect(card).toHaveAccessibleName("EA 214, Denver to Grand Junction, in the air, lands 10:52 am in 38 minutes");
  });

  it("places the plane from how far along the flight is, and leaves it off a cancelled flight", async () => {
    const progress = async (c: Case) => { const { unmount } = draw(c); const card = await screen.findByRole("article"); const got = [card.getAttribute("data-progress"), card.querySelector("[data-plane]") !== null]; unmount(); return got; };
    expect(await progress(CASES[0])).toEqual(["0", true]);
    expect((await progress(CASES[3]))[1]).toBe(true);
    expect(Number((await progress(CASES[3]))[0])).toBeGreaterThan(0.3);
    expect(await progress(CASES[4])).toEqual(["1", true]);
    expect(await progress(CASES[5])).toEqual([null, false]);
  });

  it("shows the total duration at the top right, from the flight’s actual times once landed, and none for a cancelled flight", async () => {
    const duration = async (c: Case) => { const { unmount } = draw(c); const card = await screen.findByRole("article"); const got = card.querySelector(".ml-auto")?.textContent?.trim() ?? null; unmount(); return got; };
    expect(await duration(CASES[0])).toBe("1h 12m");
    expect(await duration(CASES[4])).toBe("1h 3m");
    expect(await duration(CASES[5])).toBeNull();
  });

  it("leads with Waypoint’s own mark and the flight number and carrier, never an airline logo", async () => {
    draw({ segment: { ...booked, logo: "/api/segments/3/logo" }, now: NOW.none });
    const card = await screen.findByRole("article");
    expect(card.querySelector("img")).toBeNull();
    expect(within(card).getByText("EA 214")).toBeInTheDocument();
    expect(within(card).getByText("Example Air")).toBeInTheDocument();
  });

  it("names the airport cities under the codes once they are known, and shows the codes alone until then", async () => {
    draw(CASES[0]);
    const card = await screen.findByRole("article");
    expect(card.querySelector("[data-code='origin']")).toHaveTextContent("DEN");
    await waitFor(() => expect(within(card).getByText("Denver")).toBeInTheDocument());
    expect(within(card).getByText("Grand Junction")).toBeInTheDocument();
  });

  it("renders what the page puts under the facts", async () => {
    const footer = createRawSnippet(() => ({ render: () => "<p>under the facts</p>" }));
    draw(CASES[7], { footer });
    expect(within(await screen.findByRole("article")).getByText("under the facts")).toBeInTheDocument();
  });

  it("opens the live status view from a link over the card when it is given an address, named with the flight and its state", async () => {
    draw(CASES[3], { href: "#trip/7/flight/3" });
    const link = await screen.findByRole("link", { name: `${CASES[3].label}, open live status` });
    expect(link).toHaveAttribute("href", "#trip/7/flight/3");
  });

  it("keeps what the page puts under the facts above the link, so its buttons still work", async () => {
    const footer = createRawSnippet(() => ({ render: () => "<button type='button'>Edit</button>" }));
    draw(CASES[7], { href: "#trip/7/flight/3", footer });
    const edit = await screen.findByRole("button", { name: "Edit" });
    expect(edit.parentElement).toHaveClass("relative", "z-10");
  });

  it("has no link when it is not given an address", async () => {
    draw(CASES[3]);
    await screen.findByRole("article");
    expect(screen.queryByRole("link")).toBeNull();
  });
});
