import { describe, expect, it } from "vitest";
import { bookingCards, clock, dayIn, featuredTrip, flightKey, headline, instant, isPast, membershipFor, nextUp, placeTime, programFor, splitTrips, subline, tripDays, until, when } from "./trips";
import { membership, segment, trip } from "../test/fixtures";

const NY = "America/New_York", LON = "Europe/London", AKL = "Pacific/Auckland", LA = "America/Los_Angeles";
// 2026-11-20 12:00 in New York is 17:00 UTC (EST).
const at = (local: string, zone: string) => instant(local, zone);

describe("instant", () => {
  it("is the moment a wall-clock time at a place is, daylight saving included", () => {
    expect(at("2026-11-20T12:00", NY)).toBe(Date.UTC(2026, 10, 20, 17, 0));
    expect(at("2026-07-20T12:00", NY)).toBe(Date.UTC(2026, 6, 20, 16, 0));
    expect(at("2026-11-21T07:10", LON)).toBe(Date.UTC(2026, 10, 21, 7, 10));
    expect(at("2026-11-20T12:00", AKL)).toBe(Date.UTC(2026, 10, 19, 23, 0));
  });
  it("is NaN for text that isn't a local time", () => { expect(instant("tomorrow", NY)).toBeNaN(); });
});

describe("local times across zones", () => {
  it("shows the place's own time, and yours in brackets only when your offset then differs", () => {
    // An 7:00 PM departure from New York, read by someone in Los Angeles: 4:00 PM for them.
    expect(placeTime("2026-11-20T19:00", NY, LA)).toEqual({ text: "7:00 PM", yours: "4:00 PM PST" });
    expect(placeTime("2026-11-20T19:00", NY, NY)).toEqual({ text: "7:00 PM", yours: null });
    // A zone with the same offset then is the same time: nothing in brackets.
    expect(placeTime("2026-11-20T19:00", NY, "America/Toronto").yours).toBeNull();
  });
  it("says which day it is for you when that isn't the place's day", () => {
    // 7:10 AM in London on the 21st is 11:10 PM on the 20th in Los Angeles.
    expect(placeTime("2026-11-21T07:10", LON, LA)).toEqual({ text: "7:10 AM", yours: "Nov 20, 11:10 PM PST" });
  });
  it("never converts the place's time to the viewer's or the server's", () => {
    for (const mine of [NY, LON, AKL, LA, "UTC"]) expect(placeTime("2026-11-20T19:00", NY, mine).text).toBe("7:00 PM");
    expect(clock("2026-03-01T22:15")).toBe("10:15 PM");
  });
  it("tells the day in a zone", () => { expect(dayIn(Date.UTC(2026, 10, 21, 3, 0), NY)).toBe("2026-11-20"); });
});

describe("when", () => {
  it("says in how long, and never \"in now\" in the last minute", () => {
    expect(when("Departs", 5 * 3_600_000)).toBe("Departs in 5 h");
    expect(when("Departs", 20_000)).toBe("Departing now");
    expect(when("Arrives", 0)).toBe("Arriving now");
    expect(when("Check-in", 30_000)).toBe("Check-in now");
  });
});

describe("until", () => {
  it("counts down in the largest units that matter", () => {
    expect(until(20_000)).toBe("now");
    expect(until(45 * 60_000)).toBe("45 min");
    expect(until(5 * 3_600_000 + 20 * 60_000)).toBe("5 h 20 min");
    expect(until(3 * 3_600_000)).toBe("3 h");
    expect(until(26 * 3_600_000)).toBe("1 day 2 h");
    expect(until(48 * 3_600_000)).toBe("2 days");
  });
});

// Flight out 19:00 on the 20th from New York, arriving 07:10 on the 21st in London; a hotel from the 21st to the 27th.
const out = segment({ id: 1 });
const stay = segment({ id: 2, kind: "hotel", provider: "Marriott", origin: "Harbour Hotel", destination: null, start_local: "2026-11-21T15:00", start_zone: LON, end_local: "2026-11-27T10:00", end_zone: LON, details: { address: "1 Quay Street, London" } });
const back = segment({ id: 3, origin: "LHR", destination: "JFK", start_local: "2026-11-27T11:30", start_zone: LON, end_local: "2026-11-27T14:35", end_zone: NY });
const london = trip([out, stay, back]);

