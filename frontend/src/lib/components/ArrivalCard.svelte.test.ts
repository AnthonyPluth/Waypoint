// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), apiImage: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { apiImage } from "$lib/api";
import { arrival, pendingFor, resetArrival } from "$lib/arrival.svelte";
import { installShell, type FakeShell } from "../../test/fake-shell";
import { segment } from "../../test/fixtures";
import ArrivalCard from "./ArrivalCard.svelte";

const user = userEvent.setup({ pointerEventsCheck: 0 });
const NOW = Date.parse("2026-12-01T16:00:00Z");
const lot = segment({
  id: 5, trip_id: 7, kind: "parking", origin: "Harbour Parking, Lot B", provider: null, destination: null, confirmation: "HP-48213",
  start_local: "2026-12-01T09:00", start_zone: "America/Denver", end_local: "2026-12-05T18:00", end_zone: "America/Denver", details: {}, gate_code: { state: "ready", day: "2026-10-16" },
});
const rental = segment({ id: 6, trip_id: 7, kind: "car", provider: "Sol Rent a Car", origin: "Lisbon Airport", destination: null, confirmation: "SR-7Q2K9", start_local: "2026-12-01T09:30", start_zone: "America/Denver", end_local: "2026-12-05T10:00", end_zone: "America/Denver", details: {} });
const stay = segment({ id: 8, trip_id: 7, kind: "hotel", provider: null, origin: "Casa do Rio", destination: null, confirmation: "8841 2207", start_local: "2026-12-01T15:00", start_zone: "America/Denver", end_local: "2026-12-05T11:00", end_zone: "America/Denver", details: {} });
const flight = segment({ id: 9, trip_id: 7 });
const all = [lot, rental, stay, flight];

let shell: FakeShell;
const here = (segmentId: number | null, tripId: number | null = segmentId === null ? null : 7) => shell.replies.set("arrivalHere", { version: 1, segmentId, tripId });

beforeEach(() => { resetArrival(); shell = installShell(); vi.mocked(apiImage).mockReset(); vi.mocked(apiImage).mockResolvedValue("data:image/png;base64,QUJD"); });
afterEach(() => { vi.unstubAllGlobals(); });

describe("the card on Upcoming when the app says you are at a booking (frame A3)", () => {
  it("names the place, says the code is one tap away and offers the QR code for parking", async () => {
    here(5);
    render(ArrivalCard, { segments: all, now: NOW });
    const card = await screen.findByRole("status", { name: "You’re at Harbour Parking, Lot B" });
    expect(card).toHaveTextContent("You’re at Harbour Parking, Lot B");
    expect(card).toHaveTextContent("Your code is one tap away.");
    expect(screen.getByRole("button", { name: "Show QR code" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
  });

  it("never opens the code by itself: the tap takes the person to the booking’s trip page and hands the booking over", async () => {
    here(5);
    location.hash = "#upcoming";
    render(ArrivalCard, { segments: all, now: NOW });
    await screen.findByTestId("arrival-card");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(apiImage).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Show QR code" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(location.hash).toBe("#trip/7");
    expect(pendingFor(7)).toBe(5);
  });

  it("does the same for a rental pickup and a hotel", async () => {
    for (const [id, label] of [[6, "Show pickup"], [8, "Show check-in"]] as const) {
      resetArrival();
      location.hash = "#upcoming";
      here(id);
      const { unmount } = render(ArrivalCard, { segments: all, now: NOW });
      await user.click(await screen.findByRole("button", { name: label }));
      expect(location.hash).toBe("#trip/7");
      expect(pendingFor(7)).toBe(id);
      unmount();
    }
  });

  it("hides the card again for the same arrival after a dismissal is cleared by a different booking", async () => {
    here(5);
    render(ArrivalCard, { segments: all, now: NOW });
    await user.click(await screen.findByRole("button", { name: "Dismiss" }));
    here(8);
    document.dispatchEvent(new Event("visibilitychange"));
    await screen.findByRole("status", { name: "You’re at Casa do Rio" });
    here(5);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(await screen.findByRole("status", { name: "You’re at Harbour Parking, Lot B" })).toBeInTheDocument();
  });

  it("hides until you leave and arrive again when it is dismissed, and comes back for the next arrival", async () => {
    here(5);
    render(ArrivalCard, { segments: all, now: NOW });
    await user.click(await screen.findByRole("button", { name: "Dismiss" }));
    expect(screen.queryByTestId("arrival-card")).toBeNull();
    here(5);
    document.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() => expect(shell.posts.filter((p) => p.type === "arrivalHere")).toHaveLength(2));
    expect(screen.queryByTestId("arrival-card")).toBeNull();
    here(null);
    document.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() => expect(arrival.dismissed).toBeNull());
    here(5);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(await screen.findByTestId("arrival-card")).toBeInTheDocument();
  });

  it("asks again each time the app comes back to the front, and not while it is hidden", async () => {
    here(null);
    render(ArrivalCard, { segments: all, now: NOW });
    await waitFor(() => expect(shell.posts.filter((p) => p.type === "arrivalHere")).toHaveLength(1));
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() => expect(shell.posts.filter((p) => p.type === "arrivalHere")).toHaveLength(2));
  });

  it("shows only one card, for the booking the app named", async () => {
    here(8);
    render(ArrivalCard, { segments: all, now: NOW });
    await screen.findByTestId("arrival-card");
    expect(screen.getAllByTestId("arrival-card")).toHaveLength(1);
  });

  it("shows nothing when the app names nowhere, a booking that isn’t on the page, a booking with no code, or fails", async () => {
    for (const setup of [() => here(null), () => here(99), () => here(5, 8), () => here(9), () => shell.replies.set("arrivalHere", { version: 1, segmentId: "x", tripId: 7 })]) {
      resetArrival();
      setup();
      const { unmount } = render(ArrivalCard, { segments: all, now: NOW });
      await waitFor(() => expect(shell.posts.filter((p) => p.type === "arrivalHere").length).toBeGreaterThan(0));
      await Promise.resolve();
      expect(screen.queryByTestId("arrival-card")).toBeNull();
      shell.posts.length = 0;
      unmount();
    }
    resetArrival();
    here(5);
    const { unmount } = render(ArrivalCard, { segments: [{ ...lot, gate_code: null }, { ...rental, status: "cancelled" }], now: NOW });
    await waitFor(() => expect(shell.posts.length).toBeGreaterThan(0));
    expect(screen.queryByTestId("arrival-card")).toBeNull();
    unmount();
  });

  it("asks nothing and shows nothing in a browser", async () => {
    vi.unstubAllGlobals();
    render(ArrivalCard, { segments: all, now: NOW });
    await Promise.resolve();
    expect(screen.queryByTestId("arrival-card")).toBeNull();
    expect(shell.posts).toHaveLength(0);
  });
});
