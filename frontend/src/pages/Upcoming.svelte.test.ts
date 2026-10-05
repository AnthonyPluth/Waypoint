// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import { segment, trip } from "../test/fixtures";
import Upcoming from "./Upcoming.svelte";

const NY = "America/New_York", LON = "Europe/London";
const outbound = segment({ id: 1 });
const stay = segment({ id: 2, kind: "hotel", provider: "Marriott", origin: "Harbour Hotel", destination: null, start_local: "2026-11-21T15:00", start_zone: LON,
  end_local: "2026-11-27T10:00", end_zone: LON, confirmation: "H88231", details: { address: "1 Quay Street, London" } });
const home = segment({ id: 3, origin: "LHR", destination: "JFK", start_local: "2026-11-27T11:30", start_zone: LON, end_local: "2026-11-27T14:35", end_zone: NY });
const london = trip([outbound, stay, home]);

beforeEach(() => { vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] }); vi.mocked(api).mockReset(); });
afterEach(() => vi.useRealTimers());

const serve = (trips: unknown[]) => vi.mocked(api).mockResolvedValue({ trips });
const at = (iso: string) => vi.setSystemTime(new Date(iso));

describe("Upcoming", () => {
  it("says there are no trips yet, without making any up", async () => {
    serve([]);
    render(Upcoming);
    expect(screen.getByRole("heading", { name: "Upcoming" })).toBeInTheDocument();
    expect(await screen.findByText(/No trips yet — they’ll appear here once Waypoint can read your confirmation emails, or when you add one\./)).toBeInTheDocument();
  });

  it("leads with the next segment: countdown, flight, departure time, terminal, and a code to tap and copy", async () => {
    at("2026-11-20T09:00:00-05:00");   // 10 hours before the 7:00 PM departure
    serve([london]);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR" })).closest("section")!;
    expect(within(card).getByText("Next up")).toBeInTheDocument();
    expect(within(card).getByText("Departs in 10 h")).toBeInTheDocument();
    expect(within(card).getByText("American Airlines AA 101 · Terminal 8")).toBeInTheDocument();
    expect(within(card).getByText("7:00 PM")).toBeInTheDocument();
    expect(within(card).getByText("8")).toBeInTheDocument();
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(within(card).getByRole("button", { name: "Copy confirmation code KQ7M2X" }));
    expect(await navigator.clipboard.readText()).toBe("KQ7M2X");
  });

  it("says it's departing now, not \"in now\", in the last minute", async () => {
    at("2026-11-20T18:59:40-05:00");
    serve([london]);
    render(Upcoming);
    expect(await screen.findByText("Departing now")).toBeInTheDocument();
  });

  it("calls a flight in the air under way, and counts down to landing", async () => {
    at("2026-11-21T02:00:00-05:00");   // 7:00 AM in London: ten minutes to land
    serve([london]);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR" })).closest("section")!;
    expect(within(card).getByText("Under way")).toBeInTheDocument();
    expect(within(card).getByText("Arrives in 10 min")).toBeInTheDocument();
  });

  it("leads with a hotel's address and check-in time once the flight is behind", async () => {
    at("2026-11-21T08:00:00Z");   // landed; the hotel is the next thing
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

  it("shows a time at its place and, in brackets, yours when your zone differs", async () => {
    at("2026-11-20T09:00:00-05:00");
    serve([london]);
    render(Upcoming);
    const card = (await screen.findByRole("heading", { name: "JFK → LHR" })).closest("section")!;
    // The arrival at 7:10 AM in London reads the same wherever this runs; the bracket is there only if the zone differs.
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
});
