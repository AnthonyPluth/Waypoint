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

describe("SegmentForm: who is travelling", () => {
  const withPeople = (initial: Draft) => render(SegmentForm, { props: { initial, people: [{ id: 1, display_name: "Jane Doe" }, { id: 2, display_name: "Sam Doe" }] as never, onsaved: vi.fn(), oncancel: vi.fn() } });

  it.each(["hotel", "car", "parking"] as const)("asks nobody for a %s", (kind) => {
    withPeople(draft(kind));
    expect(screen.queryByText("Who’s travelling")).toBeNull();
    expect(screen.queryByLabelText("Sam Doe")).toBeNull();
  });

  it.each(["flight", "cruise", "train"] as const)("lets you choose who is on a %s", (kind) => {
    withPeople(draft(kind));
    expect(screen.getByText("Who’s travelling")).toBeInTheDocument();
    expect(screen.getByLabelText("Sam Doe")).toBeInTheDocument();
  });

  it("shows the choice again when the booking is changed from a stay to a flight", async () => {
    withPeople(draft("hotel"));
    expect(screen.queryByLabelText("Sam Doe")).toBeNull();
    await userEvent.selectOptions(screen.getByLabelText("What is it"), "Flight");
    expect(screen.getByLabelText("Sam Doe")).toBeInTheDocument();
  });
});

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
