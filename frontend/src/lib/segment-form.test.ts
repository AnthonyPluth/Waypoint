import { describe, expect, it } from "vitest";
import { blank, body, DETAILS, draftOf, problem, type Draft, type Kind } from "./segment-form";
import { segment } from "../test/fixtures";

/** A flight that's ready to send, with `extra` changing what a test cares about. */
const flight = (extra: Partial<Draft> = {}): Draft => ({ ...blank(), origin: "JFK", destination: "LHR", start_local: "2026-11-20T19:00", end_local: "2026-11-21T07:10", people: [1], ...extra });
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
    expect(problem(hotel({ start_zone: "" }))).toBe("Enter the time zone of the place (for example America/New_York)");
    expect(problem(hotel({ start_zone: "Mars/Olympus" }))).toBe("The time zone “Mars/Olympus” isn’t one Waypoint knows (use a name like America/New_York)");
    expect(problem(flight({ end_zone: "Nowhere" }))).toMatch(/isn’t one Waypoint knows/);
  });
  it("catches an end before the start, comparing at each place's zone", () => {
    expect(problem(hotel({ end_local: "2026-11-21T14:00", start_local: "2026-11-21T15:00" }))).toBe("This ends before it starts (times are compared at their own places’ zones)");
    // A flight's zones come from its airports, so an arrival that reads earlier on the clock isn't judged here.
    expect(problem(flight({ origin: "NRT", destination: "LAX", start_local: "2026-11-20T17:00", end_local: "2026-11-20T10:00" }))).toBeNull();
    // With zones given it is: Tokyo 17:00 is 08:00 UTC, so 10:00 in Los Angeles (18:00 UTC) is fine, 00:00 isn't.
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
      start_local: "2026-11-20T19:00", end_local: "2026-11-21T07:10", details: { flight_number: "AA 101" }, manage_url: null, travelers: [{ person_id: 1 }],
    });
    expect(body(flight({ start_zone: "Asia/Tokyo" }))).toMatchObject({ start_zone: "Asia/Tokyo" });
    expect(body(flight())).not.toHaveProperty("start_zone");
  });
  it("sends a stay's zone for both ends unless the end has its own", () => {
    expect(body(hotel())).toMatchObject({ start_zone: "Europe/London", end_zone: "Europe/London", origin: "Harbour Hotel" });
    expect(body(hotel({ end_zone: "Europe/Paris" }))).toMatchObject({ end_zone: "Europe/Paris" });
  });
  it("keeps travellers known only by their printed name, and details it has no field for", () => {
    const sent = body(hotel({ printed: ["DOE/MIA MISS"], details: { address: "1 Quay Street", seat: "12A" } }));
    expect(sent.travelers).toEqual([{ person_id: 1 }, { person_id: null, name: "DOE/MIA MISS" }]);
    expect(sent.details).toEqual({ address: "1 Quay Street", seat: "12A" });
  });
  it("starts an edit from what's there, leaving a flight's airport-given zones empty", () => {
    const d = draftOf(segment({ travelers: [{ id: 1, person_id: 1, name: "Jane Doe" }, { id: 2, person_id: null, name: "DOE/MIA MISS" }] }));
    expect(d).toMatchObject({ id: 1, tripId: 1, origin: "JFK", start_zone: "", end_zone: "", people: [1], printed: ["DOE/MIA MISS"] });
    expect(draftOf(segment({ kind: "hotel", start_zone: "Europe/London", end_zone: "Europe/London" }))).toMatchObject({ start_zone: "Europe/London" });
  });
  it("keeps an imported flight untimed until a person sets its times", () => {
    const imported = segment({ start_local: "2025-03-08T00:00", end_local: "2025-03-08T03:00", details: { time_unknown: "yes", seat: "14C" } });
    const d = draftOf(imported);
    expect(body(d).details).toEqual({ time_unknown: "yes", seat: "14C" });
    expect(body({ ...d, details: { ...d.details, seat: "15A" } }).details).toEqual({ time_unknown: "yes", seat: "15A" });   // other edits keep it
    expect(body({ ...d, start_local: "2025-03-08T09:30" }).details).toEqual({ seat: "14C" });
    expect(body(draftOf(segment({ details: { seat: "14C" } }))).details).toEqual({ seat: "14C" });
  });
});

describe("the fields each kind shows", () => {
  it("has the address, phone and room for a hotel, the pick-up address, phone and class for a car, and terminal, seat and cabin for a flight", () => {
    const names = (k: Kind) => DETAILS[k].map(([, label]) => label);
    expect(names("hotel")).toEqual(["Address", "Room", "Phone"]);
    expect(names("car")).toEqual(["Pick-up address", "Car class", "Phone"]);
    expect(names("flight")).toEqual(expect.arrayContaining(["Terminal", "Seat", "Cabin"]));
  });

  it("round-trips an address with its lines, and refuses one over the limit", () => {
    const d = draftOf(segment({ kind: "hotel", origin: "Harbour Hotel", destination: null, start_zone: "Europe/London", end_zone: "Europe/London",
      details: { address: "1 Quay Street\nLondon E1 0AA" }, travelers: [{ id: 1, person_id: 1, name: "Jane Doe" }] }));
    expect(body({ ...d, details: { ...d.details, address: "  3 Mill Lane\nLondon  " } }).details?.address).toBe("3 Mill Lane\nLondon");
    expect(problem(d)).toBeNull();
    expect(problem({ ...d, details: { address: "x".repeat(301) } })).toMatch(/at most 300/);
  });
});
