// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));

import { api } from "$lib/api";
import type { TripPlaces } from "$lib/api-types";
import { app } from "$lib/app.svelte";
import { project } from "$lib/card-map";
import { clearRouteCache } from "$lib/driving-routes";
import { clearSnapshots } from "$lib/map-snapshots";
import { segment, state, trip } from "../../test/fixtures";
import PastTripCard from "./PastTripCard.svelte";

const TODAY = "2026-10-05";
const DENVER = { latitude: 39.74, longitude: -104.99 };
const SALT_LAKE = { latitude: 40.76, longitude: -111.89 };
const FRAME = { center: { latitude: 40.27, longitude: -108.43 }, zoom: 5, width: 352, height: 168 };
const ADDRESS = "https://maps.example/snapshot?area=one";

const places = (more: Partial<TripPlaces> = {}): TripPlaces => ({
  home: null, airports: [], cities: [], stays: [{ segment_id: 91, ...DENVER, precision: "city" }, { segment_id: 92, ...SALT_LAKE, precision: "city" }],
  ...more,
});
const stay = (id: number, tripId: number, name: string, start: string, end: string) => segment({ id, trip_id: tripId, kind: "hotel", origin: name, destination: name, start_local: start, end_local: end });
const driven = (id = 9) => trip([stay(91, id, "Denver", "2026-09-03T15:00", "2026-09-05T10:00"), stay(92, id, "Salt Lake City", "2026-09-05T15:00", "2026-09-08T10:00")], { id, name: `Road trip ${id}`, start_date: "2026-09-03", end_date: "2026-09-08" });
const flown = trip([segment({ id: 1, trip_id: 8, kind: "flight", origin: "DEN", destination: "SLC", start_local: "2026-09-03T19:00", end_local: "2026-09-03T21:00" })], { id: 8, name: "Quick hop", start_date: "2026-09-03", end_date: "2026-09-10" });
const airports = [{ code: "DEN", city: "Denver", ...DENVER }, { code: "SLC", city: "Salt Lake City", ...SALT_LAKE }];

type Served = { places?: TripPlaces; snapshots?: unknown; roads?: unknown; fail?: string };
const serve = (served: Served = {}) => vi.mocked(api).mockImplementation(async (path) => {
  const text = String(path);
  if (text.endsWith("/places")) return (served.places ?? places()) as never;
  if (text.startsWith("/api/map-snapshots")) {
    if (served.fail === "snapshots") throw new Error("down");
    const q = new URLSearchParams(text.split("?")[1]);
    return (served.snapshots ?? { snapshots: q.getAll("trip").map((t) => ({ trip_id: Number(t), url: ADDRESS, ...FRAME })) }) as never;
  }
  if (text.startsWith("/api/driving-routes")) return (served.roads ?? { trips: [] }) as never;
  throw new Error("down");
});
const asked = (prefix: string) => vi.mocked(api).mock.calls.filter(([path]) => String(path).startsWith(prefix));
const image = (container: HTMLElement) => container.querySelector<HTMLImageElement>("[data-testid='route-tile'] img");
const tile = () => screen.getByTestId("route-tile");
const pending = () => screen.getByTestId("kinds-tile").dataset.pending;
const legs = (container: HTMLElement) => [...container.querySelectorAll("[data-testid='route-overlay'] g path")].map((p) => p.getAttribute("d") ?? "");
const dots = (container: HTMLElement) => [...container.querySelectorAll("[data-testid='route-overlay'] circle")];
const anyone = vi.fn();

const size = (width: number, height: number) => {
  Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => width });
  Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get: () => height });
};

beforeEach(() => {
  vi.mocked(api).mockReset();
  anyone.mockReset();
  clearSnapshots();
  clearRouteCache();
  size(358, 168);
  app.state = state({ mapkit: true });
  app.offline = false;
});
afterEach(() => {
  delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientWidth;
  delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientHeight;
  app.state = null;
  app.offline = false;
});

