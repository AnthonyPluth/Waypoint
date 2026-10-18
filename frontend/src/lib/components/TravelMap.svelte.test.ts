// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { StatsFlights } from "$lib/api-types";
import TravelMap from "./TravelMap.svelte";

vi.mock("$lib/map", async (original) => {
  const real = await original<typeof import("$lib/map")>();
  return { ...real, loadDetailedCountries: real.loadCountries, loadFineCountries: real.loadCountries };
});

const flights = {
  airports: [
    { code: "JFK", name: "John F. Kennedy International Airport", city: "New York", country: "US", visits: 6, latitude: 40.6398, longitude: -73.7789 },
    { code: "NRT", name: "Narita International Airport", city: "Tokyo", country: "JP", visits: 2, latitude: 35.772, longitude: 140.3929 },
    { code: "ZZZ", name: "ZZZ", city: null, country: null, visits: 1, latitude: null, longitude: null },
  ],
  routes: [{ a: "JFK", b: "NRT", flights: 2, distance_km: 10800, a_latitude: 40.6398, a_longitude: -73.7789, b_latitude: 35.772, b_longitude: 140.3929, trips: [{ trip_id: 7, name: "Trip to Tokyo", start: "2026-04-02", end: "2026-04-03" }, { trip_id: 9, name: "Return from Tokyo", start: "2026-04-20", end: "2026-04-20" }] }],
} as StatsFlights;

afterEach(() => vi.restoreAllMocks());

const hawaii = {
  airports: [
    { code: "HNL", name: "Daniel K. Inouye International Airport", city: "Honolulu", country: "US", visits: 4, latitude: 21.3187, longitude: -157.9225 },
    { code: "LIH", name: "Lihue Airport", city: "Lihue", country: "US", visits: 2, latitude: 21.976, longitude: -159.339 },
  ],
  routes: [{ a: "HNL", b: "LIH", flights: 2, distance_km: 170, a_latitude: 21.3187, a_longitude: -157.9225, b_latitude: 21.976, b_longitude: -159.339, trips: [] }],
} as unknown as StatsFlights;
const scale = (container: HTMLElement) => Number(/scale\(([\d.]+)\)/.exec(container.querySelector("[data-testid=map-layer]")!.getAttribute("transform") ?? "")?.[1]);

const london = { city: "London", country: "GB", latitude: 51.47, longitude: -0.45, stays: 2, nights: 6,
  trips: [{ trip_id: 4, name: "Trip to London", start: "2026-06-02", end: "2026-06-08" }, { trip_id: 12, name: "Back to London", start: "2027-01-02", end: "2027-01-05" }] };
const noFlights = { airports: [], routes: [] } as unknown as StatsFlights;

