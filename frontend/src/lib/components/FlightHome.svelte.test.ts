// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));

import { api } from "$lib/api";
import { forgetAirportZones } from "$lib/airport-zones";
import type { FlightStatus, Segment } from "$lib/api-types";
import { instant } from "$lib/trips";
import { segment } from "../../test/fixtures";
import FlightHome from "./FlightHome.svelte";

const NY = "America/New_York";
const LISBON = "Europe/Lisbon";
const AIRPORTS: Record<string, object> = {
  BOS: { code: "BOS", name: "Logan International Airport", city: "Boston", country: "US", zone: NY },
  JFK: { code: "JFK", name: "John F. Kennedy International Airport", city: "New York", country: "US", zone: NY },
  LIS: { code: "LIS", name: "Humberto Delgado Airport", city: "Lisbon", country: "PT", zone: LISBON },
};
const SEATS = (a: string, b: string, c: string) => [
  { id: 1, person_id: 1, name: "Mara Quist", seat: a }, { id: 2, person_id: 2, name: "Tomas Reyes", seat: b }, { id: 3, person_id: 3, name: "Ines Vale", seat: c },
];
const journey = (leg: 1 | 2) => ({ lead: 1, leg, legs: 2, previous: leg === 2 ? 1 : null, next: leg === 1 ? 2 : null });
const first = (extra: Partial<Segment> = {}) => segment({
  id: 1, provider: "Aurora Air", origin: "BOS", destination: "JFK", start_local: "2026-03-09T06:10", start_zone: NY, end_local: "2026-03-09T07:28", end_zone: NY,
  details: { flight_number: "AU1402", terminal: "B" }, travelers: SEATS("14A", "14B", "22C"), journey: journey(1), ...extra,
});
const second = (extra: Partial<Segment> = {}) => segment({
  id: 2, provider: "Aurora Air", origin: "JFK", destination: "LIS", start_local: "2026-03-09T09:40", start_zone: NY, end_local: "2026-03-09T21:15", end_zone: LISBON,
  details: { flight_number: "AU212", terminal: "4" }, travelers: SEATS("31A", "31B", "31C"), journey: journey(2), ...extra,
});
const at = (local: string) => instant(local, NY);
const flat = (el: Element | null | undefined) => el?.textContent?.replace(/\s+/g, " ").trim() ?? "";

const draw = (leg: Segment, all: Segment[], now: number, extra: Record<string, unknown> = {}) =>
  render(FlightHome, { segment: leg, tripSegments: all, liveOn: true, now, eyebrow: "Next up", tripName: "Lisbon", ...extra });

beforeEach(() => {
  forgetAirportZones();
  vi.mocked(api).mockReset().mockImplementation(async (path: string) => {
    const found = AIRPORTS[path.split("/").pop() ?? ""];
    if (!found) throw new Error("No such airport");
    return found;
  });
});

