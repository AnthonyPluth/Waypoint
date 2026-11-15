// @vitest-environment jsdom
import { act as flush, cleanup, render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { Person, PhotoSource, ReviewPhoto } from "$lib/api-types";
import { app } from "$lib/app.svelte";
import { toast } from "svelte-sonner";
import { state } from "../../../test/fixtures";
import PhotosSection, { ALREADY_SAID, KEY_LOST, REFUSED_SAID, UNREACHABLE_SAID, host, outcome, sourceChip } from "./PhotosSection.svelte";

class Refusal extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

const PERMISSIONS = ["asset.read", "asset.view", "user.read", "map.read", "asset.download"];
const IMMICH_REFUSED = "Immich didn’t accept this library’s API key (check it, and the permissions it was given).";
const KEY = "madeUpKeyNumberOne0123456789abcdefghij";

const person = (id: number, display_name: string, member: boolean): Person => ({ id, display_name, first_name: null, legal_name: null, aliases: [], member, links: [] });
const PEOPLE = [person(1, "Ada Brook", true), person(2, "Theo Brook", true), person(3, "June Brook", false), person(4, "Rory Brook", false)];

const source = (extra: Partial<PhotoSource> = {}): PhotoSource => ({
  id: 7, person_id: 1, url: "https://immich.brook.example", label: null, status: "ok", mine: true,
  last_sync: "2026-11-06T11:12:00+00:00", last_error: null, photos: 1904, trips: 12, ...extra,
});
const theirs = source({ id: 8, person_id: 2, mine: false, last_sync: null, last_error: null, photos: null, trips: null });

type Call = { method?: string; body?: unknown };
type Reply = (path: string, opts?: Call) => unknown;

function serve(sources: PhotoSource[], more: Reply = () => undefined) {
  vi.mocked(api).mockImplementation(async (path: string, opts?: Call) => {
    const answered = await more(path, opts);
    if (answered !== undefined) return answered as never;
    if (path === "/api/photo-sources") return { sources, permissions: PERMISSIONS } as never;
    if (path === "/api/people") return { people: PEOPLE } as never;
    if (path === "/api/photos/review") return { photos: [] } as never;
    return {} as never;
  });
}

const calls = (method: string, path: string) => vi.mocked(api).mock.calls.filter(([p, o]) => p === path && (o as Call | undefined)?.method === method);

beforeEach(() => { vi.mocked(api).mockReset(); vi.mocked(toast.success).mockReset(); vi.mocked(toast).mockReset(); app.state = state(); });
afterEach(() => { app.state = null; vi.useRealTimers(); });

describe("Settings → Photos, the source cards", () => {
  it("shows a card for each library, with actions only on the ones you connected", async () => {
    serve([source(), theirs, source({ id: 9, person_id: 3, url: "http://nas.brook.example:2283", photos: 640, trips: 4 })]);
    render(PhotosSection);
    const cards = await screen.findAllByTestId("photo-source");
    expect(cards).toHaveLength(3);

    const own = within(cards[0]);
    expect(own.getByText("Ada Brook")).toBeInTheDocument();
    expect(own.getByText("immich.brook.example")).toBeInTheDocument();
    expect(own.getByText(/· 1,904 photos on 12 trips$/)).toBeInTheDocument();
    expect(own.getByText("Up to date")).toBeInTheDocument();
    for (const name of ["Sync now, Ada Brook’s library", "Change key, Ada Brook’s library", "Pause, Ada Brook’s library", "Remove Ada Brook’s library"]) {
      expect(own.getByRole("button", { name })).toBeInTheDocument();
    }

    const other = within(cards[1]);
    expect(other.getByText("Theo Brook manages this library and what it shares.")).toBeInTheDocument();
    expect(other.getByText("Connected")).toBeInTheDocument();
    expect(other.queryAllByRole("button")).toHaveLength(0);
    expect(other.queryByText(/photos on/)).toBeNull();

    const stewarded = within(cards[2]);
    expect(stewarded.getByText("You manage this library because June Brook doesn’t sign in.")).toBeInTheDocument();
    expect(stewarded.getByText("nas.brook.example:2283")).toBeInTheDocument();
    expect(stewarded.getByRole("button", { name: "Remove June Brook’s library" })).toBeInTheDocument();
  });

  it("names a library no one has synced yet, and one whose key Immich refused, with Change key as its one main action", async () => {
    serve([source({ last_sync: null, photos: 0, trips: 0 }), source({ id: 9, person_id: 3, status: "refused" })]);
    render(PhotosSection);
    const [fresh, refused] = await screen.findAllByTestId("photo-source");
    expect(within(fresh).getByText("Not synced yet.")).toBeInTheDocument();
    expect(within(fresh).getAllByText("Not synced yet")).toHaveLength(1);
    expect(within(refused).getByText("Key refused")).toBeInTheDocument();
    expect(within(refused).getByText(/Immich turned the key down/)).toBeInTheDocument();
    expect(within(refused).queryByRole("button", { name: /Sync now/ })).toBeNull();
    expect(within(refused).getByRole("button", { name: "Change key, June Brook’s library" })).toBeInTheDocument();
  });

  it.each([
    ["Some of your library couldn’t be read."],
    ["Immich says Waypoint has made too many requests; it will try again later."],
  ])("doesn't call a library up to date while its last sync left a warning: %s", async (warning) => {
    serve([source({ last_error: warning })]);
    render(PhotosSection);
    const card = within(await screen.findByTestId("photo-source"));
    expect(card.getByText(warning)).toBeInTheDocument();
    expect(card.getByText("Not up to date")).toHaveAttribute("data-tone", "warn");
    expect(card.queryByText("Up to date")).toBeNull();
    expect(card.getByText(/^Last synced /)).toBeInTheDocument();
  });

  it("blames a key Waypoint can no longer unlock on Waypoint, not on Immich", async () => {
    serve([source({ status: "refused", last_error: KEY_LOST })]);
    render(PhotosSection);
    const card = within(await screen.findByTestId("photo-source"));
    expect(card.getByText("Key lost")).toHaveAttribute("data-tone", "bad");
    expect(card.getByText(/^Waypoint can’t unlock this library’s key any more; enter it again\./)).toBeInTheDocument();
    expect(card.queryByText(/Immich turned the key down/)).toBeNull();
    expect(card.getByRole("button", { name: "Change key, Ada Brook’s library" })).toBeInTheDocument();
  });

  it("shows why a resume was refused when the trips changed meanwhile", async () => {
    serve([source({ status: "off" })], (path, opts) => {
      if (path === "/api/photo-sources/7/resume") return { asks: false, count: 0, grants: [], snapshot: "c".repeat(32) };
      if (path === "/api/photo-sources/7" && opts?.method === "POST") throw new Refusal("Your trips changed meanwhile; try again", 409);
    });
    render(PhotosSection);
    await userEvent.click(await screen.findByRole("button", { name: "Resume, Ada Brook’s library" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Your trips changed meanwhile; try again");
    expect(alert).not.toHaveTextContent(ALREADY_SAID);
  });

  it("stops checking on a sync once the section is gone", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    serve([source()], (path) => { if (path === "/api/photo-sources/7/sync") return { started: true }; });
    const { unmount } = render(PhotosSection);
    await userEvent.click(await screen.findByRole("button", { name: "Sync now, Ada Brook’s library" }));
    expect((await screen.findByText(/^Sync started for/)).closest("[role=status]")).not.toBeNull();
    unmount();
    const before = vi.mocked(api).mock.calls.length;
    await flush(() => vi.advanceTimersByTimeAsync(30000));
    expect(vi.mocked(api).mock.calls.length).toBe(before);
  });

  it("says when no library is connected, and when photos are off without sign-in", async () => {
    serve([]);
    const { unmount } = render(PhotosSection);
    expect(await screen.findByText("No Immich library connected yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect" })).toHaveAttribute("aria-expanded", "false");
    unmount();

    vi.mocked(api).mockRejectedValue(new Refusal("Photos are off without sign-in.", 404));
    render(PhotosSection);
    expect(await screen.findByText("Photos are off without sign-in.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("offers Try again when the list doesn't load", async () => {
    let fail = true;
    serve([source()], (path) => { if (path === "/api/photo-sources" && fail) throw new Refusal("Request failed (500)", 500); });
    render(PhotosSection);
    expect(await screen.findByText("Request failed (500)")).toBeInTheDocument();
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("photo-source")).toBeInTheDocument();
  });

  it("asks before removing a library, gives focus back on Cancel, and removes it on Remove", async () => {
    serve([source()]);
    render(PhotosSection);
    const remove = await screen.findByRole("button", { name: "Remove Ada Brook’s library" });
    await userEvent.click(remove);
    const dialog = await screen.findByRole("dialog", { name: "Remove Ada Brook’s library?" });
    expect(dialog).toHaveTextContent("Its 1,904 photos leave every trip. Nothing changes in Immich.");
    expect(calls("DELETE", "/api/photo-sources/7")).toHaveLength(0);
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(remove).toHaveFocus());
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    await userEvent.keyboard("{Enter}");
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(calls("DELETE", "/api/photo-sources/7")).toHaveLength(1));
    expect(toast.success).toHaveBeenCalledWith("Ada Brook’s library removed");
  });

  it("tells the page after a pause, a resume and a removal, so what depends on the libraries loads again", async () => {
    let status: PhotoSource["status"] = "ok";
    let gone = false;
    serve([], (path, opts) => {
      if (path === "/api/photo-sources" && !opts?.method) return { sources: gone ? [] : [source({ status })], permissions: PERMISSIONS };
      if (path === "/api/photo-sources/7/resume") return { asks: false, count: 0, grants: [], snapshot: "a".repeat(32) };
      if (path === "/api/photo-sources/7" && opts?.method === "POST") { status = (opts.body as { paused: boolean }).paused ? "off" : "ok"; return source({ status }); }
      if (path === "/api/photo-sources/7" && opts?.method === "DELETE") { gone = true; return {}; }
    });
    const onchange = vi.fn();
    render(PhotosSection, { onchange });
    await userEvent.click(await screen.findByRole("button", { name: "Pause, Ada Brook’s library" }));
    await waitFor(() => expect(onchange).toHaveBeenCalledTimes(1));
    await userEvent.click(await screen.findByRole("button", { name: "Resume, Ada Brook’s library" }));
    await waitFor(() => expect(onchange).toHaveBeenCalledTimes(2));
    await userEvent.click(await screen.findByRole("button", { name: "Remove Ada Brook’s library" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(onchange).toHaveBeenCalledTimes(3));
  });

  it("pauses a library, and resumes it with the snapshot when nothing needs confirming", async () => {
    let status: PhotoSource["status"] = "ok";
    serve([], (path, opts) => {
      if (path === "/api/photo-sources") return { sources: [source({ status })], permissions: PERMISSIONS };
      if (path === "/api/photo-sources/7/resume") return { asks: false, count: 0, grants: [], snapshot: "a".repeat(32) };
      if (path === "/api/photo-sources/7" && opts?.method === "POST") { status = (opts.body as { paused: boolean }).paused ? "off" : "ok"; return source({ status }); }
    });
    render(PhotosSection);
    await userEvent.click(await screen.findByRole("button", { name: "Pause, Ada Brook’s library" }));
    expect(calls("POST", "/api/photo-sources/7")[0][1]).toMatchObject({ body: { paused: true } });
    const resume = await screen.findByRole("button", { name: "Resume, Ada Brook’s library" });
    expect(screen.getByText("Paused")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sync now, Ada Brook’s library" })).toBeDisabled();
    await userEvent.click(resume);
    await waitFor(() => expect(calls("POST", "/api/photo-sources/7")).toHaveLength(2));
    expect(calls("POST", "/api/photo-sources/7")[1][1]).toMatchObject({ body: { paused: false, snapshot: "a".repeat(32) } });
    expect(await screen.findByRole("button", { name: "Pause, Ada Brook’s library" })).toBeInTheDocument();
  });

  const GRANTS = { people: [{ person_id: 1, prefs: { default_scope: "trip", share_all: false }, count_token: "t", sources: [], eligible: [], trips: [
    { trip_id: 31, name: "Four Corners loop", start_date: null, end_date: null, state: "shared", scope: "trip", count: 9, removed_count: 0 },
    { trip_id: 32, name: "Coast weekend", start_date: null, end_date: null, state: "shared", scope: "trip", count: 3, removed_count: 0 },
  ] }] };
  const grant = (trip_id: number) => ({ trip_id, changed: 1, window: null });
  const asks = (snapshot: string, count = 12) => ({ asks: true, count, grants: [grant(31), grant(32)], snapshot });

  function resuming(checks: unknown[], onPost: (body: unknown) => unknown = () => ({})) {
    let next = 0;
    serve([source({ status: "off" })], (path, opts) => {
      if (path === "/api/photo-sources/7/resume") return checks[Math.min(next++, checks.length - 1)];
      if (path === "/api/photo-grants") return GRANTS;
      if (path === "/api/photo-sources/7" && opts?.method === "POST") return onPost(opts.body);
    });
  }

  it("asks first when resuming would add photos to trips shared with everyone, and resumes with the snapshot it showed", async () => {
    resuming([asks("b".repeat(32))]);
    render(PhotosSection);
    const resume = await screen.findByRole("button", { name: "Resume, Ada Brook’s library" });
    await userEvent.click(resume);
    const dialog = await screen.findByRole("alertdialog", { name: "Resume Ada Brook’s library?" });
    expect(dialog).toHaveTextContent("Your library is paused, because you share photos with everyone on 2 trips.");
    expect(dialog).toHaveTextContent("Resuming it shows 12 photos from it to everyone on those trips");
    expect(within(dialog).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Four Corners loop", "Coast weekend"]);
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Not now" })).toHaveFocus());
    expect(calls("POST", "/api/photo-sources/7")).toHaveLength(0);
    await userEvent.click(within(dialog).getByRole("button", { name: "Resume" }));
    await waitFor(() => expect(calls("POST", "/api/photo-sources/7")).toHaveLength(1));
    expect(calls("POST", "/api/photo-sources/7")[0][1]).toMatchObject({ body: { paused: false, snapshot: "b".repeat(32) } });
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(toast.success).toHaveBeenCalledWith("Resumed");
  });

  it("leaves the library paused and gives focus back when the person says Not now or presses Escape", async () => {
    resuming([asks("b".repeat(32))]);
    render(PhotosSection);
    const resume = await screen.findByRole("button", { name: "Resume, Ada Brook’s library" });
    for (const close of ["button", "escape"]) {
      await userEvent.click(resume);
      const dialog = await screen.findByRole("alertdialog");
      if (close === "button") await userEvent.click(within(dialog).getByRole("button", { name: "Not now" }));
      else await userEvent.keyboard("{Escape}");
      await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
      await waitFor(() => expect(resume).toHaveFocus());
      await waitFor(() => expect(document.body.style.pointerEvents).not.toBe("none"));
    }
    expect(calls("POST", "/api/photo-sources/7")).toHaveLength(0);
  });

  it("speaks of the person a steward resumes for, and counts a single photo on a single trip", async () => {
    serve([source({ status: "off", person_id: 3 })], (path) => {
      if (path === "/api/photo-sources/7/resume") return { asks: true, count: 1, grants: [grant(41)], snapshot: "d".repeat(32) };
      if (path === "/api/photo-grants") return { people: [] };
    });
    render(PhotosSection);
    await userEvent.click(await screen.findByRole("button", { name: "Resume, June Brook’s library" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Resume June Brook’s library?" });
    expect(dialog).toHaveTextContent("June’s library is paused, because June shares photos with everyone on 1 trip.");
    expect(dialog).toHaveTextContent("Resuming it shows 1 photo from it to everyone on that trip");
    expect(within(dialog).queryByRole("listitem")).toBeNull();
  });

  it("says a resume adds no photos when the count is zero, and still asks", async () => {
    resuming([{ asks: true, count: 0, grants: [grant(31), grant(32)], snapshot: "e".repeat(32) }]);
    render(PhotosSection);
    await userEvent.click(await screen.findByRole("button", { name: "Resume, Ada Brook’s library" }));
    expect(await screen.findByRole("alertdialog")).toHaveTextContent("Resuming it adds no new photos to those trips, but they are shared with everyone, so Waypoint asks first.");
  });

  it("shows a fresh count with a fresh snapshot when the trips changed, and needs a new press before resuming", async () => {
    resuming([asks("b".repeat(32), 12), asks("c".repeat(32), 15)], (body) => {
      if ((body as { snapshot: string }).snapshot === "b".repeat(32)) throw new Refusal("Your trips changed meanwhile; try again", 409);
      return {};
    });
    render(PhotosSection);
    await userEvent.click(await screen.findByRole("button", { name: "Resume, Ada Brook’s library" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Resume" }));
    await waitFor(() => expect(within(dialog).getByRole("alert")).toHaveTextContent("Your trips changed meanwhile, so what’s below is new."));
    expect(dialog).toHaveTextContent("Resuming it shows 15 photos");
    expect(screen.getByRole("alertdialog")).toBe(dialog);
    expect(calls("POST", "/api/photo-sources/7")).toHaveLength(1);
    await userEvent.click(within(dialog).getByRole("button", { name: "Resume" }));
    await waitFor(() => expect(calls("POST", "/api/photo-sources/7")).toHaveLength(2));
    expect(calls("POST", "/api/photo-sources/7")[1][1]).toMatchObject({ body: { paused: false, snapshot: "c".repeat(32) } });
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });

  it("closes the question with a note when the trips changed and nothing needs confirming now", async () => {
    resuming([asks("b".repeat(32)), { asks: false, count: 0, grants: [], snapshot: "f".repeat(32) }], () => { throw new Refusal("Your trips changed meanwhile; try again", 409); });
    render(PhotosSection);
    await userEvent.click(await screen.findByRole("button", { name: "Resume, Ada Brook’s library" }));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Resume" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(await screen.findByRole("alert")).toHaveTextContent("nothing was resumed. Press Resume again.");
    expect(calls("POST", "/api/photo-sources/7")).toHaveLength(1);
  });

  it("says the view may be out of date, with Try again, when the trips changed and cannot be checked again", async () => {
    let fail = false;
    serve([source({ status: "off" })], (path, opts) => {
      if (path === "/api/photo-sources/7/resume") { if (fail) throw new Error("offline"); return asks("b".repeat(32)); }
      if (path === "/api/photo-grants") return GRANTS;
      if (path === "/api/photo-sources/7" && opts?.method === "POST") { fail = true; throw new Refusal("Your trips changed meanwhile; try again", 409); }
    });
    render(PhotosSection);
    await userEvent.click(await screen.findByRole("button", { name: "Resume, Ada Brook’s library" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Resume" }));
    await waitFor(() => expect(within(dialog).getByRole("alert")).toHaveTextContent("may be out of date"));
    expect(within(dialog).queryByRole("button", { name: "Resume" })).toBeNull();
    fail = false;
    await userEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Resume" })).toBeInTheDocument());
    expect(calls("POST", "/api/photo-sources/7")).toHaveLength(1);
  });

  it("keeps the question open and says why when the resume itself fails", async () => {
    resuming([asks("b".repeat(32))], () => { throw new Refusal(KEY_LOST, 400); });
    render(PhotosSection);
    await userEvent.click(await screen.findByRole("button", { name: "Resume, Ada Brook’s library" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Resume" }));
    await waitFor(() => expect(within(dialog).getByRole("alert")).toHaveTextContent(KEY_LOST));
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });

  it("holds the Resume button and says it is checking while the count is fetched", async () => {
    let release: (v: unknown) => void = () => {};
    serve([source({ status: "off" })], (path) => {
      if (path === "/api/photo-sources/7/resume") return new Promise((resolve) => (release = resolve));
    });
    render(PhotosSection);
    const resume = await screen.findByRole("button", { name: "Resume, Ada Brook’s library" });
    await userEvent.click(resume);
    expect((await screen.findByText(/^Checking what resuming Ada Brook’s library would show/)).closest("[role=status]")).not.toBeNull();
    expect(resume).toBeDisabled();
    release({ asks: false, count: 0, grants: [], snapshot: "a".repeat(32) });
    await waitFor(() => expect(resume).toBeEnabled());
  });

  it("asks the same way right after connecting a library that was saved paused, and carries the snapshot", async () => {
    const paused = source({ id: 9, person_id: 3, status: "off", last_sync: null, photos: null, trips: null });
    serve([], (path, opts) => {
      if (path === "/api/photo-sources/test") return { name: "june@brook.example", same_account: null };
      if (path === "/api/photo-sources" && opts?.method === "POST") return paused;
      if (path === "/api/photo-sources") return { sources: calls("POST", "/api/photo-sources").length ? [paused] : [], permissions: PERMISSIONS };
      if (path === "/api/photo-sources/9/resume") return { asks: true, count: 40, grants: [grant(31)], snapshot: "9".repeat(32) };
      if (path === "/api/photo-grants") return { people: [{ ...GRANTS.people[0], person_id: 3 }] };
      if (path === "/api/photo-sources/9" && opts?.method === "POST") return {};
    });
    render(PhotosSection);
    await userEvent.click(await screen.findByRole("button", { name: "Connect" }));
    await userEvent.selectOptions(screen.getByLabelText("Whose library"), "3");
    await userEvent.type(screen.getByLabelText("Immich address"), "https://nas.brook.example");
    await userEvent.type(screen.getByLabelText("API key"), KEY);
    await userEvent.click(screen.getByRole("button", { name: "Test" }));
    await userEvent.click(await screen.findByRole("button", { name: "Save" }));
    const dialog = await screen.findByRole("alertdialog", { name: "June Brook’s library is connected. Resume it now?" });
    expect(dialog).toHaveTextContent("June’s library is connected and paused, until you confirm this, because June shares photos with everyone on 1 trip.");
    expect(dialog).toHaveTextContent("Resuming it shows 40 photos");
    expect(calls("POST", "/api/photo-sources/9")).toHaveLength(0);
    await userEvent.click(within(dialog).getByRole("button", { name: "Resume" }));
    await waitFor(() => expect(calls("POST", "/api/photo-sources/9")).toHaveLength(1));
    expect(calls("POST", "/api/photo-sources/9")[0][1]).toMatchObject({ body: { paused: false, snapshot: "9".repeat(32) } });
  });

  it("turns Sync now off while the sync starts and runs, and on again once the library has synced", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let release: (v: unknown) => void = () => {};
    let synced = "2026-11-06T11:12:00+00:00";
    serve([], (path, opts) => {
      if (path === "/api/photo-sources") return { sources: [source({ last_sync: synced })], permissions: PERMISSIONS };
      if (path === "/api/photo-sources/7/sync" && opts?.method === "POST") return new Promise((resolve) => (release = resolve));
    });
    render(PhotosSection);
    const sync = await screen.findByRole("button", { name: "Sync now, Ada Brook’s library" });
    await userEvent.click(sync);
    await waitFor(() => expect(sync).toBeDisabled());
    expect(sync).toHaveTextContent("Syncing…");
    release({ started: true });
    expect((await screen.findByText("Sync started for Ada Brook’s library. This card updates when it finishes.")).closest("[role=status]")).not.toBeNull();
    expect(screen.getByText("Syncing")).toBeInTheDocument();
    expect(sync).toBeDisabled();
    synced = "2026-11-06T12:12:00+00:00";
    await flush(() => vi.advanceTimersByTimeAsync(5000));
    await waitFor(() => expect(screen.getByRole("button", { name: "Sync now, Ada Brook’s library" })).toBeEnabled());
    expect(screen.queryByText(/^Sync started for/)).toBeNull();
    expect(screen.getByText("Up to date")).toBeInTheDocument();
  });

  it("says so when a sync doesn't start", async () => {
    serve([source()], (path) => { if (path === "/api/photo-sources/7/sync") return { started: false }; });
    render(PhotosSection);
    await userEvent.click(await screen.findByRole("button", { name: "Sync now, Ada Brook’s library" }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith("This library is already syncing, or has nothing to sync."));
  });

  it("changes a key in the card, and shows in the card a key for another Immich account", async () => {
    let refuse = true;
    serve([source({ id: 9, person_id: 3 })], (path, opts) => {
      if (path === "/api/photo-sources/9" && opts?.method === "POST") {
        if (refuse) throw new Refusal("That key belongs to a different Immich account; remove this library and connect it again.", 400);
        return source({ id: 9, person_id: 3 });
      }
    });
    render(PhotosSection);
    await userEvent.click(await screen.findByRole("button", { name: "Change key, June Brook’s library" }));
    const field = screen.getByLabelText("API key");
    expect(field).toHaveFocus();
    expect(field).toHaveAttribute("type", "password");
    await userEvent.type(field, KEY);
    await userEvent.click(screen.getByRole("button", { name: "Save key" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Key refused");
    expect(alert).toHaveTextContent("That key belongs to a different Immich account; remove this library and connect it again.");
    expect(field).toHaveAttribute("aria-invalid", "true");
    refuse = false;
    await userEvent.click(screen.getByRole("button", { name: "Save key" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Key changed"));
    expect(calls("POST", "/api/photo-sources/9").at(-1)?.[1]).toMatchObject({ body: { key: KEY } });
    expect(screen.queryByLabelText("API key")).toBeNull();
    expect(document.body.innerHTML).not.toContain(KEY);
  });
});

describe("Settings → Photos, connecting a library", () => {
  async function openForm(sources: PhotoSource[] = [], more: Reply = () => undefined) {
    serve(sources, more);
    render(PhotosSection);
    const open = await screen.findByRole("button", { name: "Connect" });
    await userEvent.click(open);
    return open;
  }

  async function fill(url = "https://immich.example", key = KEY) {
    await userEvent.type(screen.getByLabelText("Immich address"), url);
    await userEvent.type(screen.getByLabelText("API key"), key);
  }

  it("opens on its first field, offers yourself and people without a sign-in, and lists the key's permissions", async () => {
    const open = await openForm([theirs, source({ id: 10, person_id: 4, mine: false, photos: null, trips: null })]);
    expect(open).toHaveAttribute("aria-expanded", "true");
    const whose = screen.getByLabelText("Whose library");
    expect(whose).toHaveFocus();
    expect(within(whose).getAllByRole("option").map((o) => o.textContent)).toEqual(["Ada Brook (you)", "June Brook"]);
    expect(screen.getByRole("form", { name: "Connect an Immich library" })).toBeInTheDocument();
    for (const p of PERMISSIONS) expect(screen.getByText(p)).toBeInTheDocument();
    expect(screen.getByText(/Photos taken during your trips and the 12 hours around them/)).toBeInTheDocument();
    expect(screen.getByText(/they stay in Immich, and Waypoint fetches each one from Immich when it is shown, without storing it\./)).toBeInTheDocument();
    expect(screen.queryByText(/straight from Immich/)).toBeNull();
    expect(screen.getByLabelText("API key")).toHaveAttribute("type", "password");
    const show = screen.getByRole("button", { name: "Show the key" });
    expect(show).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(show);
    expect(screen.getByLabelText("API key")).toHaveAttribute("type", "text");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Test" })).toBeDisabled();

    await userEvent.selectOptions(whose, "3");
    expect(screen.getByText(/Photos taken during June Brook’s trips/)).toBeInTheDocument();
    expect(screen.getByText(/June Brook doesn’t sign in, so you manage what June Brook’s library shares/)).toBeInTheDocument();
    expect(screen.getByText(/signed in as June Brook, and tick/)).toBeInTheDocument();
    await userEvent.click(open);
    expect(screen.queryByLabelText("Whose library")).toBeNull();
  });

  it("tests the key, turns Save on only for what was tested, and saves without leaving the key on the page", async () => {
    let saved = false;
    serve([], (path, opts) => {
      if (path === "/api/photo-sources/test") return { name: "Demo Person", same_account: null };
      if (path === "/api/photo-sources" && opts?.method === "POST") { saved = true; return source({ id: 11, url: "https://immich.example" }); }
      if (path === "/api/photo-sources" && saved) return { sources: [source({ id: 11, url: "https://immich.example", last_sync: null })], permissions: PERMISSIONS };
    });
    render(PhotosSection);
    await userEvent.click(await screen.findByRole("button", { name: "Connect" }));
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Test" }));
    const works = await screen.findByRole("status");
    expect(works).toHaveTextContent("Key works");
    expect(works).toHaveTextContent("It belongs to the Immich user Demo Person.");
    expect(calls("POST", "/api/photo-sources/test")[0][1]).toMatchObject({ body: { url: "https://immich.example", key: KEY } });
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeEnabled();

    await userEvent.type(screen.getByLabelText("Immich address"), "x");
    expect(save).toBeDisabled();
    expect(screen.queryByText("Key works")).toBeNull();
    await userEvent.type(screen.getByLabelText("Immich address"), "{Backspace}");
    await userEvent.click(screen.getByRole("button", { name: "Test" }));
    await screen.findByText("Key works");

    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls("POST", "/api/photo-sources")).toHaveLength(1));
    expect(calls("POST", "/api/photo-sources")[0][1]).toMatchObject({ body: { person_id: 1, url: "https://immich.example", key: KEY } });
    expect(await screen.findByTestId("photo-source")).toHaveTextContent("immich.example");
    expect(screen.queryByLabelText("API key")).toBeNull();
    expect(document.body.innerHTML).not.toContain(KEY);
    expect(toast.success).toHaveBeenCalledWith("Library connected");
  });

  it("ignores a Test answer for an address or key that has since changed, so Save stays off", async () => {
    let answer: (v: unknown) => void = () => {};
    let refuse: (e: unknown) => void = () => {};
    let calls = 0;
    await openForm([], (path) => {
      if (path !== "/api/photo-sources/test") return undefined;
      calls += 1;
      return new Promise((resolve, reject) => { if (calls === 1) answer = resolve; else refuse = reject; });
    });
    await fill("https://first.immich.example");
    await userEvent.click(screen.getByRole("button", { name: "Test" }));
    await userEvent.clear(screen.getByLabelText("Immich address"));
    await userEvent.type(screen.getByLabelText("Immich address"), "https://second.immich.example");
    answer({ name: "First Account", same_account: null });
    await waitFor(() => expect(screen.getByRole("button", { name: "Test" })).toBeEnabled());
    expect(screen.queryByText("Key works")).toBeNull();
    expect(screen.queryByText(/First Account/)).toBeNull();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Test" }));
    await userEvent.type(screen.getByLabelText("API key"), "x");
    refuse(new Refusal(IMMICH_REFUSED, 400));
    await waitFor(() => expect(screen.getByRole("button", { name: "Test" })).toBeEnabled());
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it.each([
    [new Refusal(IMMICH_REFUSED, 400), "Key refused", REFUSED_SAID],
    [new Refusal("Couldn’t reach Immich.", 502), "Can’t reach Immich", UNREACHABLE_SAID],
  ])("says plainly when Test fails, keeps Save off, and clears the line on an edit", async (error, chip, said) => {
    await openForm([], (path) => { if (path === "/api/photo-sources/test") throw error; });
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Test" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(chip);
    expect(alert).toHaveTextContent(said);
    expect(screen.getByLabelText("API key").getAttribute("aria-describedby")).toContain("photo-result");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("API key"), "z");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows the API's validation message on the field it is about", async () => {
    await openForm([], (path) => {
      if (path === "/api/photo-sources/test") throw new Refusal("The Immich address must be a web address, such as https://immich.local:2283, with no path or sign-in in it", 400);
    });
    await fill("immich");
    await userEvent.click(screen.getByRole("button", { name: "Test" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The Immich address must be a web address");
    expect(screen.getByLabelText("Immich address")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("API key")).not.toHaveAttribute("aria-invalid");
  });

  it("shows a key the API turns down on the key field, and a library already connected under the fields", async () => {
    let reply: Refusal = new Refusal("Enter the API key as Immich shows it", 400);
    await openForm([], (path) => { if (path === "/api/photo-sources/test") throw reply; });
    await fill("https://immich.example", "short");
    await userEvent.click(screen.getByRole("button", { name: "Test" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter the API key as Immich shows it");
    expect(screen.getByLabelText("API key")).toHaveAttribute("aria-invalid", "true");

    reply = new Refusal("That library is already connected for this person.", 409);
    await userEvent.click(screen.getByRole("button", { name: "Test" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(ALREADY_SAID));
  });

  it("keeps the form open with the reason when Save is refused", async () => {
    await openForm([], (path, opts) => {
      if (path === "/api/photo-sources/test") return { name: "Demo Person", same_account: null };
      if (path === "/api/photo-sources" && opts?.method === "POST") throw new Refusal("This person’s library is managed by another member; ask them to connect it.", 403);
    });
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Test" }));
    await userEvent.click(await screen.findByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("managed by another member");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });
});

describe("Settings → Photos helpers", () => {
  it("reads the host from an address, and keeps text that isn't one", () => {
    expect(host("http://nas.brook.example:2283")).toBe("nas.brook.example:2283");
    expect(host("demo")).toBe("demo");
  });

  it("chooses the chip for each state", () => {
    expect(sourceChip(source(), false)).toEqual({ label: "Up to date", tone: "ok" });
    expect(sourceChip(source(), true)).toEqual({ label: "Syncing", tone: "info" });
    expect(sourceChip(source({ status: "off" }), false)).toEqual({ label: "Paused", tone: "quiet" });
    expect(sourceChip(source({ status: "unreachable" }), false)).toEqual({ label: "Can’t reach Immich", tone: "warn" });
    expect(sourceChip(theirs, false)).toEqual({ label: "Connected", tone: "quiet" });
  });

  it("keeps Waypoint's own connection problems apart from Immich's", () => {
    expect(outcome(new Refusal("Can’t reach Waypoint.", 0), "Can’t reach Waypoint.")).toEqual({ text: "Can’t reach Waypoint." });
    expect(outcome(new Error("odd"), "odd")).toEqual({ text: "odd" });
  });
});

const look = (id: number, person_id = 1, extra: Partial<ReviewPhoto> = {}): ReviewPhoto => ({
  id, person_id, trip_id: null, kind: "image", taken_local: "2026-09-13T17:40:00", zone: null, latitude: null, longitude: null, location_source: null, segment_id: null,
  match: "ambiguous", distance_km: null, cluster: null, removed_at: null, candidates: [{ id: 11, name: "Canyon weekend" }, { id: 12, name: "Redstone weekend" }], ...extra,
});

describe("Settings → Photos, Needs a look", () => {
  it("lists a person’s photos in their own card only, once, and asks for nothing when there is no library", async () => {
    serve([source(), theirs, source({ id: 9, person_id: 3 }), source({ id: 10, person_id: 1, url: "https://second.brook.example" })], (path) => {
      if (path === "/api/photos/review") return { photos: [look(21), look(22, 3)] };
    });
    render(PhotosSection);
    const cards = await screen.findAllByTestId("photo-source");
    await waitFor(() => expect(within(cards[0]).getByTestId("needs-a-look")).toBeInTheDocument());
    expect(within(cards[0]).getByText("1 photo")).toBeInTheDocument();
    expect(within(cards[1]).queryByTestId("needs-a-look")).toBeNull();
    expect(within(cards[2]).getByText("Only you see this list, because you manage June’s library.")).toBeInTheDocument();
    expect(within(cards[3]).queryByTestId("needs-a-look")).toBeNull();
    expect(screen.getAllByRole("list", { name: "Photos that need a look" })).toHaveLength(2);
  });

  it("renders nothing and never asks for the list when the viewer has no library of their own", async () => {
    serve([theirs]);
    render(PhotosSection);
    await screen.findByTestId("photo-source");
    expect(screen.queryByTestId("needs-a-look")).toBeNull();
    expect(vi.mocked(api).mock.calls.some(([p]) => p === "/api/photos/review")).toBe(false);
    cleanup();
    serve([]);
    render(PhotosSection);
    await screen.findByText("No Immich library connected yet.");
    expect(screen.queryByTestId("needs-a-look")).toBeNull();
    expect(vi.mocked(api).mock.calls.some(([p]) => p === "/api/photos/review")).toBe(false);
  });

  it("Pick sends the trip, drops the row, and refreshes the list and the card’s counts", async () => {
    let pending = [look(21), look(22)];
    let photos = 1904;
    serve([], (path, opts) => {
      if (path === "/api/photo-sources") return { sources: [source({ photos })], permissions: PERMISSIONS };
      if (path === "/api/photos/review") return { photos: pending };
      if (path === "/api/photos/21" && opts?.method === "POST") { pending = [look(22)]; photos = 1905; return {}; }
    });
    const changed = vi.fn();
    render(PhotosSection, { onchange: changed });
    const user = userEvent.setup();
    await screen.findByText("2 photos");
    await user.click(screen.getAllByRole("button", { name: /^Pick a trip/ })[0]);
    await user.click(await screen.findByRole("button", { name: "Put on Canyon weekend" }));
    await waitFor(() => expect(screen.getByText("1 photo")).toBeInTheDocument());
    expect(calls("POST", "/api/photos/21")[0][1]).toMatchObject({ body: { trip_id: 11 } });
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText(/· 1,905 photos on 12 trips$/)).toBeInTheDocument();
    expect(changed).toHaveBeenCalled();
  });

  it("Leave off removes the row the same way", async () => {
    let pending = [look(21)];
    serve([source()], (path, opts) => {
      if (path === "/api/photos/review") return { photos: pending };
      if (path === "/api/photos/21" && opts?.method === "POST") { pending = []; return {}; }
    });
    render(PhotosSection);
    await userEvent.click(await screen.findByRole("button", { name: /^Leave off, the photo/ }));
    expect(await screen.findByText("Nothing needs a look.")).toBeInTheDocument();
    expect(calls("POST", "/api/photos/21")[0][1]).toMatchObject({ body: { excluded: true } });
  });

  it("Undo on the toast brings the photo back to the list, the card’s counts and Photo sharing", async () => {
    let pending = [look(21)];
    let photos = 1904;
    serve([], (path, opts) => {
      if (path === "/api/photo-sources") return { sources: [source({ photos })], permissions: PERMISSIONS };
      if (path === "/api/photos/review") return { photos: pending };
      if (path === "/api/photos/21" && opts?.method === "POST") { pending = []; photos = 1905; return { removed_at: 1700000000.5 }; }
      if (path === "/api/photos/21/undo" && opts?.method === "POST") { pending = [look(21)]; photos = 1904; return {}; }
    });
    const changed = vi.fn();
    render(PhotosSection, { onchange: changed });
    await screen.findByText("1 photo");
    await userEvent.click(screen.getByRole("button", { name: /^Leave off, the photo/ }));
    expect(await screen.findByText("Nothing needs a look.")).toBeInTheDocument();
    expect(screen.getByText(/· 1,905 photos on 12 trips$/)).toBeInTheDocument();
    const toasted = vi.mocked(toast.success).mock.calls.at(-1);
    expect(toasted?.[0]).toBe("Left off both trips.");
    const before = changed.mock.calls.length;
    (toasted?.[1] as unknown as { action: { onClick: () => void } }).action.onClick();
    expect(await screen.findByText("1 photo")).toBeInTheDocument();
    expect(calls("POST", "/api/photos/21/undo")[0][1]).toMatchObject({ body: { left_off: 1700000000.5 } });
    expect(screen.getByText(/· 1,904 photos on 12 trips$/)).toBeInTheDocument();
    expect(changed.mock.calls.length).toBeGreaterThan(before);
  });

  it("says the list may be out of date when the reload after an Undo fails, and Try again reloads it", async () => {
    let fail = false;
    let pending = [look(21)];
    serve([source()], (path, opts) => {
      if (path === "/api/photos/review") { if (fail) throw new Refusal("Can’t reach Waypoint.", 0); return { photos: pending }; }
      if (path === "/api/photos/21" && opts?.method === "POST") { pending = []; return { removed_at: 1700000000.5 }; }
      if (path === "/api/photos/21/undo" && opts?.method === "POST") { pending = [look(21)]; fail = true; return {}; }
    });
    render(PhotosSection);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /^Leave off, the photo/ }));
    await screen.findByText("Nothing needs a look.");
    (vi.mocked(toast.success).mock.calls.at(-1)?.[1] as unknown as { action: { onClick: () => void } }).action.onClick();
    await screen.findByText("Couldn’t refresh which photos need a look, so that list may be out of date.");
    expect(screen.queryByText("1 photo")).toBeNull();
    fail = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("1 photo")).toBeInTheDocument();
  });

  it("says the list may be out of date when the reload fails after a change, drops the decided row, and Try again reloads", async () => {
    let fail = false;
    serve([source()], (path, opts) => {
      if (path === "/api/photos/review") { if (fail) throw new Refusal("Can’t reach Waypoint.", 0); return { photos: [look(21), look(22)] }; }
      if (path === "/api/photos/21" && opts?.method === "POST") { fail = true; return {}; }
    });
    render(PhotosSection);
    const user = userEvent.setup();
    await screen.findByText("2 photos");
    await user.click(screen.getAllByRole("button", { name: /^Leave off, the photo/ })[0]);
    const alert = await screen.findByText("Couldn’t refresh which photos need a look, so that list may be out of date.");
    expect(alert).toBeInTheDocument();
    expect(screen.getByText("1 photo")).toBeInTheDocument();
    fail = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.queryByText(/may be out of date/)).toBeNull());
    expect(screen.getByText("2 photos")).toBeInTheDocument();
  });

  it("says so when the list can’t be loaded the first time", async () => {
    serve([source()], (path) => { if (path === "/api/photos/review") throw new Refusal("Can’t reach Waypoint.", 0); });
    render(PhotosSection);
    expect(await screen.findByText(/may be out of date/)).toBeInTheDocument();
    expect(screen.queryByTestId("needs-a-look")).toBeNull();
  });

  it("never lets a late reply to an older list replace a newer one", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let synced = "2026-11-06T11:12:00+00:00";
    let calls_ = 0;
    let release: (v: unknown) => void = () => {};
    const pending = [look(21), look(22)];
    serve([], (path, opts) => {
      if (path === "/api/photo-sources") return { sources: [source({ last_sync: synced })], permissions: PERMISSIONS };
      if (path === "/api/photo-sources/7/sync" && opts?.method === "POST") return { started: true };
      if (path === "/api/photos/21" && opts?.method === "POST") return {};
      if (path === "/api/photos/review") {
        calls_ += 1;
        if (calls_ === 1) return { photos: pending };
        if (calls_ === 2) return new Promise((resolve) => (release = resolve));
        return { photos: [] };
      }
    });
    render(PhotosSection);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await screen.findByText("2 photos");
    await user.click(screen.getAllByRole("button", { name: /^Leave off, the photo/ })[0]);
    await waitFor(() => expect(calls_).toBe(2));
    await user.click(screen.getByRole("button", { name: "Sync now, Ada Brook’s library" }));
    synced = "2026-11-06T12:12:00+00:00";
    await flush(() => vi.advanceTimersByTimeAsync(5000));
    expect(await screen.findByText("Nothing needs a look.")).toBeInTheDocument();
    release({ photos: pending });
    await flush(() => vi.advanceTimersByTimeAsync(50));
    expect(screen.getByText("Nothing needs a look.")).toBeInTheDocument();
    expect(screen.queryByText("2 photos")).toBeNull();
  });

  it("after a 409 reloads the list, and the open sheet offers the refreshed candidates, not the obsolete trip", async () => {
    let photos = [look(21)];
    serve([source()], (path, opts) => {
      if (path === "/api/photos/review") return { photos };
      if (path === "/api/photos/21" && opts?.method === "POST") {
        photos = [look(21, 1, { candidates: [{ id: 14, name: "Mesa weekend" }, { id: 12, name: "Redstone weekend" }] })];
        throw new Refusal("The photo’s trips changed", 409);
      }
    });
    render(PhotosSection);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /^Pick a trip/ }));
    await user.click(await screen.findByRole("button", { name: "Put on Canyon weekend" }));
    const sheet = await screen.findByRole("dialog");
    await waitFor(() => expect(within(sheet).getByRole("radio", { name: "Mesa weekend" })).toBeInTheDocument());
    expect(within(sheet).queryByRole("radio", { name: "Canyon weekend" })).toBeNull();
    expect(within(sheet).getByRole("alert")).toHaveTextContent("The list is up to date");
    expect(vi.mocked(api).mock.calls.filter(([p]) => p === "/api/photos/review")).toHaveLength(2);
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("after a 409 whose reload fails, says the list may be out of date and offers Try again", async () => {
    let fail = false;
    serve([source()], (path, opts) => {
      if (path === "/api/photos/review") { if (fail) throw new Refusal("Can’t reach Waypoint.", 0); return { photos: [look(21)] }; }
      if (path === "/api/photos/21" && opts?.method === "POST") { fail = true; throw new Refusal("The photo’s trips changed", 409); }
    });
    render(PhotosSection);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /^Leave off, the photo/ }));
    expect(await screen.findByText("Couldn’t refresh which photos need a look, so that list may be out of date.")).toBeInTheDocument();
    expect(screen.getByText(/Couldn’t refresh the list, so it may be out of date\./)).toBeInTheDocument();
    expect(screen.queryByText(/The list is up to date/)).toBeNull();
    fail = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.queryByText(/may be out of date/)).toBeNull());
  });

  it("ignores a late reload after a 409 when a newer one has answered", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let synced = "2026-11-06T11:12:00+00:00";
    let n = 0;
    let release: (v: unknown) => void = () => {};
    serve([], (path, opts) => {
      if (path === "/api/photo-sources") return { sources: [source({ last_sync: synced })], permissions: PERMISSIONS };
      if (path === "/api/photo-sources/7/sync" && opts?.method === "POST") return { started: true };
      if (path === "/api/photos/21" && opts?.method === "POST") throw new Refusal("The photo’s trips changed", 409);
      if (path === "/api/photos/review") {
        n += 1;
        if (n === 1) return { photos: [look(21)] };
        if (n === 2) return new Promise((resolve) => (release = resolve));
        return { photos: [] };
      }
    });
    render(PhotosSection);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(await screen.findByRole("button", { name: /^Leave off, the photo/ }));
    await waitFor(() => expect(n).toBe(2));
    await user.click(screen.getByRole("button", { name: "Sync now, Ada Brook’s library" }));
    synced = "2026-11-06T12:12:00+00:00";
    await flush(() => vi.advanceTimersByTimeAsync(5000));
    expect(await screen.findByText("Nothing needs a look.")).toBeInTheDocument();
    release({ photos: [look(21)] });
    await flush(() => vi.advanceTimersByTimeAsync(50));
    expect(screen.getByText("Nothing needs a look.")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Photos that need a look" })).toBeNull();
  });
});

describe("Settings → Photos, when sharing changes in Photo sharing", () => {
  const reviews = () => vi.mocked(api).mock.calls.filter(([p]) => p === "/api/photos/review").length;

  it("reloads the list and the card’s counts, so a trip that was just unshared is no longer offered", async () => {
    let photos = [look(21)];
    let count = 1904;
    const changed = vi.fn();
    serve([], (path) => {
      if (path === "/api/photo-sources") return { sources: [source({ photos: count })], permissions: PERMISSIONS };
      if (path === "/api/photos/review") return { photos };
    });
    const { rerender } = render(PhotosSection, { onchange: changed, sharing: 0 });
    const user = userEvent.setup();
    await screen.findByText("1 photo");
    photos = [look(21, 1, { candidates: [{ id: 12, name: "Redstone weekend" }] })];
    count = 1700;
    await rerender({ onchange: changed, sharing: 1 });
    await waitFor(() => expect(screen.getByText(/· 1,700 photos on 12 trips$/)).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("Could belong to Redstone weekend.")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /^Pick a trip/ }));
    const sheet = await screen.findByRole("dialog");
    expect(within(sheet).queryByRole("radio", { name: "Canyon weekend" })).toBeNull();
    expect(within(sheet).getByRole("radio", { name: "Redstone weekend" })).toBeInTheDocument();
    expect(changed).not.toHaveBeenCalled();
  });

  it("offers a trip that was just shared, without a page reload", async () => {
    let photos = [look(21, 1, { candidates: [{ id: 12, name: "Redstone weekend" }] })];
    serve([source()], (path) => { if (path === "/api/photos/review") return { photos }; });
    const { rerender } = render(PhotosSection, { sharing: 0 });
    await screen.findByText("Could belong to Redstone weekend.");
    photos = [look(21)];
    await rerender({ sharing: 1 });
    expect(await screen.findByText("Fits two trips: Canyon weekend and Redstone weekend.")).toBeInTheDocument();
  });

  it("drops a row that no longer needs a look, and says nothing needs a look when it was the last", async () => {
    let photos = [look(21)];
    serve([source()], (path) => { if (path === "/api/photos/review") return { photos }; });
    const { rerender } = render(PhotosSection, { sharing: 0 });
    await screen.findByText("1 photo");
    photos = [];
    await rerender({ sharing: 1 });
    expect(await screen.findByText("Nothing needs a look.")).toBeInTheDocument();
  });

  it("holds the actions on the list while the reload is under way, and gives them back when it has answered", async () => {
    let release: (v: unknown) => void = () => {};
    let n = 0;
    serve([source()], (path) => {
      if (path !== "/api/photos/review") return;
      n += 1;
      if (n === 2) return new Promise((resolve) => (release = resolve));
      return { photos: [look(21)] };
    });
    const { rerender } = render(PhotosSection, { sharing: 0 });
    await screen.findByText("1 photo");
    expect(screen.getByRole("button", { name: /^Leave off, the photo/ })).toBeEnabled();
    await rerender({ sharing: 1 });
    await waitFor(() => expect(n).toBe(2));
    expect(screen.getByRole("button", { name: /^Leave off, the photo/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^Pick a trip/ })).toBeDisabled();
    release({ photos: [look(21)] });
    await waitFor(() => expect(screen.getByRole("button", { name: /^Leave off, the photo/ })).toBeEnabled());
  });

  it("never lets a late reload after one sharing change overwrite the one after the next", async () => {
    let n = 0;
    let release: (v: unknown) => void = () => {};
    serve([source()], (path) => {
      if (path !== "/api/photos/review") return;
      n += 1;
      if (n === 1) return { photos: [look(21), look(22)] };
      if (n === 2) return new Promise((resolve) => (release = resolve));
      return { photos: [look(21)] };
    });
    const { rerender } = render(PhotosSection, { sharing: 0 });
    await screen.findByText("2 photos");
    await rerender({ sharing: 1 });
    await waitFor(() => expect(n).toBe(2));
    await rerender({ sharing: 2 });
    expect(await screen.findByText("1 photo")).toBeInTheDocument();
    release({ photos: [look(21), look(22)] });
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(screen.getByText("1 photo")).toBeInTheDocument();
    expect(screen.queryByText("2 photos")).toBeNull();
    expect(screen.getByRole("button", { name: /^Leave off, the photo/ })).toBeEnabled();
  });

  it("says the list may be out of date when the reload fails, keeps the actions held only while it runs, and Try again reloads", async () => {
    let fail = false;
    let photos = [look(21)];
    serve([source()], (path) => {
      if (path !== "/api/photos/review") return;
      if (fail) throw new Refusal("Can’t reach Waypoint.", 0);
      return { photos };
    });
    const { rerender } = render(PhotosSection, { sharing: 0 });
    const user = userEvent.setup();
    await screen.findByText("1 photo");
    fail = true;
    await rerender({ sharing: 1 });
    expect(await screen.findByText("Couldn’t refresh which photos need a look, so that list may be out of date.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: /^Leave off, the photo/ })).toBeEnabled());
    expect(screen.queryByText(/list is up to date/i)).toBeNull();
    fail = false;
    photos = [];
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Nothing needs a look.")).toBeInTheDocument();
    expect(screen.queryByText(/may be out of date/)).toBeNull();
  });

  it("says the list may be out of date inside an open Pick a trip sheet when the reload fails, and Try again there reloads", async () => {
    let fail = false;
    let photos = [look(21)];
    serve([source()], (path) => {
      if (path !== "/api/photos/review") return;
      if (fail) throw new Refusal("Can’t reach Waypoint.", 0);
      return { photos };
    });
    const { rerender } = render(PhotosSection, { sharing: 0 });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /^Pick a trip/ }));
    const sheet = await screen.findByRole("dialog");
    fail = true;
    await rerender({ sharing: 1 });
    expect(await within(sheet).findByText("Couldn’t refresh the list, so it may be out of date.")).toBeInTheDocument();
    fail = false;
    photos = [look(21, 1, { candidates: [{ id: 12, name: "Redstone weekend" }, { id: 14, name: "Mesa weekend" }] })];
    await user.click(within(sheet).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(within(sheet).getByRole("radio", { name: "Mesa weekend" })).toBeInTheDocument());
    expect(within(sheet).queryByText(/may be out of date/)).toBeNull();
    expect(within(sheet).queryByRole("radio", { name: "Canyon weekend" })).toBeNull();
  });

  it("closes the sheet when the photo no longer needs a look after the reload", async () => {
    let photos = [look(21)];
    serve([source()], (path) => { if (path === "/api/photos/review") return { photos }; });
    const { rerender } = render(PhotosSection, { sharing: 0 });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /^Pick a trip/ }));
    await screen.findByRole("dialog");
    photos = [];
    await rerender({ sharing: 1 });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(await screen.findByText("Nothing needs a look.")).toBeInTheDocument();
  });

  it("tells the page when a sync finishes, so Photo sharing’s counts load again, and does not loop on a sharing change", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let synced = "2026-11-06T11:12:00+00:00";
    const changed = vi.fn();
    serve([], (path, opts) => {
      if (path === "/api/photo-sources") return { sources: [source({ last_sync: synced })], permissions: PERMISSIONS };
      if (path === "/api/photo-sources/7/sync" && opts?.method === "POST") return { started: true };
    });
    const { rerender } = render(PhotosSection, { onchange: changed, sharing: 0 });
    await userEvent.click(await screen.findByRole("button", { name: "Sync now, Ada Brook’s library" }));
    expect(changed).not.toHaveBeenCalled();
    synced = "2026-11-06T12:12:00+00:00";
    await flush(() => vi.advanceTimersByTimeAsync(5000));
    await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
    const before = reviews();
    await rerender({ onchange: changed, sharing: 1 });
    await waitFor(() => expect(reviews()).toBeGreaterThan(before));
    expect(changed).toHaveBeenCalledTimes(1);
  });
});
