// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { Person, PhotoSharing, PhotoSource, TripPhoto, TripPhotos as Reply } from "$lib/api-types";
import { app } from "$lib/app.svelte";
import { toast } from "svelte-sonner";
import { segment, state, trip } from "../../test/fixtures";
import TripPhotos from "./TripPhotos.svelte";

const user = userEvent.setup({ pointerEventsCheck: 0 });

class Refusal extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

type Call = { method?: string; body?: unknown };
type Body = Record<string, unknown>;

const person = (id: number, display_name: string, first_name: string, member: boolean): Person => ({ id, display_name, first_name, legal_name: null, aliases: [], member, links: [] });
const ada = person(1, "Ada Brook", "Ada", true);
const theo = person(2, "Theo Brook", "Theo", true);
const june = person(3, "June Brook", "June", false);
const stay = segment({ id: 2, kind: "hotel", origin: "Juniper House", destination: "Marlow Springs", start_local: "2026-03-01T15:00", start_zone: "America/Denver", end_local: "2026-03-04T11:00", end_zone: "America/Denver" });
const road = trip([stay], { id: 7, name: "Four Corners loop", start_date: "2026-03-01", end_date: "2026-03-04", people: [1, 2, 3] });
const after = Date.parse("2026-04-01T12:00:00Z");
const WINDOW = { start: "2026-02-28T12:00:00+00:00", end: "2026-03-05T12:00:00+00:00" };

const shot = (id: number, who = 1, extra: Partial<TripPhoto> = {}): TripPhoto => ({
  id, person_id: who, trip_id: 7, kind: "image", taken_local: `2026-03-01T${String(8 + id).padStart(2, "0")}:00`, zone: "America/Denver", latitude: 39.7, longitude: -105, location_source: "exif",
  segment_id: 2, match: "place", distance_km: 3, cluster: 0, removed_at: null, ...extra,
});
const reply = (photos: TripPhoto[]): Reply => ({ photos, clusters: [], counts: { total: photos.length, located: photos.length, inferred: 0, far: 0 }, people: [] });
const source: PhotoSource = { id: 7, person_id: 1, url: "https://immich.brook.example", label: null, status: "ok", mine: true, last_sync: "2026-03-05T06:00", last_error: null, photos: 0, trips: 0 };

let visible: TripPhoto[];
let gone: TripPhoto[];
let stamp: number;
let scope: "only_me" | "trip";
let onPhotos: () => unknown;
let onExclude: (body: Body) => unknown;
let onPutBack: (id: number, created: string | null) => unknown;
let onSharing: (call: Call | undefined, person: number) => unknown;

const tokenOf = (n: number) => `t${gone.length}n${n}`.padEnd(32, "0");
function sharingFor(who: number): PhotoSharing {
  const mine = gone.filter((p) => p.person_id === who);
  return {
    state: "shared", scope, count: visible.filter((p) => p.person_id === who).length, removed_count: mine.length, removed: mine, window: WINDOW, changed: 1700000000,
    audience: [1, 2, 3], sources: [{ id: 7, status: "ok" }], count_token: tokenOf(who),
  };
}

function serve() {
  vi.mocked(api).mockImplementation(async (path: string, opts?: Call) => {
    const method = opts?.method ?? "GET";
    if (path === "/api/photo-grants") return { people: [{ person_id: 3, prefs: { default_scope: "only_me", share_all: false }, count_token: "g".repeat(32), sources: [], eligible: [], trips: [] }] } as never;
    if (path === "/api/photo-sources") return { sources: [source], permissions: [] } as never;
    if (path.endsWith("/photos")) {
      const custom = onPhotos();
      return (custom === undefined ? reply(visible) : custom) as never;
    }
    if (path === "/api/trips/7/photo-exclusions" && method === "POST") {
      const custom = onExclude(opts?.body as Body);
      if (custom !== undefined) return custom as never;
      const ids = (opts?.body as { photo_ids: number[] }).photo_ids;
      const moving = visible.filter((p) => ids.includes(p.id));
      visible = visible.filter((p) => !ids.includes(p.id));
      stamp += 1;
      gone = [...gone, ...moving.map((p) => ({ ...p, removed_at: stamp }))];
      return sharingFor(moving[0].person_id) as never;
    }
    const back = /^\/api\/trips\/7\/photo-exclusions\/(\d+)(?:\?created=(.*))?$/.exec(path);
    if (back && method === "DELETE") {
      const id = Number(back[1]);
      const custom = onPutBack(id, back[2] ?? null);
      if (custom !== undefined) return custom as never;
      const found = gone.find((p) => p.id === id);
      gone = gone.filter((p) => p.id !== id);
      if (found) visible = [...visible, { ...found, removed_at: null }].sort((a, b) => a.id - b.id);
      return sharingFor(found?.person_id ?? 1) as never;
    }
    const sharing = /^\/api\/trips\/7\/photo-sharing\?person_id=(\d+)$/.exec(path);
    if (sharing) {
      const custom = onSharing(opts, Number(sharing[1]));
      return (custom === undefined ? sharingFor(Number(sharing[1])) : custom) as never;
    }
    if (path === "/api/trips/7/photo-sharing" && method === "POST") return sharingFor(1) as never;
    throw new Error(`unexpected ${method} ${path}`);
  });
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((a, b) => { resolve = a; reject = b; });
  return { promise, resolve, reject };
}

