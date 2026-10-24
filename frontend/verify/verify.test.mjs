import { afterAll, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { CHROMIUM_ARGS, checksAfter, contextOptions, DEFAULT_VIEWPORTS, fakeArchive, findChromium, flowProblems, FROZEN_NOW, heroFile, IMAGE_VIEWPORTS, launchOptions, lengthenNames, localBase, OFFLINE_SAVED, PAGES, PHONE_AGENT, readFlows, recheck, screenshotFile, unknownPages, VIEWPORTS, VIRTUAL_AUTHENTICATOR, writesImage } from "./verify.mjs";

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
    const bad = flowProblems({ ...ok, steps: [{ click: "a", goto: "#b" }, { fill: "text" }, { drag: "x" }] });
    expect(bad).toHaveLength(3);
    expect(bad[0]).toMatch(/step 1 must have exactly one of/);
    expect(bad[1]).toBe("step 2: fill takes a object");
    expect(bad[2]).toMatch(/step 3 must have exactly one of/);
  });

  it("takes a click that only happens when the element shows up", () => {
    expect(flowProblems({ ...ok, steps: [{ click_if_present: "text=Settings", timeout: 500 }] })).toEqual([]);
    expect(flowProblems({ ...ok, steps: [{ click_if_present: { selector: "a" } }] })).toEqual(["step 1: click_if_present takes a string"]);
  });

  it("takes a selector to hover", () => {
    expect(flowProblems({ ...ok, steps: [{ hover: "li.row" }] })).toEqual([]);
    expect(flowProblems({ ...ok, steps: [{ hover: true }] })).toEqual(["step 1: hover takes a string"]);
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
    expect(flowProblems({ ...ok, steps: [{ fake_labels: "Japan 2026, Taxes" }] })).toEqual([]);
    expect(flowProblems({ ...ok, steps: [{ fake_labels: 3 }] })).toEqual(["step 1: fake_labels takes a string"]);
    expect(flowProblems({ ...ok, steps: [{ fake_ignored: "news.example, deals.example" }, { fake_ignore: "news.example" }] })).toEqual([]);
    expect(flowProblems({ ...ok, steps: [{ fake_ignored: 3 }] })).toEqual(["step 1: fake_ignored takes a string"]);
    expect(flowProblems({ ...ok, steps: [{ fake_ignore: true }] })).toEqual(["step 1: fake_ignore takes a string"]);
    expect(flowProblems({ ...ok, steps: [{ fake_destination: "Colorado & Texas" }] })).toEqual([]);
    expect(flowProblems({ ...ok, steps: [{ fake_destination: 3 }] })).toEqual(["step 1: fake_destination takes a string"]);
    expect(flowProblems({ ...ok, steps: [{ fake_first_run: "connect" }] })).toEqual([]);
    expect(flowProblems({ ...ok, steps: [{ fake_first_run: true }] })).toEqual(["step 1: fake_first_run takes a string"]);
    expect(flowProblems({ ...ok, steps: [{ fake_merge_warning: "Sam Doe | Mia Doe" }] })).toEqual([]);
    expect(flowProblems({ ...ok, steps: [{ fake_merge_warning: 3 }] })).toEqual(["step 1: fake_merge_warning takes a string"]);
    expect(flowProblems({ ...ok, steps: [{ fake_archive: 400 }] })).toEqual([]);
    expect(flowProblems({ ...ok, steps: [{ fake_archive: "400" }] })).toEqual(["step 1: fake_archive takes a number"]);
  });

  it("makes a made-up archive of the asked size from a trip of the demo, with ids of their own", () => {
    const model = { id: 7, name: "Demo", segments: [{ id: 70, trip_id: 7, provider: "X" }] };
    const made = fakeArchive([model], 120);
    expect(made).toHaveLength(120);
    expect(new Set(made.map((t) => t.id)).size).toBe(120);
    expect(made.every((t) => t.id > 7 && t.segments[0].trip_id === t.id)).toBe(true);
    expect(fakeArchive([], 5)).toEqual([]);
  });

  it("takes a download to click and save, named", () => {
    expect(flowProblems({ ...ok, steps: [{ download: { selector: "button", name: "saved-image" } }] })).toEqual([]);
    expect(flowProblems({ ...ok, steps: [{ download: "x" }] })).toEqual(["step 1: download takes a object"]);
  });

  it("takes phone_agent as true or false", () => {
    expect(flowProblems({ ...ok, phone_agent: true })).toEqual([]);
    expect(flowProblems({ ...ok, phone_agent: "yes" })).toEqual(["phone_agent is true or false"]);
  });
  it("takes the laptop, wide and zoomed viewports a flow asks for", () => expect(flowProblems({ ...ok, viewports: ["laptop", "wide", "zoomed"] })).toEqual([]));
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

