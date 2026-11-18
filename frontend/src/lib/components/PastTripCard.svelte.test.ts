// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/svelte";
import { fireEvent } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));

import { api } from "$lib/api";
import type { TripPlaces } from "$lib/api-types";
import { app } from "$lib/app.svelte";
import { segment, state, trip } from "../../test/fixtures";
import PastTripCard from "./PastTripCard.svelte";

const TODAY = "2026-10-05";
const traveller = (id: number, name: string) => ({ id, person_id: id, name, seat: null });
const lisbon = trip([segment({ id: 1, trip_id: 9, start_local: "2026-09-03T09:00", end_local: "2026-09-10T10:00", travelers: [traveller(1, "Ada Brook"), traveller(2, "June Brook")] })], { id: 9, name: "Lisbon + Alentejo", destination: "Portugal", start_date: "2026-09-03", end_date: "2026-09-10" });
const card = () => screen.getByRole("link");

beforeEach(() => { vi.mocked(api).mockReset(); vi.mocked(api).mockRejectedValue(new Error("down")); });
afterEach(() => { vi.useRealTimers(); app.state = null; });

describe("PastTripCard", () => {
  it("is one link to the trip's page, named by its dates, nights, distance, photos and people", () => {
    render(PastTripCard, { trip: lisbon, today: TODAY, photos: 168, covers: [11, 12, 13], distance: "534 mi" });
    expect(screen.getAllByRole("link")).toHaveLength(1);
    expect(card()).toHaveAttribute("href", "#trip/9");
    expect(card()).toHaveAccessibleName("Lisbon + Alentejo, Sep 3–10, 7 nights, 534 mi, 168 photos, Ada Brook and June Brook");
  });

  it("hides the mosaic, the pill and the avatars from a screen reader", () => {
    render(PastTripCard, { trip: lisbon, today: TODAY, photos: 168, covers: [11, 12, 13], distance: "534 mi" });
    const mosaic = within(card()).getByTestId("photo-pill").closest("[aria-hidden='true']");
    expect(mosaic).toBe(within(card()).getByTestId("past-mosaic"));
    expect(within(card()).getByTestId("avatar-stack").closest("[aria-hidden='true']")).toBe(within(card()).getByTestId("past-footer"));
  });

  it("shows the count in a pill and one large photo with two small, from the thumbnail route", () => {
    render(PastTripCard, { trip: lisbon, today: TODAY, photos: 1234, covers: [11, 12, 13] });
    expect(screen.getByTestId("photo-pill")).toHaveTextContent("1,234");
    const pictures = [...card().querySelectorAll("img")];
    expect(pictures.map((i) => i.getAttribute("src"))).toEqual(["/api/photos/11/thumbnail", "/api/photos/12/thumbnail", "/api/photos/13/thumbnail"]);
    expect(pictures.every((i) => i.getAttribute("loading") === "lazy" && i.getAttribute("alt") === "")).toBe(true);
    expect(pictures[0].className).toContain("row-span-2");
  });

  it("fills the mosaic with what it has when a trip has one or two photos", () => {
    const { unmount } = render(PastTripCard, { trip: lisbon, today: TODAY, photos: 1, covers: [11] });
    expect(card().querySelectorAll("img")).toHaveLength(1);
    expect(card()).toHaveAccessibleName(/, 1 photo, /);
    unmount();
    render(PastTripCard, { trip: lisbon, today: TODAY, photos: 2, covers: [11, 12] });
    expect(card().querySelectorAll("img")).toHaveLength(2);
  });

  it("draws the trip's name over the photo and the destination only when there is room", () => {
    const { unmount } = render(PastTripCard, { trip: lisbon, today: TODAY, photos: 3, covers: [11, 12, 13] });
    expect(within(card()).getByText("Lisbon + Alentejo")).toBeInTheDocument();
    expect(within(card()).queryByText("Portugal")).toBeNull();
    unmount();
    render(PastTripCard, { trip: lisbon, today: TODAY, photos: 3, covers: [11, 12, 13], roomy: true });
    expect(within(card()).getByText("Portugal")).toBeInTheDocument();
  });

  it("puts the dates in the footer in the strong colour, with nights and distance after", () => {
    render(PastTripCard, { trip: lisbon, today: TODAY, photos: 3, covers: [11], distance: "534 mi" });
    const dates = within(card()).getByText("Sep 3–10");
    expect(dates.className).toContain("text-foreground");
    expect(dates.className).toContain("font-semibold");
    expect(dates.parentElement).toHaveTextContent("Sep 3–10 7 nights 534 mi");
  });

  it("keeps the card with no pill and no photos when the viewer may see none", () => {
    render(PastTripCard, { trip: lisbon, today: TODAY, photos: 0, covers: [], distance: "534 mi" });
    expect(screen.queryByTestId("photo-pill")).toBeNull();
    expect(card().querySelectorAll("img")).toHaveLength(0);
    expect(card()).toHaveAccessibleName("Lisbon + Alentejo, Sep 3–10, 7 nights, 534 mi, Ada Brook and June Brook");
    expect(within(card()).getByTestId("route-tile")).toBeInTheDocument();
  });

  it("falls back to the tile when a picture can't be loaded", async () => {
    render(PastTripCard, { trip: lisbon, today: TODAY, photos: 3, covers: [11, 12, 13] });
    const first = card().querySelector("img")!;
    await fireEvent.error(first);
    expect([...card().querySelectorAll("img")].map((i) => i.getAttribute("src"))).toEqual(["/api/photos/12/thumbnail", "/api/photos/13/thumbnail"]);
    for (const img of [...card().querySelectorAll("img")]) await fireEvent.error(img);
    expect(card().querySelectorAll("img")).toHaveLength(0);
    expect(within(card()).getByTestId("route-tile")).toBeInTheDocument();
  });

  it("shows the trip's route on Apple's map when it has no photos, MapKit is on and the route can be placed", async () => {
    app.state = state({ mapkit: true });
    Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => 358 });
    Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get: () => 168 });
    const places: TripPlaces = { home: null, airports: [{ code: "JFK", city: "New York", latitude: 40.64, longitude: -73.78 }, { code: "LGA", city: "New York", latitude: 40.77, longitude: -73.87 }], cities: [], stays: [] };
    const snapshot = { trip_id: 9, url: "https://maps.example/snapshot?x", center: { latitude: 40.7, longitude: -73.8 }, zoom: 10, width: 352, height: 168 };
    vi.mocked(api).mockImplementation(async (path) => {
      if (path === "/api/trips/9/places") return places as never;
      if (String(path).startsWith("/api/map-snapshots")) return { snapshots: [snapshot] } as never;
      throw new Error("down");
    });
    const flown = trip([segment({ id: 1, trip_id: 9, origin: "JFK", destination: "LGA", start_local: "2026-09-03T19:00", end_local: "2026-09-04T07:00" })], { id: 9, name: "Out and back", start_date: "2026-09-03", end_date: "2026-09-10" });
    render(PastTripCard, { trip: flown, today: TODAY });
    await vi.waitFor(() => expect(card().querySelector("img")).not.toBeNull());
    await fireEvent.load(card().querySelector("img")!);
    expect(within(card()).getByTestId("route-tile")).toHaveAttribute("data-drawn", "true");
    expect(card().querySelector("svg path.stroke-map-route")).not.toBeNull();
    expect(screen.queryByTestId("photo-pill")).toBeNull();
    delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientWidth;
    delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientHeight;
  });

  it("keeps the plain tile with the trip's kinds when the route can't be placed", async () => {
    app.state = state({ mapkit: true });
    render(PastTripCard, { trip: lisbon, today: TODAY });
    const tile = within(card()).getByTestId("route-tile");
    await vi.waitFor(() => expect(api).toHaveBeenCalledWith("/api/trips/9/places", expect.anything()));
    expect(tile).toHaveAttribute("data-drawn", "false");
    expect(within(tile).getByTestId("trip-kinds")).toBeInTheDocument();
    expect(vi.mocked(api).mock.calls.some(([path]) => String(path).startsWith("/api/map-snapshots"))).toBe(false);
  });

  it("keeps the plain tile and asks for nothing at all when MapKit is off", async () => {
    app.state = state({ mapkit: false });
    render(PastTripCard, { trip: lisbon, today: TODAY });
    await new Promise((r) => setTimeout(r, 80));
    expect(api).not.toHaveBeenCalled();
    expect(within(within(card()).getByTestId("route-tile")).getByTestId("trip-kinds")).toBeInTheDocument();
  });

  it("asks Apple for nothing for a card with photo coverage even when every thumbnail fails to load", async () => {
    app.state = state({ mapkit: true });
    render(PastTripCard, { trip: lisbon, today: TODAY, photos: 3, covers: [11, 12, 13] });
    for (const img of [...card().querySelectorAll("img")]) await fireEvent.error(img);
    expect(card().querySelectorAll("img")).toHaveLength(0);
    await new Promise((r) => setTimeout(r, 120));
    expect(api).not.toHaveBeenCalled();
    expect(within(card()).getByTestId("route-tile")).toHaveAttribute("data-drawn", "false");
    expect(within(card()).getByTestId("trip-kinds")).toBeInTheDocument();
  });

  it("waits to look up a route until the list knows which cards have photos", async () => {
    app.state = state({ mapkit: true });
    const { rerender } = render(PastTripCard, { trip: lisbon, today: TODAY, coversKnown: false });
    await new Promise((r) => setTimeout(r, 80));
    expect(api).not.toHaveBeenCalled();
    await rerender({ trip: lisbon, today: TODAY, coversKnown: true });
    await vi.waitFor(() => expect(api).toHaveBeenCalledWith("/api/trips/9/places", expect.anything()));
  });

  it("makes no snapshot request for a card with photos, or for a trip with fewer than two stops", async () => {
    app.state = state({ mapkit: true });
    const { unmount } = render(PastTripCard, { trip: lisbon, today: TODAY, photos: 5, covers: [1, 2] });
    await new Promise((r) => setTimeout(r, 80));
    unmount();
    const one = trip([segment({ id: 1, trip_id: 9, kind: "hotel", origin: "Inn", destination: "Denver", start_local: "2026-09-03T15:00", end_local: "2026-09-05T10:00" })], { id: 9, start_date: "2026-09-03", end_date: "2026-09-05" });
    render(PastTripCard, { trip: one, today: TODAY });
    await new Promise((r) => setTimeout(r, 80));
    expect(vi.mocked(api).mock.calls.some(([path]) => String(path).startsWith("/api/map-snapshots"))).toBe(false);
  });

  it("doesn't look up a route for a trip that has none to draw", () => {
    const visit = trip([segment({ id: 1, trip_id: 9, kind: "visit", start_local: "2026-09-03T00:00", end_local: "2026-09-04T00:00" })], { id: 9, name: "Stopover", start_date: "2026-09-03", end_date: "2026-09-04" });
    render(PastTripCard, { trip: visit, today: TODAY });
    expect(api).not.toHaveBeenCalled();
  });

  it("shares one limit of four /places requests across every card on the page", async () => {
    app.state = state({ mapkit: true });
    let inFlight = 0, peak = 0, asked = 0;
    const waiting: (() => void)[] = [];
    vi.mocked(api).mockImplementation((path) => {
      if (!String(path).endsWith("/places")) return Promise.reject(new Error("down"));
      asked++; inFlight++; peak = Math.max(peak, inFlight);
      return new Promise((resolve) => { waiting.push(() => { inFlight--; resolve({ home: null, airports: [], cities: [], stays: [] } as never); }); });
    });
    const many = Array.from({ length: 10 }, (_, i) => trip([segment({ id: 100 + i, trip_id: 100 + i, start_local: "2026-09-03T09:00", end_local: "2026-09-10T10:00" })], { id: 100 + i, name: `Trip ${i}`, start_date: "2026-09-03", end_date: "2026-09-10" }));
    for (const t of many) render(PastTripCard, { trip: t, today: TODAY });
    await vi.waitFor(() => expect(asked).toBe(4));
    expect(peak).toBe(4);
    while (waiting.length) { waiting.shift()!(); await new Promise((r) => setTimeout(r, 0)); }
    await vi.waitFor(() => expect(asked).toBe(10));
    while (waiting.length) { waiting.shift()!(); await new Promise((r) => setTimeout(r, 0)); }
    expect(peak).toBe(4);
  });
});
