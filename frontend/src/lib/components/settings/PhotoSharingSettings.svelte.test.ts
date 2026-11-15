// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { Person, PhotoGrantPerson, PhotoGrantTrip, PhotoSharing, PhotoSource } from "$lib/api-types";
import { app } from "$lib/app.svelte";
import { toast } from "svelte-sonner";
import { state } from "../../../test/fixtures";
import { COULDNT_CHECK, photosOf, unsharedOf } from "$lib/photo-sharing";
import PhotoSharingSettings, { NOTHING_YET, tripLine } from "./PhotoSharingSettings.svelte";

const user = userEvent.setup({ pointerEventsCheck: 0 });

class Refusal extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

const STALE = "Your photos or trips changed since they were counted. Review the count before sharing.";
const person = (id: number, display_name: string, first_name: string, member: boolean): Person => ({ id, display_name, first_name, legal_name: null, aliases: [], member, links: [] });
const PEOPLE = [person(1, "Ada Brook", "Ada", true), person(2, "Theo Brook", "Theo", true), person(3, "June Brook", "June", false)];

const trip = (id: number, name: string, extra: Partial<PhotoGrantTrip> = {}): PhotoGrantTrip => ({
  trip_id: id, name, start_date: "2025-09-06", end_date: "2025-09-20", state: "shared", scope: "only_me", count: 12, removed_count: 0, ...extra,
});
const grantsOf = (extra: Partial<PhotoGrantPerson> = {}): PhotoGrantPerson => ({
  person_id: 1, prefs: { default_scope: "only_me", share_all: false }, count_token: "a".repeat(32), sources: [{ id: 7, status: "ok" }], eligible: [], trips: [], ...extra,
});
const eligible = (...ids: number[]): PhotoGrantPerson["eligible"] => ids.map((trip_id) => ({ trip_id, window: { ...WINDOW, end: `2025-09-2${trip_id % 10}T12:00:00+00:00` }, audience: [1, 2] }));

const WINDOW = { start: "2025-09-05T12:00:00+00:00", end: "2025-09-21T12:00:00+00:00" };
const sharing = (extra: Partial<PhotoSharing> = {}): PhotoSharing => ({
  state: "none", scope: null, count: 77, removed_count: 0, removed: [], window: WINDOW, changed: null, audience: [1, 2], sources: [{ id: 7, status: "ok" }], count_token: "b".repeat(32), ...extra,
});
const source = (extra: Partial<PhotoSource> = {}): PhotoSource => ({
  id: 7, person_id: 1, url: "https://immich.brook.example", label: null, status: "ok", mine: true, last_sync: null, last_error: null, photos: null, trips: null, ...extra,
});

type Body = Record<string, unknown>;
type Call = { method?: string; body?: unknown };
type Reply = (path: string, opts?: Call) => unknown;

function serve(people: PhotoGrantPerson[], more: Reply = () => undefined, sources: PhotoSource[] = [source()]) {
  vi.mocked(api).mockImplementation(async (path: string, opts?: Call) => {
    const answered = await more(path, opts);
    if (answered !== undefined) return answered as never;
    if (path === "/api/photo-grants") return { people } as never;
    if (path === "/api/people") return { people: PEOPLE } as never;
    if (path === "/api/photo-sources") return { sources, permissions: [] } as never;
    if (path.includes("/photo-sharing-prefs/")) return { default_scope: "only_me", share_all: false, ...(opts?.body as Body | undefined) } as never;
    if (path.includes("/photo-sharing")) return sharing() as never;
    return {} as never;
  });
}

const sent = (method: string, path: string) => vi.mocked(api).mock.calls.filter(([p, o]) => p === path && (o as Call | undefined)?.method === method).map(([, o]) => (o as Call).body as Body);

const FOUR = [
  trip(10, "Four Corners loop", { scope: "trip", count: 168, removed_count: 3 }),
  trip(11, "Redstone weekend", { start_date: "2025-09-13", end_date: "2025-09-14", count: 12 }),
  trip(12, "Coast and hills", { start_date: "2026-05-02", end_date: "2026-05-07", state: "declined", scope: null, count: 112 }),
  trip(13, "Lake week", { start_date: "2026-06-01", end_date: "2026-06-08", state: "none", scope: null, count: 40 }),
];

beforeEach(() => { vi.mocked(api).mockReset(); vi.mocked(toast).mockReset(); vi.mocked(toast.success).mockReset(); vi.mocked(toast.error).mockReset(); app.state = state({ person_id: 1 }); });
afterEach(() => { app.state = null; });

