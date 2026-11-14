// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { Person, ReviewPhoto } from "$lib/api-types";
import { whoIs } from "$lib/photo-sharing";
import { toast } from "svelte-sonner";
import PhotosNeedsLook, { aboutOf, backText, choicesOf, keptText, leftText, listOf, offWhere, putText, removedText } from "./PhotosNeedsLook.svelte";

class Refusal extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

const person = (id: number, display_name: string, member: boolean): Person => ({ id, display_name, first_name: null, legal_name: null, aliases: [], member, links: [] });
const PEOPLE = [person(1, "Ada Brook", true), person(3, "June Brook", false)];

const CANYON = { id: 11, name: "Canyon weekend" };
const REDSTONE = { id: 12, name: "Redstone weekend" };
const LOOP = { id: 13, name: "Four Corners loop" };

const photo = (id: number, extra: Partial<ReviewPhoto> = {}): ReviewPhoto => ({
  id, person_id: 1, trip_id: null, kind: "image", taken_local: "2025-09-13T17:40:00", zone: null, latitude: 38.1, longitude: -109.2, location_source: "exif",
  segment_id: null, match: "ambiguous", distance_km: null, cluster: null, removed_at: null, candidates: [CANYON, REDSTONE], ...extra,
});
const ambiguous = photo(21);
const far = (id = 22, extra: Partial<ReviewPhoto> = {}) => photo(id, { match: "far", trip_id: LOOP.id, distance_km: 612, taken_local: "2025-09-10T07:55:00", candidates: [LOOP, CANYON], ...extra });

const ADA = whoIs(1, 1, PEOPLE);
const JUNE = whoIs(3, 1, PEOPLE);

type Call = { method?: string; body?: unknown };
const posted = (path: string) => vi.mocked(api).mock.calls.filter(([p, o]) => p === path && (o as Call | undefined)?.method === "POST");

function show(photos: ReviewPhoto[], who = ADA, ondecided: (id: number) => Promise<unknown> = async () => {}, onreload: () => Promise<boolean> = async () => true) {
  const spy = vi.fn(ondecided);
  const reload = vi.fn(onreload);
  const view = render(PhotosNeedsLook, { photos, who, ondecided: spy, onreload: reload });
  return { spy, reload, ...view };
}

const STAMP = 1700000000.123456;

function replyTo(path: string, o?: unknown): unknown {
  const { method, body } = (o ?? {}) as Call;
  if (method === "POST" && /^\/api\/photos\/\d+$/.test(path)) return { removed_at: (body as { excluded?: boolean }).excluded ? STAMP : null };
  if (method === "POST" && /photo-exclusions$/.test(path)) return { removed: (body as { photo_ids: number[] }).photo_ids.map((id) => ({ id, removed_at: STAMP })) };
  return {};
}

const undoOf = (n = -1): (() => void) => {
  const call = vi.mocked(toast.success).mock.calls.at(n);
  const action = (call?.[1] as { action?: { label: string; onClick: () => void } } | undefined)?.action;
  expect(action?.label).toBe("Undo");
  return action!.onClick;
};

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation((async (path: string, o?: unknown) => replyTo(path, o)) as never);
  vi.mocked(toast.success).mockReset();
  vi.mocked(toast).mockReset();
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([{}] as unknown as DOMRectList);
});
afterEach(() => vi.restoreAllMocks());

