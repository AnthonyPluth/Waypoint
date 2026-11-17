// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import { forgetAirportZones } from "$lib/airport-zones";
import type { FlightStatus, FlightStatusList, Trip } from "$lib/api-types";
import { app, route } from "$lib/app.svelte";
import { flightStatus } from "$lib/flightstatus.svelte";
import { viewport } from "$lib/phone.svelte";
import { instant } from "$lib/trips";
import { segment, trip } from "../test/fixtures";
import FlightStatusPage from "./FlightStatus.svelte";

const notFound = () => Object.assign(new Error("Not found"), { status: 404 });

const DEN = "America/Denver";
const AIRPORTS: Record<string, object> = {
  DEN: { code: "DEN", name: "Denver International Airport", city: "Denver", country: "US", zone: DEN },
  GJT: { code: "GJT", name: "Grand Junction Regional Airport", city: "Grand Junction", country: "US", zone: DEN },
  MTJ: { code: "MTJ", name: "Montrose Regional Airport", city: "Montrose", country: "US", zone: DEN },
  JFK: { code: "JFK", name: "John F. Kennedy International Airport", city: "New York", country: "US", zone: "America/New_York" },
  LHR: { code: "LHR", name: "Heathrow Airport", city: "London", country: "GB", zone: "Europe/London" },
};

const booked = segment({
  id: 3, trip_id: 7, provider: "Example Air", origin: "DEN", destination: "GJT", start_local: "2025-06-12T09:40", start_zone: DEN, end_local: "2025-06-12T10:52", end_zone: DEN,
  details: { flight_number: "EA 214", cabin: "Economy" },
  travelers: [{ id: 1, person_id: null, name: "Ada Brook", seat: "12A" }, { id: 2, person_id: null, name: "June Brook", seat: "12B" }],
});
const loop: Trip = trip([booked], { id: 7, name: "Four Corners loop" });
const at = (local: string) => instant(local, DEN);
const status = (now: number, minutesAgo: number, extra: Partial<FlightStatus> = {}): FlightStatus => ({
  segment_id: 3, state: "scheduled", origin: "DEN", destination: "GJT", dep_scheduled: "2025-06-12T09:40", dep_estimated: null, dep_actual: null, dep_zone: DEN,
  dep_terminal: null, dep_gate: null, arr_scheduled: "2025-06-12T10:52", arr_estimated: null, arr_actual: null, arr_zone: DEN, arr_terminal: null, arr_gate: null,
  delay_minutes: null, fetched_at: new Date(now - minutesAgo * 60_000).toISOString(), ...extra,
});
const listOf = (statuses: FlightStatus[], extra: Partial<FlightStatusList> = {}): FlightStatusList => ({ enabled: true, month: "2025-06", used: 3, limit: 400, paused: null, statuses, ...extra });

const NOW = {
  scheduled: at("2025-06-09T08:00"), boarding: at("2025-06-12T09:15"), delayed: at("2025-06-12T08:50"), air: at("2025-06-12T10:14"),
  landed: at("2025-06-12T10:55"), cancelled: at("2025-06-12T08:30"), diverted: at("2025-06-12T10:20"), none: at("2025-06-02T08:00"),
};
const inTheAir = (now: number, extra: Partial<FlightStatus> = {}) => status(now, 1, { state: "departed", dep_actual: "2025-06-12T09:46", arr_estimated: "2025-06-12T10:52", arr_terminal: "1", arr_gate: "A3", ...extra });

let held: Trip;
let statuses: FlightStatusList;
let refreshed: FlightStatusList | Error | null;

function serve() {
  vi.mocked(api).mockImplementation(async (path, opts) => {
    if (path.startsWith("/api/airports/")) return (AIRPORTS[path.split("/").pop() ?? ""] ?? {}) as never;
    if (path === "/api/flight-status" && opts?.method === "POST") throw new Error("unexpected");
    if (path === "/api/flight-status") return statuses as never;
    if (path.startsWith("/api/flight-status/") && opts?.method === "POST") {
      if (refreshed instanceof Error) throw refreshed;
      return (refreshed ?? statuses) as never;
    }
    if (path === "/api/trips/7") return held as never;
    throw notFound();
  });
}

