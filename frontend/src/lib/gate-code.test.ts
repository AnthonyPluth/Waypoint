import { describe, expect, it } from "vitest";
import { MARGIN, SHARE, squareSide } from "./gate-code";

describe("squareSide", () => {
  it("leaves a margin of at least four modules on each side of even the smallest code", () => {
    expect(((1 - SHARE) / 2 / SHARE) * 21).toBeGreaterThanOrEqual(4);
    expect(MARGIN).toBe(0.2);
  });

  it("uses the whole room until the picture is known", () => {
    expect(squareSide(400, 0)).toBe(400);
    expect(squareSide(0, 290)).toBe(0);
  });

  it("uses the whole room when the picture is bigger than the room allows", () => {
    expect(squareSide(366, 290)).toBe(366);
  });

  it("shows whole pixels when that costs little", () => {
    expect(squareSide(840, 290)).toBeCloseTo((290 * 2) / SHARE, 5);
    expect(squareSide(420, 100)).toBeCloseTo(300 / SHARE, 5);
  });

  it("uses the whole room rather than waste a lot of it on whole pixels", () => {
    expect(squareSide(568, 290)).toBe(568);
  });
});
