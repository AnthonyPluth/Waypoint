// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { app } from "$lib/app.svelte";
import type { Segment } from "$lib/api-types";
import Harness from "./BookingDetailHarness.test.svelte";
import { segment, state } from "../../test/fixtures";

const ada = { id: 1, person_id: 1, name: "Ada Brook", seat: null };
const june = { id: 2, person_id: 2, name: "June Brook", seat: null };
const noLinks = { app: "https://airline.example/manage", open: "https://vendor.example/", open_kind: "website" as const, directions: "https://maps.example/dir", call: "tel:+15551234" };
const base = { travelers: [ada, june], links: noLinks, has_email: true, price: { amount_minor: 41200, currency: "USD", source: "manual" } as Segment["price"] };

const flight = segment({ ...base, id: 1, kind: "flight", provider: "Example Air", origin: "DEN", destination: "GJT", start_local: "2025-06-12T09:40", end_local: "2025-06-12T10:52", confirmation: "K7QX2M", details: { flight_number: "214", terminal: "B", seat: "12B, 12A", cabin: "Economy" } });
const stay = segment({ ...base, id: 2, kind: "hotel", provider: null, origin: "Red Rock Lodge", destination: "Moab", start_local: "2025-06-12T15:00", end_local: "2025-06-15T11:00", confirmation: "HX81Q", price: { amount_minor: 128400, currency: "USD", source: "manual" }, details: { address: "1500 Red Cliffs Road, Moab, UT 84532", room: "King, 214", check_in: "3:00 PM", check_out: "11:00 AM" } });
const car = segment({ ...base, id: 3, kind: "car", provider: "Example Rentals", origin: "Grand Junction Regional Airport", destination: "Flagstaff Pulliam Airport", start_local: "2025-06-12T11:30", end_local: "2025-06-19T14:00", confirmation: "R4T9W2", details: { car_class: "Compact SUV", address: "1100 Walker Field Drive, Grand Junction" } });
const train = segment({ ...base, id: 4, kind: "train", provider: "Coast Line 14", origin: "Portland", destination: "Seattle", start_local: "2025-08-05T08:10", end_local: "2025-08-05T11:45", confirmation: "TR55P9", details: { seat: "21B, 21A", cabin: "Business", terminal: "Gate 4" } });
const cruise = segment({ ...base, id: 5, kind: "cruise", provider: "Example Cruise Line", origin: "Seattle", destination: "Seattle", start_local: "2025-08-08T16:00", end_local: "2025-08-15T07:00", confirmation: "AU9082", details: { ship: "MS Aurora", room: "8214", deck: "8" },
  days: [{ day: 1, date: "2025-08-08", sea: false, stops: [{ name: "Seattle", arrive_local: null, depart_local: "2025-08-08T16:00", recorded: true }] }, { day: 2, date: "2025-08-09", sea: true, stops: [] }, { day: 3, date: "2025-08-10", sea: false, stops: [{ name: "Juneau", arrive_local: null, depart_local: null, recorded: true }, { name: "Skagway", arrive_local: null, depart_local: null, recorded: true }] }] as Segment["days"] });
const parking = segment({ ...base, id: 6, kind: "parking", provider: null, origin: "Airport long-term parking", destination: null, start_local: "2025-06-12T06:00", end_local: "2025-06-19T22:00", confirmation: "PK3318", details: { address: "Denver Airport, Lot C", space_type: "Covered", vehicle: "Subaru Outback", notes: "Shuttle every 10 minutes" } });
const visit = segment({ ...base, id: 7, kind: "visit", provider: null, origin: null, destination: "US", start_local: "2025-06-12T00:00", end_local: "2025-06-14T00:00", confirmation: null, price: null, details: { notes: "Staying at Sam’s" } });
const cancelled = segment({ ...base, id: 8, kind: "hotel", status: "cancelled", provider: null, origin: "Canyon Rim Motel", destination: "Page", start_local: "2025-06-15T15:00", end_local: "2025-06-18T11:00", confirmation: "CM48X", price: { amount_minor: 98600, currency: "USD", source: "manual" }, details: { address: "12 Lakeview Drive, Page, AZ 86040" } });

