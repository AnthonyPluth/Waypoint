// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("$lib/map", async (original) => ({ ...(await original<typeof import("$lib/map")>()), loadCountries: async () => [], loadDetailedCountries: async () => [], loadFineCountries: async () => [] }));

import { api } from "$lib/api";
import type { Person, PhotoSharing, PhotoSource, TripPhoto, TripPhotos as Reply, TripPlaces, TripSummary } from "$lib/api-types";
import { app } from "$lib/app.svelte";
import { viewport } from "$lib/phone.svelte";
import { segment, state, trip } from "../../test/fixtures";
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
  cities: [], stays: [], roads: { legs: [], interstates: [] }, boundaries: [],
};
const summary: TripSummary = { days: 8, nights: 7, distance_km: 1996, flight_km: 0, road_km: 1996, road_estimated: false, states: ["Utah"], countries: ["United States"], photos: { total: 214, inferred: 3 }, kinds: { flight: 0, hotel: 1, car: 0, train: 0, cruise: 0, parking: 0, visit: 0 } };

const shot = (id: number, day = 1, extra: Partial<TripPhoto> = {}): TripPhoto => ({
  id, person_id: 1, trip_id: 7, kind: "image", taken_local: `2026-03-${String(day).padStart(2, "0")}T${String(8 + (id % 12)).padStart(2, "0")}:${String(id % 60).padStart(2, "0")}`, zone: "America/Denver", latitude: 39.7, longitude: -105, location_source: "exif",
  segment_id: 2, match: "place", distance_km: 3, cluster: 0, removed_at: null, ...extra,
});
const reply = (photos: TripPhoto[], best: number[] = []): Reply => ({ photos, clusters: [], counts: { total: photos.length, located: photos.length, inferred: 0, far: 0 }, people: [], best });
const source = (extra: Partial<PhotoSource> = {}): PhotoSource => ({ id: 1, person_id: 1, url: "https://immich.example", label: null, status: "ok", mine: true, last_sync: "2026-03-05T06:00", last_error: null, photos: 0, trips: 0, ...extra });
const NO_SHARING: PhotoSharing = { state: "none", scope: null, count: 0, removed_count: 0, removed: [], window: null, changed: null, audience: [1], sources: [], count_token: "a".repeat(32) };

