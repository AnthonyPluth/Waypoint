// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import { flightStatus } from "$lib/flightstatus.svelte";
import { segment, trip } from "../test/fixtures";
import Upcoming from "./Upcoming.svelte";

const NY = "America/New_York", LON = "Europe/London";
const outbound = segment({ id: 1 });
const stay = segment({ id: 2, kind: "hotel", provider: "Marriott", origin: "Harbour Hotel", destination: null, start_local: "2026-11-21T15:00", start_zone: LON,
  end_local: "2026-11-27T10:00", end_zone: LON, confirmation: "H88231", details: { address: "1 Quay Street, London" } });
const home = segment({ id: 3, origin: "LHR", destination: "JFK", start_local: "2026-11-27T11:30", start_zone: LON, end_local: "2026-11-27T14:35", end_zone: NY });
const london = trip([outbound, stay, home]);
const delayed = { enabled: true, month: "2026-11", used: 3, limit: 400, paused: null, statuses: [{
  segment_id: 1, state: "delayed", origin: "JFK", destination: "LHR", dep_scheduled: "2026-11-20T19:00", dep_estimated: "2026-11-20T19:50",
  dep_actual: null, dep_zone: "America/New_York", dep_terminal: "7", dep_gate: "B24", arr_scheduled: "2026-11-21T07:10", arr_estimated: "2026-11-21T08:05",
  arr_actual: null, arr_zone: "Europe/London", arr_terminal: null, arr_gate: null, delay_minutes: 50, fetched_at: "2026-11-20T14:05:00+00:00" }] };

beforeEach(() => { vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] }); vi.mocked(api).mockReset(); });
afterEach(() => { vi.useRealTimers(); flightStatus.list = null; });

const serve = (trips: unknown[], guests: unknown[] = []) =>
  vi.mocked(api).mockImplementation(async (path) => (path === "/api/people/claim-suggestions" ? { guests } : { trips }));
const at = (iso: string) => vi.setSystemTime(new Date(iso));

