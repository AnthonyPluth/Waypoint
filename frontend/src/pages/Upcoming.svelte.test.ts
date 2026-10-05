// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import Upcoming from "./Upcoming.svelte";

describe("Upcoming", () => {
  it("says there are no trips yet, without making any up", () => {
    render(Upcoming);
    expect(screen.getByRole("heading", { name: "Upcoming" })).toBeInTheDocument();
    expect(screen.getByText(/No trips yet — they’ll appear here once Waypoint can read your confirmation emails, or when you add one\./)).toBeInTheDocument();
  });
});