const calls = (method: string, match: string) => vi.mocked(api).mock.calls.filter(([p, o]) => String(p).includes(match) && ((o as Call | undefined)?.method ?? "GET") === method);
const sent = (method: string, match: string) => calls(method, match).map(([, o]) => (o as Call).body as Body);
const toastOf = (n = 0) => vi.mocked(toast).mock.calls[n] as unknown as [string, { action: { label: string; onClick: () => void } }];

type Props = { trip?: typeof road; people?: Person[]; onchanged?: () => void; onloaded?: (found: Reply | null) => void };
const mount = (extra: Props = {}) => render(TripPhotos, { trip: extra.trip ?? road, people: extra.people ?? [ada, theo], now: after, onchanged: extra.onchanged, onloaded: extra.onloaded });
const photosSection = () => screen.findByRole("region", { name: /^Photos/ });
const tile = (name: RegExp | string) => screen.findByRole("button", { name });
const viewer = () => screen.findByRole("dialog");
const removeButton = () => screen.getByRole("button", { name: "Remove from this trip" });

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(toast).mockReset();
  vi.mocked(toast.success).mockReset();
  vi.mocked(toast.error).mockReset();
  app.state = state({ person_id: 1 });
  visible = [shot(1), shot(2), shot(3)];
  gone = [];
  stamp = 1800000000;
  scope = "trip";
  onPhotos = () => undefined;
  onExclude = () => undefined;
  onPutBack = () => undefined;
  onSharing = () => undefined;
  serve();
});
afterEach(() => { app.state = null; });

