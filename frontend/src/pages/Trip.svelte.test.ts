// @vitest-environment jsdom
import { chooseZone } from "../test/zone";
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { LoyaltyEntry, Person, Trip as TripT } from "$lib/api-types";
import { app, route } from "$lib/app.svelte";
import { flightStatus } from "$lib/flightstatus.svelte";
import { viewport } from "$lib/phone.svelte";
import { membership, segment, state, trip } from "../test/fixtures";
import { bookingOptions, tripOptions } from "../test/menu";
import TripPage from "./Trip.svelte";

const jane: Person = { id: 1, display_name: "Jane Doe", first_name: "Jane", legal_name: null, aliases: [], member: true, links: [] };
const sam: Person = { id: 2, display_name: "Sam Doe", first_name: "Sam", legal_name: null, aliases: [], member: true, links: [] };
const flight = segment({ id: 1, locked_fields: ["terminal"], manage_url: "https://example.com/manage", links: { app: "https://example.com/manage", open: null, open_kind: null, directions: null, call: null },
  travelers: [{ id: 1, person_id: 1, name: "Jane Doe", seat: null }, { id: 2, person_id: 2, name: "Sam Doe", seat: null }, { id: 3, person_id: null, name: "DOE/MIA MISS", seat: null }] });
const stay = segment({ id: 2, kind: "hotel", provider: "Marriott", origin: "Harbour Hotel", destination: null, start_local: "2026-11-21T15:00", start_zone: "Europe/London",
  end_local: "2026-11-27T10:00", end_zone: "Europe/London", confirmation: "H88231", details: { address: "1 Quay Street, London", phone: "+44 20 7946 0000" },
  links: { app: null, open: null, open_kind: null, directions: "https://www.google.com/maps/search/?api=1&query=1%20Quay%20Street%2C%20London", call: "tel:+442079460000" }, status: "changed", travelers: [{ id: 4, person_id: 1, name: "Jane Doe", seat: null }] });
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
  loyalty = [membership(), membership({ id: 12, kind: "hotel", program: "Marriott Bonvoy", masked: "••••8899" })];
  route.page = "trip"; route.sub = "1"; route.query = ""; location.hash = "#trip/1";
  serve();
});
afterEach(() => { app.state = null; vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); flightStatus.list = null; delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView; });

