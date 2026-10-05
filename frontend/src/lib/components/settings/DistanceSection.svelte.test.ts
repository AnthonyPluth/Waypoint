// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import DistanceSection from "./DistanceSection.svelte";

beforeEach(() => vi.mocked(api).mockReset());

describe("Settings → Distances", () => {
  it("shows the household's unit and saves the other one", async () => {
    vi.mocked(api).mockImplementation(async (_p: string, opts?: { method?: string; body?: unknown }) =>
      (opts?.method === "POST" ? opts.body : { distance_unit: "mi" }) as never);
    render(DistanceSection);
    expect(await screen.findByRole("button", { name: "Miles" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Kilometres" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Kilometres" })).toHaveAttribute("aria-pressed", "true"));
    expect(api).toHaveBeenCalledWith("/api/distance-unit", { method: "POST", body: { distance_unit: "km" } });
  });

  it("says when it can't load and tries again; a refused save keeps the unit that was saved", async () => {
    vi.mocked(api).mockRejectedValueOnce(new Error("Offline"));
    render(DistanceSection);
    expect(await screen.findByRole("status")).toHaveTextContent("Offline");
    vi.mocked(api).mockImplementation(async (_p: string, opts?: { method?: string }) => {
      if (opts?.method === "POST") throw new Error("Choose miles or kilometres");
      return { distance_unit: "km" } as never;
    });
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("button", { name: "Kilometres" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Miles" }));
    await waitFor(() => expect(api).toHaveBeenCalledTimes(3));
    expect(screen.getByRole("button", { name: "Kilometres" })).toHaveAttribute("aria-pressed", "true");
  });
});
