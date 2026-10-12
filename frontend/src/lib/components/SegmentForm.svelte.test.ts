// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { blank, type Draft, type Kind } from "$lib/segment-form";
import SegmentForm from "./SegmentForm.svelte";

const KINDS: Kind[] = ["flight", "hotel", "car", "train", "cruise", "parking"];
const REMOVED = [
  /Check-in and check-out are both at the hotel/,
  /Entry and exit are both at the lot/,
  /Leave this empty to work it out/,
];

const draft = (kind: Kind, extra: Partial<Draft> = {}): Draft => ({
  ...blank(1), kind, origin: "Harbour Hotel", start_local: "2026-12-02T15:00", end_local: "2026-12-05T11:00", people: [1], ...extra,
});

const mount = (initial: Draft, onsaved = vi.fn()) => render(SegmentForm, { props: { initial, people: [], onsaved, oncancel: vi.fn() } });

describe("SegmentForm: the explanatory text is gone", () => {
  it.each(KINDS)("the %s form shows none of the removed lines", (kind) => {
    mount(draft(kind));
    for (const text of REMOVED) expect(screen.queryByText(text)).toBeNull();
    for (const el of document.querySelectorAll("[aria-describedby]")) {
      for (const id of el.getAttribute("aria-describedby")!.split(" ")) expect(document.getElementById(id), `aria-describedby ${id}`).not.toBeNull();
    }
  });

  it.each(["hotel", "parking"] as const)("keeps the blank zone choice for a %s", (kind) => {
    mount(draft(kind));
    expect(screen.getByRole("option", { name: "Work it out from the address" })).toBeInTheDocument();
  });

  it("still says what to enter when a stay has neither a time zone nor an address", async () => {
    const onsaved = vi.fn();
    mount(draft("hotel"), onsaved);
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter the time zone of the stay");
    await waitFor(() => expect(onsaved).not.toHaveBeenCalled());
  });
});

describe("SegmentForm: the cost", () => {
  it("has an amount and a currency, filled from the booking, with a note when an email supplied it", () => {
    mount(draft("hotel", { id: 5, cost: "310.00", currency: "EUR", costSource: "email" }));
    expect(screen.getByLabelText("Cost amount")).toHaveValue("310.00");
    expect(screen.getByLabelText("Cost currency")).toHaveValue("EUR");
    expect(screen.getByText(/Read from an email\. Change it and your amount is kept/)).toBeInTheDocument();
  });
  it("says nothing about an email for a cost entered by hand or none, and starts in the given currency", () => {
    mount(draft("hotel", { currency: "GBP" }));
    expect(screen.getByLabelText("Cost amount")).toHaveValue("");
    expect(screen.getByLabelText("Cost currency")).toHaveValue("GBP");
    expect(screen.queryByText(/Read from an email/)).toBeNull();
  });
  it("refuses an amount it can't read, before saving", async () => {
    const onsaved = vi.fn();
    mount(draft("hotel", { start_zone: "Europe/London", cost: "abc" }), onsaved);
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter the cost as an amount like 1240.00");
    expect(onsaved).not.toHaveBeenCalled();
  });
});
