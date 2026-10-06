// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { Person } from "$lib/api-types";
import { route } from "$lib/app.svelte";
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
afterEach(() => vi.useRealTimers());
const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

describe("Trips", () => {
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
