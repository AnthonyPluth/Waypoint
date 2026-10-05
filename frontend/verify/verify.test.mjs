import { describe, expect, it } from "vitest";
import { findChromium, flowProblems, PAGES, screenshotFiles, unknownPages } from "./verify.mjs";

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

  it("takes a file to upload and an element to scroll to", () => {
    const steps = [{ upload: { selector: "input[type=file]", file: "tests/fixtures/flight_import/flighty.csv" } }, { scroll_to: "#import-title" }];
    expect(flowProblems({ ...ok, steps })).toEqual([]);
    expect(flowProblems({ ...ok, steps: [{ upload: "x" }] })).toEqual(["step 1: upload takes a object"]);
  });

  it("rejects a viewport it doesn't know", () => expect(flowProblems({ ...ok, viewports: ["watch"] })).toEqual(["unknown viewport watch"]));

  it("rejects a page the app doesn't have, so a typo can't pass for a clean run", () => {
    expect(flowProblems({ ...ok, page: "setings" })).toEqual(["unknown page setings"]);
    expect(unknownPages(["upcoming", "setings"])).toEqual(["setings"]);
    expect(unknownPages(PAGES)).toEqual([]);
  });

  it("has the app's pages", () => expect(PAGES).toEqual(["upcoming", "trips", "people", "review", "stats", "settings"]));
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
