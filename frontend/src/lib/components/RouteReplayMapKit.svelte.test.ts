// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("$lib/map", async (original) => ({ ...(await original<typeof import("$lib/map")>()), loadCountries: async () => [], loadDetailedCountries: async () => [], loadFineCountries: async () => [] }));

import { api } from "$lib/api";
import type { TripPlaces } from "$lib/api-types";
import { app } from "$lib/app.svelte";
import { forgetMapkit } from "$lib/mapkit";
import { stopsOf } from "$lib/route-replay";
import { fake, fakeMaps, fakeMk } from "../../test/fake-mapkit";
import { clearRouteCache } from "$lib/driving-routes";
import { segment, state, trip } from "../../test/fixtures";
import RouteReplay from "./RouteReplay.svelte";
import RouteReplayMap from "./RouteReplayMap.svelte";

const places: TripPlaces = {
  home: null,
  airports: [
    { code: "MSP", city: "Minneapolis", latitude: 44.8848, longitude: -93.2223 },
    { code: "SFO", city: "San Francisco", latitude: 37.6213, longitude: -122.379 },
  ],
  cities: [],
  stays: [],
  roads: { legs: [], interstates: [] },
  boundaries: [],
};
const flights = [
  segment({ id: 1, origin: "MSP", destination: "SFO", start_local: "2025-12-05T08:00", start_zone: "America/Chicago", end_local: "2025-12-05T10:30", end_zone: "America/Los_Angeles" }),
  segment({ id: 2, origin: "SFO", destination: "MSP", start_local: "2025-12-11T13:00", start_zone: "America/Los_Angeles", end_local: "2025-12-11T18:50", end_zone: "America/Chicago" }),
];
const stops = stopsOf(trip(flights), places);
const after = Date.parse("2026-01-15T12:00:00Z");
const SCRIPT = "https://maps.example.test/mapkit.js";

let frames: ((at: number) => void)[] = [];
let clock = 0;
const advance = (ms: number) => {
  clock += ms;
  const due = frames;
  frames = [];
  due.forEach((f) => f(clock));
};
let scripts: HTMLScriptElement[] = [];
let token: unknown = { enabled: true, token: "a.b.c", expires: 4102444800, script: SCRIPT };

beforeEach(() => {
  forgetMapkit();
  clearRouteCache();
  fake.reset();
  frames = [];
  clock = 0;
  scripts = [];
  token = { enabled: true, token: "a.b.c", expires: 4102444800, script: SCRIPT };
  vi.stubGlobal("requestAnimationFrame", (f: (at: number) => void) => frames.push(f));
  vi.stubGlobal("cancelAnimationFrame", () => { frames = []; });
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: false, media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
  vi.spyOn(performance, "now").mockImplementation(() => clock);
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async (path: string) => (path === "/api/mapkit/token" ? token : places) as never);
  vi.spyOn(document.head, "append").mockImplementation((...nodes) => { scripts.push(...(nodes as HTMLScriptElement[])); });
});
afterEach(() => { app.state = null; cleanup(); delete (window as { mapkit?: unknown }).mapkit; vi.unstubAllGlobals(); vi.restoreAllMocks(); });

const labels = (c: HTMLElement) => [...c.querySelectorAll("[data-label][data-visible='true']")].map((l) => l.getAttribute("data-label"));
const svg = (c: HTMLElement) => c.querySelector("svg[data-zoomed]");
const loadScript = async () => {
  await waitFor(() => expect(scripts).toHaveLength(1));
  (window as { mapkit?: unknown }).mapkit = fakeMk;
  scripts[0].onload?.(new Event("load"));
};

