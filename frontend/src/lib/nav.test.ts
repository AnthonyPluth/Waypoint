import { describe, expect, it } from "vitest";
import { initials, NAV, pageFor } from "./nav";

describe("nav", () => {
  it("has Upcoming first, which is where an unknown route goes", () => {
    expect(NAV.map((n) => n.page)).toEqual(["upcoming", "settings"]);
    expect(pageFor("settings")).toBe("settings");
    expect(pageFor("budget")).toBe("upcoming");
    expect(pageFor("")).toBe("upcoming");
  });

  it("makes initials from a name or an email address", () => {
    expect(initials("Ada Lovelace")).toBe("AL");
    expect(initials("ada@example.com")).toBe("AE");
    expect(initials("Grace")).toBe("G");
  });
});
