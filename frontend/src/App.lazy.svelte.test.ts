// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ Toaster: vi.fn(), toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));
vi.mock("./pages/Stats.svelte", () => { throw new Error("Failed to fetch dynamically imported module"); });

import { api } from "$lib/api";
import { app } from "$lib/app.svelte";
import { segment, state, trip } from "./test/fixtures";
import App from "./App.svelte";

const go = async (hash: string) => {
  location.hash = hash;
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  await Promise.resolve();
};

beforeEach(async () => {
  vi.mocked(api).mockReset().mockResolvedValue({ trips: [], people: [], loyalty: [], guests: [] });
  app.state = state(); app.bootError = "";
  await go("#upcoming");
});
afterEach(() => { app.state = null; });

describe("pages that load on demand", () => {
  it("opens Upcoming without waiting for a second file", () => {
    render(App);
    expect(screen.getByRole("heading", { name: "Upcoming" })).toBeInTheDocument();
  });

  it("shows another page once its file has arrived", async () => {
    render(App);
    await go("#people");
    expect(await screen.findByRole("heading", { name: "People" })).toBeInTheDocument();
  });

  it("opens a flight's live status view from the address of a trip's flight", async () => {
    const loop = trip([segment({ id: 3, trip_id: 7 })], { id: 7, name: "Four Corners loop" });
    vi.mocked(api).mockImplementation(async (path) => (path === "/api/trips/7" ? loop : path === "/api/flight-status" ? { enabled: false, month: "", used: 0, limit: 0, paused: null, statuses: [] } : {}) as never);
    render(App);
    await go("#trip/7/flight/3");
    expect(await screen.findByRole("link", { name: "Back to Four Corners loop" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
  });

  it("says so, with a way to reload, when a page's file can't be fetched", async () => {
    render(App);
    await go("#stats");
    expect(await screen.findByText("Couldn’t load this page")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Stats" })).toBeNull();
    await go("#upcoming");
    expect(await screen.findByRole("heading", { name: "Upcoming" })).toBeInTheDocument();
    expect(screen.queryByText("Couldn’t load this page")).toBeNull();
  });
});
