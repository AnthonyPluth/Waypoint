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
import { viewport } from "$lib/phone.svelte";
import { segment, trip } from "../test/fixtures";
import { bookingOptions } from "../test/menu";
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
afterEach(() => { vi.useRealTimers(); panes.two = false; viewport.phone = false; });
const person = (name: string) => screen.getByRole("button", { name });
const travelling = () => screen.getByRole("group", { name: "Travelling" });
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
    expect([...icons[0].querySelectorAll("[data-tile]")].map((t) => t.getAttribute("data-tile"))).toEqual(["flight", "hotel"]);
    expect(icons[0].querySelectorAll("[role=img]")).toHaveLength(0);
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
    const links = within(upcoming).getAllByRole("link");
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveTextContent("Trip to London");
    expect(links[1]).toHaveTextContent("Trip to Auckland");
    expect(within(upcoming).getAllByRole("link")[0]).toHaveAttribute("href", "#trip/1");
    expect(within(screen.getByRole("list", { name: "Past trips in 2026" })).getByRole("link")).toHaveTextContent("Trip to Orlando");
  });

  it("filters by traveller, and keeps the filter in the address", async () => {
    render(Trips);
    await screen.findByRole("list", { name: "Upcoming trips" });
    await user().click(within(travelling()).getByRole("button", { name: "Jane Doe" }));
    expect(route.query).toBe("who=1");
    expect(screen.queryByText("Trip to Auckland")).toBeNull();
    expect(screen.getByText("Trip to London")).toBeInTheDocument();
    expect(screen.getByText("Trip to Orlando")).toBeInTheDocument();
    await user().click(within(travelling()).getByRole("button", { name: "Jane Doe" }));
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
    await u.click(screen.getByRole("checkbox", { name: "Jane Doe" }));
    await u.click(screen.getByRole("button", { name: "Add booking" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/segments", { method: "POST", body: expect.objectContaining({ kind: "flight", origin: "JFK", destination: "LHR", start_local: "2026-12-01T19:00", travelers: [{ person_id: 1, seat: null }], trip_id: null }) }));
    await waitFor(() => expect(location.hash).toBe("#trip/5"));
  });

  it("opens the add form directly when sent here to add a booking, and cancel clears the link", async () => {
    route.query = "add=booking";
    render(Trips);
    expect(await screen.findByLabelText(/From \(airport\)/)).toBeInTheDocument();
    await user().click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText(/From \(airport\)/)).toBeNull();
    expect(route.query).toBe("");
    expect(screen.getByRole("button", { name: /Add a booking/ })).toBeInTheDocument();
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
    await u.click(screen.getByRole("checkbox", { name: "Jane Doe" }));
    await u.click(screen.getByRole("button", { name: "Add booking" }));
    expect(await screen.findByText(/This ends before it starts/)).toBeInTheDocument();
    expect(screen.getByLabelText(/From \(airport\)/)).toHaveValue("JFK");
    expect(screen.getByLabelText(/^Departs/)).toHaveValue("2026-12-01T19:00");
    expect(screen.getByRole("checkbox", { name: "Jane Doe" })).toBeChecked();
  });

  it("says what's missing before sending anything", async () => {
    render(Trips);
    const u = user();
    await u.click(await screen.findByRole("button", { name: /Add a booking/ }));
    await u.click(screen.getByRole("button", { name: "Add booking" }));
    expect(await screen.findByText(/Choose the airport it leaves from/)).toBeInTheDocument();
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
    expect(person("Sam Doe")).toHaveAttribute("aria-pressed", "true");
    expect(person("Jane Doe")).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByText("Trip to Orlando")).toBeNull();

    await user().click(person("Jane Doe"));
    expect(location.hash).toBe("#trips?who=1");
    route.query = "";
    hashChanged();
    expect(route.query).toBe("who=1");
    await waitFor(() => expect(person("Jane Doe")).toHaveAttribute("aria-pressed", "true"));
    expect(screen.queryByText("Trip to Auckland")).toBeNull();
    expect(screen.getByText("Trip to Orlando")).toBeInTheDocument();

    await user().click(person("Jane Doe"));
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
    expect(location.hash).toBe("#trips?trip=2");
    expect(route.query).toBe("trip=2");
  });

  it("opens the trip the address names, and keeps the filter beside it", async () => {
    panes.two = true;
    serveTrips();
    route.query = "who=2&trip=2";
    location.hash = "#trips?who=2&trip=2";
    render(Trips);
    const pane = await screen.findByRole("region", { name: "Selected trip" });
    expect(await within(pane).findByRole("heading", { level: 1, name: "Trip to Auckland" })).toBeInTheDocument();
    await user().click(within(screen.getByRole("list", { name: "Upcoming trips" })).getAllByRole("link")[0]);
    expect(route.query).toBe("who=2&trip=1");
  });

  it("keeps the picked trip when a new filter still includes it", async () => {
    panes.two = true;
    serveTrips();
    render(Trips);
    const pane = await screen.findByRole("region", { name: "Selected trip" });
    await user().click(within(screen.getByRole("list", { name: "Upcoming trips" })).getAllByRole("link")[1]);
    await within(pane).findByRole("heading", { level: 1, name: "Trip to Auckland" });
    await user().click(person("Sam Doe"));
    expect(route.query).toBe("who=2&trip=2");
    expect(await within(screen.getByRole("region", { name: "Selected trip" })).findByRole("heading", { level: 1, name: "Trip to Auckland" })).toBeInTheDocument();
  });

  it("shows the first trip when the address names one that isn’t in the list", async () => {
    panes.two = true;
    serveTrips();
    route.query = "trip=999";
    render(Trips);
    const pane = await screen.findByRole("region", { name: "Selected trip" });
    expect(await within(pane).findByRole("heading", { level: 1, name: "Trip to London" })).toBeInTheDocument();
  });

  it("stays a plain list where the address names a trip but the screen is narrow", async () => {
    serveTrips();
    route.query = "trip=2";
    render(Trips);
    await screen.findByRole("list", { name: "Upcoming trips" });
    expect(screen.queryByRole("region", { name: "Selected trip" })).toBeNull();
  });

  it("asks before another trip is picked, or the filter swaps it, over a changed booking, and stays on the trip on Keep editing", async () => {
    panes.two = true;
    serveTrips();
    render(Trips);
    const pane = await screen.findByRole("region", { name: "Selected trip" });
    const u = user();
    await u.click(await within(pane).findByRole("button", { name: "Edit JFK → LHR" }));
    await u.type(within(pane).getByLabelText("Confirmation code"), "Z");
    const links = within(screen.getByRole("list", { name: "Upcoming trips" })).getAllByRole("link");
    await u.click(links[1]);
    await u.click(within(await screen.findByRole("dialog", { name: "Discard changes?" })).getByRole("button", { name: "Keep editing" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    document.body.style.pointerEvents = "";
    expect(within(pane).getByRole("heading", { level: 1, name: "Trip to London" })).toBeInTheDocument();
    expect((within(pane).getByLabelText("Confirmation code") as HTMLInputElement).value.endsWith("Z")).toBe(true);
    await u.click(person("Sam Doe"));
    await u.click(within(await screen.findByRole("dialog", { name: "Discard changes?" })).getByRole("button", { name: "Keep editing" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    document.body.style.pointerEvents = "";
    expect(person("Sam Doe")).toHaveAttribute("aria-pressed", "false");
    await u.click(links[1]);
    await u.click(within(await screen.findByRole("dialog", { name: "Discard changes?" })).getByRole("button", { name: "Discard changes" }));
    expect(await within(screen.getByRole("region", { name: "Selected trip" })).findByRole("heading", { level: 1, name: "Trip to Auckland" })).toBeInTheDocument();
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
    await user().click(person("Jane Doe"));
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
    await bookingOptions(u, name);
    await u.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    document.body.style.pointerEvents = "";
  };

  beforeEach(() => { panes.two = true; serveStateful(); });

  it("shows a renamed trip in the list", async () => {
    render(Trips);
    const pane = await screen.findByRole("region", { name: "Selected trip" });
    const u = user();
    await u.click(await within(pane).findByRole("button", { name: "Edit trip details" }));
    await u.clear(within(pane).getByLabelText("Name"));
    await u.type(within(pane).getByLabelText("Name"), "Lisbon");
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
    await waitFor(() => expect(within(pane).queryByRole("button", { name: "Edit Harbour Hotel" })).toBeNull());
    expect(within(pane).getByRole("button", { name: "Edit JFK → LHR" })).toBeInTheDocument();
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
    await u.click(within(pane).getByRole("button", { name: "Save changes" }));
    expect(await within(pane).findByRole("heading", { level: 1, name: "Trip to Auckland" })).toBeInTheDocument();
    expect(within(pane).getByRole("button", { name: "Edit Harbour Hotel" })).toBeInTheDocument();
    expect(location.hash).toBe("#trips?trip=2");
    expect(within(screen.getByRole("list", { name: "Upcoming trips" })).getAllByRole("link")[1]).toHaveAttribute("aria-current", "true");
  });
});

describe("overlapping loads", () => {
  it("doesn’t let an earlier, slower reply overwrite a newer list", async () => {
    panes.two = true;
    const named = (name: string) => trip([segment({ id: 1, trip_id: 1 })], { id: 1, name });
    let release: (v: unknown) => void = () => {};
    const slow = new Promise((r) => { release = r; });
    let holdNext = false;
    let latestName = "Trip to London";
    vi.mocked(api).mockImplementation(async (path, opts) => {
      if (path === "/api/people") return { people: [jane, sam] };
      if (path === "/api/loyalty") return { loyalty: [], programs: {} };
      const one = /^\/api\/trips\/(\d+)$/.exec(path);
      if (one && opts?.method === "POST") { latestName = (opts.body as { name: string }).name; return named(latestName); }
      if (one) return named(latestName);
      if (holdNext) { holdNext = false; return slow; }
      return { trips: [named(latestName)] };
    });
    render(Trips);
    const pane = await screen.findByRole("region", { name: "Selected trip" });
    const u = user();
    const rename = async (name: string) => {
      await u.click(await within(pane).findByRole("button", { name: "Edit trip details" }));
      await u.clear(within(pane).getByLabelText("Name"));
      await u.type(within(pane).getByLabelText("Name"), name);
      await u.click(within(pane).getByRole("button", { name: "Save" }));
    };
    holdNext = true;
    await rename("First name");
    await waitFor(() => expect(holdNext).toBe(false));
    await rename("Second name");
    const upcoming = screen.getByRole("list", { name: "Upcoming trips" });
    await waitFor(() => expect(within(upcoming).getByText("Second name")).toBeInTheDocument());
    release({ trips: [named("First name")] });
    await new Promise((r) => setTimeout(r, 20));
    expect(within(screen.getByRole("list", { name: "Upcoming trips" })).getByText("Second name")).toBeInTheDocument();
    expect(screen.queryByText("First name")).toBeNull();
  });
});

describe("finding a trip", () => {
  const archive = Array.from({ length: 300 }, (_, i) => trip([segment({ id: 1000 + i, trip_id: 100 + i, provider: i === 123 ? "Icelandair" : "Delta Air Lines", start_local: `${2018 + (i % 8)}-03-10T09:00`, end_local: `${2018 + (i % 8)}-03-12T09:00` })],
    { id: 100 + i, name: i === 123 ? "Aurora weekend" : `Trip ${i}`, destination: i === 123 ? "Reykjavik" : "Atlanta", start_date: `${2018 + (i % 8)}-03-10`, end_date: `${2018 + (i % 8)}-03-12` }));

  it("narrows a long archive by name, destination or airline, and keeps the search in the address", async () => {
    serve(archive);
    render(Trips);
    await screen.findByText("300 trips");
    await user().click(screen.getByRole("searchbox", { name: "Search trips" }));
    await user().paste("reykjavik");
    expect(route.query).toBe("q=reykjavik");
    expect(screen.getByText("1 of 300 trips")).toBeInTheDocument();
    expect(screen.getAllByRole("link")).toHaveLength(1);
    expect(screen.getByText("Aurora weekend")).toBeInTheDocument();
    await user().clear(screen.getByRole("searchbox", { name: "Search trips" }));
    await user().paste("icelandair");
    expect(screen.getByText("Aurora weekend")).toBeInTheDocument();
    expect(screen.getByText("1 of 300 trips")).toBeInTheDocument();
  });

  it("opens with the filters from the address, and says when nothing matches", async () => {
    serve(archive);
    route.query = "q=nowhere&when=past&year=2019";
    render(Trips);
    expect(await screen.findByText("No trips match.")).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Search trips" })).toHaveValue("nowhere");
    expect(within(screen.getByRole("group", { name: "Show" })).getByRole("button", { name: "Past" })).toHaveAttribute("aria-pressed", "true");
    expect(within(screen.getByRole("group", { name: "Year" })).getByRole("button", { name: "2019" })).toHaveAttribute("aria-pressed", "true");
    await user().click(screen.getByRole("button", { name: "Clear filters" }));
    expect(route.query).toBe("");
    expect(await screen.findByText("300 trips")).toBeInTheDocument();
  });

  it("filters by year and by upcoming or past, together with the traveller", async () => {
    serve();
    render(Trips);
    await screen.findByText("3 trips · 2 coming up");
    await user().click(within(screen.getByRole("group", { name: "Show" })).getByRole("button", { name: "Past" }));
    expect(route.query).toBe("when=past");
    expect(screen.queryByRole("list", { name: "Upcoming trips" })).toBeNull();
    expect(screen.getByText("Trip to Orlando")).toBeInTheDocument();
    await user().click(within(screen.getByRole("group", { name: "Show" })).getByRole("button", { name: "All" }));
    await user().click(within(screen.getByRole("group", { name: "Year" })).getByRole("button", { name: "2027" }));
    expect(route.query).toBe("year=2027");
    expect(screen.getByText("Trip to Auckland")).toBeInTheDocument();
    expect(screen.queryByText("Trip to Orlando")).toBeNull();
    await user().click(person("Jane Doe"));
    expect(route.query).toBe("who=1&year=2027");
    expect(screen.getByText("No trips match.")).toBeInTheDocument();
  });

  it("keeps the open trip in the address while a filter still shows it, and falls back to the first result when it doesn’t", async () => {
    route.query = "trip=2";
    location.hash = "#trips?trip=2";
    render(Trips);
    await screen.findByText("3 trips · 2 coming up");
    await user().click(within(screen.getByRole("group", { name: "Year" })).getByRole("button", { name: "2027" }));
    expect(route.query).toBe("year=2027&trip=2");
    await user().click(within(screen.getByRole("group", { name: "Show" })).getByRole("button", { name: "Past" }));
    expect(route.query).toBe("when=past&year=2027&trip=2");
    expect(screen.getByText("No trips match.")).toBeInTheDocument();
  });

  it("shows no filters before there is a trip to find", async () => {
    serve([]);
    render(Trips);
    await screen.findByText(/No trips yet/);
    expect(screen.queryByRole("searchbox")).toBeNull();
  });

  it("reads the Show control from the address and writes each choice back", async () => {
    route.query = "when=upcoming";
    render(Trips);
    await screen.findByRole("list", { name: "Upcoming trips" });
    const show = within(screen.getByRole("group", { name: "Show" }));
    expect(show.getAllByRole("button").map((b) => [b.textContent, b.getAttribute("aria-pressed")])).toEqual([["All", "false"], ["Upcoming", "true"], ["Past", "false"]]);
    expect(screen.queryByRole("list", { name: "Past trips" })).toBeNull();
    await user().click(show.getByRole("button", { name: "Past" }));
    expect(route.query).toBe("when=past");
    await user().click(show.getByRole("button", { name: "All" }));
    expect(route.query).toBe("");
  });

  it("clears the year by pressing it again, and reads it back from the address", async () => {
    route.query = "year=2027";
    render(Trips);
    await screen.findByRole("list", { name: "Upcoming trips" });
    const years = within(screen.getByRole("group", { name: "Year" }));
    expect(years.getAllByRole("button").map((b) => b.textContent)).toEqual(["2027", "2026"]);
    expect(years.getByRole("button", { name: "2027" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("Trip to Orlando")).toBeNull();
    await user().click(years.getByRole("button", { name: "2026" }));
    expect(route.query).toBe("year=2026");
    await user().click(years.getByRole("button", { name: "2026" }));
    expect(route.query).toBe("");
    expect(screen.getByText("Trip to Orlando")).toBeInTheDocument();
  });

  it("names each traveller, rings the chosen one and returns to everyone when it is pressed again", async () => {
    render(Trips);
    await screen.findByRole("list", { name: "Upcoming trips" });
    expect(within(travelling()).getAllByRole("button").map((b) => [b.getAttribute("aria-label"), b.getAttribute("data-initials")])).toEqual([["Jane Doe", "JD"], ["Sam Doe", "SD"]]);
    await user().click(person("Sam Doe"));
    expect(route.query).toBe("who=2");
    expect(person("Sam Doe")).toHaveClass("ring-primary");
    expect(person("Jane Doe")).toHaveClass("opacity-60");
    await user().click(person("Sam Doe"));
    expect(route.query).toBe("");
    expect(person("Jane Doe")).not.toHaveClass("opacity-60");
  });

  it("counts the trips and those coming up, and counts the matches while filtering", async () => {
    render(Trips);
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("3 trips · 2 coming up");
    expect(status).toHaveAttribute("aria-live", "polite");
    await user().click(person("Sam Doe"));
    expect(screen.getByRole("status")).toHaveTextContent("2 of 3 trips");
  });

  it("leaves out the coming-up count when nothing is coming up", async () => {
    serve([orlando]);
    render(Trips);
    expect(await screen.findByRole("status")).toHaveTextContent(/^1 trip$/);
  });

  it("hides the year and traveller controls when there is one year and one person", async () => {
    vi.mocked(api).mockImplementation(async (path) => (path === "/api/people" ? { people: [jane] } : { trips: [london, auckland].map((t) => ({ ...t, start_date: "2026-11-20", end_date: "2026-11-27" })) }));
    render(Trips);
    await screen.findByRole("list", { name: "Upcoming trips" });
    expect(screen.queryByRole("group", { name: "Year" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Travelling" })).toBeNull();
    expect(screen.getByRole("group", { name: "Show" })).toBeInTheDocument();
  });

  it("keeps a year that is in the address even when it is the only one", async () => {
    route.query = "year=2031";
    vi.mocked(api).mockImplementation(async (path) => (path === "/api/people" ? { people: [jane] } : { trips: [london] }));
    render(Trips);
    await screen.findByText("No trips match.");
    expect(within(screen.getByRole("group", { name: "Year" })).queryByRole("button", { name: "2031" })).toBeNull();
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeInTheDocument();
  });
});

describe("on a phone", () => {
  beforeEach(() => { viewport.phone = true; });

  it("moves the year and traveller controls into a Filters sheet that shows a dot while one is set", async () => {
    render(Trips);
    await screen.findByRole("list", { name: "Upcoming trips" });
    expect(screen.queryByRole("group", { name: "Year" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Travelling" })).toBeNull();
    expect(screen.queryByTestId("filters-dot")).toBeNull();
    const u = user();
    await u.click(screen.getByRole("button", { name: "Filters" }));
    const sheet = await screen.findByRole("dialog", { name: "Filters" });
    await u.click(within(within(sheet).getByRole("group", { name: "Year" })).getByRole("button", { name: "2027" }));
    expect(route.query).toBe("year=2027");
    await u.click(within(within(sheet).getByRole("group", { name: "Travelling" })).getByRole("button", { name: "Sam Doe" }));
    expect(route.query).toBe("who=2&year=2027");
    await u.click(within(sheet).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    document.body.style.pointerEvents = "";
    expect(screen.getByTestId("filters-dot")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Filters, in use" })).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Search trips" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Show" })).toBeInTheDocument();
  });

  it("offers adding a booking or a past trip from one button", async () => {
    render(Trips);
    const u = user();
    await u.click(await screen.findByRole("button", { name: "Add a booking" }));
    await u.click(within(screen.getByRole("group", { name: "Add a booking" })).getByRole("button", { name: "Add a past trip" }));
    expect(await screen.findByRole("button", { name: "Add booking" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add a booking" })).toBeNull();
  });
});

const stay = (id: number, name: string, start: string, end: string, extra: Partial<Trip> = {}) =>
  trip([segment({ id, trip_id: id, kind: "hotel", start_local: `${start}T15:00`, end_local: `${end}T11:00`, origin: null, destination: null })], { id, name, destination: "Portugal", ...extra });
const link = (name: string) => screen.getByRole("link", { name: new RegExp(name) });
const highlighted = () => screen.getAllByRole("link").filter((a) => a.className.includes("border-primary/35")).map((a) => a.textContent);

describe("ticket cards for upcoming trips", () => {
  it("writes the stub for a trip within a month, across months, in another year and without dates", async () => {
    serve([stay(1, "Same month", "2026-10-18", "2026-10-27"), stay(2, "Across months", "2026-10-30", "2026-11-02"), stay(3, "Another year", "2027-03-04", "2027-03-09"), stay(4, "Undated", "2026-12-01", "2026-12-02", { start_date: null, end_date: null })]);
    render(Trips);
    await screen.findByText("Same month");
    const stub = (name: string) => within(link(name)).getByTestId("stub");
    expect(stub("Same month")).toHaveTextContent("Oct 18 to 27");
    expect(stub("Across months")).toHaveTextContent("Oct 30 to Nov 2");
    expect(stub("Another year")).toHaveTextContent("Mar 4 2027");
    expect(stub("Undated")).toHaveTextContent("No dates");
    expect(link("Same month")).toHaveTextContent("Portugal · 9 nights");
  });

  it("says in the pill how soon a trip starts", async () => {
    serve([stay(1, "On now", "2026-10-03", "2026-10-09"), stay(2, "Today", "2026-10-05", "2026-10-08"), stay(3, "Tomorrow", "2026-10-06", "2026-10-08"), stay(4, "Soon", "2026-10-07", "2026-10-08")]);
    render(Trips);
    await screen.findByText("Soon");
    const pill = (name: string) => within(link(name)).getByTestId("pill").textContent;
    expect([pill("On now"), pill("Today"), pill("Tomorrow"), pill("Soon")]).toEqual(["Under way", "Today", "Tomorrow", "In 2 days"]);
  });

  it("highlights only the soonest trip", async () => {
    serve([stay(1, "Later", "2026-12-01", "2026-12-05"), stay(2, "Soonest", "2026-10-18", "2026-10-27"), stay(3, "Last", "2027-01-02", "2027-01-05")]);
    render(Trips);
    await screen.findByText("Soonest");
    expect(highlighted()).toHaveLength(1);
    expect(highlighted()[0]).toContain("Soonest");
  });

  it("shows the travellers as an avatar stack", async () => {
    render(Trips);
    const london = await screen.findByRole("link", { name: /Trip to London/ });
    expect(within(london).getByTestId("avatar-stack")).toHaveAttribute("aria-label", "Jane Doe, Sam Doe");
  });
});

describe("past trips by year", () => {
  const flown = (id: number, name: string, start: string, end: string, flights = 1) =>
    trip(Array.from({ length: flights }, (_, i) => segment({ id: id * 10 + i, trip_id: id, start_local: `${start}T09:00`, end_local: `${end}T10:00` })), { id, name, destination: "Nags Head, NC" });
  const history = () => [
    flown(1, "Beach", "2026-08-08", "2026-08-15", 2),
    flown(2, "Spring", "2026-03-02", "2026-03-05"),
    flown(3, "New Year", "2025-12-29", "2026-01-03"),
    flown(4, "Old", "2024-06-01", "2024-06-02"),
  ];

  it("groups by the year a trip started, newest first, with totals that leave out a part that is 0", async () => {
    serve(history());
    render(Trips);
    await screen.findByRole("list", { name: "Past trips in 2026" });
    expect(screen.getByRole("heading", { level: 3, name: "2026" }).parentElement).toHaveTextContent("2 trips · 10 nights · 3 flights");
    expect(screen.getByRole("heading", { level: 3, name: "2025" }).parentElement).toHaveTextContent("1 trip · 5 nights · 1 flight");
    expect(screen.getByRole("heading", { level: 3, name: "2024" }).parentElement).toHaveTextContent("1 trip · 1 night · 1 flight");
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual(["2026", "2025", "2024"]);
    expect(within(screen.getByRole("list", { name: "Past trips in 2025" })).getByRole("link")).toHaveTextContent("New Year");
    expect(within(screen.getByRole("list", { name: "Past trips in 2026" })).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual(["#trip/1", "#trip/2"]);
    expect(screen.getByText("Aug 8 – 15")).toBeInTheDocument();
    expect(screen.getByText("Dec 29 – Jan 3")).toBeInTheDocument();
  });

  it("leaves out flights when a year has none", async () => {
    serve([stay(1, "Stay", "2026-03-02", "2026-03-05")]);
    render(Trips);
    expect((await screen.findByRole("heading", { level: 3, name: "2026" })).parentElement).toHaveTextContent("1 trip · 3 nights");
    expect(screen.queryByText(/flight/)).toBeNull();
  });

  it("shows only the newest year on a phone, and reveals the next ones in turn", async () => {
    viewport.phone = true;
    serve(history());
    render(Trips);
    await screen.findByRole("list", { name: "Past trips in 2026" });
    expect(screen.queryByRole("list", { name: "Past trips in 2025" })).toBeNull();
    expect(screen.getByText("Aug 8 – 15 · Nags Head, NC")).toBeInTheDocument();
    await user().click(screen.getByRole("button", { name: "Show 2025" }));
    expect(screen.getByRole("list", { name: "Past trips in 2025" })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Past trips in 2024" })).toBeNull();
    await user().click(screen.getByRole("button", { name: "Show 2024" }));
    expect(screen.getByRole("list", { name: "Past trips in 2024" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Show/ })).toBeNull();
  });
});

describe("trip cards on a phone and in two panes", () => {
  it("shows the soonest trip as a full card with a header strip, and the rest as compact rows", async () => {
    viewport.phone = true;
    serve([stay(1, "Soonest", "2026-10-18", "2026-10-27"), stay(2, "Next", "2026-11-14", "2026-11-18")]);
    render(Trips);
    await screen.findByText("Soonest");
    expect(within(link("Soonest")).getByTestId("stub")).toHaveTextContent("OCT 18 – 27 In 13 days");
    expect(link("Next")).toHaveTextContent("4 nights · in 40 days");
    expect(within(link("Next")).queryByTestId("pill")).toBeNull();
  });

  it("uses the compact row in two panes and keeps the picked trip current with a highlighted border", async () => {
    panes.two = true;
    vi.mocked(api).mockImplementation(async (path) => {
      if (path === "/api/people") return { people: [jane, sam] };
      if (path === "/api/loyalty") return { loyalty: [], programs: {} };
      const one = /^\/api\/trips\/(\d+)$/.exec(path);
      if (one) return [london, auckland].find((t) => t.id === Number(one[1]));
      return { trips: [london, auckland] };
    });
    render(Trips);
    await screen.findByRole("region", { name: "Selected trip" });
    const first = link("Trip to London");
    expect(first).toHaveAttribute("aria-current", "true");
    expect(first.className).toContain("border-primary");
    expect(first.className).not.toContain("border-primary/35");
    expect(within(first).queryByTestId("pill")).toBeNull();
    expect(link("Trip to Auckland")).not.toHaveAttribute("aria-current");
  });
});
