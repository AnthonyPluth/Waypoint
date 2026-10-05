// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));

import { api } from "$lib/api";
import type { Stats as StatsReply } from "$lib/api-types";
import Stats from "./Stats.svelte";

const stats = {
  person: null, year: null, distance_unit: "mi",
  flights: {
    airports: [{ code: "ORD", name: "O’Hare International Airport", city: "Chicago", country: "US", visits: 3, latitude: 41.9742, longitude: -87.9073 }],
    routes: [],
  },
} as unknown as StatsReply;

beforeEach(() => vi.mocked(api).mockReset());

describe("Stats page", () => {
  it("asks the server for the household's stats and draws the map", async () => {
    vi.mocked(api).mockResolvedValue(stats);
    const { container } = render(Stats);
    expect(await screen.findByRole("heading", { name: "Where you’ve been" })).toBeTruthy();
    expect(api).toHaveBeenCalledWith("/api/stats");
    await waitFor(() => expect(container.querySelectorAll("[data-dot]")).toHaveLength(1));
  });

  it("shows a failed load with Try again, and draws nothing that could pass for current", async () => {
    vi.mocked(api).mockRejectedValueOnce(new Error("The server is down")).mockResolvedValue(stats);
    render(Stats);
    expect(await screen.findByText("The server is down")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Where you’ve been" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Where you’ve been" })).toBeTruthy();
  });
});