describe("Needs a look, the list", () => {
  it("says what each photo is, with the actions its kind gets, and counts them in the heading", () => {
    show([ambiguous, far()]);
    const list = screen.getByRole("list", { name: "Photos that need a look" });
    expect(screen.getByText("Needs a look")).toBeInTheDocument();
    expect(screen.getByText("2 photos")).toBeInTheDocument();
    const [one, two] = within(list).getAllByRole("listitem");
    expect(within(one).getByText("Fits two trips: Canyon weekend and Redstone weekend.")).toBeInTheDocument();
    expect(within(one).getByRole("button", { name: /^Pick a trip for the photo from Sat, Sep 13, 2025, 5:40 PM$/ })).toBeInTheDocument();
    expect(within(one).getByRole("button", { name: /^Leave off, the photo from Sat, Sep 13, 2025, 5:40 PM$/ })).toHaveTextContent("Leave off");
    expect(within(one).queryByText("Keep on this trip")).toBeNull();
    expect(within(one).queryByText("Far")).toBeNull();
    expect(within(two).getByText("On Four Corners loop, but taken 612 km from every booking.")).toBeInTheDocument();
    expect(within(two).getByText("Far")).toBeInTheDocument();
    expect(within(two).getByRole("button", { name: /^Keep on this trip, the photo from / })).toHaveTextContent("Keep on this trip");
    expect(within(two).getByRole("button", { name: /^Pick a trip for the photo/ })).toBeInTheDocument();
    expect(within(two).getByRole("button", { name: /^Remove from this trip, the photo from / })).toHaveTextContent("Remove from this trip");
    expect(within(two).queryByText("Leave off")).toBeNull();
  });

  it("offers a far photo no Pick a trip when no other trip holds it, and never lists a trip the API did not", () => {
    show([far(22, { candidates: [LOOP] }), photo(23, { candidates: [] })]);
    expect(screen.queryByRole("button", { name: /^Pick a trip/ })).toBeNull();
    expect(choicesOf(far())).toEqual([CANYON]);
  });

  it("words the copy for one, two, three or no candidates", () => {
    expect(aboutOf(photo(1, { candidates: [CANYON] }))).toBe("Could belong to Canyon weekend.");
    expect(aboutOf(photo(1, { candidates: [CANYON, REDSTONE, LOOP] }))).toBe("Fits 3 trips: Canyon weekend, Redstone weekend and Four Corners loop.");
    expect(aboutOf(photo(1, { candidates: [] }))).toBe("Fits more than one trip.");
    expect(listOf([])).toBe("");
    expect([offWhere(1), offWhere(2), offWhere(3)]).toEqual(["that trip", "both trips", "all those trips"]);
  });

  it("shows three, then the rest on request", async () => {
    show([21, 24, 25, 26, 27].map((id) => photo(id)));
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Show 2 more" }));
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
    await user.click(screen.getByRole("button", { name: "Show fewer" }));
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });

  it("has an empty state", () => {
    show([]);
    expect(screen.getByText("Nothing needs a look.")).toBeInTheDocument();
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("names whose list it is when someone else’s library is managed for them", () => {
    show([ambiguous], JUNE);
    expect(screen.getByText("Only you see this list, because you manage June’s library.")).toBeInTheDocument();
  });

  it("says the list is the person’s own for their own library", () => {
    show([ambiguous]);
    expect(screen.getByText("Only you see this list.")).toBeInTheDocument();
  });

  it("falls back to a mark when a thumbnail can’t be loaded", async () => {
    const { container } = show([ambiguous]);
    container.querySelector("img")?.dispatchEvent(new Event("error"));
    expect(await screen.findByRole("img", { name: "Photo, can’t be loaded right now" })).toBeInTheDocument();
  });
});

describe("Needs a look, deciding", () => {
  it("Pick a trip opens the sheet with only the listed trips, and Put on sends the chosen trip id", async () => {
    const { spy } = show([ambiguous], JUNE);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Pick a trip/ }));
    const sheet = await screen.findByRole("dialog", { name: "Pick a trip for this photo" });
    expect(sheet).toHaveAccessibleDescription("Waypoint won’t move it again by itself.");
    expect(within(sheet).getAllByRole("radio")).toHaveLength(2);
    expect(within(sheet).getByText("June’s library")).toBeInTheDocument();
    expect(within(sheet).getByText(/Only trips June has shared photos on are listed. To use another trip, share June’s photos on it first\./)).toBeInTheDocument();
    await user.click(within(sheet).getByRole("radio", { name: "Redstone weekend" }));
    await user.click(within(sheet).getByRole("button", { name: "Put on Redstone weekend" }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith(21));
    expect(posted("/api/photos/21")).toHaveLength(1);
    expect(posted("/api/photos/21")[0][1]).toMatchObject({ method: "POST", body: { trip_id: 12 } });
    expect(toast.success).toHaveBeenCalledWith("Put June’s photo on Redstone weekend.", expect.objectContaining({ action: expect.objectContaining({ label: "Undo" }) }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("Cancel closes the sheet without sending anything", async () => {
    show([ambiguous]);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Pick a trip/ }));
    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(posted("/api/photos/21")).toHaveLength(0);
  });

  it("Leave off sends excluded for an ambiguous photo", async () => {
    const { spy } = show([ambiguous]);
    await userEvent.setup().click(screen.getByRole("button", { name: /^Leave off, the photo/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith(21));
    expect(posted("/api/photos/21")[0][1]).toMatchObject({ body: { excluded: true } });
    expect(toast.success).toHaveBeenCalledWith("Left off both trips.", expect.objectContaining({ action: expect.objectContaining({ label: "Undo" }) }));
  });

  it("Keep on this trip sends the trip the photo is shown on", async () => {
    const { spy } = show([far()]);
    await userEvent.setup().click(screen.getByRole("button", { name: /^Keep on this trip, the photo/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith(22));
    expect(posted("/api/photos/22")[0][1]).toMatchObject({ body: { trip_id: 13 } });
    expect(toast.success).toHaveBeenCalledWith("Kept on Four Corners loop.", expect.objectContaining({ action: expect.objectContaining({ label: "Undo" }) }));
  });

  it("Remove from this trip removes it from the trip the photo is shown on, for that photo only", async () => {
    const { spy } = show([far()]);
    await userEvent.setup().click(screen.getByRole("button", { name: /^Remove from this trip, the photo/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith(22));
    expect(posted("/api/trips/13/photo-exclusions")[0][1]).toMatchObject({ body: { photo_ids: [22] } });
    expect(posted("/api/photos/22")).toHaveLength(0);
    expect(toast.success).toHaveBeenCalledWith("Removed from Four Corners loop.", expect.objectContaining({ action: expect.objectContaining({ label: "Undo" }) }));
  });

  it("holds every action disabled through the request and the reload, then frees them", async () => {
    let done: () => void = () => {};
    const { spy } = show([ambiguous, far()], ADA, () => new Promise<void>((resolve) => { done = resolve; }));
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Leave off, the photo/ }));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    const buttons = screen.getAllByRole("button").filter((b) => /^(Pick|Leave|Keep|Remove)/.test(b.getAttribute("aria-label") ?? ""));
    expect(buttons.length).toBe(5);
    for (const b of buttons) expect(b).toBeDisabled();
    expect(screen.getByText("Saving…")).toBeInTheDocument();
    done();
    await waitFor(() => { for (const b of buttons) expect(b).toBeEnabled(); });
  });

  it("frees the actions again when the request fails, and says so on that photo", async () => {
    vi.mocked(api).mockRejectedValue(new Refusal("Photos need sign-in", 404));
    const { spy } = show([ambiguous]);
    await userEvent.setup().click(screen.getByRole("button", { name: /^Leave off, the photo/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Photos need sign-in");
    expect(spy).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /^Leave off, the photo/ })).toBeEnabled();
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("on a 409 reloads the list before saying it is up to date, keeps the row, and offers the new candidates in the open sheet", async () => {
    vi.mocked(api).mockRejectedValue(new Refusal("The photo’s trips changed", 409));
    const NEW = { id: 14, name: "Mesa weekend" };
    const fresh = photo(21, { candidates: [NEW, REDSTONE] });
    const view: { rerender?: (p: { photos: ReviewPhoto[] }) => Promise<void> } = {};
    const made = show([ambiguous], ADA, async () => {}, async () => { await view.rerender?.({ photos: [fresh] }); return true; });
    view.rerender = made.rerender as never;
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Pick a trip/ }));
    expect(within(await screen.findByRole("dialog")).getAllByRole("radio")).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "Put on Canyon weekend" }));
    const sheet = await screen.findByRole("dialog");
    await waitFor(() => expect(within(sheet).getByRole("radio", { name: "Mesa weekend" })).toBeInTheDocument());
    expect(within(sheet).queryByRole("radio", { name: "Canyon weekend" })).toBeNull();
    expect(within(sheet).getByRole("alert")).toHaveTextContent("The photo’s trips changed. That photo changed while you were looking. The list is up to date; check it and try again.");
    for (const radio of within(sheet).getAllByRole("radio")) expect(radio).not.toBeChecked();
    expect(within(sheet).getByRole("button", { name: "Put on" })).toBeDisabled();
    await user.click(within(sheet).getByRole("radio", { name: "Mesa weekend" }));
    expect(within(sheet).getByRole("button", { name: "Put on Mesa weekend" })).toBeEnabled();
    expect(made.reload).toHaveBeenCalledTimes(1);
    expect(made.spy).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
  });

  it("closes the sheet and says so when the reload no longer lists the photo", async () => {
    vi.mocked(api).mockRejectedValue(new Refusal("No such photo", 404));
    const view: { rerender?: (p: { photos: ReviewPhoto[] }) => Promise<void> } = {};
    const made = show([ambiguous], ADA, async () => {}, async () => { await view.rerender?.({ photos: [] }); return true; });
    view.rerender = made.rerender as never;
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Pick a trip/ }));
    await user.click(await screen.findByRole("button", { name: "Put on Canyon weekend" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByText("Nothing needs a look.")).toBeInTheDocument();
    expect(toast).toHaveBeenCalledWith("No such photo.");
    expect(made.reload).toHaveBeenCalledTimes(1);
  });

  it("never says the list is up to date when the reload after a 409 fails", async () => {
    vi.mocked(api).mockRejectedValue(new Refusal("The photo’s trips changed", 409));
    const made = show([ambiguous], ADA, async () => {}, async () => false);
    await userEvent.setup().click(screen.getByRole("button", { name: /^Leave off, the photo/ }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The photo’s trips changed. Couldn’t refresh the list, so it may be out of date.");
    expect(alert).not.toHaveTextContent("up to date;");
    expect(made.reload).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: /^Leave off, the photo/ })).toBeEnabled();
  });

  it.each([
    ["Keep on this trip", far()],
    ["Leave off", ambiguous],
    ["Remove from this trip", far()],
  ])("%s reloads the list on a 409 and neither removes the row nor counts the choice as saved", async (action, subject) => {
    vi.mocked(api).mockRejectedValue(new Refusal("That photo changed", 409));
    const made = show([subject]);
    await userEvent.setup().click(screen.getByRole("button", { name: new RegExp(`^${action}`) }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That photo changed. That photo changed while you were looking. The list is up to date");
    expect(made.reload).toHaveBeenCalledTimes(1);
    expect(made.spy).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
  });

  it("reloads on a refused trip (400) and a missing photo (404) but not on a network failure or a server error", async () => {
    const made = show([ambiguous]);
    const user = userEvent.setup();
    const press = () => user.click(screen.getByRole("button", { name: /^Leave off, the photo/ }));
    for (const [status, reloads] of [[400, 1], [404, 2], [0, 2], [500, 2]] as const) {
      vi.mocked(api).mockRejectedValue(new Refusal("Nope", status));
      await press();
      await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Nope"));
      expect(made.reload).toHaveBeenCalledTimes(reloads);
    }
    expect(screen.getByRole("alert")).not.toHaveTextContent("up to date");
  });

  it("keeps the sheet open with the refusal when the trip is not shared", async () => {
    vi.mocked(api).mockRejectedValue(new Refusal("Share your photos on that trip first", 400));
    show([ambiguous]);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Pick a trip/ }));
    await user.click(await screen.findByRole("button", { name: "Put on Canyon weekend" }));
    const sheet = await screen.findByRole("dialog");
    expect(await within(sheet).findByRole("alert")).toHaveTextContent("Share your photos on that trip first");
    expect(within(sheet).getByRole("button", { name: "Put on Canyon weekend" })).toBeEnabled();
  });

  it("keeps the sheet open while a choice is being saved", async () => {
    let done: () => void = () => {};
    show([ambiguous], ADA, () => new Promise<void>((resolve) => { done = resolve; }));
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Pick a trip/ }));
    await user.click(await screen.findByRole("button", { name: "Put on Canyon weekend" }));
    const sheet = screen.getByRole("dialog");
    expect(within(sheet).getByRole("button", { name: "Saving…" })).toBeDisabled();
    expect(within(sheet).getByRole("button", { name: "Cancel" })).toBeDisabled();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    done();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("moves focus to the heading after a decision leaves other photos, and to the empty line after the last one, announcing it", async () => {
    const view: { rerender?: (p: { photos: ReviewPhoto[] }) => Promise<void> } = {};
    const next = { photos: [far()] };
    const made = show([ambiguous, far()], ADA, async () => { await view.rerender?.({ photos: next.photos }); });
    view.rerender = made.rerender as never;
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Leave off, the photo/ }));
    await waitFor(() => expect(screen.getByText("Needs a look").closest("summary")).toHaveFocus());
    expect(screen.getByRole("status")).toHaveTextContent("Saved. 1 photo still needs a look.");
    next.photos = [];
    await user.click(screen.getByRole("button", { name: /^Keep on this trip, the photo/ }));
    await waitFor(() => expect(screen.getByText("Nothing needs a look.", { selector: "p[tabindex]" })).toHaveFocus());
    expect(screen.getByRole("status")).toHaveTextContent("Saved. Nothing else needs a look.");
  });

  it("leaves no trip chosen and the confirm button off when a refused Pick removed the chosen trip", async () => {
    vi.mocked(api).mockRejectedValue(new Refusal("The photo’s trips changed", 409));
    const view: { rerender?: (p: { photos: ReviewPhoto[] }) => Promise<void> } = {};
    const fresh = photo(21, { candidates: [REDSTONE, { id: 14, name: "Mesa weekend" }] });
    const made = show([ambiguous], ADA, async () => {}, async () => { await view.rerender?.({ photos: [fresh] }); return true; });
    view.rerender = made.rerender as never;
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Pick a trip/ }));
    expect(await screen.findByRole("radio", { name: "Canyon weekend" })).toBeChecked();
    await user.click(screen.getByRole("button", { name: "Put on Canyon weekend" }));
    await waitFor(() => expect(screen.getByRole("radio", { name: "Mesa weekend" })).toBeInTheDocument());
    for (const radio of screen.getAllByRole("radio")) expect(radio).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Put on" })).toBeDisabled();
    await user.click(screen.getByRole("radio", { name: "Mesa weekend" }));
    expect(screen.getByRole("button", { name: "Put on Mesa weekend" })).toBeEnabled();
  });

  it("has its announcement region in the page before the first decision", () => {
    const { container } = show([ambiguous]);
    const region = container.querySelector("p.sr-only[role=status]") as HTMLElement;
    expect(region).not.toBeNull();
    expect(region.textContent).toBe("");
    expect(region).toHaveClass("sr-only");
  });
});

