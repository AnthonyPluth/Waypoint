// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { StatsFlights } from "$lib/api-types";

vi.mock("$lib/map", async (original) => {
  const real = await original<typeof import("$lib/map")>();
  return { ...real, loadDetailedCountries: vi.fn(real.loadCountries), loadStates: vi.fn(real.loadStates) };
});
vi.mock("$lib/mapkit", async (original) => ({ ...(await original<typeof import("$lib/mapkit")>()), loadMapkit: vi.fn() }));

import { loadDetailedCountries, loadStates } from "$lib/map";
import { loadMapkit } from "$lib/mapkit";
import { viewport } from "$lib/phone.svelte";
import { fake, fakeMaps, type FakeMap, type FakeOverlay } from "../../test/fake-mapkit";
import StatsMapKit from "./StatsMapKit.svelte";

const flights = {
  airports: [
    { code: "JFK", name: "John F. Kennedy International Airport", city: "New York", country: "US", visits: 6, latitude: 40.6398, longitude: -73.7789 },
    { code: "NRT", name: "Narita International Airport", city: "Tokyo", country: "JP", visits: 2, latitude: 35.772, longitude: 140.3929 },
    { code: "ZZZ", name: "ZZZ", city: null, country: null, visits: 1, latitude: null, longitude: null },
  ],
  routes: [{ a: "JFK", b: "NRT", flights: 2, distance_km: 10800, a_latitude: 40.6398, a_longitude: -73.7789, b_latitude: 35.772, b_longitude: 140.3929, trips: [{ trip_id: 7, name: "Trip to Tokyo", start: "2026-04-02", end: "2026-04-03" }, { trip_id: 9, name: "Return from Tokyo", start: "2026-04-20", end: "2026-04-20" }] }],
} as StatsFlights;
const noFlights = { airports: [], routes: [] } as unknown as StatsFlights;
const hawaii = {
  airports: [
    { code: "HNL", name: "Daniel K. Inouye International Airport", city: "Honolulu", country: "US", visits: 4, latitude: 21.3187, longitude: -157.9225 },
    { code: "LIH", name: "Lihue Airport", city: "Lihue", country: "US", visits: 2, latitude: 21.976, longitude: -159.339 },
  ],
  routes: [{ a: "HNL", b: "LIH", flights: 2, distance_km: 170, a_latitude: 21.3187, a_longitude: -157.9225, b_latitude: 21.976, b_longitude: -159.339, trips: [] }],
} as unknown as StatsFlights;
const london = { city: "London", country: "GB", latitude: 51.47, longitude: -0.45, stays: 2, nights: 6,
  trips: [{ trip_id: 4, name: "Trip to London", start: "2026-06-02", end: "2026-06-08" }, { trip_id: 12, name: "Back to London", start: "2027-01-02", end: "2027-01-05" }] };
const trip = (id: number, name: string) => ({ trip_id: id, name, start: "2026-07-01", end: "2026-07-08" });

type Item = { pick: { label: string; trips: unknown[] }; kind: string };
const items = (map: FakeMap, kind: string) => [...map.overlays].map((o) => o.data as Item).filter((i) => i.kind === kind);
const labels = (map: FakeMap, kind: string) => items(map, kind).map((i) => i.pick.label).sort();
const overlayOf = (map: FakeMap, kind: string, label: string) => [...map.overlays].find((o) => (o.data as Item).kind === kind && (o.data as Item).pick.label === label) as FakeOverlay;
const annotationOf = (map: FakeMap, text: string) => [...map.annotations].find((a) => (a.data as Item).pick.label.startsWith(text))!;
const ready = async (): Promise<FakeMap> => {
  await waitFor(() => expect(fake.maps).toHaveLength(1));
  return fake.last();
};

beforeEach(() => {
  fake.reset();
  vi.mocked(loadDetailedCountries).mockClear();
  vi.mocked(loadStates).mockClear();
  vi.mocked(loadMapkit).mockReset();
  vi.mocked(loadMapkit).mockImplementation(async () => fakeMaps());
  viewport.phone = false;
});
afterEach(() => { viewport.phone = false; vi.unstubAllGlobals(); });