describe("the hero for a connection", () => {
  it("before the first leg shows the whole journey, the stop on the arc and a Then line", async () => {
    const { container } = draw(first(), [first(), second()], at("2026-03-07T05:00"));
    const card = await screen.findByRole("article");
    await waitFor(() => expect(card.querySelector("[data-sentence]")).toHaveTextContent("Your flights to Lisbon"));
    expect(card).toHaveAttribute("data-connection", "before");
    expect(card.querySelector("[data-carrier]")).toHaveTextContent("Aurora Air AU 1402");
    expect(card.querySelector("[data-top]")).toHaveTextContent("In 2 days");
    expect(flat(card.querySelector("[data-big]"))).toBe("Departs 6:10 AM");
    expect(card.querySelector("[data-code='origin']")).toHaveTextContent("BOS");
    expect(card.querySelector("[data-code='destination']")).toHaveTextContent("LIS");
    expect(card.querySelector("[data-when='origin'] time")).toHaveTextContent("6:10 AM");
    expect(card.querySelector("[data-when='destination'] time")).toHaveTextContent("9:15 PM");
    expect(card.querySelector("[data-arc-note]")).toHaveTextContent("1 stop, JFK");
    expect(container.querySelectorAll("[data-stop]")).toHaveLength(1);
    expect(container.querySelector("[data-plane]")).not.toBeNull();
    expect(card.querySelector("[data-then-label]")).toHaveTextContent("Then, at JFK");
    expect(flat(card.querySelector("[data-then]"))).toBe("Then, at JFK AU 212 departs 9:40 AM · Terminal 4 · 2 h 12 min to connect");
    expect(card.querySelector("[data-facts]")).toHaveTextContent("Terminal");
    expect(flat(card.querySelector("[data-facts]"))).toContain("14A +2");
  });

  it("during the connection the plane waits at the stop and the leg you are on is the second", async () => {
    const { container } = draw(second(), [first(), second()], at("2026-03-09T07:50"));
    const card = await screen.findByRole("article");
    await waitFor(() => expect(card.querySelector("[data-sentence]")).toHaveTextContent("Your connection to Lisbon"));
    expect(card).toHaveAttribute("data-connection", "during");
    expect(card.querySelector("[data-carrier]")).toHaveTextContent("Aurora Air AU 212");
    expect(card.querySelector("[data-top]")).toHaveTextContent("Departs in 1 h 50 min");
    expect(flat(card.querySelector("[data-big]"))).toBe("Departs 9:40 AM");
    expect(flat(card.querySelector("[data-quiet]"))).toBe("Leg 2 of 2 · Times from your booking.");
    expect(card.querySelector("[data-code='origin']")).toHaveTextContent("BOS");
    expect(card.querySelector("[data-code='destination']")).toHaveTextContent("LIS");
    expect(card.querySelector("[data-arc-note]")).toHaveTextContent("At JFK");
    const stop = container.querySelector("[data-stop]") as HTMLElement;
    const plane = container.querySelector("[data-plane]") as HTMLElement;
    expect(plane.style.left).toBe(stop.style.left);
    expect(container.querySelector("[data-travelled]")).not.toBeNull();
    expect(flat(card.querySelector("[data-then]"))).toBe("Earlier AU 1402 landed at JFK 7:28 AM");
    expect(flat(card.querySelector("[data-facts]"))).toContain("Terminal 4");
    expect(flat(card.querySelector("[data-facts]"))).toContain("31A +2");
  });

  it("says on time for the leg you are on when live status has it", async () => {
    const live: FlightStatus = {
      segment_id: 2, state: "scheduled", origin: "JFK", destination: "LIS", dep_scheduled: "2026-03-09T09:40", dep_estimated: null, dep_actual: null, dep_zone: NY,
      dep_terminal: "4", dep_gate: "B22", arr_scheduled: "2026-03-09T21:15", arr_estimated: null, arr_actual: null, arr_zone: LISBON, arr_terminal: null, arr_gate: null,
      delay_minutes: null, fetched_at: new Date(at("2026-03-09T07:48")).toISOString(),
    };
    draw(second(), [first(), second()], at("2026-03-09T07:50"), { status: live });
    const card = await screen.findByRole("article");
    expect(flat(card.querySelector("[data-quiet]"))).toBe("Leg 2 of 2 · on time");
    expect(flat(card.querySelector("[data-facts]"))).toContain("B22");
  });

  it("says so in amber when the connection is under 45 minutes", async () => {
    draw(first(), [first(), second({ start_local: "2026-03-09T08:06" })], at("2026-03-07T06:10"));
    const card = await screen.findByRole("article");
    const connect = card.querySelector("[data-connect]");
    expect(connect).toHaveTextContent("38 min to connect");
    expect(connect).toHaveClass("text-signal-ink");
  });

  it("does not colour a comfortable connection", async () => {
    draw(first(), [first(), second()], at("2026-03-07T06:10"));
    const card = await screen.findByRole("article");
    expect(card.querySelector("[data-connect]")).not.toHaveClass("text-signal-ink");
  });

  it("turns the next leg's time amber when its status says it is delayed", async () => {
    const late: FlightStatus = {
      segment_id: 2, state: "delayed", origin: "JFK", destination: "LIS", dep_scheduled: "2026-03-09T09:40", dep_estimated: "2026-03-09T10:20", dep_actual: null, dep_zone: NY,
      dep_terminal: "4", dep_gate: null, arr_scheduled: "2026-03-09T21:15", arr_estimated: "2026-03-09T21:55", arr_actual: null, arr_zone: LISBON, arr_terminal: null, arr_gate: null,
      delay_minutes: 40, fetched_at: new Date(at("2026-03-07T06:00")).toISOString(),
    };
    draw(first(), [first(), second()], at("2026-03-07T06:10"), { statusOf: (id: number) => (id === 2 ? late : undefined) });
    const card = await screen.findByRole("article");
    expect(card.querySelector("[data-then-time]")).toHaveTextContent("10:20 AM");
    expect(card.querySelector("[data-then-time]")).toHaveClass("text-signal-ink");
  });

  it("keeps the first leg's own hero once it is in the air", async () => {
    const { container } = draw(first(), [first(), second()], at("2026-03-09T06:40"));
    const card = await screen.findByRole("article");
    expect(card).not.toHaveAttribute("data-connection");
    expect(card.querySelector("[data-code='destination']")).toHaveTextContent("JFK");
    expect(card.querySelector("[data-then]")).toBeNull();
    expect(card.querySelector("[data-arc-note]")).toBeNull();
    expect(container.querySelector("[data-stop]")).toBeNull();
    await waitFor(() => expect(card.querySelector("[data-sentence]")).toHaveTextContent("In the air to New York"));
  });

  it("keeps the second leg's own hero while the first has not landed", async () => {
    draw(second(), [first(), second()], at("2026-03-09T06:40"));
    const card = await screen.findByRole("article");
    expect(card).not.toHaveAttribute("data-connection");
    expect(card.querySelector("[data-code='origin']")).toHaveTextContent("JFK");
    expect(card.querySelector("[data-then]")).toBeNull();
  });

  it("is a single flight when the saved copy has no journey or the other leg is missing", async () => {
    const { unmount } = draw(first({ journey: undefined }), [first({ journey: undefined }), second({ journey: undefined })], at("2026-03-07T06:10"));
    let card = await screen.findByRole("article");
    expect(card).not.toHaveAttribute("data-connection");
    expect(card.querySelector("[data-code='destination']")).toHaveTextContent("JFK");
    unmount();
    draw(first(), [first()], at("2026-03-07T06:10"));
    card = await screen.findByRole("article");
    expect(card).not.toHaveAttribute("data-connection");
    expect(card.querySelector("[data-then]")).toBeNull();
  });

  it("is a single flight when a leg is cancelled by live status", async () => {
    const gone: FlightStatus = {
      segment_id: 2, state: "cancelled", origin: "JFK", destination: "LIS", dep_scheduled: "2026-03-09T09:40", dep_estimated: null, dep_actual: null, dep_zone: NY,
      dep_terminal: null, dep_gate: null, arr_scheduled: "2026-03-09T21:15", arr_estimated: null, arr_actual: null, arr_zone: LISBON, arr_terminal: null, arr_gate: null,
      delay_minutes: null, fetched_at: new Date(at("2026-03-07T06:00")).toISOString(),
    };
    draw(first(), [first(), second()], at("2026-03-07T06:10"), { statusOf: (id: number) => (id === 2 ? gone : undefined) });
    const card = await screen.findByRole("article");
    expect(card).not.toHaveAttribute("data-connection");
  });

  it("names every stop of a journey with three legs", async () => {
    const third = segment({ id: 3, provider: "Aurora Air", origin: "LIS", destination: "MAD", start_local: "2026-03-09T23:30", start_zone: LISBON, end_local: "2026-03-10T02:05", end_zone: "Europe/Madrid",
      details: { flight_number: "AU77" }, journey: { lead: 1, leg: 3, legs: 3, previous: 2, next: null } });
    const a = first({ journey: { lead: 1, leg: 1, legs: 3, previous: null, next: 2 } });
    const b = second({ journey: { lead: 1, leg: 2, legs: 3, previous: 1, next: 3 } });
    const { container } = draw(a, [a, b, third], at("2026-03-07T06:10"));
    const card = await screen.findByRole("article");
    expect(card.querySelector("[data-arc-note]")).toHaveTextContent("2 stops, JFK, LIS");
    expect(container.querySelectorAll("[data-stop]")).toHaveLength(2);
    expect(card.querySelector("[data-code='destination']")).toHaveTextContent("MAD");
    expect(card.querySelector("[data-when='destination'] [data-later]")).toHaveTextContent("+1 day");
  });
});