describe("Remove from this trip, in the viewer", () => {
  it("is there only on the photos of the person the page acts for, and names a person who is managed", async () => {
    visible = [shot(1), shot(2, 2), shot(3, 3)];
    mount({ people: [ada, theo, june] });
    await photosSection();
    await user.click(await tile(/^Photo, 9:00 AM/));
    expect(await viewer()).toBeTruthy();
    expect(screen.getByRole("button", { name: "Remove from this trip" })).toBeEnabled();
    await user.keyboard("{ArrowRight}");
    await waitFor(() => expect(screen.getByRole("dialog")).toHaveAccessibleName("Photo 2 of 3"));
    expect(screen.queryByRole("button", { name: /^Remove/ })).toBeNull();
    await user.keyboard("{ArrowRight}");
    await waitFor(() => expect(screen.getByRole("dialog")).toHaveAccessibleName("Photo 3 of 3"));
    expect(screen.getByRole("button", { name: "Remove June’s photo from this trip" })).toBeEnabled();
  });

  it("removes the open photo, moves to the next one at once, and updates the gallery, the card, the toast and the page", async () => {
    const onchanged = vi.fn();
    const onloaded = vi.fn();
    mount({ onchanged, onloaded });
    await photosSection();
    expect(await screen.findByRole("button", { name: /^Photo, 9:00 AM/ })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /^Photo, 10:00 AM/ }));
    await viewer();
    expect(screen.getByRole("dialog")).toHaveAccessibleName("Photo 2 of 3");
    onloaded.mockClear();
    onchanged.mockClear();
    await user.click(removeButton());
    await waitFor(() => expect(sent("POST", "/photo-exclusions")).toEqual([{ photo_ids: [2] }]));
    await waitFor(() => expect(screen.getByRole("dialog")).toHaveAccessibleName("Photo 2 of 2"));
    expect(within(screen.getByRole("dialog")).getByText("11:00 AM")).toBeTruthy();
    expect(toastOf()[0]).toBe("Removed from Four Corners loop.");
    expect(toastOf()[1].action.label).toBe("Undo");
    await waitFor(() => expect(onchanged).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(onloaded).toHaveBeenCalled());
    expect(onloaded.mock.calls.at(-1)?.[0].photos.map((p: TripPhoto) => p.id)).toEqual([1, 3]);
    expect(within(screen.getByRole("dialog")).getByRole("status").textContent).toBe("Photo 2 of 2");
    expect(document.activeElement).toBe(screen.getByRole("dialog").querySelector(".photo-viewer-stage"));
    await user.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(within(screen.getByTestId("photo-strip")).getAllByRole("button", { name: /^Photo,/ })).toHaveLength(2);
    expect(screen.getByRole("heading", { level: 2, name: /^Photos/ }).textContent).toBe("Photos2");
    const mine = await screen.findByTestId("your-photos");
    expect(within(mine).getByText("2 photos from your library")).toBeTruthy();
    expect(within(mine).getByRole("button", { name: "Removed from this trip (1)" })).toHaveAttribute("aria-expanded", "false");
  });

  it("moves to the previous photo when the last one is removed", async () => {
    mount();
    await photosSection();
    await user.click(await tile(/^Photo, 11:00 AM/));
    await viewer();
    await user.click(removeButton());
    await waitFor(() => expect(screen.getByRole("dialog")).toHaveAccessibleName("Photo 2 of 2"));
    expect(within(screen.getByRole("dialog")).getByText("10:00 AM")).toBeTruthy();
  });

  it("closes the viewer, and gives focus back to the section, when the last photo is removed", async () => {
    visible = [shot(1)];
    mount();
    await photosSection();
    await user.click(await tile(/^Photo, 9:00 AM/));
    await viewer();
    await user.click(removeButton());
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.queryByTestId("photo-strip")).toBeNull();
    expect(screen.getByText("No photos on this trip.")).toBeTruthy();
    expect(within(await screen.findByTestId("your-photos")).getByText("No photos from your library on this trip")).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("heading", { level: 2, name: /^Photos/ })));
  });

  it("puts the photo back with Undo, sending the stamp the removal answered with, and shows it in its place again", async () => {
    mount();
    await photosSection();
    await user.click(await tile(/^Photo, 10:00 AM/));
    await viewer();
    await user.click(removeButton());
    await waitFor(() => expect(toast).toHaveBeenCalled());
    await waitFor(() => expect(within(screen.getByTestId("photo-strip")).getAllByRole("button", { name: /^Photo,/ })).toHaveLength(2));
    toastOf()[1].action.onClick();
    await waitFor(() => expect(calls("DELETE", "/photo-exclusions/2")).toHaveLength(1));
    expect(vi.mocked(api).mock.calls.find(([p]) => String(p).includes("/photo-exclusions/2"))?.[0]).toBe("/api/trips/7/photo-exclusions/2?created=1800000001");
    await waitFor(() => expect(within(screen.getByTestId("photo-strip")).getAllByRole("button", { name: /^Photo,/ })).toHaveLength(3));
    expect(within(screen.getByTestId("photo-strip")).getAllByRole("button", { name: /^Photo,/ }).map((b) => b.getAttribute("data-photo"))).toEqual(["1", "2", "3"]);
  });

  it("holds Remove, Select and the card’s controls through the request and the reload, and lets go when it is done", async () => {
    mount();
    await photosSection();
    await user.click(await tile(/^Photo, 9:00 AM/));
    await viewer();
    const request = deferred<PhotoSharing>();
    onExclude = () => request.promise;
    const reload = deferred<Reply>();
    await user.click(removeButton());
    await waitFor(() => expect(removeButton()).toBeDisabled());
    expect(sent("POST", "/photo-exclusions")).toHaveLength(1);
    await user.click(removeButton());
    expect(sent("POST", "/photo-exclusions")).toHaveLength(1);
    onPhotos = () => reload.promise;
    visible = [shot(2), shot(3)];
    gone = [{ ...shot(1), removed_at: 1800000001 }];
    request.resolve(sharingFor(1));
    await waitFor(() => expect(calls("GET", "/photos").length).toBeGreaterThan(1));
    expect(removeButton()).toBeDisabled();
    reload.resolve(reply(visible));
    await waitFor(() => expect(removeButton()).toBeEnabled());
  });

  it("releases the controls, keeps the viewer on the photo and says so when the removal fails", async () => {
    mount();
    await photosSection();
    await user.click(await tile(/^Photo, 9:00 AM/));
    await viewer();
    onExclude = () => { throw new Refusal("Couldn’t remove it (500)", 500); };
    await user.click(removeButton());
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Couldn’t remove it (500)"));
    expect(removeButton()).toBeEnabled();
    expect(screen.getByRole("dialog")).toHaveAccessibleName("Photo 1 of 3");
    expect(toast).not.toHaveBeenCalled();
    expect(calls("GET", "/photos")).toHaveLength(1);
  });

  it("looks at the photos again when the server says the photo isn’t there, since the list is out of date", async () => {
    mount();
    await photosSection();
    await user.click(await tile(/^Photo, 9:00 AM/));
    await viewer();
    onExclude = () => { visible = [shot(2), shot(3)]; throw new Refusal("No such photo", 404); };
    await user.click(removeButton());
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("No such photo"));
    await waitFor(() => expect(calls("GET", "/photos")).toHaveLength(2));
    await waitFor(() => expect(screen.getByRole("dialog")).toHaveAccessibleName("Photo no longer shared"));
  });

  it("says the photos may be out of date when they can’t be reloaded, and does not bring the removed photo back", async () => {
    mount();
    await photosSection();
    await user.click(await tile(/^Photo, 9:00 AM/));
    await viewer();
    let failing = false;
    onPhotos = () => { if (failing) throw new Refusal("Waypoint is unreachable", 503); return undefined; };
    onExclude = () => { failing = true; return undefined; };
    await user.click(removeButton());
    expect(await screen.findByText("Couldn’t refresh the photos on this trip, so what shows may be out of date.")).toBeTruthy();
    expect(screen.getByRole("dialog")).toHaveAccessibleName("Photo 1 of 2");
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(within(screen.getByTestId("photo-strip")).getAllByRole("button", { name: /^Photo,/ })).toHaveLength(2);
    expect(removeButton).toThrow();
    failing = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.queryByText(/Couldn’t refresh the photos/)).toBeNull());
    expect(within(screen.getByTestId("photo-strip")).getAllByRole("button", { name: /^Photo,/ })).toHaveLength(2);
  });

  it("does not let a load that began before the removal bring the photo back", async () => {
    const { rerender } = mount();
    await photosSection();
    expect(await screen.findByRole("button", { name: /^Photo, 9:00 AM/ })).toBeTruthy();
    const older = deferred<Reply>();
    onPhotos = () => older.promise;
    await rerender({ trip: { ...road, end_date: "2026-03-05" } });
    await waitFor(() => expect(calls("GET", "/photos")).toHaveLength(2));
    onPhotos = () => undefined;
    await user.click(screen.getByRole("button", { name: /^Photo, 9:00 AM/ }));
    await viewer();
    await user.click(removeButton());
    await waitFor(() => expect(sent("POST", "/photo-exclusions")).toHaveLength(1));
    await waitFor(() => expect(calls("GET", "/photos").length).toBeGreaterThan(2));
    older.resolve(reply([shot(1), shot(2), shot(3)]));
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.getByRole("dialog")).toHaveAccessibleName("Photo 1 of 2");
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(within(screen.getByTestId("photo-strip")).getAllByRole("button", { name: /^Photo,/ })).toHaveLength(2);
    expect(screen.queryByRole("button", { name: /^Photo, 9:00 AM/ })).toBeNull();
  });

  it("serves an Undo that comes while another change is under way only once that change is done", async () => {
    mount();
    await photosSection();
    await user.click(await tile(/^Photo, 9:00 AM/));
    await viewer();
    await user.click(removeButton());
    await waitFor(() => expect(toast).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByRole("dialog")).toHaveAccessibleName("Photo 1 of 2"));
    await waitFor(() => expect(removeButton()).toBeEnabled());
    const second = deferred<PhotoSharing>();
    onExclude = () => second.promise;
    await user.click(removeButton());
    await waitFor(() => expect(sent("POST", "/photo-exclusions")).toHaveLength(2));
    toastOf(0)[1].action.onClick();
    await new Promise((r) => setTimeout(r, 20));
    expect(calls("DELETE", "/photo-exclusions")).toHaveLength(0);
    visible = [shot(3)];
    gone = [{ ...shot(1), removed_at: 1800000001 }, { ...shot(2), removed_at: 1800000002 }];
    second.resolve(sharingFor(1));
    await waitFor(() => expect(calls("DELETE", "/photo-exclusions")).toHaveLength(1));
  });
});

