// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));

import { api } from "$lib/api";
import type { Person, PhotoSource, TripPhoto, TripPhotos as Reply } from "$lib/api-types";
import { app } from "$lib/app.svelte";
import { segment, state, trip } from "../../test/fixtures";
import TripPhotos from "./TripPhotos.svelte";

const ada: Person = { id: 1, display_name: "Ada Brook", first_name: "Ada", legal_name: null, aliases: [], member: true, links: [] };
const theo: Person = { id: 2, display_name: "Theo Brook", first_name: "Theo", legal_name: null, aliases: [], member: true, links: [] };
const stay = segment({ id: 2, kind: "hotel", origin: "Juniper House", destination: "Marlow Springs", start_local: "2026-03-01T15:00", start_zone: "America/Denver", end_local: "2026-03-04T11:00", end_zone: "America/Denver" });
const roadTrip = trip([stay], { id: 7, start_date: "2026-03-01", end_date: "2026-03-04" });
const after = Date.parse("2026-04-01T12:00:00Z");
const before = Date.parse("2026-02-01T12:00:00Z");

const photo = (id: number, extra: Partial<TripPhoto> = {}): TripPhoto => ({
  id, person_id: 1, trip_id: 7, kind: "image", taken_local: "2026-03-01T10:42", zone: "America/Denver", latitude: 39.7, longitude: -105, location_source: "exif",
  segment_id: 2, match: "place", distance_km: 3, cluster: 0, removed_at: null, ...extra,
});
const reply = (photos: TripPhoto[]): Reply => ({ photos, clusters: [], counts: { total: photos.length, located: photos.length, inferred: 0, far: 0 }, people: [] });
const source = (extra: Partial<PhotoSource> = {}): PhotoSource => ({ id: 1, person_id: 1, url: "https://immich.example", label: null, status: "ok", mine: true, last_sync: "2026-03-05T06:00", last_error: null, photos: 0, trips: 0, ...extra });
const many = (n: number, perDay = 20) => Array.from({ length: n }, (_, i) => photo(i + 1, { taken_local: `2026-03-${String(1 + Math.floor(i / perDay) % 28).padStart(2, "0")}T${String(8 + (i % 12)).padStart(2, "0")}:00` }));

let photos: TripPhoto[];
let sources: PhotoSource[];
function serve() {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === "/api/photo-sources") return { sources, permissions: [] };
    if (String(path).endsWith("/photos")) return reply(photos);
    throw new Error(`unexpected ${path}`);
  });
}

const section = () => screen.findByRole("region", { name: /^Photos/ });

