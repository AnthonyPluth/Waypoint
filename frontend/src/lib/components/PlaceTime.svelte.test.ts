// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import PlaceTime from "./PlaceTime.svelte";

describe("PlaceTime", () => {
  it("shows only the time at the place, as a time element carrying the local time", () => {
    const { container } = render(PlaceTime, { local: "2026-10-08T19:00" });
    expect(screen.getByText("7:00 PM")).toBeInTheDocument();
    expect(container.querySelector("time")?.getAttribute("datetime")).toBe("2026-10-08T19:00");
    expect(container).not.toHaveTextContent("[");
    expect(screen.queryByTitle("The same moment in your time zone")).toBeNull();
  });
});