describe("TravelMap", () => {
  it("names what each mark on the map is, only for what is drawn", () => {
    render(TravelMap, { flights });
    const key = within(screen.getByTestId("map-key"));
    expect(key.getByText("Airport")).toBeTruthy();
    expect(key.getByText("Route")).toBeTruthy();
    expect(key.getByText("Visited")).toBeTruthy();
    expect(key.queryByText("Stay")).toBeNull();
  });

  it("shades the United States by state, not as one country, and a stay shades its country", async () => {
    const { container } = render(TravelMap, { flights, stays: [london] });
    await waitFor(() => expect(container.querySelectorAll("path[data-state]").length).toBeGreaterThan(50), { timeout: 8000 });
    expect([...container.querySelectorAll("path[data-state][data-visited]")].map((p) => p.getAttribute("data-state"))).toEqual(["New York"]);
    expect([...container.querySelectorAll("path[data-visited]:not([data-state]) title")].map((t) => t.textContent).sort()).toEqual(["Japan", "United Kingdom"]);
  });

  it("shades a country only remembered by a past visit, and no US state for one", async () => {
    const { container } = render(TravelMap, { flights: noFlights, visits: [{ country: "JP", state: null, latitude: 35.77, longitude: 140.39, trips: [] }, { country: "US", state: null, latitude: 39.05, longitude: -95.67, trips: [] }] });
    await waitFor(() => expect(container.querySelectorAll("path[data-state]").length).toBeGreaterThan(50), { timeout: 8000 });
    expect([...container.querySelectorAll("path[data-visited]:not([data-state]) title")].map((t) => t.textContent)).toEqual(["Japan"]);
    expect(container.querySelectorAll("path[data-state][data-visited]").length).toBe(0);
  });

  it("shades the US as one country while the states haven't loaded", async () => {
    const { container } = render(TravelMap, { flights });
    expect(container.querySelectorAll("path[data-state]").length).toBe(0);
    await waitFor(() => expect(container.querySelectorAll("path[data-visited]").length).toBeGreaterThan(0));
  });

  it("draws a pin for each stay, and lists its trips and when they were when it's picked", async () => {
    const { container } = render(TravelMap, { flights: noFlights, stays: [london] });
    expect(container.querySelectorAll("[data-stay]")).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "London: 2 stays, 6 nights" }));
    const list = within(screen.getByTestId("map-trips"));
    expect(list.getByRole("link", { name: "Trip to London" })).toHaveAttribute("href", "#trip/4");
    expect(list.getByText("Jun 2, 2026 – Jun 8, 2026")).toBeTruthy();
    expect(list.getByRole("link", { name: "Back to London" })).toHaveAttribute("href", "#trip/12");
  });

  it("lists the trips a route was flown on, with the day of each, and clears them when another place is picked", async () => {
    render(TravelMap, { flights, stays: [london] });
    await userEvent.click(screen.getByRole("button", { name: "JFK – NRT: 2 flights" }));
    const list = within(screen.getByTestId("map-trips"));
    expect(list.getByRole("link", { name: "Trip to Tokyo" })).toHaveAttribute("href", "#trip/7");
    expect(list.getByText("Apr 2, 2026 – Apr 3, 2026")).toBeTruthy();
    expect(list.getByText("Apr 20, 2026")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /^JFK · / }));
    expect(screen.queryByTestId("map-trips")).toBeNull();
  });

  it("draws the countries, the airports and the routes, and shades the countries visited", async () => {
    const { container } = render(TravelMap, { flights });
    await waitFor(() => expect(container.querySelectorAll("path[data-state]").length).toBeGreaterThan(50), { timeout: 8000 });
    expect(container.querySelectorAll("path").length).toBeGreaterThan(100);
    expect(container.querySelectorAll("[data-dot]")).toHaveLength(2);
    expect(container.querySelectorAll("[data-arc]")).toHaveLength(1);
    expect([...container.querySelectorAll("path[data-visited] title")].map((t) => t.textContent).sort()).toEqual(["Japan", "New York"]);
  });

  it("shows an airport's or a route's name and count when picked, and a tap on the land clears it", async () => {
    render(TravelMap, { flights });
    expect(screen.getByText("Tap an airport, a route or a stay for its name and count, and for the trips there.")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /^JFK · / }));
    expect(screen.getByText("JFK · New York · John F. Kennedy International Airport: 6 visits")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "JFK – NRT: 2 flights" }));
    expect(screen.getByText("JFK – NRT: 2 flights", { selector: "span" })).toBeTruthy();
    await userEvent.unhover(screen.getByRole("button", { name: "JFK – NRT: 2 flights" }));
    await waitFor(() => expect(document.querySelectorAll("path[data-visited]").length).toBeGreaterThan(0));
    await userEvent.click(document.querySelector("path[data-visited]")!);
    expect(screen.getByText("Tap an airport, a route or a stay for its name and count, and for the trips there.")).toBeTruthy();
  });

  it("picks with the keyboard", async () => {
    render(TravelMap, { flights });
    screen.getByRole("button", { name: /^NRT · / }).focus();
    await waitFor(() => expect(screen.getByText(/^NRT · Tokyo/, { selector: "span" })).toBeTruthy());
  });

  it("zooms in and out and resets", async () => {
    const { container } = render(TravelMap, { flights });
    const layer = container.querySelector("[data-testid=map-layer]")!;
    const reset = screen.getByRole("button", { name: "Reset" }) as HTMLButtonElement;
    expect(reset.disabled).toBe(true);
    expect(layer.getAttribute("transform")).toContain("scale(1)");
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(layer.getAttribute("transform")).toContain("scale(1.6)");
    expect(reset.disabled).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(layer.getAttribute("transform")).toContain("scale(1)");
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    await userEvent.click(reset);
    expect(layer.getAttribute("transform")).toContain("scale(1)");
  });

  it("says so when there are no flights, and still draws the world", async () => {
    const { container } = render(TravelMap, { flights: { airports: [], routes: [] } as unknown as StatsFlights });
    expect(screen.getByText("No airports or stays to show on the map yet.")).toBeTruthy();
    await waitFor(() => expect(container.querySelectorAll("path").length).toBeGreaterThan(100));
    expect(container.querySelectorAll("[data-visited]")).toHaveLength(0);
  });

  it("makes no network requests: the outlines are bundled", async () => {
    const fetch = vi.fn();
    const xhr = vi.fn();
    const beacon = vi.fn();
    vi.stubGlobal("fetch", fetch);
    vi.stubGlobal("XMLHttpRequest", xhr);
    vi.stubGlobal("WebSocket", xhr);
    Object.defineProperty(navigator, "sendBeacon", { value: beacon, configurable: true });
    const { container } = render(TravelMap, { flights });
    await waitFor(() => expect(container.querySelectorAll("path").length).toBeGreaterThan(100));
    expect(fetch).not.toHaveBeenCalled();
    expect(xhr).not.toHaveBeenCalled();
    expect(beacon).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("names no host in its code: nothing to fetch a tile from", () => {
    for (const file of ["TravelMap.svelte", "../map.ts"]) {
      const source = readFileSync(new URL(file, import.meta.url), "utf8");
      expect(source, file).not.toMatch(/https?:\/\/|\/\/[a-z0-9.-]+\.[a-z]{2,}\/|new Image|<image|<img/i);
    }
  });

  it("opens framed on the places flown, with Reset back to that view and World for everything", async () => {
    const { container } = render(TravelMap, { flights: hawaii });
    await waitFor(() => expect(scale(container)).toBeGreaterThan(3));
    const reset = screen.getByRole("button", { name: "Reset" }) as HTMLButtonElement;
    const world = screen.getByRole("button", { name: "World" }) as HTMLButtonElement;
    expect(reset.disabled).toBe(true);
    await userEvent.click(world);
    expect(scale(container)).toBe(1);
    expect(world.disabled).toBe(true);
    await userEvent.click(reset);
    expect(scale(container)).toBeGreaterThan(3);
  });

  it("follows the flights when they change (another traveller, another year)", async () => {
    const { container, rerender } = render(TravelMap, { flights: hawaii });
    await waitFor(() => expect(scale(container)).toBeGreaterThan(3));
    await rerender({ flights });
    await waitFor(() => expect(scale(container)).toBe(1));
  });

  describe("Alaska", () => {
    const trip = (id: number, name: string) => ({ trip_id: id, name, start: "2026-07-01", end: "2026-07-08" });
    const anchorage = { city: "Anchorage", country: null, latitude: 61.22, longitude: -149.86, stays: 1, nights: 3, trips: [trip(20, "Anchorage hotel trip")] };
    const flown = { airports: [{ code: "JNU", name: "Juneau International Airport", city: "Juneau", country: "US", visits: 1, latitude: 58.3547, longitude: -134.5785 }],
      routes: [{ a: "SEA", b: "JNU", flights: 1, distance_km: 1, a_latitude: 47.45, a_longitude: -122.31, b_latitude: 58.3547, b_longitude: -134.5785, trips: [trip(21, "Flight to Juneau")] }] } as unknown as StatsFlights;
    const cases: [string, Record<string, unknown>, string][] = [
      ["a hotel", { stays: [anchorage] }, "Anchorage hotel trip"],
      ["a flight", { flights: flown }, "Flight to Juneau"],
      ["a rental car", { points: [{ kind: "car", name: "Fairbanks", latitude: 64.84, longitude: -147.72, trips: [trip(22, "Rental trip")] }] }, "Rental trip"],
      ["a train", { points: [{ kind: "train", name: "Seward", latitude: 60.1, longitude: -149.44, trips: [trip(23, "Train trip")] }] }, "Train trip"],
      ["a cruise port of call", { points: [{ kind: "port", name: "Skagway", latitude: 59.46, longitude: -135.31, trips: [trip(24, "Cruise trip")] }] }, "Cruise trip"],
      ["a past trip to the US with the state AK", { visits: [{ country: "US", state: "AK", latitude: 61.22, longitude: -149.9, trips: [trip(25, "Old Alaska trip")] }] }, "Old Alaska trip"],
    ];

    it.each(cases)("shades Alaska for %s, and tapping it lists the trip", async (_name, props, tripName) => {
      const { container } = render(TravelMap, { flights: noFlights, ...props });
      await waitFor(() => expect(container.querySelectorAll("path[data-state]").length).toBeGreaterThan(50), { timeout: 8000 });
      expect([...container.querySelectorAll("path[data-state][data-visited]")].map((p) => p.getAttribute("data-state"))).toEqual(["Alaska"]);
      await userEvent.click(container.querySelector("path[data-state=Alaska]")!);
      expect(within(screen.getByTestId("map-trips")).getByRole("link", { name: tripName })).toBeTruthy();
      expect(screen.getByText("Alaska", { selector: "span" })).toBeTruthy();
    });

    it("shades nothing for a cruise with no placed port, a US past trip with no state, or an unplaced stay", async () => {
      const { container } = render(TravelMap, { flights: noFlights, points: [], visits: [{ country: "US", state: null, latitude: 39.05, longitude: -95.67, trips: [trip(26, "Old US trip")] }] });
      await waitFor(() => expect(container.querySelectorAll("path[data-state]").length).toBeGreaterThan(50), { timeout: 8000 });
      expect(container.querySelectorAll("path[data-state][data-visited]")).toHaveLength(0);
      expect(container.querySelectorAll("path[data-state][role=button]")).toHaveLength(0);
    });

    it("opens framed on an Alaska past trip or cruise, and Alaska can be reached from the world view", async () => {
      const { container } = render(TravelMap, { flights: noFlights, points: [{ kind: "port", name: "Juneau", latitude: 58.3, longitude: -134.4, trips: [trip(27, "Cruise")] }] });
      await waitFor(() => expect(scale(container)).toBeGreaterThan(3));
      await userEvent.click(screen.getByRole("button", { name: "World" }));
      expect(scale(container)).toBe(1);
      await waitFor(() => expect(container.querySelectorAll("path[data-state=Alaska][data-visited]")).toHaveLength(1));
    });

    it("picks a shaded state with the keyboard", async () => {
      const { container } = render(TravelMap, { flights: noFlights, stays: [anchorage] });
      await waitFor(() => expect(container.querySelector("path[data-state=Alaska][data-visited]")).toBeTruthy(), { timeout: 8000 });
      const alaska = container.querySelector("path[data-state=Alaska]") as SVGPathElement;
      alaska.focus();
      await userEvent.keyboard("{Enter}");
      expect(within(screen.getByTestId("map-trips")).getByRole("link", { name: "Anchorage hotel trip" })).toBeTruthy();
    });
  });
});