function open(now: number, list: FlightStatusList, tripValue: Trip = loop, rest = "flight/3") {
  vi.setSystemTime(now);
  held = tripValue;
  statuses = list;
  route.page = "trip"; route.sub = "7"; route.rest = rest; route.query = "";
  return render(FlightStatusPage);
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.mocked(api).mockReset();
  forgetAirportZones();
  flightStatus.list = null;
  flightStatus.problem = "";
  viewport.phone = false;
  app.sessionExpired = false;
  refreshed = null;
  serve();
});

afterEach(() => {
  viewport.phone = false;
  vi.useRealTimers();
});

const words = (el: Element): string => (el.textContent ?? "").replace(/\s+/g, " ").trim();

const headline = async () => (await screen.findByRole("heading", { level: 1 })).textContent;

describe("the headline", () => {
  const CASES: [string, number, FlightStatus | null, string, string][] = [
    ["scheduled", NOW.scheduled, status(NOW.scheduled, 4, { dep_terminal: "B" }), "Departs in 3 days 1 hour", "Scheduled"],
    ["boarding", NOW.boarding, status(NOW.boarding, 2, { dep_terminal: "B", dep_gate: "B14" }), "Boarding now at gate B14", "Boarding"],
    ["delayed", NOW.delayed, status(NOW.delayed, 4, { state: "delayed", dep_estimated: "2025-06-12T10:15", arr_estimated: "2025-06-12T11:27", dep_gate: "B14", delay_minutes: 35 }), "Departs in 1 hour 25 minutes", "Delayed 35 min"],
    ["in the air", NOW.air, inTheAir(NOW.air), "Landing in 38 minutes", "In the air"],
    ["landed", NOW.landed, status(NOW.landed, 1, { state: "landed", dep_actual: "2025-06-12T09:46", arr_actual: "2025-06-12T10:49" }), "Landed 3 minutes early", "Landed"],
    ["landed late", NOW.landed, status(NOW.landed, 1, { state: "landed", dep_actual: "2025-06-12T09:46", arr_actual: "2025-06-12T11:02" }), "Landed 10 minutes late", "Landed"],
    ["landed on time", NOW.landed, status(NOW.landed, 1, { state: "landed", dep_actual: "2025-06-12T09:46", arr_actual: "2025-06-12T10:52" }), "Landed on time", "Landed"],
    ["cancelled", NOW.cancelled, status(NOW.cancelled, 12, { state: "cancelled" }), "Cancelled", "Cancelled"],
    ["diverted", NOW.diverted, status(NOW.diverted, 3, { state: "diverted", destination: "MTJ", dep_actual: "2025-06-12T09:46", arr_estimated: "2025-06-12T10:41" }), "Diverted", "Diverted"],
    ["with no live status yet", NOW.none, null, "Departs in 10 days 1 hour", ""],
  ];

  it.each(CASES)("says what is happening to a flight that is %s", async (_name, now, live, words, pill) => {
    open(now, listOf(live ? [live] : []));
    expect(await headline()).toBe(words);
    expect(screen.getByRole("heading", { level: 1 }).getAttribute("aria-live")).toBe("polite");
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    if (pill) expect(screen.getByText(pill, { exact: false, selector: "span[data-tone]" })).toBeTruthy();
  });

  it("says when live status starts for a flight with none, and keeps its booked times", async () => {
    open(NOW.none, listOf([]));
    await headline();
    expect(screen.getByText("Live status starts 1 day before departure. Until then these are the times on your booking.")).toBeTruthy();
    expect(screen.queryByText(/Updated/)).toBeNull();
  });

  it("says who to contact about a cancelled flight and where a diverted one was headed", async () => {
    open(NOW.cancelled, listOf([status(NOW.cancelled, 12, { state: "cancelled" })]));
    await headline();
    expect(screen.getByText("Contact Example Air about rebooking.")).toBeTruthy();
  });

  it("says where a diverted flight was headed", async () => {
    open(NOW.diverted, listOf([status(NOW.diverted, 3, { state: "diverted", destination: "MTJ", dep_actual: "2025-06-12T09:46", arr_estimated: "2025-06-12T10:41" })]));
    await headline();
    await waitFor(() => expect(screen.getByText("Was headed to Grand Junction.")).toBeTruthy());
  });

  it("changes its words when the status changes, in the same live region", async () => {
    open(NOW.air, listOf([inTheAir(NOW.air)]));
    expect(await headline()).toBe("Landing in 38 minutes");
    const heading = screen.getByRole("heading", { level: 1 });
    flightStatus.list = listOf([status(NOW.air, 1, { state: "landed", dep_actual: "2025-06-12T09:46", arr_actual: "2025-06-12T10:49" })]);
    await waitFor(() => expect(heading.textContent).toBe("Landed 3 minutes early"));
  });
});

