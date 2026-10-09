// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
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

beforeEach(async () => { vi.mocked(api).mockReset(); vi.mocked(api).mockResolvedValue({ trips: [], people: [], loyalty: [], guests: [] }); app.state = state(); app.bootError = ""; await go("#upcoming"); });
afterEach(() => { app.state = null; });

describe("the shell", () => {
  it("opens Upcoming, with the brand on top and every page reachable from the tab bar and the sidebar", async () => {
    render(App);
    expect(screen.getByRole("heading", { name: "Upcoming" })).toBeInTheDocument();
    expect(screen.getByRole("banner")).toHaveTextContent("Waypoint");
    const navs = screen.getAllByRole("navigation", { name: "Main" });
    expect(navs).toHaveLength(2);
    const [side, tabs] = navs;
    for (const nav of navs) {
      expect(within(nav).getByRole("link", { name: "Upcoming" })).toHaveAttribute("aria-current", "page");
      for (const page of ["Trips", "Stats", "Review"]) expect(within(nav).getByRole("link", { name: new RegExp(page) })).toHaveAttribute("href", `#${page.toLowerCase()}`);
    }
    expect(within(tabs).queryByRole("link", { name: "People" })).toBeNull();
    expect(within(tabs).queryByRole("link", { name: "Settings" })).toBeNull();
    expect(within(side).getByRole("link", { name: "People" })).toHaveAttribute("href", "#people");
    expect(within(side).getByRole("link", { name: "Settings" })).toHaveAttribute("href", "#settings");
    await userEvent.click(within(tabs).getByRole("button", { name: "More" }));
    expect(within(tabs).getByRole("link", { name: "People" })).toHaveAttribute("href", "#people");
    expect(within(tabs).getByRole("link", { name: "Settings" })).toHaveAttribute("href", "#settings");
  });

  it("shows what's waiting on Review in both menus", () => {
    app.state = { ...state(), review_count: 4 };
    render(App);
    for (const nav of screen.getAllByRole("navigation", { name: "Main" })) {
      expect(within(nav).getByRole("link", { name: /Review/ })).toHaveTextContent("4");
    }
  });

  it("switches page when the route changes, and marks the page you're on", async () => {
    render(App);
    await go("#trips");
    expect(await screen.findByRole("heading", { name: "Trips" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Upcoming" })).toBeNull();
    for (const nav of screen.getAllByRole("navigation", { name: "Main" })) {
      expect(within(nav).getByRole("link", { name: "Trips" })).toHaveAttribute("aria-current", "page");
      expect(within(nav).getByRole("link", { name: "Upcoming" })).not.toHaveAttribute("aria-current");
    }
    expect(route.page).toBe("trips");
  });

  it.each([["people", "People"], ["settings", "Settings"]])("marks More, and %s inside it, while you're on that page", async (hash, name) => {
    await go(`#${hash}`);
    render(App);
    const [side, tabs] = screen.getAllByRole("navigation", { name: "Main" });
    expect(within(side).getByRole("link", { name })).toHaveAttribute("aria-current", "page");
    const more = within(tabs).getByRole("button", { name: `More (current page: ${name})` });
    expect(more).toHaveAttribute("aria-current", "true");
    expect(within(tabs).getByRole("link", { name: "Upcoming" })).not.toHaveAttribute("aria-current");
    await userEvent.click(more);
    expect(within(tabs).getByRole("link", { name })).toHaveAttribute("aria-current", "page");
  });

  it("opens More as a labelled disclosure that closes on Escape, on a tap elsewhere and on a page change", async () => {
    render(App);
    const [, tabs] = screen.getAllByRole("navigation", { name: "Main" });
    const more = within(tabs).getByRole("button", { name: "More" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    expect(more).toHaveAttribute("aria-controls", "more-menu");
    expect(more).not.toHaveAttribute("aria-current");
    await userEvent.click(more);
    expect(more).toHaveAttribute("aria-expanded", "true");
    expect(within(tabs).getByRole("group", { name: "More pages" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(more).toHaveAttribute("aria-expanded", "false");
    expect(more).toHaveFocus();
    expect(within(tabs).queryByRole("group", { name: "More pages" })).toBeNull();
    await userEvent.click(more);
    await userEvent.click(document.body);
    expect(more).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(more);
    await go("#people");
    expect(more).toHaveAttribute("aria-expanded", "false");
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
