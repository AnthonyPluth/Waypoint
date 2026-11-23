// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));

import { api } from "$lib/api";
import { forgetAirportZones } from "$lib/airport-zones";
import type { Segment } from "$lib/api-types";
import { instant } from "$lib/trips";
import { segment } from "../../test/fixtures";
import FlightHome from "./FlightHome.svelte";

const NY = "America/New_York";
const LISBON = "Europe/Lisbon";
const AIRPORTS: Record<string, object> = {
  BOS: { code: "BOS", name: "Logan International Airport", city: "Boston", country: "US", zone: NY },
  JFK: { code: "JFK", name: "John F. Kennedy International Airport", city: "New York", country: "US", zone: NY },
  LIS: { code: "LIS", name: "Humberto Delgado Airport", city: "Lisbon", country: "PT", zone: LISBON },
};
const SEATS = (a: string, b: string, c: string) => [
  { id: 1, person_id: 1, name: "Mara Quist", seat: a }, { id: 2, person_id: 2, name: "Tomas Reyes", seat: b }, { id: 3, person_id: 3, name: "Ines Vale", seat: c },
];
const first = (extra: Partial<Segment> = {}) => segment({
  id: 1, provider: "Aurora Air", origin: "BOS", destination: "JFK", start_local: "2026-03-09T06:10", start_zone: NY, end_local: "2026-03-09T07:28", end_zone: NY,
  details: { flight_number: "AU1402", terminal: "B" }, travelers: SEATS("14A", "14B", "22C"), ...extra,
});
const second = (extra: Partial<Segment> = {}) => segment({
  id: 2, provider: "Aurora Air", origin: "JFK", destination: "LIS", start_local: "2026-03-09T09:40", start_zone: NY, end_local: "2026-03-09T21:15", end_zone: LISBON,
  details: { flight_number: "AU212", terminal: "4" }, travelers: SEATS("31A", "31B", "31C"), ...extra,
});
const at = (local: string) => instant(local, NY);
const flat = (el: Element | null | undefined) => el?.textContent?.replace(/\s+/g, " ").trim() ?? "";

const draw = (leg: Segment, now: number, extra: Record<string, unknown> = {}) =>
  render(FlightHome, { segment: leg, liveOn: true, now, eyebrow: "Next up", tripName: "Lisbon", ...extra });

beforeEach(() => {
  forgetAirportZones();
  vi.mocked(api).mockReset().mockImplementation(async (path: string) => {
    const found = AIRPORTS[path.split("/").pop() ?? ""];
    if (!found) throw new Error("No such airport");
    return found;
  });
});

describe("the hero for a flight that has another on the same booking", () => {
  it("draws only its own flight, with no stop, no journey and no Then line, before the first flight", async () => {
    const { container } = draw(first(), at("2026-03-07T05:00"));
    const card = await screen.findByRole("article");
    await waitFor(() => expect(card.querySelector("[data-sentence]")).toHaveTextContent("Your flight to New York"));
    expect(card.querySelector("[data-carrier]")).toHaveTextContent("Aurora Air AU 1402");
    expect(card.querySelector("[data-code='origin']")).toHaveTextContent("BOS");
    expect(card.querySelector("[data-code='destination']")).toHaveTextContent("JFK");
    expect(flat(card.querySelector("[data-big]"))).toBe("Departs 6:10 AM");
    expect(card).not.toHaveAttribute("data-connection");
    expect(card.querySelector("[data-then]")).toBeNull();
    expect(card.querySelector("[data-arc-note]")).toBeNull();
    expect(container.querySelector("[data-stop]")).toBeNull();
  });

  it("draws the second flight as its own hero from its own origin, even while the first has landed", async () => {
    draw(second(), at("2026-03-09T07:50"));
    const card = await screen.findByRole("article");
    await waitFor(() => expect(card.querySelector("[data-sentence]")).toHaveTextContent("Your flight to Lisbon"));
    expect(card.querySelector("[data-carrier]")).toHaveTextContent("Aurora Air AU 212");
    expect(card.querySelector("[data-code='origin']")).toHaveTextContent("JFK");
    expect(card.querySelector("[data-code='destination']")).toHaveTextContent("LIS");
    expect(card.querySelector("[data-top]")).toHaveTextContent("In 1 hour");
    expect(card.querySelector("[data-then]")).toBeNull();
  });
});
