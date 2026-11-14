// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { createRawSnippet } from "svelte";
import { afterEach, describe, expect, it } from "vitest";
import type { Person, TripPhoto } from "$lib/api-types";
import { segment } from "../../test/fixtures";
import PhotoViewer from "./PhotoViewer.svelte";

const ada: Person = { id: 1, display_name: "Ada Brook", first_name: "Ada", legal_name: null, aliases: [], member: true, links: [] };
const stay = segment({ id: 2, kind: "hotel", origin: "Juniper House", destination: "Marlow Springs", start_local: "2026-03-08T15:00", start_zone: "America/Denver", end_local: "2026-03-12T11:00", end_zone: "America/Denver" });
const drive = segment({ id: 3, kind: "car", provider: "Example Cars", origin: "Marlow Springs airport", destination: null, start_local: "2026-03-08T09:00", start_zone: "America/Denver", end_local: "2026-03-12T11:00", end_zone: "America/Denver" });
const segments = new Map([[2, stay], [3, drive]]);
const photo = (id: number, extra: Partial<TripPhoto> = {}): TripPhoto => ({
  id, person_id: 1, trip_id: 7, kind: "image", taken_local: "2026-03-09T10:42", zone: "America/Denver", latitude: 39.7, longitude: -105, location_source: "exif",
  segment_id: 2, match: "place", distance_km: 3.2, cluster: 0, removed_at: null, ...extra,
});
const photos = [photo(11), photo(12, { kind: "video", taken_local: "2026-03-10T16:18", location_source: "inferred", latitude: null, longitude: null }), photo(13, { match: "far", distance_km: 612, taken_local: "2026-03-10T07:55", zone: "America/Los_Angeles" })];

const dialog = (name: string | RegExp) => screen.findByRole("dialog", { name });
const info = () => screen.getByTestId("photo-viewer");

afterEach(() => { document.body.innerHTML = ""; });

