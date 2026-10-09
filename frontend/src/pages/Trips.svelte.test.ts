// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { Person, Trip } from "$lib/api-types";
import { route } from "$lib/app.svelte";
import { panes } from "$lib/panes.svelte";
import { segment, trip } from "../test/fixtures";
import Trips from "./Trips.svelte";

const jane: Person = { id: 1, display_name: "Jane Doe", first_name: "Jane", legal_name: null, aliases: [], member: true, links: [] };
const sam: Person = { id: 2, display_name: "Sam Doe", first_name: "Sam", legal_name: null, aliases: [], member: true, links: [] };
const london = trip([segment({ id: 1, trip_id: 1, travelers: [{ id: 1, person_id: 1, name: "Jane Doe", seat: null }, { id: 2, person_id: 2, name: "Sam Doe", seat: null }] })], { id: 1, name: "Trip to London" });
const auckland = trip([segment({ id: 2, trip_id: 2, origin: "JFK", destination: "AKL", start_local: "2027-01-14T21:00", end_local: "2027-01-16T06:30",
  travelers: [{ id: 3, person_id: 2, name: "Sam Doe", seat: null }] })], { id: 2, name: "Trip to Auckland" });
const orlando = trip([segment({ id: 3, trip_id: 3, start_local: "2026-08-25T08:00", end_local: "2026-08-30T20:00", travelers: [{ id: 4, person_id: 1, name: "Jane Doe", seat: null }] })], { id: 3, name: "Trip to Orlando" });

function serve(trips = [london, auckland, orlando]) {
  vi.mocked(api).mockImplementation(async (path, opts) => {
    if (path === "/api/segments" && opts?.method === "POST") return segment({ id: 9, trip_id: 5 });
    if (path === "/api/people") return { people: [jane, sam] };
    return { trips };
  });
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-05T12:00:00Z"));
  vi.mocked(api).mockReset();
  route.query = "";
  location.hash = "#trips";
  serve();
});
afterEach(() => { vi.useRealTimers(); panes.two = false; });
const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

describe("what a trip holds", () => {
  it("shows a small icon for each kind of booking on a trip, named for a screen reader", async () => {
    serve([trip([segment({ id: 1, kind: "flight" }), segment({ id: 2, kind: "hotel" })], { id: 1, name: "Trip to London" }), trip([segment({ id: 3, kind: "flight" })], { id: 2, name: "Trip to Auckland" })]);
    render(Trips);
    await screen.findByText("Trip to London");
    const icons = screen.getAllByRole("img", { name: /^Includes:/ });
    expect(icons.map((i) => i.getAttribute("aria-label"))).toEqual(["Includes: flight, stay", "Includes: flight"]);
    expect(icons[0].querySelectorAll("svg")).toHaveLength(2);
    expect(icons[1].querySelectorAll("svg")).toHaveLength(1);
  });
});

