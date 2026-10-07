// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import StatusChip, { chipLabel, chipSurface, type ChipStatus } from "./StatusChip.svelte";

const BOOKING: ChipStatus[] = ["confirmed", "changed", "cancelled"];
const LIVE: ChipStatus[] = ["scheduled", "delayed", "departed", "landed", "cancelled", "diverted"];
const WORD_SURFACE: Record<ChipStatus, [string, string]> = {
  confirmed: ["Confirmed", "bg-confirmed-soft text-confirmed-ink"],
  changed: ["Changed", "bg-changed-soft text-changed-ink"],
  cancelled: ["Cancelled", "bg-cancelled-soft text-cancelled-ink"],
  scheduled: ["On time", "bg-ontime-soft text-ontime-ink"],
  delayed: ["Delayed 50 min", "bg-delayed-soft text-delayed-ink"],
  departed: ["Departed", "bg-airborne-soft text-airborne-ink"],
  landed: ["Landed", "bg-airborne-soft text-airborne-ink"],
  diverted: ["Diverted", "bg-diverted-soft text-diverted-ink"],
};

describe("the status chip", () => {
  it("has a chip for every booking status and every state live flight status can be in", () => {
    expect([...new Set([...BOOKING, ...LIVE])].sort()).toEqual(Object.keys(WORD_SURFACE).sort());
  });

  it("says the booking’s status in one word, in its own colour, at the size a booking leads with", () => {
    for (const status of BOOKING) {
      const [word, surface] = WORD_SURFACE[status];
      const { unmount } = render(StatusChip, { status });
      const chip = screen.getByTestId("status-chip");
      expect(chip).toHaveTextContent(word);
      expect(chip.className).toContain(surface);
      expect(chip.getAttribute("data-kind")).toBe("booking");
      expect(chip.className).toContain("text-sm");
      unmount();
    }
  });

  it("says every live state, smaller and secondary, with the delay in minutes", () => {
    for (const status of LIVE) {
      const [word, surface] = WORD_SURFACE[status];
      const { unmount } = render(StatusChip, { status, kind: "live", delay: status === "delayed" ? 50 : null });
      const chip = screen.getByTestId("status-chip");
      expect(chip).toHaveTextContent(word);
      expect(chip.className).toContain(surface);
      expect(chip.getAttribute("data-kind")).toBe("live");
      expect(chip.className).toContain("text-xs");
      unmount();
    }
  });

  it("says only Delayed when the delay is unknown", () => {
    expect(chipLabel("delayed")).toBe("Delayed");
    expect(chipLabel("delayed", 0)).toBe("Delayed");
    expect(chipLabel("delayed", 12)).toBe("Delayed 12 min");
    expect(chipLabel("landed")).toBe("Landed");
  });
});

describe("chip colours", () => {
  const channel = (c: number) => { const s = c / 255; return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; };
  const light = (hex: string) => {
    const n = parseInt(hex.slice(1), 16);
    return 0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255);
  };
  const contrast = (a: string, b: string) => { const [hi, lo] = [light(a), light(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05); };

  it("keeps every chip’s text at WCAG AA against its background", () => {
    const css = readFileSync("src/app.css", "utf8");
    const token = (name: string) => {
      const found = css.match(new RegExp(`--${name}:\\s*(#[0-9a-f]{6})`, "i"))?.[1];
      if (!found) throw new Error(`app.css has no --${name}`);
      return found;
    };
    for (const status of Object.keys(WORD_SURFACE) as ChipStatus[]) {
      const surface = chipSurface(status);
      const tone = surface.match(/bg-([a-z]+)-soft/)?.[1];
      const ink = surface.match(/text-([a-z]+)-ink/)?.[1];
      expect(tone, status).toBeTruthy();
      expect(ink, status).toBe(tone);
      expect(contrast(token(`${tone}-ink`), token(`${tone}-soft`)), `${status} chip`).toBeGreaterThanOrEqual(4.5);
    }
  });
});
