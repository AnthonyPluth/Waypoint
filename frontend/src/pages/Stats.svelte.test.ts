// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));

import { api } from "$lib/api";
import type { Person, Stats } from "$lib/api-types";
import { app, route } from "$lib/app.svelte";
import { state } from "../test/fixtures";
import Stats_ from "./Stats.svelte";

const jane: Person = { id: 1, display_name: "Jane Doe", first_name: "Jane", legal_name: null, aliases: [], member: true };
const sam: Person = { id: 2, display_name: "Sam Doe", first_name: "Sam", legal_name: null, aliases: [], member: true };

const none: Stats = {
  years: [2026, 2025], person: 1, year: null, distance_unit: "mi",
  flights: { count: 0, distance_km: 0, air_seconds: 0, airports: [], airlines: [], countries: [], routes: [], cabins: [], top_seat: null,
    seat_positions: { window: 0, aisle: 0, middle: 0, unknown: 0 }, longest: null, shortest: null, most_visited_airport: null, busiest_month: null,
    times_around_earth: 0, moon_fraction: 0 },
  stays: { nights: 0, chains: [], cities: [], countries: [] }, cars: { days: 0, companies: [] }, places: { countries: [], cities: [] },
};
const airports = ["JFK", "LHR", "MCO", "SFO", "CDG", "AKL", "LAX"].map((code, i) => ({ code, name: `${code} Airport`, city: `City ${i}`, country: "US", visits: 10 - i, latitude: 1, longitude: 2 }));
const full: Stats = {
  ...none,
  flights: {
    ...none.flights, count: 12, distance_km: 52000, air_seconds: 3 * 86400 + 4 * 3600, airports,
    airlines: [{ code: "DL", name: "Delta Air Lines", flights: 7 }, { code: "AA", name: "American Airlines", flights: 5 }],
    routes: [{ a: "JFK", b: "LHR", flights: 4, distance_km: 5540, a_latitude: 1, a_longitude: 1, b_latitude: 1, b_longitude: 1 },
      ...["MCO", "SFO", "CDG", "AKL", "LAX"].map((b) => ({ a: "JFK", b, flights: 1, distance_km: 1000, a_latitude: 1, a_longitude: 1, b_latitude: 1, b_longitude: 1 }))],
    cabins: [{ name: "Economy", count: 8 }, { name: "Business", count: 2 }], top_seat: "12A",
    seat_positions: { window: 6, aisle: 3, middle: 1, unknown: 2 },
    longest: { origin: "JFK", destination: "AKL", distance_km: 14200, start_local: "2026-03-01T22:15", flight_number: "NZ5" },
    shortest: { origin: "JFK", destination: "EWR", distance_km: 28, start_local: "2025-05-02T08:00", flight_number: null },
    most_visited_airport: "JFK", busiest_month: "2026-06", times_around_earth: 1.3, moon_fraction: 0.1353,
  },
  stays: { nights: 9, chains: [{ name: "Hilton", count: 2 }], cities: [], countries: [] }, cars: { days: 3, companies: [{ name: "Hertz", count: 1 }] },
  places: { countries: [{ name: "US", first_visit: "2025-05-02", visits: 3 }, { name: "GB", first_visit: "2026-06-01", visits: 1 }], cities: [] },
};

/** Serves the people and, for each stats request, what `stats` makes of its address. */
function serve(stats: (path: string) => Stats | Error | Promise<Stats>) {
  vi.mocked(api).mockImplementation((async (path: string) => {
    if (path === "/api/people") return { people: [jane, sam] };
    const r = await stats(path);
    if (r instanceof Error) throw r;
    return r;
  }) as never);
}

beforeEach(() => {
  vi.mocked(api).mockReset();
  app.state = state({ person_id: 1 });
  route.query = ""; location.hash = "#stats";
});
const statsCalls = () => vi.mocked(api).mock.calls.map((c) => c[0]).filter((p) => String(p).startsWith("/api/stats"));

