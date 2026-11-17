// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { Person, PhotoGrantPerson, PhotoSharing, TripPhoto, TripPhotos as Reply } from "$lib/api-types";
import { app } from "$lib/app.svelte";
import { viewport } from "$lib/phone.svelte";
import type { PersonSharing } from "$lib/trip-sharing.svelte";
import { segment, state, trip } from "../../test/fixtures";
import TripPhotos from "./TripPhotos.svelte";

const user = userEvent.setup({ pointerEventsCheck: 0 });

class Refusal extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

const person = (id: number, display_name: string, first_name: string, member: boolean): Person => ({ id, display_name, first_name, legal_name: null, aliases: [], member, links: [] });
const ada = person(1, "Ada Brook", "Ada", true);
const june = person(3, "June Brook", "June", false);
const stay = segment({ id: 2, kind: "hotel", origin: "Juniper House", destination: "Marlow Springs", start_local: "2026-03-01T15:00", start_zone: "America/Denver", end_local: "2026-03-04T11:00", end_zone: "America/Denver" });
const road = trip([stay], { id: 7, name: "Four Corners loop", start_date: "2026-03-01", end_date: "2026-03-04", people: [1, 3] });
const after = Date.parse("2026-04-01T12:00:00Z");
const WINDOW = { start: "2026-02-28T12:00:00+00:00", end: "2026-03-05T12:00:00+00:00" };
const sharing = (extra: Partial<PhotoSharing> = {}): PhotoSharing => ({
  state: "shared", scope: "trip", count: 169, removed_count: 0, removed: [], window: WINDOW, changed: 1700000000, audience: [1, 3], sources: [{ id: 7, status: "ok" }], count_token: "c".repeat(32), ...extra,
});
const photo = (id: number, owner = 1): TripPhoto => ({
  id, person_id: owner, trip_id: 7, kind: "image", taken_local: "2026-03-01T10:42", zone: "America/Denver", latitude: 39.7, longitude: -105, location_source: "exif", segment_id: 2, match: "place", distance_km: 3, cluster: 0, removed_at: null,
});
const reply = (photos: TripPhoto[]): Reply => ({ photos, clusters: [], counts: { total: photos.length, located: photos.length, inferred: 0, far: 0 }, people: [], best: [] });
const grants = (id: number): PhotoGrantPerson => ({ person_id: id, prefs: { default_scope: "only_me", share_all: false }, count_token: "g".repeat(32), sources: [{ id: 7, status: "ok" }], eligible: [], trips: [] });

type Call = { method?: string };
let mine: PhotoSharing | Error;
let hers: PhotoSharing | Error;
let photos: TripPhoto[];
let failReload = false;

function serve() {
  vi.mocked(api).mockImplementation(async (path: string, opts?: Call) => {
    if (path.includes("/photo-sharing")) {
      const which = path.includes("person_id=3") ? hers : mine;
      if (opts?.method === "DELETE") {
        mine = sharing({ state: "declined", scope: null });
        return mine as never;
      }
      if (which instanceof Error) throw which;
      if (failReload && opts?.method === "POST") {
        mine = new Refusal("The server fell over", 500);
        return which as never;
      }
      return which as never;
    }
    if (path === "/api/photo-grants") return { people: [grants(1), grants(3)] } as never;
    if (path === "/api/photo-sources") return { sources: [], permissions: [] } as never;
    if (path.endsWith("/photos")) return reply(photos) as never;
    throw new Error(`unexpected ${path}`);
  });
}

const mount = (extra: { timeline?: boolean; people?: Person[]; trip?: typeof road; onsharing?: (acting: PersonSharing[], settled: boolean) => void } = {}) => render(TripPhotos, { trip: extra.trip ?? { ...road, people: [1] }, people: extra.people ?? [ada], now: after, timeline: extra.timeline, onsharing: extra.onsharing });
const button = () => screen.findByRole("button", { name: "Sharing" });
const panel = () => screen.findByRole("dialog", { name: "Photo sharing for this trip" });
const stopTitle = "Stop sharing your photos on this trip?";

beforeEach(() => {
  vi.mocked(api).mockReset();
  app.state = state({ person_id: 1 });
  mine = sharing();
  hers = new Refusal("No such trip", 404);
  photos = [photo(1), photo(2)];
  viewport.phone = false;
  failReload = false;
  serve();
});
afterEach(() => { app.state = null; viewport.phone = false; });

