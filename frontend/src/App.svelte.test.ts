// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ Toaster: vi.fn(), toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import { app, route } from "$lib/app.svelte";
import { state } from "./test/fixtures";
import App from "./App.svelte";

const go = async (hash: string) => {
  location.hash = hash;
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  await Promise.resolve();
};

beforeEach(async () => { vi.mocked(api).mockReset(); vi.mocked(api).mockResolvedValue({ trips: [], people: [], loyalty: [] }); app.state = state(); app.bootError = ""; await go("#upcoming"); });
afterEach(() => { app.state = null; });

describe("the shell", () => {
  it("opens Upcoming, with the brand on top and both pages in the tab bar and the sidebar", () => {
    render(App);
    expect(screen.getByRole("heading", { name: "Upcoming" })).toBeInTheDocument();
    expect(screen.getByRole("banner")).toHaveTextContent("Waypoint");
    const navs = screen.getAllByRole("navigation", { name: "Main" });
    expect(navs).toHaveLength(2);
    for (const nav of navs) {
      expect(within(nav).getByRole("link", { name: "Upcoming" })).toHaveAttribute("aria-current", "page");
      expect(within(nav).getByRole("link", { name: "Settings" })).toHaveAttribute("href", "#settings");
    }
  });

  it("switches page when the route changes, and marks the page you're on", async () => {
    render(App);
    await go("#settings");
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Upcoming" })).toBeNull();
    for (const nav of screen.getAllByRole("navigation", { name: "Main" })) {
      expect(within(nav).getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page");
      expect(within(nav).getByRole("link", { name: "Upcoming" })).not.toHaveAttribute("aria-current");
    }
    expect(route.page).toBe("settings");
  });

  it("opens a trip by its address, with Trips lit in both menus", async () => {
    vi.mocked(api).mockRejectedValue(new Error("No such trip"));
    await go("#trip/7");
    render(App);
    expect(await screen.findByText("No such trip")).toBeInTheDocument();
    for (const nav of screen.getAllByRole("navigation", { name: "Main" })) {
      expect(within(nav).getByRole("link", { name: "Trips" })).toHaveAttribute("aria-current", "page");
    }
  });

  it("opens Upcoming for a route it doesn't know (an old Runway bookmark, say)", async () => {
    await go("#budget");
    render(App);
    expect(screen.getByRole("heading", { name: "Upcoming" })).toBeInTheDocument();
  });

  it("says when Waypoint can't be reached, with a way to try again", () => {
    app.state = null; app.bootError = "Can’t reach Waypoint.";
    render(App);
    expect(screen.getByText("Can’t reach Waypoint")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