describe("a flight in the air", () => {
  it("shows the progress as a bar named Flight progress with its value", async () => {
    open(NOW.air, listOf([inTheAir(NOW.air)]));
    await headline();
    const bar = screen.getByRole("progressbar", { name: "Flight progress" });
    expect(bar.getAttribute("aria-valuemin")).toBe("0");
    expect(bar.getAttribute("aria-valuemax")).toBe("100");
    expect(bar.getAttribute("aria-valuenow")).toBe("42");
  });

  it("has no progress bar for a cancelled flight, and an empty one before departure", async () => {
    const { unmount } = open(NOW.cancelled, listOf([status(NOW.cancelled, 12, { state: "cancelled" })]));
    await headline();
    expect(screen.queryByRole("progressbar", { name: "Flight progress" })).toBeNull();
    unmount();
    open(NOW.scheduled, listOf([status(NOW.scheduled, 4)]));
    await headline();
    expect(screen.getByRole("progressbar", { name: "Flight progress" }).getAttribute("aria-valuenow")).toBe("0");
  });

  it("lists the timeline as Departed, In the air and Lands with scheduled and actual times", async () => {
    open(NOW.air, listOf([inTheAir(NOW.air)]));
    await headline();
    const steps = within(screen.getByRole("list", { name: "Flight timeline" })).getAllByRole("listitem");
    await waitFor(() => expect(words(steps[0])).toContain("Departed Denver"));
    expect(steps.map(words)).toEqual([
      "Departed DenverScheduled 9:40 am 9:46 am",
      "In the air38 m flight time left now",
      "Lands in Grand JunctionScheduled 10:52 am 10:52 am",
    ]);
    expect(steps.map((s) => s.getAttribute("data-dot"))).toEqual(["done", "now", "next"]);
  });

  it("says how the departure and arrival went at desktop width, and where it lands at phone width", async () => {
    const live = inTheAir(NOW.air, { dep_actual: "2025-06-12T09:46", arr_estimated: "2025-06-12T10:52", arr_scheduled: "2025-06-12T10:52" });
    const { unmount } = open(NOW.air, listOf([live]));
    await headline();
    expect(screen.getByText("Departed 6 minutes late. Expected to land on time.")).toBeTruthy();
    unmount();
    viewport.phone = true;
    open(NOW.air, listOf([live]));
    await headline();
    await waitFor(() => expect(screen.getByText("Expected 10:52 am MDT at Grand Junction. Departed 6 minutes late.")).toBeTruthy());
  });

  it("shows the route with the wall-clock times and zones at the airports, never converted", async () => {
    const overseas = segment({
      id: 3, trip_id: 7, provider: "Example Air", origin: "JFK", destination: "LHR", start_local: "2025-06-12T19:00", start_zone: "America/New_York", end_local: "2025-06-13T07:10", end_zone: "Europe/London",
      details: { flight_number: "EA 100" }, travelers: [{ id: 1, person_id: null, name: "Ada Brook", seat: "12A" }],
    });
    const now = instant("2025-06-12T19:00", "America/New_York") + 3 * 3_600_000;
    const live = status(now, 1, { state: "departed", origin: "JFK", destination: "LHR", dep_scheduled: "2025-06-12T19:00", dep_actual: "2025-06-12T19:12", dep_zone: "America/New_York", arr_scheduled: "2025-06-13T07:10", arr_estimated: "2025-06-13T07:05", arr_zone: "Europe/London" });
    open(now, listOf([live]), trip([overseas], { id: 7, name: "Four Corners loop" }));
    await headline();
    const route = document.querySelector("[data-kind='flight']") as HTMLElement;
    expect(within(route).getByText("7:12 pm").closest("time")?.getAttribute("datetime")).toBe("2025-06-12T19:12");
    expect([...route.querySelectorAll("span.font-mono")].map(words).filter((t) => t.includes("scheduled"))).toEqual(["EDT · scheduled 7:00 pm", "GMT+1 · scheduled 7:10 am · +1 day, 1 day later on the calendar than departure"]);
    expect(within(route).getByText("7:05 am").closest("time")?.getAttribute("datetime")).toBe("2025-06-13T07:05");
    const steps = within(screen.getByRole("list", { name: "Flight timeline" })).getAllByRole("listitem");
    expect(words(steps[0])).toContain("Scheduled 7:00 pm 7:12 pm");
    expect(words(steps[2])).toContain("Scheduled 7:10 am 7:05 am");
  });

  it("shows the arrival's later day beside its time on the phone timeline too", async () => {
    const overseas = segment({
      id: 3, trip_id: 7, provider: "Example Air", origin: "JFK", destination: "LHR", start_local: "2025-06-12T19:00", start_zone: "America/New_York", end_local: "2025-06-13T07:10", end_zone: "Europe/London",
      details: { flight_number: "EA 100" }, travelers: [],
    });
    const now = instant("2025-06-12T19:00", "America/New_York") + 3 * 3_600_000;
    viewport.phone = true;
    open(now, listOf([]), trip([overseas], { id: 7, name: "Four Corners loop" }));
    await headline();
    const steps = within(screen.getByRole("list", { name: "Flight timeline" })).getAllByRole("listitem");
    expect(words(steps[2])).toContain("+1 day, 1 day later on the calendar than departure");
    expect(words(steps[0])).not.toContain("+1 day");
  });

  it("shows the arrival facts as a definition list with source markers and a dash for the belt", async () => {
    open(NOW.air, listOf([inTheAir(NOW.air)]));
    await headline();
    const facts = document.querySelector("[data-facts]") as HTMLElement;
    expect(facts.tagName).toBe("DL");
    expect(within(facts).getAllByRole("term").map((t) => t.textContent)).toEqual(["Terminal", "Gate", "Belt"]);
    expect(within(facts).getAllByRole("definition").map((d) => d.textContent)).toEqual(["1", "A3", "—Not known yet"]);
    expect(within(facts).getAllByRole("img", { name: "From live status" })).toHaveLength(3);
    expect(within(facts).queryByRole("img", { name: "From the booking" })).toBeNull();
    expect(screen.getByText("Arrival", { exact: false, selector: ".eyebrow" }).textContent).toBe("Arrival · Grand Junction");
    expect(screen.getByText("The belt appears after landing.")).toBeTruthy();
  });

  it("shows a dash, never a blank, for a gate the status does not have", async () => {
    open(NOW.air, listOf([inTheAir(NOW.air, { arr_terminal: null, arr_gate: null })]));
    await headline();
    const facts = document.querySelector("[data-facts]") as HTMLElement;
    expect(within(facts).getAllByRole("definition").map((d) => d.textContent)).toEqual(["—Not known yet", "—Not known yet", "—Not known yet"]);
    expect(within(facts).getAllByText("Not known yet")).toHaveLength(3);
  });

  it("shows the departure facts before the flight leaves, with the booking's terminal marked as from the booking", async () => {
    const withTerminal = segment({ ...booked, details: { ...booked.details, terminal: "B" } });
    open(NOW.scheduled, listOf([status(NOW.scheduled, 4)]), trip([withTerminal], { id: 7, name: "Four Corners loop" }));
    await headline();
    const facts = document.querySelector("[data-facts]") as HTMLElement;
    expect(within(facts).getAllByRole("term").map((t) => t.textContent)).toEqual(["Terminal", "Gate"]);
    expect(within(facts).getAllByRole("definition").map((d) => d.textContent)).toEqual(["B", "—Not known yet"]);
    expect(within(facts).getAllByRole("img").map((i) => i.getAttribute("aria-label"))).toEqual(["From the booking", "From live status"]);
    expect(screen.getByText("Departure", { exact: false, selector: ".eyebrow" })).toBeTruthy();
  });
});

