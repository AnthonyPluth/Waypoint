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
import PhotosNeedsLook, { aboutOf, choicesOf, listOf, offWhere } from "./PhotosNeedsLook.svelte";

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

function show(photos: ReviewPhoto[], who = ADA, ondecided: (id: number) => Promise<unknown> = async () => {}) {
  const spy = vi.fn(ondecided);
  const view = render(PhotosNeedsLook, { photos, who, ondecided: spy });
  return { spy, ...view };
}

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockResolvedValue({} as never);
  vi.mocked(toast.success).mockReset();
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
    expect(toast.success).toHaveBeenCalledWith("Put on Redstone weekend.");
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
    expect(toast.success).toHaveBeenCalledWith("Left off both trips.");
  });

  it("Keep on this trip sends the trip the photo is shown on", async () => {
    const { spy } = show([far()]);
    await userEvent.setup().click(screen.getByRole("button", { name: /^Keep on this trip, the photo/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith(22));
    expect(posted("/api/photos/22")[0][1]).toMatchObject({ body: { trip_id: 13 } });
    expect(toast.success).toHaveBeenCalledWith("Kept on Four Corners loop.");
  });

  it("Remove from this trip removes it from the trip the photo is shown on, for that photo only", async () => {
    const { spy } = show([far()]);
    await userEvent.setup().click(screen.getByRole("button", { name: /^Remove from this trip, the photo/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith(22));
    expect(posted("/api/trips/13/photo-exclusions")[0][1]).toMatchObject({ body: { photo_ids: [22] } });
    expect(posted("/api/photos/22")).toHaveLength(0);
    expect(toast.success).toHaveBeenCalledWith("Removed from Four Corners loop.");
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
    expect(screen.getByRole("status")).toHaveTextContent("Saving…");
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

  it("on a 409 asks for a fresh look: closes the sheet and names the change", async () => {
    vi.mocked(api).mockRejectedValue(new Refusal("The photo’s trips changed", 409));
    show([ambiguous]);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Pick a trip/ }));
    await user.click(await screen.findByRole("button", { name: "Put on Canyon weekend" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("alert")).toHaveTextContent("The photo’s trips changed That photo changed while you were looking.");
    expect(posted("/api/photos/21")).toHaveLength(1);
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
});
