// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));

import { api } from "$lib/api";
import { flightStatus, loadFlightStatus, refreshFlightStatus, statusFor } from "./flightstatus.svelte";

const reply = { enabled: true, month: "2026-11", used: 3, limit: 400, paused: null, statuses: [{ segment_id: 4, state: "landed" }] };

beforeEach(() => { vi.mocked(api).mockReset(); flightStatus.list = null; flightStatus.problem = ""; });

describe("the flight status the app holds", () => {
  it("loads the list, and finds a segment’s status in it", async () => {
    vi.mocked(api).mockResolvedValue(reply);
    await loadFlightStatus();
    expect(api).toHaveBeenCalledWith("/api/flight-status");
    expect(statusFor(4)?.state).toBe("landed");
    expect(statusFor(5)).toBeUndefined();
  });

  it("keeps what it had, and says why, when it can’t load", async () => {
    vi.mocked(api).mockResolvedValueOnce(reply);
    await loadFlightStatus();
    vi.mocked(api).mockRejectedValueOnce(new Error("offline"));
    await loadFlightStatus();
    expect(flightStatus.problem).toBe("offline");
    expect(flightStatus.list?.used).toBe(3);
  });

  it("refreshes from nothing held too", async () => {
    vi.mocked(api).mockResolvedValue(reply);
    await refreshFlightStatus(4);
    expect(flightStatus.list?.statuses).toHaveLength(1);
  });
});
