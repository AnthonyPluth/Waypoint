import { describe, expect, it } from "vitest";
import type { TripPhoto } from "./api-types";
import { segment } from "../test/fixtures";
import { byDay, clusterOf, dayCaption, daysFor, FAR_FROM_BOOKINGS, FROM_ITINERARY, isFar, isInferred, kilometres, originalUrl, personName, placeOf, previewUrl, thumbnailUrl, tileLabel, zoneCity } from "./photos";

const photo = (extra: Partial<TripPhoto> = {}): TripPhoto => ({
  id: 1, person_id: 1, trip_id: 1, kind: "image", taken_local: "2026-03-01T10:42", zone: "America/Denver", latitude: 39.7, longitude: -105, location_source: "exif",
  segment_id: 2, match: "place", distance_km: 3, cluster: 0, removed_at: null, ...extra,
});
const stay = segment({ id: 2, kind: "hotel", origin: "Juniper House", destination: "Marlow Springs", start_local: "2026-03-01T15:00", start_zone: "America/Denver", end_local: "2026-03-04T11:00", end_zone: "America/Denver" });
const flight = segment({ id: 3, origin: "DEN", destination: "SLC", start_local: "2026-03-04T09:00", start_zone: "America/Denver", end_local: "2026-03-04T10:30", end_zone: "America/Denver" });

describe("byDay", () => {
  it("groups on the local day, keeping the order photos come in", () => {
    const days = byDay([photo({ id: 1, taken_local: "2026-03-01T08:00" }), photo({ id: 2, taken_local: "2026-03-01T21:00" }), photo({ id: 3, taken_local: "2026-03-02T07:00" })]);
    expect(days.map((d) => [d.day, d.photos.map((p) => p.id)])).toEqual([["2026-03-01", [1, 2]], ["2026-03-02", [3]]]);
  });

  it("keeps two photos an hour apart on different local days across a zone change, never converting their times", () => {
    const evening = photo({ id: 1, taken_local: "2026-03-01T23:30", zone: "America/Chicago" });
    const later = photo({ id: 2, taken_local: "2026-03-02T01:30", zone: "America/New_York" });
    const days = byDay([evening, later]);
    expect(days.map((d) => d.day)).toEqual(["2026-03-01", "2026-03-02"]);
    expect(tileLabel(evening, undefined, "")).toBe("Photo, 11:30 PM");
    expect(tileLabel(later, undefined, "")).toBe("Photo, 1:30 AM");
  });

  it("is empty for no photos", () => expect(byDay([])).toEqual([]));

  it("puts the days in the order of their local dates after a westward zone change", () => {
    const lateInNewYork = photo({ id: 1, taken_local: "2026-03-02T00:30", zone: "America/New_York" });
    const eveningInLosAngeles = photo({ id: 2, taken_local: "2026-03-01T22:30", zone: "America/Los_Angeles" });
    expect(byDay([lateInNewYork, eveningInLosAngeles]).map((d) => [d.day, d.photos.map((p) => p.id)])).toEqual([["2026-03-01", [2]], ["2026-03-02", [1]]]);
  });
});

