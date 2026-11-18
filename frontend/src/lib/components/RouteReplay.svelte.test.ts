// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { tick } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("$lib/mapkit", async (original) => ({ ...(await original<typeof import("$lib/mapkit")>()), loadMapkit: vi.fn() }));

import { api } from "$lib/api";
import type { TripPlaces } from "$lib/api-types";
import { app } from "$lib/app.svelte";
import { loadMapkit, type Maps } from "$lib/mapkit";
import { fake, fakeMaps } from "../../test/fake-mapkit";
import { segment, state, trip } from "../../test/fixtures";
import RouteReplay from "./RouteReplay.svelte";

const places: TripPlaces = {
  home: null,
  airports: [
    { code: "MSP", city: "Minneapolis", latitude: 44.8848, longitude: -93.2223 },
    { code: "SFO", city: "San Francisco", latitude: 37.6213, longitude: -122.379 },
  ],
  cities: [],
  stays: [],
};
const there = segment({ id: 1, origin: "MSP", destination: "SFO", start_local: "2025-12-05T08:00", start_zone: "America/Chicago", end_local: "2025-12-05T10:30", end_zone: "America/Los_Angeles" });
const home = segment({ id: 2, origin: "SFO", destination: "MSP", start_local: "2025-12-11T13:00", start_zone: "America/Los_Angeles", end_local: "2025-12-11T18:50", end_zone: "America/Chicago" });
const after = Date.parse("2026-01-15T12:00:00Z");
const during = Date.parse("2025-12-08T12:00:00Z");
const region = () => screen.queryByRole("region", { name: "Route replay" });
const reduced = () => vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
const LINE = "The map couldn’t load";
const quiet = () => screen.queryByText(LINE);

let maps: ReturnType<typeof fakeMaps>;
let frames: ((at: number) => void)[] = [];

