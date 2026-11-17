// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PastBookings from "./PastBookings.svelte";
import Harness from "./PastBookingsHarness.test.svelte";
import { viewport } from "$lib/phone.svelte";
import { segment } from "../../test/fixtures";

const trip = [
  segment({ id: 1, kind: "flight", origin: "DEN", destination: "GJT", start_local: "2025-06-12T09:40", end_local: "2025-06-12T10:52", confirmation: "ZQ9X7K" }),
  segment({ id: 2, kind: "hotel", origin: "Red Rock Lodge", destination: "Moab", start_local: "2025-06-12T15:00", end_local: "2025-06-15T11:00", confirmation: "ZQ9X7K" }),
  segment({ id: 3, kind: "car", provider: "Example Rentals", origin: "Grand Junction", destination: null, start_local: "2025-06-12T11:30", end_local: "2025-06-19T16:00", confirmation: "ZQ9X7K" }),
  segment({ id: 4, kind: "hotel", origin: "Cliffside Inn", destination: "Page", start_local: "2025-06-15T15:00", end_local: "2025-06-18T11:00", status: "cancelled", confirmation: "ZQ9X7K" }),
  segment({ id: 5, kind: "flight", origin: "FLG", destination: "DEN", start_local: "2025-06-19T18:15", end_local: "2025-06-19T20:55", confirmation: "ZQ9X7K" }),
  segment({ id: 6, kind: "parking", origin: "Airport long-term parking", destination: null, start_local: "2025-06-12T06:00", end_local: "2025-06-19T22:00", confirmation: "ZQ9X7K" }),
];

beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([{}] as unknown as DOMRectList);
});
afterEach(() => { viewport.phone = false; vi.restoreAllMocks(); });

describe("PastBookings grouped", () => {
  it("lists Whole trip first, then a group per day in date order, then Other last", () => {
    render(PastBookings, { segments: [...trip].reverse(), onopen: vi.fn() });
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual(["Whole trip", "Thu, Jun 12, 2025", "Sun, Jun 15, 2025", "Thu, Jun 19, 2025", "Other"]);
  });

  it("names each list by its heading and puts a stay on its check-in day", () => {
    render(PastBookings, { segments: trip, onopen: vi.fn() });
    const day = screen.getByRole("list", { name: "Thu, Jun 12, 2025" });
    expect(within(day).getAllByRole("button").map((b) => b.getAttribute("data-booking"))).toEqual(["1", "2"]);
    expect(within(screen.getByRole("list", { name: "Whole trip" })).getByRole("button", { name: /Example Rentals/ })).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Other" })).getByRole("button", { name: /Airport long-term parking/ })).toBeInTheDocument();
  });

  it("leaves the Other group out when nothing is parking", () => {
    render(PastBookings, { segments: trip.filter((s) => s.kind !== "parking"), onopen: vi.fn() });
    expect(screen.queryByRole("heading", { name: "Other" })).toBeNull();
  });

  it("names a row by what it is and when, with times as at the place", () => {
    render(PastBookings, { segments: trip, onopen: vi.fn() });
    expect(screen.getByRole("button", { name: "DEN to GJT 9:40 AM – 10:52 AM" })).toHaveAttribute("aria-haspopup", "dialog");
    expect(screen.getByRole("button", { name: "Red Rock Lodge, Moab Check in · 3 nights" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "FLG to DEN 6:15 PM – 8:55 PM" })).toBeInTheDocument();
  });

  it("keeps a cancelled stay in its group with a quiet label", () => {
    render(PastBookings, { segments: trip, onopen: vi.fn() });
    const row = screen.getByRole("button", { name: /Cliffside Inn, Page/ });
    expect(within(screen.getByRole("list", { name: "Sun, Jun 15, 2025" })).getByRole("button", { name: /Cancelled/ })).toBe(row);
  });

  it("shows no confirmation code anywhere", () => {
    const { container } = render(PastBookings, { segments: trip, onopen: vi.fn() });
    expect(container.textContent).not.toContain("ZQ9X7K");
  });

  it("hands the booking and its row to onopen", async () => {
    const onopen = vi.fn();
    render(PastBookings, { segments: trip, onopen });
    const row = screen.getByRole("button", { name: /DEN to GJT/ });
    await userEvent.click(row);
    expect(onopen).toHaveBeenCalledWith(trip[0], row);
  });
});

describe("PastBookings flat", () => {
  it("has no group headings and puts the date in each row", () => {
    render(PastBookings, { segments: trip, grouped: false, onopen: vi.fn() });
    expect(screen.queryAllByRole("heading")).toEqual([]);
    const names = within(screen.getByRole("list", { name: "Bookings" })).getAllByRole("button").map((b) => b.textContent?.replace(/\s+/g, " ").trim());
    expect(names).toEqual([
      "Example Rentals · Grand Junction Whole trip · Jun 12–19",
      "DEN to GJT Thu, Jun 12, 2025 · 9:40 AM",
      "Red Rock Lodge, Moab Jun 12–15 · 3 nights",
      "Cliffside Inn, Page Jun 15–18 · 3 nights · Cancelled",
      "FLG to DEN Thu, Jun 19, 2025 · 6:15 PM",
      "Airport long-term parking Jun 12–19",
    ]);
  });

  it("highlights the open booking", () => {
    render(PastBookings, { segments: trip, grouped: false, selected: 2, onopen: vi.fn() });
    expect(screen.getByRole("button", { name: /Red Rock Lodge/ })).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: /DEN to GJT/ })).not.toHaveAttribute("aria-current");
  });
});

describe("PastBookings in its sheet", () => {
  it("is a dialog named Bookings · 5 that takes focus and returns focus to the row", async () => {
    viewport.phone = true;
    render(Harness, { segments: trip, onopen: vi.fn() });
    const user = userEvent.setup();
    const opener = screen.getByRole("button", { name: "Bookings row" });
    await user.click(opener);
    const dialog = await screen.findByRole("dialog", { name: "Bookings · 5" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleDescription("2 flights · 1 stay · 1 car · 1 parking");
    await waitFor(() => expect(dialog).toContainElement(document.activeElement as HTMLElement));
    await user.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(opener).toHaveFocus());
  });
});
