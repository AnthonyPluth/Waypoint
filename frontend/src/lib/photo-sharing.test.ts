import { describe, expect, it } from "vitest";
import type { Person } from "./api-types";
import { MAX_REMOVED, putBackLabel, removedList, removedThumbnail, removedTitle, removedToast, removeText, toggled, whoIs } from "./photo-sharing";

const person = (id: number, display_name: string, first_name: string, member: boolean): Person => ({ id, display_name, first_name, legal_name: null, aliases: [], member, links: [] });
const people = [person(1, "Ada Brook", "Ada", true), person(3, "June Brook", "June", false)];
const me = whoIs(1, 1, people);
const june = whoIs(3, 1, people);

describe("Remove from this trip: copy", () => {
  it("names the person the action is for", () => {
    expect(removeText(me)).toBe("Remove from this trip");
    expect(removeText(june)).toBe("Remove June’s photo from this trip");
    expect(removeText(june, 3)).toBe("Remove June’s photos from this trip");
    expect(removedToast(me, 1, "Four Corners loop")).toBe("Removed from Four Corners loop.");
    expect(removedToast(me, 3, "Four Corners loop")).toBe("3 photos removed from Four Corners loop.");
    expect(removedToast(june, 1, "Four Corners loop")).toBe("Removed June’s photo from Four Corners loop.");
    expect(removedToast(june, 3, "Four Corners loop")).toBe("3 of June’s photos removed from Four Corners loop.");
    expect(removedList(me)).toBe("Photos you removed from this trip");
    expect(removedList(june)).toBe("June’s photos removed from this trip");
  });

  it("labels a removed photo by when it was taken", () => {
    expect(putBackLabel({ kind: "image", taken_local: "2026-03-08T11:30" })).toBe("Put back the photo from Sun, Mar 8, 11:30 AM");
    expect(putBackLabel({ kind: "video", taken_local: "2026-03-08T11:30" })).toBe("Put back the video from Sun, Mar 8, 11:30 AM");
    expect(removedTitle(3)).toBe("Removed from this trip (3)");
    expect(removedThumbnail(7, 12)).toBe("/api/trips/7/photo-exclusions/12/thumbnail");
  });
});

describe("toggled", () => {
  it("adds, removes and never changes the set it was given", () => {
    const none = new Set<number>();
    const one = toggled(none, 4);
    expect([...one]).toEqual([4]);
    expect(none.size).toBe(0);
    expect(toggled(one, 4).size).toBe(0);
  });

  it("stops adding at the most one request may remove, and still lets one go", () => {
    const full = new Set(Array.from({ length: MAX_REMOVED }, (_, i) => i + 1));
    expect(toggled(full, 9999)).toEqual(full);
    expect(toggled(full, 1).size).toBe(MAX_REMOVED - 1);
  });
});
