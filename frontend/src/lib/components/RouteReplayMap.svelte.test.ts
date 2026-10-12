// @vitest-environment jsdom
import { fireEvent, render, screen, within } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TripPlaces } from "$lib/api-types";
import { stopsOf } from "$lib/route-replay";
import { segment, trip } from "../../test/fixtures";
import RouteReplayMap from "./RouteReplayMap.svelte";

vi.mock("$lib/map", async (original) => ({ ...(await original<typeof import("$lib/map")>()), loadCountries: async () => [] }));

const places: TripPlaces = {
  airports: [
    { code: "MSP", city: "Minneapolis", latitude: 44.8848, longitude: -93.2223 },
    { code: "SFO", city: "San Francisco", latitude: 37.6213, longitude: -122.379 },
  ],
  cities: [],
};
const flights = [
  segment({ id: 1, origin: "MSP", destination: "SFO", start_local: "2025-12-05T08:00", start_zone: "America/Chicago", end_local: "2025-12-05T10:30", end_zone: "America/Los_Angeles" }),
  segment({ id: 2, origin: "SFO", destination: "MSP", start_local: "2025-12-11T13:00", start_zone: "America/Los_Angeles", end_local: "2025-12-11T18:50", end_zone: "America/Chicago" }),
];
const stops = stopsOf(trip(flights), places);

let frames: ((at: number) => void)[] = [];
let clock = 0;
const advance = (ms: number) => {
  clock += ms;
  const due = frames;
  frames = [];
  due.forEach((f) => f(clock));
};

beforeEach(() => {
  frames = [];
  clock = 0;
  vi.stubGlobal("requestAnimationFrame", (f: (at: number) => void) => frames.push(f));
  vi.stubGlobal("cancelAnimationFrame", () => { frames = []; });
  vi.spyOn(performance, "now").mockImplementation(() => clock);
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

const labels = (container: HTMLElement) => [...container.querySelectorAll("[data-label]")].map((l) => l.getAttribute("data-label"));
const list = () => within(screen.getByRole("list", { name: "Stops in order" })).getAllByRole("listitem").map((li) => li.lastElementChild?.textContent?.replace(/\s+/g, " "));

describe("RouteReplayMap", () => {
  it("lists the stops in order as text, without waiting for any animation", () => {
    render(RouteReplayMap, { stops, year: 2025, still: false });
    expect(list()).toEqual(["Minneapolis, Dec 5", "San Francisco, Dec 5 – 11", "Back in Minneapolis, Dec 11"]);
  });

  it("does not play until asked, and shows only the first stop", () => {
    const { container } = render(RouteReplayMap, { stops, year: 2025, still: false });
    expect(frames).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Play" })).toBeTruthy();
    expect(labels(container)).toEqual(["Minneapolis"]);
    expect(container.querySelector("[data-leg]")).toBeNull();
  });

  it("draws the path and labels each stop as it is reached, pulsing the current one", async () => {
    const { container } = render(RouteReplayMap, { stops, year: 2025, still: false });
    await fireEvent.click(screen.getByRole("button", { name: "Play" }));
    expect(screen.getByRole("button", { name: "Pause" })).toBeTruthy();
    advance(4500);
    await Promise.resolve();
    expect(labels(container)).toEqual(["Minneapolis", "San Francisco"]);
    expect(container.querySelectorAll("[data-leg]")).toHaveLength(2);
    expect(container.querySelectorAll(".animate-ping")).toHaveLength(1);
    expect(container.querySelector("[data-stop='San Francisco'] .animate-ping")).toBeTruthy();
    advance(9000);
    await Promise.resolve();
    expect(labels(container)).toEqual(["Minneapolis", "San Francisco"]);
    expect(screen.getByRole("button", { name: "Replay" })).toBeTruthy();
    expect(container.querySelector(".animate-ping")).toBeNull();
    expect(frames).toHaveLength(0);
  });

  it("pauses, resumes, scrubs by keyboard-operable range and replays from the start", async () => {
    const { container } = render(RouteReplayMap, { stops, year: 2025, still: false });
    await fireEvent.click(screen.getByRole("button", { name: "Play" }));
    advance(1000);
    await fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(frames).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Resume" })).toBeTruthy();
    const slider = screen.getByRole("slider", { name: "Position along the route" }) as HTMLInputElement;
    await fireEvent.input(slider, { target: { value: "1000" } });
    expect(labels(container)).toHaveLength(2);
    expect(slider.getAttribute("aria-valuetext")).toBe("Back in Minneapolis, Dec 11");
    await fireEvent.click(screen.getByRole("button", { name: "Replay" }));
    expect(labels(container)).toEqual(["Minneapolis"]);
    expect(screen.getByRole("button", { name: "Pause" })).toBeTruthy();
  });

  it("with reduced motion shows the whole path and every stop labelled, with no controls, timers or animation classes", () => {
    const { container } = render(RouteReplayMap, { stops, year: 2025, still: true });
    expect(labels(container)).toEqual(["Minneapolis", "San Francisco"]);
    expect(container.querySelectorAll("[data-leg]")).toHaveLength(2);
    expect(container.querySelectorAll("path[data-leg][stroke-dashoffset='0']")).toHaveLength(2);
    expect(container.querySelector(".animate-ping")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("slider")).toBeNull();
    expect(frames).toHaveLength(0);
    expect(list()).toHaveLength(3);
  });

  it("follows the system's reduced-motion setting when none is forced", () => {
    const listeners: ((e: { matches: boolean }) => void)[] = [];
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener: (_: string, f: never) => listeners.push(f), removeEventListener: vi.fn() }));
    const { container } = render(RouteReplayMap, { stops, year: 2025 });
    expect(labels(container)).toHaveLength(2);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("keeps the dates of a stay beside its name", () => {
    const { container } = render(RouteReplayMap, { stops, year: 2025, still: true });
    const label = container.querySelector("[data-label='San Francisco']")!;
    expect(label.textContent).toContain("Dec 5");
  });
});