describe("Trips", () => {
  it("doesn’t tag a trip you named or changed as edited", async () => {
    serve([{ ...london, auto: false }]);
    render(Trips);
    await screen.findByText("Trip to London");
    expect(screen.queryByText("Edited")).toBeNull();
  });

  it("lists the trips still to come, soonest first, and the past ones apart", async () => {
    render(Trips);
    const upcoming = await screen.findByRole("list", { name: "Upcoming trips" });
    expect(within(upcoming).getAllByRole("link").map((a) => a.textContent?.split(" ")[0] + " " + a.textContent?.split(" ")[1] + " " + a.textContent?.split(" ")[2])).toEqual(["Trip to London", "Trip to Auckland"]);
    expect(within(upcoming).getAllByRole("link")[0]).toHaveAttribute("href", "#trip/1");
    expect(within(screen.getByRole("list", { name: "Past trips" })).getByRole("link")).toHaveTextContent("Trip to Orlando");
  });

  it("filters by traveller, and keeps the filter in the address", async () => {
    render(Trips);
    await screen.findByRole("list", { name: "Upcoming trips" });
    await user().selectOptions(screen.getByLabelText("Travelling"), "Jane Doe");
    expect(route.query).toBe("who=1");
    expect(screen.queryByText("Trip to Auckland")).toBeNull();
    expect(screen.getByText("Trip to London")).toBeInTheDocument();
    expect(screen.getByText("Trip to Orlando")).toBeInTheDocument();
    await user().selectOptions(screen.getByLabelText("Travelling"), "Everyone");
    expect(route.query).toBe("");
    expect(screen.getByText("Trip to Auckland")).toBeInTheDocument();
  });

  it("says when nobody travels on any trip, and when there are none", async () => {
    route.query = "who=2";
    serve([orlando]);
    render(Trips);
    expect(await screen.findByText("No trips with them.")).toBeInTheDocument();
  });

  it("says there are no trips yet", async () => {
    serve([]);
    render(Trips);
    expect(await screen.findByText(/No trips yet — they’ll appear here/)).toBeInTheDocument();
  });

  it("doesn't leave stale trips looking current when a reload fails", async () => {
    vi.mocked(api).mockRejectedValue(new Error("Waypoint is unreachable"));
    render(Trips);
    expect(await screen.findByText("Waypoint is unreachable")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Upcoming trips" })).toBeNull();
    serve();
    await user().click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("list", { name: "Upcoming trips" })).toBeInTheDocument();
  });

  it("adds a booking by hand, and opens the trip it landed in", async () => {
    render(Trips);
    const u = user();
    await u.click(await screen.findByRole("button", { name: /Add a booking/ }));
    await u.type(screen.getByLabelText(/From \(airport\)/), "jfk");
    await u.type(screen.getByLabelText(/To \(airport\)/), "LHR");
    await u.type(screen.getByLabelText(/^Departs/), "2026-12-01T19:00");
    await u.type(screen.getByLabelText(/^Arrives/), "2026-12-02T07:10");
    await u.click(screen.getByLabelText("Jane Doe"));
    await u.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/segments", { method: "POST", body: expect.objectContaining({ kind: "flight", origin: "JFK", destination: "LHR", start_local: "2026-12-01T19:00", travelers: [{ person_id: 1, seat: null }], trip_id: null }) }));
    await waitFor(() => expect(location.hash).toBe("#trip/5"));
  });

  it("keeps what was typed and says why when a save fails", async () => {
    vi.mocked(api).mockImplementation(async (path, opts) => {
      if (path === "/api/segments" && opts?.method === "POST") throw new Error("This ends before it starts");
      return path === "/api/people" ? { people: [jane] } : { trips: [london] };
    });
    render(Trips);
    const u = user();
    await u.click(await screen.findByRole("button", { name: /Add a booking/ }));
    await u.type(screen.getByLabelText(/From \(airport\)/), "JFK");
    await u.type(screen.getByLabelText(/To \(airport\)/), "LHR");
    await u.type(screen.getByLabelText(/^Departs/), "2026-12-01T19:00");
    await u.type(screen.getByLabelText(/^Arrives/), "2026-12-02T07:10");
    await u.click(screen.getByLabelText("Jane Doe"));
    await u.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This ends before it starts");
    expect(screen.getByLabelText(/From \(airport\)/)).toHaveValue("JFK");
    expect(screen.getByLabelText(/^Departs/)).toHaveValue("2026-12-01T19:00");
    expect(screen.getByLabelText("Jane Doe")).toBeChecked();
  });

  it("says what's missing before sending anything", async () => {
    render(Trips);
    const u = user();
    await u.click(await screen.findByRole("button", { name: /Add a booking/ }));
    await u.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A flight’s origin is an airport code like JFK");
    expect(api).not.toHaveBeenCalledWith("/api/segments", expect.anything());
    await u.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("form")).toBeNull();
  });
});

describe("the traveller filter’s address", () => {
  const hashChanged = () => window.dispatchEvent(new HashChangeEvent("hashchange"));

  it("opens on the traveller in the address, writes a new choice back and reads it again", async () => {
    location.hash = "#trips?who=2";
    hashChanged();
    expect(route.query).toBe("who=2");
    render(Trips);
    await screen.findByRole("list", { name: "Upcoming trips" });
    expect(screen.getByLabelText("Travelling")).toHaveValue("2");
    expect(screen.queryByText("Trip to Orlando")).toBeNull();

    await user().selectOptions(screen.getByLabelText("Travelling"), "Jane Doe");
    expect(location.hash).toBe("#trips?who=1");
    route.query = "";
    hashChanged();
    expect(route.query).toBe("who=1");
    await waitFor(() => expect(screen.getByLabelText("Travelling")).toHaveValue("1"));
    expect(screen.queryByText("Trip to Auckland")).toBeNull();
    expect(screen.getByText("Trip to Orlando")).toBeInTheDocument();

    await user().selectOptions(screen.getByLabelText("Travelling"), "Everyone");
    expect(location.hash).toBe("#trips");
  });
});