const open = async (segments: Segment[], name: string | RegExp, props: Record<string, unknown> = {}) => {
  const view = render(Harness, { segments, ...props });
  const u = userEvent.setup();
  await u.click(screen.getByRole("button", { name }));
  const dialog = await screen.findByRole("dialog");
  return { u, dialog, view };
};
const labels = (dialog: HTMLElement) => [...dialog.querySelectorAll("dt")].map((d) => d.textContent?.trim());
const value = (dialog: HTMLElement, label: string) => [...dialog.querySelectorAll("dt")].find((d) => d.textContent?.trim() === label)?.nextElementSibling as HTMLElement;

beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([{}] as unknown as DOMRectList);
  app.state = state();
});
afterEach(() => { app.state = null; vi.restoreAllMocks(); });

describe("BookingDetail fields by kind", () => {
  it("lists a flight's fields, with the seats in order", async () => {
    const { dialog } = await open([flight], /DEN to GJT/);
    expect(dialog).toHaveAccessibleName("DEN to GJT");
    expect(labels(dialog)).toEqual(["Departs", "Arrives", "Terminal", "Seat", "Cabin", "Confirmation", "Travellers", "Price"]);
    expect(value(dialog, "Departs")).toHaveTextContent("9:40 AM · DEN");
    expect(value(dialog, "Seat")).toHaveTextContent("12A, 12B");
    expect(value(dialog, "Travellers")).toHaveTextContent("Ada Brook, June Brook");
    expect(value(dialog, "Price")).toHaveTextContent("$412.00");
    expect(dialog).toHaveAccessibleDescription("Flight · Example Air 214 · Thu, Jun 12, 2025");
  });

  it("lists a stay's dates with no check-in or check-out time", async () => {
    const { dialog } = await open([stay], /Red Rock Lodge/);
    expect(labels(dialog)).toEqual(["Dates", "Address", "Room", "Confirmation", "Price"]);
    expect(value(dialog, "Dates")).toHaveTextContent("Jun 12–15 · 3 nights");
    expect(dialog).not.toHaveTextContent(/check.?in|check.?out|3:00|11:00/i);
    expect(dialog).toHaveAccessibleName("Red Rock Lodge");
    expect(dialog).toHaveAccessibleDescription("Stay · Moab, UT");
  });

  it("lists a car with the labels the booking card uses", async () => {
    const { dialog } = await open([car], /Example Rentals/);
    expect(labels(dialog)).toEqual(["Pick-up", "Drop-off", "Car", "Pick-up address", "Confirmation", "Price"]);
    expect(value(dialog, "Car")).toHaveTextContent("Compact SUV");
  });

  it("lists a train without a terminal or a gate", async () => {
    const { dialog } = await open([train], /Portland to Seattle/);
    expect(labels(dialog)).toEqual(["Departs", "Arrives", "Seat", "Cabin", "Confirmation", "Price"]);
    expect(dialog).not.toHaveTextContent(/gate/i);
  });

  it("lists a cruise's ports, ship, cabin and deck", async () => {
    const { dialog } = await open([cruise], /MS Aurora/);
    expect(labels(dialog)).toEqual(["Embarks", "Disembarks", "Ports", "Ship", "Cabin", "Deck", "Confirmation", "Travellers", "Price"]);
    expect(value(dialog, "Ports")).toHaveTextContent("Seattle, Juneau, Skagway");
    expect(value(dialog, "Deck")).toHaveTextContent("8");
  });

  it("lists parking, and leaves out a field with no value", async () => {
    const { dialog } = await open([{ ...parking, details: { address: "Denver Airport, Lot C", space_type: "Covered" } }], /Airport long-term parking/);
    expect(labels(dialog)).toEqual(["Dates", "Address", "Space", "Confirmation", "Price"]);
    expect(value(dialog, "Dates")).toHaveTextContent("Jun 12–19 · 7 days");
  });

  it("lists a visit without a confirmation or a price", async () => {
    const { dialog } = await open([visit], /United States/);
    expect(labels(dialog)).toEqual(["Dates", "Place", "Notes"]);
    expect(value(dialog, "Dates")).toHaveTextContent("Thu, Jun 12, 2025 – Sat, Jun 14, 2025");
    expect(dialog).not.toHaveTextContent(/time not recorded/i);
  });

  it("says time not recorded for a flight with no times, at both ends", async () => {
    const { dialog } = await open([{ ...flight, details: { ...flight.details, time_unknown: "yes" } }], /DEN to GJT/);
    expect(value(dialog, "Departs")).toHaveTextContent("time not recorded · DEN");
    expect(value(dialog, "Arrives")).toHaveTextContent("time not recorded · GJT");
  });
});

