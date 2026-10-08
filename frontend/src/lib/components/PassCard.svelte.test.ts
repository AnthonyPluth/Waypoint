// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import type { FlightStatus, FlightStatusList } from "$lib/api-types";
import { flightStatus } from "$lib/flightstatus.svelte";
import { instant } from "$lib/trips";
import { toast } from "svelte-sonner";
import { segment } from "../../test/fixtures";
import PassCard from "./PassCard.svelte";

const NY = "America/New_York", LON = "Europe/London";
const flight = segment({ id: 7, details: { flight_number: "AA 101", terminal: "8", cabin: "Economy" }, travelers: [{ id: 1, person_id: 1, name: "Jane Doe", seat: "14C" }] });
const dep = instant(flight.start_local, NY), arr = instant(flight.end_local, LON);
const HOUR = 3_600_000;
const goes = (extra = {}) => ({ segment: { ...flight, ...extra }, now: dep - 3 * HOUR });
const progressOf = (container: HTMLElement) => (container.querySelector("[data-progress]:not(section)") as HTMLElement).dataset.progress;

const status = (extra: Partial<FlightStatus> = {}): FlightStatus => ({
  segment_id: 7, state: "delayed", origin: "JFK", destination: "LHR",
  dep_scheduled: "2026-11-20T19:00", dep_estimated: "2026-11-20T19:50", dep_actual: null, dep_zone: NY, dep_terminal: "7", dep_gate: "B24",
  arr_scheduled: "2026-11-21T07:10", arr_estimated: "2026-11-21T08:05", arr_actual: null, arr_zone: LON, arr_terminal: "5", arr_gate: "A10",
  delay_minutes: 50, fetched_at: "2026-11-20T14:05:00+00:00", ...extra,
});
const list = (extra: Partial<FlightStatusList> = {}): FlightStatusList => ({ enabled: true, month: "2026-11", used: 1, limit: 400, paused: null, statuses: [status()], ...extra });

beforeEach(() => { flightStatus.list = null; vi.mocked(toast.success).mockReset(); });
afterEach(() => { flightStatus.list = null; });

