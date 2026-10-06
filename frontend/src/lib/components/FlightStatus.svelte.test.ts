// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { FlightStatus as Status, FlightStatusList } from "$lib/api-types";
import { flightStatus } from "$lib/flightstatus.svelte";
import { toast } from "svelte-sonner";
import { segment } from "../../test/fixtures";
import FlightStatus, { clock, dayShift } from "./FlightStatus.svelte";

const seg = segment({ id: 7 });
const status = (extra: Partial<Status> = {}): Status => ({
  segment_id: 7, state: "delayed", origin: "JFK", destination: "LHR",
  dep_scheduled: "2026-11-20T19:00", dep_estimated: "2026-11-20T19:50", dep_actual: null, dep_zone: "America/New_York",
  dep_terminal: "7", dep_gate: "B24",
  arr_scheduled: "2026-11-21T07:10", arr_estimated: "2026-11-21T08:05", arr_actual: null, arr_zone: "Europe/London",
  arr_terminal: "5", arr_gate: "A10", delay_minutes: 50, fetched_at: "2026-11-20T14:05:00+00:00", ...extra,
});
const list = (extra: Partial<FlightStatusList> = {}): FlightStatusList =>
  ({ enabled: true, month: "2026-11", used: 12, limit: 400, paused: null, statuses: [status()], ...extra });

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-20T09:00:00-05:00"));
  vi.mocked(api).mockReset(); vi.mocked(toast.error).mockReset(); vi.mocked(toast).mockReset(); flightStatus.list = list();
});
afterEach(() => { vi.useRealTimers(); flightStatus.list = null; });