describe("BookingDetail header", () => {
  it.each([[flight, /DEN to GJT/], [stay, /Red Rock Lodge/], [car, /Example Rentals/], [train, /Portland to Seattle/], [cruise, /MS Aurora/], [parking, /Airport long-term/], [visit, /United States/]])("keeps Edit visible next to Close for every kind (%#)", async (booking, name) => {
    const onedit = vi.fn();
    const { u, dialog } = await open([booking], name, { onedit });
    await u.click(within(dialog).getByRole("button", { name: "Edit" }));
    expect(onedit).toHaveBeenCalledWith(expect.objectContaining({ id: booking.id }));
    expect(within(dialog).getByRole("button", { name: "Close" })).toBeInTheDocument();
  });

  it("keeps Move and Remove in a More menu with the names the booking card gave them", async () => {
    const onmove = vi.fn(), onremove = vi.fn();
    const { u, dialog } = await open([stay], /Red Rock Lodge/, { onmove, onremove });
    await u.click(within(dialog).getByRole("button", { name: "More options for Red Rock Lodge" }));
    await u.click(within(dialog).getByRole("button", { name: "Move Red Rock Lodge" }));
    expect(onmove).toHaveBeenCalledWith(expect.objectContaining({ id: 2 }));
    await u.click(within(dialog).getByRole("button", { name: "More options for Red Rock Lodge" }));
    await u.click(within(dialog).getByRole("button", { name: "Remove Red Rock Lodge" }));
    expect(onremove).toHaveBeenCalledWith(expect.objectContaining({ id: 2 }));
  });

  it("hides Edit and More once the trip is Done, and keeps Close", async () => {
    const { dialog } = await open([stay], /Red Rock Lodge/, { canChange: false });
    expect(within(dialog).queryByRole("button", { name: /^(Edit|More)/ })).toBeNull();
    expect(within(dialog).getByRole("button", { name: "Close" })).toBeInTheDocument();
  });

  it("names a combined booking's legs in More, so each one can be moved or removed", async () => {
    const first = { ...flight, details: { ...flight.details, flight_number: "AA0101" } };
    const second = { ...flight, id: 9, confirmation: "BBBBBB", details: { ...flight.details, flight_number: "AA0101" } };
    const { u, dialog } = await open([first, second], /DEN to GJT/);
    await u.click(within(dialog).getByRole("button", { name: /^More options/ }));
    for (const name of ["Move DEN → GJT booking K7QX2M", "Remove DEN → GJT booking K7QX2M", "Edit DEN → GJT booking BBBBBB", "Move DEN → GJT booking BBBBBB", "Remove DEN → GJT booking BBBBBB"]) expect(within(dialog).getByRole("button", { name })).toBeInTheDocument();
    expect(labels(dialog).filter((l) => l === "Departs")).toHaveLength(2);
    expect(within(dialog).getAllByRole("button", { name: /^Copy confirmation code/ })).toHaveLength(2);
  });
});

describe("BookingDetail copy, costs and travellers", () => {
  it("copies the confirmation code and the address under their own names", async () => {
    const { u, dialog } = await open([stay], /Red Rock Lodge/);
    const write = vi.spyOn(navigator.clipboard, "writeText");
    await u.click(within(dialog).getByRole("button", { name: "Copy confirmation code HX81Q" }));
    expect(write).toHaveBeenLastCalledWith("HX81Q");
    await u.click(within(dialog).getByRole("button", { name: "Copy address" }));
    expect(write).toHaveBeenLastCalledWith("1500 Red Cliffs Road, Moab, UT 84532");
  });

  it("shows the code only here, set in the mono face", async () => {
    const { dialog } = await open([stay], /Red Rock Lodge/);
    expect(value(dialog, "Confirmation").querySelector(".mono")).toHaveTextContent("HX81Q");
  });

  it("hides Price when costs are hidden", async () => {
    app.state = state({ show_costs: false });
    const { dialog } = await open([flight], /DEN to GJT/);
    expect(labels(dialog)).not.toContain("Price");
    expect(dialog).not.toHaveTextContent("$412.00");
  });

  const sam = segment({ ...base, id: 20, kind: "visit", origin: null, destination: "US", start_local: "2025-06-13T00:00", end_local: "2025-06-14T00:00", travelers: [{ id: 3, person_id: 3, name: "Sam Brook", seat: null }] });

  it("lists no travellers for a stay, a car or parking, as the booking card did", async () => {
    const { dialog } = await open([stay, train, sam], /Red Rock Lodge/);
    expect(labels(dialog)).not.toContain("Travellers");
  });

  it("lists a train's travellers when they are not everyone on the trip", async () => {
    const { dialog } = await open([train, sam], /Portland to Seattle/);
    expect(value(dialog, "Travellers")).toHaveTextContent("Ada Brook, June Brook");
  });

  it("leaves out email, directions, call and the airline app, and any loyalty number", async () => {
    const { dialog } = await open([flight], /DEN to GJT/);
    expect(within(dialog).queryByRole("link")).toBeNull();
    expect(within(dialog).queryByRole("button", { name: /email|directions|call|app/i })).toBeNull();
    expect(dialog).not.toHaveTextContent(/loyalty|gate|on time|delayed/i);
  });
});

