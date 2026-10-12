// @vitest-environment jsdom
import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import type { Segment } from "$lib/api-types";
import { segment } from "../../test/fixtures";
import DayTime from "./DayTime.svelte";

const untimedOf = (kind: Segment["kind"], extra: Partial<Segment> = {}): Segment =>
  segment({ kind, start_local: "2005-03-10T00:00", end_local: "2005-03-29T00:00", details: { time_unknown: "yes" }, ...extra });

const text = (s: Segment, end = false, dated = false) => render(DayTime, { segment: s, end, dated }).container.textContent?.replace(/\s+/g, " ").trim();

describe("an untimed booking", () => {
  it.each(["flight", "hotel", "car", "train", "cruise", "parking"] as const)("shows the start and end day for a %s, each with time not recorded", (kind) => {
    const s = untimedOf(kind);
    expect(text(s, false)).toBe("Thu, Mar 10, 2005, time not recorded");
    expect(text(s, true)).toBe("Tue, Mar 29, 2005, time not recorded");
  });

  it("shows the year of a date in another year, and no year for a date in this year", () => {
    const thisYear = new Date().getFullYear();
    const here = untimedOf("hotel", { start_local: `${thisYear}-03-10T00:00`, end_local: `${thisYear}-03-11T00:00` });
    expect(text(here, false)).not.toMatch(/\b\d{4}\b/);
    expect(text(here, true)).not.toMatch(/\b\d{4}\b/);
  });

  it("shows one date for a same-day booking, with the end kept as same day", () => {
    const s = untimedOf("car", { end_local: "2005-03-10T00:00" });
    expect(text(s, false)).toBe("Thu, Mar 10, 2005, time not recorded");
    expect(text(s, true)).toBe("same day, time not recorded");
  });
});

describe("a past trip (country and dates only)", () => {
  it("shows its dates with the year, and no time not recorded", () => {
    const s = untimedOf("visit", { destination: "JP" });
    expect(text(s, false)).toBe("Thu, Mar 10, 2005");
    expect(text(s, true)).toBe("Tue, Mar 29, 2005");
  });

  it("shows the year even in the current year", () => {
    const thisYear = new Date().getFullYear();
    const s = untimedOf("visit", { destination: "JP", start_local: `${thisYear}-03-10T00:00`, end_local: `${thisYear}-03-29T00:00` });
    expect(text(s, false)).toMatch(new RegExp(`^\\w{3}, Mar 10, ${thisYear}$`));
  });

  it("shows Same day at the end when it starts and ends on one day", () => {
    const s = untimedOf("visit", { destination: "JP", end_local: "2005-03-10T00:00" });
    expect(text(s, false)).toBe("Thu, Mar 10, 2005");
    expect(text(s, true)).toBe("Same day");
  });
});

describe("a booking with times", () => {
  it("shows only the time, unless it is asked to show the day too", () => {
    const s = segment({ kind: "hotel", start_local: "2005-03-10T15:00", end_local: "2005-03-29T11:00", details: {} });
    expect(text(s, false)).toBe("3:00 PM");
    expect(text(s, true)).toBe("11:00 AM");
    expect(text(s, true, true)).toBe("Tue, Mar 29, 2005, 11:00 AM");
  });
});