beforeEach(() => {
  fake.reset();
  maps = fakeMaps();
  frames = [];
  vi.stubGlobal("requestAnimationFrame", (f: (at: number) => void) => frames.push(f));
  vi.stubGlobal("cancelAnimationFrame", () => { frames = []; });
  vi.mocked(api).mockReset();
  vi.mocked(api).mockResolvedValue(places as never);
  vi.mocked(loadMapkit).mockReset();
  vi.mocked(loadMapkit).mockImplementation(async () => maps);
  app.state = state({ mapkit: true });
  app.offline = false;
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: false, media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
});
afterEach(() => { cleanup(); app.state = null; app.offline = false; vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("RouteReplay", () => {
  it("shows the route inline for a trip that has ended and has two located stops, and plays it once", async () => {
    const { container } = render(RouteReplay, { trip: trip([there, home]), now: after });
    expect(await screen.findByRole("region", { name: "Route replay" })).toBeTruthy();
    expect(vi.mocked(api)).toHaveBeenCalledWith("/api/trips/1/places");
    expect(await screen.findByRole("button", { name: "Pause" })).toBeTruthy();
    expect(container.querySelector("[data-mapkit]")).toBeTruthy();
    expect(container.querySelector("svg[data-zoomed]")).toBeNull();
    expect(fake.maps).toHaveLength(1);
    expect(screen.getByRole("slider", { name: "Position along the route" })).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    const items = within(screen.getByRole("list", { name: "Stops in order" })).getAllByRole("listitem").map((li) => li.textContent);
    expect(items[0]).toContain("Minneapolis (MSP), Dec 5, 2025");
    expect(items.at(-1)).toContain("Minneapolis (MSP), Dec 11, 2025");
  });

  it("with reduced motion shows the whole route and the list, with nothing playing", async () => {
    reduced();
    render(RouteReplay, { trip: trip([there, home]), now: after });
    expect(await screen.findByRole("region", { name: "Route replay" })).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByRole("list", { name: "Stops in order" })).toBeTruthy();
  });

  it("is absent for a trip still going and does not ask for coordinates", async () => {
    render(RouteReplay, { trip: trip([there, home]), now: during });
    await Promise.resolve();
    expect(region()).toBeNull();
    expect(vi.mocked(api)).not.toHaveBeenCalled();
  });

  it("is absent for a trip that has not started", () => {
    render(RouteReplay, { trip: trip([there, home]), now: Date.parse("2025-11-01T12:00:00Z") });
    expect(region()).toBeNull();
    expect(vi.mocked(api)).not.toHaveBeenCalled();
  });

  it("is absent when fewer than two stops have coordinates", async () => {
    vi.mocked(api).mockResolvedValue({ airports: [places.airports[0]], cities: [], stays: [] } as never);
    render(RouteReplay, { trip: trip([there, home]), now: after });
    await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalled());
    await Promise.resolve();
    expect(region()).toBeNull();
    expect(loadMapkit).not.toHaveBeenCalled();
  });

  it("is absent for a single stay, without asking", () => {
    const stay = segment({ id: 3, kind: "hotel", origin: "Inn", destination: "San Francisco", start_local: "2025-12-05T15:00", start_zone: "America/Los_Angeles", end_local: "2025-12-08T11:00", end_zone: "America/Los_Angeles" });
    render(RouteReplay, { trip: trip([stay]), now: after });
    expect(region()).toBeNull();
    expect(vi.mocked(api)).not.toHaveBeenCalled();
  });

  it("is absent when the coordinates can't be loaded or come back malformed", async () => {
    vi.mocked(api).mockRejectedValue(new Error("down"));
    const first = render(RouteReplay, { trip: trip([there, home]), now: after });
    await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalled());
    await Promise.resolve();
    expect(region()).toBeNull();
    first.unmount();
    vi.mocked(api).mockResolvedValue({ id: 1, name: "x", segments: [] } as never);
    render(RouteReplay, { trip: trip([there, home]), now: after });
    await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalledTimes(2));
    await Promise.resolve();
    expect(region()).toBeNull();
  });

  describe("a drive between two stays", () => {
    const mt = "America/Denver";
    const first = segment({ id: 3, kind: "hotel", origin: "Mile High Inn", destination: "Denver", start_local: "2025-12-05T15:00", start_zone: mt, end_local: "2025-12-06T11:00", end_zone: mt });
    const second = segment({ id: 4, kind: "hotel", origin: "Salt Flat Inn", destination: "Salt Lake City", start_local: "2025-12-06T15:00", start_zone: mt, end_local: "2025-12-08T11:00", end_zone: mt });
    const drive = {
      airports: [], cities: [],
      stays: [{ segment_id: 3, latitude: 39.74, longitude: -104.99, precision: "city" }, { segment_id: 4, latitude: 40.76, longitude: -111.89, precision: "city" }],
    };

    it("draws a straight line when Apple has no road for it", async () => {
      reduced();
      vi.mocked(api).mockResolvedValue(drive as never);
      render(RouteReplay, { trip: trip([first, second]), now: after });
      expect(await screen.findByRole("region", { name: "Route replay" })).toBeTruthy();
      const [line] = [...fake.last().overlays];
      expect(line.points.length).toBeGreaterThan(2);
    });
  });
});

describe("RouteReplay without a map", () => {
  const flagOff = async (state_: ReturnType<typeof state> | null) => {
    app.state = state_;
    render(RouteReplay, { trip: trip([there, home]), now: after });
    await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalledWith("/api/trips/1/places"));
    await new Promise((r) => setTimeout(r, 20));
  };

  it("renders nothing when the server says MapKit is off, and never asks Apple's script to load", async () => {
    await flagOff(state({ mapkit: false }));
    expect(region()).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
    expect(loadMapkit).not.toHaveBeenCalled();
    expect(fake.maps).toHaveLength(0);
  });

  it("renders nothing when the state doesn't say MapKit is on, or isn't known yet", async () => {
    await flagOff(state({}));
    expect(region()).toBeNull();
    cleanup();
    await flagOff(null);
    expect(region()).toBeNull();
    expect(loadMapkit).not.toHaveBeenCalled();
  });

  it("renders nothing, and asks nothing of Apple, for a viewer who is offline", async () => {
    app.offline = true;
    render(RouteReplay, { trip: trip([there, home]), now: after });
    await new Promise((r) => setTimeout(r, 20));
    expect(region()).toBeNull();
    cleanup();
    app.offline = false;
    vi.stubGlobal("navigator", { ...navigator, onLine: false, language: "en-US" });
    render(RouteReplay, { trip: trip([there, home]), now: after });
    await new Promise((r) => setTimeout(r, 20));
    expect(region()).toBeNull();
    expect(loadMapkit).not.toHaveBeenCalled();
  });

  it("renders nothing, with no message, when MapKit doesn't load", async () => {
    vi.mocked(loadMapkit).mockResolvedValue(null);
    render(RouteReplay, { trip: trip([there, home]), now: after });
    await waitFor(() => expect(loadMapkit).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 20));
    expect(region()).toBeNull();
    expect(quiet()).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("renders nothing, with no message, when MapKit has already failed", async () => {
    maps.fail();
    render(RouteReplay, { trip: trip([there, home]), now: after });
    await waitFor(() => expect(loadMapkit).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 20));
    expect(region()).toBeNull();
    expect(quiet()).toBeNull();
    expect(fake.maps).toHaveLength(0);
  });

  it("shows nothing until MapKit has loaded, then the replay", async () => {
    let load: (found: Maps | null) => void = () => {};
    vi.mocked(loadMapkit).mockReturnValue(new Promise((resolve) => { load = resolve; }));
    render(RouteReplay, { trip: trip([there, home]), now: after });
    await waitFor(() => expect(loadMapkit).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 20));
    expect(region()).toBeNull();
    load(maps);
    expect(await screen.findByRole("region", { name: "Route replay" })).toBeTruthy();
  });

  it("renders nothing when the map can't be built, and says nothing about it", async () => {
    fake.broken = true;
    render(RouteReplay, { trip: trip([there, home]), now: after });
    await waitFor(() => expect(loadMapkit).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 20));
    expect(region()).toBeNull();
    expect(quiet()).toBeNull();
  });
});

