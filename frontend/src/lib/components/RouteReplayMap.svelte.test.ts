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
  stays: [],
  roads: { legs: [], interstates: [] },
  boundaries: [],
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

const labels = (container: HTMLElement) => [...container.querySelectorAll("[data-label][data-visible='true']")].map((l) => l.getAttribute("data-label"));
const list = () => within(screen.getByRole("list", { name: "Stops in order" })).getAllByRole("listitem").map((li) => li.lastElementChild?.textContent?.replace(/\s+/g, " "));

describe("RouteReplayMap", () => {
  it("lists the stops in order as text, without waiting for any animation", () => {
    render(RouteReplayMap, { stops, year: 2025, still: false });
    expect(list()).toEqual(["Minneapolis (MSP), Dec 5", "San Francisco (SFO), Dec 5 – 11", "Back in Minneapolis (MSP), Dec 11"]);
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
    expect(labels(container)).toEqual(["San Francisco"]);
    expect(container.querySelectorAll("[data-leg]")).toHaveLength(2);
    expect(container.querySelectorAll(".animate-ping")).toHaveLength(1);
    expect(container.querySelector("[data-stop='San Francisco'] .animate-ping")).toBeTruthy();
    advance(9000);
    await Promise.resolve();
    expect(labels(container)).toEqual(["Minneapolis"]);
    expect(screen.getByRole("button", { name: "Replay" })).toBeTruthy();
    advance(1000);
    await Promise.resolve();
    advance(1000);
    await Promise.resolve();
    expect(labels(container)).toEqual([]);
    advance(1000);
    await Promise.resolve();
    expect(container.querySelector(".animate-ping")).toBeNull();
    expect(frames).toHaveLength(0);
    expect(container.querySelectorAll("[data-plane]").length).toBeGreaterThan(0);
    expect(list()).toHaveLength(3);
  });

  it("pauses, resumes, scrubs by keyboard-operable range and replays from the start", async () => {
    const { container } = render(RouteReplayMap, { stops, year: 2025, still: false });
    await fireEvent.click(screen.getByRole("button", { name: "Play" }));
    advance(1000);
    await fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(frames).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Resume" })).toBeTruthy();
    const slider = screen.getByRole("slider", { name: "Position along the route" }) as HTMLInputElement;
    await fireEvent.input(slider, { target: { value: "4000" } });
    expect(labels(container)).toHaveLength(0);
    expect(slider.getAttribute("aria-valuetext")).toBe("Back in Minneapolis (MSP), Dec 11");
    await fireEvent.click(screen.getByRole("button", { name: "Replay" }));
    expect(labels(container)).toEqual(["Minneapolis"]);
    expect(screen.getByRole("button", { name: "Pause" })).toBeTruthy();
  });

  it("with reduced motion shows the whole path and every stop labelled, with no controls, timers or animation classes", () => {
    const { container } = render(RouteReplayMap, { stops, year: 2025, still: true });
    expect(labels(container)).toEqual(["Minneapolis", "San Francisco", "Minneapolis"]);
    expect(container.querySelectorAll("[data-leg]")).toHaveLength(2);
    expect(container.querySelectorAll("path[data-leg][stroke-dashoffset='0']")).toHaveLength(2);
    expect([...container.querySelectorAll("[data-plane]")].map((p) => p.getAttribute("data-flying"))).toEqual(["false", "false"]);
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
    expect(labels(container)).toHaveLength(3);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("keeps the dates of a stay beside its name", () => {
    const { container } = render(RouteReplayMap, { stops, year: 2025, still: true });
    const label = container.querySelector("[data-label='San Francisco']")!;
    expect(label.textContent).toContain("Dec 5");
  });

  it("flies a plane along each flight, there and back, hidden from assistive technology", async () => {
    const { container } = render(RouteReplayMap, { stops, year: 2025, still: false });
    expect(container.querySelector("[data-plane]")).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Play" }));
    advance(1500);
    await Promise.resolve();
    const first = container.querySelector("[data-plane='0']")!;
    expect(first.getAttribute("data-flying")).toBe("true");
    expect(first.closest("[aria-hidden='true']")).toBeTruthy();
    const before = first.getAttribute("transform");
    advance(1000);
    await Promise.resolve();
    expect(container.querySelector("[data-plane='0']")!.getAttribute("transform")).not.toBe(before);
    advance(3000);
    await Promise.resolve();
    expect(container.querySelector("[data-plane='1']")!.getAttribute("data-flying")).toBe("true");
    expect(container.querySelector("[data-plane='0']")!.getAttribute("data-flying")).toBe("false");
    const angle = (i: number) => Number(/rotate\((-?[\d.]+)\)/.exec(container.querySelector(`[data-plane='${i}']`)!.getAttribute("transform")!)![1]);
    expect(Math.abs(Math.cos((angle(0) * Math.PI) / 180) - Math.cos((angle(1) * Math.PI) / 180))).toBeGreaterThan(0.5);
  });

  it("fades a label out after its hold and fades the next one in", async () => {
    const { container } = render(RouteReplayMap, { stops, year: 2025, still: false });
    expect(labels(container)).toEqual(["Minneapolis"]);
    await fireEvent.click(screen.getByRole("button", { name: "Play" }));
    advance(1000);
    await Promise.resolve();
    expect(labels(container)).toEqual(["Minneapolis"]);
    advance(2500);
    await Promise.resolve();
    expect(container.querySelector("[data-label='Minneapolis']")!.getAttribute("data-visible")).toBe("false");
    expect(container.querySelector("[data-label='Minneapolis']")!.className).toContain("opacity-0");
    expect(container.querySelector("[data-label='San Francisco']")!.getAttribute("data-visible")).toBe("true");
  });

  it("autoplays once on load and does not start again after it finishes", async () => {
    render(RouteReplayMap, { stops, year: 2025, still: false, autoplay: true });
    await Promise.resolve();
    expect(frames).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Pause" })).toBeTruthy();
    advance(7000);
    await Promise.resolve();
    expect(screen.getByRole("button", { name: "Replay" })).toBeTruthy();
    advance(3000);
    await Promise.resolve();
    expect(frames).toHaveLength(0);
    await fireEvent.click(screen.getByRole("button", { name: "Replay" }));
    expect(screen.getByRole("button", { name: "Pause" })).toBeTruthy();
  });

  it("does not autoplay with reduced motion, and shows the full path", async () => {
    const { container } = render(RouteReplayMap, { stops, year: 2025, still: true, autoplay: true });
    await Promise.resolve();
    expect(frames).toHaveLength(0);
    expect(container.querySelectorAll("[data-leg]")).toHaveLength(2);
    expect(labels(container)).toHaveLength(3);
  });

  it("draws a hotel as its own marker beside the airport it is near", () => {
    const withHotel = stopsOf(trip([...flights, segment({ id: 3, kind: "hotel", origin: "Bayview Inn", destination: "San Francisco", start_local: "2025-12-05T15:00", start_zone: "America/Los_Angeles", end_local: "2025-12-11T11:00", end_zone: "America/Los_Angeles" })]),
      { ...places, cities: [{ city: "san francisco", latitude: 37.6213, longitude: -122.379 }] });
    const { container } = render(RouteReplayMap, { stops: withHotel, year: 2025, still: true });
    expect([...container.querySelectorAll("[data-stop]")].map((g) => g.getAttribute("data-kind"))).toEqual(["airport", "airport", "stay", "airport", "airport"]);
    expect(container.querySelector("[data-stop='Bayview Inn'] rect")).toBeTruthy();
    expect(container.querySelector("[data-stop='Bayview Inn'] circle")).toBeNull();
    expect(container.querySelector("[data-label='Bayview Inn']")!.textContent).toContain("Stay: Bayview Inn, San Francisco");
    expect(container.querySelectorAll("[data-leg]")).toHaveLength(4);
    expect(container.querySelectorAll("[data-plane]")).toHaveLength(2);
  });

  const la = "America/Los_Angeles";
  const hotel = segment({ id: 3, kind: "hotel", origin: "Bayview Inn", destination: "San Francisco", start_local: "2025-12-05T15:00", start_zone: la, end_local: "2025-12-11T11:00", end_zone: la });
  const hotelStops = stopsOf(trip([...flights, hotel]), { ...places, cities: [{ city: "san francisco", latitude: 37.6213, longitude: -122.379 }] });
  const viewBox = (container: HTMLElement) => container.querySelector("svg")!.getAttribute("viewBox")!.split(" ").map(Number);

  it("sends a car from the airport to the hotel, zooming in after the flight and back out before the next one", async () => {
    const { container } = render(RouteReplayMap, { stops: hotelStops, year: 2025, still: false });
    expect(viewBox(container)).toEqual([0, 0, 960, 520]);
    await fireEvent.click(screen.getByRole("button", { name: "Play" }));
    advance(3750);
    await Promise.resolve();
    expect(container.querySelector("[data-car='1']")!.getAttribute("data-flying")).toBe("true");
    expect(container.querySelector("[data-car='1']")!.closest("[aria-hidden='true']")).toBeTruthy();
    expect(container.querySelector("svg")!.getAttribute("data-zoomed")).toBe("true");
    expect(viewBox(container)[2]).toBeLessThan(960);
    advance(6250);
    await Promise.resolve();
    expect(viewBox(container)).toEqual([0, 0, 960, 520]);
    expect(container.querySelector("svg")!.getAttribute("data-zoomed")).toBe("false");
  });

  it("returns to the whole map when scrubbed to the start or the end", async () => {
    const { container } = render(RouteReplayMap, { stops: hotelStops, year: 2025, still: false });
    const slider = screen.getByRole("slider", { name: "Position along the route" });
    await fireEvent.input(slider, { target: { value: "1500" } });
    expect(viewBox(container)[2]).toBeLessThan(960);
    await fireEvent.input(slider, { target: { value: "0" } });
    expect(viewBox(container)).toEqual([0, 0, 960, 520]);
    await fireEvent.input(slider, { target: { value: "4000" } });
    expect(viewBox(container)).toEqual([0, 0, 960, 520]);
  });

  it("sends a boat along a cruise", async () => {
    const cruise = segment({ id: 5, kind: "cruise", origin: "San Francisco", destination: "San Francisco", start_local: "2025-12-09T16:00", start_zone: la, end_local: "2025-12-13T07:00", end_zone: la,
      itinerary: [{ name: "Napa", zone: la, arrive_local: "2025-12-11T08:00", depart_local: "2025-12-11T17:00" }] });
    const ship = stopsOf(trip([cruise]), { ...places, cities: [{ city: "san francisco", latitude: 37.6213, longitude: -122.379 }, { city: "napa", latitude: 38.2975, longitude: -122.2869 }] });
    const { container } = render(RouteReplayMap, { stops: ship, year: 2025, still: false });
    await fireEvent.click(screen.getByRole("button", { name: "Play" }));
    advance(1500);
    await Promise.resolve();
    expect(container.querySelector("[data-boat='0']")).toBeTruthy();
    expect(container.querySelector("[data-car]")).toBeNull();
  });

  it("with reduced motion keeps the whole map, with no zoom and static icons", () => {
    const far = stopsOf(trip([...flights, segment({ id: 3, kind: "hotel", origin: "Bay Lodge", destination: "Monterey", start_local: "2025-12-05T15:00", start_zone: la, end_local: "2025-12-11T11:00", end_zone: la })]),
      { ...places, stays: [{ segment_id: 3, latitude: 36.6, longitude: -121.9, precision: "city" }] });
    const { container } = render(RouteReplayMap, { stops: far, year: 2025, still: true });
    expect(viewBox(container)).toEqual([0, 0, 960, 520]);
    expect(container.querySelector("svg")!.getAttribute("data-zoomed")).toBe("false");
    expect(container.querySelector("[data-car]")!.getAttribute("data-flying")).toBe("false");
    expect(container.querySelector("[data-plane]")!.getAttribute("data-flying")).toBe("false");
    expect(container.querySelector(".animate-ping")).toBeNull();
  });

  it("speeds the replay up with the speed button, cycling 1×, 2×, 4× and back", async () => {
    render(RouteReplayMap, { stops, year: 2025, still: false });
    const slider = screen.getByRole("slider", { name: "Position along the route" }) as HTMLInputElement;
    await fireEvent.click(screen.getByRole("button", { name: "Play" }));
    await fireEvent.click(screen.getByRole("button", { name: "Playback speed 1×" }));
    advance(1500);
    await Promise.resolve();
    expect(slider.value).toBe("2000");
    await fireEvent.click(screen.getByRole("button", { name: "Playback speed 2×" }));
    await fireEvent.click(screen.getByRole("button", { name: "Playback speed 4×" }));
    expect(screen.getByRole("button", { name: "Playback speed 1×" })).toBeTruthy();
  });

  it("plays a 25-stop trip over fifty seconds, with each town's label lit as the path reaches it", async () => {
    const towns = Array.from({ length: 25 }, (_, i) => ({ name: `Town ${i}`, city: `Town ${i}`, code: null, kind: "place" as const, latitude: 30 + i * 0.6, longitude: -100 + i * 0.9, from: "2025-12-05", to: "2025-12-05", via: i === 0 ? null : ("car" as const), back: false }));
    const { container } = render(RouteReplayMap, { stops: towns, year: 2025, still: false });
    await fireEvent.click(screen.getByRole("button", { name: "Play" }));
    advance(25000);
    await Promise.resolve();
    expect(screen.getByRole("button", { name: "Pause" })).toBeTruthy();
    expect(labels(container)).toEqual(["Town 12"]);
    advance(24000);
    await Promise.resolve();
    expect(labels(container)).toEqual(["Town 23"]);
    advance(1000);
    await Promise.resolve();
    advance(2500);
    await Promise.resolve();
    expect(screen.getByRole("button", { name: "Replay" })).toBeTruthy();
  });
});

