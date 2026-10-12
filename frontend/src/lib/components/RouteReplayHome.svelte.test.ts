// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("$lib/map", async (original) => ({ ...(await original<typeof import("$lib/map")>()), loadCountries: async () => [] }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { TripPlaces } from "$lib/api-types";
import { stopsOf } from "$lib/route-replay";
import { segment, trip } from "../../test/fixtures";
import RouteReplay from "./RouteReplay.svelte";
import RouteReplayMap from "./RouteReplayMap.svelte";

const zone = "America/Chicago";
const places: TripPlaces = {
  home: { city: "Springfield", latitude: 39.8, longitude: -89.65 },
  airports: [],
  cities: [],
  stays: [
    { segment_id: 1, latitude: 38.63, longitude: -90.2, precision: "city" },
    { segment_id: 2, latitude: 36.16, longitude: -86.78, precision: "city" },
  ],
  roads: { legs: [], interstates: [] },
  boundaries: [],
};
const first = segment({ id: 1, kind: "hotel", origin: "Arch Inn", destination: "St. Louis", start_local: "2025-12-05T15:00", start_zone: zone, end_local: "2025-12-06T11:00", end_zone: zone });
const second = segment({ id: 2, kind: "hotel", origin: "Music Row Inn", destination: "Nashville", start_local: "2025-12-06T15:00", start_zone: zone, end_local: "2025-12-08T11:00", end_zone: zone });
const after = Date.parse("2026-01-15T12:00:00Z");
const stops = stopsOf(trip([first, second]), places);
const labels = (container: HTMLElement) => [...container.querySelectorAll("[data-label][data-visible='true']")].map((l) => l.getAttribute("data-label"));

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("RouteReplayMap with Home", () => {
  it("marks the first and last stops with a house and names the home city, with no street", () => {
    const { container } = render(RouteReplayMap, { stops, year: 2025, still: true });
    const houses = container.querySelectorAll("[data-kind='home'] [data-house]");
    expect(houses).toHaveLength(2);
    expect([...container.querySelectorAll("[data-kind='home']")].map((g) => g.getAttribute("data-stop"))).toEqual(["Springfield", "Springfield"]);
    expect(screen.getByLabelText("Map key").textContent).toContain("Home");
    const items = within(screen.getByRole("list", { name: "Stops in order" })).getAllByRole("listitem").map((li) => li.lastElementChild?.textContent?.replace(/\s+/g, " "));
    expect(items[0]).toBe("Springfield, Dec 5");
    expect(items[3]).toBe("Back in Springfield, Dec 8");
  });

  it("with reduced motion shows the finished route with both Home stops labelled once each", () => {
    const { container } = render(RouteReplayMap, { stops, year: 2025, still: true });
    expect(labels(container)).toEqual(["Springfield", "Arch Inn", "Music Row Inn", "Springfield"]);
    expect(container.querySelectorAll("[data-leg]")).toHaveLength(3);
  });

  it("shows the Home label once at the start, before anything is played", () => {
    const { container } = render(RouteReplayMap, { stops, year: 2025, still: false });
    expect(labels(container)).toEqual(["Springfield"]);
    expect(container.querySelectorAll("[data-kind='home']")).toHaveLength(1);
  });
});

describe("RouteReplay's start-and-end-at-home choice", () => {
  const reply = (body: unknown) => vi.mocked(api).mockImplementation(async (path: string, opts?: { method?: string; body?: unknown }) =>
    (opts?.method === "POST" ? { ...trip([first, second]), ...(opts.body as object) } : body) as never);

  it("offers the choice on, for a road trip with a placed Home, and saves turning it off", async () => {
    reply(places);
    const onchanged = vi.fn();
    render(RouteReplay, { trip: trip([first, second]), now: after, onchanged });
    const box = await screen.findByRole("checkbox", { name: "Start and end at home" });
    expect(box).toBeChecked();
    expect(await screen.findByRole("region", { name: "Route replay" })).toBeTruthy();
    await fireEvent.click(box);
    await waitFor(() => expect(onchanged).toHaveBeenCalled());
    expect(api).toHaveBeenCalledWith("/api/trips/1", { method: "POST", body: { replay_from_home: false } });
  });

  it("keeps the choice offered when it is off, with the route as it was before Home", async () => {
    reply(places);
    render(RouteReplay, { trip: trip([first, second], { replay_from_home: false }), now: after });
    const box = await screen.findByRole("checkbox", { name: "Start and end at home" });
    expect(box).not.toBeChecked();
    expect(within(await screen.findByRole("list", { name: "Stops in order" })).getAllByRole("listitem")).toHaveLength(2);
  });

  it("is not offered with no placed Home, or on a trip with a flight", async () => {
    reply({ ...places, home: null });
    const { unmount } = render(RouteReplay, { trip: trip([first, second]), now: after });
    expect(await screen.findByRole("region", { name: "Route replay" })).toBeTruthy();
    expect(screen.queryByRole("checkbox")).toBeNull();
    unmount();
    const flight = segment({ id: 9, origin: "MSP", destination: "SFO", start_local: "2025-12-05T08:00", start_zone: zone, end_local: "2025-12-05T10:30", end_zone: "America/Los_Angeles" });
    reply({ ...places, airports: [{ code: "MSP", city: "Minneapolis", latitude: 44.9, longitude: -93.2 }, { code: "SFO", city: "San Francisco", latitude: 37.6, longitude: -122.4 }] });
    render(RouteReplay, { trip: trip([first, flight]), now: after });
    expect(await screen.findByRole("region", { name: "Route replay" })).toBeTruthy();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });
});
