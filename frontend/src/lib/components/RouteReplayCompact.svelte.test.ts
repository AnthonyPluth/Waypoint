// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TripPlaces } from "$lib/api-types";
import { SCRUB_STEPS, stopsOf } from "$lib/route-replay";
import { segment, trip } from "../../test/fixtures";
import RouteReplayMap from "./RouteReplayMap.svelte";

vi.mock("$lib/map", async (original) => ({ ...(await original<typeof import("$lib/map")>()), loadCountries: async () => [], loadDetailedCountries: async () => [], loadFineCountries: async () => [] }));

const places: TripPlaces = {
  home: null,
  airports: [
    { code: "MSP", city: "Minneapolis", latitude: 44.8848, longitude: -93.2223 },
    { code: "SFO", city: "San Francisco", latitude: 37.6213, longitude: -122.379 },
  ],
  cities: [],
  stays: [],
};
const flights = [
  segment({ id: 1, origin: "MSP", destination: "SFO", start_local: "2025-12-05T08:00", start_zone: "America/Chicago", end_local: "2025-12-05T10:30", end_zone: "America/Los_Angeles" }),
  segment({ id: 2, origin: "SFO", destination: "MSP", start_local: "2025-12-11T13:00", start_zone: "America/Los_Angeles", end_local: "2025-12-11T18:50", end_zone: "America/Chicago" }),
];
const stops = stopsOf(trip(flights), places);

let frames: ((at: number) => void)[] = [];
let clock = 0;
beforeEach(() => {
  frames = [];
  clock = 0;
  vi.stubGlobal("requestAnimationFrame", (f: (at: number) => void) => frames.push(f));
  vi.stubGlobal("cancelAnimationFrame", () => { frames = []; });
  vi.spyOn(performance, "now").mockImplementation(() => clock);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); });

const slide = (to: number) => fireEvent.input(screen.getByRole("slider", { name: "Position along the route" }), { target: { value: String(to) } });

describe("the trip page's compact map", () => {
  it("is a group named Trip map, with no image role, and no key, controls or stops list", () => {
    const { container } = render(RouteReplayMap, { stops, year: 2025, still: true, compact: true });
    expect(screen.getByRole("group", { name: "Trip map" })).toBeTruthy();
    expect(container.querySelector("svg[role=img]")).toBeNull();
    expect(screen.queryByRole("list", { name: "Map key" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Stops list" })).toBeNull();
    expect(screen.queryByRole("slider")).toBeNull();
  });

  it("draws only the map and Replay trip when compact, and calls back when it is pressed", () => {
    const onreplay = vi.fn();
    render(RouteReplayMap, { stops, year: 2025, still: true, compact: true, onreplay });
    fireEvent.click(screen.getByRole("button", { name: "Replay trip" }));
    expect(onreplay).toHaveBeenCalledOnce();
  });

  it("starts playing again each time a still map is let go, and reports when the replay reaches its end", async () => {
    const onended = vi.fn();
    const { rerender } = render(RouteReplayMap, { stops, year: 2025, still: true, compact: true, autoplay: true, onended });
    for (let round = 0; round < 2; round++) {
      await rerender({ stops, year: 2025, still: false, compact: false, autoplay: true, onended });
      expect(await screen.findByRole("button", { name: "Pause" })).toBeTruthy();
      await rerender({ stops, year: 2025, still: true, compact: true, autoplay: true, onended });
      expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
    }
    expect(onended).not.toHaveBeenCalled();
    await rerender({ stops, year: 2025, still: false, compact: false, autoplay: true, onended });
    slide(SCRUB_STEPS);
    await vi.waitFor(() => expect(onended).toHaveBeenCalledOnce());
  });

  it("has no Replay trip button without a handler", () => {
    render(RouteReplayMap, { stops, year: 2025, still: true, compact: true });
    expect(screen.queryByRole("button", { name: "Replay trip" })).toBeNull();
  });
});
