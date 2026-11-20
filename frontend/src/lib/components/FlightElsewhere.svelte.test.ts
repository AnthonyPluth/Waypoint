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

  it("is one link named with the flight, route, state and next time, with the arc decorative", async () => {
    draw(EARLY, delayed);
    const link = await screen.findByRole("link", { name: "EA 214, Denver to Grand Junction, delayed 35 minutes, now departs 10:15 am" });
    expect(link).toHaveAttribute("href", "#trip/7/flight/3");
    expect(screen.getAllByRole("link")).toHaveLength(1);
    const line = document.querySelector("[data-flight-home] [data-plane]")?.closest("[aria-hidden='true']");
    expect(line).not.toBeNull();
    expect(screen.getByText("DEN").closest("[aria-hidden='true']")).toBeNull();
    expect(document.querySelector("[data-when='origin'] time")?.closest("[aria-hidden='true']")).toBeNull();
  });

  it("shows the amber Delayed pill, amber times, the late line with the old time struck and the three facts when delayed", async () => {
    draw(EARLY, delayed);
    await screen.findByRole("link");
    expect(screen.getByText("Delayed")).toHaveClass("bg-signal", "text-signal-foreground");
    expect(document.querySelector("[data-when='origin']")).toHaveClass("text-signal-ink");
    expect(document.querySelector("[data-when='destination']")).toHaveClass("text-signal-ink");
    expect(document.querySelector("[data-quiet]")).toHaveTextContent("35 min late · was Originally 9:40 AM");
    expect(document.querySelector("[data-quiet] s")).toHaveTextContent("9:40 AM");
    expect(screen.getByText("B14")).toBeInTheDocument();
    expect(screen.getByText("Example Air EA 214")).toBeInTheDocument();
    expect(screen.getByText("Next up").closest("p")).toHaveTextContent("Next up · Four Corners loop");
    expect(screen.getByText("Your flight to Grand Junction")).toBeInTheDocument();
  });

  it("puts the plane at the flight’s progress while it is in the air, with the time left in blue", async () => {
    draw(AIR, flying);
    await screen.findByRole("link", { name: "EA 214, Denver to Grand Junction, in the air, lands 10:52 am in 38 minutes" });
    expect(screen.getByText("38 min left")).toHaveClass("text-primary");
    expect(screen.getByText("In the air to Grand Junction")).toBeInTheDocument();
    const left = Number.parseFloat(document.querySelector<HTMLElement>("[data-plane]")!.style.left);
    expect(left).toBeCloseTo(((AIR - at("2025-06-12T09:46")) / (at("2025-06-12T10:52") - at("2025-06-12T09:46"))) * 100, -1);
  });

  it("shows the booked times, dashes and no Updated line with no live data", async () => {
    draw(at("2025-06-12T08:00"));
    await screen.findByRole("link", { name: "EA 214, Denver to Grand Junction, scheduled, departs Thu Jun 12 at 9:40 am" });
    expect(document.querySelector("[data-when='origin'] time")).toHaveTextContent("9:40 AM");
    expect(document.querySelector("[data-when='destination'] time")).toHaveTextContent("10:52 AM");
    expect([...document.querySelectorAll("[data-facts] dd")].slice(0, 2).map((dd) => dd.textContent)).toEqual(["—Not known yet", "—Not known yet"]);
    expect(document.querySelector("[data-updated]")).toBeNull();
  });
});

describe("what the cards keep from the ones they replace", () => {
  const paused = { reason: "limit" as const, until: "2025-07-01T00:00:00Z" };
  const overnight = segment({
    id: 3, trip_id: 7, provider: "Example Air", origin: "DEN", destination: "GJT", start_local: "2025-06-12T23:30", start_zone: DEN, end_local: "2025-06-13T00:40", end_zone: DEN,
    details: { flight_number: "EA 214" },
  });

  it("says live updates are paused on the Home card and the booking, whether or not a status is stored, and says nothing otherwise", async () => {
    const home = render(FlightHome, { segment: booked, status: delayed, liveOn: true, now: EARLY, eyebrow: "Next up", tripName: "Loop", paused });
    expect(await screen.findByRole("status")).toHaveTextContent(/^Live updates paused until .* \(monthly limit\)$/);
    home.unmount();
    const bare = render(FlightHome, { segment: booked, liveOn: true, now: EARLY, eyebrow: "Next up", tripName: "Loop", paused });
    expect(await screen.findByRole("status")).toHaveTextContent("Live updates paused until");
    bare.unmount();
    const none = render(FlightHome, { segment: booked, status: delayed, liveOn: true, now: EARLY, eyebrow: "Next up", tripName: "Loop" });
    await screen.findByRole("link");
    expect(none.container.querySelector("[data-paused]")).toBeNull();
    none.unmount();
    render(FlightBooking, { segment: booked, status: flying, liveOn: true, now: AIR, paused });
    expect(await screen.findByRole("status")).toHaveTextContent("Live updates paused until");
  });

  it("shows the arrival day beside the arrival time of an overnight flight, on the card and in the booking", async () => {
    const home = render(FlightHome, { segment: overnight, liveOn: true, now: at("2025-06-12T20:00"), eyebrow: "Next up", tripName: "Loop" });
    const later = await waitFor(() => { const el = home.container.querySelector("[data-later]"); expect(el).not.toBeNull(); return el!; });
    expect(later).toHaveTextContent("+1 day");
    expect(later.querySelector(".sr-only")).toHaveTextContent(", 1 day later on the calendar than departure");
    home.unmount();
    render(FlightBooking, { segment: overnight, liveOn: true, now: at("2025-06-12T20:00") });
    expect(await screen.findByText("Lands 12:40 am MDT +1 day")).toBeInTheDocument();
  });

  it("keeps both times of the compact booking, with their zones, in the accessibility tree", async () => {
    render(FlightBooking, { segment: booked, status: flying, liveOn: true, now: AIR });
    await screen.findByRole("link");
    for (const text of ["Departed 9:46 am MDT", "Lands 10:52 am MDT"]) expect(screen.getByText(text).closest("[aria-hidden='true']")).toBeNull();
  });

  it("leaves the times out when told to, for bookings that disagree", async () => {
    render(FlightBooking, { segment: booked, status: flying, liveOn: true, now: AIR, showTimes: false });
    await screen.findByRole("link");
    expect(screen.queryByText(/^Lands /)).toBeNull();
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
