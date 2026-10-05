// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { StatsFlights } from "$lib/api-types";
import TravelMap from "./TravelMap.svelte";

const flights = {
  airports: [
    { code: "JFK", name: "John F. Kennedy International Airport", city: "New York", country: "US", visits: 6, latitude: 40.6398, longitude: -73.7789 },
    { code: "NRT", name: "Narita International Airport", city: "Tokyo", country: "JP", visits: 2, latitude: 35.772, longitude: 140.3929 },
    { code: "ZZZ", name: "ZZZ", city: null, country: null, visits: 1, latitude: null, longitude: null },
  ],
  routes: [{ a: "JFK", b: "NRT", flights: 2, distance_km: 10800, a_latitude: 40.6398, a_longitude: -73.7789, b_latitude: 35.772, b_longitude: 140.3929 }],
} as StatsFlights;

afterEach(() => vi.restoreAllMocks());

describe("TravelMap", () => {
  it("draws the countries, the airports and the routes, and shades the countries visited", async () => {
    const { container } = render(TravelMap, { flights });
    await waitFor(() => expect(container.querySelectorAll("path[data-visited]").length).toBeGreaterThan(0));
    expect(container.querySelectorAll("path").length).toBeGreaterThan(100);
    expect(container.querySelectorAll("[data-dot]")).toHaveLength(2);
    expect(container.querySelectorAll("[data-arc]")).toHaveLength(1);
    expect([...container.querySelectorAll("path[data-visited] title")].map((t) => t.textContent).sort()).toEqual(["Japan", "United States of America"]);
  });

  it("shows an airport's or a route's name and count when picked, and a tap on the land clears it", async () => {
    render(TravelMap, { flights });
    expect(screen.getByText("Tap an airport or a route for its name and count.")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /^JFK · / }));
    expect(screen.getByText("JFK · New York · John F. Kennedy International Airport: 6 visits")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "JFK – NRT: 2 flights" }));
    expect(screen.getByText("JFK – NRT: 2 flights", { selector: "span" })).toBeTruthy();
    await userEvent.unhover(screen.getByRole("button", { name: "JFK – NRT: 2 flights" }));
    await waitFor(() => expect(document.querySelectorAll("path[data-visited]").length).toBeGreaterThan(0));
    await userEvent.click(document.querySelector("path[data-visited]")!);
    expect(screen.getByText("Tap an airport or a route for its name and count.")).toBeTruthy();
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
    expect(screen.getByText("No airports to show on the map yet.")).toBeTruthy();
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
});