let photos: TripPhoto[];
let best: number[];
let sources: PhotoSource[];
let photosFail = false;
let sharingReply: () => Promise<PhotoSharing>;
function serve() {
  vi.mocked(api).mockImplementation(async (path) => {
    const p = String(path);
    if (p.includes("/photo-sharing")) return sharingReply();
    if (p === "/api/photo-sources") return { sources, permissions: [] };
    if (p.endsWith("/photos")) { if (photosFail) throw new Error("down"); return reply(photos, best); }
    if (p.endsWith("/summary")) return summary;
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
const settled = () => screen.findByRole("region", { name: /^Photos/ });
const days = () => screen.getAllByRole("region").filter((r) => r.hasAttribute("data-day"));

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
  app.state = state();
  photos = [];
  best = [];
  sources = [source()];
  photosFail = false;
  sharingReply = async () => NO_SHARING;
  serve();
});
afterEach(() => { app.state = null; vi.unstubAllGlobals(); vi.restoreAllMocks(); });

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
    const facts = await screen.findByRole("list", { name: "Trip summary" }).catch(() => screen.findByTestId("trip-summary"));
    await waitFor(() => expect(within(facts).getByText("Days", { selector: "dt" })).toBeTruthy());
    expect([...facts.querySelectorAll("dt")].map((d) => d.textContent)).toEqual(["Days", "Nights away", "Distance", "Photos"]);
    expect([...facts.querySelectorAll("dd")].map((d) => d.textContent)).toEqual(["8 days", "7 nights", "1,240 mi", "214 photos"]);
    expect(facts.querySelectorAll("dt.sr-only")).toHaveLength(4);
    expect(screen.getByTestId("avatar-stack")).toHaveAttribute("role", "img");
    expect(screen.getByText("$4,312.00", { exact: false }).closest("[data-trip-total]")).toBeTruthy();
  });

  it("leaves the total out when costs are not shown", async () => {
    show({ costsShown: false, trip: { ...roadTrip, costs: { totals: [{ currency: "USD", amount_minor: 431200 }], priced: 1, bookings: 1 } } });
    await settled().catch(() => null);
    expect(document.querySelector("[data-trip-total]")).toBeNull();
  });

  it("links the photos that need a look, counting only far photos of people the viewer acts for", async () => {
    photos = [1, 2, 3, 4, 5].map((id) => shot(id)).concat([shot(6, 1, { match: "far", distance_km: 500 }), shot(7, 1, { match: "far", distance_km: 500 }), shot(8, 1, { match: "far", person_id: 2 })]);
    best = [1, 2, 3];
    show();
    const link = await screen.findByRole("link", { name: "2 photos need a look" });
    expect(link).toHaveAttribute("href", "#settings/photos");
    expect(link.firstElementChild?.className).toContain("status-warn");
  });

  it("says one photo needs a look in the singular and shows no chip for none", async () => {
    photos = [1, 2, 3, 4].map((id) => shot(id)).concat([shot(5, 1, { match: "far", distance_km: 500 })]);
    best = [1, 2, 3];
    show();
    expect(await screen.findByRole("link", { name: "1 photo needs a look" })).toBeTruthy();
  });

  it("has no need-a-look chip when no photo is far", async () => {
    photos = [1, 2, 3, 4].map((id) => shot(id));
    best = [1, 2, 3];
    show();
    await screen.findByTestId("trip-hero");
    await waitFor(() => expect(screen.getByRole("button", { name: "Photo 1, Sun Mar 1, Marlow Springs" })).toBeTruthy());
    expect(screen.queryByRole("link", { name: /need a look/ })).toBeNull();
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

  it("draws a day as a dot on a rail with its date, place and photo count, a route glyph, six photos and a +N tile", async () => {
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
    expect(two.querySelector("svg[aria-hidden='true']")).toBeTruthy();
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
    const row = await screen.findByRole("button", { name: "Bookings · 3, 2 flights · 1 stay" });
    expect(row).toHaveAttribute("aria-haspopup", "dialog");
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
  const sharingButton = () => screen.findByRole("button", { name: "Sharing" });
  const before = (a: Element, b: Element) => !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

  it("sits alone in the row under a photo hero when View photos isn't drawn, with the card only in the panel", async () => {
    photos = many(6);
    best = [1, 2, 3];
    sharingReply = async () => sharing();
    show();
    const button = await sharingButton();
    expect(screen.queryByRole("button", { name: "View photos" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Your photos on this trip" })).toBeNull();
    expect(before(screen.getByTestId("trip-hero"), button)).toBe(true);
    expect(before(button, screen.getByTestId("trip-summary"))).toBe(true);
    await userEvent.click(button);
    const panel = await screen.findByRole("dialog", { name: "Photo sharing for this trip" });
    expect(within(panel).getByRole("region", { name: "Your photos on this trip" })).toBeTruthy();
    expect(panel.className).toContain("left-[-6px]");
    expect(screen.queryByRole("button", { name: "Select your photos to remove" })).toBeNull();
  });

  it("sits beside View photos when the hero takes every photo", async () => {
    photos = many(3);
    best = [1, 2, 3];
    sharingReply = async () => sharing();
    show();
    const button = await sharingButton();
    const view = screen.getByRole("button", { name: "View photos" });
    expect(view.parentElement).toBe(button.parentElement?.parentElement);
    expect(before(view, button)).toBe(true);
  });

  it("sits alone in its own row under the map when the hero is the map", async () => {
    photos = many(2);
    best = [1, 2];
    sharingReply = async () => sharing();
    show({ trip: flown });
    const button = await sharingButton();
    expect(screen.queryByTestId("trip-hero")).toBeNull();
    expect(screen.queryByRole("button", { name: "View photos" })).toBeNull();
    expect(before(await screen.findByRole("region", { name: "Route replay" }), button)).toBe(true);
    expect(before(button, screen.getByTestId("trip-summary"))).toBe(true);
  });

  it("holds a blank slot while the sharing state loads, then shows the button in its place", async () => {
    photos = many(6);
    best = [1, 2, 3];
    let release: (value: PhotoSharing) => void = () => {};
    sharingReply = () => new Promise((resolve) => { release = resolve; });
    show();
    const slot = await screen.findByTestId("sharing-slot");
    expect(slot.textContent).toBe("");
    expect(screen.queryByRole("button", { name: "Sharing" })).toBeNull();
    release(sharing());
    await sharingButton();
    expect(screen.queryByTestId("sharing-slot")).toBeNull();
  });

  it("shows no button and no slot to a person with no sharing control once the state is known", async () => {
    photos = many(6);
    best = [1, 2, 3];
    show();
    await settled();
    await waitFor(() => expect(screen.queryByTestId("sharing-slot")).toBeNull());
    expect(screen.queryByRole("button", { name: "Sharing" })).toBeNull();
  });

  it("collapses the row under the map once, for a person with no control", async () => {
    show({ trip: flown });
    await screen.findByTestId("no-photos");
    await waitFor(() => expect(screen.queryByTestId("sharing-slot")).toBeNull());
    expect(screen.queryByRole("button", { name: "Sharing" })).toBeNull();
  });

  it("keeps the first-visit prompt above the days, with no button", async () => {
    photos = many(6);
    best = [1, 2, 3];
    sharingReply = async () => sharing({ state: "ask", scope: null });
    show();
    const prompt = await screen.findByRole("group", { name: /Your photos|photos/i });
    expect(screen.queryByRole("button", { name: "Sharing" })).toBeNull();
    expect(before(prompt, days()[0])).toBe(true);
  });

  it("puts the reminder after Not now directly under the button row, above the days, with no button", async () => {
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

  it("shows the button of the next trip after moving from one with no control, in the same page", async () => {
    photos = many(2);
    best = [];
    const next = trip([stay, there, back], { id: 8, name: "Autumn loop", destination: "Utah", start_date: "2026-03-01", end_date: "2026-03-08" });
    sharingReply = async () => NO_SHARING;
    vi.mocked(api).mockImplementation(async (path) => {
      const p = String(path);
      if (p.includes("/photo-sharing")) return (p.includes("/trips/8/") ? sharing() : NO_SHARING) as never;
      if (p === "/api/photo-sources") return { sources, permissions: [] } as never;
      if (p.endsWith("/photos")) return reply(photos, best) as never;
      if (p.endsWith("/summary")) return summary as never;
      if (p === "/api/distance-unit") return { distance_unit: "mi" } as never;
      if (p.endsWith("/places")) return places as never;
      throw new Error(`unexpected ${p}`);
    });
    const view = show({ trip: flown });
    await settled();
    await waitFor(() => expect(screen.queryByTestId("sharing-slot")).toBeNull());
    await view.rerender({ trip: next } as never);
    expect(await sharingButton()).toBeTruthy();
  });

  it("opens the panel as a sheet on a phone", async () => {
    viewport.phone = true;
    photos = many(6);
    best = [1, 2, 3];
    sharingReply = async () => sharing();
    show();
    await userEvent.click(await sharingButton());
    const sheet = await screen.findByRole("dialog", { name: "Photo sharing for this trip" });
    expect(within(sheet).getByRole("region", { name: "Your photos on this trip" })).toBeTruthy();
    viewport.phone = false;
  });
});
