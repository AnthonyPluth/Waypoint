// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));

import { api } from "$lib/api";
import { forgetAirportZones } from "$lib/airport-zones";
import type { FlightStatus } from "$lib/api-types";
import { instant } from "$lib/trips";
import { segment } from "../../test/fixtures";
import FlightBooking from "./FlightBooking.svelte";
import FlightHome from "./FlightHome.svelte";
import FlightRow from "./FlightRow.svelte";

const DEN = "America/Denver";
const AIRPORTS: Record<string, object> = {
  DEN: { code: "DEN", name: "Denver International Airport", city: "Denver", country: "US", zone: DEN },
  GJT: { code: "GJT", name: "Grand Junction Regional Airport", city: "Grand Junction", country: "US", zone: DEN },
};
const booked = segment({
  id: 3, trip_id: 7, provider: "Example Air", origin: "DEN", destination: "GJT", start_local: "2025-06-12T09:40", start_zone: DEN, end_local: "2025-06-12T10:52", end_zone: DEN,
  details: { flight_number: "EA 214" },
});
const at = (local: string) => instant(local, DEN);
const status = (now: number, minutesAgo: number, extra: Partial<FlightStatus>): FlightStatus => ({
  segment_id: 3, state: "scheduled", origin: "DEN", destination: "GJT", dep_scheduled: "2025-06-12T09:40", dep_estimated: null, dep_actual: null, dep_zone: DEN,
  dep_terminal: null, dep_gate: null, arr_scheduled: "2025-06-12T10:52", arr_estimated: null, arr_actual: null, arr_zone: DEN, arr_terminal: null, arr_gate: null,
  delay_minutes: null, fetched_at: new Date(now - minutesAgo * 60_000).toISOString(), ...extra,
});

const EARLY = at("2025-06-12T08:50");
const AIR = at("2025-06-12T10:14");
const delayed = status(EARLY, 4, { state: "delayed", dep_estimated: "2025-06-12T10:15", arr_estimated: "2025-06-12T11:27", dep_terminal: "B", dep_gate: "B14", delay_minutes: 35 });
const flying = status(AIR, 1, { state: "departed", dep_actual: "2025-06-12T09:46", arr_estimated: "2025-06-12T10:52" });

beforeEach(() => {
  forgetAirportZones();
  vi.mocked(api).mockReset().mockImplementation(async (path: string) => {
    const found = AIRPORTS[path.split("/").pop() ?? ""];
    if (!found) throw new Error("No such airport");
    return found;
  });
});

describe("the Home next-flight card", () => {
  const draw = (now: number, live?: FlightStatus) => render(FlightHome, { segment: booked, status: live, liveOn: true, now, eyebrow: "Next up", tripName: "Four Corners loop" });

  it("is one link named with the flight, route, state and next time, with the mini route decorative", async () => {
    draw(EARLY, delayed);
    const link = await screen.findByRole("link", { name: "EA 214, Denver to Grand Junction, delayed 35 minutes, now departs 10:15 am" });
    expect(link).toHaveAttribute("href", "#trip/7/flight/3");
    expect(screen.getAllByRole("link")).toHaveLength(1);
    const route = document.querySelector("[data-flight-home] [aria-hidden='true'] [data-plane]")?.closest("[aria-hidden='true']");
    expect(route).not.toBeNull();
    expect(within(route as HTMLElement).getByText("DEN")).toBeInTheDocument();
  });

  it("shows the pill, amber times, the gate and when it was updated when delayed", async () => {
    draw(EARLY, delayed);
    await screen.findByRole("link");
    expect(screen.getByText("Delayed 35 min")).toBeInTheDocument();
    expect(screen.getByText("10:15 am").parentElement).toHaveClass("text-signal-ink");
    expect(screen.getByText("11:27 am").parentElement).toHaveClass("text-signal-ink");
    expect(screen.getByText("Terminal B · Gate B14")).toBeInTheDocument();
    expect(screen.getByText("Updated 4 min ago")).toBeInTheDocument();
    expect(screen.getByText("EA 214")).toBeInTheDocument();
    expect(screen.getByText("Thu Jun 12 · Four Corners loop")).toBeInTheDocument();
    expect(screen.getAllByText("MDT")).toHaveLength(2);
  });

  it("puts the plane at the flight’s progress while it is in the air", async () => {
    draw(AIR, flying);
    await screen.findByRole("link", { name: "EA 214, Denver to Grand Junction, in the air, lands 10:52 am in 38 minutes" });
    expect(screen.getByText("In the air")).toBeInTheDocument();
    const left = Number.parseFloat(document.querySelector<HTMLElement>("[data-plane]")!.style.left);
    expect(left).toBeCloseTo(((AIR - at("2025-06-12T09:46")) / (at("2025-06-12T10:52") - at("2025-06-12T09:46"))) * 100, -1);
  });

  it("shows the booked times, dashes and no Updated line with no live data", async () => {
    draw(at("2025-06-12T08:00"));
    await screen.findByRole("link", { name: "EA 214, Denver to Grand Junction, scheduled, departs Thu Jun 12 at 9:40 am" });
    expect(screen.getByText("9:40 am")).toBeInTheDocument();
    expect(screen.getByText("10:52 am")).toBeInTheDocument();
    expect(screen.getByText("Terminal — · Gate —")).toBeInTheDocument();
    expect(document.querySelector("[data-updated]")).toBeNull();
  });
});

