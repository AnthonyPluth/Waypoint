// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Stats } from "./api-types";
import { cardSvg, imageInputs, imageSummary, mapSvg, outlinesFor, reviewFacts, reviewOffered, saveImage, svgToPng } from "./review";
import type { Country } from "./map";

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

const textOf = (svg: string) => [...svg.matchAll(/>([^<]+)</g)].map((m) => m[1]).join("\n");

const withCanaries = (): Stats => {
  const base = stats();
  return {
    ...base,
    flights: {
      ...base.flights,
      routes: [{ ...base.flights.routes[0], trips: [{ trip_id: 7, name: "Canary Trip ZQ7X9K", start: "2026-03-14", end: "2026-03-20" }] }],
      airlines: [{ code: "ZZ", name: "Canary Airways", flights: 12 }],
    },
    stays: { ...base.stays, pins: [{ city: "Canary City", country: "US", latitude: 40, longitude: -73, stays: 1, nights: 3, trips: [{ trip_id: 8, name: "Hotel Canarios FF-123456", start: "2026-03-14", end: "2026-03-17" }] }] },
  };
};

describe("the image's inputs", () => {
  const facts = reviewFacts(withCanaries(), allTime());
  const inputs = imageInputs(facts);

  it("hold only the allowed totals", () => {
    expect(Object.keys(inputs).sort()).toEqual(["airTime", "countries", "distance", "flights", "map", "nights", "topAirports", "topRoute", "year"]);
    expect(Object.keys(inputs.topRoute ?? {}).sort()).toEqual(["a", "b"]);
    expect(Object.keys(inputs.map).sort()).toEqual(["arcs", "dots"]);
    expect(inputs.map.dots.every((d) => Object.keys(d).sort().join() === "r,x,y")).toBe(true);
    expect(inputs.map.arcs.every((a) => Object.keys(a).sort().join() === "d,width")).toBe(true);
    expect(inputs.topAirports).toEqual(["JFK", "LHR"]);
  });

  it("carry none of the canary values, in the inputs, the drawn image or the list shown on screen", () => {
    const everything = [JSON.stringify(inputs), cardSvg(inputs, [{ d: "M0,0L1,1", visited: true }]), imageSummary(inputs).join("\n")].join("\n");
    for (const canary of CANARIES) expect(everything, canary).not.toContain(canary);
    expect(everything).not.toMatch(/\d{4}-\d{2}-\d{2}/);
  });
});

describe("the share card's content", () => {
  const facts = reviewFacts(stats(), allTime());
  const inputs = imageInputs(facts);

  it("shows the year, totals, top route and countries", () => {
    const text = textOf(cardSvg(inputs, []));
    for (const want of ["2026", "YEAR IN REVIEW", "12", "JFK – LHR", "Top airports: JFK · LHR", "United States", "United Kingdom"]) expect(text).toContain(want);
  });

  it("never names a person", () => {
    expect(Object.keys(inputs)).not.toContain("name");
    expect(JSON.stringify(facts)).not.toContain("Zelda");
  });

  it("leaves personal details out of the map picture too", () => {
    const svg = mapSvg(facts, []);
    for (const canary of CANARIES) expect(svg, canary).not.toContain(canary);
  });

  it("escapes what it writes", () => {
    const svg = cardSvg({ ...inputs, countries: ["<b>&\""] }, []);
    expect(svg).not.toContain("<b>");
    expect(svg).toContain("&lt;b&gt;&amp;&quot;");
  });

  it("describes what it will show, in words", () => {
    const lines = imageSummary(inputs);
    expect(lines).toContain("Top route: JFK – LHR");
    expect(lines).toContain("Top airports: JFK, LHR");
    expect(lines).toContain("2 countries: United States, United Kingdom");
    expect(imageSummary({ ...inputs, topRoute: null, topAirports: [], countries: [], flights: 1, nights: 1 }).join("\n")).not.toContain("Top");
  });
});

describe("drawing the image", () => {
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it("makes no network request, and loads only the image it was given as data", async () => {
    const fetchSpy = vi.fn(), openSpy = vi.fn(), beaconSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    vi.stubGlobal("XMLHttpRequest", class { open = openSpy; });
    Object.assign(navigator, { sendBeacon: beaconSpy });
    const loaded: string[] = [];
    vi.stubGlobal("Image", class {
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      set src(value: string) { loaded.push(value); queueMicrotask(() => this.onload?.()); }
    });
    const drawImage = vi.fn();
    const realCreate = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation(((tag: string) => tag === "canvas"
      ? { width: 0, height: 0, getContext: () => ({ drawImage }), toBlob: (cb: (b: Blob) => void) => cb(new Blob(["png"], { type: "image/png" })) }
      : realCreate(tag)) as never);
    const svg = cardSvg(imageInputs(reviewFacts(stats(), allTime())), [{ d: "M0,0L1,1", visited: true }]);
    const png = await svgToPng(svg);
    expect(png.type).toBe("image/png");
    expect(drawImage).toHaveBeenCalledOnce();
    expect(loaded).toHaveLength(1);
    expect(loaded[0].startsWith("data:image/svg+xml")).toBe(true);
    expect(svg).not.toMatch(/href=|src=|url\(|@import/);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(openSpy).not.toHaveBeenCalled();
    expect(beaconSpy).not.toHaveBeenCalled();
  });

  it("saves to the device by a download link, without sharing", () => {
    const share = vi.fn();
    Object.assign(navigator, { share, canShare: () => true });
    URL.createObjectURL = vi.fn(() => "blob:x"); URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    saveImage(new Blob(["png"], { type: "image/png" }), "waypoint-2026.png");
    expect(click).toHaveBeenCalledOnce();
    expect(share).not.toHaveBeenCalled();
    Reflect.deleteProperty(navigator, "share"); Reflect.deleteProperty(navigator, "canShare");
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
    expect(cardSvg(imageInputs(f), [])).toContain("—");
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