describe("BookingDetail seats, overnight trains and combined cancellations", () => {
  it("keeps each traveller's seat beside their name", async () => {
    const seated = { ...flight, travelers: [{ ...ada, seat: "12B" }, { ...june, seat: "12A" }] };
    const { dialog } = await open([seated], /DEN to GJT/);
    const who = value(dialog, "Travellers");
    expect(who).toHaveTextContent("Ada Brook · Seat 12B");
    expect(who).toHaveTextContent("June Brook · Seat 12A");
  });

  it("keeps the arrival day of an overnight train", async () => {
    const overnight = { ...train, start_local: "2025-08-05T21:30", end_local: "2025-08-06T07:15" };
    const { dialog } = await open([overnight], /Portland to Seattle/);
    expect(value(dialog, "Arrives")).toHaveTextContent("7:15 AM · +1 day · Seattle");
  });

  it("does not call a combined booking cancelled when only one leg is, and marks that leg", async () => {
    const live = { ...flight, details: { ...flight.details, flight_number: "AA0101" } };
    const dead = { ...flight, id: 9, status: "cancelled" as const, confirmation: "BBBBBB", details: { ...flight.details, flight_number: "AA0101" } };
    const { dialog } = await open([live, dead], /DEN to GJT/);
    expect(within(dialog).queryByText("Cancelled")).toBeNull();
    expect(dialog).not.toHaveTextContent(/^Cancelled, so not in the trip’s total/);
    expect(within(dialog).getAllByText("Cancelled, so not in the trip’s total")).toHaveLength(1);
    expect(labels(dialog).filter((l) => l === "Status")).toHaveLength(1);
    expect(dialog.querySelectorAll(".line-through").length).toBeGreaterThan(0);
  });
});