describe("a flight row", () => {
  it("is one link named like the card, with the kind tile decorative, the route and number, a meta line and a chip", async () => {
    render(FlightRow, { segment: booked, status: delayed, liveOn: true, now: EARLY });
    const link = await screen.findByRole("link", { name: "EA 214, Denver to Grand Junction, delayed 35 minutes, now departs 10:15 am" });
    expect(link).toHaveAttribute("href", "#trip/7/flight/3");
    const row = link.closest("li")!;
    expect(row.querySelector("[data-tile='flight']")).toHaveAttribute("aria-hidden", "true");
    expect(within(row).getByText("DEN to GJT · EA 214")).toBeInTheDocument();
    expect(within(row).getByText("Departs 10:15 am MDT")).toBeInTheDocument();
    expect(within(row).getByText("Delayed 35 min")).toBeInTheDocument();
  });

  it("gives the date and time of a flight that is not today, and no chip when live status has not started", async () => {
    render(FlightRow, { segment: booked, liveOn: true, now: at("2025-06-02T08:00") });
    const link = await screen.findByRole("link", { name: "EA 214, Denver to Grand Junction, scheduled, no live status yet" });
    expect(within(link.closest("li")!).getByText("Thu Jun 12 · 9:40 am MDT")).toBeInTheDocument();
    expect(link.closest("li")!.querySelector("[data-tone]")).toBeNull();
  });

  it("says when a flight in the air lands", async () => {
    render(FlightRow, { segment: booked, status: flying, liveOn: true, now: AIR });
    expect(await screen.findByText("Lands 10:52 am MDT")).toBeInTheDocument();
    expect(screen.getByText("In the air")).toBeInTheDocument();
  });
});

describe("the compact booking", () => {
  it("shows a one-line progress bar named Flight progress, when it left and when it lands", async () => {
    render(FlightBooking, { segment: booked, status: flying, liveOn: true, now: AIR });
    const link = await screen.findByRole("link", { name: "EA 214, Denver to Grand Junction, in the air, lands 10:52 am in 38 minutes" });
    expect(link).toHaveAttribute("href", "#trip/7/flight/3");
    const booking = link.closest("[data-flight-booking]") as HTMLElement;
    const bar = within(booking).getByRole("progressbar", { name: "Flight progress" });
    expect(bar).toHaveAttribute("aria-valuemin", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
    expect(Number(bar.getAttribute("aria-valuenow"))).toBe(Math.round(((AIR - at("2025-06-12T09:46")) / (at("2025-06-12T10:52") - at("2025-06-12T09:46"))) * 100));
    expect(within(booking).getByText("Departed 9:46 am MDT")).toBeInTheDocument();
    expect(within(booking).getByText("Lands 10:52 am MDT")).toBeInTheDocument();
    expect(within(booking).getByText("In the air")).toBeInTheDocument();
  });

  it("says Departs before takeoff and Landed after landing, with the bar empty or full", async () => {
    const first = render(FlightBooking, { segment: booked, status: delayed, liveOn: true, now: EARLY });
    await waitFor(() => expect(screen.getByText("Departs 10:15 am MDT")).toBeInTheDocument());
    expect(screen.getByRole("progressbar", { name: "Flight progress" })).toHaveAttribute("aria-valuenow", "0");
    first.unmount();
    const landed = status(at("2025-06-12T10:55"), 1, { state: "landed", dep_actual: "2025-06-12T09:46", arr_actual: "2025-06-12T10:49" });
    render(FlightBooking, { segment: booked, status: landed, liveOn: true, now: at("2025-06-12T10:55") });
    await waitFor(() => expect(screen.getByText("Landed 10:49 am MDT")).toBeInTheDocument());
    expect(screen.getByRole("progressbar", { name: "Flight progress" })).toHaveAttribute("aria-valuenow", "100");
  });
});