describe("a flight pass", () => {
  it("leads with the headline, then the code as the largest element, then the flight", () => {
    render(PassCard, goes());
    expect(screen.getByText("Check-in is open, departs in 3 h")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy confirmation code KQ7M2X" })).toHaveClass("text-display");
    expect(screen.getByText("American Airlines AA 101")).toBeInTheDocument();
    expect(screen.getByText("JFK")).toBeInTheDocument();
    expect(screen.getByText("LHR")).toBeInTheDocument();
  });
  it("shows terminal, seat and cabin under the tear, and the booking chip", () => {
    render(PassCard, goes());
    for (const text of ["Terminal", "8", "Seat", "14C", "Cabin", "Economy", "Confirmed"]) expect(screen.getByText(text)).toBeInTheDocument();
    expect(screen.queryByText("Gate")).toBeNull();
  });
  it("leaves out a terminal or a seat it doesn’t have", () => {
    render(PassCard, goes({ details: { flight_number: "AA 101" }, travelers: [] }));
    for (const text of ["Terminal", "Seat", "Cabin", "Gate"]) expect(screen.queryByText(text)).toBeNull();
    expect(screen.getByText("Confirmed")).toBeInTheDocument();
  });
  it("shows the times exactly as stored, never converted", () => {
    const { container } = render(PassCard, goes());
    const times = [...container.querySelectorAll("time")].map((t) => [t.getAttribute("datetime"), t.textContent]);
    expect(times).toContainEqual(["2026-11-20T19:00", "7:00 PM"]);
    expect(times).toContainEqual(["2026-11-21T07:10", "7:10 AM"]);
  });
  it("has the code as the first focusable control and copies it on tap", async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText");
    render(PassCard, { ...goes({ links: { app: "https://example.com/manage", directions: null, call: null } }) });
    await user.tab();
    expect(screen.getByRole("button", { name: "Copy confirmation code KQ7M2X" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(writeText).toHaveBeenCalledWith("KQ7M2X");
    expect(toast.success).toHaveBeenCalledWith("Copied");
  });
  it("offers the booking’s link", () => {
    render(PassCard, goes({ manage_url: "https://example.com/manage" }));
    expect(screen.getByRole("link", { name: "Manage booking" })).toHaveAttribute("href", "https://example.com/manage");
  });
  it("shows a flight with no times as untimed, with the plane at the origin", () => {
    const { container } = render(PassCard, goes({ details: { flight_number: "AA 101", time_unknown: "yes" } }));
    expect(screen.getByText("Time not recorded")).toBeInTheDocument();
    expect(screen.getAllByText("time not recorded").length).toBeGreaterThan(0);
    expect(container.querySelector("time")).toBeNull();
    expect(progressOf(container)).toBe("0");
  });
});

describe("the plane on a pass", () => {
  it("waits before departure, flies midway and rests after arrival", () => {
    for (const [now, want] of [[dep - HOUR, "0"], [dep + (arr - dep) / 2, "0.5"], [arr + HOUR, "1"]] as const) {
      const { container, unmount } = render(PassCard, { segment: flight, now });
      expect(progressOf(container)).toBe(want);
      unmount();
    }
  });
  it("is placed from the booked times alone, with live status on and delayed", () => {
    flightStatus.list = list();
    const { container } = render(PassCard, { segment: flight, now: dep + (arr - dep) / 2 });
    expect(progressOf(container)).toBe("0.5");
    expect(screen.getByText("Under way, arrives in 3 h 35 min")).toBeInTheDocument();
  });
  it("says it is worked out from the booked times", () => {
    render(PassCard, goes());
    expect(screen.getByRole("img", { name: /booked times/ })).toBeInTheDocument();
  });
  it("handles a flight across the date line", () => {
    const over = segment({ origin: "SYD", destination: "LAX", start_local: "2026-11-20T10:00", start_zone: "Australia/Sydney", end_local: "2026-11-20T06:00", end_zone: "America/Los_Angeles" });
    const from = instant(over.start_local, over.start_zone), to = instant(over.end_local, over.end_zone);
    const { container } = render(PassCard, { segment: over, now: (from + to) / 2 });
    expect(Number(progressOf(container))).toBeCloseTo(0.5, 5);
  });
});

describe("live status on a pass", () => {
  it("adds a small live chip and a quiet line, and leaves the headline on the booked times", () => {
    flightStatus.list = list();
    render(PassCard, goes());
    expect(screen.getByText("Delayed 50 min")).toBeInTheDocument();
    expect(screen.getByText("Check-in is open, departs in 3 h")).toBeInTheDocument();
    expect(screen.getByText(/50 min late · Gate B24 · as of/)).toBeInTheDocument();
    expect(screen.getByText("Gate")).toBeInTheDocument();
  });
  it("has no live chip when live status is off", () => {
    flightStatus.list = list({ enabled: false });
    render(PassCard, goes());
    expect(screen.queryByText("Delayed 50 min")).toBeNull();
    expect(screen.getByText("Confirmed")).toBeInTheDocument();
  });
});

describe("a cancelled pass", () => {
  it("shows the cancelled chip and never reads as current", () => {
    flightStatus.list = list();
    const { container } = render(PassCard, { segment: { ...flight, status: "cancelled" }, now: dep - 3 * HOUR });
    expect(screen.getAllByText("Cancelled")).toHaveLength(2);
    expect(screen.queryByText(/Check-in/)).toBeNull();
    expect(screen.queryByText("Delayed 50 min")).toBeNull();
    expect(progressOf(container)).toBe("0");
  });
});

describe("the other kinds of pass", () => {
  const stay = segment({ id: 2, kind: "hotel", provider: "Marriott", origin: "Harbour Hotel", destination: null, confirmation: "HT5521", start_local: "2026-11-21T15:00", start_zone: LON, end_local: "2026-11-27T10:00", end_zone: LON, details: { address: "1 Quay Street, London", room: "412" } });
  const nowStay = instant("2026-11-21T10:00", LON);
  it("leads a stay with check-in and check-out", () => {
    render(PassCard, { segment: stay, now: nowStay });
    expect(screen.getByText("Check-in in 5 h")).toBeInTheDocument();
    expect(screen.getByText("Harbour Hotel")).toBeInTheDocument();
    expect(screen.getByText("Check-in")).toBeInTheDocument();
    expect(screen.getByText("Check-out")).toBeInTheDocument();
    expect(screen.getByText("1 Quay Street, London")).toBeInTheDocument();
    expect(screen.getByText("412")).toBeInTheDocument();
    expect(screen.queryByRole("img")).toBeNull();
  });
  it("leads a car with pick-up and drop-off, and copes with no address", () => {
    const car = segment({ id: 3, kind: "car", provider: "Hertz", origin: "LHR", destination: null, start_local: "2026-11-21T09:00", start_zone: LON, end_local: "2026-11-23T09:00", end_zone: LON, details: { car_class: "Compact" } });
    render(PassCard, { segment: car, now: instant("2026-11-21T08:00", LON) });
    expect(screen.getByText("Pick-up in 1 h")).toBeInTheDocument();
    expect(screen.getByText("Pick-up")).toBeInTheDocument();
    expect(screen.getByText("Drop-off")).toBeInTheDocument();
    expect(screen.getByText("Compact")).toBeInTheDocument();
    expect(screen.queryByText("Address")).toBeNull();
  });
  it("leads a train with where it goes and when", () => {
    const train = segment({ id: 4, kind: "train", provider: "Eurostar", origin: "London", destination: "Paris", start_local: "2026-11-21T09:00", start_zone: LON, end_local: "2026-11-21T12:20", end_zone: "Europe/Paris", details: { seat: "31", cabin: "Standard" } });
    render(PassCard, { segment: train, now: instant("2026-11-21T10:00", LON) });
    expect(screen.getByText("London → Paris")).toBeInTheDocument();
    expect(screen.getByText("Arrives in 1 h 20 min")).toBeInTheDocument();
    expect(screen.getByText("31")).toBeInTheDocument();
  });
  it("leads a cruise with embarking and disembarking", () => {
    const ship = segment({ id: 5, kind: "cruise", provider: "Example Cruise Line", origin: "Miami", destination: "Miami", start_local: "2026-11-21T16:00", start_zone: "America/New_York", end_local: "2026-11-28T07:00", end_zone: "America/New_York", details: { ship: "Example Star", room: "9012", deck: "9" } });
    render(PassCard, { segment: ship, now: instant("2026-11-22T12:00", "America/New_York") });
    expect(screen.getByText("Disembarks in 5 days 19 h")).toBeInTheDocument();
    expect(screen.getByText("Embarks")).toBeInTheDocument();
    expect(screen.getByText("Example Star · Miami")).toBeInTheDocument();
    expect(screen.getByText("9012")).toBeInTheDocument();
  });
  it("shows a stay with no times as untimed", () => {
    render(PassCard, { segment: { ...stay, details: { time_unknown: "yes" } }, now: nowStay });
    expect(screen.getByText("Time not recorded")).toBeInTheDocument();
  });
  it("shows a cancelled stay as cancelled", () => {
    render(PassCard, { segment: { ...stay, status: "cancelled" }, now: nowStay });
    expect(screen.getAllByText("Cancelled")).toHaveLength(2);
    expect(screen.queryByText(/Check-in in/)).toBeNull();
  });
});