describe("PhotoViewer", () => {
  it("shows the preview, the wall-clock time where it was taken, the place, the person and Open original", async () => {
    render(PhotoViewer, { open: true, index: 0, photos, people: [ada], segments });
    await dialog("Photo 1 of 3");
    expect(info().querySelector("img")?.getAttribute("src")).toBe("/api/photos/11/preview");
    expect(screen.getByText("10:42 AM")).toBeTruthy();
    expect(screen.getByText("Mon, Mar 9, 2026 · Denver time")).toBeTruthy();
    expect(screen.getByText("Near Marlow Springs")).toBeTruthy();
    expect(screen.getByText("From the photo’s location · 3 km from Juniper House")).toBeTruthy();
    expect(screen.getByText("From Ada Brook’s library")).toBeTruthy();
    const original = screen.getByRole("link", { name: "Open original" });
    expect(original.getAttribute("href")).toBe("/api/photos/11/original");
    expect(original.getAttribute("target")).toBe("_blank");
    expect(original.getAttribute("rel")).toBe("noopener noreferrer");
    expect(screen.queryByRole("button", { name: /Remove|Hide/ })).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Close" })));
  });

  it("moves with the arrow keys and the buttons, and stops at either end", async () => {
    render(PhotoViewer, { open: true, index: 0, photos, people: [ada], segments });
    await dialog("Photo 1 of 3");
    expect(screen.getAllByRole("button", { name: "Previous photo" }).every((b) => (b as HTMLButtonElement).disabled)).toBe(true);
    await userEvent.keyboard("{ArrowLeft}");
    expect(await dialog("Photo 1 of 3")).toBeTruthy();
    await userEvent.keyboard("{ArrowRight}");
    expect(await dialog("Video 2 of 3")).toBeTruthy();
    await userEvent.click(screen.getAllByRole("button", { name: "Next photo" })[0]);
    expect(await dialog("Photo 3 of 3")).toBeTruthy();
    await userEvent.keyboard("{ArrowRight}");
    expect(await dialog("Photo 3 of 3")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Next photo" }).every((b) => (b as HTMLButtonElement).disabled)).toBe(true);
    await userEvent.click(screen.getAllByRole("button", { name: "Previous photo" })[0]);
    expect(await dialog("Video 2 of 3")).toBeTruthy();
  });

  it("moves on a sideways swipe and closes on a swipe down", async () => {
    const view = render(PhotoViewer, { open: true, index: 1, photos, people: [ada], segments });
    await dialog("Video 2 of 3");
    const stage = info().querySelector(".photo-viewer-stage")!;
    await fireEvent.pointerDown(stage, { clientX: 300, clientY: 200 });
    await fireEvent.pointerUp(stage, { clientX: 200, clientY: 210 });
    expect(await dialog("Photo 3 of 3")).toBeTruthy();
    await fireEvent.pointerDown(stage, { clientX: 100, clientY: 200 });
    await fireEvent.pointerUp(stage, { clientX: 260, clientY: 190 });
    expect(await dialog("Video 2 of 3")).toBeTruthy();
    await fireEvent.pointerDown(stage, { clientX: 100, clientY: 200 });
    await fireEvent.pointerUp(stage, { clientX: 110, clientY: 230 });
    expect(await dialog("Video 2 of 3")).toBeTruthy();
    await fireEvent.pointerDown(stage, { clientX: 100, clientY: 100 });
    await fireEvent.pointerUp(stage, { clientX: 105, clientY: 260 });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    view.unmount();
  });

  it("closes on Escape and on Close, giving focus back to where it was opened from", async () => {
    const tile = document.createElement("button");
    document.body.append(tile);
    render(PhotoViewer, { open: true, index: 0, photos, people: [ada], segments, returnTo: () => tile });
    await dialog("Photo 1 of 3");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(tile);
  });

  it("closes on Close", async () => {
    render(PhotoViewer, { open: true, index: 0, photos, people: [ada], segments });
    await userEvent.click(within(await dialog("Photo 1 of 3")).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("shows a video’s still with Play, then plays the original, and says where it was placed from", async () => {
    render(PhotoViewer, { open: true, index: 1, photos, people: [ada], segments });
    await dialog("Video 2 of 3");
    expect(screen.getByRole("img", { name: "Video still" }).getAttribute("src")).toBe("/api/photos/12/preview");
    expect(screen.getByText("Tue, Mar 10, 2026 · Denver time · Video")).toBeTruthy();
    expect(screen.getByText("From the itinerary")).toBeTruthy();
    expect(screen.getByText("This video has no location. You were staying at Juniper House, Marlow Springs.")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Play video" }));
    expect(info().querySelector("video")?.getAttribute("src")).toBe("/api/photos/12/original");
  });

  it("says a photo placed from a booking that isn’t a stay was placed from it, and an offset as it is given", async () => {
    render(PhotoViewer, { open: true, index: 0, photos: [photo(14, { location_source: "inferred", segment_id: 3, zone: "UTC-07:00" })], people: [ada], segments });
    await dialog("Photo 1 of 1");
    expect(screen.getByText("Mon, Mar 9, 2026 · UTC-07:00")).toBeTruthy();
    expect(screen.getByText("This photo has no location. It was placed from Example Cars · Marlow Springs airport.")).toBeTruthy();
  });

  it("flags a far photo with its distance and its own zone", async () => {
    render(PhotoViewer, { open: true, index: 2, photos, people: [ada], segments });
    await dialog("Photo 3 of 3");
    expect(screen.getByText("7:55 AM")).toBeTruthy();
    expect(screen.getByText("Tue, Mar 10, 2026 · Los Angeles time")).toBeTruthy();
    expect(screen.getByText("Far from the trip’s bookings")).toBeTruthy();
    expect(screen.getByText("Far: 612 km from every booking")).toBeTruthy();
  });

  it("says when a preview can’t be loaded, and tries again", async () => {
    render(PhotoViewer, { open: true, index: 0, photos, people: [], segments: new Map() });
    await dialog("Photo 1 of 3");
    expect(screen.queryByText(/library/)).toBeNull();
    expect(screen.getByText("Where it was taken")).toBeTruthy();
    await fireEvent.error(info().querySelector("img")!);
    expect(await dialog("Photo can’t be loaded")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("Can’t load this photo right now");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await dialog("Photo 1 of 3")).toBeTruthy();
    await fireEvent.error(info().querySelector("img")!);
    await userEvent.click(within(await screen.findByRole("status")).getByRole("button", { name: "Next photo" }));
    expect(await dialog("Video 2 of 3")).toBeTruthy();
    await fireEvent.error(info().querySelector("img")!);
    await userEvent.click(await screen.findByRole("button", { name: "Back to the trip" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("leaves room for actions on a photo", async () => {
    const actions = createRawSnippet((p: () => TripPhoto) => ({ render: () => `<button type="button">Act on ${p().id}</button>` }));
    render(PhotoViewer, { open: true, index: 0, photos, people: [ada], segments, actions });
    expect(await screen.findByRole("button", { name: "Act on 11" })).toBeTruthy();
  });
});
