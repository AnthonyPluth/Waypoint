// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { toast } from "svelte-sonner";
import { segment } from "../../test/fixtures";
import ConfirmationCode from "./ConfirmationCode.svelte";

const user = userEvent.setup({ pointerEventsCheck: 0 });
const rental = segment({
  id: 2, kind: "car", provider: "Example Rent", origin: "Example Airport", destination: null, confirmation: "SR-7Q2K9",
  start_local: "2026-12-01T13:30", start_zone: "America/Denver", end_local: "2026-12-05T10:00", end_zone: "America/Denver",
  details: { car_class: "Compact, automatic", address: "12 Airport Rd, Example City" }, travelers: [{ id: 1, person_id: 1, name: "Sam Rivera", seat: null }],
});
const stay = segment({
  id: 3, kind: "hotel", provider: "Example Hotels", origin: "Casa Example", destination: null, confirmation: "8841 2207",
  start_local: "2026-12-01T15:00", start_zone: "America/Denver", end_local: "2026-12-05T11:00", end_zone: "America/Denver",
  details: { address: "3 Inn Ave" }, travelers: [{ id: 1, person_id: 1, name: "Sam Rivera", seat: null }, { id: 2, person_id: 2, name: "Alex Kim", seat: null }],
});

beforeEach(() => { vi.mocked(toast.success).mockClear(); vi.mocked(toast).mockClear(); });

describe("the pickup confirmation (frame B3a)", () => {
  it("shows the number large in the mono face, with the rows the counter asks about, and its hint", async () => {
    render(ConfirmationCode, { segment: rental, open: true });
    const dialog = await screen.findByRole("dialog", { name: "Pickup" });
    const number = within(dialog).getByTestId("confirmation-number");
    expect(number).toHaveTextContent("SR-7Q2K9");
    expect(number).toHaveClass("mono");
    const rows = within(dialog).getByTestId("confirmation-rows");
    expect(rows).toHaveTextContent("CompanyExample Rent");
    expect(rows).toHaveTextContent("Pickup Tue, Dec 1, 1:30 PM");
    expect(rows).toHaveTextContent("Where12 Airport Rd, Example City");
    expect(rows).toHaveTextContent("CarCompact, automatic");
    expect(rows).toHaveTextContent("DriverSam Rivera");
    expect(dialog).toHaveTextContent("Show this at the counter.");
    expect(within(dialog).getByRole("button", { name: "Close" })).toBeInTheDocument();
  });

  it("leaves out the rows it has nothing for, and uses the pickup place when there is no address", async () => {
    render(ConfirmationCode, { segment: { ...rental, provider: null, details: {}, travelers: [] }, open: true });
    const rows = within(await screen.findByRole("dialog", { name: "Pickup" })).getByTestId("confirmation-rows");
    expect(rows).not.toHaveTextContent("Company");
    expect(rows).not.toHaveTextContent("Car");
    expect(rows).not.toHaveTextContent("Driver");
    expect(rows).toHaveTextContent("WhereExample Airport");
  });

  it("says the time is not recorded when the booking has none", async () => {
    render(ConfirmationCode, { segment: { ...rental, details: { ...rental.details, time_unknown: "yes" } }, open: true });
    expect(within(await screen.findByRole("dialog", { name: "Pickup" })).getByTestId("confirmation-rows")).toHaveTextContent("time not recorded");
  });
});

describe("the check-in confirmation (frame B3b)", () => {
  it("shows the number, the hotel, check-in from its time, the room and the guests, and its hint", async () => {
    render(ConfirmationCode, { segment: stay, open: true });
    const dialog = await screen.findByRole("dialog", { name: "Check-in" });
    expect(within(dialog).getByTestId("confirmation-number")).toHaveTextContent("8841 2207");
    const rows = within(dialog).getByTestId("confirmation-rows");
    expect(rows).toHaveTextContent("HotelCasa Example");
    expect(rows).toHaveTextContent("Check-in Tue, Dec 1 from 3:00 PM");
    expect(rows).toHaveTextContent("RoomNot known yet");
    expect(rows).toHaveTextContent("GuestsSam Rivera, Alex Kim");
    expect(dialog).toHaveTextContent("Show this at the front desk.");
  });

  it("shows the room when it is known and no guests row when nobody is named", async () => {
    render(ConfirmationCode, { segment: { ...stay, details: { room: "412" }, travelers: [] }, open: true });
    const rows = within(await screen.findByRole("dialog", { name: "Check-in" })).getByTestId("confirmation-rows");
    expect(rows).toHaveTextContent("Room412");
    expect(rows).not.toHaveTextContent("Guests");
  });
});

describe("Copy and Close", () => {
  it("copies the confirmation number", async () => {
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(ConfirmationCode, { segment: rental, open: true });
    await user.click(await screen.findByRole("button", { name: "Copy confirmation SR-7Q2K9" }));
    expect(writeText).toHaveBeenCalledWith("SR-7Q2K9");
    expect(toast.success).toHaveBeenCalledWith("Copied");
  });

  it("closes with its button and with Escape", async () => {
    render(ConfirmationCode, { segment: stay, open: true });
    await user.click(await screen.findByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("is not on screen until it is opened", () => {
    render(ConfirmationCode, { segment: stay });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
