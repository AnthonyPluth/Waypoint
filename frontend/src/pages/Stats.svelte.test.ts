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

const jane: Person = { id: 1, display_name: "Jane Doe", first_name: "Jane", legal_name: null, aliases: [], member: true, links: [] };
const sam: Person = { id: 2, display_name: "Sam Doe", first_name: "Sam", legal_name: null, aliases: [], member: true, links: [] };

const none: Stats = {
  years: [2026, 2025], person: 1, year: null, distance_unit: "mi",
  flights: { count: 0, distance_km: 0, air_seconds: 0, airports: [], airlines: [], countries: [], routes: [], cabins: [], top_seat: null,
    seat_positions: { window: 0, aisle: 0, middle: 0, unknown: 0 }, longest: null, shortest: null, most_visited_airport: null, busiest_month: null,
    times_around_earth: 0, moon_fraction: 0 },
  stays: { nights: 0, chains: [], cities: [], countries: [], count: 0, average_nights: 0, hotels: [], cities_by_nights: [], longest: null, most_visited_hotel: null, most_visited_city: null, busiest_month: null, pins: [] }, cars: { days: 0, companies: [] }, cruises: { count: 0, nights: 0, sea_days: 0, ports: 0, lines: [] }, places: { countries: [], cities: [] },
};
const airports = ["JFK", "LHR", "MCO", "SFO", "CDG", "AKL", "LAX"].map((code, i) => ({ code, name: `${code} Airport`, city: `City ${i}`, country: "US", visits: 10 - i, latitude: 1, longitude: 2 }));
const full: Stats = {
  ...none,
  flights: {
    ...none.flights, count: 12, distance_km: 52000, air_seconds: 3 * 86400 + 4 * 3600, airports,
    airlines: [{ code: "DL", name: "Delta Air Lines", flights: 7 }, { code: "AA", name: "American Airlines", flights: 5 }],
    routes: [{ a: "JFK", b: "LHR", flights: 4, distance_km: 5540, a_latitude: 1, a_longitude: 1, b_latitude: 1, b_longitude: 1, trips: [] },
      ...["MCO", "SFO", "CDG", "AKL", "LAX"].map((b) => ({ a: "JFK", b, flights: 1, distance_km: 1000, a_latitude: 1, a_longitude: 1, b_latitude: 1, b_longitude: 1, trips: [] }))],
    cabins: [{ name: "Economy", count: 8 }, { name: "Business", count: 2 }], top_seat: "12A",
    seat_positions: { window: 6, aisle: 3, middle: 1, unknown: 2 },
    longest: { origin: "JFK", destination: "AKL", distance_km: 14200, start_local: "2026-03-01T22:15", flight_number: "NZ5" },
    shortest: { origin: "JFK", destination: "EWR", distance_km: 28, start_local: "2025-05-02T08:00", flight_number: null },
    most_visited_airport: "JFK", busiest_month: "2026-06", times_around_earth: 1.3, moon_fraction: 0.1353,
  },
  stays: { nights: 9, chains: [{ name: "Hilton", count: 2 }], cities: [], countries: [], count: 4, average_nights: 3.5,
    hotels: [{ name: "Harbour Hotel", stays: 2, nights: 6 }, { name: "Quay Inn", stays: 1, nights: 4 }],
    cities_by_nights: [{ name: "London", stays: 2, nights: 6 }, { name: "Paris", stays: 1, nights: 4 }],
    longest: { hotel: "Harbour Hotel", city: "London", nights: 4, start_local: "2026-06-02T15:00" },
    most_visited_hotel: { name: "Harbour Hotel", stays: 2, nights: 6 }, most_visited_city: { name: "London", stays: 2, nights: 6 }, busiest_month: "2026-06", pins: [] }, cars: { days: 3, companies: [{ name: "Hertz", count: 1 }] }, cruises: { count: 2, nights: 10, sea_days: 4, ports: 5, lines: [{ name: "Example Cruise Line", count: 2 }] },
  places: { countries: [{ name: "US", first_visit: "2025-05-02", visits: 3 }, { name: "GB", first_visit: "2026-06-01", visits: 1 }], cities: [] },
};

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
    const totals = await screen.findByRole("region", { name: "Flights" });
    expect(statsCalls()).toEqual(["/api/stats?person=1&year=all"]);
    expect(within(totals).getByText("12")).toBeInTheDocument();
    expect(within(totals).getByText("32,311 mi")).toBeInTheDocument();
    expect(within(totals).getByText("3 d 4 h")).toBeInTheDocument();
    expect(within(totals).getByText("1.3× around the Earth")).toBeInTheDocument();
    expect(within(totals).getByText("14% of the way to the Moon")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Hotels" })).getByText("9")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Who" })).toHaveValue("1");
    expect(screen.getByRole("option", { name: "Jane Doe (you)" })).toBeInTheDocument();
    expect(screen.getByTestId("stats-map-slot")).toBeInTheDocument();
  });

  it("has a section each for flights, hotels, cars and cruises, with its own lists", async () => {
    serve(() => full);
    render(Stats_);
    for (const name of ["Where you’ve been", "Flights", "Hotels", "Cars", "Cruises"]) expect(await screen.findByRole("region", { name })).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Flights" })).getByText("Routes")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Hotels" })).getByText("Hotel chains")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Cars" })).getByText("Rental companies")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Cruises" })).getByText("Cruise lines")).toBeInTheDocument();
  });

  it("leaves out the section of anything not done, so someone who only stayed has just the hotels", async () => {
    serve(() => ({ ...full, flights: none.flights, cars: none.cars, cruises: none.cruises }));
    render(Stats_);
    await screen.findByRole("region", { name: "Hotels" });
    for (const name of ["Flights", "Cars", "Cruises"]) expect(screen.queryByRole("region", { name })).toBeNull();
  });

  it("shows just the Cars section for someone who only rented a car", async () => {
    serve(() => ({ ...full, flights: none.flights, stays: none.stays, cruises: none.cruises }));
    render(Stats_);
    const cars = await screen.findByRole("region", { name: "Cars" });
    expect(within(cars).getByText("Rental days")).toBeInTheDocument();
    for (const name of ["Flights", "Hotels", "Cruises"]) expect(screen.queryByRole("region", { name })).toBeNull();
  });

  it("counts cruises, nights aboard, sea days and ports, and lists the lines, only when there are cruises", async () => {
    serve(() => full);
    render(Stats_);
    const totals = await screen.findByRole("region", { name: "Cruises" });
    for (const [label, value] of [["Cruises taken", "2"], ["Nights at sea", "10"], ["Sea days", "4"], ["Ports of call", "5"]]) {
      const tile = within(totals).getByText(label).closest("div")!;
      expect(within(tile).getByText(value)).toBeInTheDocument();
    }
    expect(screen.getByText("Cruise lines")).toBeInTheDocument();
    expect(screen.getByText("2 cruises")).toBeInTheDocument();
  });

  it("shows the stay totals, records and the hotel and city lists, and none of them without stays", async () => {
    serve(() => full);
    render(Stats_);
    const totals = await screen.findByRole("region", { name: "Hotels" });
    for (const [label, value] of [["Stays", "4"], ["Average stay", "3.5 nights"], ["Different hotels", "2"]]) {
      expect(within(within(totals).getByText(label).closest("div")!).getByText(value)).toBeInTheDocument();
    }
    const records = screen.getByRole("heading", { name: "Hotel records" }).closest("div")!;
    expect(within(records).getByText("Longest stay").closest("div")).toHaveTextContent("Harbour Hotel, London4 nights");
    expect(within(records).getByText("Most-visited hotel").closest("div")).toHaveTextContent("Harbour Hotel2 stays · 6 nights");
    expect(within(records).getByText("Most-visited city").closest("div")).toHaveTextContent("London2 stays · 6 nights");
    expect(within(records).getByText("Most nights in a month").closest("div")).toHaveTextContent("June 2026");
    const hotels = screen.getByRole("heading", { name: "Hotels stayed at" }).closest("section")!;
    expect(within(hotels).getAllByRole("listitem")[0]).toHaveTextContent("1 Harbour Hotel2 stays 6 nights");
    expect(screen.getByRole("heading", { name: "Cities stayed in" })).toBeInTheDocument();
  });

  it("shows no stay tiles, hotel or city lists for someone without stays", async () => {
    serve(() => ({ ...full, stays: none.stays }));
    render(Stats_);
    await screen.findByRole("region", { name: "Flights" });
    expect(screen.queryByText("Average stay")).toBeNull();
    expect(screen.queryByRole("region", { name: "Hotels" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Hotels" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Cities stayed in" })).toBeNull();
    expect(screen.queryByText("Longest stay")).toBeNull();
  });

  it("shows no cruise tiles for someone who has not been on one", async () => {
    serve(() => ({ ...full, cruises: none.cruises }));
    render(Stats_);
    await screen.findByRole("region", { name: "Flights" });
    expect(screen.queryByText("Sea days")).toBeNull();
    expect(screen.queryByRole("region", { name: "Cruises" })).toBeNull();
    expect(screen.queryByText("Cruise lines")).toBeNull();
  });

  it("offers the year in review for a past year, and not for all time", async () => {
    serve(() => full);
    route.query = "year=2024"; location.hash = "#stats?year=2024";
    render(Stats_);
    await userEvent.click(await screen.findByRole("button", { name: "See your 2024 in review" }));
    expect(await screen.findByTestId("year-in-review")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByTestId("year-in-review")).toBeNull();
  });

  it("has no year in review for all time", async () => {
    serve(() => full);
    render(Stats_);
    await screen.findByRole("region", { name: "Flights" });
    expect(screen.queryByRole("button", { name: /in review/ })).toBeNull();
  });

  it("draws the map of the airports and routes in its slot", async () => {
    serve(() => full);
    render(Stats_);
    const slot = await screen.findByTestId("stats-map-slot");
    await waitFor(() => expect(slot.querySelectorAll("[data-dot]")).toHaveLength(airports.length));
    expect(within(slot).getByRole("heading", { name: "Where you’ve been" })).toBeInTheDocument();
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
    const records = (await screen.findByRole("heading", { name: "Flight records" })).closest("div")!;
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
    await screen.findByRole("region", { name: "Flights" });
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
  }, 15_000);

  it("lists the years that have trips, newest first", async () => {
    serve(() => full);
    render(Stats_);
    await screen.findByRole("region", { name: "Flights" });
    expect(within(screen.getByRole("combobox", { name: "When" })).getAllByRole("option").map((o) => o.textContent)).toEqual(["All time", "2026", "2025"]);
  });

  it("never shows the previous choice's numbers as current while the next loads", async () => {
    let release: (s: Stats) => void = () => {};
    serve((path) => (path.includes("person=2") ? new Promise<Stats>((r) => { release = r; }) : full));
    render(Stats_);
    await screen.findByRole("region", { name: "Flights" });
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Who" }), "Sam Doe");
    await waitFor(() => expect(screen.queryByRole("region", { name: "Flights" })).toBeNull());
    expect(screen.getByLabelText("Loading")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Who" })).toHaveValue("2");
    release({ ...full, person: 2, flights: { ...full.flights, count: 37 } });
    expect(await within(await screen.findByRole("region", { name: "Flights" })).findByText("37")).toBeInTheDocument();
  });

  it("answers a stale request's reply with nothing: only the latest choice is drawn", async () => {
    const waiting: ((s: Stats) => void)[] = [];
    serve(() => new Promise<Stats>((r) => { waiting.push(r); }));
    render(Stats_);
    await waitFor(() => expect(waiting).toHaveLength(1));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Who" }), "Sam Doe");
    await waitFor(() => expect(waiting).toHaveLength(2));
    waiting[1]({ ...full, person: 2, flights: { ...full.flights, count: 21 } });
    await within(await screen.findByRole("region", { name: "Flights" })).findByText("21");
    waiting[0]({ ...full, flights: { ...full.flights, count: 99 } });
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText("99")).toBeNull();
  });

  it("says a load failed, keeps the pickers working and tries again", async () => {
    let fail = true;
    serve(() => (fail ? new Error("Offline") : full));
    render(Stats_);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn’t load the stats: Offline");
    expect(screen.queryByRole("region", { name: "Flights" })).toBeNull();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "When" }), "All time");
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("region", { name: "Flights" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("drops the old numbers when the next load fails", async () => {
    serve((path) => (path.includes("year=2025") ? new Error("Offline") : full));
    render(Stats_);
    await screen.findByRole("region", { name: "Flights" });
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "When" }), "2025");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Flights" })).toBeNull();
  });

  it("says when a person or year has nothing finished, with links to add a trip or import flights", async () => {
    serve(() => none);
    route.query = "year=2024";
    render(Stats_);
    const empty = await screen.findByTestId("stats-empty");
    expect(empty).toHaveTextContent("Nothing finished for Jane Doe in 2024.");
    expect(within(empty).getByRole("link", { name: "Add a trip" })).toHaveAttribute("href", "#trips");
    expect(within(empty).getByRole("link", { name: "Import past flights" })).toHaveAttribute("href", "#settings/travel");
    expect(screen.getByRole("option", { name: "2024" })).toBeInTheDocument();
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
