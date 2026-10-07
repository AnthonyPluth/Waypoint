import { describe, expect, it } from "vitest";
import { blank, body, DETAILS, draftOf, problem, type Draft, type Kind } from "./segment-form";
import { segment } from "../test/fixtures";

const flight = (extra: Partial<Draft> = {}): Draft => ({ ...blank(), origin: "JFK", destination: "LHR", start_local: "2026-11-20T19:00", end_local: "2026-11-21T07:10", people: [1], ...extra });
const car = (extra: Partial<Draft> = {}): Draft => ({ ...blank(), kind: "car", origin: "Example Rental", start_local: "2026-11-21T15:00", end_local: "2026-11-27T10:00", start_zone: "Europe/London", people: [1], ...extra });
const hotel = (extra: Partial<Draft> = {}): Draft => ({ ...blank(), kind: "hotel", origin: "Harbour Hotel", start_local: "2026-11-21T15:00", end_local: "2026-11-27T10:00", start_zone: "Europe/London", people: [1], ...extra });

describe("the segment form's messages", () => {
  it("accepts a complete flight and a complete stay", () => {
    expect(problem(flight())).toBeNull();
    expect(problem(hotel())).toBeNull();
  });
  it("wants airport codes for a flight", () => {
    expect(problem(flight({ origin: "" }))).toBe("A flight’s origin is an airport code like JFK");
    expect(problem(flight({ origin: "New York" }))).toBe("A flight’s origin is an airport code like JFK");
    expect(problem(flight({ destination: "L" }))).toBe("A flight’s destination is an airport code like LHR");
  });
  it("wants a name for a stay, and both times", () => {
    expect(problem(hotel({ origin: " " }))).toBe("Enter the hotel’s name");
    expect(problem(hotel({ start_local: "" }))).toBe("Enter the check-in date and time");
    expect(problem(hotel({ end_local: "" }))).toBe("Enter the check-out date and time");
    expect(problem(flight({ start_local: "" }))).toBe("Enter when it starts");
    expect(problem(flight({ end_local: "" }))).toBe("Enter when it ends");
  });
  it("needs a time zone for anything but a flight, and one that exists", () => {
    expect(problem(car({ start_zone: "" }))).toBe("Enter the time zone of the place (for example America/New_York)");
    expect(problem(hotel({ start_zone: "Mars/Olympus" }))).toBe("The time zone “Mars/Olympus” isn’t one Waypoint knows (use a name like America/New_York)");
    expect(problem(flight({ end_zone: "Nowhere" }))).toMatch(/isn’t one Waypoint knows/);
  });
  it("catches an end before the start, comparing at each place's zone", () => {
    expect(problem(hotel({ end_local: "2026-11-21T14:00", start_local: "2026-11-21T15:00" }))).toBe("This ends before it starts (times are compared at their own places’ zones)");
    expect(problem(flight({ origin: "NRT", destination: "LAX", start_local: "2026-11-20T17:00", end_local: "2026-11-20T10:00" }))).toBeNull();
    const zones = { start_zone: "Asia/Tokyo", end_zone: "America/Los_Angeles" };
    expect(problem(flight({ ...zones, start_local: "2026-11-20T17:00", end_local: "2026-11-20T10:00" }))).toBeNull();
    expect(problem(flight({ ...zones, start_local: "2026-11-20T17:00", end_local: "2026-11-19T20:00" }))).toMatch(/ends before it starts/);
  });
  it("wants a manage link that is a web address, and someone travelling", () => {
    expect(problem(flight({ manage_url: "javascript:alert(1)" }))).toBe("The manage link must start with https:// or http://");
    expect(problem(flight({ manage_url: "https://example.com/manage" }))).toBeNull();
    expect(problem(flight({ people: [], printed: [] }))).toBe("Choose who’s travelling");
    expect(problem(flight({ people: [], printed: ["DOE/MIA MISS"] }))).toBeNull();
  });
});