describe("StatsMapKit", () => {
  it("shows the loading skeleton until MapKit and the outlines are up, then one dark map with the zoom control and no points of interest", async () => {
    render(StatsMapKit, { flights, onfailure: vi.fn() });
    expect(screen.getByLabelText("Loading the map")).toBeTruthy();
    const map = await ready();
    expect(screen.queryByLabelText("Loading the map")).toBeNull();
    expect(map.options).toMatchObject({ colorScheme: "dark", showsZoomControl: true, showsPointsOfInterest: false, showsMapTypeControl: false });
    expect(screen.getByRole("img", { name: "Map of the visited countries and states, flights, airports and stays" })).toBeTruthy();
  });

  it("hands MapKit only the airports, arcs and stays drawn and the outlines of the visited countries, never an unvisited one", async () => {
    render(StatsMapKit, { flights, stays: [london], onfailure: vi.fn() });
    const map = await ready();
    await waitFor(() => expect(items(map, "country")).toHaveLength(3));
    expect(labels(map, "country")).toEqual(["Japan", "United Kingdom", "United States of America"]);
    expect(labels(map, "route")).toEqual(["JFK – NRT: 2 flights"]);
    expect([...map.annotations].map((a) => (a.data as Item).kind).sort()).toEqual(["airport", "airport", "stay"]);
    expect([...map.annotations].map((a) => (a.data as Item).pick.label).sort()).toEqual([
      "JFK · New York · John F. Kennedy International Airport: 6 visits", "London: 2 stays, 6 nights", "NRT · Tokyo · Narita International Airport: 2 visits",
    ]);
    expect(map.overlays.size).toBe(4);
    expect(items(map, "state")).toHaveLength(0);
  });

  it("styles the shading with the visited colour at about 35% fill and 70% edge, and draws the arcs above it", async () => {
    render(StatsMapKit, { flights, onfailure: vi.fn() });
    const map = await ready();
    await waitFor(() => expect(items(map, "country").length).toBeGreaterThan(0));
    const style = overlayOf(map, "country", "Japan").options.style!.options;
    expect(style).toMatchObject({ fillOpacity: 0.35, strokeOpacity: 0.7, lineWidth: 1 });
    expect(style.fillColor).toBe(style.strokeColor);
    const order = [...map.overlays].map((o) => (o.data as Item).kind);
    expect(order.lastIndexOf("country")).toBeLessThan(order.indexOf("route"));
  });

  it("shades a country only remembered by a past visit, and no state for a US one", async () => {
    render(StatsMapKit, { flights: noFlights, visits: [{ country: "JP", state: null, latitude: 35.77, longitude: 140.39, trips: [] }, { country: "US", state: null, latitude: 39.05, longitude: -95.67, trips: [] }] as never, onfailure: vi.fn() });
    const map = await ready();
    await waitFor(() => expect(items(map, "country")).toHaveLength(2));
    expect(labels(map, "country")).toEqual(["Japan", "United States of America"]);
    map.zoomTo(10);
    await waitFor(() => expect(loadStates).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 300));
    expect(items(map, "state")).toHaveLength(0);
  });

  it("swaps the United States for its visited states once zoomed in under 40 degrees, and back when zoomed out", async () => {
    render(StatsMapKit, { flights, onfailure: vi.fn() });
    const map = await ready();
    await waitFor(() => expect(labels(map, "country")).toContain("United States of America"));
    expect(items(map, "state")).toHaveLength(0);
    map.zoomTo(30);
    await waitFor(() => expect(labels(map, "state")).toEqual(["New York"]), { timeout: 8000 });
    expect(labels(map, "country")).toEqual(["Japan"]);
    map.zoomTo(120);
    await waitFor(() => expect(labels(map, "state")).toEqual([]));
    expect(labels(map, "country")).toEqual(["Japan", "United States of America"]);
    expect(items(map, "route")).toHaveLength(1);
  });

  it("asks for the states only once the map is that close, and only once", async () => {
    render(StatsMapKit, { flights, onfailure: vi.fn() });
    const map = await ready();
    await waitFor(() => expect(items(map, "country").length).toBeGreaterThan(0));
    expect(loadStates).not.toHaveBeenCalled();
    map.zoomTo(30);
    map.zoomTo(20);
    await waitFor(() => expect(labels(map, "state")).toEqual(["New York"]), { timeout: 8000 });
    expect(loadStates).toHaveBeenCalledOnce();
  });

  it("opens on the states when the places flown fit inside 40 degrees", async () => {
    render(StatsMapKit, { flights: hawaii, onfailure: vi.fn() });
    const map = await ready();
    await waitFor(() => expect(labels(map, "state")).toEqual(["Hawaii"]), { timeout: 8000 });
    expect(labels(map, "country")).toEqual([]);
  });

  it("names an airport, route, country or state under the map when it is selected, with the trips there, and clears it when the map is tapped", async () => {
    render(StatsMapKit, { flights, stays: [london], onfailure: vi.fn() });
    const map = await ready();
    await waitFor(() => expect(items(map, "country")).toHaveLength(3));
    expect(screen.getByText("Tap a country, state, airport, route or stay to see its trips.")).toBeTruthy();
    map.select(annotationOf(map, "JFK"));
    await waitFor(() => expect(screen.getByText("JFK · New York · John F. Kennedy International Airport: 6 visits")).toBeTruthy());
    expect(screen.queryByTestId("map-trips")).toBeNull();
    map.select(overlayOf(map, "route", "JFK – NRT: 2 flights"));
    const list = await screen.findByTestId("map-trips");
    expect(within(list).getByRole("link", { name: "Trip to Tokyo" })).toHaveAttribute("href", "#trip/7");
    expect(within(list).getByText("Apr 2, 2026 – Apr 3, 2026")).toBeTruthy();
    expect(within(list).getByText("Apr 20, 2026")).toBeTruthy();
    map.select(annotationOf(map, "London"));
    expect(within(await screen.findByTestId("map-trips")).getByRole("link", { name: "Back to London" })).toHaveAttribute("href", "#trip/12");
    map.select(overlayOf(map, "country", "United Kingdom"));
    await waitFor(() => expect(screen.getByText("United Kingdom", { selector: "span" })).toBeTruthy());
    expect(within(screen.getByTestId("map-trips")).getByRole("link", { name: "Trip to London" })).toBeTruthy();
    map.deselect();
    await waitFor(() => expect(screen.getByText("Tap a country, state, airport, route or stay to see its trips.")).toBeTruthy());
    expect(screen.queryByTestId("map-trips")).toBeNull();
  });

  it("gives the selected shape a white edge and the dot too, and takes it back when another is picked", async () => {
    render(StatsMapKit, { flights, onfailure: vi.fn() });
    const map = await ready();
    await waitFor(() => expect(items(map, "country").length).toBeGreaterThan(0));
    const japan = overlayOf(map, "country", "Japan");
    map.select(japan);
    expect((japan.style as unknown as { options: Record<string, unknown> }).options).toMatchObject({ strokeColor: "#ffffff", lineWidth: 2 });
    const dot = annotationOf(map, "JFK");
    map.select(dot);
    expect((japan.style as unknown as { options: Record<string, unknown> }).options.strokeColor).not.toBe("#ffffff");
    expect(dot.factory().querySelector("circle")!.getAttribute("stroke")).toBe("#ffffff");
  });

  describe("Alaska", () => {
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

    it.each(cases)("shades Alaska for %s, and selecting it lists the trip", async (_name, props, tripName) => {
      render(StatsMapKit, { flights: noFlights, ...props, onfailure: vi.fn() });
      const map = await ready();
      await waitFor(() => expect(labels(map, "state")).toEqual(["Alaska"]), { timeout: 8000 });
      map.select(overlayOf(map, "state", "Alaska"));
      expect(within(await screen.findByTestId("map-trips")).getByRole("link", { name: tripName })).toBeTruthy();
      expect(screen.getByText("Alaska", { selector: "span" })).toBeTruthy();
    });

    it("shades no state for a past US trip with no state, a cruise with nothing placed or an unplaced stay", async () => {
      render(StatsMapKit, { flights: noFlights, points: [], visits: [{ country: "US", state: null, latitude: 39.05, longitude: -95.67, trips: [trip(26, "Old US trip")] }] as never, onfailure: vi.fn() });
      const map = await ready();
      await waitFor(() => expect(items(map, "country")).toHaveLength(1));
      map.zoomTo(10);
      await new Promise((r) => setTimeout(r, 400));
      expect(items(map, "state")).toHaveLength(0);
    });
  });

  it("opens framed on the places flown, and follows the flights when they change", async () => {
    const { rerender } = render(StatsMapKit, { flights: hawaii, onfailure: vi.fn() });
    const map = await ready();
    await waitFor(() => expect(map.rects.length).toBeGreaterThan(0));
    const first = map.rects[map.rects.length - 1];
    expect(first.width).toBeLessThan(0.05);
    expect(first.x).toBeLessThan(0.1);
    await rerender({ flights });
    await waitFor(() => expect(map.rects[map.rects.length - 1].width).toBeGreaterThan(0.3));
    expect(fake.maps).toHaveLength(1);
    expect(labels(map, "route")).toEqual(["JFK – NRT: 2 flights"]);
  });

  it("frames a trip across the antimeridian on the short way round", async () => {
    const across = { airports: [], routes: [{ a: "SYD", b: "LAX", flights: 1, distance_km: 1, a_latitude: -33.9, a_longitude: 151.2, b_latitude: 33.9, b_longitude: -118.4, trips: [] }] } as unknown as StatsFlights;
    render(StatsMapKit, { flights: across, onfailure: vi.fn() });
    const map = await ready();
    await waitFor(() => expect(map.rects.length).toBeGreaterThan(0));
    const rect = map.rects[map.rects.length - 1];
    expect(rect.width).toBeLessThan(0.7);
    expect(rect.x).toBeGreaterThan(0.8);
  });

  it("keeps the page scrolling on a phone until the map is zoomed in, then lets one finger pan it", async () => {
    viewport.phone = true;
    render(StatsMapKit, { flights, onfailure: vi.fn() });
    const map = await ready();
    expect(map.options.isScrollEnabled).toBe(false);
    await waitFor(() => expect(map.rects.length).toBeGreaterThan(0));
    expect(map.isScrollEnabled).toBe(false);
    map.zoomTo(map.region.span.longitudeDelta / 4);
    expect(map.isScrollEnabled).toBe(true);
  });

  it("pans with a drag from the start on a desktop", async () => {
    render(StatsMapKit, { flights, onfailure: vi.fn() });
    const map = await ready();
    expect(map.options.isScrollEnabled).toBe(true);
  });

  it("shows the map without shading when the outlines fail to load", async () => {
    vi.mocked(loadDetailedCountries).mockRejectedValueOnce(new Error("no outlines"));
    const onfailure = vi.fn();
    render(StatsMapKit, { flights, stays: [london], onfailure });
    const map = await ready();
    await waitFor(() => expect(map.annotations.size).toBe(3));
    expect(items(map, "country")).toHaveLength(0);
    expect(items(map, "route")).toHaveLength(1);
    expect(onfailure).not.toHaveBeenCalled();
  });

  it("asks for no outline and builds no map when MapKit doesn't load, and says so", async () => {
    vi.mocked(loadMapkit).mockResolvedValue(null);
    const onfailure = vi.fn();
    render(StatsMapKit, { flights, onfailure });
    await waitFor(() => expect(onfailure).toHaveBeenCalledOnce());
    expect(loadDetailedCountries).not.toHaveBeenCalled();
    expect(fake.maps).toHaveLength(0);
  });

  it("gives up when MapKit has already failed", async () => {
    vi.mocked(loadMapkit).mockImplementation(async () => { const maps = fakeMaps(); maps.fail(); return maps; });
    const onfailure = vi.fn();
    render(StatsMapKit, { flights, onfailure });
    await waitFor(() => expect(onfailure).toHaveBeenCalled());
    expect(fake.maps).toHaveLength(0);
  });

  it("gives up when MapKit fails after the map showed, and when drawing throws", async () => {
    const maps = fakeMaps();
    vi.mocked(loadMapkit).mockResolvedValue(maps);
    const onfailure = vi.fn();
    render(StatsMapKit, { flights, onfailure });
    await ready();
    maps.fail();
    expect(onfailure).toHaveBeenCalled();
  });

  it("gives up when the map refuses what it is handed", async () => {
    fake.broken = true;
    const onfailure = vi.fn();
    render(StatsMapKit, { flights, onfailure });
    await waitFor(() => expect(onfailure).toHaveBeenCalled());
  });

  it("destroys the map when it goes", async () => {
    const { unmount } = render(StatsMapKit, { flights, onfailure: vi.fn() });
    const map = await ready();
    unmount();
    expect(map.destroyed).toBe(true);
  });

  it("makes no request of its own: the outlines are the app's own files, never fetched from anyone", async () => {
    const fetch = vi.fn();
    const xhr = vi.fn();
    const beacon = vi.fn();
    vi.stubGlobal("fetch", fetch);
    vi.stubGlobal("XMLHttpRequest", xhr);
    vi.stubGlobal("WebSocket", xhr);
    Object.defineProperty(navigator, "sendBeacon", { value: beacon, configurable: true });
    render(StatsMapKit, { flights, onfailure: vi.fn() });
    const map = await ready();
    await waitFor(() => expect(items(map, "country").length).toBeGreaterThan(0));
    expect(fetch).not.toHaveBeenCalled();
    expect(xhr).not.toHaveBeenCalled();
    expect(beacon).not.toHaveBeenCalled();
  });
});
