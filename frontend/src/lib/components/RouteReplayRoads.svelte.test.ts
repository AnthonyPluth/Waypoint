// @vitest-environment jsdom
import { fireEvent, render, screen, within } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Roads, Stop } from "$lib/route-replay";
import RouteReplayMap from "./RouteReplayMap.svelte";

vi.mock("$lib/map", async (original) => ({ ...(await original<typeof import("$lib/map")>()), loadCountries: async () => [] }));

const stopAt = (name: string, latitude: number, longitude: number, via: Stop["via"] = null, kind: Stop["kind"] = "stay"): Stop =>
  ({ name, city: name, code: null, kind, latitude, longitude, from: "2025-12-05T15:00", to: "2025-12-06T11:00", via, back: false });
const denver = stopAt("Denver", 39.74, -104.99), saltLake = stopAt("Salt Lake City", 40.76, -111.89);
const roads: Roads = {
  legs: [{ from_segment_id: 1, to_segment_id: 2, refs: ["I-25", "I-80"], points: [[39.77, -105.0], [40.2, -105.0], [41.2, -107.5], [40.75, -111.85]] }],
  interstates: [{ ref: "I-25", points: [[39.0, -105.0], [40.2, -105.0]] }, { ref: "I-80", points: [[41.2, -107.5], [40.75, -111.85]] }],
};
const none: Roads = { legs: [], interstates: [] };

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

const list = () => within(screen.getByRole("list", { name: "Stops in order" })).getAllByRole("listitem").map((li) => li.lastElementChild?.textContent?.replace(/\s+/g, " "));
const ground = (c: HTMLElement) => c.querySelector("path[data-leg='ground']")!;

describe("RouteReplayMap on the interstates", () => {
  it("draws a road leg along the road, with the roads behind it, and names the roads in the text list", () => {
    const { container } = render(RouteReplayMap, { stops: [denver, saltLake], year: 2025, roads, still: true });
    expect(ground(container).getAttribute("d")).not.toContain("Q");
    expect(ground(container).getAttribute("data-road-leg")).toBe("I-25 I-80");
    expect([...container.querySelectorAll("[data-road]")].map((p) => p.getAttribute("data-road"))).toEqual(["I-25", "I-80"]);
    expect(list()).toEqual(["Stay in Denver, Dec 5 – 6", "Stay in Salt Lake City, Dec 5 – 6 (via I-25, I-80)"]);
    expect(screen.getByLabelText("Map key").textContent).toContain("Interstate");
  });

  it("hides the roads and their labels from assistive technology", () => {
    const { container } = render(RouteReplayMap, { stops: [denver, saltLake], year: 2025, roads, still: true });
    const layer = container.querySelector("[data-testid='interstates']")!;
    expect(layer.closest("[aria-hidden='true']") ?? layer.getAttribute("aria-hidden")).toBeTruthy();
    const shields = container.querySelector("[data-testid='shields']")!;
    expect(shields.getAttribute("aria-hidden")).toBe("true");
    expect([...shields.querySelectorAll("[data-shield]")].map((s) => s.getAttribute("data-shield")).sort()).toEqual(["I-25", "I-80"]);
    expect(container.querySelector("[data-testid='movers']")!.getAttribute("aria-hidden")).toBe("true");
  });

  it("keeps the curve and draws no roads when the trip has none", () => {
    const { container } = render(RouteReplayMap, { stops: [denver, saltLake], year: 2025, roads: none, still: true });
    expect(ground(container).getAttribute("d")).toContain("Q");
    expect(ground(container).hasAttribute("data-road-leg")).toBe(false);
    expect(container.querySelector("[data-testid='interstates']")).toBeNull();
    expect(container.querySelector("[data-testid='shields']")).toBeNull();
    expect(list()[1]).toBe("Stay in Salt Lake City, Dec 5 – 6");
    expect(screen.getByLabelText("Map key").textContent).not.toContain("Interstate");
  });

  it("works without being given any roads at all", () => {
    const { container } = render(RouteReplayMap, { stops: [denver, saltLake], year: 2025, still: true });
    expect(ground(container).getAttribute("d")).toContain("Q");
  });

  it("with reduced motion shows the road, a still car on it and no controls", () => {
    const { container } = render(RouteReplayMap, { stops: [denver, saltLake], year: 2025, roads, still: true });
    const car = container.querySelector("[data-car]")!;
    expect(car.getAttribute("data-flying")).toBe("false");
    expect(container.querySelector("path[data-leg][stroke-dashoffset='0']")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("slider")).toBeNull();
    expect(frames).toHaveLength(0);
  });

  it("drives the car along the road while playing, and keeps the scrubber, the buttons and the full list", async () => {
    const { container } = render(RouteReplayMap, { stops: [denver, saltLake], year: 2025, roads, still: false });
    await fireEvent.click(screen.getByRole("button", { name: "Play" }));
    advance(2000);
    await Promise.resolve();
    const car = container.querySelector("[data-car='0']")!;
    expect(car.getAttribute("data-flying")).toBe("true");
    const before = car.getAttribute("transform");
    advance(1500);
    await Promise.resolve();
    expect(container.querySelector("[data-car='0']")!.getAttribute("transform")).not.toBe(before);
    const slider = screen.getByRole("slider", { name: "Position along the route" });
    await fireEvent.input(slider, { target: { value: "4000" } });
    expect(slider.getAttribute("aria-valuetext")).toContain("Salt Lake City");
    expect(screen.getByRole("button", { name: "Replay" })).toBeTruthy();
    expect(list()).toHaveLength(2);
  });

  it("draws the roads only within the camera, so the ones far from a zoomed-in leg are left out", async () => {
    const airport = stopAt("Denver airport", 39.86, -104.67, "flight", "airport");
    const newYork = stopAt("New York", 40.64, -73.78, null, "airport");
    const east: Roads = { ...roads, interstates: [...roads.interstates, { ref: "I-95", points: [[40.0, -75.0], [41.0, -73.9]] }] };
    const { container } = render(RouteReplayMap, { stops: [newYork, airport, denver, saltLake], year: 2025, roads: east, still: false });
    const drawn = () => [...container.querySelectorAll("[data-road]")].map((p) => p.getAttribute("data-road"));
    expect(drawn()).toContain("I-95");
    const slider = screen.getByRole("slider", { name: "Position along the route" });
    await fireEvent.input(slider, { target: { value: "2667" } });
    expect(container.querySelector("svg")!.getAttribute("data-zoomed")).toBe("true");
    expect(drawn()).not.toContain("I-95");
    expect(drawn()).toContain("I-25");
    expect(container.querySelector("[data-shield='I-95']")).toBeNull();
  });

  it("leaves the roads out of a map too wide to read them", () => {
    const sydney = stopAt("Sydney", -33.9, 151.2, "flight", "airport");
    const { container } = render(RouteReplayMap, { stops: [sydney, denver, saltLake], year: 2025, roads, still: true });
    expect(container.querySelector("[data-testid='interstates']")).toBeNull();
    expect([...container.querySelectorAll("path[data-leg]")].map((p) => p.getAttribute("data-road-leg"))).toEqual([null, "I-25 I-80"]);
  });
});
