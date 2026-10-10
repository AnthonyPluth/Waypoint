// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import PlaceTime from "./PlaceTime.svelte";

describe("PlaceTime", () => {
  it("shows the time at the place, and the same moment in the viewer's zone small and muted beside it", () => {
    render(PlaceTime, { local: "2026-10-08T19:00", zone: "America/New_York", mine: "UTC" });
    expect(screen.getByText("7:00 PM")).toBeInTheDocument();
    const yours = screen.getByTitle("The same moment in your time zone");
    expect(yours).toHaveTextContent("[11:00 PM UTC]");
    expect(yours.className).toContain("text-xs");
    expect(yours.className).toContain("text-muted-foreground");
  });

  it("shows nothing extra when the viewer is in the same zone", () => {
    render(PlaceTime, { local: "2026-10-08T19:00", zone: "America/New_York", mine: "America/New_York" });
    expect(screen.getByText("7:00 PM")).toBeInTheDocument();
    expect(screen.queryByTitle("The same moment in your time zone")).toBeNull();
  });
});
