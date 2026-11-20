import { describe, expect, it } from "vitest";
import { segment } from "../test/fixtures";
import { journeyLegs } from "./journey";

const leg = (id: number, n: number, legs: number, extra = {}) =>
  segment({ id, journey: { lead: 1, leg: n, legs, previous: n > 1 ? id - 1 : null, next: n < legs ? id + 1 : null }, ...extra });

describe("the legs of a journey", () => {
  it("are the trip's segments in the order the server linked them", () => {
    const all = [segment({ id: 9 }), leg(3, 3, 3), leg(1, 1, 3), leg(2, 2, 3)];
    expect(journeyLegs(all[3], all)?.map((s) => s.id)).toEqual([1, 2, 3]);
    expect(journeyLegs(all[1], all)?.map((s) => s.id)).toEqual([1, 2, 3]);
  });

  it("are none for a segment the server did not link, or a copy saved before it did", () => {
    expect(journeyLegs(segment({ id: 1 }), [segment({ id: 1 })])).toBeNull();
    expect(journeyLegs(segment({ id: 1, journey: null }), [])).toBeNull();
  });

  it("are none when a leg of the journey is missing from the trip", () => {
    const all = [leg(1, 1, 3), leg(3, 3, 3)];
    expect(journeyLegs(all[0], all)).toBeNull();
  });

  it("are none when the legs disagree about their journey", () => {
    const all = [leg(1, 1, 2), leg(2, 2, 2, { journey: { lead: 7, leg: 2, legs: 2, previous: 1, next: null } })];
    expect(journeyLegs(all[0], all)).toBeNull();
  });
});
