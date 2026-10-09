import { describe, expect, it } from "vitest";
import { initials, inMore, MORE, NAV, navFor, pageFor, TABS } from "./nav";

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

  it("shows what's waiting on Review, and nothing on the other pages", () => {
    const review = NAV.find((n) => n.page === "review");
    const s = { version: "1", database: "sqlite" as const, user: null, last_backup: null, review_count: 3, person_id: null };
    expect(review?.badge?.(s)).toBe(3);
    expect(NAV.filter((n) => n.badge).map((n) => n.page)).toEqual(["review"]);
  });

  it("makes initials from a name or an email address", () => {
    expect(initials("Ada Lovelace")).toBe("AL");
    expect(initials("ada@example.com")).toBe("AE");
    expect(initials("Grace")).toBe("G");
  });
});
