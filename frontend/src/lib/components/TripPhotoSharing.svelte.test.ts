// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { Person, PhotoGrantPerson, PhotoSharing, PhotoSource, TripPhoto, TripPhotos as Reply } from "$lib/api-types";
import { app } from "$lib/app.svelte";
import { toast } from "svelte-sonner";
import { segment, state, trip } from "../../test/fixtures";
import { PersonSharing } from "$lib/trip-sharing.svelte";
import TripPhotos from "./TripPhotos.svelte";

const user = userEvent.setup({ pointerEventsCheck: 0 });

class Refusal extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

const STALE = "Your photos or trips changed since they were counted. Review the count before sharing.";
const person = (id: number, display_name: string, first_name: string, member: boolean): Person => ({ id, display_name, first_name, legal_name: null, aliases: [], member, links: [] });
const ada = person(1, "Ada Brook", "Ada", true);
const june = person(3, "June Brook", "June", false);
const stay = segment({ id: 2, kind: "hotel", origin: "Juniper House", destination: "Marlow Springs", start_local: "2026-03-01T15:00", start_zone: "America/Denver", end_local: "2026-03-04T11:00", end_zone: "America/Denver" });
const road = trip([stay], { id: 7, name: "Four Corners loop", start_date: "2026-03-01", end_date: "2026-03-04", people: [1, 2] });
const after = Date.parse("2026-04-01T12:00:00Z");

const WINDOW = { start: "2026-02-28T12:00:00+00:00", end: "2026-03-05T12:00:00+00:00" };
const sharing = (extra: Partial<PhotoSharing> = {}): PhotoSharing => ({
  state: "ask", scope: null, count: 77, removed_count: 0, removed: [], window: WINDOW, changed: null, audience: [1, 2], sources: [{ id: 7, status: "ok" }], count_token: "a".repeat(32), ...extra,
});
const shared = (extra: Partial<PhotoSharing> = {}): PhotoSharing => sharing({ state: "shared", scope: "trip", count: 169, changed: 1700000000, count_token: "c".repeat(32), ...extra });
const photo = (id: number): TripPhoto => ({
  id, person_id: 2, trip_id: 7, kind: "image", taken_local: "2026-03-01T10:42", zone: "America/Denver", latitude: 39.7, longitude: -105, location_source: "exif", segment_id: 2, match: "place", distance_km: 3, cluster: 0, removed_at: null,
});
const reply = (photos: TripPhoto[]): Reply => ({ photos, clusters: [], counts: { total: photos.length, located: photos.length, inferred: 0, far: 0 }, people: [] });
const source = (): PhotoSource => ({ id: 7, person_id: 1, url: "https://immich.brook.example", label: null, status: "ok", mine: true, last_sync: "2026-03-05T06:00", last_error: null, photos: 0, trips: 0 });
const grants = (extra: Partial<PhotoGrantPerson> = {}): PhotoGrantPerson => ({
  person_id: 1, prefs: { default_scope: "only_me", share_all: false }, count_token: "g".repeat(32), sources: [{ id: 7, status: "ok" }], eligible: [], trips: [], ...extra,
});

type Body = Record<string, unknown>;
type Call = { method?: string; body?: unknown };

let current: PhotoSharing;
let photos: TripPhoto[];
let grantList: PhotoGrantPerson[];
let onSharing: (call: Call | undefined, path: string) => unknown;
let onPhotos: () => unknown;

function serve() {
  vi.mocked(api).mockImplementation(async (path: string, opts?: Call) => {
    if (path.includes("/photo-sharing-prefs/")) return { default_scope: "only_me", share_all: true } as never;
    if (path.includes("/photo-sharing")) {
      const custom = onSharing(opts, path);
      return (custom === undefined ? current : custom) as never;
    }
    if (path === "/api/photo-grants") return { people: grantList } as never;
    if (path === "/api/photo-sources") return { sources: [source()], permissions: [] } as never;
    if (path.endsWith("/photos")) {
      const custom = onPhotos();
      return (custom === undefined ? reply(photos) : custom) as never;
    }
    throw new Error(`unexpected ${path}`);
  });
}

const undoOf = (): void => (vi.mocked(toast).mock.calls[0][1] as unknown as { action: { onClick: () => void } }).action.onClick();

const calls = (method: string, match: string) => vi.mocked(api).mock.calls.filter(([p, o]) => String(p).includes(match) && ((o as Call | undefined)?.method ?? "GET") === method);
const sent = (method: string, match: string) => calls(method, match).map(([, o]) => (o as Call).body as Body);
const sharingGets = () => calls("GET", "/photo-sharing?").length;

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((a, b) => { resolve = a; reject = b; });
  return { promise, resolve, reject };
}

