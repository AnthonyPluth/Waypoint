// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), apiImage: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { apiImage } from "$lib/api";
import { arrival, resetArrival } from "$lib/arrival.svelte";
import { installShell } from "../../test/fake-shell";
import { segment } from "../../test/fixtures";
import ArrivalOpen from "./ArrivalOpen.svelte";

const NOW = Date.parse("2026-12-01T16:00:00Z");
const lot = segment({
  id: 5, trip_id: 7, kind: "parking", origin: "Harbour Parking, Lot B", provider: null, destination: null, confirmation: "HP-48213",
  start_local: "2026-12-01T09:00", start_zone: "America/Denver", end_local: "2026-12-05T18:00", end_zone: "America/Denver", details: {}, has_email: true, gate_code: { state: "ready", day: "2026-10-16" },
});
const rental = segment({ id: 6, trip_id: 7, kind: "car", provider: "Sol Rent a Car", origin: "Lisbon Airport", destination: null, confirmation: "SR-7Q2K9", start_local: "2026-12-01T09:30", start_zone: "America/Denver", end_local: "2026-12-05T10:00", end_zone: "America/Denver", details: {} });
const target = (segmentId: number, tripId = 7) => { arrival.target = { segmentId, tripId, at: Date.now() }; };

beforeEach(() => { resetArrival(); installShell(); vi.mocked(apiImage).mockReset(); vi.mocked(apiImage).mockResolvedValue("data:image/png;base64,QUJD"); });
afterEach(() => { vi.unstubAllGlobals(); });

describe("the trip page after a tap on the arrival notification", () => {
  it("opens the QR code of the parking booking the notification was for, and uses the arrival up", async () => {
    target(5);
    render(ArrivalOpen, { tripId: 7, segments: [lot, rental], now: NOW });
    expect(await screen.findByRole("dialog", { name: "QR code" })).toBeInTheDocument();
    expect(await screen.findByRole("img", { name: "QR code for Harbour Parking, Lot B" })).toBeInTheDocument();
    expect(arrival.target).toBeNull();
  });

  it("opens the confirmation of a rental pickup", async () => {
    target(6);
    render(ArrivalOpen, { tripId: 7, segments: [lot, rental], now: NOW });
    expect(await screen.findByRole("dialog", { name: "Pickup" })).toHaveTextContent("SR-7Q2K9");
  });

  it("opens nothing for another trip, and keeps the arrival for its own", async () => {
    target(5, 8);
    render(ArrivalOpen, { tripId: 7, segments: [lot, rental], now: NOW });
    await Promise.resolve();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(arrival.target).not.toBeNull();
  });

  it("opens nothing, and forgets the arrival, when the booking has no code to show or is not on the trip", async () => {
    for (const [wanted, segments] of [[5, [{ ...lot, gate_code: null }]], [6, [{ ...rental, status: "cancelled" as const }]], [99, [lot]]] as const) {
      target(wanted);
      const { unmount } = render(ArrivalOpen, { tripId: 7, segments: [...segments], now: NOW });
      await Promise.resolve();
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(arrival.target).toBeNull();
      unmount();
    }
  });

  it("opens nothing when there was no arrival", async () => {
    render(ArrivalOpen, { tripId: 7, segments: [lot], now: NOW });
    await Promise.resolve();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows the saved picture, or the failure line with the confirmation number, with no connection", async () => {
    vi.mocked(apiImage).mockRejectedValue(new TypeError("Failed to fetch"));
    const shell = installShell({ trips: [{ trip: { id: 7 }, messages: [], codes: [{ segment_id: 5, type: "image/png", data: "REVG" }] }] });
    target(5);
    const { unmount } = render(ArrivalOpen, { tripId: 7, segments: [lot], now: NOW });
    expect(await screen.findByRole("img", { name: "QR code for Harbour Parking, Lot B" })).toHaveAttribute("src", "data:image/png;base64,REVG");
    unmount();
    shell.trips = [{ trip: { id: 7 }, messages: [] }];
    target(5);
    render(ArrivalOpen, { tripId: 7, segments: [lot], now: NOW });
    expect(await screen.findByRole("alert")).toHaveTextContent("The code can’t be shown right now");
    expect(screen.getByTestId("code-confirmation")).toHaveTextContent("Confirmation HP-48213");
  });
});