describe("The Sharing button", () => {
  it("sits first in the Photos header, ahead of Select and See all, named by its text", async () => {
    mount();
    const sharingButton = await button();
    const row = sharingButton.parentElement?.parentElement as HTMLElement;
    const names = within(row).getAllByRole("button").map((b) => b.getAttribute("aria-label") ?? b.textContent);
    expect(names).toEqual(["Sharing", "Select your photos to remove", "See all 2 photos"]);
    expect(sharingButton).toHaveAttribute("aria-haspopup", "dialog");
    expect(sharingButton).toHaveAttribute("aria-expanded", "false");
    expect(sharingButton).not.toHaveAttribute("aria-label");
    expect(sharingButton).toBeEnabled();
  });

  it("is there with no photos at all, while there is a sharing card", async () => {
    photos = [];
    mount();
    await button();
    expect(screen.queryByRole("button", { name: "Select your photos to remove" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^See all/ })).toBeNull();
  });

  it.each([
    ["the first-visit prompt", sharing({ state: "ask", scope: null })],
    ["the reminder", sharing({ state: "declined", scope: null })],
    ["a person with no library", sharing({ state: "none", scope: null, count: 0 })],
  ])("is not there beside %s", async (_name, found) => {
    mine = found;
    mount();
    await screen.findByTestId("photo-strip");
    await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalledWith("/api/trips/7/photo-sharing?person_id=1", { keep: true }));
    expect(screen.queryByRole("button", { name: "Sharing" })).toBeNull();
  });

  it("is not there for a traveller who has nothing to manage on the trip", async () => {
    mine = new Refusal("No such trip", 404);
    mount();
    await screen.findByTestId("photo-strip");
    expect(screen.queryByRole("button", { name: "Sharing" })).toBeNull();
    expect(screen.queryByTestId("your-photos")).toBeNull();
  });

  it("is left to the past trip's page on a timeline, which draws no card and no button itself", async () => {
    const onsharing = vi.fn();
    mount({ timeline: true, onsharing });
    await waitFor(() => expect(onsharing).toHaveBeenCalledWith(expect.arrayContaining([expect.objectContaining({ mode: "card" })]), true));
    expect(screen.queryByTestId("your-photos")).toBeNull();
    expect(screen.queryByRole("button", { name: "Sharing" })).toBeNull();
  });

  it("keeps the card out of the page until it is opened", async () => {
    mount();
    await button();
    expect(screen.queryByTestId("your-photos")).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("The popover on a desktop", () => {
  it("opens under the button, titled, non-modal, with the words the card has today, and moves focus to the title", async () => {
    mount();
    const trigger = await button();
    await user.click(trigger);
    const dialog = await panel();
    expect(dialog).toHaveAttribute("aria-modal", "false");
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(trigger).toHaveAttribute("aria-controls", dialog.id);
    expect(within(dialog).getByRole("heading", { level: 2, name: "Photo sharing for this trip" })).toHaveFocus();
    const card = within(dialog).getByRole("region", { name: "Your photos on this trip" });
    expect(within(card).getByText("169 photos from your library")).toBeInTheDocument();
    expect(within(card).getByText("Everyone on this trip", { selector: "[data-tone]" })).toBeInTheDocument();
    expect(within(card).getByRole("radio", { name: /^Only me/ })).not.toBeChecked();
    expect(within(card).getByRole("radio", { name: /^Everyone on this trip/ })).toBeChecked();
    expect(within(card).getByText("Nobody else on the trip can tell they’re there.")).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Stop sharing on this trip" })).toBeEnabled();
    expect(within(card).queryByRole("button", { name: /^Show sharing for/ })).toBeNull();
    expect(screen.getByTestId("photo-strip")).toBeInTheDocument();
  });

  it("closes on Escape and gives focus back to the button", async () => {
    mount();
    const trigger = await button();
    await user.click(trigger);
    await panel();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(trigger).toHaveFocus();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("closes on its Close button and on the button again, and gives focus back", async () => {
    mount();
    const trigger = await button();
    await user.click(trigger);
    await user.click(within(await panel()).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(trigger).toHaveFocus();
    await user.click(trigger);
    await panel();
    await user.click(trigger);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes on a click outside it, and stays open for a click inside it", async () => {
    mount();
    await user.click(await button());
    const dialog = await panel();
    await user.click(within(dialog).getByText("169 photos from your library"));
    expect(screen.getByRole("dialog", { name: "Photo sharing for this trip" })).toBeInTheDocument();
    await user.click(screen.getByTestId("photo-strip"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes when Tab leaves it, and carries on from the button", async () => {
    mount();
    await user.click(await button());
    const dialog = await panel();
    within(dialog).getByRole("button", { name: "Stop sharing on this trip" }).focus();
    await user.tab();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("button", { name: "Select your photos to remove" })).toHaveFocus();
  });

  it("takes Escape for itself and leaves a selection under way alone", async () => {
    mount();
    await user.click(await screen.findByRole("button", { name: "Select your photos to remove" }));
    await user.click(await button());
    await panel();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByTestId("photo-selection")).toBeInTheDocument();
  });
});

describe("The panel's own actions", () => {
  it("opens the stop confirmation on top of the panel, which stays open and gets focus back on Keep sharing", async () => {
    mount();
    await user.click(await button());
    const stop = within(await panel()).getByRole("button", { name: "Stop sharing on this trip" });
    await user.click(stop);
    const confirm = await screen.findByRole("dialog", { name: stopTitle });
    await waitFor(() => expect(within(confirm).getByRole("button", { name: "Keep sharing" })).toHaveFocus());
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: stopTitle })).toBeNull());
    expect(screen.getByRole("dialog", { name: "Photo sharing for this trip" })).toBeInTheDocument();
    await waitFor(() => expect(stop).toHaveFocus());
  });

  it("does not count a click in the confirmation as an outside click", async () => {
    mount();
    await user.click(await button());
    await user.click(within(await panel()).getByRole("button", { name: "Stop sharing on this trip" }));
    const confirm = await screen.findByRole("dialog", { name: stopTitle });
    await user.click(within(confirm).getByText(/right away, for everyone/));
    await user.click(within(confirm).getByRole("button", { name: "Keep sharing" }));
    expect(screen.getByRole("dialog", { name: "Photo sharing for this trip" })).toBeInTheDocument();
  });

  it("closes, with the button gone, when sharing is stopped, and puts focus on the Photos heading", async () => {
    mount();
    await user.click(await button());
    await user.click(within(await panel()).getByRole("button", { name: "Stop sharing on this trip" }));
    await user.click(within(await screen.findByRole("dialog", { name: stopTitle })).getByRole("button", { name: "Stop sharing" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Sharing" })).toBeNull());
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(screen.getByRole("heading", { level: 2, name: /^Photos/ })).toHaveFocus());
    expect(await screen.findByTestId("photo-reminder")).toBeInTheDocument();
  });

  it("asks before widening, from the panel, as it does today", async () => {
    mine = sharing({ scope: "only_me" });
    mount();
    await user.click(await button());
    await user.click(within(await panel()).getByRole("radio", { name: /^Everyone on this trip/ }));
    expect(await screen.findByRole("dialog", { name: /^Show your 169 photos to everyone on this trip/ })).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Photo sharing for this trip" })).toBeInTheDocument();
  });
});

describe("A steward managing a person without a sign-in", () => {
  const withJune = () => mount({ people: [ada, june], trip: road });

  it("gets the viewer's own section first and open, and June's collapsed", async () => {
    hers = sharing({ scope: "only_me", count: 41 });
    withJune();
    await user.click(await button());
    const dialog = await panel();
    const sections = within(dialog).getAllByRole("region");
    expect(sections.map((s) => s.querySelector("h3")?.textContent)).toEqual(["Your photos on this trip", "June’s photos on this trip"]);
    expect(within(sections[0]).getByRole("radio", { name: /^Only me/ })).toBeInTheDocument();
    const toggle = within(sections[1]).getByRole("button", { name: "Show sharing for June’s photos" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(within(sections[1]).getByText("41 photos from June’s library")).toBeInTheDocument();
    expect(within(sections[1]).getByText("Only June", { selector: "[data-tone]" })).toBeInTheDocument();
    expect(within(sections[1]).queryByRole("radio")).toBeNull();
    expect(within(sections[0]).queryByRole("button", { name: /^Show sharing for/ })).toBeNull();
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(within(sections[1]).getByRole("radio", { name: /^Only June/ })).toBeChecked();
    expect(within(sections[1]).getByRole("button", { name: "Stop sharing on this trip" })).toBeInTheDocument();
    await user.click(toggle);
    expect(within(sections[1]).queryByRole("radio")).toBeNull();
  });

  it("starts June's section expanded when the viewer's own sharing is still at the prompt", async () => {
    mine = sharing({ state: "ask", scope: null, count: 5 });
    hers = sharing({ scope: "only_me", count: 41 });
    withJune();
    await user.click(await button());
    const dialog = await panel();
    const section = within(dialog).getByRole("region", { name: "June’s photos on this trip" });
    expect(within(section).getByRole("radio", { name: /^Only June/ })).toBeChecked();
    expect(within(section).queryByRole("button", { name: /^Show sharing for/ })).toBeNull();
    expect(screen.getByRole("group", { name: "You have 5 photos from this trip" })).toBeInTheDocument();
  });

  it("shows the button for June's card when the viewer's own has none", async () => {
    mine = sharing({ state: "none", scope: null, count: 0 });
    hers = sharing({ scope: "only_me", count: 41 });
    withJune();
    await user.click(await button());
    expect(within(await panel()).getAllByRole("region")).toHaveLength(1);
  });
});

describe("The bottom sheet on a phone", () => {
  beforeEach(() => { viewport.phone = true; });

  it("opens the app's sheet, titled, and closes on Escape with focus back on the button", async () => {
    mount();
    const trigger = await button();
    await user.click(trigger);
    const sheet = await panel();
    expect(sheet).toHaveAttribute("data-side", "bottom");
    expect(within(sheet).getByRole("region", { name: "Your photos on this trip" })).toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: "Stop sharing on this trip" })).toBeEnabled();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("closes on its Close button, and stays open for a click inside it", async () => {
    mount();
    await user.click(await button());
    const sheet = await panel();
    await user.click(within(sheet).getByText("169 photos from your library"));
    expect(screen.getByRole("dialog", { name: "Photo sharing for this trip" })).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("opens the stop confirmation on top of the sheet", async () => {
    mount();
    await user.click(await button());
    await user.click(within(await panel()).getByRole("button", { name: "Stop sharing on this trip" }));
    const confirm = await screen.findByRole("dialog", { name: stopTitle });
    await user.click(within(confirm).getByRole("button", { name: "Keep sharing" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: stopTitle })).toBeNull());
    expect(screen.getByRole("dialog", { name: "Photo sharing for this trip" })).toBeInTheDocument();
  });

  it("shows why the controls are locked, with Try again, inside the sheet after a reload fails", async () => {
    mount();
    await user.click(await button());
    const sheet = await panel();
    failReload = true;
    await user.click(within(sheet).getByRole("radio", { name: /^Only me/ }));
    const notice = await within(sheet).findByRole("alert");
    expect(notice).toHaveTextContent("Couldn’t refresh your photo sharing for this trip, so what shows may be out of date.");
    expect(within(sheet).getByRole("radio", { name: /^Only me/ })).toBeDisabled();
    expect(within(sheet).getByRole("button", { name: "Stop sharing on this trip" })).toBeDisabled();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    failReload = false;
    mine = sharing({ scope: "only_me" });
    await user.click(within(notice).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(within(sheet).queryByRole("alert")).toBeNull());
    expect(within(sheet).getByRole("radio", { name: /^Only me/ })).toBeEnabled();
    expect(within(sheet).getByRole("radio", { name: /^Only me/ })).toBeChecked();
    expect(screen.getByRole("dialog", { name: "Photo sharing for this trip" })).toBeInTheDocument();
  });

  it("keeps the one notice on the page once the sheet is closed", async () => {
    mount();
    await user.click(await button());
    const sheet = await panel();
    failReload = true;
    await user.click(within(sheet).getByRole("radio", { name: /^Only me/ }));
    await within(sheet).findByRole("alert");
    await user.click(within(sheet).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const notice = await screen.findByRole("alert");
    expect(notice).toHaveTextContent("Couldn’t refresh your photo sharing for this trip");
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("stops sharing from the sheet, closing it and leaving the reminder on the page with focus on the Photos heading", async () => {
    mount();
    await user.click(await button());
    await user.click(within(await panel()).getByRole("button", { name: "Stop sharing on this trip" }));
    await user.click(within(await screen.findByRole("dialog", { name: stopTitle })).getByRole("button", { name: "Stop sharing" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(vi.mocked(api)).toHaveBeenCalledWith("/api/trips/7/photo-sharing?person_id=1", expect.objectContaining({ method: "DELETE" }));
    expect(screen.queryByRole("button", { name: "Sharing" })).toBeNull();
    expect(await screen.findByTestId("photo-reminder")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("heading", { level: 2, name: /^Photos/ })).toHaveFocus());
  });
});
