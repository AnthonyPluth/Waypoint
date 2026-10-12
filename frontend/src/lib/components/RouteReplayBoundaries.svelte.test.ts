// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Boundaries, Roads, Stop } from "$lib/route-replay";
import RouteReplayMap from "./RouteReplayMap.svelte";

vi.mock("$lib/map", async (original) => ({ ...(await original<typeof import("$lib/map")>()), loadCountries: async () => [] }));

const stopAt = (name: string, latitude: number, longitude: number, via: Stop["via"] = null, kind: Stop["kind"] = "stay"): Stop =>
  ({ name, city: name, code: null, kind, latitude, longitude, from: "2025-12-05T15:00", to: "2025-12-06T11:00", via, back: false });
const denver = stopAt("Denver", 39.74, -104.99), saltLake = stopAt("Salt Lake City", 40.76, -111.89);
const boundaries: Boundaries = [
  { points: [[37.0, -109.05], [41.0, -109.05]] },
  { points: [[41.0, -111.05], [41.0, -104.05]] },
];
const east: Boundaries = [...boundaries, { points: [[45.0, -75.0], [44.0, -73.4]] }];
const roads: Roads = { legs: [], interstates: [] };

let frames: ((at: number) => void)[] = [];
beforeEach(() => {
  frames = [];
  vi.stubGlobal("requestAnimationFrame", (f: (at: number) => void) => frames.push(f));
  vi.stubGlobal("cancelAnimationFrame", () => { frames = []; });
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

const drawn = (c: HTMLElement) => c.querySelectorAll("[data-testid='state-lines'] path").length;

describe("RouteReplayMap on the state lines", () => {
  it("draws the lines faintly, behind the route, hidden from assistive technology", () => {
    const { container } = render(RouteReplayMap, { stops: [denver, saltLake], year: 2025, roads, boundaries, still: true });
    const layer = container.querySelector("[data-testid='state-lines']")!;
    expect(layer.getAttribute("aria-hidden")).toBe("true");
    expect(Number(layer.getAttribute("opacity"))).toBeLessThan(1);
    expect(drawn(container)).toBe(2);
    expect(layer.compareDocumentPosition(container.querySelector("[data-testid='legs']")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(layer.querySelector("text")).toBeNull();
    expect(screen.getByLabelText("Map key").textContent).toContain("State line");
  });

  it("draws nothing, and no key entry, when the trip has no lines or none are given", () => {
    const first = render(RouteReplayMap, { stops: [denver, saltLake], year: 2025, roads, boundaries: [], still: true });
    expect(first.container.querySelector("[data-testid='state-lines']")).toBeNull();
    expect(screen.getByLabelText("Map key").textContent).not.toContain("State line");
    first.unmount();
    const second = render(RouteReplayMap, { stops: [denver, saltLake], year: 2025, still: true });
    expect(second.container.querySelector("[data-testid='state-lines']")).toBeNull();
  });

  it("leaves the lines out of a map of the whole world", () => {
    const sydney = stopAt("Sydney", -33.9, 151.2, "flight", "airport");
    const { container } = render(RouteReplayMap, { stops: [sydney, denver, saltLake], year: 2025, roads, boundaries, still: true });
    expect(container.querySelector("[data-testid='state-lines']")).toBeNull();
    expect(screen.getByLabelText("Map key").textContent).not.toContain("State line");
  });

  it("draws only the lines within the camera when it zooms in on a local run", async () => {
    const airport = stopAt("Denver airport", 39.86, -104.67, "flight", "airport");
    const newYork = stopAt("New York", 40.64, -73.78, null, "airport");
    const { container } = render(RouteReplayMap, { stops: [newYork, airport, denver, saltLake], year: 2025, roads, boundaries: east, still: false });
    expect(drawn(container)).toBe(3);
    const slider = screen.getByRole("slider", { name: "Position along the route" });
    await fireEvent.input(slider, { target: { value: "667" } });
    expect(container.querySelector("svg")!.getAttribute("data-zoomed")).toBe("true");
    expect(drawn(container)).toBe(2);
  });

  it("shows every line in view at once with reduced motion, and no controls", () => {
    const { container } = render(RouteReplayMap, { stops: [denver, saltLake], year: 2025, roads, boundaries, still: true });
    expect(drawn(container)).toBe(2);
    expect(screen.queryByRole("slider")).toBeNull();
    expect(frames).toHaveLength(0);
  });
});