describe("Needs a look, undoing a decision", () => {
  const sent = (path: string, method: string) => vi.mocked(api).mock.calls.filter(([p, o]) => p === path && (o as Call | undefined)?.method === method);

  function leaving(photos: ReviewPhoto[], who = ADA) {
    const view: { rerender?: (p: { photos: ReviewPhoto[] }) => Promise<void>; now: ReviewPhoto[] } = { now: photos };
    const made = show(photos, who, async (id) => { view.now = view.now.filter((p) => p.id !== id); await view.rerender?.({ photos: view.now }); });
    view.rerender = made.rerender as never;
    return made;
  }

  it("Undo on the Pick toast sends the trip the photo was put on, reloads and says it is back", async () => {
    const { spy } = show([ambiguous]);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Pick a trip/ }));
    await user.click(await screen.findByRole("radio", { name: "Redstone weekend" }));
    await user.click(screen.getByRole("button", { name: "Put on Redstone weekend" }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    undoOf()();
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    expect(sent("/api/photos/21/undo", "POST")[0][1]).toMatchObject({ body: { trip_id: 12 } });
    expect(spy).toHaveBeenLastCalledWith(21);
    expect(toast.success).toHaveBeenLastCalledWith("Back in Needs a look.");
  });

  it("Undo on the Keep toast sends the trip the photo is on", async () => {
    const { spy } = show([far()]);
    await userEvent.setup().click(screen.getByRole("button", { name: /^Keep on this trip, the photo/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    undoOf()();
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    expect(sent("/api/photos/22/undo", "POST")[0][1]).toMatchObject({ body: { trip_id: 13 } });
  });

  it("Undo on the Leave off toast sends the stamp the leaving off came back with, and nothing else", async () => {
    const { spy } = show([ambiguous]);
    await userEvent.setup().click(screen.getByRole("button", { name: /^Leave off, the photo/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    undoOf()();
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    expect(sent("/api/photos/21/undo", "POST")[0][1]).toMatchObject({ body: { left_off: STAMP } });
    expect(Object.keys((sent("/api/photos/21/undo", "POST")[0][1] as { body: object }).body)).toEqual(["left_off"]);
  });

  it("Undo on the Remove toast puts the photo back with the removal’s own stamp", async () => {
    const { spy } = show([far()]);
    await userEvent.setup().click(screen.getByRole("button", { name: /^Remove from this trip, the photo/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    undoOf()();
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    expect(sent(`/api/trips/13/photo-exclusions/22?created=${STAMP}`, "DELETE")).toHaveLength(1);
    expect(toast.success).toHaveBeenLastCalledWith("Back in Needs a look.");
  });

  it("offers no Undo for a removal or a leaving off the reply gives no stamp for", async () => {
    vi.mocked(api).mockResolvedValue({ removed: [], removed_at: null } as never);
    const { spy } = show([ambiguous, far()]);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Leave off, the photo/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole("button", { name: /^Remove from this trip, the photo/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    expect(vi.mocked(toast.success).mock.calls).toEqual([["Left off both trips."], ["Removed from Four Corners loop."]]);
  });

  it("words every toast for the person the photo is for", async () => {
    expect([putText(ADA, "X"), keptText(ADA, "X"), leftText(ADA, 2), removedText(ADA, "X"), backText(ADA)]).toEqual(
      ["Put on X.", "Kept on X.", "Left off both trips.", "Removed from X.", "Back in Needs a look."]);
    expect([putText(JUNE, "X"), keptText(JUNE, "X"), leftText(JUNE, 3), removedText(JUNE, "X"), backText(JUNE)]).toEqual(
      ["Put June’s photo on X.", "Kept June’s photo on X.", "Left June’s photo off all those trips.", "Removed June’s photo from X.", "June’s photo is back in Needs a look."]);
    const { spy } = show([ambiguous], JUNE);
    await userEvent.setup().click(screen.getByRole("button", { name: /^Leave off, the photo/ }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Left June’s photo off both trips.", expect.anything()));
    undoOf()();
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    expect(toast.success).toHaveBeenLastCalledWith("June’s photo is back in Needs a look.");
  });

  it("holds every action disabled through the undo request and the reload, saying it is undoing", async () => {
    let done: () => void = () => {};
    let calls = 0;
    const { spy } = show([far()], ADA, () => (++calls === 1 ? Promise.resolve() : new Promise<void>((resolve) => { done = resolve; })));
    await userEvent.setup().click(screen.getByRole("button", { name: /^Keep on this trip, the photo/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByRole("button", { name: /^Pick a trip/ })).toBeEnabled());
    undoOf()();
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    for (const b of screen.getAllByRole("button").filter((x) => /^(Pick|Keep|Remove)/.test(x.getAttribute("aria-label") ?? ""))) expect(b).toBeDisabled();
    expect(screen.getByText("Undoing…")).toBeInTheDocument();
    done();
    await waitFor(() => expect(screen.queryByText("Undoing…")).toBeNull());
    for (const b of screen.getAllByRole("button").filter((x) => /^(Pick|Keep|Remove)/.test(x.getAttribute("aria-label") ?? ""))) expect(b).toBeEnabled();
  });

  it("waits for a decision still being saved before it undoes another", async () => {
    let done: () => void = () => {};
    let calls = 0;
    const { spy } = show([ambiguous, far()], ADA, () => (++calls === 2 ? new Promise<void>((resolve) => { done = resolve; }) : Promise.resolve()));
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Leave off, the photo/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    const first = undoOf();
    await user.click(screen.getByRole("button", { name: /^Keep on this trip, the photo/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    first();
    await new Promise((wake) => setTimeout(wake, 30));
    expect(sent("/api/photos/21/undo", "POST")).toHaveLength(0);
    done();
    await waitFor(() => expect(sent("/api/photos/21/undo", "POST")).toHaveLength(1));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(3));
  });

  it("sends an Undo once however many times the toast’s button is pressed", async () => {
    const { spy } = show([far()]);
    await userEvent.setup().click(screen.getByRole("button", { name: /^Keep on this trip, the photo/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    const press = undoOf();
    press();
    press();
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    expect(sent("/api/photos/22/undo", "POST")).toHaveLength(1);
  });

  it("on a 409 reloads the list first and then says the choice can’t be undone and the list is up to date", async () => {
    const { spy, reload } = leaving([ambiguous]);
    await userEvent.setup().click(screen.getByRole("button", { name: /^Leave off, the photo/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    vi.mocked(api).mockRejectedValue(new Refusal("That photo changed since you chose, so the choice can’t be undone", 409));
    const order: string[] = [];
    reload.mockImplementation(async () => { order.push("reload"); return true; });
    vi.mocked(toast).mockImplementation((() => { order.push("toast"); }) as never);
    undoOf()();
    await waitFor(() => expect(toast).toHaveBeenCalled());
    expect(order).toEqual(["reload", "toast"]);
    expect(toast).toHaveBeenCalledWith("That photo changed since you chose, so the choice can’t be undone. The list is up to date; check it before you choose again.");
    expect(spy).toHaveBeenCalledTimes(1);
    expect(toast.success).toHaveBeenCalledTimes(1);
  });

  it("never says the list is up to date when the reload after a refused Undo fails", async () => {
    const { spy, reload } = leaving([far()]);
    await userEvent.setup().click(screen.getByRole("button", { name: /^Remove from this trip, the photo/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    vi.mocked(api).mockRejectedValue(new Refusal("That photo was removed again", 409));
    reload.mockResolvedValue(false);
    undoOf()();
    await waitFor(() => expect(toast).toHaveBeenCalledWith("That photo was removed again. Couldn’t refresh the list, so it may be out of date."));
    expect(vi.mocked(toast).mock.calls.flat().join(" ")).not.toContain("up to date;");
  });

  it("offers Try again after a failure that isn’t a refusal, and a second try undoes it", async () => {
    const { spy, reload } = leaving([ambiguous]);
    await userEvent.setup().click(screen.getByRole("button", { name: /^Leave off, the photo/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    vi.mocked(api).mockRejectedValueOnce(new Refusal("Couldn’t undo that", 500));
    undoOf()();
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Couldn’t undo that", expect.objectContaining({ action: expect.objectContaining({ label: "Try again" }) })));
    expect(reload).not.toHaveBeenCalled();
    const retry = (vi.mocked(toast).mock.calls.at(-1)?.[1] as unknown as { action: { onClick: () => void } }).action.onClick;
    retry();
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    expect(sent("/api/photos/21/undo", "POST")).toHaveLength(2);
    expect(toast.success).toHaveBeenLastCalledWith("Back in Needs a look.");
  });

  it("puts the note on the photo’s own row when the reload still lists it", async () => {
    const view: { rerender?: (p: { photos: ReviewPhoto[] }) => Promise<void> } = {};
    const made = show([ambiguous], ADA, async () => {}, async () => true);
    view.rerender = made.rerender as never;
    await userEvent.setup().click(screen.getByRole("button", { name: /^Leave off, the photo/ }));
    await waitFor(() => expect(made.spy).toHaveBeenCalledTimes(1));
    vi.mocked(api).mockRejectedValue(new Refusal("That photo changed since you chose, so the choice can’t be undone", 409));
    undoOf()();
    expect(await screen.findByRole("alert")).toHaveTextContent("That photo changed since you chose, so the choice can’t be undone. The list is up to date");
    expect(toast).not.toHaveBeenCalled();
  });
});
