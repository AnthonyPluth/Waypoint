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
const openBooking = async (card: HTMLElement) => {
  await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(within(card).getByRole("button", { name: "Confirmation, travellers and price" }));
  return await screen.findByRole("dialog");
};

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

  it("leads with the next segment within a day of departure: the flight, its time at its airport, the terminal, and its code to copy in the opened booking", async () => {
    at("2026-11-20T09:00:00-05:00");
    serve([london]);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR" })).closest("section")!;
    expect(within(card).getByText("Next up")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "AA 101, JFK to LHR, scheduled, departs Fri Nov 20 at 7:00 pm" })).toHaveAttribute("href", `#trip/${london.id}/flight/1`);
    expect(card.querySelector("[data-carrier]")).toHaveTextContent(/AA 101$/);
    expect(card.querySelector(".eyebrow")).toHaveTextContent("Next up · Trip to London");
    expect(card.querySelector("[data-quiet]")).toHaveTextContent("Fri Nov 20");
    expect(card.querySelector("[data-when='origin'] time")).toHaveTextContent("7:00 PM");
    expect(card.querySelector("[data-facts] > div")).toHaveTextContent("Terminal 8");
    expect(within(card).queryByRole("button", { name: /Copy confirmation code/ })).toBeNull();
    const booking = await openBooking(card);
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(within(booking).getByRole("button", { name: "Copy confirmation code KQ7M2X" }));
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

  it("puts the plane on the dotted line from the booked times when the flight is under way", async () => {
    at("2026-11-20T22:35:00-05:00");
    serve([london]);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR" })).closest("section")!;
    expect(within(card).getByText("Under way")).toBeInTheDocument();
    expect(card.querySelector("article")!.dataset.progress).toBe("0.5");
    expect(card.querySelector<HTMLElement>("[data-plane]")!.style.left).toBe("50%");
    expect(within(card).getByRole("link", { name: "AA 101, JFK to LHR, in the air, lands 7:10 am in 3 hours 35 minutes" })).toBeInTheDocument();
  });

  it("leads with the route and the times at each airport, and keeps the code behind the tap", async () => {
    at("2026-11-20T09:00:00-05:00");
    serve([london]);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR" })).closest("section")!;
    expect(within(card).getAllByRole("button")[0]).toHaveAccessibleName("Confirmation, travellers and price");
    expect(within(card).queryByText("KQ7M2X")).toBeNull();
    expect(within(card).getByText("JFK")).toBeInTheDocument();
    expect(within(card).getByText("LHR")).toBeInTheDocument();
  });

  it("shows a booking’s brand logo in the day-by-day list, and no airline logo on the flight card", async () => {
    at("2026-11-20T09:00:00-05:00");
    serve([trip([segment({ id: 1, logo: "/api/segments/1/logo" }), stay, home])]);
    const { container } = render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR" })).closest("section")!;
    expect(card.querySelector("img")).toBeNull();
    expect([...container.querySelectorAll("img")].map((i) => i.getAttribute("src"))).toEqual(["/api/segments/1/logo"]);
  });

  it("shows the kind icon on a day row that has no brand logo", async () => {
    at("2026-11-20T09:00:00-05:00");
    serve([london]);
    render(Upcoming);
    const list = await screen.findByRole("list", { name: /day by day/ });
    const rows = [...list.querySelectorAll("li.row-tap")];
    expect(rows.length).toBeGreaterThan(0);
    for (const r of rows) expect(r.querySelector("[data-tile]")).not.toBeNull();
  });

  it("shows the flight’s live status on the Next up card", async () => {
    at("2026-11-20T09:00:00-05:00");
    vi.mocked(api).mockImplementation(async (path: string) => (path === "/api/flight-status" ? delayed : { trips: [london] }) as never);
    render(Upcoming);
    await screen.findByRole("heading", { name: "JFK → LHR" });
    const card = document.querySelector<HTMLElement>("[data-flight-home]")!;
    expect(await within(card).findByText("Delayed")).toBeInTheDocument();
    expect(within(card).getByText("B24")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "AA 101, JFK to LHR, delayed 50 minutes, now departs 7:50 pm" })).toBeInTheDocument();
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

  it("names the flight on the card and in Flights today in the last minute before departure", async () => {
    at("2026-11-20T18:59:40-05:00");
    serve([london]);
    render(Upcoming);
    expect(await screen.findAllByRole("link", { name: "AA 101, JFK to LHR, scheduled, departs Fri Nov 20 at 7:00 pm" })).toHaveLength(2);
  });

  it("calls a flight in the air under way, and counts down to landing", async () => {
    at("2026-11-21T02:00:00-05:00");
    serve([london]);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR" })).closest("section")!;
    expect(within(card).getByText("Under way")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "AA 101, JFK to LHR, in the air, lands 7:10 am in 10 minutes" })).toBeInTheDocument();
  });

  it("doesn’t call a flight under way once live status says it landed", async () => {
    at("2026-11-21T02:00:00-05:00");
    const landed = { ...delayed, statuses: [{ ...delayed.statuses[0], state: "landed", arr_actual: "2026-11-21T01:50" }] };
    vi.mocked(api).mockImplementation(async (path: string) => (path === "/api/flight-status" ? landed : { trips: [london] }) as never);
    render(Upcoming);
    const card = (await screen.findByText("Latest flight")).closest("section")!;
    expect(within(card).queryByText("Under way")).toBeNull();
    expect(within(card).getByText("Landed", { selector: "[data-headline]" })).toBeInTheDocument();
  });

  it("does not call a flight under way once live status says it landed or was cancelled", async () => {
    at("2026-11-21T02:00:00-05:00");
    for (const state of ["landed", "cancelled"]) {
      const live = { ...delayed, statuses: [{ ...delayed.statuses[0], state, fetched_at: "2026-11-21T06:30:00+00:00" }] };
      vi.mocked(api).mockImplementation(async (path: string) => (path === "/api/flight-status" ? live : { trips: [london] }) as never);
      const { unmount } = render(Upcoming);
      const card = (await screen.findByText("Latest flight")).closest("section")!;
      await within(card).findByTestId("flight-status");
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
    expect(within(card).getByRole("button", { name: "Copy address 1 Quay Street, London and get directions" })).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: /1 Quay Street, London/ })).toHaveTextContent("London");
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
      expect(within(card).getByRole("button", { name: "Copy address 1 Terminal Road, Jamaica, NY and get directions" })).toBeInTheDocument();
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
    expect(screen.queryByRole("link", { name: "Open trip: Trip to London" })).toBeNull();
    const booking = await openBooking(document.querySelector<HTMLElement>("[data-flight-home]")!);
    expect(within(booking).getByRole("link", { name: "Open trip: Trip to London" })).toHaveAttribute("href", "#trip/1?segment=1");
  });

  it("shows a time at its place and never a second time in your zone", async () => {
    at("2026-11-20T09:00:00-05:00");
    serve([london]);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR" })).closest("section")!;
    expect(card.querySelector("[data-when='destination'] time")).toHaveTextContent("7:10 AM");
    expect(card.querySelector("[data-when='origin'] time")).toHaveTextContent("7:00 PM");
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

  describe("the trip in progress", () => {
    const staying = trip([segment({ id: 50, trip_id: 5, kind: "hotel", provider: "Marriott", origin: "Harbour Hotel", destination: null, start_local: "2026-11-20T15:00", start_zone: NY,
      end_local: "2026-11-27T11:00", end_zone: NY, details: {} })], { id: 5, name: "Beach stay", start_date: "2026-11-20", end_date: "2026-11-27" });
    const quick = trip([segment({ id: 60, trip_id: 6, start_local: "2026-11-22T09:00", end_local: "2026-11-22T12:00", end_zone: NY })], { id: 6, name: "Quick flight", start_date: "2026-11-22", end_date: "2026-11-22" });

    it("stays first, with the later trip under Later, although the later trip has a booking sooner", async () => {
      at("2026-11-21T10:00:00-05:00");
      serve([quick, staying]);
      render(Upcoming);
      expect(await screen.findByRole("heading", { name: "Beach stay", level: 2 })).toBeInTheDocument();
      expect(screen.getByRole("list", { name: "Beach stay, day by day" })).toBeInTheDocument();
      expect(within(screen.getByRole("region", { name: "Later" })).getByRole("link", { name: "Quick flight" })).toHaveAttribute("href", "#trip/6");
    });

    it("stays listed with its day by day when no booking has a time, and does not say nothing is coming up", async () => {
      at("2026-11-21T10:00:00-05:00");
      const unknown = trip([segment({ id: 70, trip_id: 7, kind: "hotel", provider: "Marriott", origin: "Harbour Hotel", destination: null, start_local: "2026-11-20T00:00", start_zone: NY,
        end_local: "2026-11-23T00:00", end_zone: NY, details: { time_unknown: "yes" } })], { id: 7, name: "Cabin", start_date: "2026-11-20", end_date: "2026-11-23" });
      serve([unknown]);
      render(Upcoming);
      expect(await screen.findByRole("heading", { name: "Cabin", level: 2 })).toBeInTheDocument();
      expect(screen.queryByText(/Nothing coming up/)).toBeNull();
    });
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

  it("shows a flight on two bookings once, with each booking’s code to copy in the opened booking", async () => {
    at("2026-11-20T09:00:00-05:00");
    const second = segment({ id: 10, confirmation: "BBBBBB", details: { flight_number: "AA0101" }, travelers: [{ id: 9, person_id: 2, name: "Sam Doe", seat: null }] });
    serve([trip([outbound, second, stay, home])]);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR", level: 2 })).closest("section")!;
    expect(within(card).queryByRole("button", { name: /Copy confirmation code/ })).toBeNull();
    const booking = await openBooking(card);
    expect(within(booking).getByRole("button", { name: "Copy confirmation code KQ7M2X" })).toBeInTheDocument();
    expect(within(booking).getByRole("button", { name: "Copy confirmation code BBBBBB" })).toBeInTheDocument();
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

  it("shows the review line only with trips and a review count, above the next-up card, as one quiet link", async () => {
    app.state = { review_count: 2 } as never;
    serve([london]);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR" })).closest("section")!;
    const line = screen.getByTestId("review-line");
    expect(line.tagName).toBe("A");
    expect(line).toHaveAttribute("href", "#review");
    expect(line).toHaveTextContent(/^2 emails to review$/);
    expect(line).toHaveAccessibleName("2 emails to review");
    expect(line.querySelector("button")).toBeNull();
    expect(line.className).not.toMatch(/\b(border|bg-signal-soft|rounded)/);
    expect(line.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("says one email in the singular and shows no review line for none", async () => {
    app.state = { review_count: 1 } as never;
    serve([london]);
    const { unmount } = render(Upcoming);
    await screen.findByRole("heading", { name: "JFK → LHR" });
    expect(screen.getByTestId("review-line")).toHaveTextContent(/^1 email to review$/);
    unmount();
    app.state = { review_count: 0 } as never;
    render(Upcoming);
    await screen.findByRole("heading", { name: "JFK → LHR" });
    expect(screen.queryByTestId("review-line")).toBeNull();
    expect(screen.queryByText(/to review/)).toBeNull();
  });

  it("keeps the empty-state review wording, with no banner, when there are no trips", async () => {
    app.state = { review_count: 3 } as never;
    serve([], [], { configured: true, mailboxes: [box()] });
    render(Upcoming);
    expect(await screen.findByRole("heading", { name: "3 emails are waiting for your review" })).toBeInTheDocument();
    expect(screen.queryByTestId("review-line")).toBeNull();
  });

  it("is the same quiet line on a phone and on a computer, with counts only and no email details", async () => {
    app.state = { review_count: 2 } as never;
    serve([london]);
    const { unmount } = render(Upcoming);
    await screen.findByRole("heading", { name: "JFK → LHR" });
    const wide = screen.getByTestId("review-line");
    expect(wide).toHaveTextContent(/^2 emails to review$/);
    unmount();
    viewport.phone = true;
    render(Upcoming);
    await screen.findByRole("heading", { name: "JFK → LHR" });
    const line = screen.getByTestId("review-line");
    expect(line).toHaveAttribute("href", "#review");
    expect(line).toHaveTextContent(/^2 emails to review$/);
    expect(line).not.toHaveTextContent("Waypoint found");
    expect(screen.queryByRole("link", { name: "Review emails" })).toBeNull();
  });

  it("marks the first day with something still to come with a blue dot and Next, and no row or pill", async () => {
    serve([london]);
    render(Upcoming);
    const list = await screen.findByRole("list", { name: /day by day/ });
    const markers = within(list).getAllByTestId("next-marker");
    expect(markers).toHaveLength(1);
    expect(markers[0]).toHaveTextContent("Next");
    const day = markers[0].closest("li")!;
    expect(within(day).getByRole("heading", { level: 3 })).toHaveTextContent("Fri, Nov 20");
    expect(within(day).getByRole("link")).toHaveTextContent("JFK → LHR");
    expect(markers[0].previousElementSibling!.className).toMatch(/bg-primary/);
    expect(screen.queryByTestId("next-up-pill")).toBeNull();
    expect(list.querySelector("[data-next]")).toBeNull();
  });

  it("puts the Next marker on the day after an earlier day that is over, not on the earlier day", async () => {
    at("2026-11-24T12:00:00+00:00");
    serve([trip([outbound, stay])]);
    render(Upcoming);
    const toggle = await screen.findByText(/Earlier in this trip/);
    const details = toggle.closest("details")!;
    const list = screen.getByRole("list", { name: "Trip to London, day by day" });
    const markers = within(list).getAllByTestId("next-marker");
    expect(markers).toHaveLength(1);
    expect(details.contains(markers[0])).toBe(false);
    expect(markers[0].closest("li")).toHaveTextContent("Check-out: Harbour Hotel");
  });

  it("marks tomorrow, not today, when everything today is over and the trip has a booking tomorrow", async () => {
    at("2026-11-20T21:00:00-05:00");
    const done = segment({ id: 21, kind: "hotel", origin: "Morning Cafe", destination: null, start_local: "2026-11-20T08:00", end_local: "2026-11-20T09:00", end_zone: NY, details: {} });
    const later = segment({ id: 22, kind: "hotel", origin: "Evening Inn", destination: null, start_local: "2026-11-21T10:00", end_local: "2026-11-21T11:00", end_zone: NY, details: {} });
    serve([trip([done, later])]);
    render(Upcoming);
    const list = await screen.findByRole("list", { name: /day by day/ });
    const markers = within(list).getAllByTestId("next-marker");
    expect(markers).toHaveLength(1);
    expect(markers[0].closest("li")).toHaveTextContent("Evening Inn");
    expect(markers[0].closest("li")).not.toHaveTextContent("Morning Cafe");
  });

  it("does not mark a day that has only cancelled bookings", async () => {
    at("2026-11-20T09:00:00-05:00");
    const gone = segment({ id: 23, kind: "hotel", status: "cancelled", origin: "Gone Inn", destination: null, start_local: "2026-11-20T15:00", end_local: "2026-11-20T16:00", end_zone: NY, details: {} });
    const kept = segment({ id: 24, kind: "hotel", origin: "Kept Inn", destination: null, start_local: "2026-11-21T10:00", end_local: "2026-11-21T11:00", end_zone: NY, details: {} });
    serve([trip([gone, kept])]);
    render(Upcoming);
    const list = await screen.findByRole("list", { name: /day by day/ });
    const markers = within(list).getAllByTestId("next-marker");
    expect(markers).toHaveLength(1);
    expect(markers[0].closest("li")).toHaveTextContent("Kept Inn");
    expect(markers[0].closest("li")).not.toHaveTextContent("Gone Inn");
  });

  it("shows Show code in place of the chevron only on a booking with a QR code", async () => {
    const lot = segment({ id: 9, kind: "parking", provider: "Example Parking", origin: "Example Airport Long-Term Lot", destination: null, confirmation: "PK30417",
      start_local: "2099-01-09T05:15", start_zone: NY, end_local: "2099-01-13T03:00", end_zone: NY, details: {}, gate_code: { state: "ready", day: "2098-12-20" }, travelers: [] });
    const bare = segment({ id: 10, kind: "parking", provider: "Other Parking", origin: "Other Lot", destination: null, start_local: "2099-01-09T06:00", start_zone: NY,
      end_local: "2099-01-13T03:00", end_zone: NY, details: {}, gate_code: null, travelers: [] });
    at("2099-01-08T09:00:00-05:00");
    serve([trip([lot, bare, segment({ id: 11, start_local: "2099-01-09T09:00", end_local: "2099-01-09T12:00", end_zone: NY })])]);
    render(Upcoming);
    const list = await screen.findByRole("list", { name: /day by day/ });
    const rows = [...list.querySelectorAll("li.row-tap")] as HTMLElement[];
    expect(rows).toHaveLength(5);
    const shown = rows.filter((r) => within(r).queryByRole("button", { name: /^Show code/ }));
    expect(shown).toHaveLength(1);
    expect(shown[0]).toHaveTextContent("Example Airport Long-Term Lot");
    expect(shown[0].querySelector(".lucide-chevron-right")).toBeNull();
    expect(within(shown[0]).getByRole("button", { name: "Show code for Example Airport Long-Term Lot" })).toHaveClass("text-primary");
    for (const r of rows.filter((r) => r !== shown[0])) expect(r.querySelector(".lucide-chevron-right")).not.toBeNull();
  });

  it("puts the list beside the hero only for a flight, and leaves a stay’s pass card full width above it", async () => {
    at("2026-11-20T09:00:00-05:00");
    serve([london]);
    const flight = render(Upcoming);
    await screen.findByRole("heading", { name: "JFK → LHR" });
    expect(flight.container.querySelector("[data-columns]")).toHaveAttribute("data-columns", "two");
    expect(screen.getByText("Coming up")).toBeInTheDocument();
    flight.unmount();
    at("2026-11-24T12:00:00+00:00");
    serve([trip([stay])]);
    const only = render(Upcoming);
    await screen.findByRole("list", { name: /day by day/ });
    expect(only.container.querySelector("[data-columns]")).toHaveAttribute("data-columns", "one");
    expect(screen.queryByText("Coming up")).toBeNull();
  });

  it("draws no stat tile and no banner, on a phone or a computer", async () => {
    app.state = { review_count: 2 } as never;
    serve([london]);
    const wide = render(Upcoming);
    await screen.findByRole("heading", { name: "JFK → LHR" });
    for (const gone of ["trip-totals", "review-banner", "next-up-pill"]) expect(screen.queryByTestId(gone)).toBeNull();
    expect(screen.queryByRole("region", { name: "Emails to review" })).toBeNull();
    expect(screen.queryByText(/^(Nights|Bookings|Cities)$/i)).toBeNull();
    wide.unmount();
    viewport.phone = true;
    render(Upcoming);
    await screen.findByRole("heading", { name: "JFK → LHR" });
    for (const gone of ["trip-totals", "review-banner", "next-up-pill"]) expect(screen.queryByTestId(gone)).toBeNull();
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

  it("shows the Saved for offline pill, linking to the offline settings, only when offline saving is working", async () => {
    Object.assign(offline, { setUp: true, hasCopy: true, savedAt: Date.now(), trips: [{ id: 1, name: "Trip" }] });
    serve([london]);
    const { unmount } = render(Upcoming);
    expect(await screen.findByRole("link", { name: "Saved for offline" })).toHaveAttribute("href", "#settings/offline");
    expect(screen.queryByText(/Saved on this device/)).toBeNull();
    unmount();
    Object.assign(offline, { failed: true });
    render(Upcoming);
    await screen.findByRole("heading", { name: "JFK → LHR" });
    expect(screen.queryByRole("link", { name: "Saved for offline" })).toBeNull();
    expect(screen.queryByText(/Couldn’t save the trips on this device/)).toBeNull();
  });
});

describe("Upcoming side column", () => {
  const places = {
    home: null, stays: [], cities: [],
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

  it("lists every trip after the featured one, soonest first, with an All trips link", async () => {
    at("2026-11-20T09:00:00-05:00");
    serveWith([porto, london, third, lisbon], withPlaces);
    render(Upcoming);
    const card = await screen.findByRole("region", { name: "Later" });
    const rows = within(card).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("Dec 30");
    expect(rows[0]).toHaveTextContent("Lisbon in winter");
    expect(rows[0]).toHaveTextContent("In 40 days · Lisbon");
    expect(within(rows[0]).getByRole("link", { name: "Lisbon in winter" })).toHaveAttribute("href", "#trip/2");
    expect(rows[1]).toHaveTextContent("Porto weekend");
    expect(rows[1]).toHaveTextContent("In 82 days · 2 nights");
    expect(rows[2]).toHaveTextContent("Rome");
    expect(within(card).getByRole("link", { name: "All trips" })).toHaveAttribute("href", "#trips");
  });

  it("leaves the Later card out when there are no later trips", async () => {
    at("2026-11-20T09:00:00-05:00");
    serveWith([london], withPlaces);
    render(Upcoming);
    await screen.findByRole("heading", { name: "Trip to London" });
    expect(screen.queryByRole("region", { name: "Later" })).toBeNull();
    expect(screen.queryByRole("link", { name: "All trips" })).toBeNull();
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

  it("asks for no trip’s places and makes no outside fetch", async () => {
    at("2026-11-20T09:00:00-05:00");
    const outside = vi.spyOn(globalThis, "fetch");
    serveWith([london, lisbon], withPlaces);
    render(Upcoming);
    await screen.findByRole("heading", { name: "Trip to London" });
    await vi.advanceTimersByTimeAsync(0);
    expect(placesCalls()).toEqual([]);
    expect(outside).not.toHaveBeenCalled();
    outside.mockRestore();
  });

  it("draws the date of each Later trip in the amber signal colour, on a computer and on a phone", async () => {
    at("2026-11-20T09:00:00-05:00");
    serveWith([london, lisbon, porto], withPlaces);
    const wide = render(Upcoming);
    const list = await screen.findByRole("region", { name: "Later" });
    const dates = [...list.querySelectorAll("[data-later-date]")];
    expect(dates.map((d) => d.textContent)).toEqual(["Dec 30", "Feb 10"]);
    for (const d of dates) expect(d).toHaveClass("text-signal");
    wide.unmount();
    viewport.phone = true;
    render(Upcoming);
    const tiles = await screen.findByRole("region", { name: "Later" });
    const small = [...tiles.querySelectorAll("[data-later-date]")];
    expect(small.map((d) => d.textContent)).toEqual(["Dec 30", "Feb 10"]);
    for (const d of small) expect(d).toHaveClass("text-signal");
    viewport.phone = false;
  });

  it("shows only the Later tiles on a phone, with no totals and no places request", async () => {
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
    expect(placesCalls()).toEqual([]);
    viewport.phone = false;
  });
});

describe("Upcoming flights: the Home card, Flights today and the booking sheet", () => {
  const card = async () => { await screen.findByRole("heading", { name: "JFK → LHR", level: 2 }); return document.querySelector<HTMLElement>("[data-flight-home]")!; };
  const liveList = (extra: Record<string, unknown> = {}) => ({ ...delayed, statuses: [{ ...delayed.statuses[0], ...extra }] });
  const serveLive = (list: unknown, trips: unknown[] = [london]) =>
    vi.mocked(api).mockImplementation(async (path: string) => (path === "/api/flight-status" ? list : { trips }) as never);

  it("shows a delayed flight with its new times in amber, the pill, the gate and when it was updated", async () => {
    at("2026-11-20T09:09:00-05:00");
    serveLive(delayed);
    render(Upcoming);
    const home = await card();
    expect(await within(home).findByText("Delayed")).toBeInTheDocument();
    expect(within(home).getByText("B24")).toBeInTheDocument();
    expect(home.querySelector("[data-quiet]")).toHaveTextContent("50 min late");
    expect(home.querySelector("[data-when='origin']")).toHaveClass("text-signal-ink");
    expect(home.querySelector("[data-when='destination']")).toHaveClass("text-signal-ink");
    expect(within(home).getByRole("link", { name: "AA 101, JFK to LHR, delayed 50 minutes, now departs 7:50 pm" })).toHaveAttribute("href", `#trip/${london.id}/flight/1`);
    expect(within(home).getByText("Next up")).toBeInTheDocument();
    expect(within(home).queryByRole("link", { name: /^Open trip/ })).toBeNull();
    expect(within(await openBooking(home)).getByRole("link", { name: /^Open trip/ })).toHaveAttribute("href", `#trip/${london.id}?segment=1`);
  });

  it("shows the zone under each time, at its own airport, whether or not the ends differ", async () => {
    at("2026-11-20T09:09:00-05:00");
    serve([london]);
    const far = render(Upcoming);
    const home = await card();
    expect(home.querySelector("[data-zone='origin']")).toHaveTextContent("EST");
    expect(home.querySelector("[data-zone='destination']")).toHaveTextContent("GMT");
    far.unmount();
    dropEarly();
    const near = trip([segment({ id: 5, origin: "BOS", destination: "JFK", start_local: "2026-11-20T15:00", end_local: "2026-11-20T16:10", end_zone: NY, details: { flight_number: "AA 7" } })]);
    serve([near]);
    const { container } = render(Upcoming);
    await waitFor(() => expect(container.querySelectorAll("[data-flight-home]")).toHaveLength(1));
    const here = container.querySelector<HTMLElement>("[data-flight-home]")!;
    expect(here.querySelector("[data-when='origin'] time")).toHaveTextContent("3:00 PM");
    expect(here.querySelector("[data-zone='origin']")).toHaveTextContent("EST");
  });

  it("shows a flight in the air with the plane at its progress", async () => {
    at("2026-11-21T02:00:00-05:00");
    serveLive(liveList({ state: "departed", dep_actual: "2026-11-20T19:05", fetched_at: "2026-11-21T06:58:00+00:00" }));
    render(Upcoming);
    await screen.findAllByText("In the air to", { exact: false });
    const home = document.querySelector<HTMLElement>("[data-flight-home]")!;
    await waitFor(() => expect(within(home).getByText(/^In the air to /)).toBeInTheDocument());
    expect(Number(home.querySelector("article")!.dataset.progress)).toBeGreaterThan(0.8);
    expect(home.querySelector<HTMLElement>("[data-plane]")!.style.left).toMatch(/^8\d(\.\d+)?%$/);
    expect(within(home).getByText("Updated 2 minutes ago")).toBeInTheDocument();
    expect(within(home).getByRole("link", { name: /in the air, lands 8:05 am in 1 hour 5 minutes$/ })).toBeInTheDocument();
  });

  it("shows the booked times and no Updated line for a flight with no live status", async () => {
    at("2026-11-20T09:00:00-05:00");
    serve([london]);
    render(Upcoming);
    const home = await card();
    expect(home.querySelector("[data-when='origin'] time")).toHaveTextContent("7:00 PM");
    expect(home.querySelector("[data-when='destination'] time")).toHaveTextContent("7:10 AM");
    expect(home.querySelector("[data-facts] > div")).toHaveTextContent("Terminal 8");
    expect(home.querySelector("[data-updated]")).toBeNull();
  });

  it("shows two dashes only when neither the terminal nor the gate is known", async () => {
    at("2026-11-20T09:00:00-05:00");
    serve([trip([segment({ id: 1, details: { flight_number: "AA 101" } })])]);
    render(Upcoming);
    const dashes = [...(await card()).querySelectorAll("[data-facts] dd")].slice(0, 2);
    expect(dashes.map((dd) => dd.textContent)).toEqual(["—Not known yet", "—Not known yet"]);
  });

  it("keeps the full card until a day before departure, and for a flight that already landed", async () => {
    at("2026-11-18T09:00:00-05:00");
    serve([london]);
    const first = render(Upcoming);
    expect(await screen.findByText("Check-in opens in 1 day 10 h")).toBeInTheDocument();
    expect(first.container.querySelector("[data-flight-home]")).toBeNull();
    first.unmount();
    dropEarly();
    at("2026-11-21T02:00:00-05:00");
    serveLive(liveList({ state: "landed", arr_actual: "2026-11-21T01:50", fetched_at: "2026-11-21T06:30:00+00:00" }));
    render(Upcoming);
    expect(await screen.findByText("Latest flight")).toBeInTheDocument();
    await waitFor(() => expect(document.querySelector("[data-flight-home]")).toBeNull());
  });

  it("lists today’s flights, flights only, above the day-by-day list, each one link with the flight’s name", async () => {
    at("2026-11-20T09:00:00-05:00");
    serveLive(delayed);
    render(Upcoming);
    const list = await screen.findByRole("list", { name: "Flights today" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(1);
    const link = within(rows[0]).getByRole("link");
    await waitFor(() => expect(link).toHaveAccessibleName("AA 101, JFK to LHR, delayed 50 minutes, now departs 7:50 pm"));
    expect(link).toHaveAttribute("href", `#trip/${london.id}/flight/1`);
    expect(within(rows[0]).getByText("JFK to LHR · AA 101")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Departs 7:50 pm EST")).toBeInTheDocument();
    expect(rows[0].querySelector("[data-tile='flight']")).toHaveAttribute("aria-hidden", "true");
    expect(within(rows[0]).getByText("Delayed 50 min")).toBeInTheDocument();
    const days = screen.getByRole("list", { name: /day by day/ });
    expect(list.compareDocumentPosition(days) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(days).getByRole("link", { name: "JFK → LHR" })).toBeInTheDocument();
    expect(within(days).getByRole("link", { name: "Harbour Hotel" })).toBeInTheDocument();
  });

  it("leaves out later flights and cancelled bookings, and the list when nothing flies today", async () => {
    at("2026-11-20T09:00:00-05:00");
    const cancelled = segment({ id: 8, status: "cancelled", start_local: "2026-11-20T21:00", details: { flight_number: "AA 9" } });
    serve([trip([outbound, cancelled, stay, home])]);
    const first = render(Upcoming);
    const list = await screen.findByRole("list", { name: "Flights today" });
    expect(within(list).getAllByRole("link")).toHaveLength(1);
    expect(within(list).queryByText(/LHR to JFK/)).toBeNull();
    first.unmount();
    dropEarly();
    at("2026-11-23T09:00:00-05:00");
    serve([london]);
    render(Upcoming);
    await screen.findByRole("list", { name: /day by day/ });
    expect(screen.queryByRole("list", { name: "Flights today" })).toBeNull();
  });

  it("dates a flight in the air that left on another day by when it lands", async () => {
    at("2026-11-21T02:00:00-05:00");
    serve([london]);
    render(Upcoming);
    const list = await screen.findByRole("list", { name: "Flights today" });
    expect(within(list).getByText("Lands 7:10 am GMT")).toBeInTheDocument();
  });

  it("opens a flight from the day-by-day list as a compact booking with a progress bar and a link to the live status", async () => {
    viewport.phone = true;
    at("2026-11-21T02:00:00-05:00");
    serve([london]);
    render(Upcoming);
    const u = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const days = await screen.findByRole("list", { name: /day by day/ });
    await u.click(within(days).getAllByRole("link", { name: "JFK → LHR" })[0]);
    const sheet = await screen.findByRole("dialog", { name: "JFK → LHR" });
    const bar = within(sheet).getByRole("progressbar", { name: "Flight progress" });
    expect(Number(bar.getAttribute("aria-valuenow"))).toBeGreaterThan(90);
    expect(within(sheet).getByText("Departed 7:00 pm EST")).toBeInTheDocument();
    expect(within(sheet).getByText("Lands 7:10 am GMT +1 day")).toBeInTheDocument();
    expect(within(sheet).getByRole("link", { name: /^AA 101, JFK to LHR, in the air, lands 7:10 am/ })).toHaveAttribute("href", `#trip/${london.id}/flight/1`);
    expect(within(sheet).getByRole("button", { name: "Copy confirmation code KQ7M2X" })).toBeInTheDocument();
    expect(within(sheet).getByRole("link", { name: "Open trip" })).toBeInTheDocument();
    expect(within(sheet).queryByTestId("flight-status")).toBeNull();
    viewport.phone = false;
  });

  it("keeps the full card in the sheet for a booking that is cancelled", async () => {
    viewport.phone = true;
    at("2026-11-20T09:00:00-05:00");
    serve([trip([segment({ id: 1, status: "cancelled" }), stay, home])]);
    render(Upcoming);
    const u = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const days = await screen.findByRole("list", { name: /day by day/ });
    await u.click(within(days).getByRole("link", { name: "JFK → LHR" }));
    const sheet = await screen.findByRole("dialog", { name: "JFK → LHR" });
    expect(within(sheet).queryByRole("progressbar", { name: "Flight progress" })).toBeNull();
    viewport.phone = false;
  });

  it("shows no flight card and no Flights today list when the trips request returns nothing", async () => {
    at("2026-11-20T09:00:00-05:00");
    serve([]);
    render(Upcoming);
    await screen.findByRole("heading", { name: "Connect Gmail" });
    expect(screen.queryByRole("list", { name: "Flights today" })).toBeNull();
    expect(document.querySelector("[data-flight-home]")).toBeNull();
  });

  it("keeps the pause warning on the Home card and in the sheet when live updates are paused", async () => {
    at("2026-11-20T09:09:00-05:00");
    serveLive({ ...delayed, paused: { reason: "rate", until: "2026-11-20T15:00:00Z" } });
    render(Upcoming);
    const home = await card();
    expect(await within(home).findByText(/^Live updates paused until .* \(rate limit\)$/)).toBeInTheDocument();
  });

  it("keeps Times differ between bookings, and each booking’s times, in the booking sheet", async () => {
    viewport.phone = true;
    at("2026-11-21T02:00:00-05:00");
    const moved = segment({ id: 10, confirmation: "BBBBBB", start_local: "2026-11-20T21:30", details: { flight_number: "AA 101" } });
    serve([trip([outbound, moved, stay, home])]);
    render(Upcoming);
    const u = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const days = await screen.findByRole("list", { name: /day by day/ });
    await u.click(within(days).getAllByRole("link", { name: "JFK → LHR" })[0]);
    const sheet = await screen.findByRole("dialog", { name: "JFK → LHR" });
    expect(within(sheet).getByText("Times differ between bookings")).toBeInTheDocument();
    expect(within(sheet).getByText(/^KQ7M2X: departs/)).toHaveTextContent(/departs Fri, Nov 20, 7:00 PM/);
    expect(within(sheet).getByText(/^BBBBBB: departs/)).toHaveTextContent(/departs Fri, Nov 20, 9:30 PM/);
    expect(within(sheet).queryByText(/^Departed /)).toBeNull();
    expect(within(sheet).getByRole("progressbar", { name: "Flight progress" })).toBeInTheDocument();
    viewport.phone = false;
  });

  it("keeps Check in on the Next up card once check-in is open, within a day of departure", async () => {
    const managed = segment({ id: 1, manage_url: "https://example.test/manage", links: { app: null, open: null, open_kind: null, directions: null, call: null } });
    at("2026-11-20T09:00:00-05:00");
    serve([trip([managed, stay, home])]);
    const open = render(Upcoming);
    expect(within(await card()).getByRole("link", { name: "Check in" })).toHaveAttribute("href", "https://example.test/manage");
    open.unmount();
    dropEarly();
    at("2026-11-20T16:00:00-05:00");
    serve([trip([{ ...managed, start_local: "2026-11-20T19:00" }, stay, home])]);
    render(Upcoming);
    expect(within(await card()).getByRole("link", { name: "Check in" })).toBeInTheDocument();
  });

  it("moves the travellers and the cost of the Next up card into the opened booking", async () => {
    at("2026-11-20T09:00:00-05:00");
    const priced = segment({ id: 1, price: { amount_minor: 45000, currency: "USD", source: "email" } as never, travelers: [{ id: 1, person_id: 1, name: "Jane Doe", seat: null }, { id: 2, person_id: 2, name: "Sam Doe", seat: null }] });
    serve([trip([priced, stay, home])]);
    render(Upcoming);
    const mini = await card();
    expect(within(mini).queryByText("Jane & Sam")).toBeNull();
    expect(within(mini).queryByText("$450.00")).toBeNull();
    expect(mini.querySelector("[data-cost]")).toBeNull();
    const booking = await openBooking(mini);
    expect(within(booking).getByText("Jane Doe, Sam Doe")).toBeInTheDocument();
    expect(within(booking).getByText("$450.00")).toBeInTheDocument();
  });

  it("keeps Directions and Call on the Next up card when the booking has them", async () => {
    at("2026-11-20T09:00:00-05:00");
    const linked = segment({ id: 1, links: { app: null, open: null, open_kind: null, directions: "https://maps.example/jfk", call: "tel:+18005551234" } });
    serve([trip([linked, stay, home])]);
    render(Upcoming);
    const mini = await card();
    expect(within(mini).getByRole("link", { name: "Directions" })).toHaveAttribute("href", "https://maps.example/jfk");
    expect(within(mini).getByRole("link", { name: "Call" })).toHaveAttribute("href", "tel:+18005551234");
  });

  it("keeps only the airline action, Directions and Call in the Next up card's footer, and every other action in the opened booking", async () => {
    at("2026-11-20T09:00:00-05:00");
    const rich = segment({ id: 1, price: { amount_minor: 45000, currency: "USD", source: "email" } as never, links: { app: null, open: null, open_kind: null, directions: "https://maps.example/jfk", call: "tel:+18005551234" }, travelers: [{ id: 1, person_id: 1, name: "Jane Doe", seat: null }] });
    serve([trip([rich, stay, home])]);
    render(Upcoming);
    const mini = await card();
    expect(within(mini).getByRole("link", { name: "Directions" })).toBeInTheDocument();
    expect(within(mini).getByRole("link", { name: "Call" })).toBeInTheDocument();
    for (const gone of [/Copy confirmation code/, /QR code/]) expect(within(mini).queryByRole("button", { name: gone })).toBeNull();
    expect(within(mini).queryByRole("link", { name: /^Open trip/ })).toBeNull();
    expect(within(mini).queryByText("Jane")).toBeNull();
    expect(within(mini).getByRole("link", { name: /open live status|AA 101/ })).toHaveAttribute("href", `#trip/${london.id}/flight/1`);
    const booking = await openBooking(mini);
    expect(within(booking).getByRole("button", { name: "Copy confirmation code KQ7M2X" })).toBeInTheDocument();
    expect(within(booking).getByRole("link", { name: /^Open trip/ })).toHaveAttribute("href", `#trip/${london.id}?segment=1`);
    expect(within(booking).getByText("Jane Doe")).toBeInTheDocument();
    expect(within(booking).getByText("$450.00")).toBeInTheDocument();
  });

  it("draws no empty footer under the Next up card when nothing but the moved items was in it", async () => {
    at("2026-11-20T09:00:00-05:00");
    serve([london]);
    render(Upcoming);
    const mini = await card();
    expect(mini.querySelector("article > div.border-t")).toBeNull();
    expect(mini.querySelector("[data-detail]")).not.toBeNull();
  });

  it("returns focus to the detail row when the opened booking is closed with Escape", async () => {
    at("2026-11-20T09:00:00-05:00");
    serve([london]);
    render(Upcoming);
    const mini = await card();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const row = within(mini).getByRole("button", { name: "Confirmation, travellers and price" });
    await openBooking(mini);
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(row).toHaveFocus());
  });

  it("shows no price in the opened booking when the household has turned costs off", async () => {
    at("2026-11-20T09:00:00-05:00");
    const priced = segment({ id: 1, price: { amount_minor: 45000, currency: "USD", source: "email" } as never });
    app.state = { show_costs: false } as never;
    serve([trip([priced, stay, home])]);
    render(Upcoming);
    const booking = await openBooking(await card());
    expect(within(booking).queryByText("$450.00")).toBeNull();
    app.state = null;
  });

  it("hides the cost on the Next up card when the household has turned costs off", async () => {
    at("2026-11-20T09:00:00-05:00");
    const priced = segment({ id: 1, price: { amount_minor: 45000, currency: "USD", source: "email" } as never });
    app.state = { show_costs: false } as never;
    serve([trip([priced, stay, home])]);
    render(Upcoming);
    const mini = await card();
    expect(within(mini).queryByText("$450.00")).toBeNull();
    expect(mini.querySelector("[data-cost]")).toBeNull();
    app.state = null;
  });

  it("keeps the pause warning in the booking sheet too", async () => {
    viewport.phone = true;
    at("2026-11-21T02:00:00-05:00");
    serveLive({ ...delayed, paused: { reason: "limit", until: "2026-12-01T00:00:00Z" } });
    render(Upcoming);
    const u = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const days = await screen.findByRole("list", { name: /day by day/ });
    await u.click(within(days).getAllByRole("link", { name: "JFK → LHR" })[0]);
    const sheet = await screen.findByRole("dialog", { name: "JFK → LHR" });
    expect(await within(sheet).findByText(/^Live updates paused until .* \(monthly limit\)$/)).toBeInTheDocument();
    viewport.phone = false;
  });

  it("counts a flight as today by the airport’s own date, like the day-by-day list", async () => {
    at("2026-11-20T21:00:00-05:00");
    const late = segment({ id: 1, origin: "LAX", destination: "SFO", start_local: "2026-11-20T23:30", start_zone: "America/Los_Angeles", end_local: "2026-11-21T00:50", end_zone: "America/Los_Angeles", details: { flight_number: "AA 55" } });
    serve([trip([late])]);
    render(Upcoming);
    const list = await screen.findByRole("list", { name: "Flights today" });
    expect(within(list).getByText("Departs 11:30 pm PST")).toBeInTheDocument();
  });
});