describe("two panes", () => {
  function serveTrips() {
    const all = [london, auckland, orlando];
    vi.mocked(api).mockImplementation(async (path) => {
      if (path === "/api/people") return { people: [jane, sam] };
      if (path === "/api/loyalty") return { loyalty: [], programs: {} };
      const one = /^\/api\/trips\/(\d+)$/.exec(path);
      if (one) return all.find((t) => t.id === Number(one[1]));
      return { trips: all };
    });
  }

  it("shows the first trip beside the list on a wide screen, and the one you pick", async () => {
    panes.two = true;
    serveTrips();
    render(Trips);
    const pane = await screen.findByRole("region", { name: "Selected trip" });
    expect(await within(pane).findByRole("heading", { level: 1, name: "Trip to London" })).toBeInTheDocument();
    expect(within(pane).queryByRole("link", { name: /^Trips$/ })).toBeNull();
    const links = within(screen.getByRole("list", { name: "Upcoming trips" })).getAllByRole("link");
    expect(links[0]).toHaveAttribute("aria-current", "true");

    await user().click(links[1]);
    expect(await within(pane).findByRole("heading", { level: 1, name: "Trip to Auckland" })).toBeInTheDocument();
    expect(links[1]).toHaveAttribute("aria-current", "true");
    expect(links[0]).not.toHaveAttribute("aria-current");
    expect(location.hash).toBe("#trips");
  });

  it("stays a list that opens the trip page on a phone or tablet", async () => {
    serveTrips();
    render(Trips);
    await screen.findByRole("list", { name: "Upcoming trips" });
    expect(screen.queryByRole("region", { name: "Selected trip" })).toBeNull();
    const link = within(screen.getByRole("list", { name: "Upcoming trips" })).getAllByRole("link")[1];
    expect(link).toHaveAttribute("href", "#trip/2");
    expect(link).not.toHaveAttribute("aria-current");
  });

  it("falls back to the first trip left when the filter hides the picked one", async () => {
    panes.two = true;
    serveTrips();
    render(Trips);
    const pane = await screen.findByRole("region", { name: "Selected trip" });
    await user().click(within(screen.getByRole("list", { name: "Upcoming trips" })).getAllByRole("link")[1]);
    await within(pane).findByRole("heading", { level: 1, name: "Trip to Auckland" });
    await user().selectOptions(screen.getByLabelText("Travelling"), "Jane Doe");
    expect(await within(screen.getByRole("region", { name: "Selected trip" })).findByRole("heading", { level: 1, name: "Trip to London" })).toBeInTheDocument();
  });
});