describe("Trip", () => {
  it("shows a flight’s live status on its card and none on a stay", async () => {
    const answer = vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation(async (path, opts) => (path === "/api/flight-status" ? delayed : answer(path, opts)) as never);
    render(TripPage);
    const cards = within(await screen.findByRole("list", { name: "Bookings" })).getAllByRole("listitem").filter((li) => li.classList.contains("pass"));
    expect(await within(cards[0]).findByTestId("flight-status")).toHaveTextContent("Delayed 50 min");
    expect(within(cards[1]).queryByTestId("flight-status")).toBeNull();
  });

  it("shows each booking’s brand logo on its card, and none where the server has none", async () => {
    held = trip([{ ...flight, logo: "/api/segments/1/logo" }, stay]);
    render(TripPage);
    const cards = within(await screen.findByRole("list", { name: "Bookings" })).getAllByRole("listitem").filter((li) => li.classList.contains("pass"));
    expect(cards[0].querySelector("img")?.getAttribute("src")).toBe("/api/segments/1/logo");
    expect(cards[1].querySelector("img")).toBeNull();
  });

  describe("travellers", () => {
    const at = (s: ReturnType<typeof segment>) => `segment-${s.id}`;
    const car = segment({ id: 3, kind: "car", provider: "Local Cars", origin: "LHR", destination: null, confirmation: "C1", start_local: "2026-11-22T09:00", start_zone: "Europe/London",
      end_local: "2026-11-25T09:00", end_zone: "Europe/London", travelers: [{ id: 5, person_id: 1, name: "Jane Doe", seat: null }, { id: 6, person_id: 2, name: "Sam Doe", seat: null }] });
    const flightFor = segment({ id: 1, travelers: [{ id: 1, person_id: 1, name: "Jane Doe", seat: "31A" }, { id: 2, person_id: 2, name: "Sam Doe", seat: "31B" }] });
    const cardOf = async (s: ReturnType<typeof segment>) => (await screen.findByRole("list", { name: "Bookings" })).querySelector(`#${at(s)}`) as HTMLElement;

    beforeEach(() => { app.state = state({ person_id: 1 }); });

    it("lists the trip's people once at the top, without repeats", async () => {
      held = trip([flightFor, car, { ...stay, travelers: [{ id: 4, person_id: 1, name: "Jane Doe", seat: null }] }]);
      render(TripPage);
      await screen.findByRole("list", { name: "Bookings" });
      expect(document.querySelectorAll("[data-trip-travellers]")).toHaveLength(1);
      expect(document.querySelector("[data-trip-travellers]")).toHaveTextContent("Travellers Jane Doe, Sam Doe");
    });

    it("keeps a flight's travellers and seats", async () => {
      held = trip([flightFor, car]);
      render(TripPage);
      const card = await cardOf(flightFor);
      expect(card).toHaveTextContent("Jane Doe · Seat 31A");
      expect(card).toHaveTextContent("Sam Doe · Seat 31B");
    });

    it("keeps a booking-level seat that no traveller holds", async () => {
      const odd = segment({ id: 1, details: { seat: "99Z" }, travelers: [{ id: 1, person_id: 1, name: "Jane Doe", seat: "12A" }, { id: 2, person_id: 2, name: "Sam Doe", seat: null }] });
      held = trip([odd, car]);
      render(TripPage);
      const card = await cardOf(odd);
      expect(card).toHaveTextContent("99Z");
      expect(card).toHaveTextContent("Jane Doe · Seat 12A");
    });

    it("lists each seat once on a flight, beside its traveller", async () => {
      held = trip([flightFor, car]);
      render(TripPage);
      const card = await cardOf(flightFor);
      expect(card.textContent?.match(/31A/g)).toHaveLength(1);
      expect(card.textContent?.match(/31B/g)).toHaveLength(1);
    });

    it("never lists travellers on a rental car, whether it has the trip's full set or a smaller one", async () => {
      held = trip([flightFor, car]);
      const { unmount } = render(TripPage);
      let card = await cardOf(car);
      expect(within(card).queryByText("Travellers")).toBeNull();
      expect(card).not.toHaveTextContent("Sam Doe");
      unmount();
      held = trip([flightFor, { ...car, travelers: [car.travelers[1]] }]);
      render(TripPage);
      card = await cardOf(car);
      expect(within(card).queryByText("Travellers")).toBeNull();
      expect(card).not.toHaveTextContent("Sam Doe");
    });

    it("shows a hotel's loyalty number on its own line without the traveller list", async () => {
      loyalty = [membership({ id: 12, person_id: 1, kind: "hotel", program: "Marriott Bonvoy", masked: "••••821L" })];
      held = trip([flightFor, { ...stay, booked_by: 1, travelers: [
        { id: 4, person_id: 1, name: "Jane Doe", seat: null }, { id: 5, person_id: 2, name: "Sam Doe", seat: null }, { id: 6, person_id: null, name: "DOE/MIA MISS", seat: null }] }]);
      render(TripPage);
      const card = await cardOf(stay);
      expect(within(card).queryByText("Travellers")).toBeNull();
      expect(card).not.toHaveTextContent("Sam Doe");
      expect(card).not.toHaveTextContent("DOE/MIA MISS");
      const line = card.querySelector("[data-membership]")!;
      expect(line).toHaveTextContent("Marriott Bonvoy");
      expect(line).toHaveTextContent("••••821L");
      expect(card).not.toHaveTextContent("Jane Doe");
    });

    it("lists several loyalty numbers one per line under Loyalty, with no names, and no block without one", async () => {
      loyalty = [membership({ id: 12, person_id: 1, kind: "hotel", program: "Marriott Bonvoy", masked: "••••821L" }), membership({ id: 13, person_id: 2, kind: "hotel", program: "Marriott Bonvoy", masked: "••••5512" })];
      held = trip([flightFor, { ...stay, travelers: [{ id: 4, person_id: 1, name: "Jane Doe", seat: null }, { id: 5, person_id: 2, name: "Sam Doe", seat: null }] }]);
      const { unmount } = render(TripPage);
      let card = await cardOf(stay);
      expect(card.querySelectorAll("[data-membership] li")).toHaveLength(2);
      expect(within(card).getByText("Loyalty")).toBeInTheDocument();
      expect(card).not.toHaveTextContent("Sam Doe");
      expect(card).not.toHaveTextContent("Jane Doe");
      unmount();
      loyalty = [];
      render(TripPage);
      card = await cardOf(stay);
      expect(card.querySelector("[data-membership]")).toBeNull();
      expect(within(card).queryByText("Loyalty")).toBeNull();
    });

    it("leaves the line out for a trip only the viewer is on, and shows it for someone else", async () => {
      held = trip([segment({ id: 1, travelers: [{ id: 1, person_id: 1, name: "Jane Doe", seat: null }] })]);
      const { unmount } = render(TripPage);
      await screen.findByRole("list", { name: "Bookings" });
      expect(document.querySelector("[data-trip-travellers]")).toBeNull();
      unmount();
      app.state = state({ person_id: 2 });
      render(TripPage);
      await screen.findByRole("list", { name: "Bookings" });
      expect(document.querySelector("[data-trip-travellers]")).toHaveTextContent("Jane Doe");
    });
  });

  describe("what the header and each booking put first", () => {
    it("leads with Add a booking and keeps Merge and Delete under Trip options", async () => {
      render(TripPage);
      const u = userEvent.setup();
      expect(await screen.findByRole("button", { name: "Add a booking" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Delete trip" })).toBeNull();
      expect(screen.queryByRole("button", { name: "Merge another trip" })).toBeNull();
      await u.click(screen.getByRole("button", { name: "Trip options" }));
      expect(screen.getByRole("button", { name: "Merge another trip" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Delete trip" })).toBeInTheDocument();
    });

    it("keeps Edit on each booking and Move and Remove under that booking’s More menu", async () => {
      render(TripPage);
      const u = userEvent.setup();
      expect(await screen.findByRole("button", { name: "Edit Harbour Hotel" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Move Harbour Hotel" })).toBeNull();
      expect(screen.queryByRole("button", { name: "Remove Harbour Hotel" })).toBeNull();
      await u.click(screen.getByRole("button", { name: "More options for Harbour Hotel" }));
      expect(screen.getByRole("button", { name: "Move Harbour Hotel" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Remove Harbour Hotel" })).toBeInTheDocument();
    });
  });

  describe("deleting a trip", () => {
    it("names the trip and how many bookings go with it, and does nothing until confirmed", async () => {
      render(TripPage);
      const u = userEvent.setup();
      await tripOptions(u, "Delete trip");
      const dialog = await screen.findByRole("dialog");
      expect(dialog).toHaveTextContent(/Delete .*\?/);
      expect(dialog).toHaveTextContent("Its 2 bookings are removed too. This can’t be undone.");
      await u.click(within(dialog).getByRole("button", { name: "Cancel" }));
      expect(api).not.toHaveBeenCalledWith("/api/trips/1", expect.objectContaining({ method: "DELETE" }));
    });

    it("says it in the singular for one booking", async () => {
      held = trip([flight]);
      render(TripPage);
      await tripOptions(userEvent, "Delete trip");
      expect(await screen.findByRole("dialog")).toHaveTextContent("Its 1 booking is removed too.");
    });

    it("deletes the trip once confirmed and goes back to Trips", async () => {
      render(TripPage);
      const u = userEvent.setup();
      await tripOptions(u, "Delete trip");
      await u.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete trip" }));
      await waitFor(() => expect(api).toHaveBeenCalledWith("/api/trips/1", { method: "DELETE" }));
      await waitFor(() => expect(location.hash).toBe("#trips"));
    });

    it("goes back to Trips after a delete even with a rename half typed, without asking to discard it", async () => {
      render(TripPage);
      const u = userEvent.setup();
      await u.click(await screen.findByRole("button", { name: "Edit trip details" }));
      await u.type(screen.getByLabelText("Name"), " again");
      await tripOptions(u, "Delete trip");
      await u.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete trip" }));
      await waitFor(() => expect(route.page).toBe("trips"));
      expect(location.hash).toBe("#trips");
      expect(screen.queryByRole("dialog", { name: "Discard changes?" })).toBeNull();
    });

    it("keeps the dialog open when the delete fails", async () => {
      const answer = vi.mocked(api).getMockImplementation()!;
      vi.mocked(api).mockImplementation(async (path, opts) => {
        if (path === "/api/trips/1" && opts?.method === "DELETE") throw new Error("No such trip");
        return answer(path, opts) as never;
      });
      render(TripPage);
      const u = userEvent.setup();
      await tripOptions(u, "Delete trip");
      await u.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete trip" }));
      await waitFor(() => expect(api).toHaveBeenCalledWith("/api/trips/1", { method: "DELETE" }));
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });
  });

  describe("moving bookings and merging trips", () => {
    const march = trip([segment({ id: 9, start_local: "2026-03-01T10:00", end_local: "2026-03-01T12:00" })], { id: 7, name: "Spring trip" });

    function withOthers() {
      const answer = vi.mocked(api).getMockImplementation()!;
      vi.mocked(api).mockImplementation(async (path, opts) => {
        if (path === "/api/trips" && !opts) return { trips: [held, march] } as never;
        if (path === "/api/trips/1/merge") return { ...held, segments: [...held.segments, ...march.segments] } as never;
        if (path.endsWith("/move")) return march as never;
        return answer(path, opts) as never;
      });
    }

    it("merges another trip into this one, listing only the others", async () => {
      withOthers();
      render(TripPage);
      const u = userEvent.setup();
      await tripOptions(u, "Merge another trip");
      const dialog = await screen.findByRole("dialog");
      const choose = await within(dialog).findByRole("combobox", { name: "Trip to merge in" });
      await waitFor(() => expect(within(choose).getAllByRole("option")).toHaveLength(2));
      expect(within(choose).getByRole("option", { name: /Spring trip/ })).toBeInTheDocument();
      expect(within(dialog).getByRole("button", { name: "Merge" })).toBeDisabled();
      await u.selectOptions(choose, "7");
      await u.click(within(dialog).getByRole("button", { name: "Merge" }));
      await waitFor(() => expect(api).toHaveBeenCalledWith("/api/trips/1/merge", { method: "POST", body: { merge: 7 } }));
    });

    it("asks before merging among different people, then merges anyway", async () => {
      const answer = vi.mocked(api).getMockImplementation()!;
      vi.mocked(api).mockImplementation(async (path, opts) => {
        if (path === "/api/trips/1/merge" && !(opts?.body as { confirm?: boolean }).confirm) {
          throw Object.assign(new Error("Merging these trips changes who sees what."), { status: 409, data: { see_booking: [{ id: 3, name: "Mia Doe" }], see_trip: [{ id: 2, name: "Sam Doe" }] } });
        }
        if (path === "/api/trips" && !opts) return { trips: [held, march] } as never;
        if (path === "/api/trips/1/merge") return { ...held, segments: [...held.segments, ...march.segments] } as never;
        return answer(path, opts) as never;
      });
      render(TripPage);
      const u = userEvent.setup();
      await tripOptions(u, "Merge another trip");
      let dialog = await screen.findByRole("dialog");
      const choose = await within(dialog).findByRole("combobox", { name: "Trip to merge in" });
      await waitFor(() => expect(within(choose).getByRole("option", { name: /Spring trip/ })).toBeInTheDocument());
      await u.selectOptions(choose, "7");
      await u.click(within(dialog).getByRole("button", { name: "Merge" }));
      dialog = await screen.findByRole("dialog", { name: "Merge them anyway?" });
      expect(dialog).toHaveTextContent("Will newly see this trip’s bookings: Mia Doe");
      expect(dialog).toHaveTextContent("Will newly see the other trip’s bookings: Sam Doe");
      expect(api).not.toHaveBeenCalledWith("/api/trips/1/merge", { method: "POST", body: { merge: 7, confirm: true } });
      await u.click(within(dialog).getByRole("button", { name: "Merge anyway" }));
      await waitFor(() => expect(api).toHaveBeenCalledWith("/api/trips/1/merge", { method: "POST", body: { merge: 7, confirm: true } }));
    });

    it("lists the trips to merge newest first, undated ones last", async () => {
      const answer = vi.mocked(api).getMockImplementation()!;
      const named = (id: number, name: string, start_date: string | null) => ({ ...march, id, name, start_date, end_date: start_date });
      vi.mocked(api).mockImplementation(async (path, opts) => {
        if (path === "/api/trips" && !opts) return { trips: [named(2, "Oldest", "2024-01-05"), named(3, "Undated", null), named(4, "Newest", "2026-09-01"), named(5, "Middle", "2025-06-10")] } as never;
        return answer(path, opts) as never;
      });
      render(TripPage);
      const u = userEvent.setup();
      await tripOptions(u, "Merge another trip");
      const choose = await within(await screen.findByRole("dialog")).findByRole("combobox", { name: "Trip to merge in" });
      await waitFor(() => expect(within(choose).getAllByRole("option")).toHaveLength(5));
      const names = within(choose).getAllByRole("option").slice(1).map((o) => o.textContent?.split(" · ")[0]);
      expect(names).toEqual(["Newest", "Middle", "Oldest", "Undated"]);
    });

    it("offers a new trip of its own only when the trip has other bookings", async () => {
      held = trip([flight]);
      withOthers();
      render(TripPage);
      const u = userEvent.setup();
      await bookingOptions(u, /^Move /);
      const choose = within(await screen.findByRole("dialog")).getByRole("combobox", { name: "Move it to" });
      await waitFor(() => expect(within(choose).getByRole("option", { name: /Spring trip/ })).toBeInTheDocument());
      expect(within(choose).queryByRole("option", { name: "A new trip of its own" })).toBeNull();
    });

    it("moves a booking into another trip, or into a new one of its own", async () => {
      withOthers();
      render(TripPage);
      const u = userEvent.setup();
      await bookingOptions(u, "Move Harbour Hotel");
      let dialog = await screen.findByRole("dialog");
      const choose = within(dialog).getByRole("combobox", { name: "Move it to" });
      expect(within(dialog).getByRole("button", { name: "Move" })).toBeDisabled();
      await waitFor(() => expect(within(choose).getByRole("option", { name: /Spring trip/ })).toBeInTheDocument());
      await u.selectOptions(choose, "7");
      await u.click(within(dialog).getByRole("button", { name: "Move" }));
      await waitFor(() => expect(api).toHaveBeenCalledWith("/api/segments/2/move", { method: "POST", body: { trip_id: 7 } }));
      expect(location.hash).toBe("#trip/7");
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      await waitFor(() => expect(getComputedStyle(document.body).pointerEvents).not.toBe("none"));
      await bookingOptions(u, "Move Harbour Hotel");
      dialog = await screen.findByRole("dialog");
      await u.selectOptions(within(dialog).getByRole("combobox", { name: "Move it to" }), "new");
      await u.click(within(dialog).getByRole("button", { name: "Move" }));
      await waitFor(() => expect(api).toHaveBeenCalledWith("/api/segments/2/move", { method: "POST", body: { trip_id: null } }));
    });

    it("lists the other trips newest first, without the one it is in", async () => {
      const older = trip([segment({ id: 10 })], { id: 5, name: "Older trip", start_date: "2026-01-10" });
      const sameDay = trip([segment({ id: 11 })], { id: 8, name: "Same day, later id", start_date: "2026-03-01" });
      const newest = trip([segment({ id: 12 })], { id: 3, name: "Newest trip", start_date: "2026-12-01" });
      const answer = vi.mocked(api).getMockImplementation()!;
      vi.mocked(api).mockImplementation(async (path, opts) => {
        if (path === "/api/trips" && !opts) return { trips: [older, held, march, newest, sameDay] } as never;
        return answer(path, opts) as never;
      });
      render(TripPage);
      const u = userEvent.setup();
      await bookingOptions(u, "Move Harbour Hotel");
      const choose = within(await screen.findByRole("dialog")).getByRole("combobox", { name: "Move it to" });
      await waitFor(() => expect(within(choose).getByRole("option", { name: /Newest trip/ })).toBeInTheDocument());
      const names = within(choose).getAllByRole("option").map((o) => o.textContent ?? "");
      expect(names.filter((n) => n.includes(" · ")).map((n) => n.split(" · ")[0])).toEqual(["Newest trip", "Same day, later id", "Spring trip", "Older trip"]);
      expect(names.some((n) => n.startsWith(held.name))).toBe(false);
    });

    it("asks before moving among different people, then moves anyway", async () => {
      const answer = vi.mocked(api).getMockImplementation()!;
      vi.mocked(api).mockImplementation(async (path, opts) => {
        if (path.endsWith("/move") && !(opts?.body as { confirm?: boolean }).confirm) {
          throw Object.assign(new Error("Moving this changes who sees what."), { status: 409, data: { see_booking: [{ id: 2, name: "Sam Doe" }], see_trip: [{ id: 3, name: "Mia Doe" }] } });
        }
        if (path === "/api/trips" && !opts) return { trips: [held, march] } as never;
        if (path.endsWith("/move")) return march as never;
        return answer(path, opts) as never;
      });
      render(TripPage);
      const u = userEvent.setup();
      await bookingOptions(u, "Move Harbour Hotel");
      let dialog = await screen.findByRole("dialog");
      const choose = within(dialog).getByRole("combobox", { name: "Move it to" });
      await waitFor(() => expect(within(choose).getByRole("option", { name: /Spring trip/ })).toBeInTheDocument());
      await u.selectOptions(choose, "7");
      await u.click(within(dialog).getByRole("button", { name: "Move" }));
      dialog = await screen.findByRole("dialog", { name: "Move it anyway?" });
      expect(dialog).toHaveTextContent("Will newly see this booking: Sam Doe");
      expect(dialog).toHaveTextContent("Will newly see that trip: Mia Doe");
      expect(location.hash).not.toBe("#trip/7");
      await u.click(within(dialog).getByRole("button", { name: "Move anyway" }));
      await waitFor(() => expect(api).toHaveBeenCalledWith("/api/segments/2/move", { method: "POST", body: { trip_id: 7, confirm: true } }));
      expect(location.hash).toBe("#trip/7");
    });
  });

  it("opens the email a booking was made from, in place, and closes it again", async () => {
    held = trip([segment({ ...flight, has_email: true }), stay]);
    const answer = vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation(async (path, opts) => (path === "/api/segments/1/emails" ? { emails: [
      { subject: "Your itinerary: EX 410", sender_domain: "example-air.example", received: "2026-10-17", text: "Gate B12", html: "<p>Gate <b>B12</b></p>", truncated: false, original: true, images: 0 }] }
      : answer(path, opts)) as never);
    render(TripPage);
    await screen.findByRole("list", { name: "Bookings" });
    expect(screen.getAllByRole("button", { name: /email for/ })).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: /View email for/ }));
    const region = await screen.findByRole("region", { name: /The email for/ });
    expect(await within(region).findByTestId("message-subject")).toHaveTextContent("Your itinerary: EX 410");
    expect(region).toHaveTextContent("example-air.example · sent 2026-10-17");
    expect(within(region).getByTestId("preview-html").shadowRoot?.innerHTML).toContain("<b>B12</b>");
    expect(vi.mocked(api)).toHaveBeenCalledWith("/api/segments/1/emails");
    await userEvent.click(screen.getByRole("button", { name: /Hide email for/ }));
    expect(screen.queryByRole("region", { name: /The email for/ })).toBeNull();
  });

  it("says why an email couldn’t be opened, and when it is no longer kept", async () => {
    held = trip([segment({ ...flight, has_email: true }), stay]);
    const answer = vi.mocked(api).getMockImplementation()!;
    let emails: unknown = new Error("Waypoint is busy.");
    vi.mocked(api).mockImplementation(async (path, opts) => { if (path === "/api/segments/1/emails") { if (emails instanceof Error) throw emails; return emails as never; } return answer(path, opts) as never; });
    render(TripPage);
    await userEvent.click(await screen.findByRole("button", { name: /View email for/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Waypoint is busy.");
    await userEvent.click(screen.getByRole("button", { name: /Hide email for/ }));
    emails = { emails: [] };
    await userEvent.click(screen.getByRole("button", { name: /View email for/ }));
    expect(await screen.findByText("This email isn’t kept any more.")).toBeInTheDocument();
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

  it("shows an untimed hotel’s end day beside time not recorded, and a past trip’s dates with their year and no time not recorded", async () => {
    held = trip([
      segment({ id: 1, kind: "hotel", origin: "Harbour Hotel", destination: null, start_local: "2026-03-08T00:00", end_local: "2026-03-10T00:00", details: { time_unknown: "yes" } }),
      segment({ id: 2, kind: "visit", provider: null, origin: null, destination: "JP", start_local: "2005-03-10T00:00", end_local: "2005-03-29T00:00", details: { time_unknown: "yes" } }),
    ]);
    render(TripPage);
    const cards = within(await screen.findByRole("list", { name: "Bookings" })).getAllByRole("listitem").filter((li) => li.classList.contains("pass"));
    expect(cards[0]).toHaveTextContent(/Check-out\s*Tue, Mar 10, time not recorded/);
    expect(cards[1]).toHaveTextContent(/From\s*Thu, Mar 10, 2005\s*To\s*Tue, Mar 29, 2005/);
    expect(cards[1]).not.toHaveTextContent("time not recorded");
    expect(cards[1]).not.toHaveTextContent("Time not recorded");
  });

  it("offers each booking’s actions, and no Wallet", async () => {
    render(TripPage);
    await screen.findByRole("heading", { name: "Trip to London" });
    const hotel = within(screen.getByRole("group", { name: /Actions for Harbour Hotel/ }));
    expect(hotel.getByRole("link", { name: "Directions" })).toHaveAttribute("href", "https://www.google.com/maps/search/?api=1&query=1%20Quay%20Street%2C%20London");
    expect(hotel.getByRole("link", { name: "Call" })).toHaveAttribute("href", "tel:+442079460000");
    expect(hotel.queryByRole("link", { name: "Manage booking" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Wallet" })).toBeNull();
  });

  it("offers a phone the vendor's app or website on a booking with no manage link, in the actions row and without a new tab", async () => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)");
    held = trip([{ ...stay, links: { app: null, open: "https://www.example-vendor.example/", open_kind: "website", directions: null, call: null } }]);
    render(TripPage);
    await screen.findByRole("heading", { name: "Trip to London" });
    const site = screen.getAllByRole("link", { name: "Open website" });
    expect(site.length).toBeGreaterThan(0);
    for (const link of site) {
      expect(link).toHaveAttribute("href", "https://www.example-vendor.example/");
      expect(link).not.toHaveAttribute("target");
    }
    expect(screen.queryByRole("link", { name: "Open in app" })).toBeNull();
  });

  it("offers a computer no vendor link", async () => {
    held = trip([{ ...stay, links: { app: null, open: "https://www.example-vendor.example/", open_kind: "app", directions: null, call: null } }]);
    render(TripPage);
    await screen.findByRole("heading", { name: "Trip to London" });
    expect(screen.queryByRole("link", { name: /Open website|Open in app/ })).toBeNull();
  });

  it("offers the provider's app, and no Wallet, on iOS", async () => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)");
    render(TripPage);
    await screen.findByRole("heading", { name: "Trip to London" });
    expect(screen.queryByRole("link", { name: "Wallet" })).toBeNull();
    expect(screen.getAllByRole("link", { name: "Open in app" })[0]).toHaveAttribute("href", "https://example.com/manage");
  });

  it("keeps a cancelled booking’s manage link and drops its other actions", async () => {
    held = trip([{ ...stay, status: "cancelled", links: { app: "https://example.com/manage", open: null, open_kind: null, directions: "https://www.google.com/maps/search/?api=1&query=x", call: "tel:+442079460000" } }]);
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
    expect(first.queryByText("Edited by you")).toBeNull();
    expect(first.getByRole("link", { name: "Manage booking" })).toHaveAttribute("href", "https://example.com/manage");
    expect(first.queryByRole("button", { name: /American AAdvantage number/ })).toBeNull();
    expect(first.queryByText(/American AAdvantage/)).toBeNull();
    expect(first.queryByText(/••••4567/)).toBeNull();
    expect(first.queryByText(/number yet/)).toBeNull();
    expect(first.getByRole("button", { name: "Copy confirmation code KQ7M2X" })).toBeInTheDocument();
    expect(first.getByText(/Not matched to a person/)).toBeInTheDocument();
    const hotel = within(cards[1]);
    expect(hotel.getByText("Changed")).toBeInTheDocument();
    expect(hotel.getByRole("button", { name: /^Show and copy Marriott Bonvoy number/ })).toHaveTextContent("••••8899");
  });

  it("reveals a number only when asked, copies it, and hides it again", async () => {
    render(TripPage);
    const u = userEvent.setup();
    const button = await screen.findByRole("button", { name: /^Show and copy Marriott Bonvoy number/ });
    expect(api).not.toHaveBeenCalledWith(expect.stringContaining("/reveal"), expect.anything());
    await u.click(button);
    expect(await screen.findByRole("button", { name: /^Hide Marriott Bonvoy number/ })).toHaveTextContent("DEMO1234567");
    expect(await navigator.clipboard.readText()).toBe("DEMO1234567");
    await u.click(screen.getByRole("button", { name: /^Hide Marriott Bonvoy number/ }));
    expect(screen.getByRole("button", { name: /^Show and copy Marriott Bonvoy number/ })).toHaveTextContent("••••8899");
  });

  it("says a number can't be read with this key rather than showing nothing", async () => {
    loyalty = [membership({ id: 12, kind: "hotel", program: "Marriott Bonvoy", readable: false, masked: "••••" })];
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
    await bookingOptions(u, "Remove Harbour Hotel");
    vi.mocked(api).mockImplementation(async (path, opts) => {
      if (opts?.method === "DELETE") return { ok: true };
      throw new Error("Waypoint is unreachable");
    });
    await u.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(await screen.findByText("Waypoint is unreachable")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Trip to London" })).toBeNull();
    serve();
    document.body.style.pointerEvents = "";
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
    await u.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/segments/1", { method: "POST", body: expect.objectContaining({
      kind: "flight", origin: "JFK", details: { flight_number: "AA 101", terminal: "7" }, travelers: [{ person_id: 1, seat: null }, { person_id: 2, seat: null }, { person_id: null, name: "DOE/MIA MISS", seat: null }] }) }));
    await waitFor(() => expect(screen.queryByRole("form")).toBeNull());
  });

  it("opens a booking's edit form right under that booking and scrolls to it, not at the top", async () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    render(TripPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Edit Harbour Hotel" }));
    const form = screen.getByRole("listitem", { name: "Edit booking" });
    expect(form.previousElementSibling).toHaveTextContent("Harbour Hotel");
    expect(within(form).getByLabelText("Hotel name")).toBeInTheDocument();
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest", behavior: "smooth" });
    await u.click(within(form).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("listitem", { name: "Edit booking" })).toBeNull();
  });

  it("still opens Add a booking at the top, above the cards", async () => {
    render(TripPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: /Add a booking/ }));
    const bookings = screen.getByRole("list", { name: "Bookings" });
    expect(screen.getByRole("heading", { name: "Trip to London" }).compareDocumentPosition(bookings.previousElementSibling!)).toBeTruthy();
    expect(screen.queryByRole("listitem", { name: "Edit booking" })).toBeNull();
    expect(bookings.previousElementSibling?.tagName).toBe("FORM");
  });

  it("edits the name in the trip’s form, sending only the name, and shows the new name", async () => {
    render(TripPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Edit trip details" }));
    expect(screen.getByLabelText("Name")).toHaveValue("Trip to London");
    await u.clear(screen.getByLabelText("Name"));
    await u.type(screen.getByLabelText("Name"), "  Lisbon in spring ");
    vi.mocked(api).mockImplementation(async (path, opts) => (path === "/api/trips/1" && opts?.method === "POST" ? { ...held, name: (opts.body as { name: string }).name } : held) as never);
    await u.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/trips/1", { method: "POST", body: { name: "Lisbon in spring" } }));
    expect(await screen.findByRole("heading", { name: "Lisbon in spring" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Name")).toBeNull();
  });

  it("hides the trip’s saved notes while its form is open, and shows them again after Cancel", async () => {
    held = trip([flight, stay], { notes: "Pack light for the trip" });
    render(TripPage);
    const u = userEvent.setup();
    expect(await screen.findByText("Pack light for the trip")).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Edit trip details" }));
    expect(screen.getByLabelText("Notes")).toHaveValue("Pack light for the trip");
    expect(screen.queryByText("Pack light for the trip")).toBeNull();
    await u.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByText("Pack light for the trip")).toBeInTheDocument();
  });

  it("edits the destination in the same form, sending only the destination, and shows the new one", async () => {
    render(TripPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Edit trip details" }));
    vi.mocked(api).mockImplementation(async (path, opts) => (path === "/api/trips/1" && opts?.method === "POST"
      ? { ...held, destination: "Colorado & Texas", destination_manual: true } : held) as never);
    await u.type(screen.getByLabelText("Destination"), "Colorado & Texas");
    await u.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/trips/1", { method: "POST", body: { destination: "Colorado & Texas" } }));
    expect(await screen.findByText(/· Colorado & Texas/)).toBeInTheDocument();
  });

  it("won't save an empty trip name, says why when the server refuses, and Cancel keeps the old name", async () => {
    render(TripPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Edit trip details" }));
    await u.clear(screen.getByLabelText("Name"));
    await u.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter a name for the trip");
    expect(vi.mocked(api).mock.calls.some(([, o]) => o?.method === "POST")).toBe(false);
    await u.type(screen.getByLabelText("Name"), "Nope");
    vi.mocked(api).mockImplementation(async (_p, opts) => { if (opts?.method === "POST") throw new Error("The name is too long"); return held; });
    await u.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The name is too long");
    expect(screen.getByLabelText("Name")).toHaveValue("Nope");
    await u.click(screen.getByRole("button", { name: "Cancel" }));
    await u.click(await screen.findByRole("button", { name: "Discard changes" }));
    expect(await screen.findByRole("heading", { name: "Trip to London" })).toBeInTheDocument();
  });

  it("explains a slip in the edit form without sending it, and keeps what was typed", async () => {
    render(TripPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Edit JFK → LHR" }));
    await u.clear(screen.getByLabelText(/From \(airport\)/));
    await u.type(screen.getByLabelText(/From \(airport\)/), "N1");
    await u.type(screen.getByLabelText("Seat of Jane Doe"), "12A");
    await u.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText(/Choose the airport it leaves from/)).toBeInTheDocument();
    expect(api).not.toHaveBeenCalledWith("/api/segments/1", expect.anything());
    expect(screen.getByLabelText("Seat of Jane Doe")).toHaveValue("12A");
  });

  it("keeps what was typed and says why when a save fails", async () => {
    render(TripPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Edit JFK → LHR" }));
    await u.type(screen.getByLabelText("Seat of Jane Doe"), "12A");
    vi.mocked(api).mockImplementation(async (path, opts) => {
      if (opts?.method === "POST") throw new Error("Someone on this isn’t in People");
      return held;
    });
    await u.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Someone on this isn’t in People");
    expect(screen.getByLabelText("Seat of Jane Doe")).toHaveValue("12A");
    expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled();
  });

  it("adds a booking to this trip", async () => {
    render(TripPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: /Add a booking/ }));
    await u.selectOptions(screen.getByLabelText("What is it"), "Hotel");
    await u.type(screen.getByLabelText("Hotel name"), "Harbour Hotel");
    await u.type(screen.getByLabelText(/^Check-in/), "2026-11-21T15:00");
    await u.type(screen.getByLabelText(/^Check-out/), "2026-11-27T10:00");
    await u.click(screen.getByRole("button", { name: "Set the time zone by hand" }));
    await chooseZone(screen.getByLabelText(/^Time zone/), "Europe/London");
    expect(screen.queryByLabelText("Sam Doe")).toBeNull();
    await u.click(screen.getByRole("button", { name: "Add booking" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/segments", { method: "POST", body: expect.objectContaining({
      trip_id: 1, kind: "hotel", origin: "Harbour Hotel", start_zone: "Europe/London" }) }));
    expect(vi.mocked(api).mock.calls.find((c) => c[0] === "/api/segments")?.[1]?.body).not.toHaveProperty("travelers");
  });

  it("doesn't show a stay's time zone on its card", async () => {
    render(TripPage);
    await screen.findByRole("heading", { name: "Trip to London" });
    expect(screen.queryByTestId("stay-zone")).toBeNull();
    expect(screen.queryByText("Time zone")).toBeNull();
    expect(screen.queryAllByText(/Europe\/London|Europe London/).filter((e) => !e.classList.contains("sr-only"))).toEqual([]);
  });

  it("asks a stay for one time zone, and says it can be worked out from the address", async () => {
    render(TripPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: /Add a booking/ }));
    await u.selectOptions(screen.getByLabelText("What is it"), "Hotel");
    expect(screen.queryByLabelText(/Time zone at the end/)).toBeNull();
    expect(screen.queryByText(/Leave this empty to work it out from the address/)).toBeNull();
    await u.selectOptions(screen.getByLabelText("What is it"), "Car rental");
    await u.click(screen.getByRole("button", { name: "Set the time zone by hand" }));
    expect(screen.getByLabelText(/Time zone at the end/)).toBeInTheDocument();
  });

  it("adds a parking booking with its lot, entry, exit and details to this trip", async () => {
    render(TripPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: /Add a booking/ }));
    await u.selectOptions(screen.getByLabelText("What is it"), "Parking");
    expect(screen.queryByLabelText(/Time zone at the end/)).toBeNull();
    expect(screen.queryByText(/Entry and exit are both at the lot/)).toBeNull();
    await u.type(screen.getByLabelText("Lot name"), "Example Long-Term Lot");
    await u.type(screen.getByLabelText(/^Entry/), "2026-11-20T16:00");
    await u.type(screen.getByLabelText(/^Exit/), "2026-11-27T21:00");
    await u.click(screen.getByRole("button", { name: "Set the time zone by hand" }));
    await chooseZone(screen.getByLabelText(/^Time zone/), "America/New_York");
    await u.type(screen.getByLabelText("Space type (covered, economy, valet)"), "Covered");
    await u.type(screen.getByLabelText("Vehicle (make and colour)"), "Blue hatchback");
    expect(screen.queryByLabelText("Sam Doe")).toBeNull();
    await u.click(screen.getByRole("button", { name: "Add booking" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/segments", { method: "POST", body: expect.objectContaining({
      trip_id: 1, kind: "parking", origin: "Example Long-Term Lot", start_zone: "America/New_York", details: { space_type: "Covered", vehicle: "Blue hatchback" } }) }));
    expect(vi.mocked(api).mock.calls.find((c) => c[0] === "/api/segments")?.[1]?.body).not.toHaveProperty("travelers");
  });

  describe("a parking booking", () => {
    const lot = segment({ id: 6, kind: "parking", provider: "Example Parking", origin: "Example Long-Term Lot", destination: null, start_zone: "America/New_York", end_zone: "America/New_York",
      start_local: "2026-11-20T16:00", end_local: "2026-11-27T21:00", confirmation: "PK1234", details: { space_type: "Covered", address: "1 Terminal Road\nJamaica, NY", vehicle: "Blue hatchback" },
      links: { app: null, open: null, open_kind: null, directions: "https://www.google.com/maps/search/?api=1&query=1%20Terminal%20Road%20Jamaica%2C%20NY", call: null } });

    it("leads with the lot, shows Entry and Exit at the lot’s times, its address, details and a Directions button", async () => {
      held = trip([lot]);
      render(TripPage);
      const card = (await screen.findByRole("heading", { name: "Example Long-Term Lot" })).closest(".pass") as HTMLElement;
      expect(within(card).getByText("Entry")).toBeInTheDocument();
      expect(within(card).getByText("Exit")).toBeInTheDocument();
      expect(within(card).getByText("4:00 PM")).toBeInTheDocument();
      expect(within(card).getByText("9:00 PM")).toBeInTheDocument();
      expect(within(card).getByText("Covered")).toBeInTheDocument();
      expect(within(card).getByText("Blue hatchback")).toBeInTheDocument();
      expect(screen.getByText("Address")).toBeInTheDocument();
      expect(screen.queryByTestId("stay-zone")).toBeNull();
      expect(screen.getByRole("link", { name: "Directions" })).toHaveAttribute("href", lot.links.directions!);
    });

    it("edits the lot and keeps the details it does not show", async () => {
      held = trip([{ ...lot, details: { ...lot.details, time_unknown: "no" } }]);
      const u = userEvent.setup();
      render(TripPage);
      await u.click(await screen.findByRole("button", { name: "Edit Example Long-Term Lot" }));
      expect(screen.getByLabelText("Lot name")).toHaveValue("Example Long-Term Lot");
      expect(screen.getByLabelText("Space type (covered, economy, valet)")).toHaveValue("Covered");
      await u.clear(screen.getByLabelText("Space type (covered, economy, valet)"));
      await u.type(screen.getByLabelText("Space type (covered, economy, valet)"), "Valet");
      await u.click(screen.getByRole("button", { name: "Save changes" }));
      await waitFor(() => expect(api).toHaveBeenCalledWith("/api/segments/6", { method: "POST", body: expect.objectContaining({
        kind: "parking", origin: "Example Long-Term Lot", start_zone: "America/New_York", details: expect.objectContaining({ space_type: "Valet", vehicle: "Blue hatchback" }) }) }));
    });

    it("offers adding an address when there is none", async () => {
      held = trip([{ ...lot, details: {}, links: { ...lot.links, directions: null } }]);
      render(TripPage);
      expect(await screen.findByRole("button", { name: "Add address to Example Long-Term Lot" })).toBeInTheDocument();
    });
  });

  it("removes a booking after asking", async () => {
    render(TripPage);
    const u = userEvent.setup();
    await bookingOptions(u, "Remove Harbour Hotel");
    await u.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/segments/2", { method: "DELETE" }));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Harbour Hotel" })).toBeNull());
  });

  describe("a flight on two bookings", () => {
    const sams = segment({ id: 5, confirmation: "BBBBBB", details: { flight_number: "AA0101" }, manage_url: "https://example.com/manage/b",
      links: { app: "https://example.com/manage/b", open: null, open_kind: null, directions: null, call: null }, travelers: [{ id: 9, person_id: 2, name: "Sam Doe", seat: null }] });
    beforeEach(() => { held = trip([flight, sams, stay]); });

    it("is one card for the flight with a block for each booking: its code, its travellers, its own Edit and Remove", async () => {
      render(TripPage);
      const list = await screen.findByRole("list", { name: "Bookings" });
      const cards = within(list).getAllByRole("listitem").filter((li) => li.classList.contains("pass"));
      expect(cards).toHaveLength(2);
      expect(within(cards[0]).getAllByRole("heading", { name: "JFK → LHR" })).toHaveLength(1);
      const blocks = within(cards[0]).getAllByRole("listitem").filter((li) => li.hasAttribute("data-booking"));
      expect(blocks).toHaveLength(2);
      expect(within(blocks[0]).getByRole("button", { name: "Copy confirmation code KQ7M2X" })).toBeInTheDocument();
      expect(within(blocks[0]).getByText("Jane Doe")).toBeInTheDocument();
      expect(within(blocks[0]).queryByText("Sam Doe")).toBeInTheDocument();
      expect(within(blocks[1]).getByRole("button", { name: "Copy confirmation code BBBBBB" })).toBeInTheDocument();
      expect(within(blocks[1]).getByText("Sam Doe")).toBeInTheDocument();
      expect(within(blocks[1]).queryByText("Jane Doe")).toBeNull();
      expect(within(blocks[1]).getByRole("link", { name: /Manage booking|Open in app/ })).toHaveAttribute("href", "https://example.com/manage/b");
      expect(within(blocks[0]).getByRole("button", { name: "Edit JFK → LHR booking KQ7M2X" })).toBeInTheDocument();
      expect(within(blocks[1]).getByRole("button", { name: "Edit JFK → LHR booking BBBBBB" })).toBeInTheDocument();
      expect(within(cards[0]).queryByText("Times differ between bookings")).toBeNull();
      expect(within(cards[0]).getAllByText("Departs")).toHaveLength(1);
    });

    it("removes the one booking whose Remove was pressed, and keeps the flight", async () => {
      render(TripPage);
      const u = userEvent.setup();
      await bookingOptions(u, "Remove JFK → LHR booking BBBBBB");
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
      expect(within(card).getAllByText("Departs")).toHaveLength(2);
    });
  });

  describe("a seat for each traveller", () => {
    it("shows each traveller's seat beside their name, and nothing for one without", async () => {
      held = trip([{ ...flight, travelers: [{ id: 1, person_id: 1, name: "Jane Doe", seat: "31A" }, { id: 2, person_id: 2, name: "Sam Doe", seat: "31B" }, { id: 3, person_id: null, name: "DOE/MIA MISS", seat: null }] }]);
      render(TripPage);
      await screen.findByRole("heading", { name: "Trip to London" });
      const who = within(screen.getByRole("heading", { name: "Travellers" }).parentElement!);
      expect(who.getByText("Jane Doe").closest("li")).toHaveTextContent("Jane Doe · Seat 31A");
      expect(who.getByText("Sam Doe").closest("li")).toHaveTextContent("Sam Doe · Seat 31B");
      expect(who.getByText("DOE/MIA MISS").closest("li")).not.toHaveTextContent("Seat");
    });

    it("has a seat field for each ticked traveller, and sends them", async () => {
      const u = userEvent.setup();
      render(TripPage);
      await u.click(await screen.findByRole("button", { name: "Edit JFK → LHR" }));
      expect(screen.queryAllByLabelText("Seat").map((e) => e.getAttribute("aria-label"))).toEqual(["Seat of Jane Doe", "Seat of Sam Doe", "Seat of DOE/MIA MISS"]);
      await u.type(screen.getByLabelText("Seat of Jane Doe"), "31A");
      await u.type(screen.getByLabelText("Seat of Sam Doe"), " 31B ");
      await u.type(screen.getByLabelText("Seat of DOE/MIA MISS"), "32A");
      await u.click(screen.getByRole("checkbox", { name: "Sam Doe" }));
      expect(screen.queryByLabelText("Seat of Sam Doe")).toBeNull();
      await u.click(screen.getByRole("button", { name: "Save changes" }));
      await waitFor(() => expect(api).toHaveBeenCalledWith("/api/segments/1", { method: "POST", body: expect.objectContaining({
        travelers: [{ person_id: 1, seat: "31A" }, { person_id: null, name: "DOE/MIA MISS", seat: "32A" }] }) }));
    });

    it("moves a seat entered on the booking onto its one traveller", async () => {
      held = trip([{ ...flight, details: { flight_number: "AA 101", seat: "14C" }, travelers: [{ id: 1, person_id: 1, name: "Jane Doe", seat: null }] }]);
      const u = userEvent.setup();
      render(TripPage);
      await u.click(await screen.findByRole("button", { name: "Edit JFK → LHR" }));
      expect(screen.getByLabelText("Seat of Jane Doe")).toHaveValue("14C");
      await u.click(screen.getByRole("button", { name: "Save changes" }));
      await waitFor(() => expect(api).toHaveBeenCalledWith("/api/segments/1", { method: "POST", body: expect.objectContaining({
        details: { flight_number: "AA 101" }, travelers: [{ person_id: 1, seat: "14C" }] }) }));
    });

    it("gives a hotel guest no seat field", async () => {
      held = trip([stay]);
      const u = userEvent.setup();
      render(TripPage);
      await u.click(await screen.findByRole("button", { name: "Edit Harbour Hotel" }));
      expect(screen.queryByLabelText(/^Seat/)).toBeNull();
    });
  });

  it("says nothing about travellers or missing numbers on a hotel with no loyalty number to show", async () => {
    loyalty = [];
    held = trip([{ ...stay, booked_by: 1, travelers: [{ id: 4, person_id: 1, name: "Jane Doe", seat: null }, { id: 5, person_id: 2, name: "Sam Doe", seat: null }, { id: 6, person_id: null, name: "DOE/MIA MISS", seat: null }] }]);
    render(TripPage);
    await screen.findByRole("heading", { name: "Trip to London" });
    expect(screen.queryByText(/number yet/)).toBeNull();
    expect(screen.queryByText(/Not matched to a person/)).toBeNull();
    expect(screen.queryByText("Sam Doe")).toBeNull();
  });

  describe("a link to one booking", () => {
    it("scrolls to that booking’s card and marks it, and leaves the others alone", async () => {
      const scroll = vi.fn();
      Element.prototype.scrollIntoView = scroll;
      route.query = "segment=2";
      render(TripPage);
      const cards = within(await screen.findByRole("list", { name: "Bookings" })).getAllByRole("listitem").filter((li) => li.classList.contains("pass"));
      expect(cards.map((c) => c.id)).toEqual(["segment-1", "segment-2"]);
      await waitFor(() => expect(scroll).toHaveBeenCalledTimes(1));
      expect(scroll.mock.contexts[0]).toBe(cards[1]);
      expect(cards[1]).toHaveClass("ring-2");
      expect(cards[0]).not.toHaveClass("ring-2");
    });

    it("does nothing for a booking that isn’t on the trip, or without a link to one", async () => {
      const scroll = vi.fn();
      Element.prototype.scrollIntoView = scroll;
      route.query = "segment=99";
      const { unmount } = render(TripPage);
      await screen.findByRole("heading", { name: "Trip to London" });
      route.query = "";
      unmount();
      render(TripPage);
      await screen.findByRole("heading", { name: "Trip to London" });
      expect(scroll).not.toHaveBeenCalled();
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

    it("shows no address line for a rental whose address is its pick-up, and never offers Add address for it", async () => {
      const car = segment({ id: 5, kind: "car", provider: "Local Cars", origin: "Example Rental", destination: "Example Rental", confirmation: "C9", start_local: "2026-11-22T09:00",
        start_zone: "Europe/London", end_local: "2026-11-25T09:00", end_zone: "Europe/London", details: { address: "Example Rental" } });
      held = trip([flight, car]);
      render(TripPage);
      await screen.findByRole("heading", { name: "Trip to London" });
      expect(screen.queryByText("Pick-up address")).toBeNull();
      expect(screen.queryByRole("button", { name: /Add address/ })).toBeNull();
    });

    it("shows a rental's address line when it differs from its pick-up", async () => {
      const car = segment({ id: 5, kind: "car", provider: "Local Cars", origin: "Example Rental", destination: "Example Rental", confirmation: "C9", start_local: "2026-11-22T09:00",
        start_zone: "Europe/London", end_local: "2026-11-25T09:00", end_zone: "Europe/London", details: { address: "1 Rental Way, Bristol BS48 3DY" } });
      held = trip([flight, car]);
      render(TripPage);
      expect((await screen.findAllByText("Pick-up address")).length).toBeGreaterThan(0);
      expect(screen.getByRole("button", { name: /Copy address 1 Rental Way/ })).toBeInTheDocument();
    });

    it("offers Add address only when there is none, and opens the form at the address field", async () => {
      held = trip([flight, { ...stay, details: {}, links: { app: null, open: null, open_kind: null, directions: "https://www.google.com/maps/search/?api=1&query=Harbour%20Hotel", call: null } }]);
      const u = userEvent.setup();
      render(TripPage);
      await screen.findByRole("heading", { name: "Trip to London" });
      expect(screen.getAllByRole("button", { name: /Add address/ })).toHaveLength(1);
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
      await u.click(screen.getByRole("button", { name: "Save changes" }));
      const post = vi.mocked(api).mock.calls.find(([path, o]) => path === "/api/segments/2" && o?.method === "POST")!;
      expect((post[1] as { body: { details: Record<string, string> } }).body.details.address).toBe("7 Mill Lane\nLondon N1 1AA");
    });
  });

  describe("View email on the row of action buttons", () => {
    const emailed = { emails: [{ subject: "Your stay", sender_domain: "example-hotel.example", received: "2026-11-01", text: "Check in at 3", html: null, truncated: false }] };

    it("puts View email in the same row as Directions and Call, after them", async () => {
      held = trip([{ ...stay, has_email: true }]);
      render(TripPage);
      const group = await screen.findByRole("group", { name: /Actions for Harbour Hotel/ });
      expect(group).toHaveClass("flex", "flex-wrap");
      expect(Array.from(group.querySelectorAll("a, button"), (el) => el.textContent?.trim())).toEqual(["Directions", "Call", "View email"]);
      expect(within(group).getByRole("button", { name: "View email for Harbour Hotel" })).toHaveAttribute("aria-expanded", "false");
    });

    it("renders View email on its own when the booking has no action links", async () => {
      held = trip([{ ...stay, has_email: true, links: { app: null, open: null, open_kind: null, directions: null, call: null } }]);
      render(TripPage);
      const button = await screen.findByRole("button", { name: "View email for Harbour Hotel" });
      expect(button).toHaveTextContent("View email");
      expect(button).toHaveAttribute("aria-expanded", "false");
      expect(screen.queryByRole("link", { name: "Directions" })).toBeNull();
    });

    it("opens the email below the whole row of buttons, and the buttons stay where they are", async () => {
      held = trip([{ ...stay, has_email: true }]);
      const answer = vi.mocked(api).getMockImplementation()!;
      vi.mocked(api).mockImplementation(async (path, opts) => (path === "/api/segments/2/emails" ? emailed : answer(path, opts)) as never);
      render(TripPage);
      const group = await screen.findByRole("group", { name: /Actions for Harbour Hotel/ });
      await userEvent.click(within(group).getByRole("button", { name: "View email for Harbour Hotel" }));
      const region = await screen.findByRole("region", { name: "The email for Harbour Hotel" });
      expect(group.contains(region)).toBe(false);
      expect(group.compareDocumentPosition(region) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(within(region).getByTestId("message-subject")).toHaveTextContent("Your stay");
      expect(within(group).getByRole("link", { name: "Directions" })).toHaveAttribute("href", stay.links.directions!);
      expect(within(group).getByRole("link", { name: "Call" })).toHaveAttribute("href", stay.links.call!);
      expect(within(group).getByRole("button", { name: "Hide email for Harbour Hotel" })).toHaveAttribute("aria-expanded", "true");
    });
  });

  describe("a cruise", () => {
    const ship = segment({ id: 5, kind: "cruise", provider: "Example Cruise Line", origin: "Miami", destination: "Miami", start_zone: "America/New_York", end_zone: "America/New_York",
      start_local: "2026-03-01T16:30", end_local: "2026-03-08T07:00", confirmation: "CR48210", details: { ship: "Example Voyager", room: "9214", address: "1 Port Boulevard\nMiami" },
      links: { app: null, open: null, open_kind: null, directions: "https://www.google.com/maps/search/?api=1&query=1%20Port%20Boulevard%20Miami", call: null },
      itinerary: [{ name: "Nassau", zone: "America/Nassau", arrive_local: "2026-03-02T08:00", depart_local: "2026-03-02T17:00" },
                  { name: "Cozumel", zone: "America/Cancun", arrive_local: null, depart_local: null }],
      days: [
        { day: 1, date: "2026-03-01", sea: false, stops: [{ name: "Miami", zone: "America/New_York", arrive_local: null, depart_local: "2026-03-01T16:30", recorded: true }] },
        { day: 2, date: "2026-03-02", sea: false, stops: [{ name: "Nassau", zone: "America/Nassau", arrive_local: "2026-03-02T08:00", depart_local: "2026-03-02T17:00", recorded: true }] },
        { day: 3, date: "2026-03-03", sea: true, stops: [] },
        { day: 4, date: "2026-03-04", sea: false, stops: [{ name: "Cozumel", zone: "America/Cancun", arrive_local: null, depart_local: null, recorded: false }] },
        { day: 5, date: "2026-03-05", sea: false, stops: [{ name: "Miami", zone: "America/New_York", arrive_local: "2026-03-05T07:00", depart_local: null, recorded: true }] }] });

    it("lists its ports of call with their local times, its terminal address, and Directions to it", async () => {
      held = trip([ship], { end_date: "2999-01-01" });
      render(TripPage);
      const days = (await screen.findByText("Itinerary")).closest("[data-itinerary]") as HTMLElement;
      const rows = within(days).getAllByRole("listitem");
      expect(rows).toHaveLength(5);
      expect(rows[0]).toHaveTextContent(/Day 1 · Sun, Mar 1\s*Miami\s*leaves .*4:30 PM/);
      expect(rows[1]).toHaveTextContent(/Day 2 · Mon, Mar 2\s*Nassau\s*arrives .*8:00 AM.*leaves .*5:00 PM/);
      expect(rows[2]).toHaveTextContent(/Day 3 · Tue, Mar 3\s*Sea day$/);
      expect(rows[3]).toHaveTextContent(/Day 4 · Wed, Mar 4\s*Cozumel\s*Time not recorded/);
      expect(rows[4]).toHaveTextContent(/Day 5 · Thu, Mar 5\s*Miami\s*arrives .*7:00 AM/);
      expect(screen.getByText("Terminal address")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Directions" })).toHaveAttribute("href", ship.links.directions!);
      expect(screen.getByText("Embarks")).toBeInTheDocument();
    });

    it("shows the traveller's cruise-line membership number masked on the cruise card", async () => {
      loyalty = [membership({ id: 31, person_id: 1, kind: "cruise", program: "Disney Castaway Club", masked: "••••0042" })];
      held = trip([{ ...ship, provider: "Disney Cruise Line", travelers: [{ id: 4, person_id: 1, name: "Jane Doe", seat: null }] }], { end_date: "2999-01-01" });
      render(TripPage);
      await screen.findByRole("heading", { name: "Example Voyager · Miami" });
      const line = document.querySelector("[data-membership]")!;
      expect(line).toHaveTextContent("Disney Castaway Club");
      expect(line).toHaveTextContent("••••0042");
      expect(within(line as HTMLElement).getByRole("button", { name: /Show/ })).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Travellers" })).toBeInTheDocument();
    });

    it("shows no membership on a cruise from a line with no program saved for the traveller", async () => {
      loyalty = [membership({ id: 31, person_id: 1, kind: "cruise", program: "Disney Castaway Club", masked: "••••0042" })];
      held = trip([{ ...ship, provider: "Carnival Cruise Line", travelers: [{ id: 4, person_id: 1, name: "Jane Doe", seat: null }] }], { end_date: "2999-01-01" });
      render(TripPage);
      await screen.findByRole("heading", { name: "Example Voyager · Miami" });
      expect(document.querySelector("[data-membership]")).toBeNull();
    });

    it("shows no ports section for a cruise without any", async () => {
      held = trip([{ ...ship, itinerary: [], days: [] }]);
      render(TripPage);
      await screen.findByRole("heading", { name: "Example Voyager · Miami" });
      expect(screen.queryByText("Itinerary")).toBeNull();
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
      await u.click(screen.getByRole("button", { name: "Save changes" }));
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
      await u.click(screen.getByRole("button", { name: "Save changes" }));
      expect(await screen.findByText(/Name port 1/)).toBeInTheDocument();
      expect(vi.mocked(api).mock.calls.some(([, o]) => o?.method === "POST")).toBe(false);
      await u.click(screen.getByRole("button", { name: "Cancel" }));
      await u.click(await screen.findByRole("button", { name: "Discard changes" }));
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      document.body.style.pointerEvents = "";
      await u.click(screen.getByRole("button", { name: "Edit JFK → LHR" }));
      expect(screen.queryByText("Ports of call", { selector: "legend" })).toBeNull();
    });
  });

  describe("a trip that is over", () => {
    const hotel = { ...stay, status: "confirmed" as const, has_email: true, start_local: "2020-03-01T15:00", end_local: "2020-03-04T10:00", travelers: [{ id: 4, person_id: 1, name: "Jane Doe", seat: null }] };
    const cardOf = async (s: ReturnType<typeof segment>) => (await screen.findByRole("list", { name: "Bookings" })).querySelector(`#segment-${s.id}`) as HTMLElement;
    const past = (extra: Partial<TripT> = {}) => trip([hotel], { start_date: "2020-03-01", end_date: "2020-03-04", ...extra });

    it("keeps the essentials and drops the actions and loyalty numbers", async () => {
      loyalty = [membership({ id: 12, person_id: 1, kind: "hotel", program: "Marriott Bonvoy", masked: "••••821L" })];
      held = past();
      render(TripPage);
      const card = await cardOf(hotel);
      expect(card).toHaveTextContent("H88231");
      expect(card).toHaveTextContent("1 Quay Street, London");
      expect(within(card).queryByRole("link", { name: "Directions" })).toBeNull();
      expect(within(card).queryByRole("link", { name: "Call" })).toBeNull();
      expect(within(card).queryByRole("button", { name: /email/i })).toBeNull();
      expect(card.querySelector("[data-membership]")).toBeNull();
      expect(within(card).getByRole("button", { name: /^Edit/ })).toBeInTheDocument();
    });

    it("keeps Edit, Move and Remove on a trip that was never marked Done", async () => {
      held = past({ done_at: null });
      render(TripPage);
      const card = await cardOf(hotel);
      expect(within(card).getByRole("button", { name: "Edit Harbour Hotel" })).toBeInTheDocument();
      await userEvent.click(within(card).getByRole("button", { name: "More options for Harbour Hotel" }));
      for (const verb of ["Move", "Remove"]) expect(within(card).getByRole("button", { name: `${verb} Harbour Hotel` })).toBeInTheDocument();
    });

    it("hides Edit, Move and Remove once the trip is Done, and keeps the booking's details", async () => {
      held = past({ done_at: 1700000000 });
      render(TripPage);
      const card = await cardOf(hotel);
      expect(card).toHaveTextContent("H88231");
      for (const verb of ["Edit", "Move", "Remove", "More options"]) expect(within(card).queryByRole("button", { name: new RegExp(`^${verb}`) })).toBeNull();
    });

    it("hides them on each booking of a combined flight card once the trip is Done", async () => {
      const first = segment({ id: 1, confirmation: "KQ7M2X", start_local: "2020-03-01T19:00", end_local: "2020-03-02T07:10", details: { flight_number: "AA0101" } });
      const second = segment({ id: 2, confirmation: "BBBBBB", start_local: "2020-03-01T19:00", end_local: "2020-03-02T07:10", details: { flight_number: "AA0101" }, travelers: [{ id: 9, person_id: 2, name: "Sam Doe", seat: null }] });
      held = trip([first, second], { start_date: "2020-03-01", end_date: "2020-03-02", done_at: 1700000000 });
      render(TripPage);
      const blocks = await screen.findAllByRole("listitem").then((all) => all.filter((li) => li.hasAttribute("data-booking")));
      expect(blocks).toHaveLength(2);
      for (const block of blocks) expect(within(block).queryByRole("button", { name: /^(Edit|Move|Remove)/ })).toBeNull();
    });

    describe("live flight status", () => {
      const sams = segment({ id: 5, confirmation: "BBBBBB", details: { flight_number: "AA0101" }, travelers: [{ id: 9, person_id: 2, name: "Sam Doe", seat: null }] });
      const gone = { start_local: "2020-03-01T19:00", end_local: "2020-03-02T07:10" };
      const withStatus = () => {
        const answer = vi.mocked(api).getMockImplementation()!;
        vi.mocked(api).mockImplementation(async (path, opts) => (path === "/api/flight-status" ? delayed : answer(path, opts)) as never);
      };
      const flightCard = async () => within(await screen.findByRole("list", { name: "Bookings" })).getAllByRole("listitem").filter((li) => li.classList.contains("pass"))[0];

      it("shows none on a past flight, and still shows it on a future one", async () => {
        held = trip([{ ...flight, ...gone }], { start_date: "2020-03-01", end_date: "2020-03-02" });
        withStatus();
        const view = render(TripPage);
        const card = await flightCard();
        await waitFor(() => expect(card).toHaveTextContent("JFK"));
        expect(within(card).queryByTestId("flight-status")).toBeNull();
        view.unmount();
        held = trip([flight]);
        render(TripPage);
        expect(await within(await flightCard()).findByTestId("flight-status")).toBeInTheDocument();
      });

      it("shows none on a past flight with two bookings, and still shows it on a future one", async () => {
        held = trip([{ ...flight, ...gone }, { ...sams, ...gone }], { start_date: "2020-03-01", end_date: "2020-03-02" });
        withStatus();
        const view = render(TripPage);
        const card = await flightCard();
        await waitFor(() => expect(card).toHaveTextContent("BBBBBB"));
        expect(within(card).queryByTestId("flight-status")).toBeNull();
        view.unmount();
        held = trip([flight, sams]);
        render(TripPage);
        expect(await within(await flightCard()).findByTestId("flight-status")).toBeInTheDocument();
      });
    });

    it("leaves a trip still to come as it was", async () => {
      loyalty = [membership({ id: 12, person_id: 1, kind: "hotel", program: "Marriott Bonvoy", masked: "••••821L" })];
      held = past({ end_date: "2999-01-01" });
      render(TripPage);
      const card = await cardOf(hotel);
      expect(within(card).getByRole("link", { name: "Directions" })).toBeInTheDocument();
      expect(within(card).getByRole("link", { name: "Call" })).toBeInTheDocument();
      expect(card.querySelector("[data-membership]")).not.toBeNull();
    });
  });
});

describe("Trip on a phone", () => {
  beforeEach(() => { viewport.phone = true; });
  afterEach(() => { viewport.phone = false; });

  it("opens Edit in a sheet, not under the booking, and Cancel closes it with focus back on Edit", async () => {
    render(TripPage);
    const u = userEvent.setup();
    const edit = await screen.findByRole("button", { name: "Edit Harbour Hotel" });
    await u.click(edit);
    const sheet = await screen.findByRole("dialog", { name: "Edit this booking" });
    expect(sheet).toHaveAttribute("data-side", "bottom");
    expect(within(sheet).getByLabelText("Hotel name")).toBeInTheDocument();
    expect(screen.queryByRole("listitem", { name: "Edit booking" })).toBeNull();
    expect(within(sheet).getAllByRole("heading", { name: "Edit this booking" })).toHaveLength(1);
    await u.click(within(sheet).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(edit).toHaveFocus());
  });

  it("saves from the sheet, closes it and reloads the same page", async () => {
    render(TripPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Edit JFK → LHR" }));
    const sheet = await screen.findByRole("dialog");
    await u.clear(within(sheet).getByLabelText("Terminal"));
    await u.type(within(sheet).getByLabelText("Terminal"), "7");
    await u.click(within(sheet).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/segments/1", { method: "POST", body: expect.objectContaining({ details: { flight_number: "AA 101", terminal: "7" } }) }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("heading", { name: "Trip to London" })).toBeInTheDocument();
  });

  it("asks before Escape, the close button, the backdrop or a swipe drops a changed booking, and keeps the typing on Keep editing", async () => {
    render(TripPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Edit JFK → LHR" }));
    const sheet = await screen.findByRole("dialog", { name: "Edit this booking" });
    await u.clear(within(sheet).getByLabelText("Terminal"));
    await u.type(within(sheet).getByLabelText("Terminal"), "7");
    const keep = async () => {
      const ask = await screen.findByRole("dialog", { name: "Discard changes?" });
      await u.click(within(ask).getByRole("button", { name: "Keep editing" }));
      await waitFor(() => expect(screen.queryByRole("dialog", { name: "Discard changes?" })).toBeNull());
      expect(within(sheet).getByLabelText("Terminal")).toHaveValue("7");
    };
    await u.keyboard("{Escape}");
    await keep();
    await u.click(within(sheet).getByRole("button", { name: "Close" }));
    await keep();
    const overlay = document.querySelector("[data-slot='sheet-overlay']") as HTMLElement;
    overlay.dispatchEvent(new MouseEvent("pointerdown", { clientX: 5, clientY: 5, bubbles: true }));
    overlay.dispatchEvent(new MouseEvent("pointerup", { clientX: 5, clientY: 5, bubbles: true }));
    overlay.dispatchEvent(new MouseEvent("click", { clientX: 5, clientY: 5, bubbles: true }));
    await keep();
    const handle = sheet.querySelector("[data-sheet-handle]") as Element;
    handle.dispatchEvent(new MouseEvent("pointerdown", { clientY: 0, bubbles: true }));
    handle.dispatchEvent(new MouseEvent("pointermove", { clientY: 200, bubbles: true }));
    handle.dispatchEvent(new MouseEvent("pointerup", { clientY: 200, bubbles: true }));
    await keep();
    await u.click(within(sheet).getByRole("button", { name: "Cancel" }));
    await u.click(within(await screen.findByRole("dialog", { name: "Discard changes?" })).getByRole("button", { name: "Discard changes" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(vi.mocked(api).mock.calls.some(([, o]) => o?.method === "POST")).toBe(false);
  });

  it("cannot be dismissed while the booking is saving", async () => {
    let finish: (v: unknown) => void = () => {};
    const slow = new Promise((resolve) => { finish = resolve; });
    const before = vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation(async (path, opts) => (opts?.method === "POST" && path === "/api/segments/1" ? slow : before(path, opts)));
    render(TripPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Edit JFK → LHR" }));
    const sheet = await screen.findByRole("dialog");
    await u.clear(within(sheet).getByLabelText("Terminal"));
    await u.type(within(sheet).getByLabelText("Terminal"), "7");
    await u.click(within(sheet).getByRole("button", { name: "Save changes" }));
    await within(sheet).findByRole("button", { name: "Saving…" });
    await u.keyboard("{Escape}");
    await u.click(within(sheet).getByRole("button", { name: "Close" }));
    expect(screen.getByRole("dialog", { name: "Edit this booking" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Discard changes?" })).toBeNull();
    finish(held.segments[0]);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("closes the sheet with Escape and its close button, and the booking is untouched", async () => {
    render(TripPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Edit JFK → LHR" }));
    await screen.findByRole("dialog");
    await u.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    document.body.style.pointerEvents = "";
    await u.click(screen.getByRole("button", { name: "Edit JFK → LHR" }));
    await u.click(await screen.findByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(vi.mocked(api).mock.calls.some(([, o]) => o?.method === "POST")).toBe(false);
  });

  it("keeps what was typed and says why inside the sheet when a save fails", async () => {
    render(TripPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Edit JFK → LHR" }));
    const sheet = await screen.findByRole("dialog");
    await u.type(within(sheet).getByLabelText("Seat of Jane Doe"), "12A");
    vi.mocked(api).mockImplementation(async (path, opts) => {
      if (opts?.method === "POST") throw new Error("Someone on this isn’t in People");
      return held;
    });
    await u.click(within(sheet).getByRole("button", { name: "Save changes" }));
    expect(await within(sheet).findByRole("alert")).toHaveTextContent("Someone on this isn’t in People");
    expect(screen.getByRole("dialog")).toBe(sheet);
    expect(within(sheet).getByLabelText("Seat of Jane Doe")).toHaveValue("12A");
    expect(within(sheet).getByRole("button", { name: "Save changes" })).toBeEnabled();
  });

  it("opens Add address in the sheet too", async () => {
    held = trip([flight, { ...stay, details: {} }]);
    render(TripPage);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Add address to Harbour Hotel" }));
    expect(within(await screen.findByRole("dialog")).getByLabelText("Address")).toBeInTheDocument();
  });

  it("still adds a booking inline at the top", async () => {
    render(TripPage);
    await userEvent.setup().click(await screen.findByRole("button", { name: /Add a booking/ }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("heading", { name: "Add a booking" })).toBeInTheDocument();
  });

  it("keeps the form where it opened if the screen turns into a desktop one", async () => {
    render(TripPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Edit JFK → LHR" }));
    const sheet = await screen.findByRole("dialog");
    await u.type(within(sheet).getByLabelText("Seat of Jane Doe"), "12A");
    viewport.phone = false;
    await waitFor(() => expect(within(screen.getByRole("dialog")).getByLabelText("Seat of Jane Doe")).toHaveValue("12A"));
  });
});

describe("beside a list of trips", () => {
  const removeFlightAndConfirm = async (u: ReturnType<typeof userEvent.setup>) => {
    await bookingOptions(u, "Remove JFK → LHR");
    await u.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  };
  const moveOnSave = () => vi.mocked(api).mockImplementation(async (path, opts) => (path === "/api/segments/1" && opts?.method === "POST" ? segment({ ...flight, trip_id: 7 }) : path === "/api/people" ? { people: [jane, sam] } : path === "/api/loyalty" ? { loyalty, programs: {} } : held) as never);

  it("takes the trip it is given, has no way back to the list, and shows no trip while it loads", async () => {
    const onchanged = vi.fn();
    render(TripPage, { tripId: 1, onchanged });
    expect(screen.getByLabelText("Loading")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Trip to London" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Trips/ })).toBeNull();
    expect(api).toHaveBeenCalledWith("/api/trips/1");
  });

  it("tells the list after a rename", async () => {
    const onchanged = vi.fn();
    render(TripPage, { tripId: 1, onchanged });
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Edit trip details" }));
    await u.clear(screen.getByLabelText("Name"));
    await u.type(screen.getByLabelText("Name"), "Lisbon");
    vi.mocked(api).mockImplementation(async (path, opts) => (path === "/api/trips/1" && opts?.method === "POST" ? { ...held, name: "Lisbon" } : held) as never);
    await u.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onchanged).toHaveBeenCalledTimes(1));
    expect(onchanged).toHaveBeenCalledWith();
  });

  it("tells the list after a booking is removed, and keeps showing the trip", async () => {
    const onchanged = vi.fn();
    render(TripPage, { tripId: 1, onchanged });
    const u = userEvent.setup();
    await bookingOptions(u, "Remove Harbour Hotel");
    await u.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(onchanged).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("heading", { name: "Trip to London" })).toBeInTheDocument();
    expect(location.hash).toBe("#trip/1");
  });

  it("tells the list instead of leaving the page when the last booking of an automatic trip is removed", async () => {
    held = trip([flight], { auto: true });
    const onchanged = vi.fn();
    render(TripPage, { tripId: 1, onchanged });
    await removeFlightAndConfirm(userEvent.setup());
    expect(onchanged).toHaveBeenCalledTimes(1);
    expect(location.hash).toBe("#trip/1");
  });

  it("tells the list which trip a saved booking moved to, without leaving the page", async () => {
    const onchanged = vi.fn();
    render(TripPage, { tripId: 1, onchanged });
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Edit JFK → LHR" }));
    moveOnSave();
    await u.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(onchanged).toHaveBeenCalledWith(7));
    expect(location.hash).toBe("#trip/1");
  });
});

describe("on its own page", () => {
  it("goes back to the trips list when the last booking of an automatic trip is removed", async () => {
    held = trip([flight], { auto: true });
    render(TripPage);
    const u = userEvent.setup();
    await bookingOptions(u, "Remove JFK → LHR");
    await u.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(location.hash).toBe("#trips"));
  });

  describe("costs", () => {
    const costs = { totals: [{ currency: "USD", amount_minor: 124000 }, { currency: "EUR", amount_minor: 31000 }], priced: 2, bookings: 3 };
    const paid = (s: ReturnType<typeof segment>, amount_minor: number, currency: string, source: "email" | "manual" = "email") => ({ ...s, price: { amount_minor, currency, source } });

    it("shows the trip's total per currency under its header, with how many bookings it counts when some have no cost", async () => {
      held = trip([paid(flight, 124000, "USD"), paid(stay, 31000, "EUR"), segment({ id: 3, kind: "car", provider: "Local Cars", confirmation: "C1", start_local: "2026-11-22T09:00",
        end_local: "2026-11-25T09:00", end_zone: "Europe/London", start_zone: "Europe/London", origin: "LHR", destination: null })], { costs });
      render(TripPage);
      await screen.findByRole("heading", { name: "Trip to London" });
      const line = document.querySelector("[data-trip-total]")!;
      expect(line).toHaveTextContent(/Total\s*\$1,240\.00 \+ €310\.00\s*·\s*2 of 3 bookings/);
    });

    it("says nothing about the count when every booking has a cost, and shows no total when none does", async () => {
      held = trip([paid(flight, 124000, "USD")], { costs: { totals: [{ currency: "USD", amount_minor: 124000 }], priced: 1, bookings: 1 } });
      const view = render(TripPage);
      await screen.findByRole("heading", { name: "Trip to London" });
      expect(document.querySelector("[data-trip-total]")).toHaveTextContent(/^Total\s*\$1,240\.00$/);
      view.unmount();
      held = trip([flight]);
      render(TripPage);
      await screen.findByRole("heading", { name: "Trip to London" });
      expect(document.querySelector("[data-trip-total]")).toBeNull();
    });

    it("shows a booking's cost on its card, and a cancelled one's struck through", async () => {
      held = trip([paid(flight, 124000, "USD"), { ...paid(stay, 31000, "EUR"), status: "cancelled" }], { costs: { ...costs, totals: [costs.totals[0]], priced: 1, bookings: 1 } });
      render(TripPage);
      const cards = within(await screen.findByRole("list", { name: "Bookings" })).getAllByRole("listitem").filter((li) => li.classList.contains("pass"));
      expect(within(cards[0]).getByText(/\$1,240\.00/)).not.toHaveClass("line-through");
      expect(within(cards[1]).getByText(/€310\.00/)).toHaveClass("line-through");
      expect(within(cards[1]).getByText("Cancelled, so not in the trip’s total")).toBeInTheDocument();
    });

    it("shows each booking's cost when several share one card", async () => {
      const twin = segment({ id: 5, confirmation: "ZZ9ZZ9", details: flight.details });
      held = trip([paid(flight, 124000, "USD"), paid(twin, 5000, "USD")], { costs: { totals: [{ currency: "USD", amount_minor: 129000 }], priced: 2, bookings: 2 } });
      render(TripPage);
      await screen.findByRole("list", { name: /Bookings of/ });
      const shown = [...document.querySelectorAll("[data-booking] [data-cost]")].map((el) => el.textContent?.replace(/\s+/g, " ").trim());
      expect(shown).toEqual(["Cost $1,240.00", "Cost $50.00"]);
    });

    it("hides the total and every cost when the household has turned costs off, and keeps the edit form's cost field", async () => {
      app.state = state({ show_costs: false });
      const twin = segment({ id: 5, confirmation: "ZZ9ZZ9", details: flight.details });
      held = trip([paid(flight, 124000, "USD"), paid(twin, 5000, "USD")], { costs: { totals: [{ currency: "USD", amount_minor: 129000 }], priced: 2, bookings: 2 } });
      render(TripPage);
      await screen.findByRole("list", { name: /Bookings of/ });
      expect(document.querySelector("[data-trip-total]")).toBeNull();
      expect(document.querySelector("[data-cost]")).toBeNull();
      expect(document.body).not.toHaveTextContent(/\$1,240\.00|\$1,290\.00/);
    });

    it("saves the cost typed in the edit form, in the smallest unit", async () => {
      held = trip([paid(flight, 124000, "USD")], { costs: { totals: [{ currency: "USD", amount_minor: 124000 }], priced: 1, bookings: 1 } });
      render(TripPage);
      const u = userEvent.setup();
      await u.click(await screen.findByRole("button", { name: "Edit JFK → LHR" }));
      const amount = screen.getByLabelText("Cost amount");
      expect(amount).toHaveValue("1240.00");
      await u.clear(amount);
      await u.type(amount, "1,300.50");
      await u.click(screen.getByRole("button", { name: "Save changes" }));
      await waitFor(() => expect(api).toHaveBeenCalledWith("/api/segments/1", expect.objectContaining({
        method: "POST", body: expect.objectContaining({ price: { amount_minor: 130050, currency: "USD" } }) })));
    });

    it("clears the cost when the amount is emptied", async () => {
      held = trip([paid(flight, 124000, "USD")], { costs: { totals: [{ currency: "USD", amount_minor: 124000 }], priced: 1, bookings: 1 } });
      render(TripPage);
      const u = userEvent.setup();
      await u.click(await screen.findByRole("button", { name: "Edit JFK → LHR" }));
      await u.clear(screen.getByLabelText("Cost amount"));
      await u.click(screen.getByRole("button", { name: "Save changes" }));
      await waitFor(() => expect(api).toHaveBeenCalledWith("/api/segments/1", expect.objectContaining({ body: expect.objectContaining({ price: null }) })));
    });
  });

  it("opens the trip a saved booking moved to", async () => {
    render(TripPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Edit JFK → LHR" }));
    vi.mocked(api).mockImplementation(async (path, opts) => (path === "/api/segments/1" && opts?.method === "POST" ? segment({ ...flight, trip_id: 7 }) : path === "/api/people" ? { people: [jane, sam] } : path === "/api/loyalty" ? { loyalty, programs: {} } : held) as never);
    await u.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(location.hash).toBe("#trip/7"));
  });
  describe("the gate code of a parking booking", () => {
    const lot = segment({ id: 5, kind: "parking", provider: "Example Parking", origin: "Example Airport Long-Term Lot", destination: null, confirmation: "PK30417",
      start_local: "2099-01-10T05:15", start_zone: "America/New_York", end_local: "2099-01-13T03:00", end_zone: "America/New_York", details: {},
      has_email: true, gate_code: { state: "ready", day: "2098-12-20" }, travelers: [] });

    it("puts Show QR code in the booking’s row of actions, ahead of View email, and Choose another picture after it", async () => {
      held = trip([lot]);
      render(TripPage);
      const group = await screen.findByRole("group", { name: "Actions for Example Airport Long-Term Lot" });
      expect(Array.from(group.querySelectorAll("a, button"), (el) => el.textContent?.trim())).toEqual(["Show QR code", "Choose another picture", "View email"]);
    });

    it("offers Choose the code when several pictures qualify, and nothing for a parking booking with no code", async () => {
      held = trip([{ ...lot, gate_code: { state: "choose", day: "2098-12-20" } }]);
      const { unmount } = render(TripPage);
      expect(await screen.findByRole("button", { name: "Choose the code for Example Airport Long-Term Lot" })).toBeInTheDocument();
      unmount();
      held = trip([{ ...lot, gate_code: null, has_email: false }]);
      render(TripPage);
      await screen.findByRole("list", { name: "Bookings" });
      expect(screen.queryByRole("button", { name: /QR code|Choose the code/ })).toBeNull();
    });

    it("shows nothing once the booking’s exit time has passed", async () => {
      held = trip([{ ...lot, start_local: "2020-01-10T05:15", end_local: "2020-01-13T03:00", gate_code: { state: "ready", day: "2019-12-20" } }]);
      render(TripPage);
      await screen.findByRole("list", { name: "Bookings" });
      expect(screen.queryByRole("button", { name: /QR code/ })).toBeNull();
    });

    it("opens the chooser from the booking’s Choose the code button", async () => {
      held = trip([{ ...lot, gate_code: { state: "choose", day: "2098-12-20" } }]);
      const answer = vi.mocked(api).getMockImplementation()!;
      vi.mocked(api).mockImplementation(async (path, opts) => (path === "/api/segments/5/emails" ? { emails: [{ subject: "x", sender_domain: "d.example", received: "2098-12-20", text: "", html: null, truncated: false, original: true, images: 0 }] } : answer(path, opts)) as never);
      render(TripPage);
      await userEvent.click(await screen.findByRole("button", { name: "Choose the code for Example Airport Long-Term Lot" }));
      expect(await screen.findByRole("dialog", { name: "Choose the code" })).toBeInTheDocument();
    });
  });
});
