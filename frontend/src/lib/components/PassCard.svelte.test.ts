// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import { createRawSnippet } from "svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import { forgetAirportZones } from "$lib/airport-zones";
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

const times = createRawSnippet(() => ({ render: () => "<p>custom rows</p>" }));
const AIRPORTS: Record<string, object> = {
  JFK: { code: "JFK", name: "John F. Kennedy International Airport", city: "New York", country: "US", zone: NY },
  LHR: { code: "LHR", name: "Heathrow Airport", city: "London", country: "GB", zone: LON },
  SYD: { code: "SYD", name: "Sydney Kingsford Smith Airport", city: "Sydney", country: "AU", zone: "Australia/Sydney" },
  LAX: { code: "LAX", name: "Los Angeles International Airport", city: "Los Angeles", country: "US", zone: "America/Los_Angeles" },
};
beforeEach(() => { forgetAirportZones(); vi.mocked(api).mockReset().mockImplementation(async (path: string) => {
  const found = AIRPORTS[path.split("/").pop() ?? ""];
  if (!found) throw new Error("No such airport");
  return found;
}); flightStatus.list = null; vi.mocked(toast.success).mockReset(); });
afterEach(() => { flightStatus.list = null; });

describe("a flight pass", () => {
  it("leads with the headline, then the code as the largest element, then the flight", () => {
    render(PassCard, goes());
    expect(screen.getByText("Check-in usually open, scheduled departure in 3 h")).toBeInTheDocument();
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
  it("lists the travellers' seats in order", () => {
    const seats = ["35C", "36D", "36E", "35A", "35B"].map((seat, i) => ({ id: i + 1, person_id: i + 1, name: `Traveller ${i + 1}`, seat }));
    render(PassCard, goes({ details: { flight_number: "AA 101" }, travelers: seats }));
    expect(screen.getByText("35A, 35B, 35C, 36D, 36E")).toBeInTheDocument();
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
    render(PassCard, { ...goes({ links: { app: "https://example.com/manage", open: null, open_kind: null, directions: null, call: null } }) });
    await user.tab();
    expect(screen.getByRole("button", { name: "Copy confirmation code KQ7M2X" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(writeText).toHaveBeenCalledWith("KQ7M2X");
    expect(toast.success).toHaveBeenCalledWith("Copied");
  });
  it("offers a phone the vendor's app, or its website, without opening a new tab, and a computer nothing", () => {
    const vendor = (open_kind: "app" | "website") => ({ links: { app: null, open: "https://www.example-vendor.example/", open_kind, directions: null, call: null } });
    const ua = vi.spyOn(navigator, "userAgent", "get").mockReturnValue("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)");
    const first = render(PassCard, { ...goes(vendor("app")), now: dep - 25 * HOUR });
    const app = screen.getByRole("link", { name: "Open in app" });
    expect(app).toHaveAttribute("href", "https://www.example-vendor.example/");
    expect(app).not.toHaveAttribute("target");
    first.unmount();
    render(PassCard, { ...goes(vendor("website")), now: dep - 25 * HOUR });
    expect(screen.getByRole("link", { name: "Open website" })).not.toHaveAttribute("target");
    ua.mockReturnValue("Mozilla/5.0 (X11; Linux x86_64)");
  });
  it("offers a computer no vendor button", () => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue("Mozilla/5.0 (X11; Linux x86_64)");
    render(PassCard, { ...goes({ links: { app: null, open: "https://www.example-vendor.example/", open_kind: "app", directions: null, call: null } }), now: dep - 25 * HOUR });
    expect(screen.queryByRole("link", { name: /Open in app|Open website|Manage booking/ })).toBeNull();
  });
  it("offers the booking’s link", () => {
    render(PassCard, { ...goes({ manage_url: "https://example.com/manage" }), now: dep - 25 * HOUR });
    expect(screen.getByRole("link", { name: "Manage booking" })).toHaveAttribute("href", "https://example.com/manage");
  });
  it("says Check in from 24 hours before departure until it departs", () => {
    const manage = { manage_url: "https://example.com/manage" };
    const inside = render(PassCard, { ...goes(manage), now: dep - 24 * HOUR });
    expect(screen.getByRole("link", { name: "Check in" })).toHaveAttribute("href", "https://example.com/manage");
    inside.unmount();
    render(PassCard, { ...goes(manage), now: dep });
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
    expect(screen.getByText("Scheduled arrival in 3 h 35 min")).toBeInTheDocument();
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
    expect(screen.getByText("Check-in usually open, scheduled departure in 3 h")).toBeInTheDocument();
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

describe("a booking's cost", () => {
  const stay = segment({ id: 2, kind: "hotel", provider: "Marriott", origin: "Harbour Hotel", destination: null, confirmation: "HT5521", start_local: "2026-11-21T15:00", start_zone: LON, end_local: "2026-11-27T10:00", end_zone: LON, details: { address: "1 Quay Street, London", room: "412" } });
  const nowStay = instant("2026-11-21T10:00", LON);

  it("is a fact on the card in its own currency", () => {
    render(PassCard, { segment: { ...stay, price: { amount_minor: 31000, currency: "EUR", source: "email" } }, now: nowStay });
    expect(screen.getByText("Cost")).toBeInTheDocument();
    expect(screen.getByText(/€310\.00/)).toBeInTheDocument();
  });
  it("is absent when the booking has none", () => {
    render(PassCard, { segment: stay, now: nowStay });
    expect(screen.queryByText("Cost")).toBeNull();
  });
  it("is struck through and noted as not counted when the booking is cancelled", () => {
    render(PassCard, { segment: { ...stay, status: "cancelled", price: { amount_minor: 124000, currency: "USD", source: "manual" } }, now: nowStay });
    expect(screen.getByText(/\$1,240\.00/)).toHaveClass("line-through");
    expect(screen.getByText("Cancelled, so not in the trip’s total")).toBeInTheDocument();
  });
  it("is left to the caller on a card that holds several bookings", () => {
    const other = { ...stay, id: 99, price: { amount_minor: 100, currency: "USD", source: "email" as const } };
    render(PassCard, { segment: { ...stay, price: { amount_minor: 31000, currency: "EUR", source: "email" } }, bookings: [stay, other], now: nowStay });
    expect(screen.queryByText("Cost")).toBeNull();
  });
});

describe("a past trip with no times", () => {
  const visit = segment({ id: 3, kind: "visit", provider: null, origin: null, destination: "JP", confirmation: null, start_local: "2005-03-10T00:00", start_zone: LON, end_local: "2005-03-29T00:00", end_zone: LON, details: { time_unknown: "yes" } });

  it("shows its dates with the year and no time not recorded line above the title", () => {
    render(PassCard, { segment: visit, now: instant("2026-11-21T10:00", LON) });
    expect(screen.queryByText("Time not recorded")).toBeNull();
    expect(screen.queryByText(/time not recorded/)).toBeNull();
    expect(screen.getByText("Thu, Mar 10, 2005")).toBeInTheDocument();
    expect(screen.getByText("Tue, Mar 29, 2005")).toBeInTheDocument();
  });

  it("still says time not recorded for a booking of another kind", () => {
    render(PassCard, { segment: { ...visit, kind: "hotel", origin: "Harbour Hotel", destination: null, details: { time_unknown: "yes" } }, now: instant("2005-03-10T10:00", LON) });
    expect(screen.getByText("Time not recorded")).toBeInTheDocument();
    expect(screen.getAllByText(/time not recorded/)).toHaveLength(2);
  });
});

describe("evidence on a pass", () => {
  const fresh = (extra: Partial<FlightStatus> = {}) => list({ statuses: [status({ fetched_at: new Date(dep + HOUR).toISOString(), ...extra })] });
  const midway = dep + 2 * HOUR;

  it("labels the plane as based on the schedule", () => {
    render(PassCard, { segment: flight, now: midway });
    expect(screen.getByText("Based on schedule")).toBeInTheDocument();
  });
  it("never calls a flight landed or under way from the clock, with live status unavailable, stale or offline", () => {
    const offline = vi.spyOn(navigator, "onLine", "get");
    for (const [setup, list_] of [["none", null], ["stale", list({ statuses: [status({ state: "departed", fetched_at: new Date(dep - 6 * HOUR).toISOString() })] })], ["offline", fresh({ state: "departed" })]] as const) {
      flightStatus.list = list_;
      offline.mockReturnValue(setup !== "offline");
      const { container, unmount } = render(PassCard, { segment: flight, now: arr + HOUR });
      const text = container.querySelector("[data-headline]")?.textContent;
      expect(text, setup).toBe("Scheduled arrival time passed");
      unmount();
    }
    offline.mockRestore();
  });
  it("leads with a delay instead of under way", () => {
    flightStatus.list = fresh();
    render(PassCard, { segment: flight, now: midway });
    expect(screen.getByText("Delayed 50 min, not yet confirmed as departed")).toBeInTheDocument();
    expect(screen.queryByText(/Under way/)).toBeNull();
  });
  it("leads with a live cancellation in red and parks the plane", () => {
    flightStatus.list = fresh({ state: "cancelled" });
    const { container } = render(PassCard, { segment: flight, now: midway });
    expect(screen.getByText("Cancelled by the airline")).toHaveClass("text-destructive");
    expect(progressOf(container)).toBe("0");
    expect(screen.queryByText("Based on schedule")).toBeNull();
  });
  it("says landed, with the plane at the end and no schedule label, only when live status does", () => {
    flightStatus.list = fresh({ state: "landed", arr_actual: "2026-11-21T07:03" });
    const { container } = render(PassCard, { segment: flight, now: arr - 2 * HOUR });
    expect(container.querySelector("[data-headline]")?.textContent).toBe("Landed");
    expect(progressOf(container)).toBe("1");
    expect(screen.queryByText("Based on schedule")).toBeNull();
  });
});

describe("airports and days on a flight pass", () => {
  it("puts the city and airport name under each code", async () => {
    render(PassCard, goes());
    expect(await screen.findByText("New York")).toBeInTheDocument();
    expect(screen.getByText("John F. Kennedy International Airport")).toBeInTheDocument();
    expect(screen.getByText("London")).toBeInTheDocument();
    expect(screen.getByText("Heathrow Airport")).toBeInTheDocument();
  });
  it("shows the code alone for an airport Waypoint doesn’t know", async () => {
    const { container } = render(PassCard, goes({ origin: "ZZZ" }));
    await screen.findByText("London");
    expect(screen.getByText("ZZZ")).toBeInTheDocument();
    expect(container.querySelectorAll("[data-airport-name]")).toHaveLength(1);
  });
  it("marks nothing for a same-day flight", () => {
    const { container } = render(PassCard, goes({ start_local: "2026-11-20T08:00", end_local: "2026-11-20T11:00" }));
    expect(container.querySelector("[data-day-shift]")).toBeNull();
  });
  it("marks an overnight arrival as +1 day, with words for a screen reader", () => {
    const { container } = render(PassCard, goes());
    const mark = container.querySelector("[data-day-shift]") as HTMLElement;
    expect(mark).toHaveTextContent("+1 day");
    expect(mark).toHaveTextContent("1 day later on the calendar than departure");
  });
  it("marks a flight that lands a calendar day earlier across the date line as −1 day, and one that lands two days later as +2 days", () => {
    const west = render(PassCard, goes({ origin: "SYD", destination: "LAX", start_local: "2026-11-20T10:00", start_zone: "Australia/Sydney", end_local: "2026-11-19T06:00", end_zone: "America/Los_Angeles" }));
    expect(west.container.querySelector("[data-day-shift]")).toHaveTextContent("−1 day");
    west.unmount();
    const east = render(PassCard, goes({ origin: "LAX", destination: "SYD", start_local: "2026-11-20T22:00", start_zone: "America/Los_Angeles", end_local: "2026-11-22T06:00", end_zone: "Australia/Sydney" }));
    expect(east.container.querySelector("[data-day-shift]")).toHaveTextContent("+2 days");
  });
  it("says the times are local to each airport and names each zone for a screen reader", () => {
    const { container } = render(PassCard, goes());
    expect(screen.getByText("Times are local to each airport")).toBeInTheDocument();
    expect(container.textContent).toContain(`(${NY})`);
    expect(container.textContent).toContain(`(${LON})`);
  });
  it("writes the live line’s clock like the scheduled times", () => {
    flightStatus.list = list();
    render(PassCard, goes());
    expect(screen.getByText(/as of \d?\d:\d\d [AP]M/)).toBeInTheDocument();
  });
  it("keeps the day marker, the local-times note and the zones when the page supplies its own time rows", () => {
    const { container } = render(PassCard, { ...goes(), times });
    const mark = container.querySelector("[data-day-shift]") as HTMLElement;
    expect(mark).toHaveTextContent("+1 day");
    expect(screen.getByText(/Times are local to each airport/)).toBeInTheDocument();
    expect(container.textContent).toContain(`departs ${NY}, arrives ${LON}`);
    expect(screen.getByText("custom rows")).toBeInTheDocument();
  });
  it("asks for airport names in a way that survives leaving the page", async () => {
    render(PassCard, goes());
    await screen.findByText("London");
    expect(vi.mocked(api).mock.calls.every(([, opts]) => (opts as { keep?: boolean } | undefined)?.keep === true)).toBe(true);
  });
});