describe("Settings → Photos → Photo sharing: what it shows", () => {
  it("shows the defaults and the first three trips, then the rest on request", async () => {
    serve([grantsOf({ trips: FOUR })]);
    render(PhotoSharingSettings);
    const scopes = await screen.findByRole("group", { name: "Who sees the photos you share" });
    expect(screen.getByRole("heading", { level: 2, name: "Photo sharing" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Whose sharing" })).toBeNull();

    expect(within(scopes).getByRole("radio", { name: /Only me/ })).toBeChecked();
    expect(within(scopes).getByRole("radio", { name: /Everyone on the trip/ })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Share on all my trips/ })).not.toBeChecked();

    expect(screen.getByRole("heading", { level: 3, name: "Trips with your photos" })).toBeInTheDocument();
    const rows = screen.getAllByTestId("photo-grant");
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByText(/168 photos · 3 removed$/)).toBeInTheDocument();
    expect(within(rows[0]).getByRole("combobox", { name: "Who sees your photos on Four Corners loop" })).toHaveValue("trip");
    expect(within(rows[0]).getByRole("button", { name: "Stop sharing on Four Corners loop" })).toBeInTheDocument();
    expect(within(rows[1]).getByRole("combobox", { name: "Who sees your photos on Redstone weekend" })).toHaveValue("only_me");
    expect(within(rows[2]).getByText("Not shared")).toBeInTheDocument();
    expect(within(rows[2]).getByText(/112 photos · not shared$/)).toBeInTheDocument();
    expect(within(rows[2]).getByRole("button", { name: "Share on Coast and hills" })).toHaveTextContent("Share…");

    await user.click(screen.getByRole("button", { name: "Show 1 more trip with your photos" }));
    expect(screen.getAllByTestId("photo-grant")).toHaveLength(4);
    expect(screen.queryByRole("button", { name: /more trip/ })).toBeNull();
  });

  it("says plainly when there are no trips yet", async () => {
    serve([grantsOf()]);
    render(PhotoSharingSettings);
    expect(await screen.findByText(NOTHING_YET)).toBeInTheDocument();
    expect(screen.queryByTestId("photo-grant")).toBeNull();
  });

  it("shows a count that couldn't be checked as such, never as a number", async () => {
    serve([grantsOf({ trips: [trip(12, "Coast and hills", { state: "declined", scope: null, count: null })] })]);
    render(PhotoSharingSettings);
    const row = within(await screen.findByTestId("photo-grant"));
    expect(row.getByText(/Couldn’t check your libraries/)).toBeInTheDocument();
    expect(row.queryByText(/\d+ photos?/)).toBeNull();
  });

  it("shows nothing when photos are off, and a way to try again when the list failed", async () => {
    vi.mocked(api).mockImplementation(async (path: string) => { if (path === "/api/photo-grants") throw new Refusal("Photos aren’t available", 404); return { people: PEOPLE } as never; });
    const { unmount } = render(PhotoSharingSettings);
    await waitFor(() => expect(api).toHaveBeenCalled());
    expect(screen.queryByRole("heading", { name: "Photo sharing" })).toBeNull();
    unmount();

    let fail = true;
    serve([grantsOf()], (path) => { if (path === "/api/photo-grants" && fail) throw new Refusal("Request failed (500)", 500); });
    render(PhotoSharingSettings);
    expect(await screen.findByText("Request failed (500)")).toBeInTheDocument();
    fail = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(NOTHING_YET)).toBeInTheDocument();
  });

  it("lets a steward switch to the child's sharing, and names her in every label", async () => {
    serve([grantsOf({ trips: [trip(10, "Four Corners loop")] }), grantsOf({ person_id: 3, trips: [trip(14, "Redstone weekend", { count: 9 })] })]);
    render(PhotoSharingSettings);
    const switcher = await screen.findByRole("group", { name: "Whose sharing" });
    expect(within(switcher).getByRole("button", { name: "Ada Brook (you)" })).toHaveAttribute("aria-pressed", "true");
    expect(within(switcher).getByRole("button", { name: "June Brook" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByText(/You manage June’s sharing/)).toBeNull();

    await user.click(within(switcher).getByRole("button", { name: "June Brook" }));
    expect(screen.getByText("You manage June’s sharing because June doesn’t sign in.")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Share on all of June’s trips/ })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Who sees the photos June shares" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Trips with June’s photos" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Only June/ })).toBeChecked();
    expect(screen.getByRole("combobox", { name: "Who sees June’s photos on Redstone weekend" })).toBeInTheDocument();
    expect(screen.queryByText("Four Corners loop")).toBeNull();
  });
});