describe("a Past card's map on Apple's snapshot", () => {
  it("asks for the card's places and then its address, once, for the card's own size and the viewer's language", async () => {
    serve();
    const { container } = render(PastTripCard, { trip: driven(9), today: TODAY });
    await waitFor(() => expect(image(container)).not.toBeNull());
    expect(asked("/api/trips/9/places")).toHaveLength(1);
    expect(asked("/api/map-snapshots")).toHaveLength(1);
    const query = new URLSearchParams(String(asked("/api/map-snapshots")[0][0]).split("?")[1]);
    expect([query.getAll("trip"), query.get("w"), query.get("h"), query.get("lang")]).toEqual([["9"], "352", "168", navigator.language]);
  });

  it("loads the address as a lazy, decorative image that sends no referrer, and shows the kinds at half strength until it arrives", async () => {
    serve();
    const { container } = render(PastTripCard, { trip: driven(9), today: TODAY });
    expect(pending()).toBe("true");
    await waitFor(() => expect(image(container)).not.toBeNull());
    const img = image(container)!;
    expect(img.getAttribute("src")).toBe(ADDRESS);
    expect([img.getAttribute("loading"), img.getAttribute("referrerpolicy"), img.getAttribute("alt")]).toEqual(["lazy", "no-referrer", ""]);
    expect(pending()).toBe("true");
    expect(tile()).toHaveAttribute("data-drawn", "false");
    expect(container.querySelector("[data-testid='route-overlay']")).toBeNull();
    expect(screen.getByTestId("kinds-tile").className).toContain("opacity-50");
  });

  it("draws the route and the stops on the image once it has loaded, and takes the kinds away", async () => {
    serve();
    const { container } = render(PastTripCard, { trip: driven(9), today: TODAY });
    await waitFor(() => expect(image(container)).not.toBeNull());
    await fireEvent.load(image(container)!);
    expect(tile()).toHaveAttribute("data-drawn", "true");
    expect(legs(container)).toHaveLength(1);
    expect(legs(container)[0]).toMatch(/^M[\d.]+,[\d.]+ L[\d.]+,[\d.]+$/);
    expect(dots(container)).toHaveLength(2);
    expect(screen.queryByTestId("kinds-tile")).toBeNull();
    expect(container.querySelector("[data-testid='route-overlay']")!.getAttribute("viewBox")).toBe("0 0 352 168");
  });

  it("puts each stop where Web Mercator puts it for the centre and zoom the server chose", async () => {
    serve();
    const { container } = render(PastTripCard, { trip: driven(9), today: TODAY });
    await waitFor(() => expect(image(container)).not.toBeNull());
    await fireEvent.load(image(container)!);
    const [first, second] = dots(container).map((d) => [Number(d.getAttribute("cx")), Number(d.getAttribute("cy"))]);
    for (const [got, place] of [[first, DENVER], [second, SALT_LAKE]] as const) {
      const want = project(place, FRAME);
      expect(got[0]).toBeCloseTo(want.x, 6);
      expect(got[1]).toBeCloseTo(want.y, 6);
    }
    expect(first[0]).toBeGreaterThan(second[0]);
  });

  it("draws the stored Apple road for a drive when the server has one, and a straight line for the rest", async () => {
    const road = [[39.74, -104.99], [40.1, -106.5], [40.5, -109.2], [40.76, -111.89]];
    serve({ roads: { trips: [{ trip_id: 9, routes: [{ start: DENVER, end: SALT_LAKE, path: road }] }] } });
    const { container } = render(PastTripCard, { trip: driven(9), today: TODAY });
    await waitFor(() => expect(image(container)).not.toBeNull());
    await fireEvent.load(image(container)!);
    await waitFor(() => expect(legs(container)[0].match(/[ML]/g)).toHaveLength(road.length));
    expect(asked("/api/driving-routes")).toHaveLength(1);
    expect(String(asked("/api/driving-routes")[0][0])).toBe("/api/driving-routes?trip=9");
  });

  it("draws a flight as an arc in the route colour, with its airports in the airport colour, and asks for no road", async () => {
    serve({ places: places({ stays: [], airports }) });
    const { container } = render(PastTripCard, { trip: flown, today: TODAY });
    await waitFor(() => expect(image(container)).not.toBeNull());
    await fireEvent.load(image(container)!);
    expect(container.querySelector("[data-testid='route-overlay'] path.stroke-map-route")).not.toBeNull();
    expect(legs(container)[0]).toContain(" Q");
    expect(dots(container).every((d) => d.getAttribute("class")!.includes("fill-map-airport"))).toBe(true);
    expect(asked("/api/driving-routes")).toHaveLength(0);
  });

  it("keeps the image drawn when the list reloads the trip and gives the card a fresh copy of it", async () => {
    serve();
    const { container, rerender } = render(PastTripCard, { trip: driven(9), today: TODAY });
    await waitFor(() => expect(image(container)).not.toBeNull());
    await fireEvent.load(image(container)!);
    await rerender({ trip: { ...driven(9), name: "Renamed" }, today: TODAY });
    await new Promise((r) => setTimeout(r, 80));
    expect(tile()).toHaveAttribute("data-drawn", "true");
    expect(asked("/api/map-snapshots")).toHaveLength(1);
  });

  it("gives every card on a page the same limit of four places lookups and a single batched address request", async () => {
    serve();
    const cards = [1, 2, 3].map((n) => render(PastTripCard, { trip: driven(20 + n), today: TODAY }));
    await waitFor(() => expect(cards.every((c) => image(c.container) !== null)).toBe(true));
    expect(asked("/api/map-snapshots")).toHaveLength(1);
    expect(new URLSearchParams(String(asked("/api/map-snapshots")[0][0]).split("?")[1]).getAll("trip")).toEqual(["21", "22", "23"]);
  });
});