describe("marks and labels", () => {
  it("knows inferred and far photos", () => {
    expect(isInferred(photo({ location_source: "inferred" }))).toBe(true);
    expect(isInferred(photo())).toBe(false);
    expect(isFar(photo({ match: "far" }))).toBe(true);
    expect(isFar(photo())).toBe(false);
    expect(FROM_ITINERARY).toBe("From the itinerary");
    expect(FAR_FROM_BOOKINGS).toBe("Far from the trip’s bookings");
  });

  it("names a tile like the design: kind, time, place, library, then the marks", () => {
    expect(tileLabel(photo(), stay, "Ada")).toBe("Photo, 10:42 AM, near Marlow Springs, Ada’s library");
    expect(tileLabel(photo({ location_source: "inferred" }), stay, "Theo")).toBe("Photo, 10:42 AM, Marlow Springs, Theo’s library, place from the itinerary");
    expect(tileLabel(photo({ match: "far", distance_km: 612.4 }), stay, "Ada")).toBe("Photo, 10:42 AM, Ada’s library, 612 km from every booking");
    expect(tileLabel(photo({ kind: "video" }), undefined, "")).toBe("Video, 10:42 AM");
  });

  it("places a photo by its booking", () => {
    expect(placeOf(photo(), stay)).toBe("Marlow Springs");
    expect(placeOf(photo(), { ...stay, destination: null })).toBe("Juniper House");
    expect(placeOf(photo({ taken_local: "2026-03-04T08:00" }), flight)).toBe("DEN");
    expect(placeOf(photo({ taken_local: "2026-03-04T11:00" }), flight)).toBe("SLC");
    expect(placeOf(photo(), segment({ kind: "car", origin: "Denver airport", provider: "Example Cars" }))).toBe("Denver airport");
    expect(placeOf(photo(), segment({ kind: "visit", origin: null, destination: "FR" }))).toBe("France");
    expect(placeOf(photo(), undefined)).toBe("");
  });

  it("finds a photo’s cluster", () => {
    const clusters = [{ latitude: 1, longitude: 2, count: 1, first: "2026-03-01T10:42", last: "2026-03-01T10:42", cover: 1, inferred: false }];
    expect(clusterOf(photo(), clusters)).toBe(clusters[0]);
    expect(clusterOf(photo({ cluster: null }), clusters)).toBeNull();
    expect(clusterOf(photo({ cluster: 4 }), clusters)).toBeNull();
  });

  it("builds the three image addresses from Waypoint’s photo id", () => {
    expect(thumbnailUrl(7)).toBe("/api/photos/7/thumbnail");
    expect(previewUrl(7)).toBe("/api/photos/7/preview");
    expect(originalUrl(7)).toBe("/api/photos/7/original");
  });

  it("words zones, distances and names", () => {
    expect(zoneCity("America/Los_Angeles")).toBe("Los Angeles");
    expect(zoneCity(null)).toBe("");
    expect(kilometres(1234.6)).toBe("1,235 km");
    expect(kilometres(null)).toBe("0 km");
    const people = [{ id: 1, display_name: "Ada Brook", first_name: "Ada", legal_name: null, aliases: [], member: true, links: [] }, { id: 2, display_name: "Theo Brook", first_name: null, legal_name: null, aliases: [], member: true, links: [] }];
    expect(personName(people, 1)).toBe("Ada");
    expect(personName(people, 2)).toBe("Theo Brook");
    expect(personName(people, 3)).toBe("");
  });
});

describe("day captions and pages", () => {
  const segments = new Map([[2, stay], [3, flight]]);

  it("says the day of the trip, its places, the far ones and the count", () => {
    const group = { day: "2026-03-03", photos: [photo({ id: 1 }), photo({ id: 2 }), photo({ id: 3, match: "far" }), photo({ id: 4, segment_id: null })] };
    expect(dayCaption({ start_date: "2026-03-01" }, group, segments)).toBe("Day 3 · Marlow Springs, and 1 far away · 4 photos");
    expect(dayCaption({ start_date: null }, { day: "2026-03-03", photos: [photo({ match: "far" })] }, segments)).toBe("1 far away · 1 photo");
  });

  it("adds whole days until a page is full", () => {
    const days = [3, 30, 30, 5].map((n, i) => ({ day: `2026-03-0${i + 1}`, photos: Array.from({ length: n }, (_, j) => photo({ id: i * 100 + j })) }));
    expect(daysFor(days, 0)).toBe(3);
    expect(daysFor(days, 3)).toBe(4);
    expect(daysFor(days, 0, 2)).toBe(1);
    expect(daysFor(days, 4)).toBe(4);
  });
});
