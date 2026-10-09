import { describe, expect, it } from "vitest";
import { bookingChip, liveChip, segmentChips } from "./status";

describe("bookingChip", () => {
  it("says confirmed, changed and cancelled, each in its own tone", () => {
    expect(bookingChip("confirmed")).toEqual({ label: "Confirmed", tone: "ok" });
    expect(bookingChip("changed")).toEqual({ label: "Changed", tone: "warn" });
    expect(bookingChip("cancelled")).toEqual({ label: "Cancelled", tone: "bad" });
  });
});

describe("liveChip", () => {
  it("covers every state live flight status can report", () => {
    expect(liveChip({ state: "scheduled", delay_minutes: null })).toEqual({ label: "On time", tone: "info" });
    expect(liveChip({ state: "departed", delay_minutes: null })).toEqual({ label: "Departed", tone: "info" });
    expect(liveChip({ state: "landed", delay_minutes: null })).toEqual({ label: "Landed", tone: "quiet" });
    expect(liveChip({ state: "cancelled", delay_minutes: null })).toEqual({ label: "Cancelled", tone: "bad" });
    expect(liveChip({ state: "diverted", delay_minutes: null })).toEqual({ label: "Diverted", tone: "bad" });
  });
  it("puts the minutes in a delay, and says plain Delayed without them", () => {
    expect(liveChip({ state: "delayed", delay_minutes: 25 })).toEqual({ label: "Delayed 25 min", tone: "warn" });
    expect(liveChip({ state: "delayed", delay_minutes: null })).toEqual({ label: "Delayed", tone: "warn" });
    expect(liveChip({ state: "delayed", delay_minutes: 0 })).toEqual({ label: "Delayed", tone: "warn" });
  });
  it("only shows minutes for a delay", () => {
    expect(liveChip({ state: "scheduled", delay_minutes: 10 }).label).toBe("On time");
  });
});

describe("segmentChips", () => {
  const flight = { state: "delayed", delay_minutes: 25 } as const;
  it("shows the live chip after the booking chip when live status is on", () => {
    expect(segmentChips("confirmed", flight, true)).toEqual({
      booking: { label: "Confirmed", tone: "ok" },
      live: { label: "Delayed 25 min", tone: "warn" },
    });
  });
  it("has no live chip when live status is off, whatever the flight says", () => {
    expect(segmentChips("confirmed", flight, false).live).toBeNull();
    expect(segmentChips("cancelled", flight, false).booking).toEqual({ label: "Cancelled", tone: "bad" });
  });
  it("has no live chip when there is no flight status", () => {
    expect(segmentChips("changed", null, true).live).toBeNull();
    expect(segmentChips("changed", undefined, true).live).toBeNull();
  });
});
