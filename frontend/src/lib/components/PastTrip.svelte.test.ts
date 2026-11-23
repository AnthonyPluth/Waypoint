// @vitest-environment jsdom
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("$lib/map", async (original) => ({ ...(await original<typeof import("$lib/map")>()), loadCountries: async () => [], loadDetailedCountries: async () => [], loadFineCountries: async () => [] }));
vi.mock("$lib/mapkit", async (original) => ({ ...(await original<typeof import("$lib/mapkit")>()), loadMapkit: vi.fn() }));

import { api } from "$lib/api";
import type { Person, PhotoCluster, PhotoSharing, PhotoSource, TripPhoto, TripPhotos as Reply, TripPlaces, TripSummary } from "$lib/api-types";
import { app } from "$lib/app.svelte";
import { loadMapkit } from "$lib/mapkit";
import { fake, fakeMaps } from "../../test/fake-mapkit";
import { viewport } from "$lib/phone.svelte";
import { SCRUB_STEPS } from "$lib/route-replay";
import { segment, state, trip } from "../../test/fixtures";
import { createRawSnippet } from "svelte";
import PastTrip from "./PastTrip.svelte";

const ada: Person = { id: 1, display_name: "Ada Brook", first_name: "Ada", legal_name: null, aliases: [], member: true, links: [] };
const stay = segment({ id: 2, kind: "hotel", origin: "Juniper House", destination: "Marlow Springs", start_local: "2026-03-01T15:00", start_zone: "America/Denver", end_local: "2026-03-08T11:00", end_zone: "America/Denver" });
const there = segment({ id: 3, origin: "MSP", destination: "SFO", start_local: "2026-03-01T08:00", start_zone: "America/Chicago", end_local: "2026-03-01T10:30", end_zone: "America/Los_Angeles" });
const back = segment({ id: 4, origin: "SFO", destination: "MSP", start_local: "2026-03-08T13:00", start_zone: "America/Los_Angeles", end_local: "2026-03-08T18:50", end_zone: "America/Chicago" });
const roadTrip = trip([stay], { id: 7, name: "Spring loop", destination: "Utah", start_date: "2026-03-01", end_date: "2026-03-08" });
const flown = trip([there, stay, back], { id: 7, name: "Spring loop", destination: "Utah", start_date: "2026-03-01", end_date: "2026-03-08" });
const after = Date.parse("2026-04-01T12:00:00Z");

const places: TripPlaces = {
  home: null,
  airports: [
    { code: "MSP", city: "Minneapolis", latitude: 44.8848, longitude: -93.2223 },
    { code: "SFO", city: "San Francisco", latitude: 37.6213, longitude: -122.379 },
  ],
  cities: [], stays: [],
};
const summary: TripSummary = { days: 8, nights: 7, distance_km: 1996, flight_km: 0, road_km: 1996, road_estimated: false, states: ["Utah"], countries: ["United States"], photos: { total: 214, inferred: 3 }, kinds: { flight: 0, hotel: 1, car: 0, train: 0, cruise: 0, parking: 0, visit: 0 } };

const shot = (id: number, day = 1, extra: Partial<TripPhoto> = {}): TripPhoto => ({
  id, person_id: 1, trip_id: 7, kind: "image", taken_local: `2026-03-${String(day).padStart(2, "0")}T${String(8 + (id % 12)).padStart(2, "0")}:${String(id % 60).padStart(2, "0")}`, zone: "America/Denver", latitude: 39.7, longitude: -105, location_source: "exif",
  segment_id: 2, match: "place", distance_km: 3, cluster: 0, removed_at: null, ...extra,
});
const reply = (photos: TripPhoto[], best: number[] = [], clusters: PhotoCluster[] = []): Reply => ({ photos, clusters, counts: { total: photos.length, located: photos.length, inferred: 0, far: 0 }, people: [], best });
const source = (extra: Partial<PhotoSource> = {}): PhotoSource => ({ id: 1, person_id: 1, url: "https://immich.example", label: null, status: "ok", mine: true, last_sync: "2026-03-05T06:00", last_error: null, photos: 0, trips: 0, ...extra });
const NO_SHARING: PhotoSharing = { state: "none", scope: null, count: 0, removed_count: 0, removed: [], window: null, changed: null, audience: [1], sources: [], count_token: "a".repeat(32) };

let photos: TripPhoto[];
let best: number[];
let clusters: PhotoCluster[];
let reported: TripSummary;
let sources: PhotoSource[];
let photosFail = false;
let sharingReply: () => Promise<PhotoSharing>;
function serve() {
  vi.mocked(api).mockImplementation(async (path) => {
    const p = String(path);
    if (p.includes("/photo-sharing")) return sharingReply();
    if (p === "/api/photo-sources") return { sources, permissions: [] };
    if (p.endsWith("/photos")) { if (photosFail) throw new Error("down"); return reply(photos, best, clusters); }
    if (p.endsWith("/summary")) return reported;
    if (p === "/api/distance-unit") return { distance_unit: "mi" };
    if (p.endsWith("/places")) return places;
    throw new Error(`unexpected ${p}`);
  });
}

const options = (extra: Record<string, unknown> = {}) => [
  { label: "Add a booking", onselect: vi.fn() },
  { label: "Merge another trip", onselect: vi.fn() },
  { label: "Delete trip", destructive: true, divided: true, onselect: vi.fn() },
  ...Object.entries(extra).map(([label, onselect]) => ({ label, onselect: onselect as () => void })),
];
const show = (extra: Record<string, unknown> = {}) => render(PastTrip, { trip: roadTrip, people: [ada], now: after, dates: "Mar 1, 2026 – Mar 8, 2026", costsShown: true, loads: 1, back: true, options: options(), onsaved: vi.fn(), ...extra } as never);
const placeStay = () => {
  const base = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path: string, options?: Parameters<typeof api>[1]) => String(path).endsWith("/places") ? { ...places, stays: [{ segment_id: 2, latitude: 39.7, longitude: -105, precision: "city" }] } : base(path, options));
};
const settled = () => screen.findByRole("region", { name: /^Photos/ });
const days = () => screen.getAllByRole("region").filter((r) => r.hasAttribute("data-day"));