const mount = (extra: { onchanged?: () => void; people?: Person[]; trip?: typeof road } = {}) => render(TripPhotos, { trip: extra.trip ?? road, people: extra.people ?? [ada], now: after, onchanged: extra.onchanged });
const prompt = () => screen.findByRole("group", { name: /from this trip$|^Couldn’t check your libraries$/ });
const card = () => screen.findByRole("region", { name: /photos on this trip$/ });

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(toast).mockReset();
  vi.mocked(toast.success).mockReset();
  vi.mocked(toast.error).mockReset();
  app.state = state({ person_id: 1 });
  current = sharing();
  photos = [photo(1), photo(2)];
  grantList = [grants()];
  onSharing = () => undefined;
  onPhotos = () => undefined;
  serve();
});
afterEach(() => { app.state = null; });

describe("Share prompt: what shows", () => {
  it("asks first, with Only me chosen, the count and the three choices, above the strip", async () => {
    mount();
    const ask = await screen.findByRole("group", { name: "You have 77 photos from this trip" });
    expect(within(ask).getByRole("heading", { level: 3, name: "You have 77 photos from this trip" })).toBeInTheDocument();
    expect(within(ask).getByText("Only you see this. Nothing from your library is on the trip until you share it.")).toBeInTheDocument();
    const scopes = within(ask).getByRole("group", { name: "Who can see them" });
    expect(within(scopes).getByRole("radio", { name: /^Only me/ })).toBeChecked();
    expect(within(scopes).getByRole("radio", { name: /^Everyone on this trip/ })).not.toBeChecked();
    expect(within(ask).getByRole("button", { name: "Share on this trip" })).toBeEnabled();
    expect(within(ask).getByRole("button", { name: "Share on all my trips" })).toBeEnabled();
    expect(within(ask).getByRole("button", { name: "Not now" })).toBeEnabled();
    expect(within(ask).getByText(/also covers trips you join later/)).toBeInTheDocument();
    const strip = await screen.findByTestId("photo-strip");
    expect(ask.compareDocumentPosition(strip) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(vi.mocked(api)).toHaveBeenCalledWith("/api/trips/7/photo-sharing?person_id=1", { keep: true });
  });

  it("says a count that couldn’t be made as such, and shares only to the person alone until it can be counted", async () => {
    current = sharing({ count: null });
    mount();
    const ask = await screen.findByRole("group", { name: "Couldn’t check your libraries" });
    expect(within(ask).queryByText(/\d+ photos?/)).toBeNull();
    await user.click(within(ask).getByRole("radio", { name: /^Everyone on this trip/ }));
    expect(within(ask).getByRole("button", { name: "Share on this trip" })).toBeDisabled();
    expect(within(ask).getByRole("button", { name: "Share on all my trips" })).toBeDisabled();
    await user.click(within(ask).getByRole("radio", { name: /^Only me/ }));
    expect(within(ask).getByRole("button", { name: "Share on this trip" })).toBeEnabled();
  });

  it("shows the reminder after Not now, with the count, and no prompt", async () => {
    current = sharing({ state: "declined" });
    mount();
    const reminder = await screen.findByTestId("photo-reminder");
    expect(reminder).toHaveTextContent("Your 77 photos from this trip aren’t on it. Only you see this.");
    expect(within(reminder).getByRole("button", { name: "Share your photos on this trip" })).toHaveTextContent("Share…");
    expect(screen.queryByRole("group", { name: /from this trip$/ })).toBeNull();
  });

  it("says a reminder’s count couldn’t be made", async () => {
    current = sharing({ state: "declined", count: null });
    mount();
    expect(await screen.findByTestId("photo-reminder")).toHaveTextContent("Couldn’t check your libraries. Your photos from this trip aren’t on it.");
  });

  it("shows Your photos on this trip once shared, with the scope, the count and Stop sharing", async () => {
    current = shared();
    mount();
    const mine = await card();
    expect(within(mine).getByRole("heading", { level: 3, name: "Your photos on this trip" })).toBeInTheDocument();
    expect(within(mine).getByText("169 photos from your library")).toBeInTheDocument();
    expect(within(mine).getByText("Everyone on this trip", { selector: "[data-tone]" })).toHaveAttribute("data-tone", "info");
    const scopes = within(mine).getByRole("group", { name: "Who can see your photos on this trip" });
    expect(within(scopes).getByRole("radio", { name: /^Everyone on this trip/ })).toBeChecked();
    expect(within(mine).getByRole("button", { name: "Stop sharing on this trip" })).toBeEnabled();
    expect(screen.queryByTestId("photo-reminder")).toBeNull();
  });

  it("keeps the card, and Stop sharing, on a shared trip whose photos haven’t been read yet", async () => {
    current = shared({ count: 0 });
    photos = [];
    mount();
    const mine = await card();
    expect(within(mine).getByText("No photos from your library yet")).toBeInTheDocument();
    expect(within(mine).getByRole("button", { name: "Stop sharing on this trip" })).toBeEnabled();
  });

  it("shows Only me as a quiet chip", async () => {
    current = shared({ scope: "only_me" });
    mount();
    expect(await within(await card()).findByText("Only me", { selector: "[data-tone]" })).toHaveAttribute("data-tone", "quiet");
  });

  it.each([
    ["no photos from this person", sharing({ state: "none", count: 0 })],
    ["a declined trip with none left to share", sharing({ state: "declined", count: 0 })],
  ])("renders nothing of its own for %s", async (_name, found) => {
    current = found;
    photos = [];
    mount();
    await screen.findByText("No photos on this trip yet.");
    expect(screen.queryByRole("group", { name: /from this trip$/ })).toBeNull();
    expect(screen.queryByTestId("photo-reminder")).toBeNull();
    expect(screen.queryByTestId("your-photos")).toBeNull();
  });

  it("does not say there are no photos while it asks about the person’s own", async () => {
    photos = [];
    mount();
    await prompt();
    expect(screen.queryByText("No photos on this trip yet.")).toBeNull();
  });

  it("shows nothing at all when photos are off", async () => {
    onSharing = () => { throw new Refusal("Photos aren’t available", 404); };
    photos = [];
    mount();
    await waitFor(() => expect(sharingGets()).toBe(1));
    await Promise.resolve();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("group", { name: /from this trip$/ })).toBeNull();
  });

  it("asks for nothing without a sign-in", async () => {
    app.state = state({ user: { name: null, email: null, local: true } });
    mount();
    await Promise.resolve();
    expect(vi.mocked(api)).not.toHaveBeenCalled();
  });

  it("names a child the member manages, and asks only as them", async () => {
    grantList = [grants(), grants({ person_id: 3 })];
    const seen: string[] = [];
    onSharing = (_call, path) => {
      seen.push(path);
      return path.includes("person_id=3") ? sharing({ count: 12 }) : sharing({ state: "none", count: 0 });
    };
    mount({ people: [ada, june], trip: { ...road, people: [1, 3] } });
    const ask = await screen.findByRole("group", { name: "June has 12 photos from this trip" });
    expect(within(ask).getByText("Only June sees this. Nothing from June’s library is on the trip until June shares it.")).toBeInTheDocument();
    expect(within(ask).getByRole("radio", { name: /^Only June/ })).toBeChecked();
    expect(seen).toContain("/api/trips/7/photo-sharing?person_id=3");
    await user.click(within(ask).getByRole("button", { name: "Share on this trip" }));
    await waitFor(() => expect(sent("POST", "/photo-sharing")).toHaveLength(1));
    expect(sent("POST", "/photo-sharing")[0]).toMatchObject({ person_id: 3, scope: "only_me" });
    expect(toast.success).toHaveBeenCalledWith("Shared with June only. Change it any time under June’s photos on this trip.");
  });

  it("does not look up the managed people for a trip with none of them", async () => {
    mount();
    await prompt();
    expect(calls("GET", "/api/photo-grants")).toHaveLength(0);
  });

  it("says when it couldn’t tell which libraries the member manages, and tries again", async () => {
    let failing = true;
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path === "/api/photo-grants") { if (failing) throw new Refusal("Waypoint is unreachable", 503); return { people: [grants(), grants({ person_id: 3 })] } as never; }
      if (path.includes("person_id=3")) return sharing({ count: 12 }) as never;
      if (path.includes("/photo-sharing")) return sharing({ state: "none", count: 0 }) as never;
      if (path.endsWith("/photos")) return reply(photos) as never;
      return { sources: [source()], permissions: [] } as never;
    });
    mount({ people: [ada, june], trip: { ...road, people: [1, 3] } });
    expect(await screen.findByText(/Couldn’t check which libraries you manage on this trip/)).toBeInTheDocument();
    failing = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("group", { name: "June has 12 photos from this trip" })).toBeInTheDocument();
    expect(screen.queryByText(/Couldn’t check which libraries/)).toBeNull();
  });
});