describe("nextUp", () => {
  it("is the segment that starts soonest while none is under way", () => {
    const now = at("2026-11-18T09:00", NY);
    expect(nextUp([london], now)).toMatchObject({ state: "next", segment: { id: 1 } });
  });
  it("leads with a flight under way (in progress) over what comes later", () => {
    const now = at("2026-11-21T02:00", NY);   // in the air
    expect(nextUp([london], now)).toMatchObject({ state: "now", segment: { id: 1 } });
  });
  it("lets a hotel stay under way give way to the next flight (next, not now)", () => {
    const now = at("2026-11-23T12:00", LON);
    expect(nextUp([london], now)).toMatchObject({ state: "next", segment: { id: 3 } });
  });
  it("shows the stay as under way when nothing else is left", () => {
    expect(nextUp([trip([stay])], at("2026-11-23T12:00", LON))).toMatchObject({ state: "now", segment: { id: 2 } });
  });
  it("skips cancelled segments and segments that are over, and is null when nothing is left", () => {
    const cancelled = segment({ id: 9, status: "cancelled", start_local: "2026-11-19T09:00", end_local: "2026-11-19T12:00", start_zone: NY, end_zone: NY });
    expect(nextUp([trip([cancelled, out])], at("2026-11-18T09:00", NY))?.segment.id).toBe(1);
    expect(nextUp([london], at("2026-12-01T09:00", NY))).toBeNull();
    expect(nextUp([], Date.now())).toBeNull();
  });
  it("looks across every trip", () => {
    const later = trip([segment({ id: 20, trip_id: 2, start_local: "2027-01-14T21:00", end_local: "2027-01-16T06:30" })], { id: 2, name: "Trip to Auckland" });
    expect(nextUp([later, london], at("2026-11-18T09:00", NY))?.trip.id).toBe(1);
    expect(nextUp([later, london], at("2026-12-01T09:00", NY))?.trip.id).toBe(2);
  });
});

describe("trips by when", () => {
  const past = trip([segment({ id: 30, start_local: "2026-08-25T08:00", end_local: "2026-08-30T20:00" })], { id: 3, name: "Past" });
  const undated = trip([], { id: 4, name: "Undated", start_date: null, end_date: null });
  it("splits upcoming (soonest first, undated last) from past (latest first)", () => {
    const { upcoming, past: gone } = splitTrips([undated, london, past], "2026-10-05");
    expect(upcoming.map((t) => t.id)).toEqual([1, 4]);
    expect(gone.map((t) => t.id)).toEqual([3]);
    expect(isPast(london, "2026-11-27")).toBe(false);
    expect(isPast(london, "2026-11-28")).toBe(true);
  });
  it("features the next up segment's trip, else the first still to come", () => {
    expect(featuredTrip([london, past], nextUp([london], at("2026-11-18T09:00", NY)), "2026-11-18")?.id).toBe(1);
    expect(featuredTrip([past], null, "2026-10-05")).toBeNull();
    expect(featuredTrip([past, london], null, "2026-10-05")?.id).toBe(1);
  });
});

describe("tripDays", () => {
  it("lists what happens each day, with a stay's check-out on its last day, and no empty days", () => {
    const days = tripDays(london);
    expect(days.map((d) => d.date)).toEqual(["2026-11-20", "2026-11-21", "2026-11-27"]);
    expect(days[2].items.map((i) => `${i.segment.id}:${i.role}`)).toEqual(["2:end", "3:start"]);
  });
});

describe("wording", () => {
  it("names a segment and describes it", () => {
    expect(headline(out)).toBe("JFK → LHR");
    expect(subline(out)).toBe("American Airlines AA 101 · Terminal 8");
    expect(headline(stay)).toBe("Harbour Hotel");
    expect(subline(stay)).toBe("1 Quay Street, London");
    expect(headline(segment({ kind: "car", provider: "Hertz", origin: "SFO airport" }))).toBe("Hertz · SFO airport");
    expect(headline(segment({ kind: "train", origin: "NYP", destination: "BOS" }))).toBe("NYP → BOS");
    expect(headline(segment({ kind: "hotel", origin: null, provider: null }))).toBe("Hotel stay");
  });
});

describe("loyalty on a booking", () => {
  const jane = { id: 1, person_id: 1, name: "Jane Doe" };
  it("knows the program a provider's name belongs to", () => {
    expect(programFor(out)).toBe("American AAdvantage");
    expect(programFor(stay)).toBe("Marriott Bonvoy");
    expect(programFor(segment({ kind: "car", provider: "Hertz" }))).toBe("Hertz Gold Plus Rewards");
    expect(programFor(segment({ provider: "Example Air" }))).toBeNull();
    expect(programFor(segment({ provider: null }))).toBeNull();
    expect(programFor(segment({ kind: "train", provider: "Amtrak" }))).toBeNull();
    // Only a booking of that kind, and only the whole word: a hotel isn't an airline or a car company.
    expect(programFor(segment({ kind: "hotel", provider: "International Inn" }))).toBeNull();
    expect(programFor(segment({ kind: "hotel", provider: "United Suites" }))).toBeNull();
    expect(programFor(segment({ kind: "car", provider: "National Car Rental" }))).toBe("National Emerald Club");
    expect(programFor(segment({ provider: "Americana Air" }))).toBeNull();
  });
  it("finds the traveller's number for it, or says they have none, or that the name isn't matched", () => {
    const mine = membership();
    expect(membershipFor(out, jane, [mine, membership({ id: 12, person_id: 2 })])).toEqual({ state: "found", entry: mine });
    expect(membershipFor(out, jane, [membership({ program: "Delta SkyMiles" })])).toEqual({ state: "none", program: "American AAdvantage" });
    expect(membershipFor(out, { id: 2, person_id: null, name: "DOE/MIA MISS" }, [mine])).toEqual({ state: "unmatched" });
    expect(membershipFor(segment({ provider: "Example Air" }), jane, [mine])).toBeNull();
  });
});