describe("The viewer when the list changes under it", () => {
  it("stays on the photo it shows when an earlier photo leaves the list", async () => {
    const { rerender } = mount();
    await photosSection();
    await user.click(await tile(/^Photo, 11:00 AM/));
    await viewer();
    expect(screen.getByRole("dialog")).toHaveAccessibleName("Photo 3 of 3");
    visible = [shot(2), shot(3)];
    await rerender({ trip: { ...road, end_date: "2026-03-05" } });
    await waitFor(() => expect(screen.getByRole("dialog")).toHaveAccessibleName("Photo 2 of 2"));
    expect(within(screen.getByRole("dialog")).getByText("11:00 AM")).toBeTruthy();
  });

  it("says a photo is no longer shared when a reload no longer lists it, and goes on to the next from there", async () => {
    const { rerender } = mount();
    await photosSection();
    await user.click(await tile(/^Photo, 10:00 AM/));
    await viewer();
    visible = [shot(1), shot(3)];
    await rerender({ trip: { ...road, end_date: "2026-03-05" } });
    await waitFor(() => expect(screen.getByRole("dialog")).toHaveAccessibleName("Photo no longer shared"));
    expect(screen.getByText("It isn’t shared with you any more.")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Next photo" }));
    await waitFor(() => expect(screen.getByRole("dialog")).toHaveAccessibleName("Photo 2 of 2"));
    expect(within(screen.getByRole("dialog")).getByText("11:00 AM")).toBeTruthy();
  });

  it("offers the previous photo when the last one left, and closes when none is left", async () => {
    const { rerender } = mount();
    await photosSection();
    await user.click(await tile(/^Photo, 11:00 AM/));
    await viewer();
    visible = [shot(1), shot(2)];
    await rerender({ trip: { ...road, end_date: "2026-03-05" } });
    await waitFor(() => expect(screen.getByRole("dialog")).toHaveAccessibleName("Photo no longer shared"));
    expect(screen.queryByRole("button", { name: "Next photo" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Previous photo" }));
    await waitFor(() => expect(screen.getByRole("dialog")).toHaveAccessibleName("Photo 2 of 2"));
    visible = [];
    await rerender({ trip: { ...road, end_date: "2026-03-06" } });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("checks the list again when a preview can’t be loaded, and says the photo is gone only if it is", async () => {
    mount();
    await photosSection();
    await user.click(await tile(/^Photo, 9:00 AM/));
    const dialog = await viewer();
    visible = [shot(2), shot(3)];
    dialog.querySelector("img")!.dispatchEvent(new Event("error"));
    await waitFor(() => expect(calls("GET", "/photos")).toHaveLength(2));
    await waitFor(() => expect(screen.getByRole("dialog")).toHaveAccessibleName("Photo no longer shared"));
  });
});

describe("Select, in the gallery", () => {
  const gallery = async () => {
    await photosSection();
    await user.click(await screen.findByRole("button", { name: "Select your photos to remove" }));
    return screen.findByTestId("photo-selection");
  };

  it("is not there for someone with no photo of their own on the trip", async () => {
    visible = [shot(1, 2), shot(2, 2)];
    mount();
    await photosSection();
    await screen.findByTestId("photo-strip");
    expect(screen.queryByRole("button", { name: "Select your photos to remove" })).toBeNull();
  });

  it("makes your tiles checkboxes, leaves other people’s as pictures that can’t be selected, and removes the chosen ones in one request", async () => {
    visible = [shot(1), shot(2, 2), shot(3), shot(4)];
    mount();
    const bar = await gallery();
    expect(within(bar).getByRole("status").textContent).toBe("0 selected");
    expect(within(bar).getByRole("button", { name: "Remove from this trip" })).toBeDisabled();
    expect(screen.getByText("You can select only your own photos.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Show fewer" })).toHaveAttribute("aria-expanded", "true");
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes).toHaveLength(3);
    expect(boxes.every((b) => b.getAttribute("aria-checked") === "false")).toBe(true);
    const others = screen.getByRole("img", { name: "Photo by Theo, 10:00 AM, not yours to remove" });
    expect(others.getAttribute("tabindex")).toBeNull();
    await user.click(boxes[0]);
    await user.click(boxes[2]);
    expect(within(bar).getByRole("status").textContent).toBe("2 selected");
    expect(boxes[0]).toHaveAttribute("aria-checked", "true");
    await user.click(boxes[2]);
    await user.click(boxes[2]);
    await user.click(within(bar).getByRole("button", { name: "Remove from this trip" }));
    await waitFor(() => expect(sent("POST", "/photo-exclusions")).toEqual([{ photo_ids: [1, 4] }]));
    await waitFor(() => expect(toast).toHaveBeenCalled());
    expect(toastOf()[0]).toBe("2 photos removed from Four Corners loop.");
    await waitFor(() => expect(screen.queryByTestId("photo-selection")).toBeNull());
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.getByRole("heading", { level: 2, name: /^Photos/ }).textContent).toBe("Photos2");
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Select your photos to remove" })));
  });

  it("leaves select mode on Cancel and on Escape, sending nothing", async () => {
    mount();
    const bar = await gallery();
    await user.click(screen.getAllByRole("checkbox")[0]);
    await user.click(within(bar).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByTestId("photo-selection")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Select your photos to remove" }));
    expect(screen.getByTestId("photo-selection").textContent).toContain("0 selected");
    await user.keyboard("{Escape}");
    expect(screen.queryByTestId("photo-selection")).toBeNull();
    expect(sent("POST", "/photo-exclusions")).toHaveLength(0);
  });

  it("keeps the selection and says so when the removal fails", async () => {
    mount();
    const bar = await gallery();
    await user.click(screen.getAllByRole("checkbox")[1]);
    onExclude = () => { throw new Refusal("Couldn’t remove it (500)", 500); };
    await user.click(within(bar).getByRole("button", { name: "Remove from this trip" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Couldn’t remove it (500)"));
    expect(screen.getByTestId("photo-selection").textContent).toContain("1 selected");
    expect(within(bar).getByRole("button", { name: "Remove from this trip" })).toBeEnabled();
    expect(screen.getAllByRole("checkbox")[1]).toHaveAttribute("aria-checked", "true");
  });

  it("holds the controls while the removal is under way", async () => {
    mount();
    const bar = await gallery();
    await user.click(screen.getAllByRole("checkbox")[0]);
    const request = deferred<PhotoSharing>();
    onExclude = () => request.promise;
    await user.click(within(bar).getByRole("button", { name: "Remove from this trip" }));
    await waitFor(() => expect(within(bar).getByRole("button", { name: "Remove from this trip" })).toBeDisabled());
    expect(within(bar).getByRole("button", { name: "Cancel" })).toBeDisabled();
    for (const box of screen.getAllByRole("checkbox")) expect(box).toBeDisabled();
    visible = [shot(2), shot(3)];
    gone = [{ ...shot(1), removed_at: 1800000001 }];
    request.resolve(sharingFor(1));
    await waitFor(() => expect(screen.queryByTestId("photo-selection")).toBeNull());
  });

  it("drops a selected photo that leaves the list, and leaves select mode when none of yours is left", async () => {
    const { rerender } = mount();
    const bar = await gallery();
    await user.click(screen.getAllByRole("checkbox")[0]);
    expect(within(bar).getByRole("status").textContent).toBe("1 selected");
    visible = [shot(2), shot(3)];
    await rerender({ trip: { ...road, end_date: "2026-03-05" } });
    await waitFor(() => expect(within(screen.getByTestId("photo-selection")).getByRole("status").textContent).toBe("0 selected"));
    visible = [shot(2, 2)];
    await rerender({ trip: { ...road, end_date: "2026-03-06" } });
    await waitFor(() => expect(screen.queryByTestId("photo-selection")).toBeNull());
  });

  it("asks once for each person it acts for, in the order of the photos, and stops at the first that fails", async () => {
    visible = [shot(1), shot(2, 3), shot(3)];
    mount({ people: [ada, theo, june] });
    const bar = await gallery();
    expect(screen.getByText("You can select only your own photos and those of people you manage.")).toBeTruthy();
    for (const box of screen.getAllByRole("checkbox")) await user.click(box);
    expect(within(bar).getByRole("button", { name: "Remove from this trip" })).toBeEnabled();
    onExclude = (body) => { if ((body.photo_ids as number[]).includes(2)) throw new Refusal("Couldn’t remove it (500)", 500); return undefined; };
    await user.click(within(bar).getByRole("button", { name: "Remove from this trip" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(sent("POST", "/photo-exclusions")).toEqual([{ photo_ids: [1, 3] }, { photo_ids: [2] }]);
    expect(screen.getByTestId("photo-selection").textContent).toContain("1 selected");
  });

  it("names a managed person when that is the only one chosen", async () => {
    visible = [shot(1), shot(2, 3), shot(3, 3)];
    mount({ people: [ada, theo, june] });
    const bar = await gallery();
    const boxes = screen.getAllByRole("checkbox");
    await user.click(boxes[1]);
    await user.click(boxes[2]);
    await user.click(within(bar).getByRole("button", { name: "Remove June’s photos from this trip" }));
    await waitFor(() => expect(sent("POST", "/photo-exclusions")).toEqual([{ photo_ids: [2, 3] }]));
    expect(toastOf()[0]).toBe("2 of June’s photos removed from Four Corners loop.");
  });

  it("puts every photo of a bulk removal back with Undo, each with its own stamp, and says how far it got if one fails", async () => {
    mount();
    const bar = await gallery();
    const boxes = screen.getAllByRole("checkbox");
    await user.click(boxes[0]);
    await user.click(boxes[1]);
    await user.click(within(bar).getByRole("button", { name: "Remove from this trip" }));
    await waitFor(() => expect(toast).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByTestId("photo-selection")).toBeNull());
    onPutBack = (id) => { if (id === 2) throw new Refusal("Your photo was removed again since. Review it under Your photos on this trip.", 409); return undefined; };
    toastOf()[1].action.onClick();
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(vi.mocked(api).mock.calls.filter(([p, o]) => (o as Call | undefined)?.method === "DELETE" && String(p).includes("photo-exclusions")).map(([p]) => p)).toEqual([
      "/api/trips/7/photo-exclusions/1?created=1800000001",
      "/api/trips/7/photo-exclusions/2?created=1800000001",
    ]);
    expect(vi.mocked(toast.error).mock.calls[0][0]).toBe("Your photo was removed again since. Review it under Your photos on this trip.");
  });
});

describe("Removed from this trip, on the card", () => {
  const open = async () => {
    const mine = await screen.findByTestId("your-photos");
    await user.click(within(mine).getByRole("button", { name: /^Removed from this trip/ }));
    return mine;
  };

  beforeEach(() => {
    gone = [{ ...shot(5), removed_at: 1700000100 }, { ...shot(6, 1, { kind: "video" }), removed_at: 1700000200 }];
    visible = [shot(1), shot(2)];
  });

  it("is a closed disclosure with the count, which lists what only you see, each with Put back", async () => {
    mount();
    const mine = await screen.findByTestId("your-photos");
    expect(within(mine).getByText("2 photos from your library")).toBeTruthy();
    const button = within(mine).getByRole("button", { name: "Removed from this trip (2)" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(within(mine).queryByRole("list")).toBeNull();
    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(button.getAttribute("aria-controls")).toBe(within(mine).getByRole("list", { name: "Photos you removed from this trip" }).parentElement?.id);
    expect(within(mine).getByText("Only you see these. Nobody else on the trip can tell they were here.")).toBeTruthy();
    expect(within(mine).getAllByRole("listitem")).toHaveLength(2);
    expect(within(mine).getByRole("button", { name: "Put back the photo from Sun, Mar 1, 1:00 PM" })).toBeEnabled();
    expect(within(mine).getByRole("button", { name: "Put back the video from Sun, Mar 1, 2:00 PM" })).toBeEnabled();
    expect(mine.querySelector("img")?.getAttribute("src")).toBe("/api/trips/7/photo-exclusions/5/thumbnail");
    expect(within(mine).getAllByRole("button", { name: /^Put back/ }).map((b) => b.textContent)).toEqual(["Put back", "Put back"]);
  });

  it("has no disclosure when nothing is removed", async () => {
    gone = [];
    mount();
    const mine = await screen.findByTestId("your-photos");
    expect(within(mine).queryByRole("button", { name: /^Removed from this trip/ })).toBeNull();
  });

  it("puts a photo back with the stamp it was listed with, drops it from the list at once and reloads the gallery, the count and the page", async () => {
    const onchanged = vi.fn();
    mount({ onchanged });
    const mine = await open();
    await photosSection();
    onchanged.mockClear();
    await user.click(within(mine).getByRole("button", { name: "Put back the photo from Sun, Mar 1, 1:00 PM" }));
    await waitFor(() => expect(vi.mocked(api).mock.calls.some(([p]) => p === "/api/trips/7/photo-exclusions/5?created=1700000100")).toBe(true));
    await waitFor(() => expect(within(mine).getByText("3 photos from your library")).toBeTruthy());
    expect(within(mine).getAllByRole("listitem")).toHaveLength(1);
    expect(within(mine).getByRole("button", { name: "Removed from this trip (1)" })).toBeTruthy();
    await waitFor(() => expect(onchanged).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByRole("heading", { level: 2, name: /^Photos/ }).textContent).toBe("Photos3"));
    await waitFor(() => expect(document.activeElement).toBe(within(mine).getByRole("button", { name: "Removed from this trip (1)" })));
  });

  it("closes the list and moves focus to the card’s heading when the last removed photo is put back", async () => {
    gone = [{ ...shot(5), removed_at: 1700000100 }];
    mount();
    const mine = await open();
    await user.click(within(mine).getByRole("button", { name: /^Put back/ }));
    await waitFor(() => expect(within(mine).queryByRole("button", { name: /^Removed from this trip/ })).toBeNull());
    expect(within(mine).queryByRole("list")).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(within(mine).getByRole("heading", { name: "Your photos on this trip" })));
  });

  it("holds Put back, and everything else on the card, until the change and its reload are done", async () => {
    mount();
    const mine = await open();
    const request = deferred<PhotoSharing>();
    onPutBack = () => request.promise;
    await user.click(within(mine).getByRole("button", { name: "Put back the photo from Sun, Mar 1, 1:00 PM" }));
    await waitFor(() => expect(within(mine).getByRole("button", { name: "Put back the video from Sun, Mar 1, 2:00 PM" })).toBeDisabled());
    expect(within(mine).getByRole("button", { name: "Stop sharing on this trip" })).toBeDisabled();
    expect(within(mine).getByRole("radio", { name: /^Only me/ })).toBeDisabled();
    await user.click(within(mine).getByRole("button", { name: "Put back the video from Sun, Mar 1, 2:00 PM" }));
    expect(calls("DELETE", "/photo-exclusions")).toHaveLength(1);
    gone = [gone[1]];
    visible = [...visible, shot(5)];
    request.resolve(sharingFor(1));
    await waitFor(() => expect(within(mine).getByRole("button", { name: "Put back the video from Sun, Mar 1, 2:00 PM" })).toBeEnabled());
  });

  it("says why, releases the card and looks again when the removal was changed meanwhile", async () => {
    mount();
    const mine = await open();
    onPutBack = () => {
      gone = [{ ...shot(5), removed_at: 1700000999 }, gone[1]];
      throw new Refusal("You removed this photo again since. Review it under Your photos on this trip.", 409);
    };
    await user.click(within(mine).getByRole("button", { name: "Put back the photo from Sun, Mar 1, 1:00 PM" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("You removed this photo again since. Review it under Your photos on this trip."));
    await waitFor(() => expect(calls("GET", "/photo-sharing?").length).toBeGreaterThan(1));
    onPutBack = () => undefined;
    await user.click(within(mine).getByRole("button", { name: "Put back the photo from Sun, Mar 1, 1:00 PM" }));
    await waitFor(() => expect(vi.mocked(api).mock.calls.some(([p]) => p === "/api/trips/7/photo-exclusions/5?created=1700000999")).toBe(true));
  });

  it("says the sharing may be out of date, and holds Put back, when the card can’t be reloaded after a change", async () => {
    mount();
    const mine = await open();
    let failing = false;
    onSharing = () => { if (failing) throw new Refusal("Waypoint is unreachable", 503); return undefined; };
    onPutBack = () => { failing = true; return undefined; };
    await user.click(within(mine).getByRole("button", { name: "Put back the photo from Sun, Mar 1, 1:00 PM" }));
    expect(await screen.findByText(/Couldn’t refresh your photo sharing for this trip, so what shows may be out of date\./)).toBeTruthy();
    expect(within(mine).getByRole("button", { name: "Put back the video from Sun, Mar 1, 2:00 PM" })).toBeDisabled();
    failing = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(within(mine).getByRole("button", { name: "Put back the video from Sun, Mar 1, 2:00 PM" })).toBeEnabled());
  });

  it("names a managed person in the card, the list and the buttons", async () => {
    gone = [{ ...shot(5, 3), removed_at: 1700000100 }];
    visible = [shot(1, 3), shot(2)];
    mount({ people: [ada, theo, june] });
    const mine = await screen.findByRole("region", { name: "June’s photos on this trip" });
    await user.click(within(mine).getByRole("button", { name: "Removed from this trip (1)" }));
    expect(within(mine).getByRole("list", { name: "June’s photos removed from this trip" })).toBeTruthy();
    await user.click(within(mine).getByRole("button", { name: /^Put back/ }));
    await waitFor(() => expect(vi.mocked(api).mock.calls.some(([p]) => String(p).startsWith("/api/trips/7/photo-exclusions/5"))).toBe(true));
  });

  it("sends the count and token the removal left when everyone is shown the photos afterwards", async () => {
    scope = "only_me";
    visible = [shot(1), shot(2), shot(3)];
    gone = [];
    mount();
    await photosSection();
    await user.click(await tile(/^Photo, 9:00 AM/));
    await viewer();
    await user.click(removeButton());
    await waitFor(() => expect(screen.getByRole("dialog")).toHaveAccessibleName("Photo 1 of 2"));
    await user.click(screen.getByRole("button", { name: "Close" }));
    const mine = await screen.findByTestId("your-photos");
    await waitFor(() => expect(within(mine).getByText("2 photos from your library")).toBeTruthy());
    await user.click(within(mine).getByRole("radio", { name: /^Everyone on this trip/ }));
    const dialog = await screen.findByRole("dialog", { name: "Show your 2 photos to everyone on this trip?" });
    await user.click(within(dialog).getByRole("button", { name: "Show them" }));
    await waitFor(() => expect(sent("POST", "/photo-sharing")).toHaveLength(1));
    expect(sent("POST", "/photo-sharing")[0].count_token).toBe(tokenOf(1));
  });
});
