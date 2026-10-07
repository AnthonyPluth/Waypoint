// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import type { FlightStatus as Status, FlightStatusList, Segment } from "$lib/api-types";
import { flightStatus } from "$lib/flightstatus.svelte";
import { segment } from "../../test/fixtures";
import FlightPassCard from "./FlightPassCard.svelte";

const dep = new Date("2026-11-21T00:00:00+00:00");
const mid = new Date("2026-11-21T03:35:00+00:00");

const my_segment = segment;
const status = (extra: Partial<Status> = {}): Status => ({
  segment_id: 1, state: "delayed", origin: "JFK", destination: "LHR",
  dep_scheduled: "2026-11-20T19:00", dep_estimated: "2026-11-20T19:50", dep_actual: null, dep_zone: "America/New_York",
  dep_terminal: "7", dep_gate: "B24",
  arr_scheduled: "2026-11-21T07:10", arr_estimated: "2026-11-21T08:05", arr_actual: null, arr_zone: "Europe/London",
  arr_terminal: "5", arr_gate: "A10", delay_minutes: 50, fetched_at: "2026-11-20T14:05:00+00:00", ...extra,
});
const list = (extra: Partial<FlightStatusList> = {}): FlightStatusList =>
  ({ enabled: true, month: "2026-11", used: 12, limit: 400, paused: null, statuses: [status()], ...extra });

const clipboard = { writeText: vi.fn().mockResolvedValue(undefined) };

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(mid);
  flightStatus.list = null;
  Object.defineProperty(navigator, "clipboard", { value: clipboard, configurable: true });
  clipboard.writeText.mockClear();
});
afterEach(() => { vi.useRealTimers(); flightStatus.list = null; });

const passFacts = () => screen.getByTestId("pass-facts");
const fact = (key: string): HTMLElement | null => passFacts().querySelector(`[data-fact="${key}"]`);