describe("Upcoming", () => {
  it("says there are no trips yet, without making any up", async () => {
    serve([]);
    render(Upcoming);
    expect(screen.getByRole("heading", { name: "Upcoming" })).toBeInTheDocument();
    expect(await screen.findByText(/No trips yet — they’ll appear here once Waypoint can read your confirmation emails, or when you add one\./)).toBeInTheDocument();
  });

  it("asks a member with no trips whether they are one of the matching guests, and links the one they pick", async () => {
    const mia = { id: 2, display_name: "Mia Doe", first_name: null, legal_name: null, aliases: [], member: false, links: [] };
    serve([], [mia]);
    render(Upcoming);
    expect(await screen.findByRole("heading", { name: "Are you one of these?" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "This is me: Mia Doe" }));
    const dialog = await screen.findByRole("dialog", { name: "Link Mia Doe to you?" });
    expect(dialog).toHaveTextContent(/can’t be undone in Waypoint/);
    serve([london], []);
    await userEvent.click(within(dialog).getByRole("button", { name: "This is me" }));
    expect(api).toHaveBeenCalledWith("/api/people/2/claim", { method: "POST" });
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Are you one of these?" })).toBeNull());
  });

  it("None of these hides the suggestion", async () => {
    serve([], [{ id: 2, display_name: "Mia Doe", first_name: null, legal_name: null, aliases: [], member: false, links: [] }]);
    render(Upcoming);
    await userEvent.click(await screen.findByRole("button", { name: "None of these" }));
    expect(api).toHaveBeenCalledWith("/api/people/claim-suggestions/dismiss", { method: "POST" });
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Are you one of these?" })).toBeNull());
    expect(screen.getByRole("heading", { name: "No trips yet" })).toBeInTheDocument();
  });

  it("offers nothing when no guest matches, or when there are trips", async () => {
    serve([]);
    render(Upcoming);
    await screen.findByRole("heading", { name: "No trips yet" });
    expect(screen.queryByRole("heading", { name: "Are you one of these?" })).toBeNull();
  });

  it("leads with the next segment: countdown, flight, departure time, terminal, and a code to tap and copy", async () => {
    at("2026-11-20T09:00:00-05:00");
    serve([london]);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR" })).closest("section")!;
    expect(within(card).getByText("Next up")).toBeInTheDocument();
    expect(within(card).getByText("Check-in is open, departs in 10 h")).toBeInTheDocument();
    expect(within(card).getByText("American Airlines AA 101")).toBeInTheDocument();
    expect(within(card).getAllByText("7:00 PM")).toHaveLength(2);
    expect(within(card).getByText("8")).toBeInTheDocument();
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(within(card).getByRole("button", { name: "Copy confirmation code KQ7M2X" }));
    expect(await navigator.clipboard.readText()).toBe("KQ7M2X");
  });

  it("counts down to check-in until it opens, 24 hours before departure", async () => {
    at("2026-11-18T09:00:00-05:00");
    serve([london]);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR" })).closest("section")!;
    expect(within(card).getByText("Next up")).toBeInTheDocument();
    expect(within(card).getByText("Check-in opens in 1 day 10 h")).toBeInTheDocument();
  });

  it("puts the plane on the route line from the booked times when the flight is under way", async () => {
    at("2026-11-20T22:35:00-05:00");
    serve([london]);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR" })).closest("section")!;
    expect(within(card).getByText("Under way")).toBeInTheDocument();
    expect(within(card).getByRole("img", { name: /booked times/ }).dataset.progress).toBe("0.5");
    expect(within(card).getByText("Under way, arrives in 3 h 35 min")).toBeInTheDocument();
  });

  it("leads with the card’s code first, then the route and the times at each airport", async () => {
    at("2026-11-20T09:00:00-05:00");
    serve([london]);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR" })).closest("section")!;
    expect(within(card).getAllByRole("button")[0]).toHaveAccessibleName("Copy confirmation code KQ7M2X");
    expect(within(card).getByText("JFK")).toBeInTheDocument();
    expect(within(card).getByText("LHR")).toBeInTheDocument();
    expect(within(card).getByText("Confirmed")).toBeInTheDocument();
  });

  it("shows a booking’s brand logo on the Next up card and in the day-by-day list, and no image for one without", async () => {
    at("2026-11-20T09:00:00-05:00");
    serve([trip([segment({ id: 1, logo: "/api/segments/1/logo" }), stay, home])]);
    const { container } = render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR" })).closest("section")!;
    expect(card.querySelector("img")?.getAttribute("src")).toBe("/api/segments/1/logo");
    expect([...container.querySelectorAll("img")].map((i) => i.getAttribute("src"))).toEqual(["/api/segments/1/logo", "/api/segments/1/logo"]);
  });

  it("shows the flight’s live status on the Next up card", async () => {
    at("2026-11-20T09:00:00-05:00");
    vi.mocked(api).mockImplementation(async (path: string) => (path === "/api/flight-status" ? delayed : { trips: [london] }) as never);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR" })).closest("section")!;
    expect(await within(card).findByTestId("flight-status")).toHaveTextContent("Delayed 50 min");
    expect(within(card).getByTestId("flight-status")).toHaveTextContent("Terminal 7 · Gate B24");
  });

  it("shows a flight with no times by its day, with no countdown and no flight status", async () => {
    at("2026-11-18T09:00:00-05:00");
    const untimedTrip = trip([segment({ id: 9, origin: "SEA", destination: "SFO", start_local: "2026-11-20T00:00", start_zone: "America/Los_Angeles",
      end_local: "2026-11-20T00:00", end_zone: "America/Los_Angeles", details: { flight_number: "AS 2002", time_unknown: "yes" } })]);
    vi.mocked(api).mockImplementation(async (path: string) => (path === "/api/flight-status" ? delayed : { trips: [untimedTrip] }) as never);
    render(Upcoming);
    expect(await screen.findByText("time not recorded")).toBeInTheDocument();
    expect(document.querySelector("[data-countdown]")).toBeNull();
    expect(screen.queryByText("Next up")).toBeNull();
    expect(screen.queryByTestId("flight-status")).toBeNull();
  });

  it("says it's departing now, not \"in now\", in the last minute", async () => {
    at("2026-11-20T18:59:40-05:00");
    serve([london]);
    render(Upcoming);
    expect(await screen.findByText("Check-in is open, departing now")).toBeInTheDocument();
  });

  it("calls a flight in the air under way, and counts down to landing", async () => {
    at("2026-11-21T02:00:00-05:00");
    serve([london]);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR" })).closest("section")!;
    expect(within(card).getByText("Under way")).toBeInTheDocument();
    expect(within(card).getByText("Under way, arrives in 10 min")).toBeInTheDocument();
  });

  it("leads with a hotel's address and check-in time once the flight is behind", async () => {
    at("2026-11-21T08:00:00Z");
    serve([trip([outbound, stay])]);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "Harbour Hotel" })).closest("section")!;
    expect(within(card).getByText("Check-in in 7 h")).toBeInTheDocument();
    expect(within(card).getByText("1 Quay Street, London", { selector: "dd" })).toBeInTheDocument();
    expect(within(card).getByText("3:00 PM")).toBeInTheDocument();
  });

  it("lists the trip day by day, with the stay's check-out on its last day", async () => {
    at("2026-11-20T09:00:00-05:00");
    serve([london]);
    render(Upcoming);
    const days = await screen.findByRole("list", { name: "Trip to London, day by day" });
    expect(within(days).getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual(["Fri, Nov 20 · Today", "Sat, Nov 21", "Fri, Nov 27"]);
    expect(within(days).getByText("Check-out: Harbour Hotel")).toBeInTheDocument();
  });

  it("links each booking in the day-by-day list, and the Next up card, to that booking on its trip", async () => {
    at("2026-11-20T09:00:00-05:00");
    serve([london]);
    render(Upcoming);
    const days = await screen.findByRole("list", { name: "Trip to London, day by day" });
    expect(within(days).getByRole("link", { name: "Harbour Hotel" })).toHaveAttribute("href", "#trip/1?segment=2");
    expect(within(days).getByRole("link", { name: "Check-out: Harbour Hotel" })).toHaveAttribute("href", "#trip/1?segment=2");
    expect(within(days).getByRole("link", { name: "JFK → LHR" })).toHaveAttribute("href", "#trip/1?segment=1");
    expect(screen.getByRole("link", { name: "Open Trip to London" })).toHaveAttribute("href", "#trip/1?segment=1");
  });

  it("shows a time at its place and, in brackets, yours when your zone differs", async () => {
    at("2026-11-20T09:00:00-05:00");
    serve([london]);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR" })).closest("section")!;
    expect(within(card).getByText("7:10 AM")).toBeInTheDocument();
  });

  it("says nothing is coming up when every trip is over", async () => {
    at("2027-03-01T09:00:00Z");
    serve([london]);
    render(Upcoming);
    expect(await screen.findByText(/Nothing coming up/)).toBeInTheDocument();
  });

  it("doesn't leave stale trips looking current when a reload fails, and loads again on Try again", async () => {
    at("2026-11-20T09:00:00-05:00");
    vi.mocked(api).mockRejectedValueOnce(new Error("Waypoint is unreachable"));
    render(Upcoming);
    expect(await screen.findByText("Waypoint is unreachable")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "JFK → LHR" })).toBeNull();
    vi.mocked(api).mockResolvedValue({ trips: [london] });
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "JFK → LHR" })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Waypoint is unreachable")).toBeNull());
  });

  it("shows a flight on two bookings once, with each booking’s code to copy", async () => {
    at("2026-11-20T09:00:00-05:00");
    const second = segment({ id: 10, confirmation: "BBBBBB", details: { flight_number: "AA0101" }, travelers: [{ id: 9, person_id: 2, name: "Sam Doe", seat: null }] });
    serve([trip([outbound, second, stay, home])]);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR", level: 2 })).closest("section")!;
    expect(within(card).getByRole("button", { name: "Copy confirmation code KQ7M2X" })).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Copy confirmation code BBBBBB" })).toBeInTheDocument();
    expect(within(card).queryByText("Times differ between bookings")).toBeNull();
    const days = screen.getByRole("list", { name: "Trip to London, day by day" });
    expect(within(days).getAllByText("JFK → LHR")).toHaveLength(1);
    expect(within(days).getByText("2 bookings")).toBeInTheDocument();
  });

  it("says when the bookings of a flight disagree on its times, and gives each booking’s", async () => {
    at("2026-11-20T09:00:00-05:00");
    const moved = segment({ id: 10, confirmation: "BBBBBB", start_local: "2026-11-20T21:30", details: { flight_number: "AA 101" } });
    serve([trip([outbound, moved, stay, home])]);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR", level: 2 })).closest("section")!;
    expect(within(card).getByText("Times differ between bookings")).toBeInTheDocument();
    expect(within(card).getByText(/^KQ7M2X: departs/)).toHaveTextContent(/departs Fri, Nov 20, 7:00 PM.*arrives Sat, Nov 21, 7:10 AM/);
    expect(within(card).getByText(/^BBBBBB: departs/)).toHaveTextContent(/departs Fri, Nov 20, 9:30 PM/);
  });
});
