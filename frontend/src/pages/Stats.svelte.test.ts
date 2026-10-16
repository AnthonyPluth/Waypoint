// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));

import { api } from "$lib/api";
import type { Person, Stats } from "$lib/api-types";
import { app, route } from "$lib/app.svelte";
import { viewport } from "$lib/phone.svelte";
import { state } from "../test/fixtures";
import Stats_ from "./Stats.svelte";

const jane: Person = { id: 1, display_name: "Jane Doe", first_name: "Jane", legal_name: null, aliases: [], member: true, links: [] };
const sam: Person = { id: 2, display_name: "Sam Doe", first_name: "Sam", legal_name: null, aliases: [], member: true, links: [] };

const none: Stats = {
  years: [2026, 2025], person: 1, year: null, distance_unit: "mi",
  flights: { count: 0, distance_km: 0, air_seconds: 0, airports: [], airlines: [], countries: [], routes: [], cabins: [], top_seat: null,
    seat_positions: { window: 0, aisle: 0, middle: 0, unknown: 0 }, longest: null, shortest: null, most_visited_airport: null, busiest_month: null,
    times_around_earth: 0, moon_fraction: 0 },
  stays: { nights: 0, chains: [], cities: [], countries: [], count: 0, average_nights: 0, hotels: [], cities_by_nights: [], longest: null, most_visited_hotel: null, most_visited_city: null, busiest_month: null, pins: [] }, cars: { days: 0, companies: [] }, cruises: { count: 0, nights: 0, sea_days: 0, ports: 0, lines: [] }, parking: { days: 0, bookings: 0, lots: [] }, places: { countries: [], cities: [], visits: [], points: [] },
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
  parking: { days: 9, bookings: 3, lots: [{ name: "Example Long-Term Lot", count: 2 }, { name: "Example Economy Lot", count: 1 }] },
  places: { countries: [{ name: "US", first_visit: "2025-05-02", visits: 3 }, { name: "GB", first_visit: "2026-06-01", visits: 1 }], cities: [], visits: [], points: [] },
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
afterEach(() => { viewport.phone = false; });
const traveller = async (name: string) => within(await screen.findByRole("group", { name: "Travelling" })).getByRole("button", { name });
const yearChip = async (year: string) => within(await screen.findByRole("group", { name: "Year" })).getByRole("button", { name: year });
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
    expect((await traveller("Jane Doe"))).toHaveAttribute("aria-pressed", "true");
    expect((await traveller("Sam Doe"))).toHaveAttribute("aria-pressed", "false");
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

  it("counts parking days and bookings and ranks the lots, only when there is parking", async () => {
    serve(() => full);
    render(Stats_);
    const totals = await screen.findByRole("region", { name: "Parking" });
    for (const [label, value] of [["Parking days", "9"], ["Parking bookings", "3"]]) {
      expect(within(within(totals).getByText(label).closest("div")!).getByText(value)).toBeInTheDocument();
    }
    const lots = within(totals).getByRole("heading", { name: "Lots" }).closest("section")!;
    expect(within(lots).getAllByRole("listitem")[0]).toHaveTextContent("1 Example Long-Term Lot 2 stays");
  });

  it("shows no parking section for someone who has not parked", async () => {
    serve(() => ({ ...full, parking: none.parking }));
    render(Stats_);
    await screen.findByRole("region", { name: "Flights" });
    expect(screen.queryByRole("region", { name: "Parking" })).toBeNull();
    expect(screen.queryByText("Parking days")).toBeNull();
    expect(screen.queryByText("Lots")).toBeNull();
  });

  it("is not empty for someone whose only finished trip was a parking booking", async () => {
    serve(() => ({ ...none, parking: full.parking }));
    render(Stats_);
    expect(await screen.findByRole("region", { name: "Parking" })).toBeInTheDocument();
    expect(screen.queryByTestId("stats-empty")).toBeNull();
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

  it("leads with the headline totals, left out where there is nothing to total", async () => {
    serve(() => full);
    render(Stats_);
    const headline = within(await screen.findByTestId("stats-headline"));
    for (const [label, value] of [["Flights flown", "12"], ["Distance flown", "32.3K mi"], ["Countries visited", "2"], ["Nights away", "9"]]) {
      expect(within(headline.getByText(label).closest("div")!).getByText(value)).toBeInTheDocument();
    }
  });

  it("has no headline row for a person with nothing finished", async () => {
    serve(() => none);
    render(Stats_);
    await screen.findByTestId("stats-empty");
    expect(screen.queryByTestId("stats-headline")).toBeNull();
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

  it("keeps a record's long value in its row, to the right of the label, and the label truncates", async () => {
    const longHotel = "Santa Cruz / Monterey Bay KOA Holiday Resort and Campground";
    serve(() => ({ ...full, stays: { ...full.stays, longest: { ...full.stays.longest!, hotel: longHotel } } }));
    render(Stats_);
    const records = (await screen.findByRole("heading", { name: "Hotel records" })).closest("div")!;
    const label = within(records).getByText("Longest stay");
    const row = label.closest("div")!;
    const value = row.querySelector("dd")!;
    expect(row).toHaveTextContent(`Longest stay${longHotel}, London4 nights`);
    expect(row.className).toContain("flex-nowrap");
    expect(label.className).toContain("truncate");
    expect(label.className).toContain("min-w-0");
    expect(value.className).toContain("max-w-[60%]");
    expect(value.className).toContain("shrink-0");
    expect(label.nextElementSibling).toBe(value);
  });

  it("truncates a long bar name and keeps its figure on one line on the right", async () => {
    const longCabin = "Premium Economy Extra Legroom Exit Row Seats on the Wing";
    serve(() => ({ ...full, flights: { ...full.flights, cabins: [{ name: longCabin, count: 8 }, { name: "Business", count: 2 }] } }));
    render(Stats_);
    const seats = (await screen.findByRole("heading", { name: "Seats" })).closest("section")!;
    const name = within(seats).getByText(longCabin);
    const figure = within(seats).getByText("80% · 8");
    expect(name.className).toContain("truncate");
    expect(name).toHaveAttribute("title", longCabin);
    expect(figure.className).toContain("shrink-0");
    expect(figure.className).toContain("whitespace-nowrap");
    expect(name.parentElement).toContainElement(figure);
    expect(seats.querySelector(".row")!.className).toContain("flex-nowrap");
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
    expect((await traveller("Sam Doe"))).toHaveAttribute("aria-pressed", "true");
    expect((await yearChip("2025"))).toHaveAttribute("aria-pressed", "true");
    await userEvent.click((await traveller("Sam Doe")));
    await waitFor(() => expect(route.query).toBe("who=all&year=2025"));
    await userEvent.click((await yearChip("2025")));
    await waitFor(() => expect(route.query).toBe("who=all"));
    await userEvent.click((await traveller("Jane Doe")));
    await waitFor(() => expect(route.query).toBe(""));
    expect(statsCalls().at(-1)).toBe("/api/stats?person=1&year=all");
  }, 15_000);

  it("lists the years that have trips, newest first", async () => {
    serve(() => full);
    render(Stats_);
    await screen.findByRole("region", { name: "Flights" });
    expect(within(screen.getByRole("group", { name: "Year" })).getAllByRole("button").map((b) => b.textContent)).toEqual(["2026", "2025"]);
  });

  it("never shows the previous choice's numbers as current while the next loads", async () => {
    let release: (s: Stats) => void = () => {};
    serve((path) => (path.includes("person=2") ? new Promise<Stats>((r) => { release = r; }) : full));
    render(Stats_);
    await screen.findByRole("region", { name: "Flights" });
    await userEvent.click((await traveller("Sam Doe")));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Flights" })).toBeNull());
    expect(screen.getByLabelText("Loading")).toBeInTheDocument();
    expect((await traveller("Sam Doe"))).toHaveAttribute("aria-pressed", "true");
    release({ ...full, person: 2, flights: { ...full.flights, count: 37 } });
    expect(await within(await screen.findByRole("region", { name: "Flights" })).findByText("37")).toBeInTheDocument();
  });

  it("answers a stale request's reply with nothing: only the latest choice is drawn", async () => {
    const waiting: ((s: Stats) => void)[] = [];
    serve(() => new Promise<Stats>((r) => { waiting.push(r); }));
    render(Stats_);
    await waitFor(() => expect(waiting).toHaveLength(1));
    await userEvent.click((await traveller("Sam Doe")));
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
    await userEvent.click((await traveller("Jane Doe")));
    expect(route.query).toBe("who=all");
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("region", { name: "Flights" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("drops the old numbers when the next load fails", async () => {
    serve((path) => (path.includes("year=2025") ? new Error("Offline") : full));
    render(Stats_);
    await screen.findByRole("region", { name: "Flights" });
    await userEvent.click((await yearChip("2025")));
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
    expect(within(empty).getByRole("link", { name: "Import past flights" })).toHaveAttribute("href", "#settings/backup");
    expect((await yearChip("2024"))).toHaveAttribute("aria-pressed", "true");
  });

  it("opens on everyone on your own machine, and falls back to Everyone when the names don't load", async () => {
    app.state = state({ person_id: null });
    vi.mocked(api).mockImplementation((async (path: string) => { if (path === "/api/people") throw new Error("nope"); return none; }) as never);
    render(Stats_);
    expect(await screen.findByTestId("stats-empty")).toHaveTextContent("Nothing finished yet.");
    expect(statsCalls()).toEqual(["/api/stats?person=all&year=all"]);
    expect(screen.queryByRole("group", { name: "Travelling" })).toBeNull();
  });

  it("keeps a record's value and a bar's figure on their row when a detail or a name is long", async () => {
    const longAirport = "Ted Stevens Anchorage International Airport and Cargo Terminal Complex";
    const longCabin = "Premium economy with a very long cabin name that goes on and on";
    serve(() => ({
      ...full,
      flights: { ...full.flights, airports: [{ ...airports[0], name: longAirport }, ...airports.slice(1)], cabins: [{ name: longCabin, count: 8 }, { name: "Business", count: 2 }] },
    }));
    render(Stats_);
    const records = (await screen.findByRole("heading", { name: "Flight records" })).closest("div")!;
    const airportRow = within(records).getByText("Most-visited airport").closest("div")!;
    expect(airportRow.className).toContain("flex-nowrap");
    expect(within(airportRow).getByText("Most-visited airport").className).toContain("truncate");
    expect(within(airportRow).getByText(longAirport).closest("dd")!.className).toContain("break-words");
    const seats = screen.getByRole("heading", { name: "Seats" }).closest("section")!;
    const cabin = within(seats).getByText(longCabin);
    expect(cabin.className).toContain("truncate");
    expect(cabin.getAttribute("title")).toBe(longCabin);
    expect(cabin.nextElementSibling!.className).toContain("whitespace-nowrap");
    expect(cabin.nextElementSibling).toHaveTextContent("80% · 8");
  });

  it("puts the counts for the selection in a polite status above the title", async () => {
    serve(() => full);
    route.query = "year=2026";
    render(Stats_);
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("2026 · 12 flights · 2 countries");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status.compareDocumentPosition(screen.getByRole("heading", { name: "Stats", level: 1 })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("says all time when no year is picked, and counts one flight and one country in the singular", async () => {
    serve(() => ({ ...full, flights: { ...full.flights, count: 1 }, places: { ...full.places, countries: [full.places.countries[0]] } }));
    render(Stats_);
    expect(await screen.findByRole("status")).toHaveTextContent("All time · 1 flight · 1 country");
  });

  it("leaves a count out of the status when there is nothing to count, and has no status for an empty selection", async () => {
    serve(() => ({ ...full, flights: none.flights, places: { ...full.places, countries: [] } }));
    render(Stats_);
    expect(await screen.findByRole("status")).toHaveTextContent(/^All time$/);
  });

  it("has no status for a selection with nothing finished", async () => {
    serve(() => none);
    render(Stats_);
    await screen.findByTestId("stats-empty");
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("writes the year to the address when a chip is pressed, reads it back, and clears it when pressed again", async () => {
    serve(() => full);
    render(Stats_);
    const chip = await yearChip("2025");
    expect(chip).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(chip);
    await waitFor(() => expect(route.query).toBe("year=2025"));
    await waitFor(() => expect(statsCalls().at(-1)).toBe("/api/stats?person=1&year=2025"));
    expect(await yearChip("2025")).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByRole("status")).toHaveTextContent(/^2025 · /);
    await userEvent.click(await yearChip("2025"));
    await waitFor(() => expect(route.query).toBe(""));
    expect(await yearChip("2025")).toHaveAttribute("aria-pressed", "false");
  }, 15_000);

  it("shows travellers as initials with their names, rings the selected one and clears it when pressed again", async () => {
    serve(() => full);
    render(Stats_);
    const sam = await traveller("Sam Doe");
    expect(sam).toHaveAttribute("data-initials", "SD");
    expect(sam.className).toContain("size-10");
    expect(sam.className).not.toContain("ring-primary");
    await userEvent.click(sam);
    await waitFor(() => expect(route.query).toBe("who=2"));
    await waitFor(() => expect(statsCalls().at(-1)).toBe("/api/stats?person=2&year=all"));
    expect((await traveller("Sam Doe")).className).toContain("ring-2 ring-primary");
    expect(await traveller("Jane Doe")).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(await traveller("Sam Doe"));
    await waitFor(() => expect(route.query).toBe("who=all"));
    await waitFor(() => expect(statsCalls().at(-1)).toBe("/api/stats?person=all&year=all"));
    expect(await traveller("Sam Doe")).toHaveAttribute("aria-pressed", "false");
  }, 15_000);

  it("has no traveller row for a household of one, and no year row when there is a single year and none picked", async () => {
    vi.mocked(api).mockImplementation((async (path: string) => (path === "/api/people" ? { people: [jane] } : { ...full, years: [2026] })) as never);
    render(Stats_);
    await screen.findByRole("region", { name: "Flights" });
    expect(screen.queryByRole("group", { name: "Travelling" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Year" })).toBeNull();
  });

  it("gives each section a kind tile in its header, and none to the places", async () => {
    serve(() => full);
    render(Stats_);
    await screen.findByRole("region", { name: "Flights" });
    for (const [name, kind] of [["Flights", "flight"], ["Hotels", "hotel"], ["Cars", "car"], ["Parking", "parking"], ["Cruises", "cruise"]]) {
      const section = screen.getByRole("region", { name });
      const tile = section.querySelector(`[data-tile="${kind}"]`)!;
      expect(tile).not.toBeNull();
      expect(tile.nextElementSibling).toBe(within(section).getByRole("heading", { name, level: 2 }));
    }
    expect(screen.getByRole("region", { name: "Where you’ve been" }).querySelector("[data-tile]")).toBeNull();
  });

  it("sets the tile figures in the mono face", async () => {
    serve(() => full);
    render(Stats_);
    const flights = await screen.findByRole("region", { name: "Flights" });
    expect(within(flights).getByText("32,311 mi").className).toContain("mono");
    expect(within(await screen.findByTestId("stats-headline")).getByText("32.3K mi").className).toContain("mono");
  });

  it("draws the tiles on the ticket cards' surface", async () => {
    serve(() => full);
    render(Stats_);
    const tile = (await screen.findByRole("region", { name: "Cars" })).querySelector("dl > div")!;
    for (const name of ["rounded-2xl", "border-border", "bg-card", "shadow-card"]) expect(tile.className).toContain(name);
  });
});

describe("on a phone", () => {
  beforeEach(() => { viewport.phone = true; });

  it("moves the year and traveller controls into a Filters sheet that shows a dot while one is set", async () => {
    serve(() => full);
    render(Stats_);
    await screen.findByRole("region", { name: "Flights" });
    expect(screen.queryByRole("group", { name: "Year" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Travelling" })).toBeNull();
    expect(screen.queryByTestId("filters-dot")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Filters" }));
    const sheet = await screen.findByRole("dialog", { name: "Filters" });
    await userEvent.click(within(within(sheet).getByRole("group", { name: "Year" })).getByRole("button", { name: "2025" }));
    await waitFor(() => expect(route.query).toBe("year=2025"));
    await userEvent.click(within(within(sheet).getByRole("group", { name: "Travelling" })).getByRole("button", { name: "Sam Doe" }));
    await waitFor(() => expect(route.query).toBe("who=2&year=2025"));
    await userEvent.click(within(sheet).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    document.body.style.pointerEvents = "";
    expect(screen.getByTestId("filters-dot")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Filters, in use" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/^2025 · /);
  }, 15_000);
});