describe("RouteReplay with the flag off", () => {
  it("draws the flat map, loads nothing and calls no one but the server", async () => {
    token = { enabled: false };
    const { container } = render(RouteReplay, { trip: trip(flights), now: after });
    expect(await screen.findByRole("button", { name: "Pause" })).toBeTruthy();
    expect(svg(container)).toBeTruthy();
    expect(container.querySelector("[data-mapkit]")).toBeNull();
    expect(scripts).toHaveLength(0);
    expect(fake.maps).toHaveLength(0);
    expect(vi.mocked(api).mock.calls.map((c) => c[0]).sort()).toEqual(["/api/mapkit/token", "/api/trips/1/places"]);
  });

  it("asks nothing about maps when the server's state says MapKit is not active, and plays at once", async () => {
    app.state = state({ mapkit: false });
    const { container } = render(RouteReplay, { trip: trip(flights), now: after });
    expect(await screen.findByRole("button", { name: "Pause" })).toBeTruthy();
    expect(svg(container)).toBeTruthy();
    expect(vi.mocked(api).mock.calls.map((c) => c[0])).toEqual(["/api/trips/1/places"]);
  });

  it("still asks when the state says MapKit is active, or doesn't say", async () => {
    for (const mapkit of [true, undefined]) {
      forgetMapkit();
      vi.mocked(api).mockClear();
      app.state = state(mapkit === undefined ? {} : { mapkit });
      render(RouteReplay, { trip: trip(flights), now: after });
      await waitFor(() => expect(vi.mocked(api).mock.calls.map((c) => c[0])).toContain("/api/mapkit/token"));
      cleanup();
    }
  });

  it("asks nothing about maps for a trip that has no replay", async () => {
    render(RouteReplay, { trip: trip(flights), now: Date.parse("2025-12-08T12:00:00Z") });
    await Promise.resolve();
    expect(vi.mocked(api)).not.toHaveBeenCalled();
  });
});