describe("flightKey", () => {
  it("is one flight however its number is written", () => {
    for (const n of ["AA 4001", "AA4001", "aa 4001", "AA04001", "AA  4001", "AA-4001"]) expect(flightKey(n)).toBe("AA4001");
    expect(flightKey("B6 123")).toBe("B6123");
  });
  it("is null for what isn't a flight number", () => {
    expect(flightKey(undefined)).toBeNull();
    expect(flightKey("")).toBeNull();
    expect(flightKey("not a flight")).toBeNull();
  });
});

describe("bookingCards", () => {
  // The same flight on two reservations: each keeps its own segment (its code, travellers, edits), the card is one.
  const mine = segment({ id: 1, confirmation: "AAAAAA", details: { flight_number: "AA 101" } });
  const theirs = segment({ id: 2, confirmation: "BBBBBB", details: { flight_number: "AA0101" }, travelers: [{ id: 5, person_id: 2, name: "Sam Doe" }] });

  it("makes one card of the same flight, date and airports on two bookings, keeping both", () => {
    const [card, ...rest] = bookingCards([mine, theirs]);
    expect(rest).toEqual([]);
    expect(card.segments.map((s) => s.confirmation)).toEqual(["AAAAAA", "BBBBBB"]);
    expect(card.lead).toBe(mine);
    expect(card.timesDiffer).toBe(false);
  });
  it("keeps other dates, flights and airports apart, and a booking alone is its own card", () => {
    const nextDay = segment({ id: 3, start_local: "2026-11-21T19:00", end_local: "2026-11-22T07:10", details: { flight_number: "AA 101" } });
    const otherFlight = segment({ id: 4, details: { flight_number: "AA 102" } });
    const otherLeg = segment({ id: 5, destination: "MAN", details: { flight_number: "AA 101" } });
    expect(bookingCards([mine, theirs, nextDay, otherFlight, otherLeg]).map((c) => c.segments.map((s) => s.id))).toEqual([[1, 2], [3], [4], [5]]);
    expect(bookingCards([mine]).map((c) => c.segments.length)).toEqual([1]);
  });
  it("never groups stays or rentals, nor flights with no number", () => {
    const stays = [segment({ id: 6, kind: "hotel", details: {} }), segment({ id: 7, kind: "hotel", details: {} })];
    const unnumbered = [segment({ id: 8, details: {} }), segment({ id: 9, details: {} })];
    expect(bookingCards([...stays, ...unnumbered]).map((c) => c.segments.length)).toEqual([1, 1, 1, 1]);
  });
  it("says when the bookings disagree on the times, ignoring a cancelled one", () => {
    const moved = segment({ id: 2, confirmation: "BBBBBB", start_local: "2026-11-20T21:30", details: { flight_number: "AA 101" } });
    expect(bookingCards([mine, moved])[0].timesDiffer).toBe(true);
    const arrives = segment({ id: 2, confirmation: "BBBBBB", end_local: "2026-11-21T08:00", details: { flight_number: "AA 101" } });
    expect(bookingCards([mine, arrives])[0].timesDiffer).toBe(true);
    expect(bookingCards([mine, { ...moved, status: "cancelled" }])[0].timesDiffer).toBe(false);
  });
  it("leads with a booking that isn't cancelled, and is cancelled only when every booking is", () => {
    const [one] = bookingCards([{ ...mine, status: "cancelled" }, theirs]);
    expect(one.lead.id).toBe(2);
    expect(one.cancelled).toBe(false);
    expect(bookingCards([{ ...mine, status: "cancelled" }, { ...theirs, status: "cancelled" }])[0].cancelled).toBe(true);
  });
});

describe("a flight on two bookings, across the screens", () => {
  const second = segment({ id: 10, confirmation: "BBBBBB", details: { flight_number: "AA 101" } });
  const split = trip([out, second, stay, back]);
  it("is one item on its day", () => {
    const days = tripDays(split);
    expect(days[0].items.map((i) => `${i.segment.id}:${i.bookings.length}`)).toEqual(["1:2"]);
  });
  it("is one flight to lead with, listing both bookings", () => {
    expect(nextUp([split], at("2026-11-18T09:00", NY))).toMatchObject({ state: "next", segment: { id: 1 }, bookings: [{ id: 1 }, { id: 10 }] });
  });
});
