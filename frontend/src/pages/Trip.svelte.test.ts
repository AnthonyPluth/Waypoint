// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { LoyaltyEntry, Person, Trip as TripT } from "$lib/api-types";
import { route } from "$lib/app.svelte";
import { flightStatus } from "$lib/flightstatus.svelte";
import { membership, segment, trip } from "../test/fixtures";
import TripPage from "./Trip.svelte";

const jane: Person = { id: 1, display_name: "Jane Doe", first_name: "Jane", legal_name: null, aliases: [], member: true, links: [] };
const sam: Person = { id: 2, display_name: "Sam Doe", first_name: "Sam", legal_name: null, aliases: [], member: true, links: [] };
const flight = segment({ id: 1, locked_fields: ["terminal"], manage_url: "https://example.com/manage", links: { app: "https://example.com/manage", directions: null, call: null },
  travelers: [{ id: 1, person_id: 1, name: "Jane Doe" }, { id: 2, person_id: 2, name: "Sam Doe" }, { id: 3, person_id: null, name: "DOE/MIA MISS" }] });
const stay = segment({ id: 2, kind: "hotel", provider: "Marriott", origin: "Harbour Hotel", destination: null, start_local: "2026-11-21T15:00", start_zone: "Europe/London",
  end_local: "2026-11-27T10:00", end_zone: "Europe/London", confirmation: "H88231", details: { address: "1 Quay Street, London", phone: "+44 20 7946 0000" },
  links: { app: null, directions: "https://maps.apple.com/?q=1%20Quay%20Street%2C%20London", call: "tel:+442079460000" }, status: "changed", travelers: [{ id: 4, person_id: 1, name: "Jane Doe" }] });
const delayed = { enabled: true, month: "2026-11", used: 3, limit: 400, paused: null, statuses: [{
  segment_id: 1, state: "delayed", origin: "JFK", destination: "LHR", dep_scheduled: "2026-11-20T19:00", dep_estimated: "2026-11-20T19:50",
  dep_actual: null, dep_zone: "America/New_York", dep_terminal: "7", dep_gate: "B24", arr_scheduled: "2026-11-21T07:10", arr_estimated: "2026-11-21T08:05",
  arr_actual: null, arr_zone: "Europe/London", arr_terminal: null, arr_gate: null, delay_minutes: 50, fetched_at: "2026-11-20T14:05:00+00:00" }] };
let held: TripT;
let loyalty: LoyaltyEntry[];

function serve() {
  vi.mocked(api).mockImplementation(async (path, opts) => {
    if (path.endsWith("/reveal")) return { number: "DEMO1234567" };
    if (path === "/api/people") return { people: [jane, sam] };
    if (path === "/api/loyalty") return { loyalty, programs: {} };
    if (path.startsWith("/api/segments/") && opts?.method === "DELETE") { held = { ...held, segments: held.segments.filter((s) => s.id !== 2) }; return { ok: true }; }
    if (path.startsWith("/api/segments/") && opts?.method === "POST") return flight;
    return held;
  });
}

beforeEach(() => {
  vi.mocked(api).mockReset();
  held = trip([flight, stay]);
  loyalty = [membership()];
  route.page = "trip"; route.sub = "1"; location.hash = "#trip/1";
  serve();
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); flightStatus.list = null; });

