// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import BookingCard from "./BookingCard.svelte";
import { bookingCards } from "$lib/trips";
import type { Segment } from "$lib/api-types";
import { segment } from "../../test/fixtures";

const NOW = Date.parse("2026-03-01T12:00:00Z");

const common = { confirmation: "ZQ9X7K", price: { amount_minor: 123400, currency: "USD", source: "manual" } as Segment["price"], travelers: [{ id: 1, person_id: 1, name: "Jane Doe", seat: null }] };
const stay = segment({ id: 1, kind: "hotel", provider: "Hotel Example", origin: "Hotel Example", destination: "Alfama", start_local: "2026-03-13T15:00", end_local: "2026-03-16T11:00", details: { address: "1 Rua Example, Lisbon" }, ...common });
const car = segment({ id: 2, kind: "car", provider: "Example Rentals", origin: "Lisbon Airport", destination: null, start_local: "2026-03-13T11:00", end_local: "2026-03-20T16:00", ...common });
const train = segment({ id: 3, kind: "train", provider: "Example Rail", origin: "Lisboa", destination: "Porto", start_local: "2026-03-13T09:15", end_local: "2026-03-13T12:40", ...common });
const cruise = segment({ id: 4, kind: "cruise", provider: "Example Lines", origin: "Azure Meridian", destination: null, start_local: "2026-03-13T17:00", end_local: "2026-03-20T07:00", ...common });
const lot = segment({ id: 5, kind: "parking", origin: "Bayside Park & Fly", destination: null, start_local: "2026-03-09T04:30", end_local: "2026-03-20T22:00", gate_code: { state: "ready", day: "2026-03-01" }, ...common });

const leg = segment({ id: 6, kind: "flight", provider: "Example Air", origin: "LIS", destination: "JFK", start_local: "2026-03-20T10:05", end_local: "2026-03-20T13:20", details: { flight_number: "EX 410" }, ...common });

const cardOf = (s: typeof stay) => bookingCards([s])[0];
const show = (s: typeof stay, extra: Partial<{ now: number }> = {}) => render(BookingCard, { card: cardOf(s), now: NOW, onopen: vi.fn(), ...extra });
const facts = (container: HTMLElement) => [...container.querySelectorAll("dl > div")].map((d) => [d.querySelector("dt")?.textContent, d.querySelector("dd")?.textContent]);

describe("BookingCard facts", () => {
  it.each([
    ["stay", stay, [["Check-in", "Mar 13"], ["Nights", "3"], ["Check-out", "Mar 16"]]],
    ["car", car, [["Pick-up", "Mar 13"], ["Days", "7"], ["Return", "Mar 20"]]],
    ["train", train, [["Departs", "9:15 AM"], ["From", "Lisboa"], ["Arrives", "12:40 PM"]]],
    ["cruise", cruise, [["Embarks", "Mar 13"], ["Nights", "7"], ["Disembarks", "Mar 20"]]],
    ["parking", lot, [["Entry", "4:30 AM"], ["Days", "11"], ["Exit", "Mar 20"]]],
    ["flight", leg, [["Departs", "10:05 AM"], ["Flight", "EX 410"], ["Arrives", "1:20 PM"]]],
  ] as const)("shows the three facts of a %s", (_, s, expected) => {
    const { container } = show(s);
    expect(facts(container)).toEqual(expected);
  });

  it("shows a flight with no number or no times by dashes, with no repeated label", () => {
    const { container } = show({ ...leg, details: { time_unknown: "yes" } });
    expect(facts(container)).toEqual([["Departs", "—"], ["Flight", "—"], ["Arrives", "—"]]);
  });

  it("shows that an overnight flight arrives on another day, without converting its time", () => {
    const { container } = show({ ...leg, end_local: "2026-03-21T07:10" });
    expect(facts(container)[2]).toEqual(["Arrives", "7:10 AM+1 day"]);
    expect(container.querySelector("[data-shift]")).toHaveTextContent("+1 day");
    expect(facts(show(leg).container)[2]).toEqual(["Arrives", "1:20 PM"]);
  });

  it("opens a flight’s booking from its card, like every other kind", async () => {
    const onopen = vi.fn();
    show(leg, { onopen } as never);
    await userEvent.click(screen.getByRole("button", { name: /LIS/ }));
    expect(onopen).toHaveBeenCalledOnce();
  });

  it("names the booking, its kind and place, and that it is confirmed", () => {
    show(stay);
    const header = screen.getByRole("button", { name: /Hotel Example/ });
    expect(header).toHaveTextContent("Stay · Lisbon · Confirmed");
    expect(header).toHaveAttribute("aria-haspopup", "dialog");
  });

  it("says Changed in place of Confirmed, and keeps a cancelled booking greyed with struck facts", () => {
    const changed = render(BookingCard, { card: cardOf({ ...stay, status: "changed" }), now: NOW, onopen: vi.fn() });
    expect(changed.container.textContent).toContain("Changed");
    expect(changed.container.textContent).not.toContain("Confirmed");
    changed.unmount();
    const { container } = render(BookingCard, { card: cardOf({ ...lot, status: "cancelled" }), now: NOW, onopen: vi.fn() });
    expect(container.textContent).toContain("Cancelled");
    expect(container.querySelector("dd")?.className).toContain("line-through");
    expect(screen.queryByRole("button", { name: /Show code/ })).toBeNull();
  });
});

