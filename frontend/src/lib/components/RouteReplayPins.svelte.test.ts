// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PhotoCluster, TripPhoto, TripPlaces } from "$lib/api-types";
import { clusterInfos } from "$lib/photos";
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
  roads: { legs: [], interstates: [] },
  boundaries: [],
};
const stay = segment({ id: 3, kind: "hotel", origin: "Bay Inn", destination: "San Francisco", start_local: "2025-12-05T15:00", start_zone: "America/Los_Angeles", end_local: "2025-12-11T11:00", end_zone: "America/Los_Angeles" });
const flights = [
  segment({ id: 1, origin: "MSP", destination: "SFO", start_local: "2025-12-05T08:00", start_zone: "America/Chicago", end_local: "2025-12-05T10:30", end_zone: "America/Los_Angeles" }),
  segment({ id: 2, origin: "SFO", destination: "MSP", start_local: "2025-12-11T13:00", start_zone: "America/Los_Angeles", end_local: "2025-12-11T18:50", end_zone: "America/Chicago" }),
];
const stops = stopsOf(trip(flights), places);
const segments = new Map([stay, ...flights].map((s) => [s.id, s]));

const photo = (id: number, cluster: number | null, extra: Partial<TripPhoto> = {}): TripPhoto => ({
  id, person_id: 1, trip_id: 1, kind: "image", taken_local: "2025-12-07T10:00", zone: "America/Los_Angeles", latitude: 37.8, longitude: -122.4, location_source: "exif",
  segment_id: 3, match: "place", distance_km: 2, cluster, removed_at: null, ...extra,
});
const bay: PhotoCluster = { latitude: 37.8, longitude: -122.4, count: 40, first: "2025-12-07T10:00", last: "2025-12-09T18:00", cover: 11, inferred: false };
const hollow: PhotoCluster = { latitude: 44.9, longitude: -93.2, count: 14, first: "2025-12-05T07:30", last: "2025-12-05T07:50", cover: 21, inferred: true };
const distant: PhotoCluster = { latitude: 34.0, longitude: -118.2, count: 3, first: "2025-12-11T15:00", last: "2025-12-11T16:00", cover: 31, inferred: false };
const clusters = [bay, hollow, distant];
const photos = [
  photo(11, 0), photo(12, 0, { taken_local: "2025-12-09T18:00" }),
  photo(21, 1, { taken_local: "2025-12-05T07:30", location_source: "inferred", segment_id: 1, latitude: 44.9, longitude: -93.2 }),
  ...[31, 32, 33].map((id) => photo(id, 2, { taken_local: "2025-12-11T15:00", match: "far", distance_km: 612, segment_id: null })),
  photo(41, null, { latitude: null, longitude: null, match: "time" }),
];
const infos = clusterInfos(photos, clusters, segments);

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

const said = (text: string | null) => (text ?? "").replace(/\s/g, " ");
const pins = (container: HTMLElement) => [...container.querySelectorAll<HTMLElement>("[data-pin]")];
const slide = (to: number) => fireEvent.input(screen.getByRole("slider", { name: "Position along the route" }), { target: { value: String(to) } });