describe("Trip", () => {
  it("shows a flight’s live status on its card and none on a stay", async () => {
    const answer = vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation(async (path, opts) => (path === "/api/flight-status" ? delayed : answer(path, opts)) as never);
    render(TripPage);
    const cards = within(await screen.findByRole("list", { name: "Bookings" })).getAllByRole("listitem").filter((li) => li.classList.contains("pass"));
    expect(await within(cards[0]).findByTestId("flight-status")).toHaveTextContent("Delayed 50 min");
    expect(within(cards[1]).queryByTestId("flight-status")).toBeNull();
  });

  it("asks for a look at the times of a booking whose times couldn’t be settled, and only that one", async () => {
    held = trip([{ ...flight, check_times: true }, stay]);
    render(TripPage);
    const cards = within(await screen.findByRole("list", { name: "Bookings" })).getAllByRole("listitem").filter((li) => li.classList.contains("pass"));
    expect(within(cards[0]).getByRole("note")).toHaveTextContent(/Check the times/);
    expect(within(cards[1]).queryByRole("note")).toBeNull();
  });

  it("shows a flight with no times by its day: “time not recorded” at both ends, and no live status", async () => {
    held = trip([segment({ id: 1, origin: "LAX", destination: "JFK", start_local: "2026-03-08T00:00", start_zone: "America/Los_Angeles",
      end_local: "2026-03-08T03:00", end_zone: "America/New_York", details: { flight_number: "DL 1002", time_unknown: "yes" } })]);
    const answer = vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation(async (path, opts) => (path === "/api/flight-status" ? delayed : answer(path, opts)) as never);
    render(TripPage);
    const card = (await screen.findByRole("list", { name: "Bookings" })).querySelector(".pass") as HTMLElement;
    expect(within(card).getAllByText("time not recorded")).toHaveLength(2);
    expect(within(card).queryByText(/12:00 AM|3:00 AM/)).toBeNull();
    expect(within(card).queryByTestId("flight-status")).toBeNull();
  });

  it("offers each booking’s actions, and no Wallet", async () => {
    render(TripPage);
    await screen.findByRole("heading", { name: "Trip to London" });
    const hotel = within(screen.getByRole("group", { name: /Actions for Harbour Hotel/ }));
    expect(hotel.getByRole("link", { name: "Directions" })).toHaveAttribute("href", "https://maps.apple.com/?q=1%20Quay%20Street%2C%20London");
    expect(hotel.getByRole("link", { name: "Call" })).toHaveAttribute("href", "tel:+442079460000");
    expect(hotel.queryByRole("link", { name: "Manage booking" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Wallet" })).toBeNull();
  });

  it("offers the provider's app, and no Wallet, on iOS", async () => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)");
    render(TripPage);
    await screen.findByRole("heading", { name: "Trip to London" });
    expect(screen.queryByRole("link", { name: "Wallet" })).toBeNull();
    expect(screen.getAllByRole("link", { name: "Open in app" })[0]).toHaveAttribute("href", "https://example.com/manage");
  });

  it("keeps a cancelled booking’s manage link and drops its other actions", async () => {
    held = trip([{ ...stay, status: "cancelled", links: { app: "https://example.com/manage", directions: "https://maps.apple.com/?q=x", call: "tel:+442079460000" } }]);
    render(TripPage);
    await screen.findByRole("heading", { name: "Trip to London" });
    const group = within(screen.getByRole("group", { name: /Actions for Harbour Hotel/ }));
    expect(group.getByRole("link", { name: "Manage booking" })).toHaveAttribute("href", "https://example.com/manage");
    expect(group.queryByRole("link", { name: "Directions" })).toBeNull();
    expect(group.queryByRole("link", { name: "Call" })).toBeNull();
  });

  it("shows each booking with its local times, who is on it and the number each would use", async () => {
    render(TripPage);
    expect(await screen.findByRole("heading", { name: "Trip to London" })).toBeInTheDocument();
    const cards = within(screen.getByRole("list", { name: "Bookings" })).getAllByRole("listitem", { name: "" }).filter((li) => li.classList.contains("pass"));
    const first = within(cards[0]);
    expect(first.getByRole("heading", { name: "JFK → LHR" })).toBeInTheDocument();
    expect(first.getByText("7:00 PM")).toBeInTheDocument();
    expect(first.getByText("7:10 AM")).toBeInTheDocument();
    expect(first.getByText("Edited by you")).toBeInTheDocument();
    expect(first.getByRole("link", { name: "Manage booking" })).toHaveAttribute("href", "https://example.com/manage");
    // Jane has an AAdvantage number (masked); Sam has none, with a hint; a printed name isn't matched yet.
    expect(first.getByRole("button", { name: "Show and copy American AAdvantage number" })).toHaveTextContent("••••4567");
    expect(first.getByText(/No American AAdvantage number yet/)).toBeInTheDocument();
    expect(first.getByText(/Not matched to a person/)).toBeInTheDocument();
    const hotel = within(cards[1]);
    expect(hotel.getByText("Changed")).toBeInTheDocument();
    expect(hotel.getByText(/No Marriott Bonvoy number yet/)).toBeInTheDocument();
  });

  it("reveals a number only when asked, copies it, and hides it again", async () => {
    render(TripPage);
    const u = userEvent.setup();
    const button = await screen.findByRole("button", { name: "Show and copy American AAdvantage number" });
    expect(api).not.toHaveBeenCalledWith(expect.stringContaining("/reveal"), expect.anything());
    await u.click(button);
    expect(await screen.findByRole("button", { name: "Hide American AAdvantage number" })).toHaveTextContent("DEMO1234567");
    expect(await navigator.clipboard.readText()).toBe("DEMO1234567");
    await u.click(screen.getByRole("button", { name: "Hide American AAdvantage number" }));
    expect(screen.getByRole("button", { name: "Show and copy American AAdvantage number" })).toHaveTextContent("••••4567");
  });

  it("says a number can't be read with this key rather than showing nothing", async () => {
    loyalty = [membership({ readable: false, masked: "••••" })];
    render(TripPage);
    expect(await screen.findByText(/Can’t be read with this key/)).toBeInTheDocument();
  });

  it("says there's no such trip for one that isn't yours or doesn't exist, and for an address without one", async () => {
    vi.mocked(api).mockRejectedValue(new Error("No such trip"));
    render(TripPage);
    expect(await screen.findByText("No such trip")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Trip to London" })).toBeNull();
  });

  it("doesn't let a slow earlier load put its trip on screen under a newer address", async () => {
    let release: (t: TripT) => void = () => {};
    const slow = new Promise<TripT>((r) => { release = r; });
    vi.mocked(api).mockImplementation(async (path) => {
      if (path === "/api/trips/1") return slow;
      if (path === "/api/trips/2") return trip([flight], { id: 2, name: "Trip to Auckland" });
      return path === "/api/people" ? { people: [jane, sam] } : { loyalty, programs: {} };
    });
    render(TripPage);
    route.sub = "2";
    expect(await screen.findByRole("heading", { name: "Trip to Auckland" })).toBeInTheDocument();
    release(held);
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByRole("heading", { name: "Trip to London" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Trip to Auckland" })).toBeInTheDocument();
  });

  it("doesn't ask the server for a trip with no number in its address", async () => {
    route.sub = "";
    render(TripPage);
    expect(await screen.findByText("No such trip")).toBeInTheDocument();
    expect(api).not.toHaveBeenCalled();
  });

  it("doesn't leave the trip on screen looking current when a reload fails", async () => {
    render(TripPage);
    const u = userEvent.setup();
    await screen.findByRole("heading", { name: "Trip to London" });
    await u.click(screen.getByRole("button", { name: "Remove Harbour Hotel" }));
    vi.mocked(api).mockImplementation(async (path, opts) => {
      if (opts?.method === "DELETE") return { ok: true };
      throw new Error("Waypoint is unreachable");
    });
    await u.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(await screen.findByText("Waypoint is unreachable")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Trip to London" })).toBeNull();
    serve();
    document.body.style.pointerEvents = "";   // the dialog's scroll lock lingers in jsdom after it closes
    await u.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Trip to London" })).toBeInTheDocument();
  });

  it("edits a booking, sending what's there with the change, and reloads", async () => {
    render(TripPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Edit JFK → LHR" }));
    expect(screen.getByText(/a later email won’t put it back/)).toBeInTheDocument();
    expect(screen.getByLabelText("Terminal")).toHaveValue("8");
    await u.clear(screen.getByLabelText("Terminal"));
    await u.type(screen.getByLabelText("Terminal"), "7");
    await u.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/segments/1", { method: "POST", body: expect.objectContaining({
      kind: "flight", origin: "JFK", details: { flight_number: "AA 101", terminal: "7" }, travelers: [{ person_id: 1 }, { person_id: 2 }, { person_id: null, name: "DOE/MIA MISS" }] }) }));
    await waitFor(() => expect(screen.queryByRole("form")).toBeNull());
  });

  it("explains a slip in the edit form without sending it, and keeps what was typed", async () => {
    render(TripPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Edit JFK → LHR" }));
    await u.clear(screen.getByLabelText(/From \(airport\)/));
    await u.type(screen.getByLabelText(/From \(airport\)/), "N1");
    await u.type(screen.getByLabelText("Seat"), "12A");
    await u.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A flight’s origin is an airport code like JFK");
    expect(api).not.toHaveBeenCalledWith("/api/segments/1", expect.anything());
    expect(screen.getByLabelText("Seat")).toHaveValue("12A");
  });

  it("keeps what was typed and says why when a save fails", async () => {
    render(TripPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Edit JFK → LHR" }));
    await u.type(screen.getByLabelText("Seat"), "12A");
    vi.mocked(api).mockImplementation(async (path, opts) => {
      if (opts?.method === "POST") throw new Error("Someone on this isn’t in People");
      return held;
    });
    await u.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Someone on this isn’t in People");
    expect(screen.getByLabelText("Seat")).toHaveValue("12A");
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("adds a booking to this trip", async () => {
    render(TripPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: /Add a booking/ }));
    await u.selectOptions(screen.getByLabelText("What is it"), "Hotel");
    await u.type(screen.getByLabelText("Hotel name"), "Harbour Hotel");
    await u.type(screen.getByLabelText(/^Check-in/), "2026-11-21T15:00");
    await u.type(screen.getByLabelText(/^Check-out/), "2026-11-27T10:00");
    await u.type(screen.getByLabelText("Time zone"), "Europe/London");
    await u.click(screen.getByLabelText("Sam Doe"));
    await u.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/segments", { method: "POST", body: expect.objectContaining({
      trip_id: 1, kind: "hotel", origin: "Harbour Hotel", start_zone: "Europe/London", end_zone: "Europe/London", travelers: [{ person_id: 2 }] }) }));
  });

  it("removes a booking after asking", async () => {
    render(TripPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Remove Harbour Hotel" }));
    await u.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/segments/2", { method: "DELETE" }));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Harbour Hotel" })).toBeNull());
  });

  describe("a flight on two bookings", () => {
    const sams = segment({ id: 5, confirmation: "BBBBBB", details: { flight_number: "AA0101" }, manage_url: "https://example.com/manage/b",
      links: { app: "https://example.com/manage/b", directions: null, call: null }, travelers: [{ id: 9, person_id: 2, name: "Sam Doe" }] });
    beforeEach(() => { held = trip([flight, sams, stay]); });

    it("is one card for the flight with a block for each booking: its code, its travellers, its own Edit and Remove", async () => {
      render(TripPage);
      const list = await screen.findByRole("list", { name: "Bookings" });
      const cards = within(list).getAllByRole("listitem").filter((li) => li.classList.contains("pass"));
      expect(cards).toHaveLength(2);   // (the flight once, then the stay)
      expect(within(cards[0]).getAllByRole("heading", { name: "JFK → LHR" })).toHaveLength(1);
      const blocks = within(cards[0]).getAllByRole("listitem").filter((li) => li.hasAttribute("data-booking"));
      expect(blocks).toHaveLength(2);
      expect(within(blocks[0]).getByRole("button", { name: "Copy confirmation code KQ7M2X" })).toBeInTheDocument();
      expect(within(blocks[0]).getByText("Jane Doe")).toBeInTheDocument();
      expect(within(blocks[0]).queryByText("Sam Doe")).toBeInTheDocument();   // (flight's own travellers: Jane, Sam and a printed name)
      expect(within(blocks[1]).getByRole("button", { name: "Copy confirmation code BBBBBB" })).toBeInTheDocument();
      expect(within(blocks[1]).getByText("Sam Doe")).toBeInTheDocument();
      expect(within(blocks[1]).queryByText("Jane Doe")).toBeNull();
      expect(within(blocks[1]).getByRole("link", { name: /Manage booking|Open in app/ })).toHaveAttribute("href", "https://example.com/manage/b");
      expect(within(blocks[0]).getByRole("button", { name: "Edit JFK → LHR booking KQ7M2X" })).toBeInTheDocument();
      expect(within(blocks[1]).getByRole("button", { name: "Edit JFK → LHR booking BBBBBB" })).toBeInTheDocument();
      expect(within(cards[0]).queryByText("Times differ between bookings")).toBeNull();
      expect(within(cards[0]).getAllByText("Departs")).toHaveLength(1);   // (the times once)
    });

    it("removes the one booking whose Remove was pressed, and keeps the flight", async () => {
      render(TripPage);
      const u = userEvent.setup();
      await u.click(await screen.findByRole("button", { name: "Remove JFK → LHR booking BBBBBB" }));
      await u.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Remove" }));
      await waitFor(() => expect(api).toHaveBeenCalledWith("/api/segments/5", { method: "DELETE" }));
      expect(api).not.toHaveBeenCalledWith("/api/segments/1", expect.anything());
    });

    it("says when the bookings disagree on the times, and shows each booking’s own rather than picking one", async () => {
      held = trip([flight, { ...sams, start_local: "2026-11-20T21:30" }, stay]);
      render(TripPage);
      const card = (await screen.findAllByRole("heading", { name: "JFK → LHR" }))[0].closest("li.pass") as HTMLElement;
      expect(within(card).getByText("Times differ between bookings")).toBeInTheDocument();
      expect(within(card).getByText("9:30 PM")).toBeInTheDocument();
      expect(within(card).getByText("7:00 PM")).toBeInTheDocument();
      expect(within(card).getAllByText("Departs")).toHaveLength(2);   // (once in each booking's block)
    });
  });

  describe("a stay’s address", () => {
    it("shows it as written, copies it on a tap, and Directions uses it", async () => {
      const writeText = vi.fn().mockResolvedValue(undefined);
      vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
      held = trip([{ ...stay, details: { address: "1 Quay Street\nLondon E1 0AA" } }]);
      render(TripPage);
      await userEvent.click(await screen.findByRole("button", { name: /Copy address 1 Quay Street/ }));
      expect(writeText).toHaveBeenCalledWith("1 Quay Street\nLondon E1 0AA");
      expect(screen.queryByRole("button", { name: /Add address/ })).toBeNull();
      expect(screen.getByRole("link", { name: "Directions" })).toHaveAttribute("href", stay.links.directions!);
    });

    it("offers Add address only when there is none, and opens the form at the address field", async () => {
      held = trip([flight, { ...stay, details: {}, links: { app: null, directions: "https://maps.apple.com/?q=Harbour%20Hotel", call: null } }]);
      const u = userEvent.setup();
      render(TripPage);
      await screen.findByRole("heading", { name: "Trip to London" });
      expect(screen.getAllByRole("button", { name: /Add address/ })).toHaveLength(1);   // (not on the flight)
      await u.click(await screen.findByRole("button", { name: "Add address to Harbour Hotel" }));
      const field = await screen.findByLabelText("Address");
      expect(field.tagName).toBe("TEXTAREA");
      expect(field).toHaveFocus();
    });

    it("saves an address typed in the form, trimmed, with its lines", async () => {
      held = trip([{ ...stay, details: {} }]);
      const u = userEvent.setup();
      render(TripPage);
      await u.click(await screen.findByRole("button", { name: "Add address to Harbour Hotel" }));
      await u.type(await screen.findByLabelText("Address"), "  7 Mill Lane{Enter}London N1 1AA ");
      await u.click(screen.getByRole("button", { name: "Save" }));
      const post = vi.mocked(api).mock.calls.find(([path, o]) => path === "/api/segments/2" && o?.method === "POST")!;
      expect((post[1] as { body: { details: Record<string, string> } }).body.details.address).toBe("7 Mill Lane\nLondon N1 1AA");
    });
  });

  describe("a cruise", () => {
    const ship = segment({ id: 5, kind: "cruise", provider: "Example Cruise Line", origin: "Miami", destination: "Miami", start_zone: "America/New_York", end_zone: "America/New_York",
      start_local: "2026-03-01T16:30", end_local: "2026-03-08T07:00", confirmation: "CR48210", details: { ship: "Example Voyager", room: "9214", address: "1 Port Boulevard\nMiami" },
      links: { app: null, directions: "https://maps.apple.com/?q=1%20Port%20Boulevard%20Miami", call: null },
      itinerary: [{ name: "Nassau", zone: "America/Nassau", arrive_local: "2026-03-02T08:00", depart_local: "2026-03-02T17:00" },
                  { name: "Cozumel", zone: "America/Cancun", arrive_local: null, depart_local: null }] });

    it("lists its ports of call with their local times, its terminal address, and Directions to it", async () => {
      held = trip([ship]);
      render(TripPage);
      const ports = (await screen.findByText("Ports of call")).closest("[data-itinerary]") as HTMLElement;
      const rows = within(ports).getAllByRole("listitem");
      expect(rows).toHaveLength(2);
      expect(rows[0]).toHaveTextContent("Nassau");
      expect(rows[0]).toHaveTextContent(/arrives .*8:00 AM.*leaves .*5:00 PM/);
      expect(rows[1]).toHaveTextContent("Cozumel");
      expect(rows[1]).toHaveTextContent("Time not recorded");
      expect(screen.getByText("Terminal address")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Directions" })).toHaveAttribute("href", ship.links.directions!);
      expect(screen.getByText("Embarks")).toBeInTheDocument();
    });

    it("shows no ports section for a cruise without any", async () => {
      held = trip([{ ...ship, itinerary: [] }]);
      render(TripPage);
      await screen.findByRole("heading", { name: "Example Voyager · Miami" });
      expect(screen.queryByText("Ports of call")).toBeNull();
    });

    it("edits the ports: adds one in the last one’s zone, moves, removes, and sends them in order", async () => {
      held = trip([ship]);
      const u = userEvent.setup();
      render(TripPage);
      await u.click(await screen.findByRole("button", { name: "Edit Example Voyager · Miami" }));
      expect(screen.getByLabelText("Port 1 name")).toHaveValue("Nassau");
      await u.click(screen.getByRole("button", { name: "Add a port" }));
      expect(screen.getByLabelText("Port 3 time zone")).toHaveValue("America/Cancun");
      await u.type(screen.getByLabelText("Port 3 name"), "Grand Cayman");
      await u.click(screen.getByRole("button", { name: "Move port 3 up" }));
      expect(screen.getByLabelText("Port 2 name")).toHaveValue("Grand Cayman");
      await u.click(screen.getByRole("button", { name: "Remove port 1" }));
      expect(screen.getByLabelText("Port 1 name")).toHaveValue("Grand Cayman");
      expect(screen.queryByLabelText("Port 3 name")).toBeNull();
      await u.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() => expect(api).toHaveBeenCalledWith("/api/segments/5", { method: "POST", body: expect.objectContaining({
        kind: "cruise", itinerary: [{ name: "Grand Cayman", zone: "America/Cancun", arrive_local: null, depart_local: null },
                                    { name: "Cozumel", zone: "America/Cancun", arrive_local: null, depart_local: null }] }) }));
    });

    it("says what is wrong with a port without sending, and shows the ports section only for a cruise", async () => {
      held = trip([ship, flight]);
      const u = userEvent.setup();
      render(TripPage);
      await u.click(await screen.findByRole("button", { name: "Edit Example Voyager · Miami" }));
      await u.clear(screen.getByLabelText("Port 1 name"));
      await u.click(screen.getByRole("button", { name: "Save" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("Name port 1");
      expect(vi.mocked(api).mock.calls.some(([, o]) => o?.method === "POST")).toBe(false);
      await u.click(screen.getByRole("button", { name: "Cancel" }));
      await u.click(screen.getByRole("button", { name: "Edit JFK → LHR" }));
      expect(screen.queryByText("Ports of call", { selector: "legend" })).toBeNull();
    });
  });
});
