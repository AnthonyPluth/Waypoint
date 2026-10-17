import { describe, expect, it } from "vitest";
import { segment, trip } from "../test/fixtures";
import { laterTrips, tripCities, usablePlaces } from "./side-column";

const rental = (origin: string, destination: string) =>
  segment({ id: 1, kind: "car", origin, destination, start_local: "2026-11-20T10:00", end_local: "2026-11-24T10:00" });

describe("tripCities", () => {
  it("counts both the pick-up and the drop-off city of a one-way rental", () => {
    expect(tripCities(trip([rental("Boston", "Chicago")]))).toBe(2);
  });

  it("counts a round-trip rental’s city once", () => {
    expect(tripCities(trip([rental("Boston", "Boston")]))).toBe(1);
  });

  it("counts a rental with only one end known", () => {
    expect(tripCities(trip([rental("Boston", null as never)]))).toBe(1);
  });
});

describe("laterTrips", () => {
  const dated = (id: number, start: string, end: string) => trip([segment({ id, trip_id: id })], { id, start_date: start, end_date: end });

  it("leaves out trips that began before today", () => {
    const featured = dated(1, "2026-11-20", "2026-11-27");
    const began = dated(2, "2026-11-10", "2026-11-25");
    const coming = dated(3, "2026-12-30", "2027-01-03");
    expect(laterTrips([began, featured, coming], featured, "2026-11-20").map((t) => t.id)).toEqual([3]);
  });
  it("lists every trip that has not started, soonest first, with no cap", () => {
    const featured = dated(1, "2026-11-20", "2026-11-27");
    const rest = [2, 3, 4, 5, 6, 7].map((id) => dated(id, `2026-12-${String(id).padStart(2, "0")}`, `2026-12-${String(id + 1).padStart(2, "0")}`));
    expect(laterTrips([featured, ...rest], featured, "2026-11-20").map((t) => t.id)).toEqual([2, 3, 4, 5, 6, 7]);
  });
});

describe("usablePlaces", () => {
  const whole = { home: null, airports: [], cities: [], stays: [], roads: { legs: [], interstates: [] }, boundaries: [] };

  it("accepts a reply with every collection", () => {
    expect(usablePlaces(whole)).toBe(true);
  });

  it("rejects a reply missing any collection, or not an object", () => {
    expect(usablePlaces({ ...whole, stays: undefined })).toBe(false);
    expect(usablePlaces({ ...whole, roads: undefined })).toBe(false);
    expect(usablePlaces({ ...whole, boundaries: null })).toBe(false);
    expect(usablePlaces(null)).toBe(false);
    expect(usablePlaces("nope")).toBe(false);
  });
});
