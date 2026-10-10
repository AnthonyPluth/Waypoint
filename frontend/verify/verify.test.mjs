import { describe, expect, it } from "vitest";
import { findChromium, flowProblems, lengthenNames, PAGES, screenshotFiles, unknownPages } from "./verify.mjs";

describe("lengthenNames", () => {
  it("adds the suffix to the names a list shows, at any depth, and leaves the rest of the reply as it was", () => {
    const reply = { year: null, flights: { airlines: [{ code: "DL", name: "Delta", flights: 7 }] }, stays: { hotels: [{ name: "Quay", stays: 1 }],
      longest: { hotel: "Harbour", city: "London", nights: 4, start_local: "2026-06-02T15:00" } }, places: { countries: [{ name: "US", visits: 3 }] } };
    expect(lengthenNames(reply, " (long)")).toEqual({ year: null, flights: { airlines: [{ code: "DL", name: "Delta (long)", flights: 7 }] },
      stays: { hotels: [{ name: "Quay (long)", stays: 1 }], longest: { hotel: "Harbour (long)", city: "London (long)", nights: 4, start_local: "2026-06-02T15:00" } },
      places: { countries: [{ name: "US (long)", visits: 3 }] } });
  });

  it("leaves codes, numbers and nulls alone", () => {
    expect(lengthenNames({ code: "JFK", longest: null, count: 2 }, "!")).toEqual({ code: "JFK", longest: null, count: 2 });
    expect(lengthenNames([], "!")).toEqual([]);
  });
});

describe("flowProblems", () => {
  const ok = { name: "open-settings", page: "upcoming", steps: [{ goto: "#settings" }, { click: "text=Settings", timeout: 500 }] };

  it("accepts a well formed flow", () => expect(flowProblems(ok)).toEqual([]));

  it("names what is wrong, step by step", () => {
    expect(flowProblems({ steps: [] })).toEqual(["needs a name of letters, digits, - or _", "needs a list of steps"]);
    const bad = flowProblems({ ...ok, steps: [{ click: "a", goto: "#b" }, { fill: "text" }, { hover: "x" }] });
    expect(bad).toHaveLength(3);
    expect(bad[0]).toMatch(/step 1 must have exactly one of/);
    expect(bad[1]).toBe("step 2: fill takes a object");
    expect(bad[2]).toMatch(/step 3 must have exactly one of/);
  });

  it("needs a selector and a file name for a download", () => {
    expect(flowProblems({ ...ok, steps: [{ download: { selector: "button", name: "saved-image" } }] })).toEqual([]);
    expect(flowProblems({ ...ok, steps: [{ download: { selector: "button" } }] })).toEqual(["step 1: download needs a selector and a name of letters, digits, - or _"]);
    expect(flowProblems({ ...ok, steps: [{ download: { name: "saved-image" } }] })).toEqual(["step 1: download needs a selector and a name of letters, digits, - or _"]);
    expect(flowProblems({ ...ok, steps: [{ download: { selector: "button", name: "../x" } }] })).toHaveLength(1);
  });

  it("takes an option to select by its position", () => {
    expect(flowProblems({ ...ok, steps: [{ select: { selector: "select", index: 2 } }] })).toEqual([]);
    expect(flowProblems({ ...ok, steps: [{ select: "x" }] })).toEqual(["step 1: select takes a object"]);
  });

  it("takes a file to upload and an element to scroll to", () => {
    const steps = [{ upload: { selector: "input[type=file]", file: "tests/fixtures/flight_import/flighty.csv" } }, { scroll_to: "#import-title" }];
    expect(flowProblems({ ...ok, steps })).toEqual([]);
    expect(flowProblems({ ...ok, steps: [{ upload: "x" }] })).toEqual(["step 1: upload takes a object"]);
  });

  it("takes a suffix for the names of a list, to check a long one's layout", () => {
    expect(flowProblems({ ...ok, steps: [{ long_names: ", a long name" }] })).toEqual([]);
    expect(flowProblems({ ...ok, steps: [{ long_names: 3 }] })).toEqual(["step 1: long_names takes a string"]);
  });

  it("takes a download to click and save, named", () => {
    expect(flowProblems({ ...ok, steps: [{ download: { selector: "button", name: "saved-image" } }] })).toEqual([]);
    expect(flowProblems({ ...ok, steps: [{ download: "x" }] })).toEqual(["step 1: download takes a object"]);
  });

  it("rejects a viewport it doesn't know", () => expect(flowProblems({ ...ok, viewports: ["watch"] })).toEqual(["unknown viewport watch"]));

  it("rejects a page the app doesn't have, so a typo can't pass for a clean run", () => {
    expect(flowProblems({ ...ok, page: "setings" })).toEqual(["unknown page setings"]);
    expect(unknownPages(["upcoming", "setings"])).toEqual(["setings"]);
    expect(unknownPages(PAGES)).toEqual([]);
  });

  it("rejects a scheme: the app is dark only", () => {
    expect(flowProblems({ ...ok, scheme: "dark" })).toEqual(["scheme is not an option: the app is dark only"]);
    expect(flowProblems(ok)).toEqual([]);
  });

  it("has the app's pages", () => expect(PAGES).toEqual(["upcoming", "trips", "stats", "people", "review", "settings", "design", "oauth-approve"]));
});

describe("screenshotFiles", () => {
  it("names the full-page file as before and a viewport-only one beside it", () => {
    expect(screenshotFiles("upcoming", "phone")).toEqual({ full: "upcoming-phone.png", top: "upcoming-phone-top.png" });
    expect(screenshotFiles("flow-open-settings-settings-open", "desktop").top).toBe("flow-open-settings-settings-open-desktop-top.png");
  });
});

describe("findChromium", () => {
  const tree = (files) => ({ exists: (p) => files.some((f) => f === p || f.startsWith(`${p}/`)), list: () => ["ffmpeg-1011", "chromium-1194", "chromium-1200"] });

  it("uses the newest preinstalled Chromium, wherever its folder is", () => {
    const { exists, list } = tree(["/opt/pw-browsers/chromium-1194/chrome-linux/chrome"]);
    expect(findChromium({}, exists, list)).toBe("/opt/pw-browsers/chromium-1194/chrome-linux/chrome");
    const both = tree(["/opt/pw-browsers/chromium-1194/chrome-linux/chrome", "/opt/pw-browsers/chromium-1200/chrome-linux64/chrome"]);
    expect(findChromium({}, both.exists, both.list)).toBe("/opt/pw-browsers/chromium-1200/chrome-linux64/chrome");
  });

  it("follows PLAYWRIGHT_BROWSERS_PATH, and leaves it to Playwright when there is no Chromium", () => {
    const { exists, list } = tree(["/x/chromium-1194/chrome-linux/chrome"]);
    expect(findChromium({ PLAYWRIGHT_BROWSERS_PATH: "/x" }, exists, list)).toBe("/x/chromium-1194/chrome-linux/chrome");
    expect(findChromium({ PLAYWRIGHT_BROWSERS_PATH: "/nowhere" }, exists, list)).toBeUndefined();
  });
});