describe("Share prompt: Share on this trip", () => {
  it("sends the window, audience, sources and count token it was shown, and reloads the photos and tells the page", async () => {
    const changed = vi.fn();
    mount({ onchanged: changed });
    const ask = await prompt();
    const getsBefore = sharingGets();
    onSharing = (call) => (call?.method === "POST" ? shared({ scope: "only_me" }) : undefined);
    current = shared({ scope: "only_me" });
    await user.click(within(ask).getByRole("button", { name: "Share on this trip" }));
    await waitFor(() => expect(sent("POST", "/photo-sharing")).toHaveLength(1));
    expect(sent("POST", "/photo-sharing")[0]).toEqual({ person_id: 1, scope: "only_me", window: WINDOW, audience: [1, 2], sources: [{ id: 7, status: "ok" }], count_token: "a".repeat(32) });
    expect(sharingGets()).toBe(getsBefore + 1);
    expect(toast.success).toHaveBeenCalledWith("Shared with you only. Change it any time under Your photos on this trip.");
    await card();
    expect(screen.queryByRole("group", { name: /from this trip$/ })).toBeNull();
    expect(changed).toHaveBeenCalledTimes(1);
    expect(calls("GET", "/api/trips/7/photos").length).toBeGreaterThanOrEqual(2);
  });

  it("sends the snapshot it showed for Everyone on this trip, not what the server says by then", async () => {
    mount();
    const ask = await prompt();
    current = sharing({ count: 99, count_token: "z".repeat(32), sources: [{ id: 7, status: "ok" }, { id: 8, status: "ok" }], audience: [1, 2, 3] });
    await user.click(within(ask).getByRole("radio", { name: /^Everyone on this trip/ }));
    await user.click(within(ask).getByRole("button", { name: "Share on this trip" }));
    await waitFor(() => expect(sent("POST", "/photo-sharing")).toHaveLength(1));
    expect(sent("POST", "/photo-sharing")[0]).toEqual({ person_id: 1, scope: "trip", window: WINDOW, audience: [1, 2], sources: [{ id: 7, status: "ok" }], count_token: "a".repeat(32) });
    expect(toast.success).toHaveBeenCalledWith("Shared with everyone on this trip. Change it any time under Your photos on this trip.");
  });

  it("sends the version of a trip it asks about again, so a changed one is refused", async () => {
    current = sharing({ changed: 1700000001 });
    mount();
    await user.click(within(await prompt()).getByRole("button", { name: "Share on this trip" }));
    await waitFor(() => expect(sent("POST", "/photo-sharing")).toHaveLength(1));
    expect(sent("POST", "/photo-sharing")[0]).toMatchObject({ expected_changed: 1700000001 });
  });

  it("shows the fresh count and waits for a new confirmation when the server says the count is out of date", async () => {
    mount();
    const ask = await prompt();
    onSharing = (call) => {
      if (call?.method !== "POST") return undefined;
      current = sharing({ count: 80, count_token: "d".repeat(32) });
      throw new Refusal(STALE, 409);
    };
    await user.click(within(ask).getByRole("button", { name: "Share on this trip" }));
    const fresh = await screen.findByRole("group", { name: "You have 80 photos from this trip" });
    expect(within(fresh).getByRole("alert")).toHaveTextContent(STALE);
    expect(sent("POST", "/photo-sharing")).toHaveLength(1);
    expect(toast.success).not.toHaveBeenCalled();
    onSharing = () => undefined;
    await user.click(within(fresh).getByRole("button", { name: "Share on this trip" }));
    await waitFor(() => expect(sent("POST", "/photo-sharing")).toHaveLength(2));
    expect(sent("POST", "/photo-sharing")[1]).toMatchObject({ count_token: "d".repeat(32) });
  });

  it("holds every action while the share and the reloads are under way, so nothing is sent twice or against it", async () => {
    mount();
    const ask = await prompt();
    const post = deferred<PhotoSharing>();
    const reload = deferred<Reply>();
    onSharing = (call) => (call?.method === "POST" ? post.promise : undefined);
    const share = within(ask).getByRole("button", { name: "Share on this trip" });
    await user.click(share);
    await user.click(share);
    expect(sent("POST", "/photo-sharing")).toHaveLength(1);
    expect(share).toBeDisabled();
    expect(within(ask).getByRole("button", { name: "Not now" })).toBeDisabled();
    expect(within(ask).getByRole("button", { name: "Share on all my trips" })).toBeDisabled();
    expect(within(ask).getByRole("group", { name: "Who can see them" })).toBeDisabled();
    onPhotos = () => reload.promise;
    current = shared({ scope: "only_me" });
    post.resolve(current);
    await waitFor(() => expect(calls("GET", "/api/trips/7/photos").length).toBe(2));
    await card();
    expect(within(screen.getByTestId("your-photos")).getByRole("button", { name: "Stop sharing on this trip" })).toBeDisabled();
    reload.resolve(reply(photos));
    await waitFor(() => expect(within(screen.getByTestId("your-photos")).getByRole("button", { name: "Stop sharing on this trip" })).toBeEnabled());
  });

  it("releases the controls when the share fails, and says so", async () => {
    mount();
    const ask = await prompt();
    onSharing = (call) => { if (call?.method === "POST") throw new Refusal("Couldn’t share it (500)", 500); return undefined; };
    await user.click(within(ask).getByRole("button", { name: "Share on this trip" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Couldn’t share it (500)"));
    expect(within(ask).getByRole("button", { name: "Share on this trip" })).toBeEnabled();
    expect(within(ask).getByRole("button", { name: "Not now" })).toBeEnabled();
  });
});

describe("Share prompt: Not now", () => {
  it("records the decision and folds the prompt into the reminder", async () => {
    mount();
    const ask = await prompt();
    onSharing = (call) => { if (call?.method === "POST") { current = sharing({ state: "declined" }); return current; } return undefined; };
    await user.click(within(ask).getByRole("button", { name: "Not now" }));
    expect(await screen.findByTestId("photo-reminder")).toBeInTheDocument();
    expect(sent("POST", "/photo-sharing")).toEqual([{ person_id: 1, declined: true }]);
    expect(screen.queryByRole("group", { name: /from this trip$/ })).toBeNull();
  });

  it("holds Share and Not now apart while one is under way", async () => {
    mount();
    const ask = await prompt();
    const post = deferred<PhotoSharing>();
    onSharing = (call) => (call?.method === "POST" ? post.promise : undefined);
    await user.click(within(ask).getByRole("button", { name: "Not now" }));
    expect(within(ask).getByRole("button", { name: "Share on this trip" })).toBeDisabled();
    await user.click(within(ask).getByRole("button", { name: "Not now" }));
    expect(sent("POST", "/photo-sharing")).toHaveLength(1);
    current = sharing({ state: "declined" });
    post.resolve(current);
    await screen.findByTestId("photo-reminder");
  });

  it("keeps the prompt and says why when the decision couldn’t be saved", async () => {
    mount();
    const ask = await prompt();
    onSharing = (call) => { if (call?.method === "POST") throw new Refusal("Couldn’t save it (500)", 500); return undefined; };
    await user.click(within(ask).getByRole("button", { name: "Not now" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Couldn’t save it (500)"));
    expect(screen.getByRole("group", { name: /from this trip$/ })).toBeInTheDocument();
    expect(within(ask).getByRole("button", { name: "Not now" })).toBeEnabled();
  });

  it("reopens the prompt from the reminder with a fresh count, and Not now then only folds it away", async () => {
    current = sharing({ state: "declined" });
    mount();
    const reminder = await screen.findByTestId("photo-reminder");
    current = sharing({ state: "declined", count: 81, count_token: "e".repeat(32) });
    await user.click(within(reminder).getByRole("button", { name: "Share your photos on this trip" }));
    const ask = await screen.findByRole("group", { name: "You have 81 photos from this trip" });
    expect(screen.queryByTestId("photo-reminder")).toBeNull();
    await user.click(within(ask).getByRole("button", { name: "Not now" }));
    expect(await screen.findByTestId("photo-reminder")).toBeInTheDocument();
    expect(sent("POST", "/photo-sharing")).toHaveLength(0);
  });

  it("shares from the reopened prompt with the count it shows, then the card replaces the reminder", async () => {
    current = sharing({ state: "declined" });
    mount();
    await user.click(within(await screen.findByTestId("photo-reminder")).getByRole("button", { name: "Share your photos on this trip" }));
    const ask = await prompt();
    current = shared({ scope: "only_me" });
    await user.click(within(ask).getByRole("button", { name: "Share on this trip" }));
    await card();
    expect(sent("POST", "/photo-sharing")[0]).toMatchObject({ scope: "only_me", count_token: "a".repeat(32) });
    expect(screen.queryByTestId("photo-reminder")).toBeNull();
  });
});

describe("Share prompt: Share on all my trips", () => {
  it("with Only me turns the standing setting on at once and reloads", async () => {
    mount();
    const ask = await prompt();
    current = shared({ scope: "only_me" });
    await user.click(within(ask).getByRole("button", { name: "Share on all my trips" }));
    await waitFor(() => expect(sent("POST", "/photo-sharing-prefs/1")).toHaveLength(1));
    expect(sent("POST", "/photo-sharing-prefs/1")[0]).toEqual({ default_scope: "only_me", share_all: true });
    expect(toast.success).toHaveBeenCalledWith("Sharing on all trips, with you only. Change it any time in Settings.");
    await card();
  });

  it("with Everyone on this trip asks first with the count of every trip, and sends the snapshot it showed", async () => {
    grantList = [grants({ eligible: [{ trip_id: 7, window: WINDOW, audience: [1, 2] }, { trip_id: 8, window: WINDOW, audience: [1] }], trips: [
      { trip_id: 7, name: "Four Corners loop", start_date: "2026-03-01", end_date: "2026-03-04", state: "none", scope: null, count: 77, removed_count: 0 },
      { trip_id: 8, name: "Coast and hills", start_date: "2026-05-01", end_date: "2026-05-04", state: "declined", scope: null, count: 242, removed_count: 0 },
    ] })];
    mount();
    const ask = await prompt();
    await user.click(within(ask).getByRole("radio", { name: /^Everyone on this trip/ }));
    await user.click(within(ask).getByRole("button", { name: "Share on all my trips" }));
    const dialog = await screen.findByRole("dialog", { name: "Show your 319 photos to everyone on 2 trips?" });
    expect(sent("POST", "/photo-sharing-prefs/1")).toHaveLength(0);
    grantList = [grants({ count_token: "n".repeat(32) })];
    current = shared();
    await user.click(within(dialog).getByRole("button", { name: "Show them" }));
    await waitFor(() => expect(sent("POST", "/photo-sharing-prefs/1")).toHaveLength(1));
    expect(sent("POST", "/photo-sharing-prefs/1")[0]).toEqual({
      default_scope: "trip", share_all: true, sources: [{ id: 7, status: "ok" }], count_token: "g".repeat(32),
      windows: { 7: WINDOW, 8: WINDOW }, audiences: { 7: [1, 2], 8: [1] },
    });
    await card();
  });

  it("asks again with the fresh count, and sends nothing new, when the server says the count moved", async () => {
    const trips = (count: number) => [{ trip_id: 7, name: "Four Corners loop", start_date: "2026-03-01", end_date: "2026-03-04", state: "none" as const, scope: null, count, removed_count: 0 }];
    grantList = [grants({ eligible: [{ trip_id: 7, window: WINDOW, audience: [1, 2] }], trips: trips(77) })];
    mount();
    const ask = await prompt();
    await user.click(within(ask).getByRole("radio", { name: /^Everyone on this trip/ }));
    await user.click(within(ask).getByRole("button", { name: "Share on all my trips" }));
    const first = await screen.findByRole("dialog", { name: "Show your 77 photos to everyone on 1 trip?" });
    grantList = [grants({ count_token: "n".repeat(32), eligible: [{ trip_id: 7, window: WINDOW, audience: [1, 2] }], trips: trips(80) })];
    onSharing = () => undefined;
    const original = vi.mocked(api).getMockImplementation()!;
    let refused = false;
    vi.mocked(api).mockImplementation(async (path: string, opts?: Call) => {
      if (path.includes("/photo-sharing-prefs/") && !refused) { refused = true; throw new Refusal(STALE, 409); }
      return original(path, opts as never);
    });
    await user.click(within(first).getByRole("button", { name: "Show them" }));
    const fresh = await screen.findByRole("dialog", { name: "Show your 80 photos to everyone on 1 trip?" });
    expect(within(fresh).getByRole("alert")).toHaveTextContent(STALE);
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("says when the photos on every trip couldn’t be counted, and cannot be confirmed", async () => {
    grantList = [grants({ eligible: [{ trip_id: 7, window: WINDOW, audience: [1, 2] }], trips: [{ trip_id: 7, name: "Four Corners loop", start_date: null, end_date: null, state: "none", scope: null, count: null, removed_count: 0 }] })];
    mount();
    const ask = await prompt();
    await user.click(within(ask).getByRole("radio", { name: /^Everyone on this trip/ }));
    await user.click(within(ask).getByRole("button", { name: "Share on all my trips" }));
    const dialog = await screen.findByRole("dialog", { name: "Show your photos to everyone on 1 trip?" });
    expect(within(dialog).getByText(/Couldn’t check your libraries/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Show them" })).toBeDisabled();
  });

  it("says so, and releases the controls, when the lookup for every trip fails", async () => {
    mount();
    const ask = await prompt();
    await user.click(within(ask).getByRole("radio", { name: /^Everyone on this trip/ }));
    const original = vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation(async (path: string, opts?: Call) => {
      if (path === "/api/photo-grants") throw new Refusal("Waypoint is unreachable", 503);
      return original(path, opts as never);
    });
    await user.click(within(ask).getByRole("button", { name: "Share on all my trips" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Waypoint is unreachable"));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(within(ask).getByRole("button", { name: "Share on all my trips" })).toBeEnabled();
  });
});

describe("Your photos on this trip", () => {
  it("narrows to Only me at once, without asking, with a toast that offers Undo", async () => {
    current = shared();
    mount();
    const mine = await card();
    onSharing = (call) => { if (call?.method === "POST") { current = shared({ scope: "only_me", changed: 1700000002 }); return current; } return undefined; };
    await user.click(within(mine).getByRole("radio", { name: /^Only me/ }));
    await waitFor(() => expect(sent("POST", "/photo-sharing")).toEqual([{ person_id: 1, scope: "only_me" }]));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(toast).toHaveBeenCalledWith("Now only you see your photos on this trip.", expect.objectContaining({ action: expect.objectContaining({ label: "Undo" }) }));
    await waitFor(() => expect(within(screen.getByTestId("your-photos")).getByText("Only me", { selector: "[data-tone]" })).toBeInTheDocument());
    expect(within(screen.getByTestId("your-photos")).getByRole("radio", { name: /^Only me/ })).toBeChecked();
  });

  it("puts it back on Undo, with the snapshot the narrowing answered with", async () => {
    current = shared();
    mount();
    const mine = await card();
    const narrowed = shared({ scope: "only_me", changed: 1700000002, count_token: "f".repeat(32) });
    onSharing = (call) => { if (call?.method === "POST" && (call.body as Body).scope === "only_me") { current = narrowed; return narrowed; } return undefined; };
    await user.click(within(mine).getByRole("radio", { name: /^Only me/ }));
    await waitFor(() => expect(toast).toHaveBeenCalled());
    const undo = undoOf;
    current = shared();
    undo();
    await waitFor(() => expect(sent("POST", "/photo-sharing")).toHaveLength(2));
    expect(sent("POST", "/photo-sharing")[1]).toEqual({
      person_id: 1, scope: "trip", window: WINDOW, audience: [1, 2], sources: [{ id: 7, status: "ok" }], count_token: "f".repeat(32), expected_changed: 1700000002,
    });
  });

  it("asks again, with the fresh count, when Undo is refused because the trip changed", async () => {
    current = shared();
    mount();
    const mine = await card();
    onSharing = (call) => {
      if (call?.method !== "POST") return undefined;
      if ((call.body as Body).scope === "only_me") { current = shared({ scope: "only_me" }); return current; }
      current = shared({ scope: "only_me", count: 175 });
      throw new Refusal(STALE, 409);
    };
    await user.click(within(mine).getByRole("radio", { name: /^Only me/ }));
    await waitFor(() => expect(toast).toHaveBeenCalled());
    undoOf();
    const dialog = await screen.findByRole("dialog", { name: "Show your 175 photos to everyone on this trip?" });
    expect(within(dialog).getByRole("alert")).toHaveTextContent(STALE);
  });

  it("asks once before widening, with the count it just fetched, and sends that snapshot", async () => {
    current = shared({ scope: "only_me", count: 169 });
    mount();
    const mine = await card();
    await user.click(within(mine).getByRole("radio", { name: /^Everyone on this trip/ }));
    const dialog = await screen.findByRole("dialog", { name: "Show your 169 photos to everyone on this trip?" });
    expect(within(dialog).getByText("Everyone else on Four Corners loop will see your photos there, on the map and in the counts too.")).toBeInTheDocument();
    expect(within(mine).getByRole("radio", { name: /^Everyone on this trip/ })).toBeChecked();
    expect(sent("POST", "/photo-sharing")).toHaveLength(0);
    current = shared({ count: 170, count_token: "q".repeat(32) });
    await user.click(within(dialog).getByRole("button", { name: "Show them" }));
    await waitFor(() => expect(sent("POST", "/photo-sharing")).toHaveLength(1));
    expect(sent("POST", "/photo-sharing")[0]).toMatchObject({ scope: "trip", count_token: "c".repeat(32), expected_changed: 1700000000 });
    expect(toast.success).toHaveBeenCalledWith("Shared with everyone on this trip");
  });

  it("puts the choice back when the widening is cancelled", async () => {
    current = shared({ scope: "only_me" });
    mount();
    const mine = await card();
    await user.click(within(mine).getByRole("radio", { name: /^Everyone on this trip/ }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(within(mine).getByRole("radio", { name: /^Only me/ })).toBeChecked();
    expect(sent("POST", "/photo-sharing")).toHaveLength(0);
  });

  it("asks again with the fresh count when the widening is refused as out of date", async () => {
    current = shared({ scope: "only_me", count: 169 });
    mount();
    const mine = await card();
    await user.click(within(mine).getByRole("radio", { name: /^Everyone on this trip/ }));
    const first = await screen.findByRole("dialog", { name: "Show your 169 photos to everyone on this trip?" });
    onSharing = (call) => {
      if (call?.method !== "POST") return undefined;
      current = shared({ scope: "only_me", count: 190, count_token: "r".repeat(32) });
      throw new Refusal(STALE, 409);
    };
    await user.click(within(first).getByRole("button", { name: "Show them" }));
    const fresh = await screen.findByRole("dialog", { name: "Show your 190 photos to everyone on this trip?" });
    expect(within(fresh).getByRole("alert")).toHaveTextContent(STALE);
    onSharing = () => undefined;
    await user.click(within(fresh).getByRole("button", { name: "Show them" }));
    await waitFor(() => expect(sent("POST", "/photo-sharing")).toHaveLength(2));
    expect(sent("POST", "/photo-sharing")[1]).toMatchObject({ count_token: "r".repeat(32) });
  });

  it("asks before stopping, says it is immediate for everyone, and sends nothing on Keep sharing", async () => {
    current = shared();
    mount();
    const mine = await card();
    await user.click(within(mine).getByRole("button", { name: "Stop sharing on this trip" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Stop sharing your photos on this trip?" }).catch(() => screen.findByRole("dialog", { name: "Stop sharing your photos on this trip?" }));
    expect(within(dialog).getByText("Your 169 photos leave Four Corners loop right away, for everyone: the gallery, the map, the replay and the trip’s counts. Nothing changes in Immich, and you can share them again later.")).toBeInTheDocument();
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Keep sharing" })).toHaveFocus());
    await user.click(within(dialog).getByRole("button", { name: "Keep sharing" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls("DELETE", "/photo-sharing")).toHaveLength(0);
    await waitFor(() => expect(within(mine).getByRole("button", { name: "Stop sharing on this trip" })).toHaveFocus());
  });

  it("stops sharing, reloads the photos and the state, and tells the page", async () => {
    current = shared();
    const changed = vi.fn();
    mount({ onchanged: changed });
    const mine = await card();
    await user.click(within(mine).getByRole("button", { name: "Stop sharing on this trip" }));
    const reload = calls("GET", "/api/trips/7/photos").length;
    onSharing = (call) => { if (call?.method === "DELETE") { current = sharing({ state: "declined" }); return current; } return undefined; };
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Stop sharing" }));
    await waitFor(() => expect(calls("DELETE", "/photo-sharing")).toHaveLength(1));
    expect(vi.mocked(api)).toHaveBeenCalledWith("/api/trips/7/photo-sharing?person_id=1", expect.objectContaining({ method: "DELETE" }));
    await screen.findByTestId("photo-reminder");
    expect(screen.queryByTestId("your-photos")).toBeNull();
    expect(calls("GET", "/api/trips/7/photos").length).toBeGreaterThan(reload);
    expect(changed).toHaveBeenCalledTimes(1);
  });

  it("keeps the dialog open and says so when stopping fails", async () => {
    current = shared();
    mount();
    await user.click(within(await card()).getByRole("button", { name: "Stop sharing on this trip" }));
    onSharing = (call) => { if (call?.method === "DELETE") throw new Refusal("Couldn’t stop sharing (500)", 500); return undefined; };
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Stop sharing" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Couldn’t stop sharing (500)"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Stop sharing" })).toBeEnabled();
  });

  it("names the child in the question and the card", async () => {
    grantList = [grants(), grants({ person_id: 3 })];
    onSharing = (_call, path) => (path.includes("person_id=3") ? shared({ count: 12 }) : sharing({ state: "none", count: 0 }));
    mount({ people: [ada, june], trip: { ...road, people: [1, 3] } });
    const mine = await screen.findByRole("region", { name: "June’s photos on this trip" });
    expect(within(mine).getByText("12 photos from June’s library")).toBeInTheDocument();
    await user.click(within(mine).getByRole("button", { name: "Stop sharing on this trip" }));
    const dialog = await screen.findByRole("dialog", { name: "Stop sharing June’s photos on this trip?" });
    expect(within(dialog).getByText(/^June’s 12 photos leave Four Corners loop right away/)).toBeInTheDocument();
  });
});

describe("A reload that fails after a change", () => {
  it("says the sharing may be out of date, with Try again, and holds the controls until it can show it", async () => {
    mount();
    const ask = await prompt();
    let failing = false;
    onSharing = (call) => {
      if (call?.method === "POST") { failing = true; current = shared({ scope: "only_me" }); return current; }
      if (failing) throw new Refusal("Waypoint is unreachable", 503);
      return undefined;
    };
    await user.click(within(ask).getByRole("button", { name: "Share on this trip" }));
    const alert = await screen.findByText(/Couldn’t refresh your photo sharing for this trip, so what shows may be out of date\./);
    expect(alert).toBeInTheDocument();
    expect(within(ask).getByRole("button", { name: "Share on this trip" })).toBeDisabled();
    expect(within(ask).getByRole("button", { name: "Not now" })).toBeDisabled();
    failing = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await card();
    expect(screen.queryByText(/so what shows may be out of date/)).toBeNull();
  });

  it("says the photos may be out of date, with Try again, when only the photos fail to reload", async () => {
    mount();
    const ask = await prompt();
    let failing = false;
    onPhotos = () => { if (failing) throw new Refusal("Waypoint is unreachable", 503); return undefined; };
    onSharing = (call) => { if (call?.method === "POST") { failing = true; current = shared({ scope: "only_me" }); return current; } return undefined; };
    await user.click(within(ask).getByRole("button", { name: "Share on this trip" }));
    expect(await screen.findByText("Couldn’t refresh the photos on this trip, so what shows may be out of date.")).toBeInTheDocument();
    expect(screen.getByTestId("photo-strip")).toBeInTheDocument();
    failing = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.queryByText(/Couldn’t refresh the photos/)).toBeNull());
  });

  it("goes back to what the first load showed when the first load of the sharing fails, and offers Try again", async () => {
    let failing = true;
    onSharing = () => { if (failing) throw new Refusal("Waypoint is unreachable", 503); return undefined; };
    mount();
    expect(await screen.findByText(/Couldn’t load your photo sharing for this trip\./)).toBeInTheDocument();
    failing = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await prompt();
    expect(screen.queryByText(/Couldn’t load your photo sharing/)).toBeNull();
  });
});

describe("Loads that arrive late", () => {
  it("does not let the sharing of a trip left behind replace the one now shown", async () => {
    const slow = deferred<PhotoSharing>();
    onSharing = (_call, path) => (path.includes("/trips/7/") ? slow.promise : path.includes("/trips/8/") ? sharing({ count: 5 }) : undefined);
    const view = mount();
    await waitFor(() => expect(sharingGets()).toBe(1));
    await view.rerender({ trip: { ...road, id: 8, name: "Coast and hills" }, people: [ada], now: after });
    expect(await screen.findByRole("group", { name: "You have 5 photos from this trip" })).toBeInTheDocument();
    slow.resolve(sharing({ count: 999 }));
    await Promise.resolve();
    await Promise.resolve();
    expect(screen.queryByRole("group", { name: "You have 999 photos from this trip" })).toBeNull();
    expect(screen.getByRole("group", { name: "You have 5 photos from this trip" })).toBeInTheDocument();
  });

  it("does not let a slow load overwrite a newer one", async () => {
    const first = deferred<PhotoSharing>();
    const second = deferred<PhotoSharing>();
    const answers = [first.promise, second.promise];
    vi.mocked(api).mockImplementation(async () => answers.shift() as never);
    const who = new PersonSharing(7, 1, 1, [ada], { changed: async () => undefined });
    const older = who.load();
    const newer = who.load();
    second.resolve(shared({ count: 160 }));
    await newer;
    first.resolve(shared({ count: 1 }));
    await older;
    expect(who.sharing?.count).toBe(160);
    who.dispose();
  });
});