describe("the request the form makes", () => {
  it("sends a flight's airport codes in capitals and its zones only if typed", () => {
    expect(body(flight({ origin: " jfk ", provider: " American Airlines ", confirmation: "", details: { flight_number: "AA 101", terminal: " " } }))).toEqual({
      kind: "flight", status: "confirmed", provider: "American Airlines", confirmation: null, origin: "JFK", destination: "LHR",
      start_local: "2026-11-20T19:00", end_local: "2026-11-21T07:10", details: { flight_number: "AA 101" }, manage_url: null, travelers: [{ person_id: 1, seat: null }],
    });
    expect(body(flight({ start_zone: "Asia/Tokyo" }))).toMatchObject({ start_zone: "Asia/Tokyo" });
    expect(body(flight())).not.toHaveProperty("start_zone");
  });
  it("sends a stay's one zone, and a rental's for both ends unless the end has its own", () => {
    expect(body(hotel())).toMatchObject({ start_zone: "Europe/London", origin: "Harbour Hotel" });
    expect(body(hotel())).not.toHaveProperty("end_zone");
    expect(body(hotel({ end_zone: "Europe/Paris" }))).not.toHaveProperty("end_zone");
    expect(body(car())).toMatchObject({ start_zone: "Europe/London", end_zone: "Europe/London" });
    expect(body(car({ end_zone: "Europe/Paris" }))).toMatchObject({ end_zone: "Europe/Paris" });
  });
  it("lets a stay leave its zone empty when it has an address to work it out from", () => {
    expect(problem(hotel({ start_zone: "", details: { address: "1 Quay Street, London" } }))).toBeNull();
    expect(body(hotel({ start_zone: "", details: { address: "1 Quay Street, London" } }))).toMatchObject({ start_zone: null });
    expect(problem(hotel({ start_zone: "" }))).toBe("Enter the time zone of the stay (for example America/New_York), or its address to work it out from");
    expect(problem(hotel({ start_zone: "Mars/Olympus" }))).toMatch(/isn’t one Waypoint knows/);
  });
  it("keeps travellers known only by their printed name, and details it has no field for", () => {
    const sent = body(hotel({ printed: ["DOE/MIA MISS"], details: { address: "1 Quay Street", seat: "12A" } }));
    expect(sent.travelers).toEqual([{ person_id: 1 }, { person_id: null, name: "DOE/MIA MISS" }]);
    expect(sent.details).toEqual({ address: "1 Quay Street", seat: "12A" });
  });
  it("starts an edit from what's there, leaving a flight's airport-given zones empty", () => {
    const d = draftOf(segment({ travelers: [{ id: 1, person_id: 1, name: "Jane Doe", seat: null }, { id: 2, person_id: null, name: "DOE/MIA MISS", seat: null }] }));
    expect(d).toMatchObject({ id: 1, tripId: 1, origin: "JFK", start_zone: "", end_zone: "", people: [1], printed: ["DOE/MIA MISS"] });
    expect(draftOf(segment({ kind: "hotel", start_zone: "Europe/London", end_zone: "Europe/London" }))).toMatchObject({ start_zone: "Europe/London" });
  });
  it("keeps an imported flight untimed until a person sets its times", () => {
    const imported = segment({ start_local: "2025-03-08T00:00", end_local: "2025-03-08T03:00", details: { time_unknown: "yes", seat: "14C" } });
    const d = draftOf(imported);
    expect(body(d).details).toEqual({ time_unknown: "yes" });
    expect(body(d).travelers).toEqual([{ person_id: 1, seat: "14C" }]);
    expect(body({ ...d, start_local: "2025-03-08T09:30" }).details).toEqual({});
    expect(body({ ...d, seats: { p1: "15A" } }).travelers).toEqual([{ person_id: 1, seat: "15A" }]);
  });
});

describe("a cruise", () => {
  const cruise = (extra: Partial<Draft> = {}): Draft => ({ ...blank(), kind: "cruise", origin: "Miami", destination: "Miami", start_local: "2026-03-01T16:30",
    end_local: "2026-03-08T07:00", start_zone: "America/New_York", people: [1], ...extra });
  const nassau = { name: " Nassau ", zone: "America/Nassau", arrive: "2026-03-02T08:00", depart: "2026-03-02T17:00" };

  it("is sent with its ports in order, trimmed, and none for a time left empty", () => {
    const sent = body(cruise({ itinerary: [nassau, { name: "Cozumel", zone: "America/Cancun", arrive: "", depart: "" }], details: { ship: "Example Voyager" } }));
    expect(sent.itinerary).toEqual([{ name: "Nassau", zone: "America/Nassau", arrive_local: "2026-03-02T08:00", depart_local: "2026-03-02T17:00" },
      { name: "Cozumel", zone: "America/Cancun", arrive_local: null, depart_local: null }]);
    expect(sent.details).toEqual({ ship: "Example Voyager" });
    expect(body(flight()).itinerary).toBeUndefined();
  });

  it("round-trips what the server gave", () => {
    const d = draftOf(segment({ kind: "cruise", origin: "Miami", destination: "Miami", start_zone: "America/New_York", end_zone: "America/New_York",
      itinerary: [{ name: "Nassau", zone: "America/Nassau", arrive_local: "2026-03-02T08:00", depart_local: null }], travelers: [{ id: 1, person_id: 1, name: "Jane Doe", seat: null }] }));
    expect(d.itinerary).toEqual([{ name: "Nassau", zone: "America/Nassau", arrive: "2026-03-02T08:00", depart: "" }]);
    expect(body(d).itinerary).toEqual([{ name: "Nassau", zone: "America/Nassau", arrive_local: "2026-03-02T08:00", depart_local: null }]);
  });

  it("says what is wrong with a port", () => {
    expect(problem(cruise({ itinerary: [nassau] }))).toBeNull();
    expect(problem(cruise({ itinerary: [{ ...nassau, name: " " }] }))).toBe("Name port 1");
    expect(problem(cruise({ itinerary: [{ ...nassau, zone: "" }] }))).toMatch(/Enter the time zone of Nassau/);
    expect(problem(cruise({ itinerary: [{ ...nassau, zone: "Nowhere/Land" }] }))).toMatch(/isn’t one Waypoint knows/);
    expect(problem(cruise({ itinerary: [{ ...nassau, arrive: "soon" }] }))).toBe("Enter Nassau’s arrival as a date and time");
    expect(problem(cruise({ itinerary: [{ ...nassau, depart: "2026-03-02T07:00" }] }))).toMatch(/can’t leave before it arrives/);
    expect(problem(cruise({ itinerary: Array.from({ length: 41 }, () => nassau) }))).toBe("Add at most 40 ports of call");
  });
});