describe("BookingCard kind icon", () => {
  it.each([
    ["stay", stay, "text-kind-stay"],
    ["rental car", car, "text-kind-car"],
    ["train", train, "text-kind-train"],
    ["cruise", cruise, "text-kind-cruise"],
    ["parking", lot, "text-kind-parking"],
  ] as const)("draws the %s icon as a coloured outline with no tinted chip", (name, s, ink) => {
    show(s);
    const icon = screen.getByRole("img", { name });
    expect(icon.className).toContain(ink);
    expect(icon.className).not.toMatch(/bg-kind|rounded/);
  });
});

describe("BookingCard Show code", () => {
  it("is the one blue button on a booking with a QR code", () => {
    show(lot);
    const button = screen.getByRole("button", { name: "Show code for Bayside Park & Fly" });
    expect(button).toHaveTextContent("Show code");
    expect(button.className).toContain("bg-primary");
  });

  it.each([
    ["a stay", stay],
    ["a car", car],
    ["a train", train],
    ["a cruise", cruise],
    ["parking with no code", { ...lot, gate_code: null }],
    ["parking whose code still has to be chosen", { ...lot, gate_code: { state: "choose" as const, day: null } }],
  ] as const)("is not offered on %s", (_, s) => {
    show(s as typeof stay);
    expect(screen.queryByText("Show code")).toBeNull();
  });

  it("is not offered once the booking has ended", () => {
    show(lot, { now: Date.parse("2026-03-21T12:00:00Z") });
    expect(screen.queryByText("Show code")).toBeNull();
  });
});

describe("BookingCard keeps private details off the card", () => {
  it.each([["stay", stay], ["car", car], ["train", train], ["cruise", cruise], ["parking", lot]] as const)("has no confirmation code, cost, address or traveller on a %s", (_, s) => {
    const { container } = show({ ...s, details: { ...s.details, address: "1 Rua Example, Lisbon" }, travelers: [{ id: 1, person_id: 1, name: "Jane Doe", seat: "14A" }] });
    const markup = container.innerHTML;
    for (const secret of ["ZQ9X7K", "1,234", "1234", "Rua Example", "Jane", "14A", "Confirmation", "Cost", "Address"]) expect(markup).not.toContain(secret);
  });
});

describe("BookingCard tap", () => {
  it("opens the booking's detail from the header, at least 44 pixels tall", async () => {
    const onopen = vi.fn();
    const { container } = render(BookingCard, { card: cardOf(stay), now: NOW, onopen });
    const header = within(container).getByRole("button", { name: /Hotel Example/ });
    expect(header.className).toContain("min-h-16");
    await userEvent.click(header);
    expect(onopen).toHaveBeenCalledWith(stay, header);
  });
});
