import { describe, expect, it } from "vitest";
import { bookingCards, appWord, checkInOpen, CHECK_IN_WINDOW_HOURS, passHeadline, routeProgress, clock, dayIn, featuredTrip, flightKey, headline, instant, isPast, membershipFor, nextUp, programFor, splitTrips, START_WORD, tripKinds, END_WORD, subline, seatsInOrder, cityState, upcomingTitle, tripDays, untimed, until, when } from "./trips";
import { membership, segment, trip } from "../test/fixtures";

const NY = "America/New_York", LON = "Europe/London", AKL = "Pacific/Auckland", LA = "America/Los_Angeles";
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
  it("never converts the place's time to the viewer's or the server's", () => {
    expect(clock("2026-11-20T19:00")).toBe("7:00 PM");
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
    const now = at("2026-11-21T02:00", NY);
    expect(nextUp([london], now)).toMatchObject({ state: "now", segment: { id: 1 } });
  });
  it("never leads with a flight that has no times: there's nothing to count down to", () => {
    const now = at("2026-11-18T09:00", NY);
    const untimedFlight = segment({ id: 9, start_local: "2026-11-19T00:00", end_local: "2026-11-19T00:00", details: { time_unknown: "yes" } });
    expect(nextUp([trip([untimedFlight, ...london.segments])], now)).toMatchObject({ state: "next", segment: { id: 1 } });
    expect(nextUp([trip([untimedFlight])], now)).toBeNull();
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

describe("hotel brand and place", () => {
  it("reads the city and state from an address", () => {
    expect(cityState("1 Quay Street, London")).toBe("London");
    expect(cityState("100 Example Blvd, Fort Lauderdale, FL 33301, USA")).toBe("Fort Lauderdale, FL");
    expect(cityState("100 Example Blvd, Suite 4, Miami, FL 33101")).toBe("Miami, FL");
    expect(cityState("10 Rue Exemple, 75001 Paris, France")).toBe("Paris, France");
    expect(cityState("Somewhere")).toBe("");
    expect(cityState("100 Example Blvd, USA")).toBe("");
    expect(cityState(undefined)).toBe("");
  });

  it("shows the brand with its city, and the full name when there is no brand", () => {
    const place = segment({ kind: "hotel", origin: "Hyatt Place Example Beach Convention Center", hotel_brand: "Hyatt Place", details: { address: "100 Example Blvd, Fort Lauderdale, FL 33301, USA", room: "412" } });
    expect(upcomingTitle(place)).toBe("Hyatt Place");
    expect(subline(place, true)).toBe("Fort Lauderdale, FL · 412");
    expect(headline(place)).toBe("Hyatt Place Example Beach Convention Center");
    expect(subline(place)).toBe("100 Example Blvd, Fort Lauderdale, FL 33301, USA · 412");
    const plain = segment({ kind: "hotel", origin: "Harbour Hotel", details: { address: "1 Quay Street, London" } });
    expect(upcomingTitle(plain)).toBe("Harbour Hotel");
    expect(subline(plain, true)).toBe("");
    expect(upcomingTitle(segment({ origin: "JFK", destination: "LHR", hotel_brand: "Hyatt Place" }))).toBe("JFK → LHR");
  });
});

describe("wording", () => {
  it("names a segment and describes it", () => {
    expect(headline(out)).toBe("JFK → LHR");
    expect(subline(out)).toBe("American Airlines AA 101 · Terminal 8");
    expect(subline({ ...out, details: { ...out.details, aircraft: "Boeing 737" } })).toBe("American Airlines AA 101 · Boeing 737 · Terminal 8");
    expect(headline(stay)).toBe("Harbour Hotel");
    expect(subline(stay)).toBe("1 Quay Street, London");
    expect(subline({ ...out, details: { ...out.details, seat: "12A", cabin: "Economy" } })).toBe("American Airlines AA 101 · Terminal 8 · Seat 12A · Economy");
    expect(subline({ ...out, details: { ...out.details, seat: "12A", cabin: "Economy" } }, true)).toBe("American Airlines AA 101 · Terminal 8 · Seat 12A");
    expect(subline({ ...stay, details: { address: "1 Quay Street, London", room: "412" } })).toBe("1 Quay Street, London · 412");
    expect(subline({ ...stay, details: { address: "1 Quay Street, London", room: "412" } }, true)).toBe("412");
    expect(subline(stay, true)).toBe("");
    expect(headline(segment({ kind: "car", provider: "Hertz", origin: "SFO airport" }))).toBe("Hertz · SFO airport");
    expect(headline(segment({ kind: "train", origin: "NYP", destination: "BOS" }))).toBe("NYP → BOS");
    expect(headline(segment({ kind: "hotel", origin: null, provider: null }))).toBe("Hotel stay");
    const ship = segment({ kind: "cruise", provider: "Example Cruise Line", origin: "Miami", details: { ship: "Example Voyager", room: "9214", deck: "9" } });
    expect(headline(ship)).toBe("Example Voyager · Miami");
    expect(subline(ship)).toBe("Example Cruise Line · Cabin 9214 · Deck 9");
    expect(headline(segment({ kind: "cruise", origin: null, provider: null, details: {} }))).toBe("Cruise");
    expect([START_WORD.cruise, END_WORD.cruise]).toEqual(["Embarks", "Disembarks"]);
  });
});

describe("loyalty on a booking", () => {
  const jane = { id: 1, person_id: 1, name: "Jane Doe", seat: null };
  it("knows the program a provider's name belongs to", () => {
    expect(programFor(out)).toBe("American AAdvantage");
    expect(programFor(stay)).toBe("Marriott Bonvoy");
    expect(programFor(segment({ kind: "car", provider: "Hertz" }))).toBe("Hertz Gold Plus Rewards");
    expect(programFor(segment({ provider: "Example Air" }))).toBeNull();
    expect(programFor(segment({ provider: null }))).toBeNull();
    expect(programFor(segment({ kind: "train", provider: "Amtrak" }))).toBeNull();
    expect(programFor(segment({ kind: "hotel", provider: "International Inn" }))).toBeNull();
    expect(programFor(segment({ kind: "hotel", provider: "United Suites" }))).toBeNull();
    expect(programFor(segment({ kind: "car", provider: "National Car Rental" }))).toBe("National Emerald Club");
    expect(programFor(segment({ provider: "Americana Air" }))).toBeNull();
  });
  it("finds the traveller's number for it, or says they have none, or that the name isn't matched", () => {
    const mine = membership();
    expect(membershipFor(out, jane, [mine, membership({ id: 12, person_id: 2 })])).toBeNull();
    expect(membershipFor(out, jane, [membership({ program: "Delta SkyMiles" })])).toBeNull();
    expect(membershipFor(out, { id: 2, person_id: null, name: "DOE/MIA MISS", seat: null }, [mine])).toEqual({ state: "unmatched" });
    expect(membershipFor(segment({ provider: "Example Air" }), jane, [mine])).toBeNull();
  });
  it("finds a car renter's number for the rental brand, or says they have none", () => {
    const hertz = membership({ program: "Hertz Gold Plus Rewards" });
    const rental = segment({ kind: "car", provider: "Hertz", booked_by: 1 });
    expect(membershipFor(rental, jane, [hertz])).toEqual({ state: "found", entry: hertz });
    expect(membershipFor(rental, jane, [])).toEqual({ state: "none", program: "Hertz Gold Plus Rewards" });
  });
  it("asks a car renter's party for a number only of whoever booked, and shows one anyone has", () => {
    const hertz = membership({ program: "Hertz Gold Plus Rewards" });
    const rental = segment({ kind: "car", provider: "Hertz", booked_by: 1 });
    const sam = { id: 2, person_id: 2, name: "Sam Doe", seat: null };
    expect(membershipFor(rental, sam, [])).toBeNull();
    expect(membershipFor(rental, { id: 3, person_id: null, name: "DOE/MIA MISS", seat: null }, [])).toBeNull();
    const hers = membership({ id: 12, person_id: 2, program: "Hertz Gold Plus Rewards" });
    expect(membershipFor(rental, sam, [hertz, hers])).toEqual({ state: "found", entry: hers });
  });
  it("asks a hotel guest for a number only if they booked the room, and shows one anyone has", () => {
    const sam = { id: 2, person_id: 2, name: "Sam Doe", seat: null };
    const mia = { id: 3, person_id: null, name: "DOE/MIA MISS", seat: null };
    const room = segment({ kind: "hotel", provider: "Marriott", booked_by: 1 });
    const bonvoy = membership({ program: "Marriott Bonvoy" });
    expect(membershipFor(room, jane, [])).toEqual({ state: "none", program: "Marriott Bonvoy" });
    expect(membershipFor(room, jane, [bonvoy])).toEqual({ state: "found", entry: bonvoy });
    expect(membershipFor(room, sam, [])).toBeNull();
    expect(membershipFor(room, mia, [bonvoy])).toBeNull();
    const hers = membership({ id: 12, person_id: 2, program: "Marriott Bonvoy" });
    expect(membershipFor(room, sam, [bonvoy, hers])).toEqual({ state: "found", entry: hers });
    expect(membershipFor({ ...room, booked_by: null }, jane, [])).toBeNull();
    expect(membershipFor(segment({ provider: "American Airlines", booked_by: 1 }), sam, [])).toBeNull();
    expect(membershipFor(segment({ provider: "American Airlines", booked_by: 1 }), mia, [])).toEqual({ state: "unmatched" });
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
  const mine = segment({ id: 1, confirmation: "AAAAAA", details: { flight_number: "AA 101" } });
  const theirs = segment({ id: 2, confirmation: "BBBBBB", details: { flight_number: "AA0101" }, travelers: [{ id: 5, person_id: 2, name: "Sam Doe", seat: null }] });

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

describe("untimed", () => {
  it("is an imported flight whose file gave no times", () => {
    expect(untimed(segment({ details: { time_unknown: "yes" } }))).toBe(true);
    expect(untimed(segment({ details: { flight_number: "DL1001" } }))).toBe(false);
  });
});

describe("tripKinds", () => {
  it("lists what a trip holds once each, in a fixed order, and not what was cancelled", () => {
    const t = trip([segment({ id: 1, kind: "hotel" }), segment({ id: 2, kind: "flight" }), segment({ id: 3, kind: "flight" }), segment({ id: 4, kind: "car", status: "cancelled" }), segment({ id: 5, kind: "cruise" })]);
    expect(tripKinds(t)).toEqual(["flight", "hotel", "cruise"]);
  });
  it("still shows what a trip was when everything on it is cancelled, and nothing for an empty trip", () => {
    expect(tripKinds(trip([segment({ kind: "train", status: "cancelled" })]))).toEqual(["train"]);
    expect(tripKinds(trip([]))).toEqual([]);
  });
});

describe("the order of a day's items", () => {
  const hotel = segment({ id: 1, kind: "hotel", origin: "Harbour Hotel", start_local: "2026-11-05T15:00", end_local: "2026-11-08T11:00" });
  const car = segment({ id: 2, kind: "car", origin: "Miami Airport", provider: "Hertz", start_local: "2026-11-05T14:00", end_local: "2026-11-08T08:00" });
  const flight = segment({ id: 3, kind: "flight", origin: "MIA", destination: "MSP", start_local: "2026-11-08T09:30", end_local: "2026-11-08T12:45" });
  const last = (segments: Parameters<typeof trip>[0]) => tripDays(trip(segments)).at(-1)!.items.map((i) => `${i.segment.id}:${i.role}`);

  it("puts the check-out before the car's return and the car's return before the flight, whatever the times say", () => {
    expect(last([hotel, car, flight])).toEqual(["1:end", "2:end", "3:start"]);
  });
  it("keeps each item's own time, only changing where it sits", () => {
    const items = tripDays(trip([hotel, car, flight])).at(-1)!.items;
    expect(items[0].segment.end_local).toBe("2026-11-08T11:00");
  });
  it("leaves the order by time when nothing is leaving", () => {
    const stay = segment({ id: 4, kind: "hotel", start_local: "2026-11-05T15:00", end_local: "2026-11-08T11:00" });
    const pickup = segment({ id: 5, kind: "car", start_local: "2026-11-08T13:00", end_local: "2026-11-09T09:00" });
    const dinner = segment({ id: 6, kind: "train", start_local: "2026-11-08T18:00", end_local: "2026-11-08T19:00" });
    const onThe8th = tripDays(trip([stay, pickup, dinner])).find((d) => d.date === "2026-11-08")!.items.map((i) => `${i.segment.id}:${i.role}`);
    expect(onThe8th).toEqual(["4:end", "5:start", "6:start"]);
  });
  it("is not moved by a cancelled flight", () => {
    const cancelled = { ...flight, status: "cancelled" as const, start_local: "2026-11-08T07:00" };
    expect(last([hotel, { ...car, end_local: "2026-11-08T12:00" }, cancelled])).toEqual(["3:start", "1:end", "2:end"]);
  });
  it("leaves other days alone", () => {
    expect(tripDays(trip([hotel, car, flight])).map((d) => d.date)).toEqual(["2026-11-05", "2026-11-08"]);
  });
});

describe("the check-in button", () => {
  const flight = segment({ id: 9, start_local: "2026-11-20T19:00", start_zone: NY, end_local: "2026-11-21T07:10", end_zone: LON });
  const dep = at("2026-11-20T19:00", NY), HOUR = 3_600_000;
  it("says Check in from exactly 24 hours before departure until it departs", () => {
    expect(appWord(flight, dep - 24 * HOUR, true)).toBe("Check in");
    expect(appWord(flight, dep - 24 * HOUR, false)).toBe("Check in");
    expect(appWord(flight, dep - 1, true)).toBe("Check in");
  });
  it("keeps its old label before the window and from departure", () => {
    expect(appWord(flight, dep - 24 * HOUR - 1, true)).toBe("Open in app");
    expect(appWord(flight, dep - 24 * HOUR - 1, false)).toBe("Manage booking");
    expect(appWord(flight, dep, true)).toBe("Open in app");
    expect(appWord(flight, dep + HOUR, false)).toBe("Manage booking");
  });
  it("is only for a flight that is not cancelled and has times", () => {
    const now = dep - HOUR;
    expect(checkInOpen({ ...flight, status: "cancelled" }, now)).toBe(false);
    expect(checkInOpen({ ...flight, kind: "train" }, now)).toBe(false);
    expect(checkInOpen({ ...flight, details: { time_unknown: "yes" } }, now)).toBe(false);
  });
});

describe("the pass headline", () => {
  const flight = segment({ id: 9, start_local: "2026-11-20T19:00", start_zone: NY, end_local: "2026-11-21T07:10", end_zone: LON });
  const dep = at("2026-11-20T19:00", NY), arr = at("2026-11-21T07:10", LON), HOUR = 3_600_000;
  it("uses the same 24 hours as the check-in reminder", () => { expect(CHECK_IN_WINDOW_HOURS).toBe(24); });
  it("counts down to check-in more than 24 hours out", () => {
    expect(passHeadline(flight, dep - 30 * HOUR)).toBe("Check-in opens in 6 h");
    expect(passHeadline(flight, dep - 24 * HOUR - 60_000)).toBe("Check-in opens in 1 min");
  });
  it("is open from exactly 24 hours before departure", () => {
    expect(passHeadline(flight, dep - 24 * HOUR)).toBe("Check-in is open, departs in 1 day");
    expect(passHeadline(flight, dep - 24 * HOUR + 60_000)).toBe("Check-in is open, departs in 23 h 59 min");
    expect(passHeadline(flight, dep - 3 * HOUR)).toBe("Check-in is open, departs in 3 h");
  });
  it("says now rather than in now in the last minute", () => {
    expect(passHeadline(flight, dep - 20_000)).toBe("Check-in is open, departing now");
    expect(passHeadline(flight, arr - 20_000)).toBe("Under way, arriving now");
  });
  it("is under way from departure and landed from arrival", () => {
    expect(passHeadline(flight, dep)).toBe("Under way, arrives in 7 h 10 min");
    expect(passHeadline(flight, arr - 70 * 60_000)).toBe("Under way, arrives in 1 h 10 min");
    expect(passHeadline(flight, arr)).toBe("Landed");
    expect(passHeadline(flight, arr + 5 * HOUR)).toBe("Landed");
  });
  it("says so for a flight with no times, and never reads a cancelled one as current", () => {
    expect(passHeadline(segment({ details: { time_unknown: "yes" } }), dep)).toBe("Time not recorded");
    expect(passHeadline(segment({ status: "cancelled" }), dep - 3 * HOUR)).toBe("Cancelled");
    expect(passHeadline(segment({ status: "cancelled" }), dep + HOUR)).toBe("Cancelled");
  });
  it("keeps the words stays, cars, trains and cruises already have", () => {
    expect(passHeadline(stay, at("2026-11-21T10:00", LON))).toBe("Check-in in 5 h");
    expect(passHeadline(stay, at("2026-11-23T10:00", LON))).toBe("Check-out in 4 days");
    expect(passHeadline(stay, at("2026-11-27T10:00", LON))).toBe("Checked out");
    expect(passHeadline(segment({ kind: "car" }), dep - HOUR)).toBe("Pick-up in 1 h");
    expect(passHeadline(segment({ kind: "train" }), dep + HOUR)).toBe("Arrives in 6 h 10 min");
    expect(passHeadline(segment({ kind: "cruise" }), arr + HOUR)).toBe("Disembarked");
  });
});

describe("the route progress", () => {
  const flight = segment({ start_local: "2026-11-20T19:00", start_zone: NY, end_local: "2026-11-21T07:10", end_zone: LON });
  const dep = at("2026-11-20T19:00", NY), arr = at("2026-11-21T07:10", LON);
  it("waits at the origin, moves along the flight and rests at the destination", () => {
    expect(routeProgress(flight, dep - 5_000_000)).toBe(0);
    expect(routeProgress(flight, dep)).toBe(0);
    expect(routeProgress(flight, dep + (arr - dep) / 2)).toBe(0.5);
    expect(routeProgress(flight, arr)).toBe(1);
    expect(routeProgress(flight, arr + 5_000_000)).toBe(1);
  });
  it("counts a flight across the date line by instants, not by the clock", () => {
    const over = segment({ origin: "SYD", destination: "LAX", start_local: "2026-11-20T10:00", start_zone: "Australia/Sydney", end_local: "2026-11-20T06:00", end_zone: LA });
    const from = at("2026-11-20T10:00", "Australia/Sydney"), to = at("2026-11-20T06:00", LA);
    expect(to).toBeGreaterThan(from);
    expect(routeProgress(over, (from + to) / 2)).toBeCloseTo(0.5, 5);
  });
  it("keeps the plane at the origin for a segment with no times", () => {
    expect(routeProgress(segment({ details: { time_unknown: "yes" } }), dep + 3_600_000)).toBe(0);
    expect(routeProgress(segment({ start_local: "soon" }), dep)).toBe(0);
  });
});

describe("seatsInOrder", () => {
  it("puts seats in order by row, then letter, without repeats", () => {
    expect(seatsInOrder("35C, 36D, 36E, 35A, 35B")).toBe("35A, 35B, 35C, 36D, 36E");
    expect(seatsInOrder("10A, 9B, 9A, 9A")).toBe("9A, 9B, 10A");
  });
  it("leaves one seat, no seat and a seat without a letter as they are", () => {
    expect(seatsInOrder("14C")).toBe("14C");
    expect(seatsInOrder("31")).toBe("31");
    expect(seatsInOrder("")).toBe("");
  });
  it("orders the seats in a flight's subline", () => {
    expect(subline(segment({ kind: "flight", provider: "Example Air", details: { flight_number: "EA 1", seat: "12B, 12A" } }), true)).toContain("Seat 12A, 12B");
  });
});