describe("photo pins on the route map", () => {
  it("draws one button per cluster with the count inside and a name that says where and when", () => {
    const { container } = render(RouteReplayMap, { stops, year: 2025, still: true, infos });
    expect(pins(container).map((p) => said(p.getAttribute("aria-label")))).toEqual([
      "14 photos placed from the itinerary near MSP, Dec 5",
      "40 photos near San Francisco, Dec 7 – 9",
      "3 photos, 612 km from every booking, Dec 11",
    ]);
    expect(pins(container).map((p) => p.textContent?.trim())).toEqual(["14", "40", "3"]);
    expect(screen.getByRole("button", { name: /^40 photos near San Francisco, Dec 7/ })).toBeTruthy();
  });

  it("fills a pin with GPS photos, leaves a pin of itinerary-placed photos hollow and puts a dot on one with far photos", () => {
    const { container } = render(RouteReplayMap, { stops, year: 2025, still: true, infos });
    const [inferred, filled, far] = pins(container);
    expect(inferred.dataset.hollow).toBe("true");
    expect(inferred.querySelector("[data-disc]")!.className).toContain("bg-map-sea");
    expect(filled.dataset.hollow).toBe("false");
    expect(filled.querySelector("[data-disc]")!.className).toContain("bg-map-photo");
    expect(filled.querySelector("[data-far-dot]")).toBeNull();
    expect(far.querySelector("[data-far-dot]")).toBeTruthy();
  });

  it("sizes each pin by its count, 16 px plus 4 px for every doubling, at most 40, inside a button of at least 24 px", () => {
    const { container } = render(RouteReplayMap, { stops, year: 2025, still: true, infos });
    expect(pins(container).map((p) => p.querySelector<HTMLElement>("[data-disc]")!.style.width)).toEqual(["31px", "37px", "22px"]);
    expect(pins(container).map((p) => p.style.width)).toEqual(["31px", "37px", "24px"]);
  });

  it("puts the pins in time order in the tab order, as buttons the keyboard reaches", () => {
    const { container } = render(RouteReplayMap, { stops, year: 2025, still: true, infos });
    expect(pins(container).map((p) => p.dataset.pin)).toEqual(["1", "0", "2"]);
    for (const p of pins(container)) {
      expect(p.tagName).toBe("BUTTON");
      expect(p.getAttribute("tabindex")).toBeNull();
    }
    pins(container)[0].focus();
    expect(document.activeElement).toBe(pins(container)[0]);
  });

  it("extends the map's name and key, and leaves them alone with no photos", () => {
    const { container, unmount } = render(RouteReplayMap, { stops, year: 2025, still: true, infos });
    expect(screen.getByRole("img", { name: "Map of the route, stop by stop, with photo places; the stops are listed below" })).toBeTruthy();
    const key = within(screen.getByRole("list", { name: "Map key" }));
    expect(key.getByText("Photos")).toBeTruthy();
    expect(key.getByText("Photos placed from the itinerary")).toBeTruthy();
    expect(key.getByText("Far from every booking")).toBeTruthy();
    expect(container.querySelector("[data-testid='photo-pins']")).toBeTruthy();
    unmount();
    const plain = render(RouteReplayMap, { stops, year: 2025, still: true });
    expect(screen.getByRole("img", { name: "Map of the route, stop by stop; the stops are listed below" })).toBeTruthy();
    expect(plain.container.querySelector("[data-testid='photo-pins']")).toBeNull();
    expect(within(screen.getByRole("list", { name: "Map key" })).queryByText("Photos")).toBeNull();
  });

  it("draws the map exactly as before for a trip whose photos the viewer can't see", () => {
    const none = render(RouteReplayMap, { stops, year: 2025, still: true, infos: clusterInfos([], [], segments), unlocated: 0 });
    const html = none.container.innerHTML;
    none.unmount();
    const plain = render(RouteReplayMap, { stops, year: 2025, still: true });
    expect(plain.container.innerHTML).toBe(html);
  });

  describe("selecting a pin", () => {
    it("shows a callout with the cover, the count, the dates and where, and offers the photos", async () => {
      const { container } = render(RouteReplayMap, { stops, year: 2025, still: true, infos });
      expect(screen.queryByTestId("pin-card")).toBeNull();
      await fireEvent.click(pins(container)[1]);
      const card = within(screen.getByRole("group", { name: "40 photos near San Francisco" }));
      expect(card.getByText("40 photos")).toBeTruthy();
      expect(screen.getByTestId("pin-card").textContent).toContain("near San Francisco");
      expect(screen.getByTestId("pin-card").querySelector("img")!.getAttribute("src")).toBe("/api/photos/11/thumbnail");
      expect(pins(container)[1].getAttribute("aria-pressed")).toBe("true");
      expect(card.getByRole("button", { name: "Show these photos" })).toBeTruthy();
    });

    it("raises the cluster's id when asked to show its photos", async () => {
      const onshow = vi.fn();
      const { container } = render(RouteReplayMap, { stops, year: 2025, still: true, infos, onshow });
      await fireEvent.click(pins(container)[1]);
      await fireEvent.click(screen.getByRole("button", { name: "Show these photos" }));
      expect(onshow).toHaveBeenCalledExactlyOnceWith(0);
      await fireEvent.click(pins(container)[2]);
      await fireEvent.click(screen.getByRole("button", { name: "Show these photos" }));
      expect(onshow).toHaveBeenLastCalledWith(2);
    });

    it("moves the callout to the next pin, and closes it with Close, handing focus back to the pin", async () => {
      const { container } = render(RouteReplayMap, { stops, year: 2025, still: true, infos });
      await fireEvent.click(pins(container)[1]);
      await fireEvent.click(pins(container)[2]);
      expect(screen.getAllByTestId("pin-card")).toHaveLength(1);
      expect(screen.getByRole("group", { name: "3 photos, 612 km from every booking" })).toBeTruthy();
      await fireEvent.click(screen.getByRole("button", { name: "Close" }));
      expect(screen.queryByTestId("pin-card")).toBeNull();
      await vi.waitFor(() => expect(document.activeElement).toBe(pins(container)[2]));
    });

    it("closes on Escape, and by tapping the same pin again", async () => {
      const { container } = render(RouteReplayMap, { stops, year: 2025, still: true, infos });
      await fireEvent.click(pins(container)[0]);
      expect(screen.getByTestId("pin-card")).toBeTruthy();
      await fireEvent.keyDown(pins(container)[0], { key: "Escape" });
      expect(screen.queryByTestId("pin-card")).toBeNull();
      await fireEvent.click(pins(container)[0]);
      await fireEvent.click(pins(container)[0]);
      expect(screen.queryByTestId("pin-card")).toBeNull();
    });

    it("drops the callout when its cluster goes away", async () => {
      const { container, rerender } = render(RouteReplayMap, { stops, year: 2025, still: true, infos });
      await fireEvent.click(pins(container)[1]);
      await rerender({ infos: [] });
      expect(screen.queryByTestId("pin-card")).toBeNull();
      expect(container.querySelector("[data-pin]")).toBeNull();
    });
  });

  describe("during the replay", () => {
    it("dims a pin until the replay reaches its first photo, and lights every pin at the end", async () => {
      const { container } = render(RouteReplayMap, { stops, year: 2025, still: false, infos });
      const lit = () => pins(container).map((p) => p.dataset.lit);
      expect(lit()).toEqual(["true", "false", "false"]);
      expect(pins(container)[1].className).toContain("opacity-45");
      await slide(0.6 * SCRUB_STEPS);
      expect(lit()).toEqual(["true", "true", "false"]);
      await slide(0.7 * SCRUB_STEPS);
      expect(lit()).toEqual(["true", "true", "true"]);
      expect(pins(container)[1].className).not.toContain("opacity-45");
    });

    it("pings a pin once as it lights, names it in a label card, and lets both go", async () => {
      vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
      const { container } = render(RouteReplayMap, { stops, year: 2025, still: false, infos });
      await fireEvent.click(screen.getByRole("button", { name: "Play" }));
      expect(container.querySelector("[data-ping]")).toBeNull();
      clock += 4500;
      frames.splice(0).forEach((f) => f(clock));
      await Promise.resolve();
      expect(container.querySelectorAll("[data-pin] [data-ping]").length).toBeGreaterThan(0);
      expect(screen.getByTestId("photo-label").textContent).toContain("photos");
      vi.advanceTimersByTime(2000);
      await Promise.resolve();
      expect(container.querySelector("[data-pin] [data-ping]")).toBeNull();
      expect(screen.queryByTestId("photo-label")).toBeNull();
    });

    it("with reduced motion lights every pin and pings none", () => {
      const { container } = render(RouteReplayMap, { stops, year: 2025, still: true, infos });
      expect(pins(container).map((p) => p.dataset.lit)).toEqual(["true", "true", "true"]);
      expect(container.querySelector("[data-ping]")).toBeNull();
      expect(container.querySelector("[data-pin].opacity-45")).toBeNull();
    });
  });

  describe("with no route to replay", () => {
    it("shows the photo pins alone, with no controls, stops list or route key, and says how many photos have no place", () => {
      const { container } = render(RouteReplayMap, { stops: [], year: 2025, infos, unlocated: 5 });
      expect(screen.getByRole("img", { name: "Map of where this trip’s photos were taken" })).toBeTruthy();
      expect(pins(container)).toHaveLength(3);
      expect(pins(container).every((p) => p.dataset.lit === "true")).toBe(true);
      expect(screen.queryByRole("button", { name: "Play" })).toBeNull();
      expect(screen.queryByRole("slider")).toBeNull();
      expect(screen.queryByRole("list", { name: "Stops in order" })).toBeNull();
      expect(screen.queryByRole("region", { name: "Stops list" })).toBeNull();
      const key = within(screen.getByRole("list", { name: "Map key" }));
      expect(key.queryByText("Airport")).toBeNull();
      expect(key.getByText("Photos")).toBeTruthy();
      expect(screen.getByTestId("unlocated").textContent).toBe("5 photos have no location and aren’t on the map.");
      expect(frames).toHaveLength(0);
    });

    it("says nothing about unlocated photos when there are none, and uses the singular for one", () => {
      const none = render(RouteReplayMap, { stops: [], year: 2025, infos, unlocated: 0 });
      expect(none.queryByTestId("unlocated")).toBeNull();
      none.unmount();
      render(RouteReplayMap, { stops: [], year: 2025, infos, unlocated: 1 });
      expect(screen.getByTestId("unlocated").textContent).toBe("1 photo has no location and isn’t on the map.");
    });

    it("fits a single cluster at a fixed regional zoom", () => {
      const { container } = render(RouteReplayMap, { stops: [], year: 2025, infos: infos.slice(0, 1) });
      expect(pins(container)).toHaveLength(1);
      const left = parseFloat(pins(container)[0].style.left);
      expect(left).toBeGreaterThan(40);
      expect(left).toBeLessThan(60);
    });
  });
});
