import { describe, expect, it } from "vitest";
import { emailNews } from "./email-news";

describe("emailNews", () => {
  it("names what a newer email changed once each", () => {
    expect(emailNews({ at: 1, updated: ["start_local", "start_zone", "end_local"], disagreed: [] })).toEqual({ updated: "the start and the end", disagreed: "" });
  });

  it("names what it disagreed with separately", () => {
    expect(emailNews({ at: 1, updated: [], disagreed: ["start_local"] })).toEqual({ updated: "", disagreed: "the start" });
  });

  it("lists three places and times with commas", () => {
    expect(emailNews({ at: 1, updated: ["start_local", "end_local", "origin"], disagreed: [] }).updated).toBe("the start, the end and the first place");
  });

  it("says nothing when nothing is named", () => {
    expect(emailNews({ at: 1, updated: [], disagreed: [] })).toEqual({ updated: "", disagreed: "" });
  });
});
