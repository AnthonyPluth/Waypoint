// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { Home } from "$lib/api-types";
import HomeSection from "./HomeSection.svelte";

const empty: Home = { city: "", state: "", zip: "", country: "US", saved: false, placed: false };
const saved: Home = { city: "Springfield", state: "IL", zip: "62701", country: "US", saved: true, placed: true };

beforeEach(() => vi.mocked(api).mockReset());

describe("Settings → Home", () => {
  it("starts empty with the household's country filled in, and saves what is typed", async () => {
    vi.mocked(api).mockImplementation(async (_p: string, opts?: { method?: string; body?: Record<string, string> }) =>
      (opts?.method === "POST" ? { ...opts.body, saved: true, placed: true } : empty) as never);
    render(HomeSection);
    expect(await screen.findByLabelText("City")).toHaveValue("");
    expect(screen.getByLabelText("Country code")).toHaveValue("US");
    expect(screen.queryByLabelText(/street|address/i)).toBeNull();
    expect(screen.getByRole("button", { name: "Clear" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("City"), "Springfield");
    await userEvent.type(screen.getByLabelText("State or region"), "IL");
    await userEvent.type(screen.getByLabelText("ZIP or postal code (optional)"), "62701");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/home", { method: "POST", body: { city: "Springfield", state: "IL", zip: "62701", country: "US" } }));
    expect(screen.queryByText("Waypoint can’t place this on the map.")).toBeNull();
    expect(await screen.findByRole("button", { name: "Clear" })).toBeEnabled();
  });

  it("shows what the server refused under the fields and keeps what was typed", async () => {
    vi.mocked(api).mockImplementation(async (_p: string, opts?: { method?: string }) => {
      if (opts?.method === "POST") throw new Error("The city doesn’t look right");
      return empty as never;
    });
    render(HomeSection);
    await userEvent.type(await screen.findByLabelText("City"), "12 Main");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The city doesn’t look right");
    expect(screen.getByLabelText("City")).toHaveValue("12 Main");
    expect(screen.getByLabelText("City")).toHaveAttribute("aria-invalid", "true");
  });

  it("says when Waypoint can't place the city", async () => {
    vi.mocked(api).mockResolvedValue({ ...saved, city: "Nowhereville", zip: "", placed: false } as never);
    render(HomeSection);
    expect(await screen.findByRole("status")).toHaveTextContent("Waypoint can’t place this on the map.");
  });

  it("clears Home", async () => {
    vi.mocked(api).mockImplementation(async (_p: string, opts?: { method?: string }) => (opts?.method === "DELETE" ? empty : saved) as never);
    render(HomeSection);
    expect(await screen.findByLabelText("City")).toHaveValue("Springfield");
    await userEvent.click(screen.getByRole("button", { name: "Clear" }));
    await waitFor(() => expect(screen.getByLabelText("City")).toHaveValue(""));
    expect(api).toHaveBeenCalledWith("/api/home", { method: "DELETE" });
  });

  it("shows nothing of Home to someone who isn't signed in, and offers to try again", async () => {
    vi.mocked(api).mockRejectedValueOnce(new Error("Sign in first"));
    render(HomeSection);
    expect(await screen.findByRole("status")).toHaveTextContent("Sign in first");
    expect(screen.queryByLabelText("City")).toBeNull();
    vi.mocked(api).mockResolvedValue(saved as never);
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByLabelText("City")).toHaveValue("Springfield");
  });
});