describe("seats", () => {
  it("lists each traveller's seat and cabin from the booking at desktop width", async () => {
    open(NOW.air, listOf([inTheAir(NOW.air)]));
    await headline();
    const rows = within(screen.getByRole("list", { name: "Seats by traveller" })).getAllByRole("listitem");
    expect(rows.map(words)).toEqual(["Ada BrookSeat 12A · Economy", "June BrookSeat 12B · Economy"]);
    rows.forEach((row) => expect(within(row).getByRole("img", { name: "From the booking" })).toBeTruthy());
    expect(screen.getByText("Seats and cabin come from the booking. Gate, terminal and belt come from live status and can change.")).toBeTruthy();
  });

  it("lists them on one line at phone width", async () => {
    viewport.phone = true;
    open(NOW.air, listOf([inTheAir(NOW.air)]));
    await headline();
    const rows = within(screen.getByRole("list", { name: "Seats by traveller" })).getAllByRole("listitem");
    expect(rows.map(words)).toEqual(["Ada 12A", "June 12B"]);
  });

  it("says a seat is not known yet rather than leaving it out", async () => {
    const unseated = segment({ ...booked, travelers: [{ id: 1, person_id: null, name: "Ada Brook", seat: null }] });
    open(NOW.air, listOf([inTheAir(NOW.air)]), trip([unseated], { id: 7, name: "Four Corners loop" }));
    await headline();
    expect(words(within(screen.getByRole("list", { name: "Seats by traveller" })).getAllByRole("listitem")[0])).toBe("Ada BrookSeat not known yet · Economy");
  });

  it("uses the booking's own seat for a single traveller with no seat of their own", async () => {
    const solo = segment({ ...booked, details: { ...booked.details, seat: "14C" }, travelers: [{ id: 1, person_id: null, name: "Ada Brook", seat: null }] });
    open(NOW.air, listOf([inTheAir(NOW.air)]), trip([solo], { id: 7, name: "Four Corners loop" }));
    await headline();
    expect(words(within(screen.getByRole("list", { name: "Seats by traveller" })).getAllByRole("listitem")[0])).toBe("Ada BrookSeat 14C · Economy");
  });

  it("has no seat list when the booking names no traveller", async () => {
    open(NOW.air, listOf([inTheAir(NOW.air)]), trip([segment({ ...booked, travelers: [] })], { id: 7, name: "Four Corners loop" }));
    await headline();
    expect(screen.queryByRole("list", { name: "Seats by traveller" })).toBeNull();
  });
});

