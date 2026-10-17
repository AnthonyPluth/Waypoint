import { describe, expect, it } from "vitest";
import { blankTrip, TRIP_NAME_LIMIT, tripBody, tripIssues } from "./quick-trip";

const draft = (extra: Partial<ReturnType<typeof blankTrip>> = {}) => ({ ...blankTrip(), name: "Lisbon", ...extra });
const messages = (d: ReturnType<typeof blankTrip>) => tripIssues(d).map((i) => `${i.field}: ${i.message}`);

describe("the quick trip's messages", () => {
  it("needs only a name", () => {
    expect(tripIssues(draft())).toEqual([]);
  });

  it("wants a name that is not blank and not too long", () => {
    expect(messages(draft({ name: "  " }))).toEqual(["name: Enter where you’re going, or a name for the trip"]);
    expect(messages(draft({ name: "x".repeat(TRIP_NAME_LIMIT + 1) }))).toEqual([`name: The name can be at most ${TRIP_NAME_LIMIT} characters`]);
    expect(tripIssues(draft({ name: "x".repeat(TRIP_NAME_LIMIT) }))).toEqual([]);
  });

  it("accepts both days, or only the first", () => {
    expect(tripIssues(draft({ start: "2026-12-01", end: "2026-12-08" }))).toEqual([]);
    expect(tripIssues(draft({ start: "2026-12-01", end: "2026-12-01" }))).toEqual([]);
    expect(tripIssues(draft({ start: "2026-12-01" }))).toEqual([]);
  });

  it("refuses a last day with no first day, and a last day before the first", () => {
    expect(messages(draft({ end: "2026-12-08" }))).toEqual(["start: Enter the first day, or clear the last day"]);
    expect(messages(draft({ start: "2026-12-08", end: "2026-12-01" }))).toEqual(["end: The last day can’t be before the first"]);
  });

  it("refuses a day that is not a date", () => {
    expect(messages(draft({ start: "2026-12", end: "soon" }))).toEqual(["start: Enter the first day as a date", "end: Enter the last day as a date"]);
  });
});

describe("the quick trip's request", () => {
  it("sends the name alone for an undated trip", () => {
    expect(tripBody(draft({ name: " Lisbon " }), null)).toEqual({ name: "Lisbon" });
  });

  it("sends both days, the last defaulting to the first", () => {
    expect(tripBody(draft({ start: "2026-12-01", end: "2026-12-08" }), null)).toEqual({ name: "Lisbon", start_date: "2026-12-01", end_date: "2026-12-08" });
    expect(tripBody(draft({ start: "2026-12-01" }), null)).toEqual({ name: "Lisbon", start_date: "2026-12-01", end_date: "2026-12-01" });
  });

  it("puts only the signed-in person on the trip", () => {
    expect(tripBody(draft(), 3)).toEqual({ name: "Lisbon", people: [3] });
  });
});