describe("BookingDetail seats shown once, and legs of a combined booking", () => {
  const seated = { ...flight, travelers: [{ ...ada, seat: "12B" }, { ...june, seat: "12A" }] };

  it("shows each seat once, beside its traveller, when every traveller has one", async () => {
    const { dialog } = await open([seated], /DEN to GJT/);
    expect(labels(dialog)).not.toContain("Seat");
    expect(dialog.textContent?.match(/12B/g)).toHaveLength(1);
    expect(dialog.textContent?.match(/12A/g)).toHaveLength(1);
  });

  it("keeps a Seat row for a seat that belongs to no listed traveller, without repeating the others", async () => {
    const extra = { ...seated, details: { ...seated.details, seat: "12A, 12B, 12C" } };
    const { dialog } = await open([extra], /DEN to GJT/);
    expect(value(dialog, "Seat").textContent?.trim()).toBe("12C");
    expect(dialog.textContent?.match(/12B/g)).toHaveLength(1);
  });

  const live = { ...flight, travelers: [{ ...ada, seat: "12B" }], details: { ...flight.details, flight_number: "AA0101", seat: "12B" } };
  const dead = { ...flight, id: 9, status: "cancelled" as const, confirmation: "BBBBBB", travelers: [{ ...ada, seat: "9A" }, { ...june, seat: "9B" }], details: { ...flight.details, flight_number: "AA0101", seat: "9A, 9B" } };

  it("ties the cancelled leg's Status row to that leg's confirmation code", async () => {
    const { dialog } = await open([live, dead], /DEN to GJT/);
    expect(value(dialog, "Status")).toHaveTextContent("Cancelled, so not in the trip’s total");
    expect(value(dialog, "Status").querySelector(".mono")).toHaveTextContent("BBBBBB");
  });

  it("marks the travellers who belong to the cancelled leg, with its code", async () => {
    const { dialog } = await open([live, dead], /DEN to GJT/);
    const who = value(dialog, "Travellers");
    expect(who).toHaveTextContent("Ada Brook · Seat 12B · On cancelled booking BBBBBB");
    expect(who).toHaveTextContent("June Brook · Seat 9B · On cancelled booking BBBBBB");
  });

  it("takes a traveller's seat from the live leg, even when the cancelled leg comes first", async () => {
    const { dialog } = await open([dead, live], /DEN to GJT/);
    const who = value(dialog, "Travellers");
    expect(who).toHaveTextContent("Ada Brook · Seat 12B");
    expect(who).not.toHaveTextContent("Seat 9A");
  });

  it("keeps the cancelled leg's own seat in its Seat row, without repeating a seat shown beside a traveller", async () => {
    const { dialog } = await open([dead, live], /DEN to GJT/);
    const seats = [...dialog.querySelectorAll("dt")].filter((d) => d.textContent?.trim() === "Seat").map((d) => d.nextElementSibling?.textContent?.trim());
    expect(seats).toEqual(["9A"]);
  });

  it("shows a traveller's seats per leg when two live legs differ", async () => {
    const other = { ...live, id: 10, confirmation: "CCCCCC", travelers: [{ ...ada, seat: "14C" }] };
    const { dialog } = await open([live, other], /DEN to GJT/);
    expect(value(dialog, "Travellers")).toHaveTextContent("Ada Brook · Seat 12B (K7QX2M) · Seat 14C (CCCCCC)");
  });

  it("marks nobody and adds no cancelled note when no leg is cancelled", async () => {
    const { dialog } = await open([live, { ...live, id: 10, confirmation: "CCCCCC" }], /DEN to GJT/);
    expect(dialog).not.toHaveTextContent(/cancelled/i);
  });
});

describe("BookingDetail changed", () => {
  const changed = { ...stay, id: 11, status: "changed" as const };

  it("shows the Changed chip in the header, in the warn tone", async () => {
    const { dialog } = await open([changed], /Red Rock Lodge/);
    expect(within(dialog).getByText("Changed")).toHaveAttribute("data-tone", "warn");
    expect(dialog).not.toHaveTextContent(/Cancelled/);
  });

  it("shows the chip when only one leg of a combined booking changed", async () => {
    const first = { ...flight, details: { ...flight.details, flight_number: "AA0101" } };
    const second = { ...first, id: 9, confirmation: "BBBBBB", status: "changed" as const };
    const { dialog } = await open([first, second], /DEN to GJT/);
    expect(within(dialog).getByText("Changed")).toBeInTheDocument();
  });

  it("shows no status chip for a confirmed booking", async () => {
    const { dialog } = await open([stay], /Red Rock Lodge/);
    expect(within(dialog).queryByText(/^(Changed|Confirmed|Cancelled)$/)).toBeNull();
  });
});

describe("BookingDetail cancelled", () => {
  it("shows the red chip, strikes the dates and price and says it is not in the total", async () => {
    const { dialog } = await open([cancelled], /Canyon Rim Motel/);
    expect(within(dialog).getByText("Cancelled")).toHaveAttribute("data-tone", "bad");
    expect(dialog).toHaveTextContent("Cancelled, so not in the trip’s total");
    expect(value(dialog, "Dates").querySelector(".line-through")).not.toBeNull();
    expect(value(dialog, "Price").querySelector(".line-through")).toHaveTextContent("$986.00");
    expect(labels(dialog)).toContain("Confirmation");
  });
});

describe("BookingDetail focus", () => {
  it("moves focus in, and gives it back to the row that opened it", async () => {
    const view = render(Harness, { segments: [flight, stay] });
    const u = userEvent.setup();
    const row = screen.getByRole("button", { name: /Red Rock Lodge/ });
    await u.click(row);
    const dialog = await screen.findByRole("dialog", { name: "Red Rock Lodge" });
    await waitFor(() => expect(dialog).toContainElement(document.activeElement as HTMLElement));
    await u.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(row).toHaveFocus());
    view.unmount();
  });
});