describe("RouteReplay with the flag on", () => {
  it("waits for MapKit, then plays the replay on it, with the same labels, controls and list", async () => {
    const { container } = render(RouteReplay, { trip: trip(flights), now: after });
    expect(await screen.findByRole("region", { name: "Route replay" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Play" })).toBeTruthy();
    expect(frames).toHaveLength(0);
    await loadScript();
    expect(await screen.findByRole("button", { name: "Pause" })).toBeTruthy();
    expect(container.querySelector("[data-mapkit]")).toBeTruthy();
    expect(svg(container)).toBeNull();
    expect(container.querySelector("[data-testid='replay-map']")).toBeTruthy();
    expect(fake.maps).toHaveLength(1);
    expect(labels(container)).toEqual(["Minneapolis"]);
    expect(screen.getByRole("slider", { name: "Position along the route" })).toBeTruthy();
    expect(screen.getByRole("list", { name: "Stops in order" })).toBeTruthy();
    advance(4500);
    await Promise.resolve();
    expect(labels(container)).toEqual(["San Francisco"]);
    const map = fake.last();
    expect(map.overlays.size).toBe(2);
    expect([...map.annotations].filter((a) => a.factory().hasAttribute("data-stop"))).toHaveLength(2);
  });

  it("follows the slider on the MapKit map", async () => {
    const { container } = render(RouteReplay, { trip: trip(flights), now: after });
    await loadScript();
    await screen.findByRole("button", { name: "Pause" });
    await fireEvent.input(screen.getByRole("slider", { name: "Position along the route" }), { target: { value: "4000" } });
    expect(screen.getByRole("button", { name: "Replay" })).toBeTruthy();
    expect([...fake.last().annotations].filter((a) => a.factory().hasAttribute("data-stop"))).toHaveLength(3);
    expect(container.querySelectorAll("[data-stop-item]")).toHaveLength(3);
    await fireEvent.input(screen.getByRole("slider", { name: "Position along the route" }), { target: { value: "0" } });
    expect(fake.last().overlays.size).toBe(0);
  });

  it("keeps a Play press made while MapKit loads, instead of restarting from the beginning", async () => {
    const { container } = render(RouteReplay, { trip: trip(flights), now: after });
    await fireEvent.click(await screen.findByRole("button", { name: "Play" }));
    advance(4500);
    await Promise.resolve();
    expect(labels(container)).toEqual(["San Francisco"]);
    await loadScript();
    await waitFor(() => expect(container.querySelector("[data-mapkit]")).toBeTruthy());
    expect(labels(container)).toEqual(["San Francisco"]);
    expect(screen.getByRole("button", { name: "Pause" })).toBeTruthy();
  });

  it("keeps a scrub made while MapKit loads, without starting playback", async () => {
    const { container } = render(RouteReplay, { trip: trip(flights), now: after });
    await fireEvent.input(await screen.findByRole("slider", { name: "Position along the route" }), { target: { value: "4000" } });
    await loadScript();
    await waitFor(() => expect(container.querySelector("[data-mapkit]")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Replay" })).toBeTruthy();
  });

  it("tries MapKit again for the next trip after a transient failure", async () => {
    const view = render(RouteReplay, { trip: trip(flights), now: after });
    await waitFor(() => expect(scripts).toHaveLength(1));
    scripts[0].onerror?.(new Event("error"));
    expect(await screen.findByRole("button", { name: "Pause" })).toBeTruthy();
    expect(view.container.querySelector("[data-mapkit]")).toBeNull();
    await view.rerender({ trip: trip(flights, { id: 2 }), now: after });
    await waitFor(() => expect(scripts).toHaveLength(2));
    (window as { mapkit?: unknown }).mapkit = fakeMk;
    scripts[1].onload?.(new Event("load"));
    await waitFor(() => expect(view.container.querySelector("[data-mapkit]")).toBeTruthy());
  });

  it("shows the whole route with reduced motion", async () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    render(RouteReplay, { trip: trip(flights), now: after });
    await loadScript();
    await waitFor(() => expect(fake.maps).toHaveLength(1));
    expect(screen.queryByRole("button")).toBeNull();
    await waitFor(() => expect(fake.last().overlays.size).toBe(2));
  });

  it("falls back to the flat map, mid-replay and at the same place, when MapKit reports an error", async () => {
    const { container } = render(RouteReplay, { trip: trip(flights), now: after });
    await loadScript();
    await screen.findByRole("button", { name: "Pause" });
    advance(4500);
    await Promise.resolve();
    expect(labels(container)).toEqual(["San Francisco"]);
    fake.emit("error", { status: "Unauthorized" });
    await waitFor(() => expect(svg(container)).toBeTruthy());
    expect(container.querySelector("[data-mapkit]")).toBeNull();
    expect(fake.last().destroyed).toBe(true);
    expect(labels(container)).toEqual(["San Francisco"]);
    expect(container.querySelectorAll("[data-leg]")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Pause" })).toBeTruthy();
    expect(screen.getByRole("list", { name: "Stops in order" })).toBeTruthy();
  });

  it("falls back to the flat map when the script can't be loaded", async () => {
    const { container } = render(RouteReplay, { trip: trip(flights), now: after });
    await waitFor(() => expect(scripts).toHaveLength(1));
    scripts[0].onerror?.(new Event("error"));
    expect(await screen.findByRole("button", { name: "Pause" })).toBeTruthy();
    expect(svg(container)).toBeTruthy();
    expect(fake.maps).toHaveLength(0);
  });

  it("falls back to the flat map when the token can't be had after MapKit started", async () => {
    const { container } = render(RouteReplay, { trip: trip(flights), now: after });
    await loadScript();
    await screen.findByRole("button", { name: "Pause" });
    vi.mocked(api).mockRejectedValue(new Error("offline"));
    fake.inits[0].authorizationCallback(vi.fn());
    await waitFor(() => expect(svg(container)).toBeTruthy());
  });
});

describe("RouteReplayMap on MapKit", () => {
  it("draws the flat map when it is given no MapKit, as before", () => {
    const { container } = render(RouteReplayMap, { stops, year: 2025, still: true, maps: null });
    expect(svg(container)).toBeTruthy();
    expect(container.querySelector("[data-mapkit]")).toBeNull();
  });

  it("falls back at once when MapKit can't build the map", async () => {
    const maps = fakeMaps();
    fake.broken = true;
    const { container } = render(RouteReplayMap, { stops, year: 2025, still: true, maps });
    await waitFor(() => expect(svg(container)).toBeTruthy());
    expect(maps.watching()).toBe(0);
    expect(fake.last().destroyed).toBe(true);
    expect(fake.listening("error")).toBe(0);
  });

  it("falls back when MapKit fails through the session, and takes the map down", async () => {
    const maps = fakeMaps();
    const { container } = render(RouteReplayMap, { stops, year: 2025, still: true, maps });
    expect(container.querySelector("[data-mapkit]")).toBeTruthy();
    expect(maps.watching()).toBe(1);
    maps.fail();
    await waitFor(() => expect(svg(container)).toBeTruthy());
    expect(fake.last().destroyed).toBe(true);
    expect(maps.watching()).toBe(0);
  });

  it("takes the map down when the replay goes away", () => {
    const maps = fakeMaps();
    const view = render(RouteReplayMap, { stops, year: 2025, still: true, maps });
    expect(fake.maps).toHaveLength(1);
    view.unmount();
    expect(fake.last().destroyed).toBe(true);
    expect(maps.watching()).toBe(0);
  });
});
