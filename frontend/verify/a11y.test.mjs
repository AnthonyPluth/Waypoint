import { describe, expect, it } from "vitest";
import { axeProblems, focusProblems, MIN_TAP, tapProblems } from "./a11y.mjs";

describe("axeProblems", () => {
  it("names each failing element with its rule", () => {
    const violations = [{ id: "color-contrast", help: "Elements must meet contrast", nodes: [{ target: ["p.muted"] }, { target: ["iframe", "span"] }] }];
    expect(axeProblems(violations)).toEqual(["color-contrast: p.muted (Elements must meet contrast)", "color-contrast: iframe span (Elements must meet contrast)"]);
    expect(axeProblems([])).toEqual([]);
  });
});

describe("tapProblems", () => {
  const boxes = [{ target: "button A", width: MIN_TAP, height: MIN_TAP }, { target: "button B", width: 32, height: 44 }, { target: "a C", width: 100, height: 20.4 }];
  it("flags targets under 44 px on the phone only", () => {
    expect(tapProblems(boxes, "phone")).toEqual([`tap-target: button B is 32×44 px, under ${MIN_TAP}`, `tap-target: a C is 100×20 px, under ${MIN_TAP}`]);
    expect(tapProblems(boxes, "tablet")).toEqual([]);
    expect(tapProblems(boxes, "desktop")).toEqual([]);
  });
});

describe("focusProblems", () => {
  it("flags a stop with no ring", () => {
    expect(focusProblems([{ target: "a X", ringed: true }, { target: "g Y", ringed: false }])).toEqual(["focus: g Y shows no focus ring"]);
  });
});
