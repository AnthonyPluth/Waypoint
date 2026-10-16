// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/svelte";
import { tick } from "svelte";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { app, route } from "$lib/app.svelte";
import type { AppState } from "$lib/types";
import SideNav from "./SideNav.svelte";
import TabBar from "./TabBar.svelte";
import TopBar from "./TopBar.svelte";

const demoUser = { name: "Demo Person", email: "demo@example.com", local: false } as unknown as AppState["user"];
const state = (extra: Partial<AppState> = {}): AppState =>
  ({ version: "1.0", database: "sqlite", user: null, last_backup: null, review_count: 0, person_id: null, ai: false, show_costs: false, ...extra });

beforeEach(() => {
  route.page = "upcoming";
  app.state = state({ review_count: 3, user: demoUser });
});
afterEach(() => {
  cleanup();
  app.state = null;
});

describe("SideNav", () => {
  it("marks only the current page with aria-current", () => {
    route.page = "trips";
    render(SideNav);
    const nav = screen.getByRole("navigation", { name: "Main" });
    const current = within(nav).getAllByRole("link").filter((a) => a.getAttribute("aria-current") === "page");
    expect(current.map((a) => a.textContent?.trim())).toEqual(["Trips"]);
  });

  it("keeps Trips current while on a trip", () => {
    route.page = "trip";
    render(SideNav);
    expect(screen.getByRole("link", { name: "Trips" }).getAttribute("aria-current")).toBe("page");
  });

  it("announces the Review count", () => {
    render(SideNav);
    expect(screen.getByRole("link", { name: /Review.*3\s*waiting/ })).toBeTruthy();
  });

  it("puts the mark first and the signed-in person last, linking to Settings", () => {
    render(SideNav);
    const links = screen.getAllByRole("link");
    expect(links[0].textContent).toContain("Waypoint");
    const chip = screen.getByTestId("side-user");
    expect(links[links.length - 1]).toBe(chip);
    expect(chip.getAttribute("href")).toBe("#settings");
    expect(chip.getAttribute("aria-label")).toBe("Signed in as Demo Person");
    expect(chip.textContent).toContain("Signed in");
    expect(chip.textContent).toContain("DP");
  });

  it("has no person chip when nobody is signed in", () => {
    app.state = state();
    render(SideNav);
    expect(screen.queryByTestId("side-user")).toBeNull();
  });
});

describe("TopBar", () => {
  it("is hidden from lg up, where the side nav carries the mark", () => {
    render(TopBar);
    expect(screen.getByRole("banner").className).toContain("lg:hidden");
  });
});

describe("TabBar", () => {
  it("marks only the current tab with aria-current", () => {
    route.page = "stats";
    render(TabBar);
    const current = screen.getAllByRole("link").filter((a) => a.getAttribute("aria-current") === "page");
    expect(current.map((a) => a.textContent?.trim())).toEqual(["Stats"]);
  });

  it("marks More current on a page inside it", () => {
    route.page = "people";
    render(TabBar);
    const more = screen.getByRole("button", { name: /More/ });
    expect(more.getAttribute("aria-current")).toBe("true");
    expect(more.textContent).toContain("current page: People");
  });

  it("announces the Review count", () => {
    render(TabBar);
    expect(screen.getByRole("link", { name: /Review.*3\s*waiting/ })).toBeTruthy();
  });

  it("floats inset from the sides", () => {
    render(TabBar);
    const cls = screen.getByRole("navigation", { name: "Main" }).className;
    expect(cls).toContain("inset-x-3");
    expect(cls).toContain("bottom-[calc(env(safe-area-inset-bottom)+0.75rem)]");
  });

  it("opens More, closes it on Escape and returns focus to the button", async () => {
    render(TabBar);
    const more = screen.getByRole("button", { name: /More/ });
    await fireEvent.click(more);
    expect(more.getAttribute("aria-expanded")).toBe("true");
    const menu = screen.getByRole("group", { name: "More pages" });
    expect(within(menu).getAllByRole("link").map((a) => a.textContent?.trim())).toEqual(["People", "Settings"]);
    within(menu).getByRole("link", { name: "People" }).focus();
    await fireEvent.keyDown(window, { key: "Escape" });
    await tick();
    expect(screen.queryByRole("group", { name: "More pages" })).toBeNull();
    expect(more.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(more);
  });

  it("closes More on an outside click", async () => {
    render(TabBar);
    await fireEvent.click(screen.getByRole("button", { name: /More/ }));
    await fireEvent.pointerDown(document.body);
    await tick();
    expect(screen.queryByRole("group", { name: "More pages" })).toBeNull();
  });
});
