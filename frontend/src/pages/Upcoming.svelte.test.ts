// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import { app } from "$lib/app.svelte";
import { offline } from "$lib/offline.svelte";
import { dropEarly, startEarly } from "$lib/early";
import { flightStatus } from "$lib/flightstatus.svelte";
import { viewport } from "$lib/phone.svelte";
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
afterEach(() => { vi.useRealTimers(); flightStatus.list = null; dropEarly(); });

const box = (over: Record<string, unknown> = {}) => ({ id: 1, address: "me@example.test", status: "connected", scanning: false, ...over });
const serve = (trips: unknown[], guests: unknown[] = [], mail: unknown = { configured: true, mailboxes: [] }) =>
  vi.mocked(api).mockImplementation(async (path) => (path === "/api/people/claim-suggestions" ? { guests } : path === "/api/mailboxes" ? mail : path === "/api/state" ? { review_count: 0 } : path === "/api/mailboxes/connect" ? { url: "#upcoming" } : { trips }));
const at = (iso: string) => vi.setSystemTime(new Date(iso));

describe("Upcoming", () => {
  it("says there are no trips yet, without making any up", async () => {
    serve([]);
    render(Upcoming);
    expect(screen.getByRole("heading", { name: "Upcoming" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Connect Gmail" })).toBeInTheDocument();
  });

  it("offers to connect Gmail, starting the connection directly, next to adding a booking by hand", async () => {
    serve([]);
    render(Upcoming);
    await userEvent.click(await screen.findByRole("button", { name: "Connect Gmail" }));
    expect(api).toHaveBeenCalledWith("/api/mailboxes/connect", { method: "POST" });
    expect(screen.getByRole("link", { name: "Add a booking" })).toHaveAttribute("href", "#trips?add=booking");
  });

  it("offers only adding a booking when Gmail isn’t set up on the server", async () => {
    serve([], [], { configured: false, mailboxes: [] });
    render(Upcoming);
    expect(await screen.findByRole("heading", { name: "No trips yet" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Gmail/ })).toBeNull();
    expect(screen.getByRole("link", { name: "Add a booking" })).toHaveAttribute("href", "#trips?add=booking");
  });

  it("says the mailbox is being scanned", async () => {
    serve([], [], { configured: true, mailboxes: [box({ scanning: true })] });
    render(Upcoming);
    expect(await screen.findByRole("heading", { name: "Scanning your mailbox" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connect Gmail" })).toBeNull();
  });

  it("reloads the trips when the scan ends, so found trips replace the empty state", async () => {
    let scanned = false;
    vi.mocked(api).mockImplementation(async (path) => (path === "/api/mailboxes" ? { configured: true, mailboxes: [box({ scanning: !scanned })] }
      : path === "/api/people/claim-suggestions" ? { guests: [] } : path === "/api/state" ? { review_count: 0 } : { trips: scanned ? [london] : [] }));
    render(Upcoming);
    expect(await screen.findByRole("heading", { name: "Scanning your mailbox" })).toBeInTheDocument();
    scanned = true;
    await vi.advanceTimersByTimeAsync(5_000);
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Scanning your mailbox" })).toBeNull());
    expect(screen.queryByRole("heading", { name: "No trips yet" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Connect Gmail" })).toBeNull();
  });

  it("keeps polling the scan when one mailbox poll fails", async () => {
    let calls = 0, scanned = false;
    vi.mocked(api).mockImplementation(async (path) => {
      if (path === "/api/mailboxes") { calls++; if (calls === 2) throw new Error("offline"); return { configured: true, mailboxes: [box({ scanning: !scanned })] }; }
      return path === "/api/people/claim-suggestions" ? { guests: [] } : path === "/api/state" ? { review_count: 0 } : { trips: scanned ? [london] : [] };
    });
    render(Upcoming);
    expect(await screen.findByRole("heading", { name: "Scanning your mailbox" })).toBeInTheDocument();
    await vi.advanceTimersByTimeAsync(5_000);
    expect(calls).toBe(2);
    expect(screen.getByRole("heading", { name: "Scanning your mailbox" })).toBeInTheDocument();
    scanned = true;
    await vi.advanceTimersByTimeAsync(5_000);
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Scanning your mailbox" })).toBeNull());
    expect(screen.queryByRole("heading", { name: "No trips yet" })).toBeNull();
  });

  it("asks to reconnect a mailbox Waypoint can’t read", async () => {
    serve([], [], { configured: true, mailboxes: [box({ status: "reconnect" })] });
    render(Upcoming);
    expect(await screen.findByRole("button", { name: "Reconnect Gmail" })).toBeInTheDocument();
  });

  it("links to Review when emails are waiting", async () => {
    serve([], [], { configured: true, mailboxes: [box()] });
    app.state = { review_count: 3 } as never;
    render(Upcoming);
    expect(await screen.findByRole("heading", { name: "3 emails are waiting for your review" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review 3 emails" })).toHaveAttribute("href", "#review");
    app.state = null;
  });

  it("falls back to adding a booking by hand once a mailbox is connected and nothing is waiting", async () => {
    serve([], [], { configured: true, mailboxes: [box()] });
    render(Upcoming);
    expect(await screen.findByRole("heading", { name: "No trips yet" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add a booking" })).toHaveAttribute("href", "#trips?add=booking");
  });

  it("still shows the manual path when the mailbox list can’t be read", async () => {
    vi.mocked(api).mockImplementation(async (path) => { if (path === "/api/mailboxes") throw new Error("Down."); return (path === "/api/people/claim-suggestions" ? { guests: [] } : { trips: [] }) as never; });
    render(Upcoming);
    expect(await screen.findByRole("link", { name: "Add a booking" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
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
    expect(screen.getByRole("heading", { name: "Connect Gmail" })).toBeInTheDocument();
  });

  it("offers nothing when no guest matches, or when there are trips", async () => {
    serve([]);
    render(Upcoming);
    await screen.findByRole("heading", { name: "Connect Gmail" });
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
    expect(within(card).getByText("7:00 PM")).toBeInTheDocument();
    expect(within(card).getByText("Fri, Nov 20")).toBeInTheDocument();
    expect(within(card).getByText("New York time")).toBeInTheDocument();
    expect(within(card).getByText("8")).toBeInTheDocument();
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(within(card).getByRole("button", { name: "Copy confirmation code KQ7M2X" }));
    expect(await navigator.clipboard.readText()).toBe("KQ7M2X");
  });

  it("starts an ongoing trip's timeline at today and keeps the earlier days behind a keyboard-reachable disclosure", async () => {
    at("2026-11-27T08:00:00+00:00");
    serve([london]);
    render(Upcoming);
    const toggle = await screen.findByText(/Earlier in this trip · 2 days/);
    expect(toggle.closest("details")).not.toHaveAttribute("open");
    expect(toggle.tagName).toBe("SUMMARY");
    const days = screen.getByRole("list", { name: "Trip to London, day by day" });
    expect(within(days).getByRole("heading", { name: /Today/ })).toBeInTheDocument();
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(toggle);
    expect(toggle.closest("details")).toHaveAttribute("open");
    expect(within(screen.getByRole("list", { name: "Trip to London, earlier days" })).getAllByRole("heading", { level: 3 })).toHaveLength(2);
  });

  it("judges earlier days by the instant in the viewer's day, not the booking's calendar date", async () => {
    at("2026-11-21T00:00:00-05:00");
    const LA = "America/Los_Angeles";
    const late = segment({ id: 1, origin: "LAX", destination: "JFK", start_local: "2026-11-20T22:00", start_zone: LA, end_local: "2026-11-21T06:00", end_zone: NY });
    serve([trip([late, stay])]);
    render(Upcoming);
    await screen.findByRole("heading", { name: "LAX → JFK" });
    expect(screen.queryByText(/Earlier in this trip/)).toBeNull();
    expect(within(screen.getByRole("list", { name: "Trip to London, day by day" })).getByText(/Nov 20/)).toBeInTheDocument();
  });

  it("offers no earlier days before a trip starts", async () => {
    at("2026-11-20T09:00:00-05:00");
    serve([london]);
    render(Upcoming);
    await screen.findByRole("heading", { name: "JFK → LHR" });
    expect(screen.queryByText(/Earlier in this trip/)).toBeNull();
  });

  it("shows Directions and Call for the stay under way, in place of the app link", async () => {
    at("2026-11-21T08:00:00Z");
    const here = segment({ ...stay, links: { app: "https://example.test/app", open: null, open_kind: null, directions: "https://maps.example/dir", call: "tel:+442000000000" } });
    serve([trip([outbound, here])]);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "Harbour Hotel" })).closest("section")!;
    expect(within(card).getByRole("link", { name: "Directions" })).toHaveAttribute("href", "https://maps.example/dir");
    expect(within(card).getByRole("link", { name: "Call" })).toHaveAttribute("href", "tel:+442000000000");
    expect(within(card).queryByRole("link", { name: /app/i })).toBeNull();
    expect(within(card).getByRole("button", { name: /Copy confirmation code H88231/ })).toBeInTheDocument();
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
    expect(within(card).getByRole("img", { name: "Route" }).dataset.progress).toBe("0.5");
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

  it("doesn’t call a flight under way once live status says it landed", async () => {
    at("2026-11-21T02:00:00-05:00");
    const landed = { ...delayed, statuses: [{ ...delayed.statuses[0], state: "landed", arr_actual: "2026-11-21T01:50" }] };
    vi.mocked(api).mockImplementation(async (path: string) => (path === "/api/flight-status" ? landed : { trips: [london] }) as never);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR" })).closest("section")!;
    expect(await within(card).findByText("Latest flight")).toBeInTheDocument();
    expect(within(card).queryByText("Under way")).toBeNull();
    expect(within(card).getByText("Landed", { selector: "[data-headline]" })).toBeInTheDocument();
  });

  it("does not call a flight under way once live status says it landed or was cancelled", async () => {
    at("2026-11-21T02:00:00-05:00");
    for (const state of ["landed", "cancelled"]) {
      const live = { ...delayed, statuses: [{ ...delayed.statuses[0], state, fetched_at: "2026-11-21T06:30:00+00:00" }] };
      vi.mocked(api).mockImplementation(async (path: string) => (path === "/api/flight-status" ? live : { trips: [london] }) as never);
      const { unmount } = render(Upcoming);
      const card = (await screen.findByRole("heading", { name: "JFK → LHR" })).closest("section")!;
      await within(card).findByTestId("flight-status");
      expect(within(card).getByText("Latest flight")).toBeInTheDocument();
      expect(within(card).queryByText("Under way")).toBeNull();
      unmount();
      flightStatus.list = null;
    }
  });

  it("leads with a hotel's address and check-in time once the flight is behind", async () => {
    at("2026-11-21T08:00:00Z");
    serve([trip([outbound, stay])]);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "Harbour Hotel" })).closest("section")!;
    expect(within(card).getByText("Check-in in 7 h")).toBeInTheDocument();
    expect(within(card).getByText("London", { selector: "dd" })).toBeInTheDocument();
    expect(within(card).getByText("3:00 PM")).toBeInTheDocument();
  });

  describe("a parking booking", () => {
    const lot = segment({ id: 7, kind: "parking", provider: "Example Parking", origin: "Example Long-Term Lot", destination: null, start_local: "2026-11-20T15:00", start_zone: NY,
      end_local: "2026-11-27T21:00", end_zone: NY, confirmation: "PK1234", details: { space_type: "Covered", address: "1 Terminal Road, Jamaica, NY" } });

    it("leads with the lot as Next up, counting down to entry", async () => {
      at("2026-11-20T09:00:00-05:00");
      serve([trip([lot, outbound, stay, home])]);
      render(Upcoming);
      const card = (await screen.findByRole("heading", { name: "Example Long-Term Lot" })).closest("section")!;
      expect(within(card).getByText("Next up")).toBeInTheDocument();
      expect(within(card).getByText("Entry in 6 h")).toBeInTheDocument();
      expect(within(card).getByText("Jamaica, NY", { selector: "dd" })).toBeInTheDocument();
      expect(within(card).getByText("Exit")).toBeInTheDocument();
    });

    it("calls it under way while the vehicle is parked and nothing else is left", async () => {
      at("2026-11-22T12:00:00-05:00");
      serve([trip([lot])]);
      render(Upcoming);
      const card = (await screen.findByRole("heading", { name: "Example Long-Term Lot" })).closest("section")!;
      expect(within(card).getByText("Under way")).toBeInTheDocument();
      expect(within(card).getByText("Exit in 5 days 9 h")).toBeInTheDocument();
    });

    it("lists the lot on the day it starts and again on the day it ends, with the lot type", async () => {
      at("2026-11-20T09:00:00-05:00");
      serve([trip([lot, outbound, home])]);
      render(Upcoming);
      const days = await screen.findByRole("list", { name: "Trip to London, day by day" });
      expect(within(days).getByRole("link", { name: "Example Long-Term Lot" })).toHaveAttribute("href", "#trip/1?segment=7");
      expect(within(days).getByRole("link", { name: "Exit: Example Long-Term Lot" })).toHaveAttribute("href", "#trip/1?segment=7");
      expect(within(days).getByText(/Covered/)).toBeInTheDocument();
    });
  });

  it("leaves a flight's cabin and a hotel's address out of the day-by-day list", async () => {
    at("2026-11-20T09:00:00-05:00");
    const economy = segment({ id: 1, details: { flight_number: "AA 101", seat: "12A", cabin: "Economy" } });
    serve([trip([economy, stay])]);
    render(Upcoming);
    const days = await screen.findByRole("list", { name: "Trip to London, day by day" });
    expect(within(days).getByText(/Seat 12A/)).toBeInTheDocument();
    expect(within(days).queryByText(/Economy/)).toBeNull();
    expect(within(days).getByText("Harbour Hotel")).toBeInTheDocument();
    expect(within(days).queryByText(/1 Quay Street/)).toBeNull();
  });

  it("names a branded hotel by its brand and city in the list, with the full name on hover", async () => {
    at("2026-11-20T09:00:00-05:00");
    const branded = segment({ id: 2, kind: "hotel", provider: "Hyatt", origin: "Hyatt Place Example Beach Convention Center", hotel_brand: "Hyatt Place", destination: null,
      start_local: "2026-11-21T15:00", start_zone: LON, end_local: "2026-11-27T10:00", end_zone: LON,
      details: { address: "100 Example Blvd, Fort Lauderdale, FL 33301, USA" } });
    serve([trip([outbound, branded])]);
    render(Upcoming);
    const days = await screen.findByRole("list", { name: "Trip to London, day by day" });
    const link = within(days).getByRole("link", { name: "Hyatt Place" });
    expect(link).toHaveAttribute("title", "Hyatt Place Example Beach Convention Center");
    expect(within(days).getByText("Fort Lauderdale, FL")).toBeInTheDocument();
    expect(within(days).queryByText(/100 Example Blvd/)).toBeNull();
    expect(within(days).getByRole("link", { name: "Check-out: Hyatt Place" })).toBeInTheDocument();
  });

  it("shows the same city and state on the Next up card and in the day-by-day list", async () => {
    at("2026-11-20T09:00:00-05:00");
    const hotel = segment({ id: 2, kind: "hotel", provider: "Hyatt", origin: "Hyatt Place Example Beach Convention Center", hotel_brand: "Hyatt Place", destination: null,
      start_local: "2026-11-21T15:00", start_zone: LON, end_local: "2026-11-27T10:00", end_zone: LON,
      details: { address: "100 Example Blvd, Minneapolis, Minnesota 55401" } });
    serve([trip([hotel])]);
    render(Upcoming);
    const days = await screen.findByRole("list", { name: "Trip to London, day by day" });
    expect(within(days).getByText("Minneapolis, Minnesota")).toBeInTheDocument();
    const nextCard = screen.getByRole("heading", { name: "Hyatt Place Example Beach Convention Center" }).closest("section") as HTMLElement;
    expect(within(nextCard).getByText("Minneapolis, Minnesota")).toBeInTheDocument();
    expect(within(nextCard).queryByText(/100 Example Blvd/)).toBeNull();
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
    expect(screen.getByRole("link", { name: "Open trip: Trip to London" })).toHaveAttribute("href", "#trip/1?segment=1");
  });

  it("shows a time at its place and never a second time in your zone", async () => {
    at("2026-11-20T09:00:00-05:00");
    serve([london]);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR" })).closest("section")!;
    expect(within(card).getByText("7:10 AM")).toBeInTheDocument();
    expect(card).not.toHaveTextContent("[");
  });

  it("keeps a parking booking and a rental under way beside the flight that leads, with when each ends", async () => {
    const parking = segment({ id: 40, kind: "parking", provider: "Lot A", origin: "Lot A", destination: null, start_local: "2026-11-15T06:00", start_zone: NY, end_local: "2026-11-22T20:00", end_zone: NY, details: {} });
    const rental = segment({ id: 41, kind: "car", provider: "Hertz", origin: "JFK", destination: null, start_local: "2026-11-16T09:00", start_zone: NY, end_local: "2026-11-24T09:00", end_zone: NY, details: {} });
    serve([trip([parking, rental, segment({ id: 42, start_local: "2026-11-18T11:00", end_local: "2026-11-18T14:00", end_zone: NY })])]);
    at("2026-11-18T09:00:00-05:00");
    render(Upcoming);
    const also = await screen.findByRole("region", { name: "Also under way" });
    const links = within(also).getAllByRole("link");
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute("href", "#trip/1?segment=40");
    expect(links[1]).toHaveAttribute("href", "#trip/1?segment=41");
    expect(also).toHaveTextContent(/Exit/);
    expect(also).toHaveTextContent(/Drop-off/);
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

describe("Upcoming booking detail", () => {
  beforeEach(() => { viewport.phone = true; });
  afterEach(() => { viewport.phone = false; });

  it("opens a booking’s full card in a bottom sheet on a phone from the day-by-day list, with a way to the trip", async () => {
    at("2026-11-20T09:00:00-05:00");
    serve([london]);
    render(Upcoming);
    const u = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const list = await screen.findByRole("list", { name: /day by day/ });
    const link = within(list).getByRole("link", { name: "Harbour Hotel" });
    await u.click(link);
    const sheet = await screen.findByRole("dialog", { name: "Harbour Hotel" });
    expect(sheet).toHaveAttribute("data-side", "bottom");
    expect(within(sheet).getByRole("link", { name: "Open trip" })).toHaveAttribute("href", `#trip/${london.id}?segment=2`);
    expect(location.hash).not.toContain("#trip/");
    await u.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(link).toHaveFocus());
  });

  it("opens it as a side panel on a larger screen", async () => {
    viewport.phone = false;
    at("2026-11-20T09:00:00-05:00");
    serve([london]);
    render(Upcoming);
    const u = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await u.click(within(await screen.findByRole("list", { name: /day by day/ })).getByRole("link", { name: "Harbour Hotel" }));
    expect(await screen.findByRole("dialog", { name: "Harbour Hotel" })).toHaveAttribute("data-side", "right");
  });

  it("leaves the link alone for a modified click", async () => {
    at("2026-11-20T09:00:00-05:00");
    serve([london]);
    render(Upcoming);
    const link = within(await screen.findByRole("list", { name: /day by day/ })).getByRole("link", { name: "Harbour Hotel" });
    link.addEventListener("click", (e) => e.preventDefault());
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).keyboard("{Control>}");
    link.dispatchEvent(new MouseEvent("click", { ctrlKey: true, bubbles: true, cancelable: true }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("Upcoming day-by-day rows", () => {
  const rowsOf = async () => {
    at("2026-11-20T09:00:00-05:00");
    serve([london]);
    render(Upcoming);
    const list = await screen.findByRole("list", { name: /day by day/ });
    return within(list).getAllByRole("listitem").filter((li) => li.classList.contains("row-tap"));
  };

  it("gives each row one link, named as before, that carries the stretched hit area over the whole row", async () => {
    const rows = await rowsOf();
    expect(rows.map((r) => within(r).getAllByRole("link").map((a) => a.textContent))).toEqual([["JFK → LHR"], ["Harbour Hotel"], ["Check-out: Harbour Hotel"], ["LHR → JFK"]]);
    for (const row of rows) {
      expect(row).toHaveClass("row-tap");
      const link = within(row).getByRole("link");
      expect(link).toHaveClass("row-tap-link");
      expect(row.querySelectorAll("a, button, [onclick]")).toHaveLength(1);
    }
  });

  it("opens the same booking from the link of a row whose time, logo and subline sit under the stretched area", async () => {
    const rows = await rowsOf();
    const row = rows[1];
    expect(within(row).getByText("Harbour Hotel").closest("a")).toBe(within(row).getByRole("link"));
    expect(row.querySelector("time")).not.toBeNull();
    expect(row.querySelector("time")!.closest("a")).toBeNull();
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(within(row).getByRole("link"));
    expect(await screen.findByRole("dialog", { name: "Harbour Hotel" })).toBeInTheDocument();
  });
});

describe("the reads started before the page opened", () => {
  it("uses them instead of asking again", async () => {
    vi.mocked(api).mockImplementation(async (path: string) => (path === "/api/flight-status" ? delayed : { trips: [london] }) as never);
    startEarly("upcoming");
    render(Upcoming);
    expect(await screen.findByRole("heading", { name: /London/ })).toBeInTheDocument();
    await waitFor(() => expect(flightStatus.list?.enabled).toBe(true));
    expect(vi.mocked(api).mock.calls.filter(([path]) => path === "/api/trips")).toHaveLength(1);
    expect(vi.mocked(api).mock.calls.filter(([path]) => path === "/api/flight-status")).toHaveLength(1);
  });

  it("shows the failure of an early read like any other", async () => {
    vi.mocked(api).mockRejectedValue(new Error("Request failed (500)"));
    startEarly("upcoming");
    render(Upcoming);
    expect(await screen.findByText("Request failed (500)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
  it("puts Show QR code on the Next up card of a parking booking with a code, and on nothing else", async () => {
    const lot = segment({ id: 9, kind: "parking", provider: "Example Parking", origin: "Example Airport Long-Term Lot", destination: null, confirmation: "PK30417",
      start_local: "2099-01-10T05:15", start_zone: NY, end_local: "2099-01-13T03:00", end_zone: NY, details: {}, gate_code: { state: "ready", day: "2098-12-20" }, travelers: [] });
    at("2099-01-09T09:00:00-05:00");
    serve([trip([lot])]);
    render(Upcoming);
    const card = (await screen.findAllByText("Next up")).map((e) => e.closest("section")).find(Boolean)!;
    const show = within(card).getByRole("button", { name: "Show QR code for Example Airport Long-Term Lot" });
    expect(show).toBeInTheDocument();
    expect(show.closest(".phone\\:hidden")).toBeNull();
    expect(within(card).getByRole("link", { name: /Open / })).toBeInTheDocument();
  });

  it("shows no QR code button on the Next up card of a flight", async () => {
    at("2026-11-20T09:00:00-05:00");
    serve([london]);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR" })).closest("section")!;
    expect(within(card).queryByRole("button", { name: /QR code/ })).toBeNull();
  });
});

describe("Upcoming header, review banner and timeline", () => {
  const offlineReset = { checked: true, setUp: false, hasCopy: false, savedAt: null, off: false, damaged: false, supported: true, reason: "", declined: false, failed: false, trips: [] };
  beforeEach(() => { Object.assign(offline, offlineReset); at("2026-11-20T09:00:00-05:00"); });
  afterEach(() => { app.state = null; viewport.phone = false; Object.assign(offline, offlineReset); });

  it("puts today's date above the title, short on a phone", async () => {
    serve([london]);
    const { unmount } = render(Upcoming);
    await screen.findByRole("heading", { name: "JFK → LHR" });
    expect(screen.getByTestId("today-eyebrow")).toHaveTextContent("Friday, November 20");
    unmount();
    viewport.phone = true;
    render(Upcoming);
    await screen.findByRole("heading", { name: "JFK → LHR" });
    expect(screen.getByTestId("today-eyebrow")).toHaveTextContent("Fri, Nov 20");
    expect(screen.getByRole("link", { name: "Add a booking" })).toHaveAttribute("href", "#trips?add=booking");
  });

  it("shows the review banner only with trips and a review count, above the next-up card", async () => {
    app.state = { review_count: 2 } as never;
    serve([london]);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR" })).closest("section")!;
    const banner = screen.getByTestId("review-banner");
    expect(banner).toHaveTextContent("2 emails to review. Waypoint found what look like bookings and needs you to check them.");
    expect(within(banner).getByRole("link", { name: "Review emails" })).toHaveAttribute("href", "#review");
    expect(banner.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("says one email in the singular and shows no banner for none", async () => {
    app.state = { review_count: 1 } as never;
    serve([london]);
    const { unmount } = render(Upcoming);
    await screen.findByRole("heading", { name: "JFK → LHR" });
    expect(screen.getByTestId("review-banner")).toHaveTextContent("1 email to review.");
    unmount();
    app.state = { review_count: 0 } as never;
    render(Upcoming);
    await screen.findByRole("heading", { name: "JFK → LHR" });
    expect(screen.queryByTestId("review-banner")).toBeNull();
  });

  it("keeps the empty-state review wording, with no banner, when there are no trips", async () => {
    app.state = { review_count: 3 } as never;
    serve([], [], { configured: true, mailboxes: [box()] });
    render(Upcoming);
    expect(await screen.findByRole("heading", { name: "3 emails are waiting for your review" })).toBeInTheDocument();
    expect(screen.queryByTestId("review-banner")).toBeNull();
  });

  it("is one compact link to Review on a phone, with no explanation and no email details", async () => {
    viewport.phone = true;
    app.state = { review_count: 2 } as never;
    serve([london]);
    render(Upcoming);
    await screen.findByRole("heading", { name: "JFK → LHR" });
    const banner = screen.getByTestId("review-banner");
    expect(banner.tagName).toBe("A");
    expect(banner).toHaveAttribute("href", "#review");
    expect(banner).toHaveTextContent("2 emails to review Review");
    expect(banner).not.toHaveTextContent("Waypoint found");
  });

  it("marks the next-up booking's row with a Next up pill instead of a chevron", async () => {
    serve([london]);
    render(Upcoming);
    const list = await screen.findByRole("list", { name: /day by day/ });
    const rows = within(list).getAllByRole("listitem").filter((li) => li.classList.contains("row-tap"));
    const marked = rows.filter((r) => r.dataset.next === "true");
    expect(marked).toHaveLength(1);
    expect(within(marked[0]).getByTestId("next-up-pill")).toHaveTextContent("Next up");
    expect(within(marked[0]).getByRole("link")).toHaveTextContent("JFK → LHR");
    expect(rows.filter((r) => r !== marked[0]).every((r) => within(r).queryByTestId("next-up-pill") === null)).toBe(true);
  });

  it("counts the nights of the trip across a month end, and none for a one-day trip", async () => {
    const away = trip([segment({ id: 5, start_local: "2026-11-28T09:00", end_local: "2026-11-28T12:00", end_zone: NY }), segment({ id: 6, start_local: "2026-12-02T09:00", end_local: "2026-12-02T12:00", end_zone: NY })]);
    serve([away]);
    const { unmount } = render(Upcoming);
    await screen.findByRole("list", { name: /day by day/ });
    expect(screen.getByText("Nov 28 – Dec 2 · 4 nights")).toBeInTheDocument();
    unmount();
    const one = trip([segment({ id: 7, start_local: "2026-11-28T09:00", end_local: "2026-11-28T12:00", end_zone: NY })]);
    serve([one]);
    render(Upcoming);
    await screen.findByRole("list", { name: /day by day/ });
    expect(screen.queryByText(/night/)).toBeNull();
    expect(screen.getByText("Nov 28")).toBeInTheDocument();
  });

  it("shows the year on both dates of a range outside the current year, and a single date for a one-day trip there", async () => {
    const make = (a: string, b: string) => trip([segment({ id: 8, start_local: `${a}T09:00`, end_local: `${a}T12:00`, end_zone: NY }), segment({ id: 9, start_local: `${b}T09:00`, end_local: `${b}T12:00`, end_zone: NY })]);
    serve([make("2027-01-02", "2027-01-08")]);
    const next = render(Upcoming);
    await screen.findByRole("list", { name: /day by day/ });
    expect(screen.getByText("Jan 2, 2027 – Jan 8, 2027 · 6 nights")).toBeInTheDocument();
    next.unmount();
    serve([make("2031-03-04", "2031-03-04")]);
    const far = render(Upcoming);
    await screen.findByRole("list", { name: /day by day/ });
    expect(screen.getByText("Mar 4, 2031")).toBeInTheDocument();
    far.unmount();
    serve([make("2026-12-30", "2027-01-02")]);
    render(Upcoming);
    await screen.findByRole("list", { name: /day by day/ });
    expect(screen.getByText("Dec 30, 2026 – Jan 2, 2027 · 3 nights")).toBeInTheDocument();
  });

  it("marks the end row of an ongoing stay as next up when its start day is in the collapsed earlier days", async () => {
    at("2026-11-24T12:00:00+00:00");
    serve([trip([outbound, stay])]);
    render(Upcoming);
    const toggle = await screen.findByText(/Earlier in this trip/);
    const details = toggle.closest("details")!;
    const list = screen.getByRole("list", { name: "Trip to London, day by day" });
    const marked = [...list.querySelectorAll("li[data-next='true']")];
    expect(marked).toHaveLength(1);
    expect(details.contains(marked[0])).toBe(false);
    expect(marked[0]).toHaveTextContent("Check-out: Harbour Hotel");
    expect(within(marked[0] as HTMLElement).getByTestId("next-up-pill")).toBeInTheDocument();
  });

  it("shows the Saved for offline pill only when offline saving is working", async () => {
    Object.assign(offline, { setUp: true, hasCopy: true, savedAt: Date.now(), trips: [{ id: 1, name: "Trip" }] });
    serve([london]);
    const { unmount } = render(Upcoming);
    const pill = await screen.findByRole("button", { name: "Saved for offline" });
    expect(screen.queryByTestId("offline-status")).toBeNull();
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(pill);
    expect(screen.getByTestId("offline-status")).toBeInTheDocument();
    unmount();
    Object.assign(offline, { failed: true });
    render(Upcoming);
    await screen.findByRole("heading", { name: "JFK → LHR" });
    expect(screen.queryByRole("button", { name: "Saved for offline" })).toBeNull();
    expect(screen.getByTestId("offline-status")).toBeInTheDocument();
  });
});

describe("Upcoming side column", () => {
  const places = {
    home: null, stays: [], cities: [], roads: { legs: [], interstates: [] }, boundaries: [],
    airports: [{ code: "JFK", city: "New York", latitude: 40.64, longitude: -73.78 }, { code: "LHR", city: "London", latitude: 51.47, longitude: -0.45 }],
  };
  const later = (id: number, name: string, start: string, end: string, destination: string | null) =>
    trip([segment({ id: id * 10, trip_id: id, origin: "BOS", destination: "LIS", start_local: `${start}T10:00`, end_local: `${start}T18:00` }),
      segment({ id: id * 10 + 1, trip_id: id, kind: "hotel", origin: "Casa", destination: "Lisbon", start_local: `${start}T19:00`, end_local: `${end}T10:00` })], { id, name, destination, start_date: start, end_date: end });
  const lisbon = later(2, "Lisbon in winter", "2026-12-30", "2027-01-03", "Lisbon");
  const porto = later(3, "Porto weekend", "2027-02-10", "2027-02-12", null);
  const third = later(4, "Rome", "2027-03-01", "2027-03-04", "Rome");
  const serveWith = (trips: unknown[], reply: (path: string) => unknown) =>
    vi.mocked(api).mockImplementation(async (path) => (path === "/api/people/claim-suggestions" ? { guests: [] } : path === "/api/mailboxes" ? { configured: true, mailboxes: [] } : path === "/api/state" ? { review_count: 0 } : reply(path as string) ?? { trips }) as never);
  const placesCalls = () => vi.mocked(api).mock.calls.map(([path]) => path as string).filter((p) => p.startsWith("/api/trips/"));
  const withPlaces = (path: string) => (path === "/api/trips/1/places" ? places : undefined);

  it("draws the featured trip’s route small, with a description built from its legs, and links it to the trip", async () => {
    at("2026-11-20T09:00:00-05:00");
    serveWith([london], withPlaces);
    render(Upcoming);
    const map = await screen.findByRole("img", { name: "Route map: New York to London, flight back to New York" });
    expect(map.closest("a")).toHaveAttribute("href", "#trip/1");
    expect(map.querySelector('[data-leg="flight"]')).toHaveAttribute("stroke-dasharray");
    expect(map.querySelector('[data-stop="New York"] text')).toHaveTextContent("JFK");
  });

  it("counts nights, live bookings and distinct cities", async () => {
    at("2026-11-20T09:00:00-05:00");
    const cancelled = segment({ id: 9, kind: "hotel", status: "cancelled", origin: "Gone Inn", destination: "Paris", start_local: "2026-11-21T15:00", end_local: "2026-11-22T10:00" });
    serveWith([trip([outbound, stay, home, cancelled], { end_date: "2026-11-27" })], (path) => { if (path.endsWith("/places")) throw new Error("offline"); return undefined; });
    render(Upcoming);
    const totals = await screen.findByTestId("trip-totals");
    expect(totals.children[0]).toHaveTextContent("Nights7");
    expect(totals.children[1]).toHaveTextContent("Bookings3");
    expect(totals.children[2]).toHaveTextContent("Cities3");
  });

  it("names a city once when its airport and its stay agree", async () => {
    at("2026-11-20T09:00:00-05:00");
    serveWith([london], withPlaces);
    render(Upcoming);
    await screen.findByRole("img", { name: /^Route map/ });
    expect(screen.getByTestId("trip-totals").children[2]).toHaveTextContent("Cities2");
  });

  it("lists the next two trips after the featured one, with an All trips link", async () => {
    at("2026-11-20T09:00:00-05:00");
    serveWith([porto, london, third, lisbon], withPlaces);
    render(Upcoming);
    const card = await screen.findByRole("region", { name: "Later" });
    const rows = within(card).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Dec 30");
    expect(rows[0]).toHaveTextContent("Lisbon in winter");
    expect(rows[0]).toHaveTextContent("In 40 days · Lisbon");
    expect(within(rows[0]).getByRole("link", { name: "Lisbon in winter" })).toHaveAttribute("href", "#trip/2");
    expect(rows[1]).toHaveTextContent("Porto weekend");
    expect(rows[1]).toHaveTextContent("In 82 days · 2 nights");
    expect(within(card).queryByText("Rome")).toBeNull();
    expect(within(card).getByRole("link", { name: "All trips" })).toHaveAttribute("href", "#trips?when=upcoming");
  });

  it("leaves the Later card out when there are no later trips", async () => {
    at("2026-11-20T09:00:00-05:00");
    serveWith([london], withPlaces);
    render(Upcoming);
    await screen.findByTestId("trip-totals");
    expect(screen.queryByRole("region", { name: "Later" })).toBeNull();
    expect(screen.queryByRole("link", { name: "All trips" })).toBeNull();
  });

  it("leaves the map out, without an error, when the places request fails, and keeps the totals", async () => {
    at("2026-11-20T09:00:00-05:00");
    serveWith([london], (path) => { if (path === "/api/trips/1/places") throw new Error("offline"); return undefined; });
    render(Upcoming);
    await screen.findByTestId("trip-totals");
    await waitFor(() => expect(placesCalls()).toEqual(["/api/trips/1/places"]));
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.queryByRole("img", { name: /^Route map/ })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByTestId("trip-totals")).toBeInTheDocument();
  });

  it("leaves the map out when the places reply is malformed", async () => {
    at("2026-11-20T09:00:00-05:00");
    serveWith([london], (path) => (path === "/api/trips/1/places" ? { trips: [] } : undefined));
    render(Upcoming);
    await screen.findByTestId("trip-totals");
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.queryByRole("img", { name: /^Route map/ })).toBeNull();
  });

  it("leaves the map out, and keeps the page, when the places reply lacks a collection the route needs", async () => {
    at("2026-11-20T09:00:00-05:00");
    serveWith([london], (path) => (path === "/api/trips/1/places" ? { ...places, stays: undefined } : undefined));
    render(Upcoming);
    await screen.findByTestId("trip-totals");
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.queryByRole("img", { name: /^Route map/ })).toBeNull();
    expect(screen.getByRole("heading", { name: "Trip to London" })).toBeInTheDocument();
  });

  it("leaves out an overlapping trip that has already started", async () => {
    at("2026-11-20T09:00:00-05:00");
    const started = later(5, "Already away", "2026-11-10", "2026-11-25", "Oslo");
    serveWith([started, london, lisbon], withPlaces);
    render(Upcoming);
    const card = await screen.findByRole("region", { name: "Later" });
    const rows = within(card).getAllByRole("listitem");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("Lisbon in winter");
    expect(within(card).queryByText("Already away")).toBeNull();
    expect(card).not.toHaveTextContent("Starting today");
  });

  it("makes no request but the featured trip’s own places, and no outside fetch", async () => {
    at("2026-11-20T09:00:00-05:00");
    const outside = vi.spyOn(globalThis, "fetch");
    serveWith([london, lisbon], withPlaces);
    render(Upcoming);
    await screen.findByRole("img", { name: /^Route map/ });
    expect(placesCalls()).toEqual(["/api/trips/1/places"]);
    expect(outside).not.toHaveBeenCalled();
    outside.mockRestore();
  });

  it("shows only the Later tiles on a phone, with no map, no totals and no places request", async () => {
    viewport.phone = true;
    at("2026-11-20T09:00:00-05:00");
    serveWith([london, lisbon, porto], withPlaces);
    render(Upcoming);
    const section = await screen.findByRole("region", { name: "Later" });
    const tiles = within(section).getAllByRole("listitem");
    expect(tiles).toHaveLength(2);
    expect(tiles[0]).toHaveTextContent("Dec 30");
    expect(tiles[0]).toHaveTextContent("Lisbon in winter");
    expect(tiles[0]).toHaveTextContent("In 40 days");
    expect(tiles[0]).not.toHaveTextContent("Lisbon in winter · ");
    expect(screen.queryByTestId("trip-totals")).toBeNull();
    expect(screen.queryByTestId("route-map")).toBeNull();
    expect(placesCalls()).toEqual([]);
    viewport.phone = false;
  });
});
