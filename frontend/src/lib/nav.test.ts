import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { flightRoute, initials, inMore, MORE, NAV, navFor, pageFor, TABS } from "./nav";

describe("nav", () => {
  it("has Upcoming first, which is where an unknown route goes", () => {
    expect(NAV.map((n) => n.page)).toEqual(["upcoming", "trips", "stats", "people", "review", "settings"]);
    expect(pageFor("settings")).toBe("settings");
    expect(pageFor("budget")).toBe("upcoming");
    expect(pageFor("")).toBe("upcoming");
  });

  it("puts four pages in the tab bar and People and Settings under More, so every page is reachable", () => {
    expect(TABS.map((n) => n.page)).toEqual(["upcoming", "trips", "stats", "review"]);
    expect(MORE.map((n) => n.page)).toEqual(["people", "settings"]);
    expect([...TABS, ...MORE].map((n) => n.page).sort()).toEqual(NAV.map((n) => n.page).sort());
    expect(inMore(navFor("people"))).toBe(true);
    expect(inMore(navFor("design"))).toBe(true);
    expect(inMore(navFor("trip"))).toBe(false);
  });

  it("opens a trip from Trips, which stays lit while you're on it", () => {
    expect(pageFor("trip")).toBe("trip");
    expect(navFor("trip")).toBe("trips");
    expect(navFor("people")).toBe("people");
    expect(navFor("budget")).toBe("upcoming");
  });

  it("opens a flight's live status view from a trip's address, and only for a flight number", () => {
    expect(flightRoute("flight/34")).toBe(34);
    expect(flightRoute("flight/")).toBeNull();
    expect(flightRoute("flight/x")).toBeNull();
    expect(flightRoute("flight/34/more")).toBeNull();
    expect(flightRoute("")).toBeNull();
    expect(pageFor("trip", "flight/34")).toBe("flight");
    expect(pageFor("trip", "")).toBe("trip");
    expect(pageFor("trips", "flight/34")).toBe("trips");
    expect(pageFor("flight")).toBe("upcoming");
    expect(navFor("trip")).toBe("trips");
  });

  it("shows what's waiting on Review, and nothing on the other pages", () => {
    const review = NAV.find((n) => n.page === "review");
    const s = { version: "1", database: "sqlite" as const, user: null, last_backup: null, review_count: 3, person_id: null, ai: false, show_costs: true };
    expect(review?.badge?.(s)).toBe(3);
    expect(NAV.filter((n) => n.badge).map((n) => n.page)).toEqual(["review"]);
  });

  it("makes initials from a name or an email address", () => {
    expect(initials("Ada Lovelace")).toBe("AL");
    expect(initials("ada@example.com")).toBe("AE");
    expect(initials("Grace")).toBe("G");
  });

  it("reaches every page of the user feature map by a URL that opens that page", () => {
    const map = readFileSync(new URL("../../../.claude/skills/verify-waypoint/references/feature-map.md", import.meta.url), "utf8");
    const reached: Record<string, string> = {};
    for (const section of map.split(/^## /m).slice(1)) {
      const page = /\(`([^`]+)`\)/.exec(section.split("\n")[0])?.[1];
      const url = /^- \*\*Reach it:\*\*.*?URL `#([^`]+)`/m.exec(section)?.[1];
      if (page && url) reached[page] = url;
    }
    expect(Object.keys(reached)).toContain("flight");
    for (const [page, url] of Object.entries(reached)) {
      const [route, , ...rest] = url.replace(/<[^>]+>/g, "7").split("/");
      expect([page, pageFor(route, rest.join("/"))]).toEqual([page, page]);
    }
  });
});
