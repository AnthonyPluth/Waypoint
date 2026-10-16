// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import { createRawSnippet } from "svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import { forgetAirportZones } from "$lib/airport-zones";
import type { FlightStatus, FlightStatusList, Segment } from "$lib/api-types";
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
    expect(screen.getByText("Under way, arrives in 3 h 35 min")).toBeInTheDocument();
  });
  it("labels the route line plainly, with no schedule caveat", () => {
    const { container } = render(PassCard, goes());
    expect(screen.getByRole("img", { name: "Route" })).toBeInTheDocument();
    expect(container.querySelector("[data-schedule-label]")).toBeNull();
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

  it("puts the plane on the full-width route line between the codes, with the names in a row of their own", () => {
    const { container } = render(PassCard, { segment: flight, now: midway });
    const grid = screen.getByRole("img", { name: "Route" }).parentElement as HTMLElement;
    const [from, line, to, names] = [...grid.children];
    expect(from.textContent).toBe("JFK");
    expect(line).toHaveAttribute("role", "img");
    expect(to.textContent).toBe("LHR");
    expect(names).toHaveClass("col-span-3");
    expect(container.querySelector("[data-schedule-label]")).toBeNull();
    expect(screen.queryByText("Based on schedule")).toBeNull();
  });
  it("reads landed and under way from the clock when live status is unavailable, stale or offline", () => {
    const offline = vi.spyOn(navigator, "onLine", "get");
    for (const [setup, list_] of [["none", null], ["stale", list({ statuses: [status({ state: "departed", fetched_at: new Date(dep - 6 * HOUR).toISOString() })] })], ["offline", fresh({ state: "departed" })]] as const) {
      flightStatus.list = list_;
      offline.mockReturnValue(setup !== "offline");
      const { container, unmount } = render(PassCard, { segment: flight, now: arr + HOUR });
      const text = container.querySelector("[data-headline]")?.textContent;
      expect(text, setup).toBe("Landed");
      unmount();
    }
    offline.mockRestore();
  });
  it("keeps the plane at the destination for a landed status however old, and at the clock's place for a stale non-terminal one", () => {
    const old = new Date(dep - 30 * 24 * HOUR).toISOString();
    flightStatus.list = list({ statuses: [status({ state: "landed", fetched_at: old })] });
    const landed = render(PassCard, { segment: flight, now: dep - HOUR });
    expect(progressOf(landed.container)).toBe("1");
    landed.unmount();
    flightStatus.list = list({ statuses: [status({ state: "departed", fetched_at: old })] });
    const stale = render(PassCard, { segment: flight, now: midway });
    expect(progressOf(stale.container)).not.toBe("1");
    expect(stale.container.querySelector("[data-headline]")?.textContent).toMatch(/^Under way/);
  });
  it("parks a past flight with a cancelled booking at the start, with no airline status", () => {
    const { container } = render(PassCard, { segment: { ...flight, status: "cancelled" }, now: arr + 40 * 24 * HOUR });
    expect(container.querySelector("[data-headline]")?.textContent).toBe("Cancelled");
    expect(progressOf(container)).toBe("0");
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
  });
  it("says landed, with the plane at the end, when live status does", () => {
    flightStatus.list = fresh({ state: "landed", arr_actual: "2026-11-21T07:03" });
    const { container } = render(PassCard, { segment: flight, now: arr - 2 * HOUR });
    expect(container.querySelector("[data-headline]")?.textContent).toBe("Landed");
    expect(progressOf(container)).toBe("1");
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
  it("names each zone for a screen reader and no longer prints a local-times note", () => {
    const { container } = render(PassCard, goes());
    expect(container.textContent).not.toContain("Times are local to each airport");
    expect(container.querySelector("[data-zone-note]")).toBeNull();
    expect(container.textContent).toContain(`(${NY})`);
    expect(container.textContent).toContain(`(${LON})`);
  });
  it("writes the live line’s clock like the scheduled times", () => {
    flightStatus.list = list();
    render(PassCard, goes());
    expect(screen.getByText(/as of \d?\d:\d\d [AP]M/)).toBeInTheDocument();
  });
  it("keeps the day marker and the zones when the page supplies its own time rows", () => {
    const { container } = render(PassCard, { ...goes(), times });
    const mark = container.querySelector("[data-day-shift]") as HTMLElement;
    expect(mark).toHaveTextContent("+1 day");
    expect(container.textContent).not.toContain("Times are local to each airport");
    expect(container.textContent).toContain(`departs ${NY}, arrives ${LON}`);
    expect(screen.getByText("custom rows")).toBeInTheDocument();
  });
  it("asks for airport names in a way that survives leaving the page", async () => {
    render(PassCard, goes());
    await screen.findByText("London");
    expect(vi.mocked(api).mock.calls.every(([, opts]) => (opts as { keep?: boolean } | undefined)?.keep === true)).toBe(true);
  });
});

describe("the boarding-pass variant", () => {
  const board = (extra: Record<string, unknown> = {}, seg: object = {}) => ({ segment: { ...flight, ...seg }, now: dep - 3 * HOUR, boarding: true, tripName: "Trip to London", eyebrow: "Next up", ...extra });
  const plane = (container: HTMLElement) => container.querySelector("[data-plane]") as HTMLElement;

  it("shows the eyebrow, the trip name, the chips and the countdown in the header", () => {
    render(PassCard, board());
    expect(screen.getByText("Next up")).toBeInTheDocument();
    expect(screen.getByText(/Trip to London/)).toBeInTheDocument();
    expect(screen.getByText("Confirmed")).toBeInTheDocument();
    expect(screen.getByText("Check-in is open, departs in 3 h")).toBeInTheDocument();
    expect(document.querySelector("[data-countdown] strong")).toHaveTextContent("3 h");
  });
  it.each(["Under way", "In the air", "Delayed", "Latest flight", "Next up"])("renders the %s eyebrow", (eyebrow) => {
    render(PassCard, board({ eyebrow }));
    expect(screen.getByText(eyebrow)).toBeInTheDocument();
  });
  it("pulses the dot only where asked", () => {
    const quiet = render(PassCard, board());
    expect(quiet.container.querySelector("[data-dot]")).not.toHaveClass("animate-pulse");
    quiet.unmount();
    const live = render(PassCard, board({ pulse: true }));
    expect(live.container.querySelector("[data-dot]")).toHaveClass("animate-pulse", "motion-reduce:animate-none");
  });
  it("puts the plane at the middle of the line until the flight is in the air", () => {
    const { container } = render(PassCard, board());
    expect(screen.getByRole("img", { name: "Route" }).dataset.progress).toBe("0.5");
    expect(plane(container).style.left).toBe("50%");
  });
  it("moves the plane along the line with routeProgress in the air", () => {
    const first = render(PassCard, board({ now: dep + (arr - dep) / 4 }));
    expect(screen.getByRole("img", { name: "Route" }).dataset.progress).toBe("0.25");
    expect(plane(first.container).style.left).toBe("25%");
    first.unmount();
    const later = render(PassCard, board({ now: dep + ((arr - dep) * 3) / 4 }));
    expect(plane(later.container).style.left).toBe("75%");
  });
  it("shows both codes, the length, nonstop, and each time at its own airport with the day shift", async () => {
    render(PassCard, board());
    expect(screen.getByText("JFK")).toBeInTheDocument();
    expect(screen.getByText("LHR")).toBeInTheDocument();
    expect(screen.getByText("American Airlines AA 101")).toBeInTheDocument();
    expect(screen.getByText("7 h 10 min · nonstop")).toBeInTheDocument();
    expect(screen.getByText("7:00 PM")).toBeInTheDocument();
    expect(screen.getByText("7:10 AM")).toBeInTheDocument();
    expect(await screen.findByText("Fri, Nov 20 · New York time")).toBeInTheDocument();
    expect(await screen.findByText("Sat, Nov 21 · London time")).toBeInTheDocument();
    expect(document.querySelector("[data-day-shift]")).toHaveTextContent("+1");
  });
  it("shows no countdown for a cancelled booking, and strikes the route", () => {
    const { container } = render(PassCard, board({}, { status: "cancelled" }));
    expect(container.querySelector("[data-countdown]")).toBeNull();
    expect(screen.getByText("Cancelled")).toBeInTheDocument();
    expect(container.querySelector("[data-code='origin']")?.parentElement).toHaveClass("line-through");
  });
  it("shows no countdown for a booking without a time", () => {
    const { container } = render(PassCard, board({}, { details: { flight_number: "AA 101", time_unknown: "yes" } }));
    expect(container.querySelector("[data-countdown]")).toBeNull();
    expect(screen.getAllByText("Time not recorded")).toHaveLength(2);
  });
  it("reads Not yet for a gate that isn't known, and the gate once it is", () => {
    const first = render(PassCard, board());
    expect(screen.getByText("Gate").closest("div")).toHaveTextContent("Not yet");
    expect(screen.getByText("Not yet")).toHaveClass("text-muted-foreground");
    first.unmount();
    flightStatus.list = list();
    render(PassCard, board());
    expect(screen.getByText("Gate").closest("div")).toHaveTextContent("B24");
  });
  it("puts the code with its copy button, the details and the travellers in the stub", async () => {
    render(PassCard, board({}, { details: { flight_number: "AA 101", terminal: "8", cabin: "Economy", seat: "14C, 14D" }, travelers: [{ id: 1, person_id: 1, name: "Jane Doe", seat: null }, { id: 2, person_id: 2, name: "Mia Doe", seat: null }] }));
    await userEvent.click(screen.getByRole("button", { name: "Copy confirmation code KQ7M2X" }));
    expect(toast.success).toHaveBeenCalledWith("Copied");
    for (const label of ["Terminal", "Seats", "Cabin"]) expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText("14C, 14D")).toBeInTheDocument();
    expect(screen.getByTestId("avatar-stack")).toHaveAccessibleName("Jane Doe, Mia Doe");
    expect(screen.getByText("Jane & Mia")).toBeInTheDocument();
  });
  it("shows the app link as the filled primary action before the page's own buttons", () => {
    const footer = createRawSnippet(() => ({ render: () => "<a href='#trip/1'>Open trip</a>" }));
    render(PassCard, board({ footer }, { links: { app: "https://example.test/app", open: null, open_kind: null, directions: null, call: null } }));
    const primary = screen.getByRole("link", { name: "Check in" });
    expect(primary).toHaveClass("bg-primary");
    expect(primary.compareDocumentPosition(screen.getByRole("link", { name: "Open trip" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
  it("keeps the live status between the route and the actions", () => {
    const live = createRawSnippet(() => ({ render: () => "<p>live area</p>" }));
    const footer = createRawSnippet(() => ({ render: () => "<a href='#trip/1'>Open trip</a>" }));
    render(PassCard, board({ live, footer }));
    const area = screen.getByText("live area");
    expect(screen.getByText("JFK").compareDocumentPosition(area) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(area.compareDocumentPosition(screen.getByRole("link", { name: "Open trip" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
  it("leaves loyalty and Known Traveler numbers off the card", () => {
    render(PassCard, board({}, { details: { flight_number: "AA 101", loyalty: "AA1234567", known_traveler: "TT12345678" } }));
    expect(document.body.textContent).not.toMatch(/AA1234567|TT12345678/);
  });

  describe("other kinds", () => {
    const NOW = Date.UTC(2026, 10, 21, 8);
    const stay = segment({ id: 2, kind: "hotel", provider: "Marriott", origin: "Harbour Hotel", destination: null, start_local: "2026-11-21T15:00", start_zone: LON, end_local: "2026-11-27T10:00", end_zone: LON,
      confirmation: "H88231", details: { address: "1 Quay Street, London", room: "412" }, travelers: [] });
    const take = (seg: Segment, extra: Record<string, unknown> = {}) => ({ segment: seg, now: NOW, boarding: true, condensed: true, eyebrow: "Next up", tripName: "Trip to London", ...extra });

    it("shows a stay's name with check-in and check-out, its room, and no empty traveller stack", async () => {
      render(PassCard, take(stay));
      expect(screen.getByRole("heading", { name: "Harbour Hotel" })).toBeInTheDocument();
      expect(screen.getByText("Check-in")).toBeInTheDocument();
      expect(screen.getByText("Check-out")).toBeInTheDocument();
      expect(screen.getByText("3:00 PM")).toBeInTheDocument();
      expect(screen.getByText("10:00 AM")).toBeInTheDocument();
      expect(screen.getByText("412")).toBeInTheDocument();
      expect(screen.getByText("Check-in in 7 h")).toBeInTheDocument();
      expect(screen.queryByTestId("avatar-stack")).toBeNull();
      expect(await screen.findByText("Sat, Nov 21 · London time")).toBeInTheDocument();
    });
    it("shows a rental car's pick-up and drop-off", () => {
      const car = segment({ id: 3, kind: "car", provider: "Hertz", origin: "Heathrow", destination: null, start_local: "2026-11-21T09:00", start_zone: LON, end_local: "2026-11-24T09:00", end_zone: LON, details: { car_class: "Compact" } });
      render(PassCard, take(car));
      expect(screen.getByRole("heading", { name: "Hertz · Heathrow" })).toBeInTheDocument();
      expect(screen.getByText("Pick-up")).toBeInTheDocument();
      expect(screen.getByText("Drop-off")).toBeInTheDocument();
      expect(screen.getByText("Compact")).toBeInTheDocument();
    });
    it("shows a train's stations in the code positions with a train on the line", () => {
      const train = segment({ id: 4, kind: "train", provider: "Eurostar", origin: "London St Pancras", destination: "Paris Nord", start_local: "2026-11-21T10:00", start_zone: LON, end_local: "2026-11-21T13:20", end_zone: "Europe/Paris", details: {} });
      const { container } = render(PassCard, take(train));
      expect(screen.getByRole("heading", { name: "London St Pancras → Paris Nord" })).toBeInTheDocument();
      expect(container.querySelector("[data-code='origin']")).toHaveTextContent("London St Pancras");
      expect(container.querySelector("[data-code='destination']")).toHaveTextContent("Paris Nord");
      expect(screen.queryByText("Gate")).toBeNull();
    });
    it("shows parking's entry and exit, and a cruise's embarkation", () => {
      const lot = segment({ id: 5, kind: "parking", provider: "Example Parking", origin: "Example Lot", destination: null, start_local: "2026-11-21T09:00", start_zone: NY, end_local: "2026-11-28T09:00", end_zone: NY, details: {} });
      const first = render(PassCard, take(lot));
      expect(screen.getByRole("heading", { name: "Example Lot" })).toBeInTheDocument();
      expect(screen.getByText("Entry")).toBeInTheDocument();
      expect(screen.getByText("Exit")).toBeInTheDocument();
      first.unmount();
      const ship = segment({ id: 6, kind: "cruise", provider: "Example Cruises", origin: "Miami", destination: null, start_local: "2026-11-22T16:00", start_zone: NY, end_local: "2026-11-29T07:00", end_zone: NY, details: { ship: "Example Star", deck: "9" } });
      render(PassCard, take(ship));
      expect(screen.getByText("Embarks")).toBeInTheDocument();
      expect(screen.getByText("Disembarks")).toBeInTheDocument();
      expect(screen.getByText("Example Star")).toBeInTheDocument();
    });
    it("shows no countdown for a cancelled stay and strikes its name", () => {
      const { container } = render(PassCard, take({ ...stay, status: "cancelled" }));
      expect(container.querySelector("[data-countdown]")).toBeNull();
      expect(screen.getByRole("heading", { name: "Harbour Hotel" })).toHaveClass("line-through");
    });
  });
});