beforeEach(() => {
  vi.mocked(api).mockReset();
  app.state = state();
  photos = [];
  sources = [source()];
  serve();
});
afterEach(() => { app.state = null; vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("TripPhotos", () => {
  it("shows the strip with the first photos and a +N tile that opens the gallery by day", async () => {
    photos = many(14, 7);
    render(TripPhotos, { trip: roadTrip, people: [ada], now: after });
    const found = await section();
    expect(within(found).getByRole("heading", { level: 2 }).textContent).toBe("Photos14");
    const strip = screen.getByTestId("photo-strip");
    expect(within(strip).getAllByRole("button", { name: /^Photo,/ })).toHaveLength(10);
    const plus = within(strip).getByRole("button", { name: "See all 14 photos" });
    expect(plus.textContent).toBe("+4See allSee all 14 photos");
    expect(vi.mocked(api)).toHaveBeenCalledWith("/api/trips/7/photos");
    await userEvent.click(plus);
    expect(screen.queryByTestId("photo-strip")).toBeNull();
    expect(screen.getByRole("button", { name: "Show fewer" }).getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("region", { name: "Sun, Mar 1" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Mon, Mar 2" })).toBeTruthy();
    expect(screen.getByText("Day 1 · Marlow Springs · 7 photos")).toBeTruthy();
    await waitFor(() => expect(document.activeElement?.getAttribute("data-photo")).toBe("1"));
    expect(screen.getByText("Showing all 14 photos by day")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Show fewer" }));
    expect(screen.getByTestId("photo-strip")).toBeTruthy();
    expect(screen.getByRole("button", { name: "See all 14 photos", expanded: false })).toBeTruthy();
  });

  it("has no +N tile when every photo fits in the strip", async () => {
    photos = many(3);
    render(TripPhotos, { trip: roadTrip, people: [ada], now: after });
    await section();
    expect(within(screen.getByTestId("photo-strip")).queryByRole("button", { name: /^See all/ })).toBeNull();
  });

  it("marks far and inferred photos and videos, and names whose library each is from", async () => {
    photos = [photo(1, { match: "far", distance_km: 560 }), photo(2, { location_source: "inferred", person_id: 2 }), photo(3, { kind: "video" })];
    render(TripPhotos, { trip: roadTrip, people: [ada, theo], now: after });
    await section();
    const far = screen.getByRole("button", { name: "Photo, 10:42 AM, Ada’s library, 560 km from every booking" });
    expect(far.textContent).toContain("Far");
    const inferred = screen.getByRole("button", { name: "Photo, 10:42 AM, Marlow Springs, Theo’s library, place from the itinerary" });
    expect(inferred.querySelector("[data-mark='inferred']")).toBeTruthy();
    expect(inferred.textContent).not.toContain("Far");
    const video = screen.getByRole("button", { name: "Video, 10:42 AM, near Marlow Springs, Ada’s library" });
    expect(video.querySelector("[data-mark='video']")).toBeTruthy();
    expect(far.querySelector("img")?.getAttribute("src")).toBe("/api/photos/1/thumbnail");
    expect(far.querySelector("img")?.getAttribute("loading")).toBe("lazy");
  });

  it("turns a tile that can’t load into a named picture that isn’t a control", async () => {
    photos = [photo(1, { person_id: 2 }), photo(2)];
    render(TripPhotos, { trip: roadTrip, people: [ada, theo], now: after });
    await section();
    await fireEvent.error(screen.getByRole("button", { name: /Theo’s library/ }).querySelector("img")!);
    expect(screen.getByRole("img", { name: "Photo from Theo’s library, can’t be loaded right now" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Theo’s library/ })).toBeNull();
    expect(screen.getByText("Theo’s photos can’t be loaded right now. They show again once Waypoint can reach their Immich.")).toBeTruthy();
  });

  it("with no library connected points to Settings on a trip that has started", async () => {
    sources = [];
    render(TripPhotos, { trip: roadTrip, people: [ada], now: after });
    await section();
    expect(screen.getByText("Photos from Immich can show on every trip, matched by when and where they were taken.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Connect a library in Settings" }).getAttribute("href")).toBe("#settings/photos");
  });

  it("with no library connected shows nothing on a trip still to come", async () => {
    sources = [];
    render(TripPhotos, { trip: roadTrip, people: [ada], now: before });
    await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalledWith("/api/photo-sources"));
    await Promise.resolve();
    expect(screen.queryByRole("region", { name: /^Photos/ })).toBeNull();
  });

  it("says a connected library hasn’t synced yet", async () => {
    sources = [source({ last_sync: null })];
    render(TripPhotos, { trip: roadTrip, people: [ada], now: after });
    await section();
    expect(screen.getByText("Ada’s library is connected. The first sync finds your photos; then you choose whether, and with whom, to share them on each trip.")).toBeTruthy();
  });

  it("says a trip has no photos yet once a library has synced", async () => {
    render(TripPhotos, { trip: roadTrip, people: [ada], now: after });
    await section();
    expect(screen.getByText("No photos on this trip yet.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^See all/ })).toBeNull();
  });

  it("says when the photos couldn’t be loaded and tries again", async () => {
    vi.mocked(api).mockRejectedValueOnce(new Error("offline"));
    photos = many(2);
    render(TripPhotos, { trip: roadTrip, people: [ada], now: after });
    expect(await screen.findByText("Couldn’t load the photos on this trip.")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("photo-strip")).toBeTruthy();
  });

  it("asks for nothing without a sign-in", async () => {
    app.state = state({ user: { name: null, email: null, local: true } });
    render(TripPhotos, { trip: roadTrip, people: [ada], now: after });
    await Promise.resolve();
    expect(vi.mocked(api)).not.toHaveBeenCalled();
    expect(screen.queryByRole("region", { name: /^Photos/ })).toBeNull();
  });

  it("ignores the answer for a trip it has since left", async () => {
    let answerFirst: (r: Reply) => void = () => {};
    vi.mocked(api).mockImplementation(async (path) => {
      if (path === "/api/trips/7/photos") return new Promise<Reply>((resolve) => { answerFirst = resolve; });
      if (path === "/api/trips/8/photos") return reply([photo(80, { trip_id: 8 })]);
      return { sources, permissions: [] };
    });
    const view = render(TripPhotos, { trip: roadTrip, people: [ada], now: after });
    await view.rerender({ trip: { ...roadTrip, id: 8 }, people: [ada], now: after });
    expect(await screen.findByRole("button", { name: /^Photo,/ })).toBeTruthy();
    answerFirst(reply(many(5)));
    await Promise.resolve();
    await Promise.resolve();
    expect(screen.getAllByRole("button", { name: /^Photo,/ })).toHaveLength(1);
    expect(screen.getByRole("button", { name: /^Photo,/ }).getAttribute("data-photo")).toBe("80");
  });

  it("renders the strip of a 2,000-photo trip quickly and mounts the gallery’s tiles as it scrolls", async () => {
    const watching: { cb: IntersectionObserverCallback; el: Element }[] = [];
    vi.stubGlobal("IntersectionObserver", class {
      constructor(private cb: IntersectionObserverCallback) {}
      observe(el: Element) { watching.push({ cb: this.cb, el }); }
      disconnect() { watching.length = 0; }
      unobserve() {}
      takeRecords() { return []; }
    });
    photos = many(2000);
    const started = performance.now();
    render(TripPhotos, { trip: roadTrip, people: [ada], now: after });
    await screen.findByTestId("photo-strip");
    expect(performance.now() - started).toBeLessThan(1500);
    expect(document.querySelectorAll("#trip-photos-gallery img")).toHaveLength(10);
    await userEvent.click(screen.getAllByRole("button", { name: "See all 2000 photos" })[0]);
    const mounted = () => document.querySelectorAll("#trip-photos-gallery img").length;
    const first = mounted();
    expect(first).toBeGreaterThan(0);
    expect(first).toBeLessThan(100);
    expect(screen.getByText(`Showing ${first} of 2000 photos`)).toBeTruthy();
    await waitFor(() => expect(watching.length).toBe(1));
    const { cb, el } = watching[0];
    cb([{ isIntersecting: true, target: el } as unknown as IntersectionObserverEntry], {} as IntersectionObserver);
    await waitFor(() => expect(mounted()).toBeGreaterThan(first));
    expect(mounted()).toBeLessThan(200);
  });

  it("shows more days from the button, moving focus to the first new photo and saying how many", async () => {
    photos = many(120, 30);
    render(TripPhotos, { trip: roadTrip, people: [ada], now: after });
    await userEvent.click((await screen.findAllByRole("button", { name: "See all 120 photos" }))[0]);
    expect(screen.getByText("Showing 60 of 120 photos")).toBeTruthy();
    const button = screen.getByRole("button", { name: "Show more days" });
    expect(button.getAttribute("aria-describedby")).toBe("trip-photos-count");
    await userEvent.click(button);
    expect(screen.getByText("Loaded 60 more photos, 120 of 120 shown")).toBeTruthy();
    await waitFor(() => expect(document.activeElement?.getAttribute("data-photo")).toBe("61"));
    expect(screen.queryByRole("button", { name: "Show more days" })).toBeNull();
  });

  it("opens the viewer on a tile and gives focus back to it", async () => {
    photos = many(3);
    render(TripPhotos, { trip: roadTrip, people: [ada], now: after });
    await section();
    const second = screen.getAllByRole("button", { name: /^Photo,/ })[1];
    await userEvent.click(second);
    expect(await screen.findByRole("dialog", { name: "Photo 2 of 3" })).toBeTruthy();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(second));
  });
});
