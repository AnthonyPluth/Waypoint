// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));

import { api } from "$lib/api";
import type { TripSummary as Reply } from "$lib/api-types";
import TripSummary from "./TripSummary.svelte";

const kinds = { flight: 0, hotel: 0, car: 0, train: 0, cruise: 0, parking: 0, visit: 0 };
const reply = (extra: Partial<Reply> = {}): Reply => ({
  days: 15, nights: 14, distance_km: 2066.3, flight_km: 0, road_km: 2066.3, road_estimated: false, states: [], countries: [], photos: { total: 0, inferred: 0 }, kinds, ...extra,
});

let summary: Reply;
let unit: "mi" | "km" | Error;
function serve() {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === "/api/distance-unit") { if (unit instanceof Error) throw unit; return { distance_unit: unit }; }
    if (String(path).endsWith("/summary")) return summary;
    throw new Error(`unexpected ${path}`);
  });
}

const line = () => screen.findByTestId("trip-summary");
const term = (name: string) => screen.getByText(name, { selector: "dt" });
const value = (name: string) => term(name).nextElementSibling as HTMLElement;
const settled = () => waitFor(() => expect(vi.mocked(api).mock.calls.length).toBeGreaterThanOrEqual(2));

beforeEach(() => {
  vi.mocked(api).mockReset();
  summary = reply();
  unit = "mi";
  serve();
});
afterEach(() => vi.restoreAllMocks());