let maps: ReturnType<typeof fakeMaps>;
beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
  fake.reset();
  maps = fakeMaps();
  vi.mocked(loadMapkit).mockReset();
  vi.mocked(loadMapkit).mockImplementation(async () => maps);
  app.state = state({ mapkit: true });
  photos = [];
  best = [];
  clusters = [];
  reported = summary;
  viewport.phone = true;
  sources = [source()];
  photosFail = false;
  sharingReply = async () => NO_SHARING;
  serve();
});
afterEach(() => { app.state = null; app.offline = false; viewport.phone = false; vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("PastTrip hero", () => {
  it("is a mosaic of the first three of best, with the trip's name as the page's h1 and the images decorative", async () => {
    photos = [1, 2, 3, 4, 5, 6, 7].map((id) => shot(id));
    best = [5, 3, 7, 1];
    show();
    const hero = await screen.findByTestId("trip-hero");
    await waitFor(() => expect(hero.querySelectorAll("img")).toHaveLength(3));
    expect([...hero.querySelectorAll("img")].map((i) => i.getAttribute("src"))).toEqual(["/api/photos/5/thumbnail", "/api/photos/3/thumbnail", "/api/photos/7/thumbnail"]);
    expect(hero.querySelector("[aria-hidden='true']")?.querySelectorAll("img")).toHaveLength(3);
    expect(hero.querySelectorAll("img[alt='']")).toHaveLength(3);
    expect(hero.className).toContain("rounded-[22px]");
    expect(hero.className).toContain("border-border");
    expect(within(hero).getByRole("heading", { level: 1, name: "Spring loop" })).toBeTruthy();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(within(hero).getByText("Mar 1, 2026 – Mar 8, 2026 · Utah")).toBeTruthy();
    expect(screen.queryByTestId("no-photos")).toBeNull();
  });

  it("is the route map with its Replay button, and a quiet line, when there are no photos", async () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: false, media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    show({ trip: flown });
    expect(await screen.findByRole("region", { name: "Route replay" })).toBeTruthy();
    expect(await screen.findByTestId("no-photos")).toHaveTextContent("No photos yet");
    expect(screen.queryByTestId("trip-hero")).toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: "Spring loop" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /^(Play|Pause|Resume|Replay)$/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Replay trip" })).toBeNull();
    expect(screen.getByTestId("no-photos").className).toContain("-mt-3");
  });

  it("draws no photo pins, no Photos key entry and no stops list on the route map, whatever the photos' places", async () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: false, media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    photos = [shot(1), shot(2, 2)];
    best = [1, 2];
    clusters = [{ latitude: 39.7, longitude: -105, count: 2, first: "2026-03-01T08:00", last: "2026-03-02T18:00", cover: 1, inferred: false }];
    const { container } = show({ trip: flown });
    await screen.findByRole("region", { name: "Route replay" });
    await settled();
    expect(container.querySelector("[data-pin]")).toBeNull();
    expect(container.querySelector("[data-testid=photo-pins]")).toBeNull();
    expect(within(screen.getByRole("list", { name: "Map key" })).queryByText("Photos")).toBeNull();
    expect(screen.queryByRole("list", { name: "Stops in order" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Stops list" })).toBeNull();
    expect(screen.getByRole("slider", { name: "Position along the route" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "Map of the route, stop by stop" })).toBeTruthy();
  });

  it("is the route map with no quiet line when the library has one or two photos, which stay in the days", async () => {
    photos = [shot(1), shot(2, 2)];
    best = [1, 2];
    show({ trip: flown });
    expect(await screen.findByRole("region", { name: "Route replay" })).toBeTruthy();
    await settled();
    expect(screen.queryByTestId("trip-hero")).toBeNull();
    expect(screen.queryByTestId("no-photos")).toBeNull();
    expect(days().map((d) => d.getAttribute("data-day"))).toEqual(["2026-03-01", "2026-03-02"]);
    expect(screen.getByRole("button", { name: "Photo 1, Sun Mar 1, Marlow Springs" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Photo 1, Mon Mar 2, Marlow Springs" })).toBeTruthy();
  });

  it("is the map with the quiet line when no library is connected", async () => {
    sources = [];
    show({ trip: flown });
    expect(await screen.findByTestId("no-photos")).toBeTruthy();
    expect(await screen.findByRole("link", { name: "Connect a library in Settings" })).toBeTruthy();
  });

  it("is the map, without the quiet line, when the photos can't be loaded", async () => {
    photosFail = true;
    show({ trip: flown });
    expect(await screen.findByRole("region", { name: "Route replay" })).toBeTruthy();
    expect(await screen.findByText("Couldn’t load the photos on this trip.")).toBeTruthy();
    expect(screen.queryByTestId("no-photos")).toBeNull();
  });

  it("is only the title when there are no photos and no route", async () => {
    show();
    expect(await screen.findByTestId("no-photos")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1, name: "Spring loop" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Route replay" })).toBeNull();
  });

  it("uses no photos for the hero when the viewer can see only the videos best skipped", async () => {
    photos = [1, 2, 3].map((id) => shot(id, 1, { kind: "video" }));
    best = [];
    show({ trip: flown });
    await settled();
    expect(screen.queryByTestId("trip-hero")).toBeNull();
    expect(screen.queryByTestId("no-photos")).toBeNull();
  });
});

describe("PastTrip with a hero that takes every photo", () => {
  it("keeps a way into the photo viewer, since the days are empty", async () => {
    photos = [1, 2, 3].map((id) => shot(id));
    best = [1, 2, 3];
    show();
    const open = await screen.findByRole("button", { name: "View photos" });
    expect(document.querySelector("[data-day]")).toBeNull();
    await userEvent.click(open);
    expect(within(await screen.findByRole("dialog")).getByText("Photo 1 of 3")).toBeTruthy();
  });

  it("has no View photos button while the days show photos", async () => {
    photos = [1, 2, 3, 4].map((id) => shot(id));
    best = [1, 2, 3];
    show();
    await screen.findByTestId("trip-hero");
    await waitFor(() => expect(days()).toHaveLength(1));
    expect(screen.queryByRole("button", { name: "View photos" })).toBeNull();
  });
});

describe("PastTrip facts", () => {
  it("is the Trip summary list with its hidden terms, the household's unit, the avatars as one image and the total", async () => {
    photos = [1, 2, 3, 4].map((id) => shot(id));
    best = [1, 2, 3];
    show({ trip: { ...roadTrip, costs: { totals: [{ currency: "USD", amount_minor: 431200 }], priced: 1, bookings: 1 } } });
    const facts = await screen.findByTestId("trip-summary").catch(() => screen.findByTestId("trip-summary"));
    await waitFor(() => expect(within(facts).getByText("Days", { selector: "dt" })).toBeTruthy());
    expect([...facts.querySelectorAll("dt")].map((d) => d.textContent)).toEqual(["Days", "Nights away", "Distance", "Photos"]);
    expect([...facts.querySelectorAll("dd")].map((d) => d.textContent)).toEqual(["8 days", "7 nights", "1,240 mi", "214 photos"]);
    expect(facts.querySelectorAll("dt.sr-only")).toHaveLength(4);
    expect(screen.getByTestId("avatar-stack")).toHaveAttribute("role", "img");
    expect(screen.getByText("$4,312.00", { exact: false }).closest("[data-trip-total]")).toBeTruthy();
  });

  it("makes the avatars a button that opens the people sheet, and plain avatars when the page offers none", async () => {
    const onpeople = vi.fn();
    const { unmount } = show({ onpeople });
    const names = screen.getByTestId("avatar-stack").getAttribute("aria-label");
    const button = screen.getByRole("button", { name: `People on this trip: ${names}` });
    await userEvent.click(button);
    expect(onpeople).toHaveBeenCalledOnce();
    unmount();
    show();
    expect(screen.queryByRole("button", { name: /^People on this trip/ })).toBeNull();
    expect(screen.getByTestId("avatar-stack")).toBeInTheDocument();
  });

  it("leaves the total out when costs are not shown", async () => {
    show({ costsShown: false, trip: { ...roadTrip, costs: { totals: [{ currency: "USD", amount_minor: 431200 }], priced: 1, bookings: 1 } } });
    await settled().catch(() => null);
    expect(document.querySelector("[data-trip-total]")).toBeNull();
  });

  it("opens the replay under the facts from Replay trip when the hero is photos", async () => {
    photos = [1, 2, 3, 4].map((id) => shot(id));
    best = [1, 2, 3];
    show({ trip: flown });
    const replay = await screen.findByRole("button", { name: "Replay trip" });
    expect(replay).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("region", { name: "Route replay" })).toBeNull();
    await userEvent.click(replay);
    expect(replay).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByRole("region", { name: "Route replay" })).toBeTruthy();
    await userEvent.click(replay);
    expect(screen.queryByRole("region", { name: "Route replay" })).toBeNull();
  });

  it("offers Replay trip for a trip with a single placed stay, which zooms onto the stay", async () => {
    placeStay();
    photos = [1, 2, 3, 4].map((id) => shot(id));
    best = [1, 2, 3];
    show();
    const replay = await screen.findByRole("button", { name: "Replay trip" });
    await userEvent.click(replay);
    expect(replay).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByRole("region", { name: "Route replay" })).toBeTruthy();
    expect(document.querySelector("[data-label=\"Juniper House\"]")).toBeTruthy();
  });

  it("shows the map as the hero for a single placed stay when there are no photos", async () => {
    placeStay();
    show();
    const region = await screen.findByRole("region", { name: "Route replay" });
    expect(region.querySelector("[data-label]")?.textContent).toContain("Juniper House");
    expect(screen.queryByRole("button", { name: "Replay trip" })).toBeNull();
  });

  it("has no Replay trip button for a single stay that can't be placed", async () => {
    photos = [1, 2, 3, 4].map((id) => shot(id));
    best = [1, 2, 3];
    show();
    await screen.findByTestId("trip-hero");
    await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalledWith(expect.stringContaining("/places")));
    expect(screen.queryByRole("button", { name: "Replay trip" })).toBeNull();
  });

  it("has no Replay trip button for a trip with no route", async () => {
    photos = [1, 2, 3, 4].map((id) => shot(id));
    best = [1, 2, 3];
    show();
    await screen.findByTestId("trip-hero");
    expect(screen.queryByRole("button", { name: "Replay trip" })).toBeNull();
  });
});

describe("PastTrip days", () => {
  const month = (n: number, day: number, extra: Partial<TripPhoto> = {}) => Array.from({ length: n }, (_, i) => shot(1000 * day + i + 1, day, { taken_local: `2026-03-${String(day).padStart(2, "0")}T${String(Math.floor(i / 2)).padStart(2, "0")}:${i % 2 ? "30" : "00"}`, ...extra }));

  it("draws a day as a dot on a rail with its date, place and photo count, six photos and a +N tile, and no glyph beside it", async () => {
    photos = [...month(3, 1), ...month(38, 2)];
    best = [];
    show();
    await settled();
    const [one, two] = days();
    expect(two.className).toContain("border-l-2");
    expect(two.className).toContain("border-border");
    expect(two.querySelector(".bg-primary")).toBeTruthy();
    expect(within(two).getByRole("heading", { level: 3, name: "Mon Mar 2" })).toBeTruthy();
    expect(two).toHaveTextContent("Marlow Springs · 38 photos");
    expect(two.querySelector("svg")).toBeNull();
    expect(two.querySelector("[data-testid=day-glyph]")).toBeNull();
    expect(within(two).getAllByRole("button")).toHaveLength(6);
    expect(within(one).getAllByRole("button")).toHaveLength(3);
  });

  it("leads each day with its first photo with GPS, then the rest in time order", async () => {
    photos = [shot(1, 1, { taken_local: "2026-03-01T08:00", latitude: null, longitude: null, location_source: null }), shot(2, 1, { taken_local: "2026-03-01T09:00", location_source: "inferred" }), shot(3, 1, { taken_local: "2026-03-01T10:00" }), shot(4, 1, { taken_local: "2026-03-01T11:00" })];
    show();
    await settled();
    const [day] = days();
    expect([...day.querySelectorAll("[data-photo]")].map((t) => t.getAttribute("data-photo"))).toEqual(["3", "1", "2", "4"]);
  });

  it("leads a day with no GPS with its first photo", async () => {
    photos = [2, 1, 3].map((id) => shot(id, 1, { taken_local: `2026-03-01T0${id}:00`, latitude: null, longitude: null, location_source: null }));
    show();
    await settled();
    expect([...days()[0].querySelectorAll("[data-photo]")].map((t) => t.getAttribute("data-photo"))).toEqual(["1", "2", "3"]);
  });

  it("shows each photo once: the hero's photos are out of the days, and the counts are what is left", async () => {
    photos = month(10, 1);
    best = [photos[4].id, photos[0].id, photos[9].id, photos[2].id];
    show();
    const hero = await screen.findByTestId("trip-hero");
    await waitFor(() => expect(hero.querySelectorAll("img")).toHaveLength(3));
    const [day] = days();
    const tiles = [...day.querySelectorAll("[data-photo]")].map((t) => Number(t.getAttribute("data-photo")));
    const inHero = [...hero.querySelectorAll("img")].map((i) => Number(i.getAttribute("src")?.split("/")[3]));
    expect(inHero).toEqual([photos[4].id, photos[0].id, photos[9].id]);
    expect(tiles).toHaveLength(6);
    expect(new Set(tiles).size).toBe(6);
    for (const id of inHero) expect(tiles).not.toContain(id);
    expect(day).toHaveTextContent("Marlow Springs · 7 photos");
    expect(within(day).getByRole("button", { name: "Photo 6 and 1 more, Sun Mar 1, Marlow Springs" })).toHaveTextContent("+1");
    expect(screen.getByTestId("trip-summary")).toHaveTextContent("214 photos");
  });

  it("names the photos and the last tile as the design does, and has no +N tile for a day of six or fewer", async () => {
    photos = [...month(38, 1), ...month(6, 2)];
    show();
    await settled();
    const [one, two] = days();
    expect(within(one).getByRole("button", { name: "Photo 3, Sun Mar 1, Marlow Springs" })).toBeTruthy();
    const last = within(one).getByRole("button", { name: "Photo 6 and 32 more, Sun Mar 1, Marlow Springs" });
    expect(last).toHaveTextContent("+32");
    expect(within(two).getByRole("button", { name: "Photo 6, Mon Mar 2, Marlow Springs" })).not.toHaveTextContent("+");
    expect(one).toHaveAccessibleName("Sun Mar 1");
    expect(within(one).getByRole("heading", { level: 3, name: "Sun Mar 1" })).toBeTruthy();
  });

  it("shows the first three days, then Show all N days shows the rest", async () => {
    photos = [1, 2, 3, 4, 5].flatMap((d) => month(2, d));
    show();
    await settled();
    expect(days()).toHaveLength(3);
    const more = screen.getByRole("button", { name: "Show all 5 days" });
    await userEvent.click(more);
    expect(days()).toHaveLength(5);
    expect(screen.queryByRole("button", { name: /^Show all/ })).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("heading", { level: 3, name: "Wed Mar 4" })));
  });

  it("has no Show all button for three days or fewer", async () => {
    photos = [1, 2, 3].flatMap((d) => month(2, d));
    show();
    await settled();
    expect(days()).toHaveLength(3);
    expect(screen.queryByRole("button", { name: /^Show all/ })).toBeNull();
  });

  it("opens the photo viewer from a tile, over every photo the viewer may see", async () => {
    photos = month(8, 1);
    best = [photos[0].id, photos[1].id, photos[2].id];
    show();
    const tile = await screen.findByRole("button", { name: /^Photo 1, Sun Mar 1/ });
    await userEvent.click(tile);
    const viewer = await screen.findByRole("dialog");
    expect(within(viewer).getByText("Photo 4 of 8")).toBeTruthy();
  });

  it("keeps the sharing prompt and the connect-a-library line with the days", async () => {
    sources = [];
    show();
    expect(await screen.findByRole("link", { name: "Connect a library in Settings" })).toBeTruthy();
  });
});

describe("PastTrip top row and Trip options", () => {
  it("names Back Past trips, and has none where the trip is in a side pane", async () => {
    const { unmount } = show();
    const link = screen.getByRole("link", { name: "Past trips" });
    expect(link).toHaveAttribute("href", "#trips");
    unmount();
    show({ back: false });
    expect(screen.queryByRole("link", { name: "Past trips" })).toBeNull();
  });

  it("opens a menu with Add a booking, Merge another trip and Delete trip, and runs the one chosen", async () => {
    const list = options();
    show({ options: list });
    const trigger = screen.getByRole("button", { name: "Trip options" });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(trigger);
    const menu = screen.getByRole("menu", { name: "Trip options" });
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent?.trim())).toEqual(["Add a booking", "Merge another trip", "Delete trip"]);
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Merge another trip" }));
    expect(list[1].onselect).toHaveBeenCalledOnce();
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("shows no menu while there are no options", () => {
    show({ options: [] });
    expect(screen.queryByRole("button", { name: "Trip options" })).toBeNull();
  });

  it("edits the trip's details from a pencil, since the title is the hero's", async () => {
    show();
    expect(screen.queryByRole("textbox", { name: "Name" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Edit trip details" }));
    expect(await screen.findByRole("textbox", { name: "Name" })).toHaveValue("Spring loop");
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.queryByTestId("trip-hero")).toBeNull();
  });

  it("takes the pencil away while the form is open, so a draft is never reset", async () => {
    show();
    await userEvent.click(screen.getByRole("button", { name: "Edit trip details" }));
    const name = await screen.findByRole("textbox", { name: "Name" });
    await userEvent.type(name, " draft");
    expect(screen.queryByRole("button", { name: "Edit trip details" })).toBeNull();
    expect(name).toHaveValue("Spring loop draft");
  });
});

describe("PastTrip bookings row", () => {
  it("is a button that opens a dialog, with the kinds, when a handler is given", async () => {
    const onbookings = vi.fn();
    show({ trip: flown, onbookings });
    const row = await screen.findByRole("button", { name: /^Bookings · 3/ });
    expect(row).toHaveAttribute("aria-haspopup", "dialog");
    expect(row).toHaveTextContent("2 flights · 1 stay");
    await userEvent.click(row);
    expect(onbookings).toHaveBeenCalledOnce();
  });

  it("is not drawn without a handler, so it is never a dead control", async () => {
    show({ trip: flown });
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("button", { name: /^Bookings/ })).toBeNull();
  });
});

describe("PastTrip Sharing", () => {
  const sharing = (extra: Partial<PhotoSharing> = {}): PhotoSharing => ({ ...NO_SHARING, state: "shared", scope: "only_me", count: 5, ...extra });
  const many = (n: number) => [...Array(n).keys()].map((i) => shot(i + 1, 1 + (i % 3)));
  const optionsButton = () => screen.getByRole("button", { name: "Trip options" });
  const sharingItem = async (user: { click: (element: Element) => Promise<void> } = userEvent) => {
    if (optionsButton().getAttribute("aria-expanded") !== "true") await user.click(optionsButton());
    return screen.findByRole("menuitem", { name: "Sharing" });
  };
  const noSharingItem = async () => {
    await userEvent.click(optionsButton());
    const menu = screen.getByRole("menu", { name: "Trip options" });
    expect(within(menu).queryByRole("menuitem", { name: "Sharing" })).toBeNull();
    return menu;
  };
  const before = (a: Element, b: Element) => !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
  const stub = (answer: (p: string, opts?: unknown) => PhotoSharing) => vi.mocked(api).mockImplementation(async (path, opts) => {
    const p = String(path);
    if (p.includes("/photo-sharing")) return answer(p, opts) as never;
    if (p === "/api/photo-sources") return { sources, permissions: [] } as never;
    if (p.endsWith("/photos")) return reply(photos, best) as never;
    if (p.endsWith("/summary")) return summary as never;
    if (p === "/api/distance-unit") return { distance_unit: "mi" } as never;
    if (p.endsWith("/places")) return places as never;
    throw new Error(`unexpected ${p}`);
  });

  it("has no Sharing button anywhere on a phone, and lists Sharing first in Trip options, opening the sheet with the card only in it", async () => {
    photos = many(6);
    best = [1, 2, 3];
    sharingReply = async () => sharing();
    show();
    await settled();
    const item = await sharingItem();
    expect(screen.queryByRole("button", { name: "Sharing" })).toBeNull();
    expect(screen.queryByRole("button", { name: "View photos" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Your photos on this trip" })).toBeNull();
    const menu = screen.getByRole("menu", { name: "Trip options" });
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent?.trim())).toEqual(["Sharing", "Add a booking", "Merge another trip", "Delete trip"]);
    await userEvent.click(item);
    const panel = await screen.findByRole("dialog", { name: "Photo sharing for this trip" });
    expect(within(panel).getByRole("region", { name: "Your photos on this trip" })).toBeTruthy();
    expect(screen.queryByRole("menu")).toBeNull();
    expect(screen.queryByRole("button", { name: "Select your photos to remove" })).toBeNull();
  });

  it("has no Sharing button beside Open gallery on desktop, and opens the popover under the top row, leftward to stay on screen", async () => {
    viewport.phone = false;
    photos = many(6);
    best = [1, 2, 3];
    sharingReply = async () => sharing();
    show();
    await settled();
    const item = await sharingItem();
    const open = screen.getByRole("button", { name: "Open gallery" });
    const heading = screen.getByRole("heading", { level: 2, name: "Photos by day" });
    expect(screen.queryByRole("button", { name: "Sharing" })).toBeNull();
    expect(heading.parentElement?.getAttribute("class")).toContain("justify-between");
    expect(within(heading.parentElement as HTMLElement).getAllByRole("button").map((b) => b.textContent?.trim())).toEqual(["Open gallery"]);
    expect(open).toBeTruthy();
    expect(screen.queryByRole("button", { name: "View photos" })).toBeNull();
    await userEvent.click(item);
    const panel = await screen.findByRole("dialog", { name: "Photo sharing for this trip" });
    expect(panel.className).toContain("right-[-6px]");
    expect(panel.parentElement?.contains(optionsButton())).toBe(true);
    expect(before(optionsButton(), panel)).toBe(true);
  });

  it("puts the reminder directly under the Photos by day header on desktop", async () => {
    viewport.phone = false;
    photos = many(6);
    best = [1, 2, 3];
    sharingReply = async () => sharing({ state: "declined", scope: null });
    show();
    const reminder = await screen.findByTestId("photo-reminder");
    const heading = screen.getByRole("heading", { level: 2, name: "Photos by day" });
    expect(heading.parentElement?.nextElementSibling).toBe(reminder);
    expect(before(reminder, days()[0])).toBe(true);
    expect(screen.queryByRole("button", { name: "Sharing" })).toBeNull();
    await noSharingItem();
  });

  it("draws no blank slot while the sharing state loads, and adds the menu item once it is known", async () => {
    photos = many(6);
    best = [1, 2, 3];
    let release: (value: PhotoSharing) => void = () => {};
    sharingReply = () => new Promise((resolve) => { release = resolve; });
    show();
    await settled();
    expect(screen.queryByTestId("sharing-slot")).toBeNull();
    const menu = await noSharingItem();
    release(sharing());
    expect(await within(menu).findByRole("menuitem", { name: "Sharing" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Sharing" })).toBeNull();
  });

  it("shows View photos alone in its row when the hero takes every photo", async () => {
    photos = many(3);
    best = [1, 2, 3];
    sharingReply = async () => sharing();
    show();
    const view = await screen.findByRole("button", { name: "View photos" });
    expect(within(view.parentElement as HTMLElement).getAllByRole("button")).toEqual([view]);
    await sharingItem();
    expect(screen.queryByRole("button", { name: "Sharing" })).toBeNull();
  });

  it("draws no row for sharing under the map when the hero is the map, and keeps the menu item", async () => {
    photos = many(2);
    best = [1, 2];
    sharingReply = async () => sharing();
    show({ trip: flown });
    await settled();
    await sharingItem();
    expect(screen.queryByTestId("trip-hero")).toBeNull();
    expect(screen.queryByRole("button", { name: "View photos" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Sharing" })).toBeNull();
    await userEvent.click(await screen.findByRole("menuitem", { name: "Sharing" }));
    expect(await screen.findByRole("dialog", { name: "Photo sharing for this trip" })).toBeTruthy();
  });

  it("offers no Sharing item, and draws no blank slot, to a person with no sharing control once the state is known", async () => {
    photos = many(6);
    best = [1, 2, 3];
    show();
    await settled();
    expect(screen.queryByTestId("sharing-slot")).toBeNull();
    await noSharingItem();
    expect(screen.queryByRole("button", { name: "Sharing" })).toBeNull();
  });

  it("keeps Trip options to its own choices for a person with no control, under the map", async () => {
    show({ trip: flown });
    await screen.findByTestId("no-photos");
    expect(screen.queryByTestId("sharing-slot")).toBeNull();
    const menu = await noSharingItem();
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent?.trim())).toEqual(["Add a booking", "Merge another trip", "Delete trip"]);
  });

  it("keeps Sharing in Trip options when the trip has no other options", async () => {
    photos = many(6);
    best = [1, 2, 3];
    sharingReply = async () => sharing();
    show({ options: [] });
    await settled();
    const item = await sharingItem();
    expect(within(screen.getByRole("menu", { name: "Trip options" })).getAllByRole("menuitem")).toEqual([item]);
  });

  it("keeps the first-visit prompt above the days, with no button and no menu item", async () => {
    photos = many(6);
    best = [1, 2, 3];
    sharingReply = async () => sharing({ state: "ask", scope: null });
    show();
    const prompt = await screen.findByRole("group", { name: /Your photos|photos/i });
    expect(screen.queryByRole("button", { name: "Sharing" })).toBeNull();
    expect(before(prompt, days()[0])).toBe(true);
    await noSharingItem();
  });

  it("puts the reminder after Not now directly under the hero, above the summary, with no button", async () => {
    photos = many(6);
    best = [1, 2, 3];
    sharingReply = async () => sharing({ state: "declined", scope: null });
    show();
    const reminder = await screen.findByTestId("photo-reminder");
    expect(screen.queryByRole("button", { name: "Sharing" })).toBeNull();
    expect(before(screen.getByTestId("trip-hero"), reminder)).toBe(true);
    expect(before(reminder, screen.getByTestId("trip-summary"))).toBe(true);
    expect(screen.getAllByTestId("photo-reminder")).toHaveLength(1);
  });

  it("offers the menu item of the next trip after moving from one with no control, in the same page", async () => {
    photos = many(2);
    best = [];
    const next = trip([stay, there, back], { id: 8, name: "Autumn loop", destination: "Utah", start_date: "2026-03-01", end_date: "2026-03-08" });
    sharingReply = async () => NO_SHARING;
    stub((p) => (p.includes("/trips/8/") ? sharing() : NO_SHARING));
    const view = show({ trip: flown });
    await settled();
    await noSharingItem();
    await view.rerender({ trip: next } as never);
    expect(await screen.findByRole("menuitem", { name: "Sharing" })).toBeTruthy();
  });

  it("opens no panel on the next trip when the sheet was open as the trip changed", async () => {
    photos = many(6);
    best = [1, 2, 3];
    const next = trip([stay], { id: 8, name: "Autumn loop", destination: "Utah", start_date: "2026-03-01", end_date: "2026-03-08" });
    stub(() => sharing());
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    const view = show();
    await settled();
    await user.click(await sharingItem(user));
    await screen.findByRole("dialog", { name: "Photo sharing for this trip" });
    await view.rerender({ trip: next } as never);
    await sharingItem(user);
    expect(screen.queryByRole("dialog", { name: "Photo sharing for this trip" })).toBeNull();
  });

  it("does not reopen the panel when sharing is stopped and then shared again", async () => {
    photos = many(6);
    best = [1, 2, 3];
    let current = sharing({ count: 5 });
    stub((_p, opts) => {
      const method = (opts as { method?: string } | undefined)?.method;
      if (method === "DELETE") current = sharing({ state: "declined", scope: null, count: 5 });
      if (method === "POST") current = sharing({ count: 5 });
      return current;
    });
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    show();
    await settled();
    await user.click(await sharingItem(user));
    const panel = await screen.findByRole("dialog", { name: "Photo sharing for this trip" });
    await user.click(within(panel).getByRole("button", { name: "Stop sharing on this trip" }));
    await user.click(within(await screen.findByRole("dialog", { name: "Stop sharing your photos on this trip?" })).getByRole("button", { name: "Stop sharing" }));
    const reminder = await screen.findByTestId("photo-reminder");
    expect(screen.queryByRole("button", { name: "Sharing" })).toBeNull();
    await user.click(within(reminder).getByRole("button", { name: /^Share .* photos on this trip$/ }));
    await user.click(await screen.findByRole("button", { name: "Share on this trip" }));
    await sharingItem(user);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens the panel as a sheet on a phone", async () => {
    viewport.phone = true;
    photos = many(6);
    best = [1, 2, 3];
    sharingReply = async () => sharing();
    show();
    await settled();
    await userEvent.click(await sharingItem());
    const sheet = await screen.findByRole("dialog", { name: "Photo sharing for this trip" });
    expect(within(sheet).getByRole("region", { name: "Your photos on this trip" })).toBeTruthy();
    viewport.phone = false;
  });

  it("closes the popover when Trip options is opened again on desktop, so the two never overlap", async () => {
    viewport.phone = false;
    photos = many(6);
    best = [1, 2, 3];
    sharingReply = async () => sharing();
    show();
    await settled();
    const user = userEvent.setup();
    await user.click(await sharingItem(user));
    await screen.findByRole("dialog", { name: "Photo sharing for this trip" });
    await user.click(optionsButton());
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Photo sharing for this trip" })).toBeNull());
    expect(await screen.findByRole("menu", { name: "Trip options" })).toBeTruthy();
  });

  it("closes the popover with Escape and returns focus to Trip options on desktop", async () => {
    viewport.phone = false;
    photos = many(6);
    best = [1, 2, 3];
    sharingReply = async () => sharing();
    show();
    await settled();
    const user = userEvent.setup();
    await user.click(await sharingItem(user));
    const panel = await screen.findByRole("dialog", { name: "Photo sharing for this trip" });
    await waitFor(() => expect(panel).toContainElement(document.activeElement as HTMLElement));
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Photo sharing for this trip" })).toBeNull());
    expect(optionsButton()).toHaveFocus();
  });
});

describe("PastTrip on desktop", () => {
  const tiles = (count: number, day = 1) => Array.from({ length: count }, (_, i) => shot(100 * day + i + 1, day, { taken_local: `2026-03-0${day}T${String(Math.floor(i / 4) + 6).padStart(2, "0")}:${String((i % 4) * 10).padStart(2, "0")}` }));
  const marlow = (count: number): PhotoCluster => ({ latitude: 39.7, longitude: -105, count, first: "2026-03-01T08:00", last: "2026-03-07T18:00", cover: 101, inferred: false });
  const column = () => screen.getByTestId("trip-column");
  const heroImages = (hero: HTMLElement) => [...hero.querySelectorAll("img")].map((i) => Number(i.getAttribute("src")?.split("/")[3]));

  beforeEach(() => { viewport.phone = false; });

  it("switches with the viewport: two columns on desktop, one stack on a phone", async () => {
    photos = tiles(9);
    best = [101, 102, 103];
    const { unmount } = show();
    expect(await screen.findByTestId("trip-columns")).toBeTruthy();
    unmount();
    viewport.phone = true;
    show();
    await screen.findByTestId("trip-hero");
    expect(screen.queryByTestId("trip-columns")).toBeNull();
    expect(screen.queryByTestId("trip-column")).toBeNull();
  });

  it("keeps the left column in view while the photos scroll, 400 px wide beside the photos", async () => {
    photos = tiles(9);
    best = [101, 102, 103];
    show();
    await screen.findByTestId("trip-hero");
    expect(column().className).toContain("sticky");
    expect(column().className).toContain("lg:top-4");
    expect(column().className).toContain("overflow-y-auto");
    expect(column().parentElement?.className).toContain("grid-cols-[400px_minmax(0,1fr)]");
    const photosHeading = await screen.findByRole("heading", { level: 2, name: "Photos by day" });
    expect(column().parentElement?.contains(photosHeading)).toBe(true);
    expect(column().contains(photosHeading)).toBe(false);
  });

  describe("hero", () => {
    it("is the route map and the quiet line with no photos, and the columns still follow", async () => {
      show({ trip: flown });
      expect(await screen.findByTestId("no-photos")).toHaveTextContent("No photos yet");
      expect(screen.queryByTestId("trip-hero")).toBeNull();
      expect(screen.getByRole("heading", { level: 1, name: "Spring loop" })).toBeTruthy();
      expect(screen.getByRole("region", { name: "Route replay" })).toBeTruthy();
      expect(screen.getByTestId("trip-columns")).toBeTruthy();
      expect(within(column()).queryByRole("region", { name: "Route replay" })).toBeNull();
    });

    it("is the route map for one or two photos, which stay in the days", async () => {
      photos = tiles(2);
      best = [101, 102];
      show({ trip: flown });
      await settled();
      expect(screen.queryByTestId("trip-hero")).toBeNull();
      expect(screen.queryByTestId("no-photos")).toBeNull();
      expect(screen.getByRole("region", { name: "Route replay" })).toBeTruthy();
      expect(within(days()[0]).getAllByRole("button")).toHaveLength(2);
    });

    it.each([3, 4, 6])("is the three-photo mosaic across the full width for %i photos", async (count) => {
      photos = tiles(count);
      best = photos.map((p) => p.id);
      show();
      const hero = await screen.findByTestId("trip-hero");
      await waitFor(() => expect(hero.querySelectorAll("img")).toHaveLength(3));
      expect(heroImages(hero)).toEqual([101, 102, 103]);
      expect(hero.firstElementChild?.className).toContain("grid-cols-[2fr_1fr]");
      expect(hero.className).toContain("h-[260px]");
      expect(hero.className).toContain("rounded-[22px]");
      expect(hero.className).toContain("border-border");
    });

    it("is a mosaic of seven for seven or more photos, the first spanning two rows", async () => {
      photos = tiles(20);
      best = [110, 103, 105, 101, 107, 102, 109, 111];
      show();
      const hero = await screen.findByTestId("trip-hero");
      await waitFor(() => expect(hero.querySelectorAll("img")).toHaveLength(7));
      expect(heroImages(hero)).toEqual([110, 103, 105, 101, 107, 102, 109]);
      expect(hero.firstElementChild?.className).toContain("grid-cols-[2fr_1fr_1fr_1fr]");
      expect(hero.firstElementChild?.firstElementChild?.className).toContain("row-span-2");
      expect(hero.querySelectorAll("img[alt='']")).toHaveLength(7);
      expect(within(hero).getByRole("heading", { level: 1, name: "Spring loop" })).toBeTruthy();
      expect(within(hero).getByText("Mar 1, 2026 – Mar 8, 2026 · Utah")).toBeTruthy();
    });

    it("takes the hero's photos out of the days so each shows once", async () => {
      photos = tiles(20);
      best = [110, 103, 105, 101, 107, 102, 109];
      show();
      const hero = await screen.findByTestId("trip-hero");
      await waitFor(() => expect(hero.querySelectorAll("img")).toHaveLength(7));
      const [day] = days();
      const shown = [...day.querySelectorAll("[data-photo]")].map((t) => Number(t.getAttribute("data-photo")));
      for (const id of heroImages(hero)) expect(shown).not.toContain(id);
      expect(day).toHaveTextContent("Marlow Springs · 13 photos");
    });
  });

  describe("photos by day", () => {
    it("has a visible Photos by day heading and days of up to twelve photos, six across, with a +N tile", async () => {
      photos = [...tiles(40, 1), ...tiles(12, 2)];
      show();
      await settled();
      const heading = screen.getByRole("heading", { level: 2, name: "Photos by day" });
      expect(heading.className).not.toContain("sr-only");
      const [one, two] = days();
      expect(within(one).getAllByRole("button")).toHaveLength(12);
      expect(one.querySelector(".grid")?.className).toContain("grid-cols-6");
      expect(within(one).getByRole("button", { name: "Photo 12 and 28 more, Sun Mar 1, Marlow Springs" })).toHaveTextContent("+28");
      expect(within(two).getAllByRole("button")).toHaveLength(12);
      expect(within(two).getByRole("button", { name: "Photo 12, Mon Mar 2, Marlow Springs" })).not.toHaveTextContent("+");
      expect(within(one).getByRole("heading", { level: 3, name: "Sun Mar 1" })).toBeTruthy();
      expect(one).toHaveTextContent("Marlow Springs · 40 photos");
    });

    it("draws a day with no rail or dot, as the desktop frame does", async () => {
      photos = tiles(5);
      show();
      await settled();
      const [day] = days();
      expect(day.className).not.toContain("border-l-2");
      expect(day.querySelector(".bg-primary")).toBeNull();
    });

    it("shows the first three days and Show all N days reveals the rest", async () => {
      photos = [1, 2, 3, 4, 5].flatMap((d) => tiles(2, d));
      show();
      await settled();
      expect(days()).toHaveLength(3);
      await userEvent.click(screen.getByRole("button", { name: "Show all 5 days" }));
      expect(days()).toHaveLength(5);
    });

    it("opens a grid of every photo from Open gallery, hero's included, where a tile opens the viewer, and closes it again", async () => {
      photos = tiles(30);
      best = photos.slice(0, 7).map((p) => p.id);
      show();
      await settled();
      const open = screen.getByRole("button", { name: "Open gallery" });
      expect(open).toHaveAttribute("aria-expanded", "false");
      await userEvent.click(open);
      const grid = document.getElementById("trip-photos-gallery") as HTMLElement;
      await waitFor(() => expect(grid.querySelectorAll("[data-photo]").length).toBeGreaterThan(23));
      expect(grid.querySelector(`[data-photo="${best[0]}"]`)).toBeTruthy();
      await userEvent.click(grid.querySelector("[data-photo]") as HTMLElement);
      expect(within(await screen.findByRole("dialog")).getByText(/^Photo \d+ of 30$/)).toBeTruthy();
      await userEvent.keyboard("{Escape}");
      await waitFor(() => expect(document.body.style.pointerEvents).not.toBe("none"));
      await userEvent.click(screen.getByRole("button", { name: "Close gallery" }));
      await waitFor(() => expect(screen.getByRole("button", { name: "Open gallery" })).toBeTruthy());
    });

    it("has no Open gallery button when there are no photos", async () => {
      show();
      await screen.findByTestId("no-photos");
      expect(screen.queryByRole("button", { name: "Open gallery" })).toBeNull();
    });
  });

  describe("left column", () => {
    const withTotal = { ...flown, costs: { totals: [{ currency: "USD", amount_minor: 431200 }], priced: 1, bookings: 1 } };

    it("has the Trip summary list, the total, the photo count, and the people, with no need-a-look chip", async () => {
      photos = [...tiles(9), shot(50, 1, { match: "far", distance_km: 500 })];
      best = [101, 102, 103];
      show({ trip: withTotal });
      const facts = await within(column()).findByTestId("trip-summary");
      await waitFor(() => expect(within(facts).getByText("Days", { selector: "dt" })).toBeTruthy());
      expect([...facts.querySelectorAll("dt")].map((d) => d.textContent)).toEqual(["Days", "Nights away", "Distance", "Places"]);
      expect([...facts.querySelectorAll("dd")].map((d) => d.textContent)).toEqual(["8 days", "7 nights", "1,240 mi", "Utah"]);
      expect(facts).toHaveAccessibleName("Trip summary");
      expect(within(column()).getByText("$4,312.00", { exact: false }).closest("[data-trip-total]")).toBeTruthy();
      expect(await within(column()).findByText("10 photos")).toBeTruthy();
      expect(within(column()).getByTestId("avatar-stack")).toHaveAttribute("role", "img");
      expect(within(column()).getByText("Jane Doe")).toBeTruthy();
      expect(screen.queryByRole("link", { name: /need a look/ })).toBeNull();
    });

    it("leaves the total out when costs are not shown, and shows the notes under the facts", async () => {
      photos = tiles(4);
      show({ costsShown: false, trip: { ...withTotal, notes: "Bring the tent." } });
      await settled();
      expect(document.querySelector("[data-trip-total]")).toBeNull();
      expect(within(column()).getByText("Bring the tent.")).toBeTruthy();
    });

    it.each([
      [["Utah"], ["United States"], "Utah"],
      [["Utah", "Arizona", "Colorado"], ["United States"], "3 states"],
      [[], ["France"], "France"],
      [[], ["France", "Italy"], "2 countries"],
      [["Utah"], ["United States", "Canada"], "2 places"],
    ])("words the places of %j in %j as %s", async (states, countries, text) => {
      reported = { ...summary, states, countries };
      photos = tiles(4);
      show({ trip: flown });
      const facts = await within(column()).findByTestId("trip-summary");
      await waitFor(() => expect(within(facts).getByText(text, { selector: "dd" })).toBeTruthy());
    });

    it("has no Replay button in the facts and no Bookings row, which are the phone's", async () => {
      photos = tiles(4);
      best = [101, 102, 103];
      show({ trip: flown, onbookings: vi.fn() });
      await screen.findByTestId("trip-hero");
      expect(screen.queryByRole("button", { name: /^Bookings · 3/ })).toBeNull();
      expect(screen.queryByRole("button", { name: "Replay" })).toBeNull();
    });

    it("gives the bookings list its place under the map", async () => {
      photos = tiles(4);
      const bookings = createRawSnippet(() => ({ render: () => "<section aria-label='Bookings list'>listed</section>" }));
      show({ trip: flown, bookings });
      await settled();
      expect(within(column()).getByRole("region", { name: "Bookings list" })).toBeTruthy();
    });
  });

  describe("trip map", () => {
    beforeEach(() => {
      photos = tiles(9);
      best = [107, 108, 109];
      clusters = [marlow(38)];
      vi.stubGlobal("matchMedia", (q: string) => ({ matches: false, media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    });

    it("is a group named Trip map, with Replay trip on it and no pins", async () => {
      show({ trip: flown });
      const map = await within(column()).findByRole("group", { name: "Trip map" });
      expect(within(map).getByRole("button", { name: "Replay trip" })).toHaveAttribute("aria-expanded", "false");
      expect(map.querySelector("[data-pin]")).toBeNull();
      expect(within(map).queryByRole("button", { name: /photos near/ })).toBeNull();
      expect(within(column()).queryByRole("list", { name: "Map key" })).toBeNull();
      expect(within(column()).queryByRole("slider")).toBeNull();
      expect(within(column()).queryByRole("region", { name: "Stops list" })).toBeNull();
    });

    it("is a still map in the column for a single placed stay, with Replay trip on it", async () => {
      placeStay();
      show({ trip: roadTrip });
      const map = await within(column()).findByRole("group", { name: "Trip map" });
      expect(within(map).getByRole("button", { name: "Replay trip" })).toHaveAttribute("aria-expanded", "false");
      await userEvent.click(within(map).getByRole("button", { name: "Replay trip" }));
      expect(await within(column()).findByRole("slider", { name: "Position along the route" })).toBeTruthy();
    });

    it("plays the replay in the column from Replay trip with only its own controls, and puts the map back when it ends", async () => {
      vi.stubGlobal("matchMedia", (q: string) => ({ matches: false, media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
      show({ trip: flown });
      await userEvent.click(await within(column()).findByRole("button", { name: "Replay trip" }));
      const slider = await within(column()).findByRole("slider", { name: "Position along the route" });
      expect(within(column()).queryByRole("region", { name: "Stops list" })).toBeNull();
      expect(within(column()).queryByRole("list", { name: "Stops in order" })).toBeNull();
      expect(within(column()).queryByRole("button", { name: "Hide replay" })).toBeNull();
      fireEvent.input(slider, { target: { value: "50" } });
      expect(within(column()).queryByRole("group", { name: "Trip map" })).toBeNull();
      fireEvent.input(slider, { target: { value: String(SCRUB_STEPS) } });
      expect(await within(column()).findByRole("group", { name: "Trip map" })).toBeTruthy();
      expect(within(column()).queryByRole("slider")).toBeNull();
      expect(within(column()).getByRole("button", { name: "Replay trip" })).toBeTruthy();
    });

    it("offers no Replay trip to someone who asks for reduced motion, who would have no controls to leave it with", async () => {
      vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
      show({ trip: flown });
      const map = await within(column()).findByRole("group", { name: "Trip map" });
      expect(within(map).queryByRole("button", { name: "Replay trip" })).toBeNull();
    });

    it("puts the map back when reduced motion is asked for during the replay in the column", async () => {
      let change: ((e: { matches: boolean }) => void) | null = null;
      vi.stubGlobal("matchMedia", (q: string) => ({ matches: false, media: q, addEventListener: (_: string, run: typeof change) => { change = run; }, removeEventListener: vi.fn() }));
      show({ trip: flown });
      await userEvent.click(await within(column()).findByRole("button", { name: "Replay trip" }));
      await within(column()).findByRole("slider", { name: "Position along the route" });
      act(() => change?.({ matches: true }));
      const map = await within(column()).findByRole("group", { name: "Trip map" });
      expect(within(column()).queryByRole("slider")).toBeNull();
      expect(within(map).queryByRole("button", { name: "Replay trip" })).toBeNull();
    });

    it("has no map in the column for a trip with no route, even when its photos have places", async () => {
      show();
      await settled();
      expect(within(column()).queryByRole("group", { name: "Trip map" })).toBeNull();
      expect(column().querySelector("[data-pin]")).toBeNull();
    });
  });
});

describe("PastTrip with no map", () => {
  const stage = () => screen.getByTestId("past-trip");
  const emptyBlocks = () => [...stage().children].filter((c) => c.tagName === "DIV" && c.childElementCount === 0 && !c.textContent);

  beforeEach(() => {
    app.state = state({ mapkit: false });
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: false, media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
  });

  it("on a phone with fewer than three photos is the title, the dates, No photos yet and the facts, with no map and no Replay trip", async () => {
    show({ trip: flown });
    expect(await screen.findByTestId("no-photos")).toHaveTextContent("No photos yet");
    expect(screen.getByRole("heading", { level: 1, name: "Spring loop" })).toBeTruthy();
    expect(screen.getByText("Mar 1, 2026 – Mar 8, 2026 · Utah")).toBeTruthy();
    expect(await screen.findByTestId("trip-summary")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Route replay" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Replay trip" })).toBeNull();
    expect(screen.queryByRole("img", { name: /Map of the route/ })).toBeNull();
    expect(screen.queryByTestId("replay-map")).toBeNull();
    expect(screen.getByTestId("no-photos").className).not.toContain("-mt-3");
    expect(emptyBlocks()).toEqual([]);
    expect(loadMapkit).not.toHaveBeenCalled();
    expect(fake.maps).toHaveLength(0);
  });

  it("on a phone with three or more photos is the mosaic and the facts, with no Replay trip", async () => {
    photos = [1, 2, 3, 4].map((id) => shot(id));
    best = [1, 2, 3];
    show({ trip: flown });
    await screen.findByTestId("trip-hero");
    await screen.findByTestId("trip-summary");
    expect(screen.queryByRole("button", { name: "Replay trip" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Route replay" })).toBeNull();
    expect(emptyBlocks()).toEqual([]);
  });

  it("on desktop has no map block and no Replay trip in the left column", async () => {
    viewport.phone = false;
    photos = [1, 2, 3, 4].map((id) => shot(id));
    best = [1, 2, 3];
    show({ trip: flown });
    const column = await screen.findByTestId("trip-column");
    await within(column).findByTestId("trip-summary");
    expect(within(column).queryByRole("group", { name: "Trip map" })).toBeNull();
    expect(within(column).queryByRole("button", { name: "Replay trip" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Route replay" })).toBeNull();
  });

  it("makes no request to load a map for a viewer who is offline, and shows none", async () => {
    app.state = state({ mapkit: true });
    app.offline = true;
    show({ trip: flown });
    expect(await screen.findByTestId("no-photos")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Route replay" })).toBeNull();
    expect(loadMapkit).not.toHaveBeenCalled();
  });

  it("shows no map when Apple's map doesn't load, and offers no Replay trip", async () => {
    app.state = state({ mapkit: true });
    vi.mocked(loadMapkit).mockResolvedValue(null);
    photos = [1, 2, 3, 4].map((id) => shot(id));
    best = [1, 2, 3];
    show({ trip: flown });
    await screen.findByTestId("trip-hero");
    await waitFor(() => expect(loadMapkit).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByRole("button", { name: "Replay trip" })).toBeNull();
  });
});

describe("PastTrip when the map fails after the replay showed", () => {
  beforeEach(() => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: false, media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
  });

  it("on a phone puts a quiet line where the map was, and moves focus from the replay's controls to the facts", async () => {
    show({ trip: flown });
    const pause = await screen.findByRole("button", { name: /^(Play|Pause|Resume|Replay)$/ });
    pause.focus();
    maps.fail();
    expect(await screen.findByText("The map couldn’t load")).toBeTruthy();
    expect(screen.getByText("The map couldn’t load")).toHaveAttribute("role", "status");
    expect(screen.queryByRole("region", { name: "Route replay" })).toBeNull();
    expect(screen.getByTestId("no-photos").className).not.toContain("-mt-3");
    const facts = await screen.findByTestId("trip-summary");
    await waitFor(() => expect(document.activeElement).toBe(facts));
  });

  it("on desktop does the same for the column's map, and takes Replay trip away", async () => {
    viewport.phone = false;
    photos = [1, 2, 3, 4].map((id) => shot(id));
    best = [1, 2, 3];
    show({ trip: flown });
    const column = await screen.findByTestId("trip-column");
    const replay = await within(column).findByRole("button", { name: "Replay trip" });
    replay.focus();
    maps.fail();
    expect(await within(column).findByText("The map couldn’t load")).toBeTruthy();
    expect(within(column).queryByRole("button", { name: "Replay trip" })).toBeNull();
    const facts = within(column).getByTestId("trip-summary");
    await waitFor(() => expect(document.activeElement).toBe(facts));
  });

  it("on a phone with photos takes Replay trip away once the map has failed", async () => {
    photos = [1, 2, 3, 4].map((id) => shot(id));
    best = [1, 2, 3];
    show({ trip: flown });
    const replay = await screen.findByRole("button", { name: "Replay trip" });
    await userEvent.click(replay);
    await screen.findByRole("region", { name: "Route replay" });
    replay.focus();
    maps.fail();
    expect(await screen.findByText("The map couldn’t load")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Replay trip" })).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByTestId("trip-summary")));
  });
});
