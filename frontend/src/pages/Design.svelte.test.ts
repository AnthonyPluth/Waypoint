// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import { navFor, pageFor } from "$lib/nav";
import Design from "./Design.svelte";

describe("Design", () => {
  it("shows every booking and live chip", () => {
    render(Design);
    for (const word of ["Confirmed", "Changed", "Cancelled", "On time", "Delayed 25 min", "Departed", "Landed", "Diverted"]) {
      expect(screen.getByText(word)).toBeTruthy();
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
  it("is reachable at #design, under Settings in the navigation", () => {
    expect(pageFor("design")).toBe("design");
    expect(navFor("design")).toBe("settings");
  });
});