describe("a flight’s live status", () => {
  it("shows a delay with the new time beside the booked one, the gate and terminal, and when it was fetched", () => {
    render(FlightStatus, { segment: seg });
    const card = screen.getByTestId("flight-status");
    expect(card).toHaveTextContent("Delayed 50 min");
    expect(card).toHaveTextContent("Now 19:50 (booked 19:00)");
    expect(card).toHaveTextContent("Terminal 7 · Gate B24");
    expect(card).toHaveTextContent("Arrives 08:05");
    expect(card).toHaveTextContent("Arrival terminal 5 · gate a10");
    expect(card).toHaveTextContent(/as of \d\d:\d\d/);
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
  });

  it("says on time, departed, landed, cancelled and diverted in words", () => {
    const cases: [Partial<Status>, string, string][] = [
      [{ state: "scheduled", dep_estimated: null, delay_minutes: null, arr_estimated: null }, "On time", "Booked 19:00"],
      [{ state: "departed", dep_actual: "2026-11-20T19:12", delay_minutes: 12 }, "Departed", "Left 19:12 (booked 19:00)"],
      [{ state: "landed", arr_actual: "2026-11-21T07:03" }, "Landed", "Landed 07:03"],
      [{ state: "cancelled", dep_estimated: null }, "Cancelled", "Booked 19:00"],
      [{ state: "diverted", dep_actual: "2026-11-20T19:06" }, "Diverted", "Left 19:06"],
    ];
    for (const [extra, word, line] of cases) {
      flightStatus.list = list({ statuses: [status(extra)] });
      const { unmount } = render(FlightStatus, { segment: seg });
      expect(screen.getByTestId("flight-status")).toHaveTextContent(word);
      expect(screen.getByTestId("flight-status")).toHaveTextContent(line);
      unmount();
    }
  });

  it("shows a time on another day with how many", () => {
    flightStatus.list = list({ statuses: [status({ dep_estimated: "2026-11-21T00:40" })] });
    render(FlightStatus, { segment: seg });
    expect(screen.getByTestId("flight-status")).toHaveTextContent("Now 00:40 (+1 day) (booked 19:00)");
    expect(dayShift("2026-11-22T01:00", "2026-11-20T19:00")).toBe(" (+2 days)");
    expect(dayShift("2026-11-19T23:00", "2026-11-20T19:00")).toBe(" (−1 day)");
    expect(dayShift("2026-11-20T19:50", "2026-11-20T19:00")).toBe("");
    expect(dayShift(null, "2026-11-20T19:00")).toBe("");
    expect(clock(null)).toBe("");
  });

  it("shows nothing without the key, and nothing for a flight with no status but a way to ask", async () => {
    flightStatus.list = list({ enabled: false });
    const { unmount } = render(FlightStatus, { segment: seg });
    expect(screen.queryByTestId("flight-status")).toBeNull();
    unmount();
    flightStatus.list = null;
    render(FlightStatus, { segment: seg });
    expect(screen.queryByTestId("flight-status")).toBeNull();
    flightStatus.list = list({ statuses: [] });
    expect(await screen.findByRole("button", { name: "Check live status" })).toBeInTheDocument();
  });

  it("asks for nothing, and shows only what it has, once the flight landed hours ago", () => {
    vi.setSystemTime(new Date("2026-11-21T14:00:00+00:00"));
    flightStatus.list = list({ statuses: [] });
    const { unmount } = render(FlightStatus, { segment: seg });
    expect(screen.queryByTestId("flight-status")).toBeNull();
    unmount();
    flightStatus.list = list({ statuses: [status({ state: "landed", arr_actual: "2026-11-21T07:03" })] });
    render(FlightStatus, { segment: seg });
    expect(screen.getByTestId("flight-status")).toHaveTextContent("Landed 07:03");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("says why nothing is fetched: the monthly limit, a rate limit, a refused key", () => {
    const until = "2026-12-01T00:00:00-05:00";
    for (const [reason, text] of [["limit", /Live status paused until Dec 1 \(monthly limit\)/], ["rate", /paused until \d\d:\d\d \(rate limit\)/],
      ["key", /paused until \d\d:\d\d \(RapidAPI didn’t accept the key\)/]] as const) {
      flightStatus.list = list({ paused: { until, reason } });
      const { unmount } = render(FlightStatus, { segment: seg });
      expect(screen.getByRole("status")).toHaveTextContent(text);
      expect(screen.queryByRole("button", { name: "Refresh" })).toBeNull();
      expect(screen.getByTestId("flight-status")).toHaveTextContent("Delayed 50 min");
      unmount();
    }
  });

  it("refreshes: asks for this segment, then shows the new answer and the month’s count", async () => {
    vi.mocked(api).mockResolvedValue(list({ used: 13, statuses: [status({ state: "departed", dep_actual: "2026-11-20T19:55", delay_minutes: 55 })] }));
    flightStatus.list = list({ statuses: [status(), status({ segment_id: 8, state: "landed" })] });
    render(FlightStatus, { segment: seg });
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(api).toHaveBeenCalledWith("/api/flight-status/7", { method: "POST", failed: "Couldn’t refresh the status" });
    await waitFor(() => expect(screen.getByTestId("flight-status")).toHaveTextContent("Departed"));
    expect(flightStatus.list?.used).toBe(13);
    expect(flightStatus.list?.statuses.map((x) => x.segment_id).sort()).toEqual([7, 8]);
  });

  it("says so when the service has no status for the flight", async () => {
    vi.mocked(api).mockResolvedValue(list({ statuses: [] }));
    flightStatus.list = list({ statuses: [] });
    render(FlightStatus, { segment: seg });
    await userEvent.click(screen.getByRole("button", { name: "Check live status" }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith("No live status found for this flight yet."));
  });

  it("reloads the list after a refused refresh, so a pause shows", async () => {
    const paused = list({ paused: { until: "2026-11-20T10:00:00-05:00", reason: "rate" } });
    vi.mocked(api).mockImplementation(async (path: string) => { if (path === "/api/flight-status") return paused; throw new Error("too many requests"); });
    render(FlightStatus, { segment: seg });
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("(rate limit)"));
  });

  it("says what went wrong when the refresh fails, and keeps what it had", async () => {
    vi.mocked(api).mockRejectedValue(new Error("Couldn’t reach the flight status service."));
    render(FlightStatus, { segment: seg });
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Couldn’t reach the flight status service."));
    expect(screen.getByTestId("flight-status")).toHaveTextContent("Delayed 50 min");
    expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled();
  });
});