describe("Settings → Photos → Photo sharing: the defaults", () => {
  it("saves the default choice at once", async () => {
    serve([grantsOf()]);
    render(PhotoSharingSettings);
    await user.click(await screen.findByRole("radio", { name: /Everyone on the trip/ }));
    await waitFor(() => expect(sent("POST", "/api/photo-sharing-prefs/1")).toEqual([{ default_scope: "trip" }]));
    expect(screen.getByRole("radio", { name: /Everyone on the trip/ })).toBeChecked();
    expect(toast.success).toHaveBeenCalledWith("Saved");
  });

  it("turns Share on all my trips on at once while the default is Only me, with no count to confirm", async () => {
    serve([grantsOf({ trips: [trip(12, "Coast and hills", { state: "none", scope: null, count: 5 })] })]);
    render(PhotoSharingSettings);
    await user.click(await screen.findByRole("checkbox", { name: /Share on all my trips/ }));
    await waitFor(() => expect(sent("POST", "/api/photo-sharing-prefs/1")).toEqual([{ share_all: true }]));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("turns it off without asking, and says it grants and revokes nothing", async () => {
    serve([grantsOf({ prefs: { default_scope: "trip", share_all: true }, trips: [trip(10, "Four Corners loop", { scope: "trip" })] })]);
    render(PhotoSharingSettings);
    const box = await screen.findByRole("checkbox", { name: /Share on all my trips/ });
    expect(box).toBeChecked();
    expect(screen.getByText(/Trips already shared stay as they are; change them one by one below\./)).toBeInTheDocument();
    await user.click(box);
    await waitFor(() => expect(sent("POST", "/api/photo-sharing-prefs/1")).toEqual([{ share_all: false }]));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(box).not.toBeChecked();
  });

  it("asks before widening the default while Share on all my trips is on, and leaves it alone on Cancel", async () => {
    serve([grantsOf({ prefs: { default_scope: "only_me", share_all: true } })]);
    render(PhotoSharingSettings);
    await user.click(await screen.findByRole("radio", { name: /Everyone on the trip/ }));
    const dialog = await screen.findByRole("dialog", { name: "Show your photos on trips you join later to everyone on them?" });
    expect(sent("POST", "/api/photo-sharing-prefs/1")).toEqual([]);
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("radio", { name: /Only me/ })).toBeChecked();
    expect(sent("POST", "/api/photo-sharing-prefs/1")).toEqual([]);

    await user.click(screen.getByRole("radio", { name: /Everyone on the trip/ }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sent("POST", "/api/photo-sharing-prefs/1")).toEqual([{ default_scope: "trip" }]));
  });
});

describe("Settings → Photos → Photo sharing: Share on all my trips at the Trip scope", () => {
  const everyone = (extra: Partial<PhotoGrantPerson> = {}) => grantsOf({
    prefs: { default_scope: "trip", share_all: false }, eligible: eligible(12, 13), trips: [trip(12, "Coast and hills", { state: "declined", scope: null, count: 112 }), trip(13, "Lake week", { state: "none", scope: null, count: 40 })], ...extra,
  });

  it("confirms the count it was shown and sends the windows, people, libraries and the count token it was shown with", async () => {
    serve([everyone({ eligible: eligible(12, 13) })]);
    render(PhotoSharingSettings);
    await user.click(await screen.findByRole("checkbox", { name: /Share on all my trips/ }));
    const dialog = await screen.findByRole("dialog", { name: "Show your 152 photos to everyone on 2 trips?" });
    expect(within(dialog).getByText(/This applies to every trip you’re on now and to trips you join later\./)).toBeInTheDocument();
    expect(sent("POST", "/api/photo-sharing-prefs/1")).toEqual([]);
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();

    await user.click(within(dialog).getByRole("button", { name: "Show them" }));
    await waitFor(() => expect(sent("POST", "/api/photo-sharing-prefs/1")).toHaveLength(1));
    expect(sent("POST", "/api/photo-sharing-prefs/1")[0]).toEqual({
      share_all: true,
      windows: { "12": eligible(12)[0].window, "13": eligible(13)[0].window },
      audiences: { "12": [1, 2], "13": [1, 2] },
      sources: [{ id: 7, status: "ok" }],
      count_token: "a".repeat(32),
    });
  });

  it("sends the window and people of an eligible trip that has no photos, which the list leaves out", async () => {
    serve([everyone({ trips: [trip(12, "Coast and hills", { state: "declined", scope: null, count: 112 })], eligible: eligible(12, 15) })]);
    render(PhotoSharingSettings);
    await user.click(await screen.findByRole("checkbox", { name: /Share on all my trips/ }));
    await user.click(within(await screen.findByRole("dialog", { name: "Show your 112 photos to everyone on 2 trips?" })).getByRole("button", { name: "Show them" }));
    await waitFor(() => expect(sent("POST", "/api/photo-sharing-prefs/1")).toHaveLength(1));
    const body = sent("POST", "/api/photo-sharing-prefs/1")[0] as { windows: Record<string, unknown>; audiences: Record<string, unknown> };
    expect(Object.keys(body.windows)).toEqual(["12", "15"]);
    expect(Object.keys(body.audiences)).toEqual(["12", "15"]);
    expect(vi.mocked(api).mock.calls.some(([p]) => String(p).includes("/photo-sharing?"))).toBe(false);
  });

  it("recovers from a stale token: shows the new count and asks again with the new token", async () => {
    let posts = 0;
    let reads = 0;
    vi.mocked(api).mockImplementation(async (path: string, opts?: Call) => {
      if (path === "/api/photo-grants") { reads += 1; return { people: [everyone(reads === 1 ? {} : { count_token: "c".repeat(32), trips: [trip(12, "Coast and hills", { state: "declined", scope: null, count: 130 }), trip(13, "Lake week", { state: "none", scope: null, count: 40 })] })] } as never; }
      if (path === "/api/people") return { people: PEOPLE } as never;
      if (path === "/api/photo-sources") return { sources: [source()], permissions: [] } as never;
      if (path.includes("/photo-sharing?")) return sharing() as never;
      if (path === "/api/photo-sharing-prefs/1" && opts?.method === "POST") {
        posts += 1;
        if (posts === 1) throw new Refusal(STALE, 409);
        return { default_scope: "trip", share_all: true } as never;
      }
      return {} as never;
    });
    render(PhotoSharingSettings);
    await user.click(await screen.findByRole("checkbox", { name: /Share on all my trips/ }));
    await user.click(within(await screen.findByRole("dialog", { name: "Show your 152 photos to everyone on 2 trips?" })).getByRole("button", { name: "Show them" }));

    const fresh = await screen.findByRole("dialog", { name: "Show your 170 photos to everyone on 2 trips?" });
    expect(within(fresh).getByRole("alert")).toHaveTextContent(STALE);
    expect(sent("POST", "/api/photo-sharing-prefs/1")).toHaveLength(1);

    await user.click(within(fresh).getByRole("button", { name: "Show them" }));
    await waitFor(() => expect(sent("POST", "/api/photo-sharing-prefs/1")).toHaveLength(2));
    expect(sent("POST", "/api/photo-sharing-prefs/1")[1]).toMatchObject({ share_all: true, count_token: "c".repeat(32) });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("won't confirm a count it couldn't make, and sends nothing", async () => {
    serve([everyone({ trips: [trip(12, "Coast and hills", { state: "declined", scope: null, count: null }), trip(13, "Lake week", { state: "none", scope: null, count: 40 })] })]);
    render(PhotoSharingSettings);
    await user.click(await screen.findByRole("checkbox", { name: /Share on all my trips/ }));
    const dialog = await screen.findByRole("dialog", { name: "Show your photos to everyone on 2 trips?" });
    expect(within(dialog).getByText(new RegExp(COULDNT_CHECK))).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Show them" })).toBeDisabled();
    expect(sent("POST", "/api/photo-sharing-prefs/1")).toEqual([]);
  });

  it("names the child in the question when a steward turns it on for her", async () => {
    serve([grantsOf(), everyone({ person_id: 3, eligible: eligible(12), trips: [trip(12, "Coast and hills", { state: "none", scope: null, count: 20 })] })]);
    render(PhotoSharingSettings);
    await user.click(within(await screen.findByRole("group", { name: "Whose sharing" })).getByRole("button", { name: "June Brook" }));
    await user.click(screen.getByRole("checkbox", { name: /Share on all of June’s trips/ }));
    const dialog = await screen.findByRole("dialog", { name: "Show June’s 20 photos to everyone on 1 trip?" });
    expect(within(dialog).getByText(/This applies to every trip June is on now and to trips June joins later\./)).toBeInTheDocument();
  });

  it("leaves the switch off when the dialog is cancelled", async () => {
    serve([everyone()]);
    render(PhotoSharingSettings);
    await user.click(await screen.findByRole("checkbox", { name: /Share on all my trips/ }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("checkbox", { name: /Share on all my trips/ })).not.toBeChecked();
    expect(sent("POST", "/api/photo-sharing-prefs/1")).toEqual([]);
  });
});

describe("Settings → Photos → Photo sharing: one trip", () => {
  const shared = () => [trip(10, "Four Corners loop", { scope: "only_me", count: 169 })];

  it("asks once before showing a trip's photos to everyone, with the token it was shown", async () => {
    serve([grantsOf({ trips: shared() })], (path) => {
      if (path.startsWith("/api/trips/10/photo-sharing")) return sharing({ state: "shared", scope: "only_me", count: 169, changed: 1700.5, audience: [1, 2], count_token: "d".repeat(32) });
    });
    render(PhotoSharingSettings);
    await user.selectOptions(await screen.findByRole("combobox", { name: "Who sees your photos on Four Corners loop" }), "trip");
    const dialog = await screen.findByRole("dialog", { name: "Show your 169 photos to everyone on this trip?" });
    expect(sent("POST", "/api/trips/10/photo-sharing")).toEqual([]);
    expect(screen.getByRole("combobox", { name: "Who sees your photos on Four Corners loop" })).toHaveValue("only_me");

    await user.click(within(dialog).getByRole("button", { name: "Show them" }));
    await waitFor(() => expect(sent("POST", "/api/trips/10/photo-sharing")).toHaveLength(1));
    expect(sent("POST", "/api/trips/10/photo-sharing")[0]).toEqual({
      person_id: 1, scope: "trip", window: WINDOW, audience: [1, 2], sources: [{ id: 7, status: "ok" }], count_token: "d".repeat(32), expected_changed: 1700.5,
    });
  });

  it("asks again with the fresh count when the trip changed under the question", async () => {
    let posts = 0;
    let reads = 0;
    serve([grantsOf({ trips: shared() })], (path, opts) => {
      if (path.startsWith("/api/trips/10/photo-sharing") && opts?.method === "POST") { posts += 1; if (posts === 1) throw new Refusal(STALE, 409); return sharing({ state: "shared", scope: "trip" }); }
      if (path.startsWith("/api/trips/10/photo-sharing")) { reads += 1; return sharing({ state: "shared", scope: "only_me", count: reads === 1 ? 169 : 171, changed: 5, count_token: reads === 1 ? "d".repeat(32) : "e".repeat(32) }); }
    });
    render(PhotoSharingSettings);
    await user.selectOptions(await screen.findByRole("combobox", { name: "Who sees your photos on Four Corners loop" }), "trip");
    await user.click(within(await screen.findByRole("dialog", { name: "Show your 169 photos to everyone on this trip?" })).getByRole("button", { name: "Show them" }));
    const fresh = await screen.findByRole("dialog", { name: "Show your 171 photos to everyone on this trip?" });
    expect(within(fresh).getByRole("alert")).toHaveTextContent(STALE);
    await user.click(within(fresh).getByRole("button", { name: "Show them" }));
    await waitFor(() => expect(sent("POST", "/api/trips/10/photo-sharing")).toHaveLength(2));
    expect(sent("POST", "/api/trips/10/photo-sharing")[1]).toMatchObject({ count_token: "e".repeat(32) });
  });

  it("narrows to Only me at once, with an undo that sends what the narrowing answered with, not a fresh read", async () => {
    serve([grantsOf({ trips: [trip(10, "Four Corners loop", { scope: "trip", count: 169 })] })], (path, opts) => {
      if (path.startsWith("/api/trips/10/photo-sharing") && opts?.method === "POST" && (opts.body as Body | undefined)?.scope === "only_me") return sharing({ state: "shared", scope: "only_me", changed: 99, count_token: "f".repeat(32) });
      if (path.startsWith("/api/trips/10/photo-sharing") && !opts?.method) {
        return sharing({ state: "shared", scope: "only_me", changed: 99, count_token: "9".repeat(32), sources: [{ id: 7, status: "ok" }, { id: 8, status: "ok" }], audience: [1, 2, 3], window: { ...WINDOW, end: "2030-01-01T00:00:00+00:00" } });
      }
    });
    render(PhotoSharingSettings);
    await user.selectOptions(await screen.findByRole("combobox", { name: "Who sees your photos on Four Corners loop" }), "only_me");
    await waitFor(() => expect(sent("POST", "/api/trips/10/photo-sharing")).toEqual([{ person_id: 1, scope: "only_me" }]));
    expect(screen.queryByRole("dialog")).toBeNull();
    const [message, options] = vi.mocked(toast).mock.calls[0] as unknown as [string, { action: { label: string; onClick: () => void } }];
    expect(message).toBe("Now only you see your photos on Four Corners loop.");
    expect(options.action.label).toBe("Undo");

    vi.mocked(api).mockClear();
    options.action.onClick();
    await waitFor(() => expect(sent("POST", "/api/trips/10/photo-sharing")).toHaveLength(1));
    expect(sent("POST", "/api/trips/10/photo-sharing")[0]).toEqual({
      person_id: 1, scope: "trip", window: WINDOW, audience: [1, 2], sources: [{ id: 7, status: "ok" }], count_token: "f".repeat(32), expected_changed: 99,
    });
    expect(vi.mocked(api).mock.calls.some(([p, o]) => String(p).startsWith("/api/trips/10/photo-sharing") && !(o as Call | undefined)?.method)).toBe(false);
  });

  it("does not share a library connected between narrowing and Undo: the server refuses and the question comes back with the new count", async () => {
    let reads = 0;
    const LATER = [{ id: 7, status: "ok" }, { id: 8, status: "ok" }];
    serve([grantsOf({ trips: [trip(10, "Four Corners loop", { scope: "trip", count: 169 })] })], (path, opts) => {
      if (!path.startsWith("/api/trips/10/photo-sharing")) return;
      const body = opts?.body as Body | undefined;
      if (opts?.method === "POST" && body?.scope === "only_me") return sharing({ state: "shared", scope: "only_me", changed: 99 });
      if (opts?.method === "POST") {
        if (JSON.stringify(body?.sources) !== JSON.stringify(LATER)) throw new Refusal("Your libraries changed. Review them before sharing.", 409);
        return sharing({ state: "shared", scope: "trip" });
      }
      reads += 1;
      return sharing({ state: "shared", scope: "only_me", count: 190, changed: 99, sources: LATER, count_token: "e".repeat(32) });
    });
    render(PhotoSharingSettings);
    await user.selectOptions(await screen.findByRole("combobox", { name: "Who sees your photos on Four Corners loop" }), "only_me");
    await waitFor(() => expect(toast).toHaveBeenCalled());
    const [, options] = vi.mocked(toast).mock.calls[0] as unknown as [string, { action: { onClick: () => void } }];
    options.action.onClick();
    const dialog = await screen.findByRole("dialog", { name: "Show your 190 photos to everyone on this trip?" });
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Your libraries changed.");
    expect(reads).toBe(1);
    expect(sent("POST", "/api/trips/10/photo-sharing")[1]).toMatchObject({ scope: "trip", sources: [{ id: 7, status: "ok" }] });
    await user.click(within(dialog).getByRole("button", { name: "Show them" }));
    await waitFor(() => expect(sent("POST", "/api/trips/10/photo-sharing")).toHaveLength(3));
    expect(sent("POST", "/api/trips/10/photo-sharing")[2]).toMatchObject({ sources: LATER, count_token: "e".repeat(32), expected_changed: 99 });
  });

  it("asks before stopping, says it is immediate for everyone, and keeps the sharing on Keep sharing", async () => {
    serve([grantsOf({ trips: [trip(10, "Four Corners loop", { scope: "trip", count: 169 })] })]);
    render(PhotoSharingSettings);
    const button = await screen.findByRole("button", { name: "Stop sharing on Four Corners loop" });
    await user.click(button);
    const dialog = await screen.findByRole("dialog", { name: "Stop sharing your photos on this trip?" });
    expect(within(dialog).getByText("Your 169 photos leave Four Corners loop right away, for everyone: the gallery, the map, the replay and the trip’s counts. Nothing changes in Immich, and you can share them again later.")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Keep sharing" })).toHaveFocus();
    await user.click(within(dialog).getByRole("button", { name: "Keep sharing" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(sent("DELETE", "/api/trips/10/photo-sharing?person_id=1")).toEqual([]);

    await user.click(button);
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Stop sharing" }));
    await waitFor(() => expect(vi.mocked(api).mock.calls.some(([p, o]) => p === "/api/trips/10/photo-sharing?person_id=1" && (o as Call).method === "DELETE")).toBe(true));
  });

  it("names the child in the stop question", async () => {
    serve([grantsOf(), grantsOf({ person_id: 3, trips: [trip(14, "Redstone weekend", { scope: "trip", count: 9 })] })]);
    render(PhotoSharingSettings);
    await user.click(within(await screen.findByRole("group", { name: "Whose sharing" })).getByRole("button", { name: "June Brook" }));
    await user.click(screen.getByRole("button", { name: "Stop sharing on Redstone weekend" }));
    const dialog = await screen.findByRole("dialog", { name: "Stop sharing June’s photos on this trip?" });
    expect(within(dialog).getByText(/^June’s 9 photos leave Redstone weekend right away/)).toBeInTheDocument();
  });

  it("opens the prompt for a trip that isn't shared, and shares it with everyone using the count it was shown", async () => {
    serve([grantsOf({ trips: [trip(12, "Coast and hills", { state: "declined", scope: null, count: 112 })] })], (path) => {
      if (path.startsWith("/api/trips/12/photo-sharing") && !(vi.mocked(api).mock.lastCall?.[1] as Call | undefined)?.method) return sharing({ state: "declined", count: 77, changed: 42 });
    });
    render(PhotoSharingSettings);
    await user.click(await screen.findByRole("button", { name: "Share on Coast and hills" }));
    const prompt = await screen.findByRole("group", { name: "You have 77 photos from this trip" });
    expect(within(prompt).getByText("Only you see this. Nothing from your library is on the trip until you share it.")).toBeInTheDocument();
    expect(within(prompt).getByRole("radio", { name: /Only me/ })).toBeChecked();

    await user.click(within(prompt).getByRole("radio", { name: /Everyone on this trip/ }));
    await user.click(within(prompt).getByRole("button", { name: "Share on this trip" }));
    await waitFor(() => expect(sent("POST", "/api/trips/12/photo-sharing")).toHaveLength(1));
    expect(sent("POST", "/api/trips/12/photo-sharing")[0]).toEqual({
      person_id: 1, scope: "trip", window: WINDOW, audience: [1, 2], sources: [{ id: 7, status: "ok" }], count_token: "b".repeat(32), expected_changed: 42,
    });
    expect(toast.success).toHaveBeenCalledWith("Shared with everyone on this trip. Change it any time under Your photos on this trip.");
  });

  it("shares with you only without needing a count, and says who sees them", async () => {
    serve([grantsOf({ trips: [trip(13, "Lake week", { state: "none", scope: null, count: 40 })] })], (path) => {
      if (path.startsWith("/api/trips/13/photo-sharing") && !(vi.mocked(api).mock.lastCall?.[1] as Call | undefined)?.method) return sharing({ count: null });
    });
    render(PhotoSharingSettings);
    await user.click(await screen.findByRole("button", { name: "Share on Lake week" }));
    const prompt = await screen.findByRole("group", { name: COULDNT_CHECK });
    await user.click(within(prompt).getByRole("radio", { name: /Everyone on this trip/ }));
    expect(within(prompt).getByRole("button", { name: "Share on this trip" })).toBeDisabled();
    await user.click(within(prompt).getByRole("radio", { name: /Only me/ }));
    await user.click(within(prompt).getByRole("button", { name: "Share on this trip" }));
    await waitFor(() => expect(sent("POST", "/api/trips/13/photo-sharing")).toHaveLength(1));
    expect(sent("POST", "/api/trips/13/photo-sharing")[0]).toMatchObject({ scope: "only_me" });
    expect(toast.success).toHaveBeenCalledWith("Shared with you only. Change it any time under Your photos on this trip.");
  });

  it("records Not now without sharing anything", async () => {
    serve([grantsOf({ trips: [trip(13, "Lake week", { state: "none", scope: null, count: 40 })] })]);
    render(PhotoSharingSettings);
    await user.click(await screen.findByRole("button", { name: "Share on Lake week" }));
    await user.click(within(await screen.findByRole("group", { name: "You have 77 photos from this trip" })).getByRole("button", { name: "Not now" }));
    await waitFor(() => expect(sent("POST", "/api/trips/13/photo-sharing")).toEqual([{ person_id: 1, declined: true }]));
    await waitFor(() => expect(screen.queryByRole("group", { name: /photos from this trip/ })).toBeNull());
  });
});

describe("Settings → Photos → Photo sharing: libraries that change between the count and the confirmation", () => {
  const LATER = [{ id: 7, status: "ok" }, { id: 8, status: "ok" }];
  const refuseOtherLibraries = (body: unknown) => {
    if (JSON.stringify((body as Body).sources) !== JSON.stringify(LATER)) throw new Refusal("Your libraries changed. Review them before sharing.", 409);
  };

  it("submits the libraries the shown count covered, so a library connected meanwhile makes the server refuse and the question comes back with the new count", async () => {
    let reads = 0;
    serve([grantsOf({ trips: [trip(10, "Four Corners loop", { scope: "only_me", count: 169 })] })], (path, opts) => {
      if (path === "/api/photo-sources") return { sources: [source(), source({ id: 8 })], permissions: [] };
      if (path.startsWith("/api/trips/10/photo-sharing") && opts?.method === "POST") { refuseOtherLibraries(opts.body); return sharing({ state: "shared", scope: "trip" }); }
      if (path.startsWith("/api/trips/10/photo-sharing")) { reads += 1; return reads === 1 ? sharing({ state: "shared", scope: "only_me", count: 169, changed: 5 }) : sharing({ state: "shared", scope: "only_me", count: 190, changed: 5, sources: LATER, count_token: "e".repeat(32) }); }
    });
    render(PhotoSharingSettings);
    await user.selectOptions(await screen.findByRole("combobox", { name: "Who sees your photos on Four Corners loop" }), "trip");
    await user.click(within(await screen.findByRole("dialog", { name: "Show your 169 photos to everyone on this trip?" })).getByRole("button", { name: "Show them" }));
    const again = await screen.findByRole("dialog", { name: "Show your 190 photos to everyone on this trip?" });
    expect(within(again).getByRole("alert")).toHaveTextContent("Your libraries changed.");
    expect(sent("POST", "/api/trips/10/photo-sharing")[0]).toMatchObject({ sources: [{ id: 7, status: "ok" }] });
    await user.click(within(again).getByRole("button", { name: "Show them" }));
    await waitFor(() => expect(sent("POST", "/api/trips/10/photo-sharing")).toHaveLength(2));
    expect(sent("POST", "/api/trips/10/photo-sharing")[1]).toMatchObject({ sources: LATER, count_token: "e".repeat(32) });
  });

  it("does the same for a trip that isn't shared yet", async () => {
    let reads = 0;
    serve([grantsOf({ trips: [trip(13, "Lake week", { state: "none", scope: null, count: 40 })] })], (path, opts) => {
      if (path === "/api/photo-sources") return { sources: [source(), source({ id: 8 })], permissions: [] };
      if (path.startsWith("/api/trips/13/photo-sharing") && opts?.method === "POST") { refuseOtherLibraries(opts.body); return sharing(); }
      if (path.startsWith("/api/trips/13/photo-sharing")) { reads += 1; return reads === 1 ? sharing() : sharing({ count: 90, sources: LATER }); }
    });
    render(PhotoSharingSettings);
    await user.click(await screen.findByRole("button", { name: "Share on Lake week" }));
    const prompt = await screen.findByRole("group", { name: "You have 77 photos from this trip" });
    await user.click(within(prompt).getByRole("radio", { name: /Everyone on this trip/ }));
    await user.click(within(prompt).getByRole("button", { name: "Share on this trip" }));
    expect(await screen.findByRole("group", { name: "You have 90 photos from this trip" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Your libraries changed.");
    expect(sent("POST", "/api/trips/13/photo-sharing")).toHaveLength(1);
    expect(sent("POST", "/api/trips/13/photo-sharing")[0]).toMatchObject({ sources: [{ id: 7, status: "ok" }] });
  });

  it("does the same for Share on all my trips: it sends the libraries listed with the count", async () => {
    let reads = 0;
    vi.mocked(api).mockImplementation(async (path: string, opts?: Call) => {
      if (path === "/api/photo-grants") {
        reads += 1;
        return { people: [grantsOf({ prefs: { default_scope: "trip", share_all: false }, eligible: eligible(12), ...(reads === 1 ? { trips: [trip(12, "Coast and hills", { state: "none", scope: null, count: 10 })] } : { sources: LATER, count_token: "c".repeat(32), trips: [trip(12, "Coast and hills", { state: "none", scope: null, count: 25 })] }) })] } as never;
      }
      if (path === "/api/people") return { people: PEOPLE } as never;
      if (path === "/api/photo-sources") return { sources: [source(), source({ id: 8 })], permissions: [] } as never;
      if (path === "/api/photo-sharing-prefs/1" && opts?.method === "POST") { refuseOtherLibraries(opts.body); return { default_scope: "trip", share_all: true } as never; }
      return {} as never;
    });
    render(PhotoSharingSettings);
    await user.click(await screen.findByRole("checkbox", { name: /Share on all my trips/ }));
    await user.click(within(await screen.findByRole("dialog", { name: "Show your 10 photos to everyone on 1 trip?" })).getByRole("button", { name: "Show them" }));
    const again = await screen.findByRole("dialog", { name: "Show your 25 photos to everyone on 1 trip?" });
    expect(within(again).getByRole("alert")).toHaveTextContent("Your libraries changed.");
    expect(sent("POST", "/api/photo-sharing-prefs/1")[0]).toMatchObject({ sources: [{ id: 7, status: "ok" }] });
    await user.click(within(again).getByRole("button", { name: "Show them" }));
    await waitFor(() => expect(sent("POST", "/api/photo-sharing-prefs/1")).toHaveLength(2));
    expect(sent("POST", "/api/photo-sharing-prefs/1")[1]).toMatchObject({ sources: LATER, count_token: "c".repeat(32) });
  });
});

describe("Settings → Photos → Photo sharing: while a request is under way", () => {
  it("holds Share and Not now until the share and the reload are done", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => { release = resolve; });
    serve([grantsOf({ trips: [trip(13, "Lake week", { state: "none", scope: null, count: 40 })] })], async (path, opts) => {
      if (path === "/api/trips/13/photo-sharing" && opts?.method === "POST") { await gate; return sharing({ state: "shared", scope: "only_me" }); }
    });
    render(PhotoSharingSettings);
    await user.click(await screen.findByRole("button", { name: "Share on Lake week" }));
    const prompt = await screen.findByRole("group", { name: "You have 77 photos from this trip" });
    await user.click(within(prompt).getByRole("button", { name: "Share on this trip" }));
    await waitFor(() => expect(within(prompt).getByRole("button", { name: "Not now" })).toBeDisabled());
    expect(within(prompt).getByRole("button", { name: "Share on this trip" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: /Share on all my trips/ })).toBeDisabled();
    release();
    await waitFor(() => expect(screen.queryByRole("group", { name: /photos from this trip/ })).toBeNull());
    expect(sent("POST", "/api/trips/13/photo-sharing")).toHaveLength(1);
    await waitFor(() => expect(screen.getByRole("checkbox", { name: /Share on all my trips/ })).toBeEnabled());
  });

  it("holds the rest of the list while a stop is under way", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => { release = resolve; });
    serve([grantsOf({ trips: [trip(10, "Four Corners loop", { scope: "trip" }), trip(11, "Redstone weekend")] })], async (path, opts) => {
      if (path.startsWith("/api/trips/10/photo-sharing") && opts?.method === "DELETE") { await gate; return sharing(); }
    });
    render(PhotoSharingSettings);
    await user.click(await screen.findByRole("button", { name: "Stop sharing on Four Corners loop" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Stop sharing" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Stop sharing on Redstone weekend" })).toBeDisabled());
    release();
    await waitFor(() => expect(screen.getByRole("button", { name: "Stop sharing on Redstone weekend" })).toBeEnabled());
  });
});

describe("Settings → Photos → Photo sharing: a reload that fails after a change", () => {
  const TOLD = "Request failed (500)";

  function failReloadAfter(people: PhotoGrantPerson[], more: Reply) {
    let failing = false;
    serve(people, async (path, opts) => {
      if (path === "/api/photo-grants" && failing) throw new Refusal(TOLD, 500);
      const answered = await more(path, opts);
      if (opts?.method === "POST" || opts?.method === "DELETE") failing = true;
      return answered;
    });
    return () => { failing = false; };
  }

  const expectStale = async (recover: () => void) => {
    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("Couldn’t refresh your sharing, so what shows may be out of date.");
    expect(banner).toHaveTextContent(TOLD);
    for (const box of screen.getAllByRole("checkbox")) expect(box).toBeDisabled();
    for (const select of screen.queryAllByRole("combobox")) expect(select).toBeDisabled();
    for (const button of screen.queryAllByRole("button", { name: /^(Stop sharing on|Share on)/ })) expect(button).toBeDisabled();
    recover();
    await user.click(within(banner).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    for (const box of screen.getAllByRole("checkbox")) expect(box).toBeEnabled();
  };

  it("after stopping", async () => {
    const recover = failReloadAfter([grantsOf({ trips: [trip(10, "Four Corners loop", { scope: "trip" })] })], (path, opts) => { if (opts?.method === "DELETE") return sharing(); });
    render(PhotoSharingSettings);
    await user.click(await screen.findByRole("button", { name: "Stop sharing on Four Corners loop" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Stop sharing" }));
    await expectStale(recover);
  });

  it("after sharing a trip", async () => {
    const recover = failReloadAfter([grantsOf({ trips: [trip(13, "Lake week", { state: "none", scope: null, count: 40 })] })], (path, opts) => { if (opts?.method === "POST") return sharing({ state: "shared" }); });
    render(PhotoSharingSettings);
    await user.click(await screen.findByRole("button", { name: "Share on Lake week" }));
    await user.click(within(await screen.findByRole("group", { name: "You have 77 photos from this trip" })).getByRole("button", { name: "Share on this trip" }));
    await expectStale(recover);
  });

  it("after not now", async () => {
    const recover = failReloadAfter([grantsOf({ trips: [trip(13, "Lake week", { state: "none", scope: null, count: 40 })] })], (path, opts) => { if (opts?.method === "POST") return sharing(); });
    render(PhotoSharingSettings);
    await user.click(await screen.findByRole("button", { name: "Share on Lake week" }));
    await user.click(within(await screen.findByRole("group", { name: "You have 77 photos from this trip" })).getByRole("button", { name: "Not now" }));
    await expectStale(recover);
  });

  it("after widening a trip", async () => {
    const recover = failReloadAfter([grantsOf({ trips: [trip(10, "Four Corners loop", { scope: "only_me", count: 169 })] })], (path, opts) => {
      if (path.startsWith("/api/trips/10/photo-sharing") && !opts?.method) return sharing({ state: "shared", scope: "only_me", count: 169, changed: 5 });
      if (opts?.method === "POST") return sharing({ state: "shared", scope: "trip" });
    });
    render(PhotoSharingSettings);
    await user.selectOptions(await screen.findByRole("combobox", { name: "Who sees your photos on Four Corners loop" }), "trip");
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Show them" }));
    await expectStale(recover);
  });

  it("after narrowing a trip", async () => {
    const recover = failReloadAfter([grantsOf({ trips: [trip(10, "Four Corners loop", { scope: "trip", count: 169 })] })], (path, opts) => { if (opts?.method === "POST") return sharing({ state: "shared", scope: "only_me", changed: 9 }); });
    render(PhotoSharingSettings);
    await user.selectOptions(await screen.findByRole("combobox", { name: "Who sees your photos on Four Corners loop" }), "only_me");
    await expectStale(recover);
  });

  it("after turning Share on all my trips on, at either scope", async () => {
    const first = failReloadAfter([grantsOf({ trips: [trip(12, "Coast and hills", { state: "none", scope: null, count: 5 })] })], (path, opts) => { if (opts?.method === "POST") return { default_scope: "only_me", share_all: true }; });
    const { unmount } = render(PhotoSharingSettings);
    await user.click(await screen.findByRole("checkbox", { name: /Share on all my trips/ }));
    await expectStale(first);
    unmount();

    vi.mocked(api).mockReset();
    const second = failReloadAfter([grantsOf({ prefs: { default_scope: "trip", share_all: false }, eligible: eligible(12), trips: [trip(12, "Coast and hills", { state: "none", scope: null, count: 5 })] })], (path, opts) => { if (opts?.method === "POST") return { default_scope: "trip", share_all: true }; });
    render(PhotoSharingSettings);
    await user.click(await screen.findByRole("checkbox", { name: /Share on all my trips/ }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Show them" }));
    await expectStale(second);
  });

  it("keeps showing the saved default, with nothing to reload, after the default or the switch changes", async () => {
    serve([grantsOf({ prefs: { default_scope: "only_me", share_all: true } })]);
    render(PhotoSharingSettings);
    await user.click(await screen.findByRole("checkbox", { name: /Share on all my trips/ }));
    await waitFor(() => expect(sent("POST", "/api/photo-sharing-prefs/1")).toEqual([{ share_all: false }]));
    expect(vi.mocked(api).mock.calls.filter(([p]) => p === "/api/photo-grants")).toHaveLength(1);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("closes the share-all question and says the list is out of date when the refresh after a 409 fails", async () => {
    let reads = 0;
    serve([], (path, opts) => {
      if (path === "/api/photo-grants") { reads += 1; if (reads > 1) throw new Refusal(TOLD, 500); return { people: [grantsOf({ prefs: { default_scope: "trip", share_all: false }, eligible: eligible(12), trips: [trip(12, "Coast and hills", { state: "none", scope: null, count: 10 })] })] }; }
      if (path === "/api/photo-sharing-prefs/1" && opts?.method === "POST") throw new Refusal(STALE, 409);
    });
    render(PhotoSharingSettings);
    await user.click(await screen.findByRole("checkbox", { name: /Share on all my trips/ }));
    await user.click(within(await screen.findByRole("dialog", { name: "Show your 10 photos to everyone on 1 trip?" })).getByRole("button", { name: "Show them" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("Couldn’t refresh your sharing, so what shows may be out of date.");
    expect(banner).toHaveTextContent(TOLD);
    expect(screen.getByRole("checkbox", { name: /Share on all my trips/ })).toBeDisabled();
    expect(sent("POST", "/api/photo-sharing-prefs/1")).toHaveLength(1);
  });

  it("tells the person when the very first load failed, as before", async () => {
    serve([grantsOf()], (path) => { if (path === "/api/photo-grants") throw new Refusal(TOLD, 500); });
    render(PhotoSharingSettings);
    expect(await screen.findByText(TOLD)).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });
});

describe("Settings → Photos → Photo sharing: when the libraries change elsewhere on the page", () => {
  it("loads again when told the libraries changed, and keeps the person being shown", async () => {
    let people = [grantsOf()];
    serve([], (path) => { if (path === "/api/photo-grants") return { people }; });
    const { rerender } = render(PhotoSharingSettings, { refresh: 0 });
    await screen.findByRole("checkbox", { name: /Share on all my trips/ });
    expect(screen.queryByRole("group", { name: "Whose sharing" })).toBeNull();
    people = [grantsOf(), grantsOf({ person_id: 3 })];
    await rerender({ refresh: 1 });
    const switcher = await screen.findByRole("group", { name: "Whose sharing" });
    expect(within(switcher).getByRole("button", { name: "June Brook" })).toBeInTheDocument();
    expect(within(switcher).getByRole("button", { name: "Ada Brook (you)" })).toHaveAttribute("aria-pressed", "true");
  });

  it("shows a later load's answer, never an earlier one that arrived last", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => { release = resolve; });
    let reads = 0;
    serve([], async (path) => {
      if (path !== "/api/photo-grants") return;
      reads += 1;
      if (reads === 1) { await gate; return { people: [grantsOf({ trips: [] })] }; }
      return { people: [grantsOf({ trips: [trip(10, "Four Corners loop")] })] };
    });
    const { rerender } = render(PhotoSharingSettings, { refresh: 0 });
    await waitFor(() => expect(reads).toBe(1));
    await rerender({ refresh: 1 });
    expect(await screen.findByText("Four Corners loop")).toBeInTheDocument();
    release();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.getByText("Four Corners loop")).toBeInTheDocument();
  });
});

describe("Settings → Photos → Photo sharing: helpers", () => {
  it("words a trip's line, leaving the removed count to shared trips", () => {
    expect(tripLine(trip(1, "A", { count: 1 }), "Sep 6")).toBe("Sep 6 · 1 photo");
    expect(tripLine(trip(1, "A", { count: 168, removed_count: 3 }), "Sep 6")).toBe("Sep 6 · 168 photos · 3 removed");
    expect(tripLine(trip(1, "A", { state: "none", count: 4, removed_count: 2 }), "Sep 6")).toBe("Sep 6 · 4 photos · not shared");
    expect(tripLine(trip(1, "A", { state: "declined", count: null }), "Sep 6")).toBe(`Sep 6 · ${COULDNT_CHECK} · not shared`);
  });

  it("totals the unshared trips, or nothing when one of them couldn't be counted", () => {
    const person = grantsOf({ trips: [trip(1, "A", { count: 3 }), trip(2, "B", { state: "none", scope: null, count: 4 }), trip(3, "C", { state: "declined", scope: null, count: 5 })] });
    expect(unsharedOf(person).map((t) => t.trip_id)).toEqual([2, 3]);
    expect(photosOf(unsharedOf(person))).toBe(9);
    expect(photosOf([trip(2, "B", { state: "none", count: null })])).toBeNull();
    expect(photosOf([])).toBe(0);
  });
});
