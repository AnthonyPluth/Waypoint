// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import { navFor, pageFor } from "$lib/nav";
import Design from "./Design.svelte";

describe("Design", () => {
  it("shows every booking and live chip", () => {
    render(Design);
    const status = screen.getByRole("heading", { name: "Status" }).closest("section") as HTMLElement;
    for (const word of ["Confirmed", "Changed", "Cancelled", "On time", "Delayed 25 min", "Departed", "Landed", "Diverted"]) {
      expect(within(status).getByText(word)).toBeTruthy();
    }
  });
  it("names the airports and places the plane at the start, along the way and at the end", () => {
    render(Design);
    expect(screen.getByText("MSP", { selector: "abbr" }).getAttribute("title")).toBe("Minneapolis–Saint Paul");
    const route = screen.getByRole("heading", { name: "Route line" }).closest("section") as HTMLElement;
    const lines = within(route).getAllByRole("img");
    expect(lines.map((l) => l.dataset.progress)).toEqual(["0", "0.55", "1"]);
    expect(lines[1].getAttribute("aria-label")).toBe("Under way, based on the booked times");
  });
  it("shows the pass card for a flight before and during the flight, and for a stay", () => {
    render(Design);
    const pass = screen.getByRole("heading", { name: "Pass card" }).closest("section") as HTMLElement;
    expect(within(pass).getByText("Check-in is open, departs in 3 h")).toBeTruthy();
    expect(within(pass).getByText("Under way, arrives in 2 h 45 min")).toBeTruthy();
    expect(within(pass).getByText("Check-in in 7 h")).toBeTruthy();
  });
  it("shows every kind tile and avatar stacks of one, three and six people", () => {
    render(Design);
    const kinds = screen.getByRole("heading", { name: "Kind tiles" }).closest("section") as HTMLElement;
    expect(within(kinds).getAllByRole("img", { name: "past visit" })).toHaveLength(2);
    expect(within(kinds).getAllByRole("img")).toHaveLength(14);
    const people = screen.getByRole("heading", { name: "Avatar stack" }).closest("section") as HTMLElement;
    expect(within(people).getAllByTestId("avatar-stack").map((s) => s.getAttribute("aria-label")?.split(", ").length)).toEqual([1, 3, 6]);
    expect(within(people).getByText("+2")).toBeTruthy();
  });
  it("is reachable at #design, under Settings in the navigation", () => {
    expect(pageFor("design")).toBe("design");
    expect(navFor("design")).toBe("settings");
  });
});