describe("TripSummary", () => {
  it("shows days, nights, distance, places and photos, each with its term for a screen reader", async () => {
    summary = reply({ states: ["Arizona", "Colorado"], countries: ["United States"], photos: { total: 248, inferred: 23 } });
    render(TripSummary, { tripId: 1 });
    expect(await line()).toHaveAttribute("aria-label", "Trip summary");
    expect(value("Days")).toHaveTextContent("15 days");
    expect(value("Nights away")).toHaveTextContent("14 nights");
    expect(value("Distance")).toHaveTextContent("1,284 mi");
    expect(value("Places")).toHaveTextContent("Arizona, Colorado");
    expect(value("Photos")).toHaveTextContent("248 photos (23 placed from the itinerary)");
    expect(screen.getByTestId("trip-summary").querySelectorAll("button, a")).toHaveLength(0);
  });

  it("shows the distance in kilometres when that is the household’s unit", async () => {
    unit = "km";
    summary = reply({ distance_km: 2940.4 });
    render(TripSummary, { tripId: 1 });
    await line();
    expect(value("Distance")).toHaveTextContent(/^2,940 km$/);
  });

  it("says “about” when part of the distance is a straight line between stays, in either unit", async () => {
    summary = reply({ road_estimated: true });
    const { unmount } = render(TripSummary, { tripId: 1 });
    await line();
    expect(value("Distance")).toHaveTextContent(/^about 1,284 mi$/);
    unmount();
    unit = "km";
    render(TripSummary, { tripId: 1 });
    await screen.findByTestId("trip-summary");
    expect(value("Distance")).toHaveTextContent(/^about 2,066 km$/);
  });

  it("uses the singular for one day, one night and one photo, and leaves out what is zero", async () => {
    summary = reply({ days: 1, nights: 0, distance_km: 0, states: ["Oregon"], countries: ["United States"], photos: { total: 1, inferred: 0 } });
    render(TripSummary, { tripId: 1 });
    await line();
    expect(value("Days")).toHaveTextContent(/^1 day$/);
    expect(value("Photos")).toHaveTextContent(/^1 photo$/);
    expect(screen.queryByText("Nights away", { selector: "dt" })).toBeNull();
    expect(screen.queryByText("Distance", { selector: "dt" })).toBeNull();
    const text = screen.getByTestId("trip-summary").textContent ?? "";
    expect(text).not.toMatch(/\b0 nights|No photos|placed from the itinerary/);
  });

  it("lists countries when there are no US states, and each place once in full without a control to expand them", async () => {
    summary = reply({ states: [], countries: ["Portugal", "Spain"] });
    render(TripSummary, { tripId: 1 });
    await line();
    expect(value("Places")).toHaveTextContent(/^Portugal, Spain$/);
    const many = ["Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware", "Florida", "Georgia"];
    summary = reply({ states: many, countries: ["United States"] });
    render(TripSummary, { tripId: 2 });
    await waitFor(() => expect(screen.getAllByTestId("trip-summary")).toHaveLength(2));
    const second = screen.getAllByTestId("trip-summary")[1];
    expect(within(second).getByText(many.join(", "), { selector: "dd" })).toBeTruthy();
    expect(within(second).queryAllByRole("button")).toHaveLength(0);
  });

  it("names the United States only when no state is known, and other countries beside the states", async () => {
    summary = reply({ states: [], countries: ["United States"] });
    const { unmount } = render(TripSummary, { tripId: 1 });
    await line();
    expect(value("Places")).toHaveTextContent(/^United States$/);
    unmount();
    summary = reply({ states: ["Idaho", "Montana"], countries: ["Canada", "United States"] });
    render(TripSummary, { tripId: 1 });
    await screen.findByTestId("trip-summary");
    expect(value("Places")).toHaveTextContent(/^Idaho, Montana, Canada$/);
  });

  it("shows nothing when every figure is zero and there are no photos or places", async () => {
    summary = reply({ days: 0, nights: 0, distance_km: 0 });
    const { container } = render(TripSummary, { tripId: 1 });
    await settled();
    await new Promise((r) => setTimeout(r));
    expect(container.querySelector("[data-testid=trip-summary]")).toBeNull();
    expect(screen.queryByRole("term")).toBeNull();
  });

  it("shows only photos when that is all a trip has", async () => {
    summary = reply({ days: 0, nights: 0, distance_km: 0, photos: { total: 12, inferred: 0 } });
    render(TripSummary, { tripId: 1 });
    await line();
    expect(screen.getAllByText(/./, { selector: "dt" }).map((e) => e.textContent)).toEqual(["Photos"]);
  });

  it("leaves the distance out, rather than guess a unit, when the unit can’t be read", async () => {
    unit = new Error("no");
    render(TripSummary, { tripId: 1 });
    await line();
    expect(value("Days")).toHaveTextContent("15 days");
    expect(screen.queryByText("Distance", { selector: "dt" })).toBeNull();
  });

  it("shows nothing when the numbers can’t be read, and drops what was on screen for another trip", async () => {
    const { rerender, container } = render(TripSummary, { tripId: 1 });
    await line();
    vi.mocked(api).mockImplementation(async (path) => { if (path === "/api/distance-unit") return { distance_unit: "mi" }; throw new Error("down"); });
    await rerender({ tripId: 2 });
    await waitFor(() => expect(container.querySelector("[data-testid=trip-summary]")).toBeNull());
  });

  it("asks once per trip and again for another, and an answer that arrives late for the earlier trip is dropped", async () => {
    let release: (r: Reply) => void = () => {};
    vi.mocked(api).mockImplementation((path) => {
      if (path === "/api/distance-unit") return Promise.resolve({ distance_unit: "mi" }) as never;
      if (path === "/api/trips/1/summary") return new Promise((r) => { release = r as never; }) as never;
      return Promise.resolve(reply({ days: 3, nights: 2, distance_km: 0 })) as never;
    });
    const { rerender } = render(TripSummary, { tripId: 1 });
    await waitFor(() => expect(vi.mocked(api).mock.calls.some(([p]) => p === "/api/trips/1/summary")).toBe(true));
    await rerender({ tripId: 2 });
    expect(await screen.findByText("3 days", { selector: "dd" })).toBeTruthy();
    release(reply({ days: 99 }));
    await new Promise((r) => setTimeout(r, 10));
    expect(screen.queryByText("99 days")).toBeNull();
    expect(value("Days")).toHaveTextContent("3 days");
    expect(vi.mocked(api).mock.calls.filter(([p]) => String(p).endsWith("/summary"))).toHaveLength(2);
  });

  it("asks again when the trip’s bookings change, keeping the line until the new answer arrives", async () => {
    const { rerender } = render(TripSummary, { tripId: 1, revision: "a" });
    await line();
    summary = reply({ days: 20 });
    await rerender({ tripId: 1, revision: "b" });
    expect(await screen.findByText("20 days", { selector: "dd" })).toBeTruthy();
    expect(vi.mocked(api).mock.calls.filter(([p]) => p === "/api/trips/1/summary")).toHaveLength(2);
  });
});
