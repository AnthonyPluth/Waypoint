// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("$lib/review", async (orig) => ({ ...(await orig<typeof import("$lib/review")>()), svgToPng: vi.fn(async () => new Blob(["png"], { type: "image/png" })) }));

import { api } from "$lib/api";
import type { Stats } from "$lib/api-types";
import YearInReview from "./YearInReview.svelte";

const stats = (year: number | null): Stats => ({
  years: [2026], person: 1, year, distance_unit: "mi",
  flights: {
    count: 12, distance_km: 52000, air_seconds: 86400, countries: [], cabins: [], top_seat: null, seat_positions: { window: 0, aisle: 0, middle: 0, unknown: 0 },
    airports: [{ code: "JFK", name: "Canary Airport", city: null, country: "US", visits: 6, latitude: 40.64, longitude: -73.78 }, { code: "LHR", name: "Heathrow", city: null, country: "GB", visits: 4, latitude: 51.47, longitude: -0.45 }],
    airlines: [], routes: [{ a: "JFK", b: "LHR", flights: 4, distance_km: 5540, a_latitude: 40.64, a_longitude: -73.78, b_latitude: 51.47, b_longitude: -0.45, trips: [] }],
    longest: null, shortest: null, most_visited_airport: "JFK", busiest_month: null, times_around_earth: 1.3, moon_fraction: 0.1,
  },
  stays: { nights: 9, chains: [{ name: "Hotel Canarios", count: 2 }], cities: [], countries: [], count: 0, average_nights: 0, hotels: [], cities_by_nights: [], longest: null, most_visited_hotel: null, most_visited_city: null, busiest_month: null, pins: [] }, cars: { days: 0, companies: [] }, cruises: { count: 0, nights: 0, sea_days: 0, ports: 0, lines: [] },
  places: { countries: [{ name: "US", first_visit: year ? "2019-05-01" : "2019-05-01", visits: 3 }, { name: "GB", first_visit: "2026-03-14", visits: 1 }], cities: [] },
});

beforeEach(() => { vi.mocked(api).mockReset(); vi.mocked(api).mockResolvedValue(stats(null) as never); });
afterEach(() => { vi.restoreAllMocks(); Reflect.deleteProperty(navigator, "share"); Reflect.deleteProperty(navigator, "canShare"); });

const next = async (n: number) => { for (let i = 0; i < n; i++) await userEvent.click(screen.getByRole("button", { name: "Next" })); };
const cardText = () => decodeURIComponent((screen.getByTestId("save-card") as HTMLImageElement).src.split(",").slice(1).join(","));

describe("YearInReview", () => {
  it("steps through the cards to the one to share, and asks for the all-time numbers of the same person", async () => {
    render(YearInReview, { stats: stats(2026), person: 1, onclose: () => {} });
    expect(screen.getByText("32,311 mi")).toBeTruthy();
    await next(1); expect(screen.getByText("12 flights")).toBeTruthy();
    await next(1); expect(await screen.findByText("1 new this year: United Kingdom")).toBeTruthy();
    await next(1); expect(screen.getByText("JFK – LHR")).toBeTruthy();
    await next(1); expect(screen.getByText("9 nights")).toBeTruthy();
    await next(2);
    expect(await screen.findByTestId("save-card")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Next" }).hasAttribute("disabled")).toBe(true);
    expect(vi.mocked(api).mock.calls.map((c) => c[0])).toContain("/api/stats?person=1&year=all");
  });

  it("adds a card for cruises, with the nights aboard and the sea days, only when there were cruises", async () => {
    const withCruise = { ...stats(2026), cruises: { count: 2, nights: 10, sea_days: 1, ports: 3, lines: [] } };
    render(YearInReview, { stats: withCruise, person: 1, onclose: () => {} });
    await next(5);
    expect(screen.getByText("2 cruises")).toBeTruthy();
    expect(screen.getByText("10 nights aboard")).toBeTruthy();
    expect(screen.getByText("1 sea day")).toBeTruthy();
  });

  it("keeps names, numbers and hotels off the card and has no first-name option", async () => {
    render(YearInReview, { stats: stats(2026), person: 1, onclose: () => {} });
    await next(6);
    await screen.findByTestId("save-card");
    expect(cardText()).not.toContain("Hotel Canarios");
    expect(screen.queryByLabelText(/first name/i)).toBeNull();
  });

  it("saves the image to the downloads, and does not open a share sheet", async () => {
    const share = vi.fn();
    Object.assign(navigator, { share, canShare: () => true });
    URL.createObjectURL = vi.fn(() => "blob:x"); URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(YearInReview, { stats: stats(2026), person: 1, onclose: () => {} });
    await next(6);
    await waitFor(() => expect(screen.getByRole("button", { name: "Save as image" }).hasAttribute("disabled")).toBe(false));
    await userEvent.click(screen.getByRole("button", { name: "Save as image" }));
    expect(await screen.findByText("Saved the image to your downloads.")).toBeTruthy();
    expect(click).toHaveBeenCalled();
    expect(share).not.toHaveBeenCalled();
  });

  it("says so when the image can't be made", async () => {
    const { svgToPng } = await import("$lib/review");
    vi.mocked(svgToPng).mockRejectedValueOnce(new Error("no canvas"));
    render(YearInReview, { stats: stats(2026), person: 1, onclose: () => {} });
    await next(6);
    await waitFor(() => expect(screen.getByRole("button", { name: "Save as image" }).hasAttribute("disabled")).toBe(false));
    await userEvent.click(screen.getByRole("button", { name: "Save as image" }));
    expect((await screen.findByRole("alert")).textContent).toContain("no canvas");
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("says so on the map and share cards when the country outlines can't load", async () => {
    const map = await import("$lib/map");
    vi.spyOn(map, "loadCountries").mockRejectedValue(new Error("chunk failed"));
    render(YearInReview, { stats: stats(2026), person: 1, onclose: () => {} });
    await next(5);
    expect(await screen.findByText(/country outlines couldn’t load/)).toBeTruthy();
    await next(1);
    expect(screen.getByTestId("save-card")).toBeTruthy();
    expect(screen.getByText(/country outlines couldn’t load/)).toBeTruthy();
  });

  it("leaves out the new-countries line when the all-time numbers don't load, and closes on Escape", async () => {
    vi.mocked(api).mockRejectedValue(new Error("offline"));
    const onclose = vi.fn();
    render(YearInReview, { stats: stats(2026), person: 1, onclose });
    await next(2);
    expect(screen.queryByText(/new this year/)).toBeNull();
    await userEvent.keyboard("{Escape}");
    expect(onclose).toHaveBeenCalled();
  });
});