describe("screenshotFile", () => {
  it("names one image for a shot, with no viewport-only variant", () => {
    expect(screenshotFile("upcoming", "phone")).toBe("upcoming-phone.png");
    expect(screenshotFile("flow-open-settings-settings-open", "desktop")).toBe("flow-open-settings-settings-open-desktop.png");
    expect(screenshotFile("upcoming", "phone")).not.toContain("-top");
  });

  it("names a page's first-screen image beside its full-page one", () => {
    expect(heroFile("upcoming", "phone")).toBe("upcoming-phone-hero.png");
    expect(heroFile("trips", "desktop")).toBe("trips-desktop-hero.png");
  });

  it("sets up offline access on localhost with a passkey that has PRF, and waits for the saved line", () => {
    expect(localBase("http://127.0.0.1:8765")).toBe("http://localhost:8765");
    expect(localBase("http://localhost:8765")).toBe("http://localhost:8765");
    expect(VIRTUAL_AUTHENTICATOR).toMatchObject({ transport: "internal", hasPrf: true, isUserVerified: true, hasUserVerification: true });
    expect(OFFLINE_SAVED).toContain("offline-saved");
  });

  it("writes images at phone and desktop only, and checks the extra widths without one", () => {
    expect(IMAGE_VIEWPORTS).toEqual(["phone", "desktop"]);
    expect(DEFAULT_VIEWPORTS).toEqual(["phone", "desktop"]);
    expect(["phone", "desktop", "laptop", "wide", "zoomed"].filter(writesImage)).toEqual(["phone", "desktop"]);
  });

  it("freezes the clock on a fixed date", () => expect(FROZEN_NOW).toBe("2026-06-15T12:00:00Z"));
});

describe("CHROMIUM_ARGS", () => {
  it("rasters in one thread, without partial raster and with a fixed colour profile and no sub-pixel text, so an edge comes out the same every run", () => {
    expect(CHROMIUM_ARGS).toEqual(["--force-color-profile=srgb", "--disable-lcd-text", "--num-raster-threads=1", "--disable-partial-raster"]);
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

describe("launchOptions and contextOptions", () => {
  it("launch the browser the same way for a run and for a control session", () => {
    expect(launchOptions().args).toEqual(CHROMIUM_ARGS);
  });

  it("make the dark UTC context a visit gets, with the phone agent only at phone width", () => {
    expect(contextOptions("desktop")).toEqual({ viewport: VIEWPORTS.desktop, colorScheme: "dark", timezoneId: "UTC", reducedMotion: "no-preference" });
    expect(contextOptions("phone", { phoneAgent: true }).userAgent).toBe(PHONE_AGENT);
    expect(contextOptions("desktop", { phoneAgent: true }).userAgent).toBeUndefined();
    expect(contextOptions("phone", { reducedMotion: "reduce" }).reducedMotion).toBe("reduce");
  });
});

describe("readFlows", () => {
  const folder = mkdtempSync(join(tmpdir(), "waypoint-flows-"));
  const write = (name, text) => writeFileSync(join(folder, name), text);
  afterAll(() => rmSync(folder, { recursive: true, force: true }));

  it("reads every flow of the repository", () => {
    const { flows, error } = readFlows(join(import.meta.dirname, "flows"));
    expect(error).toBeUndefined();
    expect(flows.length).toBeGreaterThan(50);
  });

  it("says which file is not JSON or not a flow, instead of ending the process", () => {
    write("a.json", JSON.stringify({ name: "a", steps: [{ goto: "#trips" }] }));
    write("b.json", "{ nope");
    expect(readFlows(folder).error).toMatch(/^flow b\.json isn't valid JSON/);
    write("b.json", JSON.stringify({ name: "b", steps: [] }));
    expect(readFlows(folder).error).toBe("flow b.json: needs a list of steps");
    write("b.json", JSON.stringify({ name: "b", steps: [{ goto: "#people" }] }));
    expect(readFlows(folder).flows.map((f) => f.name)).toEqual(["a", "b"]);
    expect(readFlows(join(folder, "none"))).toEqual({ flows: [] });
  });
});

describe("the assertions a screenshot must not undo", () => {
  const expectText = { expect_text: { selector: "h1", text: "Trips" } };

  it("are the expect_text steps since the last action", () => {
    let checks = [];
    checks = checksAfter(checks, expectText);
    checks = checksAfter(checks, { wait_for: "ul" });
    checks = checksAfter(checks, { screenshot: "a" });
    checks = checksAfter(checks, { scroll_to: "#x" });
    checks = checksAfter(checks, { expect_text: { selector: "main", text: "Jane" }, timeout: 500 });
    expect(checks).toHaveLength(2);
    expect(checksAfter(checks, { click: "a" })).toEqual([]);
    expect(checksAfter(checks, { goto: "#people" })).toEqual([]);
    expect(checksAfter(checks, { reload: true })).toEqual([]);
  });

  const pageShowing = (text) => ({ waitForTimeout: async () => {}, locator: () => ({ first: () => ({ waitFor: async () => {}, innerText: async () => text }) }) });

  it("hold, or are named when the page no longer shows them", async () => {
    expect(await recheck(pageShowing("Trips and more"), [expectText])).toBeNull();
    expect(await recheck(pageShowing("Settings"), [])).toBeNull();
    const lost = await recheck(pageShowing("Settings"), [expectText], 1);
    expect(lost).toContain("no longer holds after the screenshot");
    expect(lost).toContain('expected "Trips" in h1, found "Settings"');
  });
});
