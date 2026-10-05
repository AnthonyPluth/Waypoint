import { describe, expect, it } from "vitest";
import { comparisons, count, countryName, distance, duration, monthLabel, parseSelection, selectionQuery, share, statsPath } from "./stats";

describe("formatting", () => {
  it("writes large numbers with separators", () => {
    expect(count(0)).toBe("0");
    expect(count(1234567.4)).toBe("1,234,567");
  });

  it("converts the server's kilometres to the household's unit", () => {
    expect(distance(1609.344, "mi")).toBe("1,000 mi");
    expect(distance(12459.4, "km")).toBe("12,459 km");
    expect(distance(0, "mi")).toBe("0 mi");
  });

  it("writes time in the air as days, hours and minutes, leaving out zeros", () => {
    expect(duration(3 * 86400 + 4 * 3600)).toBe("3 d 4 h");
    expect(duration(3 * 86400)).toBe("3 d");
    expect(duration(5 * 3600 + 20 * 60)).toBe("5 h 20 min");
    expect(duration(2 * 3600)).toBe("2 h");
    expect(duration(45 * 60 + 20)).toBe("45 min");
    expect(duration(0)).toBe("0 min");
    expect(duration(-5)).toBe("0 min");
    expect(duration(86400 + 29)).toBe("1 d");   // rounds to the minute first
  });

  it("names a month and a country", () => {
    expect(monthLabel("2026-06")).toBe("June 2026");
    expect(countryName("NZ")).toBe("New Zealand");
    expect(countryName("not a code")).toBe("not a code");
  });

  it("works out a share, and 0% of nothing", () => {
    expect(share(1, 3)).toBe(33);
    expect(share(0, 0)).toBe(0);
  });
});

describe("comparisons", () => {
  it("compares the distance to the Earth's girth and the way to the Moon", () => {
    expect(comparisons({ times_around_earth: 1.3, moon_fraction: 0.1355 })).toEqual(["1.3× around the Earth", "14% of the way to the Moon"]);
    expect(comparisons({ times_around_earth: 0.04, moon_fraction: 0.0042 })).toEqual(["Under 1% of the way to the Moon"]);
    expect(comparisons({ times_around_earth: 38.4, moon_fraction: 4 })).toEqual(["38.4× around the Earth", "4.0× the distance to the Moon"]);
  });

  it("says nothing when nothing was flown a distance", () => {
    expect(comparisons({ times_around_earth: 0, moon_fraction: 0 })).toEqual([]);
  });
});

describe("the pickers' choice in the address", () => {
  it("leaves your own numbers and all time unmarked", () => {
    expect(selectionQuery({ who: 7, year: null }, 7)).toBe("");
    expect(parseSelection("", 7)).toEqual({ who: 7, year: null });
  });

  it("round-trips anyone, everyone and a year", () => {
    for (const sel of [{ who: 3, year: 2025 }, { who: "all" as const, year: null }, { who: "all" as const, year: 2024 }, { who: 7, year: 2026 }]) {
      expect(parseSelection(selectionQuery(sel, 7), 7)).toEqual(sel);
    }
    expect(selectionQuery({ who: 3, year: 2025 }, 7)).toBe("who=3&year=2025");
    expect(selectionQuery({ who: "all", year: null }, 7)).toBe("who=all");
  });

  it("opens on everyone without a person of your own (your own machine)", () => {
    expect(parseSelection("", null)).toEqual({ who: "all", year: null });
    expect(selectionQuery({ who: "all", year: 2025 }, null)).toBe("year=2025");
  });

  it("takes what isn't a person or a year as the default", () => {
    expect(parseSelection("who=jane&year=last", 7)).toEqual({ who: 7, year: null });
    expect(parseSelection("who=1e3&year=20", 7)).toEqual({ who: 7, year: null });
    expect(parseSelection("who=&year=", null)).toEqual({ who: "all", year: null });
  });

  it("asks the server for the choice", () => {
    expect(statsPath({ who: 3, year: 2025 })).toBe("/api/stats?person=3&year=2025");
    expect(statsPath({ who: "all", year: null })).toBe("/api/stats?person=all&year=all");
  });
});
