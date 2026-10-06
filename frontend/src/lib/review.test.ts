import { describe, expect, it } from "vitest";
import type { Stats } from "./api-types";
import { cardSvg, firstName, mapSvg, outlinesFor, reviewFacts, reviewOffered } from "./review";
import type { Country } from "./map";

// Canary values sit where the stats carry personal or detailed data; none may reach the card.
const CANARIES = ["Zelda Quimby", "Quimby", "ZQ7X9K", "Hotel Canarios", "Canario Suites", "ZX 9931", "2026-03-14", "14 Mar", "March 14", "Canary City", "Canary Airways", "FF-123456"];

const stats = (year: number | null = 2026): Stats => ({
  years: [2026, 2025], person: 1, year, distance_unit: "mi",
  flights: {
    count: 12, distance_km: 52000, air_seconds: 3 * 86400, countries: [], cabins: [], top_seat: "12A", seat_positions: { window: 1, aisle: 1, middle: 1, unknown: 0 },
    airports: [
      { code: "JFK", name: "Canary Airport ZQ7X9K", city: "Canary City", country: "US", visits: 6, latitude: 40.64, longitude: -73.78 },
      { code: "LHR", name: "Heathrow", city: "London", country: "GB", visits: 4, latitude: 51.47, longitude: -0.45 },
    ],
    airlines: [{ code: "ZZ", name: "Canary Airways", flights: 12 }],
    routes: [{ a: "JFK", b: "LHR", flights: 4, distance_km: 5540, a_latitude: 40.64, a_longitude: -73.78, b_latitude: 51.47, b_longitude: -0.45, trips: [] }],
    longest: { origin: "JFK", destination: "LHR", distance_km: 5540, start_local: "2026-03-14T09:00", flight_number: "ZX 9931" },
    shortest: null, most_visited_airport: "JFK", busiest_month: "2026-03", times_around_earth: 1.3, moon_fraction: 0.1353,
  },
  stays: { nights: 9, chains: [{ name: "Hotel Canarios", count: 2 }], cities: [{ name: "Canario Suites", count: 1 }], countries: [], count: 0, average_nights: 0, hotels: [], cities_by_nights: [], longest: null, most_visited_hotel: null, most_visited_city: null, busiest_month: null, pins: [] },
  cars: { days: 0, companies: [] }, cruises: { count: 0, nights: 0, sea_days: 0, ports: 0, lines: [] },
  places: { countries: [{ name: "US", first_visit: "2026-01-02", visits: 3 }, { name: "GB", first_visit: "2026-03-14", visits: 1 }], cities: [] },
});
const allTime = (): Stats => ({ ...stats(null), places: { countries: [{ name: "US", first_visit: "2019-05-01", visits: 9 }, { name: "GB", first_visit: "2026-03-14", visits: 1 }], cities: [] } });

/** Every piece of text in a card, and the markup around it. */
const textOf = (svg: string) => [...svg.matchAll(/>([^<]+)</g)].map((m) => m[1]).join("\n");

describe("the share card's content", () => {
  const facts = reviewFacts(stats(), allTime());

  it("shows the year, totals, top route and countries", () => {
    const text = textOf(cardSvg(facts, [], null));
    for (const want of ["2026", "YEAR IN REVIEW", "12", "JFK – LHR", "United States", "United Kingdom"]) expect(text).toContain(want);
  });

  it.each([null, "Zelda"])("leaves out names, codes, dates, hotels and loyalty numbers (name: %s)", (name) => {
    const svg = cardSvg(facts, [{ d: "M0,0L1,1", visited: true }], name);
    for (const canary of CANARIES) expect(svg, canary).not.toContain(canary);
    expect(svg).not.toMatch(/\d{4}-\d{2}-\d{2}/);
    expect(JSON.stringify(facts)).not.toContain("Zelda");
  });

  it("has no name unless 'Show my name' is ticked, and then only the first name", () => {
    expect(textOf(cardSvg(facts, [], null))).not.toContain("Zelda");
    const named = textOf(cardSvg(facts, [], firstName("Zelda Quimby")));
    expect(named).toContain("ZELDA’S YEAR IN REVIEW");
    expect(named).not.toContain("Quimby");
  });

  it("leaves personal details out of the map picture too", () => {
    const svg = mapSvg(facts, []);
    for (const canary of CANARIES) expect(svg, canary).not.toContain(canary);
  });

  it("escapes what it writes", () => {
    const svg = cardSvg(facts, [], "<b>&\"");
    expect(svg).not.toContain("<b>");
    expect(svg).toContain("&lt;B&gt;&amp;&quot;");
  });
});

describe("reviewFacts", () => {
  it("calls a country new only if its first visit ever was that year", () => {
    expect(reviewFacts(stats(), allTime()).newCountries).toEqual(["United Kingdom"]);
  });
  it("claims nothing as new when the all-time numbers didn't load", () => {
    expect(reviewFacts(stats(), null).newCountries).toEqual([]);
  });
  it("copes with a year of no flights", () => {
    const quiet = stats();
    quiet.flights = { ...quiet.flights, count: 0, routes: [], airports: [], most_visited_airport: null, distance_km: 0, air_seconds: 0 };
    const f = reviewFacts(quiet, null);
    expect(f.topRoute).toBeNull();
    expect(cardSvg(f, [], null)).toContain("—");
  });
});

describe("firstName", () => {
  it("is the first word, or nothing", () => {
    expect(firstName("  Zelda  Quimby ")).toBe("Zelda");
    expect(firstName("")).toBeNull();
    expect(firstName(null)).toBeNull();
  });
});

describe("reviewOffered", () => {
  it("is offered from December 1 for this year, and any time for past years", () => {
    expect(reviewOffered(2026, new Date(2026, 10, 30))).toBe(false);
    expect(reviewOffered(2026, new Date(2026, 11, 1))).toBe(true);
    expect(reviewOffered(2025, new Date(2026, 0, 2))).toBe(true);
    expect(reviewOffered(2027, new Date(2026, 11, 20))).toBe(false);
    expect(reviewOffered(null, new Date(2026, 11, 20))).toBe(false);
  });
});

describe("the card's country shading", () => {
  const square = (id: string, west: number, south: number, east: number, north: number): Country => ({
    type: "Feature", id, properties: {}, geometry: { type: "Polygon", coordinates: [[[west, south], [west, north], [east, north], [east, south], [west, south]]] },
  });
  const countries = [square("826", -8, 49, 2, 61), square("250", -5, 42, 8, 51), square("392", 129, 31, 146, 46)];

  it("shades the countries of the airports flown and of the cities stayed in", () => {
    const base = stats();
    const withStay = { ...base, flights: { ...base.flights, airports: [base.flights.airports[0]] },
      stays: { ...base.stays, pins: [{ city: "Paris", country: "FR", latitude: 48.85, longitude: 2.35, stays: 1, nights: 3, trips: [] }] } };
    expect(outlinesFor(countries, withStay).map((c) => c.visited)).toEqual([false, true, false]);
    expect(outlinesFor(countries, { ...withStay, stays: { ...withStay.stays, pins: [] } }).map((c) => c.visited)).toEqual([false, false, false]);
  });
});