describe("when there is no map to show", () => {
  it.each([["MapKit off", () => { app.state = state({ mapkit: false }); }], ["no state yet", () => { app.state = null; }], ["offline", () => { app.offline = true; }]])("asks for nothing with %s, and the kinds tile shows at full strength", async (_name, setUp) => {
    setUp();
    serve();
    const { container } = render(PastTripCard, { trip: driven(9), today: TODAY });
    await new Promise((r) => setTimeout(r, 80));
    expect(vi.mocked(api)).not.toHaveBeenCalled();
    expect(image(container)).toBeNull();
    expect(tile()).toHaveAttribute("data-drawn", "false");
    expect(pending()).toBe("false");
    expect(screen.getByTestId("trip-kinds")).toBeInTheDocument();
  });

  it("makes no request for a card with photos", async () => {
    serve();
    render(PastTripCard, { trip: driven(9), today: TODAY, photos: 3, covers: [11, 12, 13] });
    await new Promise((r) => setTimeout(r, 80));
    expect(vi.mocked(api)).not.toHaveBeenCalled();
    expect(screen.queryByTestId("route-tile")).toBeNull();
  });

  it("asks for no address when the trip has fewer than two stops it can place, and shows the kinds at full strength", async () => {
    serve({ places: places({ stays: [places().stays[0]] }) });
    const { container } = render(PastTripCard, { trip: driven(9), today: TODAY });
    await waitFor(() => expect(pending()).toBe("false"));
    await new Promise((r) => setTimeout(r, 80));
    expect(asked("/api/map-snapshots")).toHaveLength(0);
    expect(image(container)).toBeNull();
    expect(screen.getByTestId("trip-kinds")).toBeInTheDocument();
  });

  it("asks for nothing for a trip with fewer than two possible stops, or one that hasn't ended", async () => {
    serve();
    const visit = trip([segment({ id: 1, trip_id: 9, kind: "visit", start_local: "2026-09-03T00:00", end_local: "2026-09-04T00:00" })], { id: 9, start_date: "2026-09-03", end_date: "2026-09-04" });
    render(PastTripCard, { trip: visit, today: TODAY });
    render(PastTripCard, { trip: driven(10), today: "2026-09-04" });
    await new Promise((r) => setTimeout(r, 80));
    expect(vi.mocked(api)).not.toHaveBeenCalled();
  });

  it("shows the kinds at full strength, with no image and no message, when the server leaves the trip out", async () => {
    serve({ snapshots: { snapshots: [] } });
    const { container } = render(PastTripCard, { trip: driven(9), today: TODAY });
    await waitFor(() => expect(pending()).toBe("false"));
    expect(image(container)).toBeNull();
    expect(screen.getByTestId("trip-kinds")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/couldn.t|failed|error/i);
  });

  it("shows the kinds at full strength when the address can't be had, and doesn't ask again", async () => {
    serve({ fail: "snapshots" });
    render(PastTripCard, { trip: driven(9), today: TODAY });
    await waitFor(() => expect(pending()).toBe("false"));
    await new Promise((r) => setTimeout(r, 120));
    expect(asked("/api/map-snapshots")).toHaveLength(1);
    expect(asked("/api/driving-routes")).toHaveLength(0);
  });

  it("shows the kinds at full strength when the image fails, takes the image away, and doesn't try again until the page reloads", async () => {
    serve();
    const { container } = render(PastTripCard, { trip: driven(9), today: TODAY });
    await waitFor(() => expect(image(container)).not.toBeNull());
    await fireEvent.error(image(container)!);
    expect(image(container)).toBeNull();
    expect(container.querySelector("[data-testid='route-overlay']")).toBeNull();
    expect(pending()).toBe("false");
    expect(screen.getByTestId("kinds-tile").className).not.toContain("opacity-50");
    expect(tile()).toHaveAttribute("data-drawn", "false");
    await new Promise((r) => setTimeout(r, 120));
    expect(asked("/api/map-snapshots")).toHaveLength(1);
  });

  it("doesn't ask for an address before the card has a size, and asks as soon as it does", async () => {
    size(0, 0);
    serve();
    const { unmount } = render(PastTripCard, { trip: driven(9), today: TODAY });
    await waitFor(() => expect(asked("/api/trips/9/places")).toHaveLength(1));
    await new Promise((r) => setTimeout(r, 80));
    expect(asked("/api/map-snapshots")).toHaveLength(0);
    unmount();
  });

  it("asks within what Apple draws: sides of at least 50 and at most 640 pixels", async () => {
    size(5000, 900);
    serve();
    render(PastTripCard, { trip: driven(9), today: TODAY });
    await waitFor(() => expect(asked("/api/map-snapshots")).toHaveLength(1));
    const query = new URLSearchParams(String(asked("/api/map-snapshots")[0][0]).split("?")[1]);
    expect([query.get("w"), query.get("h")]).toEqual(["640", "640"]);
  });
});