describe("the page", () => {
  it("links back to the trip by its name", async () => {
    open(NOW.air, listOf([inTheAir(NOW.air)]));
    await headline();
    const back = screen.getByRole("link", { name: "Back to Four Corners loop" });
    expect(back.getAttribute("href")).toBe("#trip/7");
  });

  it("names the flight, its provider and its day", async () => {
    open(NOW.air, listOf([inTheAir(NOW.air)]));
    await headline();
    expect(screen.getByText("EA 214")).toBeTruthy();
    expect(screen.getByText("Example Air · Thu Jun 12")).toBeTruthy();
    expect(screen.getByText("In the air", { selector: "span[data-tone]" })).toBeTruthy();
  });

  it("asks the server only for the trip, which answers 404 to someone who cannot see it", async () => {
    vi.mocked(api).mockImplementation(async (path) => { throw path === "/api/trips/7" ? notFound() : new Error("unexpected"); });
    open(NOW.air, listOf([]));
    expect(await screen.findByText("Not found")).toBeTruthy();
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
    expect(screen.queryByRole("progressbar", { name: "Flight progress" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Refresh/ })).toBeNull();
    expect(vi.mocked(api).mock.calls.map(([path]) => path)).not.toContain("/api/flight-status");
  });

  it("says there is no such flight when the trip has no flight with that id", async () => {
    open(NOW.air, listOf([inTheAir(NOW.air)]), loop, "flight/99");
    expect(await screen.findByText("No such flight")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Back to Four Corners loop" }).getAttribute("href")).toBe("#trip/7");
  });

  it("says there is no such flight for a booking that is not a flight", async () => {
    const stay = segment({ id: 3, trip_id: 7, kind: "hotel", origin: "Harbour Hotel", destination: null });
    open(NOW.air, listOf([]), trip([stay], { id: 7, name: "Four Corners loop" }));
    expect(await screen.findByText("No such flight")).toBeTruthy();
  });

  it("says a flight with no time recorded has no live status to show", async () => {
    const untimed = segment({ ...booked, details: { ...booked.details, time_unknown: "yes" } });
    open(NOW.air, listOf([]), trip([untimed], { id: 7, name: "Four Corners loop" }));
    expect(await screen.findByText("This flight has no time recorded yet, so there’s no live status to show.")).toBeTruthy();
  });

  it("says when the paused updates resume and offers no Refresh", async () => {
    open(NOW.air, listOf([inTheAir(NOW.air)], { paused: { until: "2025-07-01T00:00:00Z", reason: "limit" } }));
    await headline();
    expect((await screen.findByRole("status")).textContent).toContain("Live updates paused until");
    expect(screen.queryByRole("button", { name: /Refresh/ })).toBeNull();
  });

  it("has no Refresh when live status is off", async () => {
    open(NOW.air, listOf([], { enabled: false }));
    await headline();
    expect(screen.queryByRole("button", { name: /Refresh/ })).toBeNull();
  });
});

describe("connectivity", () => {
  it("stops trusting a cached estimate when the browser goes offline, and trusts it again when it is back", async () => {
    const onLine = vi.spyOn(navigator, "onLine", "get");
    onLine.mockReturnValue(true);
    open(NOW.air, listOf([inTheAir(NOW.air, { arr_estimated: "2025-06-12T11:10" })]));
    expect(await headline()).toBe("Landing in 56 minutes");
    onLine.mockReturnValue(false);
    window.dispatchEvent(new Event("offline"));
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Landing in 38 minutes"));
    onLine.mockReturnValue(true);
    window.dispatchEvent(new Event("online"));
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Landing in 56 minutes"));
    onLine.mockRestore();
  });

  it("stops listening when the page is gone", async () => {
    const remove = vi.spyOn(window, "removeEventListener");
    const { unmount } = open(NOW.air, listOf([inTheAir(NOW.air)]));
    await headline();
    unmount();
    expect(remove.mock.calls.map(([name]) => name)).toEqual(expect.arrayContaining(["online", "offline"]));
    remove.mockRestore();
  });
});

describe("Refresh", () => {
  it("is a button with the word Refresh at desktop width", async () => {
    open(NOW.air, listOf([inTheAir(NOW.air)]));
    await headline();
    expect(screen.getByRole("button", { name: "Refresh" }).textContent).toBe("Refresh");
    expect(screen.queryByRole("button", { name: "Refresh flight status" })).toBeNull();
  });

  it("is an icon button named Refresh flight status at phone width", async () => {
    viewport.phone = true;
    open(NOW.air, listOf([inTheAir(NOW.air)]));
    await headline();
    const button = screen.getByRole("button", { name: "Refresh flight status" });
    expect(button.textContent?.trim()).toBe("");
    expect(screen.queryByRole("button", { name: "Refresh" })).toBeNull();
  });

  it("asks the status service for this flight and shows the new answer", async () => {
    open(NOW.air, listOf([inTheAir(NOW.air)]));
    expect(await headline()).toBe("Landing in 38 minutes");
    refreshed = listOf([status(NOW.air, 0, { state: "landed", dep_actual: "2025-06-12T09:46", arr_actual: "2025-06-12T10:49" })]);
    await userEvent.setup({ advanceTimers: () => {} }).click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Landed 3 minutes early"));
    expect(vi.mocked(api).mock.calls.find(([path, opts]) => path === "/api/flight-status/3" && opts?.method === "POST")).toBeTruthy();
    expect(screen.queryByText(/Couldn’t refresh/)).toBeNull();
  });

  it("keeps the old data when it fails and says when it was last updated, never just now", async () => {
    const { toast } = await import("svelte-sonner");
    open(NOW.air, listOf([inTheAir(NOW.air)]));
    expect(await headline()).toBe("Landing in 38 minutes");
    expect(screen.getByText("Updated 1 min ago · live status")).toBeTruthy();
    refreshed = new Error("Couldn’t refresh the status");
    await userEvent.setup({ advanceTimers: () => {} }).click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(screen.getByText(/^Couldn’t refresh\. Last updated /)).toBeTruthy());
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Landing in 38 minutes");
    expect(within(screen.getByRole("list", { name: "Flight timeline" })).getAllByRole("listitem")).toHaveLength(3);
    expect(screen.queryByText(/just now/)).toBeNull();
    expect(toast.error).toHaveBeenCalledWith("Couldn’t refresh the status");
    expect(screen.getByRole("button", { name: "Refresh" }).hasAttribute("disabled")).toBe(false);
  });

  it("does not say just now even when the data is under a minute old", async () => {
    open(NOW.air, listOf([status(NOW.air, 0, { state: "departed", dep_actual: "2025-06-12T09:46", arr_estimated: "2025-06-12T10:52" })]));
    await headline();
    expect(screen.queryByText(/just now/)).toBeNull();
    expect(screen.getByText("Updated less than a minute ago · live status")).toBeTruthy();
  });

  it("says when no status was found for the flight", async () => {
    const { toast } = await import("svelte-sonner");
    open(NOW.none, listOf([]));
    await headline();
    refreshed = listOf([]);
    await userEvent.setup({ advanceTimers: () => {} }).click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith("No live status found for this flight yet."));
  });
});