describe("changing a trip in the pane", () => {
  const second = segment({ id: 4, trip_id: 1, kind: "hotel", origin: "Harbour Hotel", destination: null, confirmation: "H88231", details: {}, start_local: "2026-11-21T15:00", start_zone: "Europe/London", end_local: "2026-11-27T10:00", end_zone: "Europe/London" });
  let store: Trip[];

  function serveStateful() {
    store = [trip([...london.segments, second], { id: 1, name: "Trip to London" }), auckland, orlando];
    vi.mocked(api).mockImplementation(async (path, opts) => {
      if (path === "/api/people") return { people: [jane, sam] };
      if (path === "/api/loyalty") return { loyalty: [], programs: {} };
      const one = /^\/api\/trips\/(\d+)$/.exec(path);
      if (one && opts?.method === "POST") {
        store = store.map((t) => (t.id === Number(one[1]) ? { ...t, name: (opts.body as { name: string }).name } : t));
        return store.find((t) => t.id === Number(one[1]));
      }
      if (one) return store.find((t) => t.id === Number(one[1]));
      const gone = /^\/api\/segments\/(\d+)$/.exec(path);
      if (gone && opts?.method === "DELETE") {
        store = store.map((t) => ({ ...t, segments: t.segments.filter((s) => s.id !== Number(gone[1])) })).filter((t) => t.segments.length);
        return { ok: true };
      }
      if (gone && opts?.method === "POST") {
        const moved = segment({ ...second, trip_id: 2 });
        store = store.map((t) => (t.id === 1 ? { ...t, segments: t.segments.filter((s) => s.id !== 4) } : t.id === 2 ? { ...t, segments: [...t.segments, moved] } : t));
        return moved;
      }
      return { trips: store };
    });
  }

  const confirmRemove = async (u: ReturnType<typeof user>, name: string) => {
    await u.click(await screen.findByRole("button", { name }));
    await u.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    document.body.style.pointerEvents = "";
  };

  beforeEach(() => { panes.two = true; serveStateful(); });

  it("shows a renamed trip in the list", async () => {
    render(Trips);
    const pane = await screen.findByRole("region", { name: "Selected trip" });
    const u = user();
    await u.click(await within(pane).findByRole("button", { name: "Rename trip" }));
    await u.clear(within(pane).getByLabelText("Trip name"));
    await u.type(within(pane).getByLabelText("Trip name"), "Lisbon");
    await u.click(within(pane).getByRole("button", { name: "Save" }));
    const upcoming = screen.getByRole("list", { name: "Upcoming trips" });
    await waitFor(() => expect(within(upcoming).getByText("Lisbon")).toBeInTheDocument());
    expect(within(upcoming).queryByText("Trip to London")).toBeNull();
    expect(await within(pane).findByRole("heading", { level: 1, name: "Lisbon" })).toBeInTheDocument();
  });

  it("drops a removed booking from the pane and keeps the trip in the list", async () => {
    render(Trips);
    const pane = await screen.findByRole("region", { name: "Selected trip" });
    await within(pane).findByRole("heading", { level: 1, name: "Trip to London" });
    await confirmRemove(user(), "Remove Harbour Hotel");
    await waitFor(() => expect(within(pane).queryByRole("button", { name: "Remove Harbour Hotel" })).toBeNull());
    expect(within(pane).getByRole("button", { name: "Remove JFK → LHR" })).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Upcoming trips" })).getByText("Trip to London")).toBeInTheDocument();
  });

  it("falls back to the next trip, and stays on the page, when the last booking of the selected trip is removed", async () => {
    store = [trip([london.segments[0]], { id: 1, name: "Trip to London" }), auckland, orlando];
    render(Trips);
    const pane = await screen.findByRole("region", { name: "Selected trip" });
    await within(pane).findByRole("heading", { level: 1, name: "Trip to London" });
    await confirmRemove(user(), "Remove JFK → LHR");
    expect(await within(pane).findByRole("heading", { level: 1, name: "Trip to Auckland" })).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Upcoming trips" })).queryByText("Trip to London")).toBeNull();
    expect(location.hash).toBe("#trips");
  });

  it("clears the pane when the last trip is gone", async () => {
    store = [trip([london.segments[0]], { id: 1, name: "Trip to London" })];
    render(Trips);
    const pane = await screen.findByRole("region", { name: "Selected trip" });
    await within(pane).findByRole("heading", { level: 1, name: "Trip to London" });
    await confirmRemove(user(), "Remove JFK → LHR");
    expect(await screen.findByText(/No trips yet/)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Selected trip" })).toBeNull();
    expect(location.hash).toBe("#trips");
  });

  it("shows nothing of the previous trip while the picked one loads", async () => {
    render(Trips);
    const pane = await screen.findByRole("region", { name: "Selected trip" });
    await within(pane).findByRole("heading", { level: 1, name: "Trip to London" });
    const answer = vi.mocked(api).getMockImplementation()!;
    let release: () => void = () => {};
    const held = new Promise<void>((r) => { release = r; });
    vi.mocked(api).mockImplementation(async (path, opts) => { if (path === "/api/trips/2") await held; return answer(path, opts); });
    await user().click(within(screen.getByRole("list", { name: "Upcoming trips" })).getAllByRole("link")[1]);
    expect(within(pane).queryByRole("heading", { level: 1, name: "Trip to London" })).toBeNull();
    expect(within(pane).getByLabelText("Loading")).toBeInTheDocument();
    release();
    expect(await within(pane).findByRole("heading", { level: 1, name: "Trip to Auckland" })).toBeInTheDocument();
  });

  it("follows a booking that is saved onto another trip, instead of leaving the two panes", async () => {
    render(Trips);
    const pane = await screen.findByRole("region", { name: "Selected trip" });
    const u = user();
    await u.click(await within(pane).findByRole("button", { name: "Edit Harbour Hotel" }));
    await u.click(within(pane).getByRole("button", { name: "Save" }));
    expect(await within(pane).findByRole("heading", { level: 1, name: "Trip to Auckland" })).toBeInTheDocument();
    expect(within(pane).getByRole("button", { name: "Edit Harbour Hotel" })).toBeInTheDocument();
    expect(location.hash).toBe("#trips");
    expect(within(screen.getByRole("list", { name: "Upcoming trips" })).getAllByRole("link")[1]).toHaveAttribute("aria-current", "true");
  });
});