describe("RouteReplay when the map fails after it showed", () => {
  const shown = async (extra: Record<string, unknown> = {}) => {
    const view = render(RouteReplay, { trip: trip([there, home]), now: after, ...extra });
    expect(await screen.findByRole("button", { name: "Pause" })).toBeTruthy();
    return view;
  };

  it("replaces the block with a quiet line, announced politely, and takes the map and its controls away", async () => {
    await shown();
    expect(screen.getByRole("status")).toBeTruthy();
    expect(quiet()).toBeNull();
    maps.fail();
    expect(await screen.findByText(LINE)).toBeTruthy();
    expect(region()).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("slider")).toBeNull();
    const line = screen.getByRole("status");
    expect(line.textContent).toBe(LINE);
    expect(line).toHaveAttribute("aria-live", "polite");
    expect(line.className).toContain("text-sm");
    expect(line.className).toContain("text-muted-foreground");
    expect(line.className).toContain("border-dashed");
    expect(line.className).toContain("border-border");
    expect(line.className).toContain("rounded");
    expect(fake.last().destroyed).toBe(true);
  });

  it("does the same when MapKit raises an error through the map", async () => {
    await shown();
    fake.emit("error", { status: "Unauthorized" });
    expect(await screen.findByText(LINE)).toBeTruthy();
    expect(region()).toBeNull();
  });

  it("keeps the line, and does not build the map again, when the trip's own data reloads", async () => {
    const view = await shown();
    maps.fail();
    await screen.findByText(LINE);
    const built = fake.maps.length;
    await view.rerender({ trip: trip([there, home]), now: after + 1000 });
    await tick();
    expect(quiet()).toBeTruthy();
    expect(fake.maps).toHaveLength(built);
  });

  it("is gone when the page is left", async () => {
    const view = await shown();
    maps.fail();
    await screen.findByText(LINE);
    view.unmount();
    expect(quiet()).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("is gone for the next trip, which gets its own replay", async () => {
    const view = await shown();
    maps.fail();
    await screen.findByText(LINE);
    maps = fakeMaps();
    await view.rerender({ trip: trip([there, home], { id: 2 }), now: after });
    expect(await screen.findByRole("region", { name: "Route replay" })).toBeTruthy();
    expect(quiet()).toBeNull();
  });

  it("moves focus to the place it is told to when the focus was inside the replay", async () => {
    const facts = document.createElement("dl");
    facts.tabIndex = -1;
    document.body.append(facts);
    await shown({ fallbackFocus: () => facts });
    screen.getByRole("button", { name: "Pause" }).focus();
    expect(region()!.contains(document.activeElement)).toBe(true);
    maps.fail();
    await screen.findByText(LINE);
    await waitFor(() => expect(document.activeElement).toBe(facts));
    facts.remove();
  });

  it("leaves focus alone when it was somewhere else", async () => {
    const facts = document.createElement("dl");
    facts.tabIndex = -1;
    const other = document.createElement("button");
    document.body.append(facts, other);
    await shown({ fallbackFocus: () => facts });
    other.focus();
    maps.fail();
    await screen.findByText(LINE);
    await tick();
    expect(document.activeElement).toBe(other);
    facts.remove();
    other.remove();
  });

  it("does not fail when there is nowhere to move focus to", async () => {
    await shown({ fallbackFocus: () => null });
    screen.getByRole("button", { name: "Pause" }).focus();
    maps.fail();
    expect(await screen.findByText(LINE)).toBeTruthy();
  });

  it("closes a compact block the same way, with its Replay trip button", async () => {
    render(RouteReplay, { trip: trip([there, home]), now: after, compact: true, onreplay: () => {} });
    expect(await screen.findByRole("button", { name: "Replay trip" })).toBeTruthy();
    maps.fail();
    expect(await screen.findByText(LINE)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Replay trip" })).toBeNull();
  });

  it("starts nothing and keeps no timer or listener behind once it has failed", async () => {
    await shown();
    await fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    maps.fail();
    await screen.findByText(LINE);
    expect(maps.watching()).toBe(0);
    expect(frames).toHaveLength(0);
  });
});

describe("RouteReplay when the connection or MapKit changes while it is waiting", () => {
  it("stops being offered when the shared MapKit session fails while the replay is hidden", async () => {
    const facts = document.createElement("dl");
    facts.tabIndex = -1;
    const replayButton = document.createElement("button");
    replayButton.setAttribute("aria-controls", "past-trip-replay");
    document.body.append(facts, replayButton);
    const onstops = vi.fn();
    render(RouteReplay, { trip: trip([there, home]), now: after, shown: false, onstops, wrapId: "past-trip-replay", fallbackFocus: () => facts });
    await waitFor(() => expect(onstops.mock.calls.at(-1)?.[0]).toBeGreaterThan(1));
    replayButton.focus();
    maps.fail();
    await waitFor(() => expect(onstops).toHaveBeenLastCalledWith(0));
    await waitFor(() => expect(document.activeElement).toBe(facts));
    expect(fake.maps).toHaveLength(0);
    expect(screen.queryByText(LINE)).toBeNull();
    facts.remove();
    replayButton.remove();
  });

  it("shows only one quiet line, not none, when it fails while shown", async () => {
    render(RouteReplay, { trip: trip([there, home]), now: after });
    await screen.findByRole("button", { name: "Pause" });
    maps.fail();
    expect(await screen.findByText(LINE)).toBeTruthy();
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.getByText(LINE)).toBeTruthy();
  });

  it("goes when the browser goes offline, and comes back when it is online again", async () => {
    vi.mocked(api).mockImplementation((async (path: string) => (path === "/api/state" ? state({ mapkit: true }) : places)) as never);
    const facts = document.createElement("dl");
    facts.tabIndex = -1;
    document.body.append(facts);
    const onstops = vi.fn();
    render(RouteReplay, { trip: trip([there, home]), now: after, onstops, fallbackFocus: () => facts });
    expect(await screen.findByRole("region", { name: "Route replay" })).toBeTruthy();
    (await screen.findByRole("button", { name: "Pause" })).focus();
    vi.stubGlobal("navigator", { ...navigator, onLine: false, language: "en-US" });
    window.dispatchEvent(new Event("offline"));
    await waitFor(() => expect(region()).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(facts));
    facts.remove();
    expect(onstops).toHaveBeenLastCalledWith(0);
    vi.stubGlobal("navigator", { ...navigator, onLine: true, language: "en-US" });
    window.dispatchEvent(new Event("online"));
    expect(await screen.findByRole("region", { name: "Route replay" })).toBeTruthy();
  });

  it("does not mount a map that finishes loading after the browser went offline", async () => {
    let load: (found: Maps | null) => void = () => {};
    vi.mocked(loadMapkit).mockReturnValue(new Promise((resolve) => { load = resolve; }));
    render(RouteReplay, { trip: trip([there, home]), now: after });
    await waitFor(() => expect(loadMapkit).toHaveBeenCalled());
    vi.stubGlobal("navigator", { ...navigator, onLine: false, language: "en-US" });
    window.dispatchEvent(new Event("offline"));
    await tick();
    load(maps);
    await new Promise((r) => setTimeout(r, 20));
    expect(region()).toBeNull();
    expect(fake.maps).toHaveLength(0);
  });
});