describe("the flight pass card", () => {
  it("is a pass for a flight, a stay, a car, a train and a cruise, each led by its own facts", () => {
    const each: [Segment["kind"], string][] = [
      ["flight", "AA 101"],
      ["hotel", "Harbour Hotel"],
      ["car", "Hertz"],
      ["train", "Acela"],
      ["cruise", "Example Voyager"],
    ];
    for (const [kind, lead] of each) {
      const made = kind === "flight" ? my_segment()
        : kind === "hotel" ? my_segment({ kind, provider: "Marriott", origin: "Harbour Hotel", destination: null, start_zone: "Europe/London", end_zone: "Europe/London", details: { room: "910" } })
          : kind === "car" ? my_segment({ kind, provider: "Hertz", start_zone: "America/Los_Angeles", end_zone: "America/Los_Angeles", details: { car_class: "Compact" } })
            : kind === "train" ? my_segment({ kind, provider: "Acela", start_zone: "America/New_York", end_zone: "America/New_York", details: { cabin: "Business" } })
              : my_segment({ kind, provider: "Example Cruise Line", origin: "Miami", start_zone: "America/New_York", end_zone: "America/New_York", details: { ship: "Example Voyager", room: "9214", deck: "9" } });
      const { unmount } = render(FlightPassCard, { segment: made, now: mid.getTime() });
      const card = screen.getByTestId("flight-pass-card");
      expect(card).toHaveAttribute("data-kind", kind);
      expect(card).toHaveTextContent(lead);
      expect(card).toHaveTextContent("KQ7M2X");
      expect(screen.getByTestId("status-chip")).toBeInTheDocument();
      unmount();
    }
  });

  it("shows the wall-clock time at each end exactly as booked, and the flight number, date and departure time", () => {
    render(FlightPassCard, { segment: my_segment(), now: mid.getTime() });
    const times = screen.getByTestId("booked-times");
    expect(times).toHaveAttribute("title", "The line is at the booked times, not the live ones.");
    expect(times).toHaveAttribute("aria-label", "The line is at the booked times, not the live ones.");
    expect(times).toHaveTextContent("New York");
    expect(times).toHaveTextContent("London");
    expect(times).toHaveTextContent("7:00 PM");
    expect(times).toHaveTextContent("7:10 AM");
    expect(screen.getByTestId("focal-facts")).toHaveTextContent("AA 101");
    expect(screen.getByTestId("focal-facts")).toHaveTextContent("Fri, Nov 20");
    expect(screen.getByTestId("focal-facts")).toHaveTextContent("departs 7:00 PM");
  });

  it("shows terminal, gate, seat and cabin below the tear line, only what the booking has", () => {
    const withAll = my_segment({ details: { flight_number: "AA 101", terminal: "8", gate: "45B", cabin: "Economy" }, travelers: [{ id: 1, person_id: 1, name: "Jane Doe", seat: "12A" }] });
    let view = render(FlightPassCard, { segment: withAll, now: mid.getTime() });
    expect(fact("terminal")).toHaveTextContent("8");
    expect(fact("gate")).toHaveTextContent("45B");
    expect(fact("seat")).toHaveTextContent("12A");
    expect(fact("cabin")).toHaveTextContent("Economy");
    view.unmount();
    view = render(FlightPassCard, { segment: my_segment(), now: mid.getTime() });
    expect(fact("terminal")).toHaveTextContent("8");
    expect(fact("gate")).toBeNull();
    view.unmount();
    const withoutTerminal = my_segment({ details: { flight_number: "AA 101", gate: "45B" } });
    render(FlightPassCard, { segment: withoutTerminal, now: mid.getTime() });
    expect(fact("terminal")).toBeNull();
    expect(fact("gate")).toHaveTextContent("45B");
  });

  it("counts down the headline line, from check-in to landed, at each boundary", () => {
    const cases: [Date, string][] = [
      [new Date("2026-11-19T23:00:00Z"), "Check-in opens in 1 h"],
      [new Date("2026-11-20T07:00:00-05:00"), "Check-in is open, departs in 12 h"],
      [mid, "Under way, arrives in 3 h 35 min"],
      [new Date("2026-11-21T12:10:00Z"), "Landed"],
    ];
    for (const [now, line] of cases) {
      vi.setSystemTime(now);
      const { unmount } = render(FlightPassCard, { segment: my_segment(), now: now.getTime() });
      expect(screen.getByTestId("headline-line")).toHaveTextContent(line);
      unmount();
    }
  });

  it("is the first focusable control after the headline line, and copies on tap", async () => {
    render(FlightPassCard, { segment: my_segment({ links: { app: "https://example.com/manage/KQ7M2X", directions: null, call: null } }), now: mid.getTime() });
    const card = screen.getByTestId("flight-pass-card");
    const focusable = [...card.querySelectorAll("a[href], button")];
    expect(screen.getByTestId("headline-line")).toBeInTheDocument();
    expect(focusable[0]?.getAttribute("aria-label")).toBe("Copy confirmation code KQ7M2X");
    await userEvent.click(focusable[0] as HTMLElement);
    await waitFor(() => expect(clipboard.writeText).toHaveBeenCalledWith("KQ7M2X"));
  });

  it("opens the booking in the app, with the phone word on a phone", () => {
    render(FlightPassCard, { segment: my_segment({ links: { app: "https://example.com/manage/KQ7M2X", directions: null, call: null } }), now: mid.getTime() });
    expect(screen.getByRole("link", { name: "Manage booking" })).toHaveAttribute("href", "https://example.com/manage/KQ7M2X");
  });

  it("hides nothing for a flight with no times: no headline, times not recorded, plane at the origin", () => {
    vi.setSystemTime(dep);
    const untimed = my_segment({ start_local: "2026-11-20T00:00", end_local: "2026-11-20T00:00", details: { time_unknown: "yes" } });
    render(FlightPassCard, { segment: untimed, now: dep.getTime() });
    expect(screen.queryByTestId("headline-line")).toBeNull();
    expect(screen.getByTestId("focal-facts")).toHaveTextContent("time not recorded");
    expect(screen.getByTestId("booked-times")).toHaveTextContent("time not recorded");
    expect(screen.getByTestId("route-line")).toHaveAttribute("data-progress", "0");
    expect(screen.queryByTestId("flight-status")).toBeNull();
  });

  it("moves the plane by the booked times alone, from the origin to the destination", () => {
    for (const [now, at] of [[new Date("2026-11-20T17:00:00Z"), "0"], [mid, "0.5"], [new Date("2026-11-21T23:00:00Z"), "1"]] as const) {
      vi.setSystemTime(now);
      const { unmount } = render(FlightPassCard, { segment: my_segment(), now: now.getTime() });
      expect(screen.getByTestId("route-line")).toHaveAttribute("data-progress", at);
      unmount();
    }
  });

  it("keeps the plane on the booked times even with live status on and the flight delayed", () => {
    flightStatus.list = list();
    render(FlightPassCard, { segment: my_segment(), now: mid.getTime() });
    expect(screen.getByTestId("flight-status")).toHaveTextContent("Delayed 50 min");
    expect(screen.getByTestId("route-line")).toHaveAttribute("data-progress", "0.5");
  });

  it("never reads as current when the flight is cancelled: the cancelled chip, no headline, no live status", () => {
    render(FlightPassCard, { segment: my_segment({ status: "cancelled" }), now: mid.getTime() });
    expect(screen.getByTestId("status-chip")).toHaveAttribute("data-status", "cancelled");
    expect(screen.queryByTestId("headline-line")).toBeNull();
    expect(screen.queryByTestId("flight-status")).toBeNull();
  });
});