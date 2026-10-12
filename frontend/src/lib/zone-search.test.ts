import { describe, expect, it } from "vitest";
import { COMMON_NAMES } from "./zone-names";
import { MAX_SHOWN, buildIndex, describeZone, normalize, searchZones, supportedZones, zoneEntry } from "./zone-search";

const real = buildIndex(supportedZones() ?? []);
const find = (index: typeof real, text: string) => searchZones(index, text).map((entry) => entry.zone);

describe("zone search", () => {
  it("finds a zone by its city first", () => {
    expect(find(real, "Chicago")[0]).toBe("America/Chicago");
  });

  it("ignores case, spaces, underscores, slashes and accents", () => {
    for (const text of ["new york", "newyork", "New_York", "NEW YORK", "america/new_york", "Néw Yörk"]) {
      expect(find(real, text)).toContain("America/New_York");
    }
    expect(normalize("São Paulo")).toBe("saopaulo");
    expect(find(real, "sao paulo")).toContain("America/Sao_Paulo");
  });

  it("finds the US and Canadian states a person would think of", () => {
    for (const text of ["Illinois", "IL", "Central", "Minnesota"]) expect(find(real, text)).toContain("America/Chicago");
    expect(find(real, "Pacific")).toContain("America/Los_Angeles");
    expect(find(real, "Alaska")).toContain("America/Anchorage");
    expect(find(real, "Hawaii")).toContain("Pacific/Honolulu");
    expect(find(real, "British Columbia")).toContain("America/Vancouver");
  });

  it("finds common names and the abbreviations the browser gives", () => {
    expect(find(real, "EST")).toContain("America/New_York");
    expect(find(real, "Eastern")).toEqual(expect.arrayContaining(["America/New_York", "America/Toronto"]));
    expect(find(real, "CST")).toContain("America/Chicago");
    expect(find(real, "PST")).toContain("America/Los_Angeles");
    expect(find(real, "GMT")).toContain("Europe/London");
    expect(find(real, "UTC")).toContain("Europe/London");
    expect(find(real, "tokyo")).toContain("Asia/Tokyo");
    expect(find(real, "Japan")).toContain("Asia/Tokyo");
    expect(find(real, "India")).toContain("Asia/Calcutta");
    expect(find(real, "Kolkata")).toContain("Asia/Calcutta");
  });

  it("finds a zone by the long name the browser gives", () => {
    expect(find(real, "Central Daylight Time")).toContain("America/Chicago");
  });

  it("finds a zone by its region", () => {
    const europe = find(real, "Europe");
    expect(europe.length).toBeGreaterThan(0);
    expect(europe.every((zone) => zone.startsWith("Europe/"))).toBe(true);
  });

  it("ranks an exact city, then a city prefix, then a name, then anything containing it", () => {
    const index = buildIndex(["Test/Alpha", "Test/Alphabet", "Test/Zed_Alpha", "Alpha/Realm", "Other/Beta"]);
    expect(find(index, "alpha")).toEqual(["Test/Alpha", "Test/Alphabet", "Alpha/Realm", "Test/Zed_Alpha"]);
  });

  it("orders zones of one rank alphabetically", () => {
    expect(find(buildIndex(["Test/Pinecone", "Test/Pine", "Test/Pineapple"]), "pine")).toEqual(["Test/Pine", "Test/Pineapple", "Test/Pinecone"]);
  });

  it("shows no more than the limit", () => {
    expect(searchZones(real, "a")).toHaveLength(MAX_SHOWN);
    expect(searchZones(real, "")).toHaveLength(MAX_SHOWN);
  });

  it("finds nothing for nonsense", () => {
    expect(find(real, "qqqqzzzz")).toEqual([]);
  });

  it("describes a zone with its current name", () => {
    expect(describeZone(zoneEntry("America/Chicago"))).toBe("America/Chicago, Central Time");
    expect(describeZone(zoneEntry("America/Los_Angeles"))).toBe("America/Los Angeles, Pacific Time");
  });

  it("has no abbreviation noise for offset-only names", () => {
    expect(zoneEntry("Asia/Tokyo").abbreviations).toEqual([]);
  });
});

describe("common names", () => {
  it("names only zones the browser lists", () => {
    const listed = new Set(supportedZones());
    expect(Object.keys(COMMON_NAMES).length).toBeGreaterThan(10);
    for (const zone of Object.keys(COMMON_NAMES)) expect(listed.has(zone), zone).toBe(true);
  });
});
