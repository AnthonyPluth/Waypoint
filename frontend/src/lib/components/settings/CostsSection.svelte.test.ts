// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import { app } from "$lib/app.svelte";
import CostsSection from "./CostsSection.svelte";

const state = (show_costs: boolean) => ({ version: "dev", database: "sqlite", user: null, last_backup: null, review_count: 0, person_id: null, ai: false, show_costs }) as const;

beforeEach(() => {
  vi.mocked(api).mockReset();
  app.state = state(true);
});

describe("Settings → Trip costs", () => {
  it("shows costs by default and saves hiding them", async () => {
    vi.mocked(api).mockImplementation(async (_p: string, opts?: { body?: unknown }) => opts?.body as never);
    render(CostsSection);
    expect(screen.getByRole("button", { name: "Show" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Hide" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Hide" })).toHaveAttribute("aria-pressed", "true"));
    expect(api).toHaveBeenCalledWith("/api/show-costs", { method: "POST", body: { show_costs: false } });
    expect(app.state?.show_costs).toBe(false);
  });

  it("keeps the saved choice when the save is refused", async () => {
    app.state = state(false);
    vi.mocked(api).mockRejectedValue(new Error("Send show_costs as true or false"));
    render(CostsSection);
    expect(screen.getByRole("button", { name: "Hide" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Show" }));
    await waitFor(() => expect(api).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Hide" })).toHaveAttribute("aria-pressed", "true");
    expect(app.state?.show_costs).toBe(false);
  });
});