describe("a seat for each traveller", () => {
  const two = (extra: Partial<Draft> = {}): Draft => ({ ...blank(), origin: "JFK", destination: "LHR", start_local: "2026-11-20T19:00", end_local: "2026-11-21T07:10", people: [1, 2], printed: ["DOE/MIA MISS"], ...extra });
  it("sends each traveller's own seat, trimmed, and none for an empty one", () => {
    expect(body(two({ seats: { p1: " 31a ", p2: "", nDOE_MIA: "x" } })).travelers).toEqual([
      { person_id: 1, seat: "31a" }, { person_id: 2, seat: null }, { person_id: null, name: "DOE/MIA MISS", seat: null }]);
    expect(body(two({ seats: { "nDOE/MIA MISS": "32A" } })).travelers?.at(-1)).toEqual({ person_id: null, name: "DOE/MIA MISS", seat: "32A" });
  });
  it("sends no seats for a booking that has none (a hotel's guests keep what they had)", () => {
    expect(body({ ...two(), kind: "hotel", origin: "Harbour Hotel", start_zone: "Europe/London" }).travelers).toEqual([
      { person_id: 1 }, { person_id: 2 }, { person_id: null, name: "DOE/MIA MISS" }]);
  });
  it("starts from each traveller's seat, and gives a booking's old seat to its one traveller only", () => {
    const jane = { id: 1, person_id: 1, name: "Jane Doe", seat: "12A" }, sam = { id: 2, person_id: 2, name: "Sam Doe", seat: null };
    expect(draftOf(segment({ details: { seat: "99Z" }, travelers: [jane, sam] })).seats).toEqual({ p1: "12A" });
    expect(body(draftOf(segment({ details: { seat: "99Z" }, travelers: [jane, sam] }))).details).toEqual({ seat: "99Z" });
    expect(draftOf(segment({ details: { seat: "99Z" }, travelers: [sam] })).seats).toEqual({ p2: "99Z" });
  });
  it("refuses a seat that is too long", () => {
    expect(problem(two({ seats: { p1: "x".repeat(11) } }))).toBe("A seat is at most 10 characters");
    expect(problem(two({ seats: { p1: "x".repeat(10) } }))).toBeNull();
  });
});

describe("the fields each kind shows", () => {
  it("has the address, phone and room for a hotel, the pick-up address, phone and class for a car, and terminal, seat and cabin for a flight", () => {
    const names = (k: Kind) => DETAILS[k].map(([, label]) => label);
    expect(names("hotel")).toEqual(["Address", "Room", "Phone"]);
    expect(names("car")).toEqual(["Pick-up address", "Car class", "Phone"]);
    expect(names("cruise")).toEqual(["Ship", "Cabin", "Deck", "Terminal address", "Phone"]);
    expect(names("flight")).toEqual(["Flight number", "Terminal", "Gate", "Cabin"]);
  });

  it("round-trips an address with its lines, and refuses one over the limit", () => {
    const d = draftOf(segment({ kind: "hotel", origin: "Harbour Hotel", destination: null, start_zone: "Europe/London", end_zone: "Europe/London",
      details: { address: "1 Quay Street\nLondon E1 0AA" }, travelers: [{ id: 1, person_id: 1, name: "Jane Doe", seat: null }] }));
    expect(body({ ...d, details: { ...d.details, address: "  3 Mill Lane\nLondon  " } }).details?.address).toBe("3 Mill Lane\nLondon");
    expect(problem(d)).toBeNull();
    expect(problem({ ...d, details: { address: "x".repeat(301) } })).toMatch(/at most 300/);
  });
});