describe("Stats", () => {
  it("opens on your own numbers for all time, with the totals in the household's unit", async () => {
    serve(() => full);
    render(Stats_);
    const totals = await screen.findByRole("region", { name: "Totals" });
    expect(statsCalls()).toEqual(["/api/stats?person=1&year=all"]);
    expect(within(totals).getByText("12")).toBeInTheDocument();
    expect(within(totals).getByText("32,311 mi")).toBeInTheDocument();
    expect(within(totals).getByText("3 d 4 h")).toBeInTheDocument();
    expect(within(totals).getByText("1.3× around the Earth")).toBeInTheDocument();
    expect(within(totals).getByText("14% of the way to the Moon")).toBeInTheDocument();
    expect(within(totals).getByText("9")).toBeInTheDocument();   // nights away
    expect(screen.getByRole("combobox", { name: "Who" })).toHaveValue("1");
    expect(screen.getByRole("option", { name: "Jane Doe (you)" })).toBeInTheDocument();
    expect(screen.getByTestId("stats-map-slot")).toBeInTheDocument();
  });

  it("uses kilometres when the household does", async () => {
    serve(() => ({ ...full, distance_unit: "km" }));
    render(Stats_);
    expect(await screen.findByText("52,000 km")).toBeInTheDocument();
  });

  it("shows the top five of each list, and all of it on Show all", async () => {
    serve(() => full);
    render(Stats_);
    const routes = await screen.findByRole("region", { name: "Routes" });
    expect(within(routes).getAllByRole("listitem")).toHaveLength(5);
    await userEvent.click(within(routes).getByRole("button", { name: "Show all 6" }));
    expect(within(routes).getAllByRole("listitem")).toHaveLength(6);
    await userEvent.click(within(routes).getByRole("button", { name: "Show fewer" }));
    expect(within(routes).getAllByRole("listitem")).toHaveLength(5);
    const airlines = screen.getByRole("region", { name: "Airlines" });
    expect(within(airlines).queryByRole("button")).toBeNull();
    expect(within(airlines).getByText("Delta Air Lines")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Countries" })).getByText("United States")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Hotel chains" })).toHaveTextContent("Hilton");
    expect(screen.getByRole("region", { name: "Rental companies" })).toHaveTextContent("Hertz");
  });

  it("shows the records and the seats", async () => {
    serve(() => full);
    render(Stats_);
    const records = (await screen.findByRole("heading", { name: "Records" })).closest("section")!;
    expect(records).toHaveTextContent("Longest flightJFK – AKL8,823 mi · Mar 1, 2026");
    expect(records).toHaveTextContent("Shortest flightJFK – EWR17 mi · May 2, 2025");
    expect(records).toHaveTextContent("Most-visited airportJFKJFK Airport");
    expect(records).toHaveTextContent("Busiest monthJune 2026");
    const seats = screen.getByRole("heading", { name: "Seats" }).closest("section")!;
    expect(seats).toHaveTextContent("Economy80% · 8");
    expect(seats).toHaveTextContent("Window60% · 6");
    expect(seats).toHaveTextContent("Top seat 12A");
  });

  it("keeps the choice in the address, and a linked address opens on it", async () => {
    serve(() => full);
    route.query = "who=2&year=2025";
    render(Stats_);
    await screen.findByRole("region", { name: "Totals" });
    expect(statsCalls()).toEqual(["/api/stats?person=2&year=2025"]);
    expect(screen.getByRole("combobox", { name: "Who" })).toHaveValue("2");
    expect(screen.getByRole("combobox", { name: "When" })).toHaveValue("2025");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Who" }), "all");
    await waitFor(() => expect(route.query).toBe("who=all&year=2025"));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "When" }), "All time");
    await waitFor(() => expect(route.query).toBe("who=all"));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Who" }), "Jane Doe (you)");
    await waitFor(() => expect(route.query).toBe(""));
    expect(statsCalls().at(-1)).toBe("/api/stats?person=1&year=all");
  });

  it("lists the years that have trips, newest first", async () => {
    serve(() => full);
    render(Stats_);
    await screen.findByRole("region", { name: "Totals" });
    expect(within(screen.getByRole("combobox", { name: "When" })).getAllByRole("option").map((o) => o.textContent)).toEqual(["All time", "2026", "2025"]);
  });

  it("never shows the previous choice's numbers as current while the next loads", async () => {
    let release: (s: Stats) => void = () => {};
    serve((path) => (path.includes("person=2") ? new Promise<Stats>((r) => { release = r; }) : full));
    render(Stats_);
    await screen.findByRole("region", { name: "Totals" });
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Who" }), "Sam Doe");
    await waitFor(() => expect(screen.queryByRole("region", { name: "Totals" })).toBeNull());
    expect(screen.getByLabelText("Loading")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Who" })).toHaveValue("2");   // the pickers stay usable
    release({ ...full, person: 2, flights: { ...full.flights, count: 3 } });
    expect(await within(await screen.findByRole("region", { name: "Totals" })).findByText("3")).toBeInTheDocument();
  });

  it("answers a stale request's reply with nothing: only the latest choice is drawn", async () => {
    const waiting: ((s: Stats) => void)[] = [];
    serve(() => new Promise<Stats>((r) => { waiting.push(r); }));
    render(Stats_);
    await waitFor(() => expect(waiting).toHaveLength(1));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Who" }), "Sam Doe");
    await waitFor(() => expect(waiting).toHaveLength(2));
    waiting[1]({ ...full, person: 2, flights: { ...full.flights, count: 21 } });
    await within(await screen.findByRole("region", { name: "Totals" })).findByText("21");
    waiting[0]({ ...full, flights: { ...full.flights, count: 99 } });
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText("99")).toBeNull();
  });

  it("says a load failed, keeps the pickers working and tries again", async () => {
    let fail = true;
    serve(() => (fail ? new Error("Offline") : full));
    render(Stats_);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn’t load the stats: Offline");
    expect(screen.queryByRole("region", { name: "Totals" })).toBeNull();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "When" }), "All time");   // still usable
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("region", { name: "Totals" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("drops the old numbers when the next load fails", async () => {
    serve((path) => (path.includes("year=2025") ? new Error("Offline") : full));
    render(Stats_);
    await screen.findByRole("region", { name: "Totals" });
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "When" }), "2025");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Totals" })).toBeNull();
  });

  it("says when a person or year has nothing finished, with links to add a trip or import flights", async () => {
    serve(() => none);
    route.query = "year=2024";
    render(Stats_);
    const empty = await screen.findByTestId("stats-empty");
    expect(empty).toHaveTextContent("Nothing finished for Jane Doe in 2024.");
    expect(within(empty).getByRole("link", { name: "Add a trip" })).toHaveAttribute("href", "#trips");
    expect(within(empty).getByRole("link", { name: "Import past flights" })).toHaveAttribute("href", "#settings");
    expect(screen.getByRole("option", { name: "2024" })).toBeInTheDocument();   // the chosen year stays in the picker
  });

  it("opens on everyone on your own machine, and falls back to Everyone when the names don't load", async () => {
    app.state = state({ person_id: null });
    vi.mocked(api).mockImplementation((async (path: string) => { if (path === "/api/people") throw new Error("nope"); return none; }) as never);
    render(Stats_);
    expect(await screen.findByTestId("stats-empty")).toHaveTextContent("Nothing finished yet.");
    expect(statsCalls()).toEqual(["/api/stats?person=all&year=all"]);
    expect(screen.getByRole("combobox", { name: "Who" })).toHaveValue("all");
  });
});
