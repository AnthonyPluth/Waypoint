// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import { tick } from "svelte";
import { describe, expect, it } from "vitest";
import type { Tone } from "$lib/status";
import StatusChip from "./StatusChip.svelte";

describe("StatusChip", () => {
  it("shows the word and the tone's colours, so colour is never the only signal", () => {
    render(StatusChip, { chip: { label: "Delayed 25 min", tone: "warn" } });
    const chip = screen.getByText("Delayed 25 min");
    expect(chip.dataset.tone).toBe("warn");
    expect(chip.className).toContain("bg-status-warn-soft");
    expect(chip.className).toContain("text-status-warn-ink");
  });
  it("has colours for each tone", () => {
    for (const tone of ["ok", "warn", "bad", "info", "quiet"] as Tone[]) {
      const { unmount } = render(StatusChip, { chip: { label: tone, tone } });
      expect(screen.getByText(tone).className).toContain(`bg-status-${tone}-soft text-status-${tone}-ink`);
      unmount();
    }
  });
  it("is smaller as a secondary chip", () => {
    const { unmount } = render(StatusChip, { chip: { label: "On time", tone: "info" } });
    expect(screen.getByText("On time").className).toContain("text-xs");
    unmount();
    render(StatusChip, { chip: { label: "On time", tone: "info" }, small: true });
    expect(screen.getByText("On time").className).toContain("text-[11px]");
  });
  it("hides its dot from screen readers", () => {
    render(StatusChip, { chip: { label: "Confirmed", tone: "ok" } });
    expect(screen.getByText("Confirmed").querySelector("[aria-hidden='true']")).not.toBeNull();
  });
});

describe("StatusChip motion", () => {
  it("animates when its label changes, not when it first appears", async () => {
    const { rerender } = render(StatusChip, { chip: { label: "On time", tone: "ok" } });
    expect(screen.getByText("On time").classList.contains("status-chip")).toBe(false);
    await rerender({ chip: { label: "Delayed", tone: "warn" } });
    await tick();
    expect(screen.getByText("Delayed").classList.contains("status-chip")).toBe(true);
  });
});
