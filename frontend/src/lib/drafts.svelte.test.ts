// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({ api: vi.fn(), newPage: vi.fn() }));
vi.mock("./offline.svelte", () => ({ syncSavedTrip: vi.fn() }));
vi.mock("./early", () => ({ startEarly: vi.fn(), dropEarly: vi.fn() }));

import { route } from "./app.svelte";
import { anyDirty, leave } from "./drafts.svelte";
import Harness from "./components/ui/discard-dialog/DraftHarness.test.svelte";

const visit = (hash: string) => { location.hash = hash; };

beforeEach(async () => {
  visit("#trips");
  await waitFor(() => expect(route.page).toBe("trips"));
});
afterEach(() => { document.body.innerHTML = ""; });

describe("leaving a changed form", () => {
  it("lets a form nobody changed go without asking", async () => {
    render(Harness, { dirty: false });
    visit("#people");
    await waitFor(() => expect(route.page).toBe("people"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("asks before hash navigation, stays on the page and keeps the form on Keep editing", async () => {
    render(Harness, { dirty: true });
    visit("#people");
    const ask = await screen.findByRole("dialog", { name: "Discard changes?" });
    expect(ask).toHaveTextContent("What you typed here won’t be saved.");
    await waitFor(() => expect(location.hash).toBe("#trips"));
    await userEvent.click(screen.getByRole("button", { name: "Keep editing" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(route.page).toBe("trips");
    expect(screen.getByTestId("discarded")).toHaveTextContent("0");
    expect(anyDirty()).toBe(true);
  });

  it("goes where it was heading, and drops the form, on Discard changes", async () => {
    render(Harness, { dirty: true });
    visit("#people");
    const discard = await screen.findByRole("button", { name: "Discard changes" });
    await waitFor(() => expect(location.hash).toBe("#trips"));
    await userEvent.click(discard);
    await waitFor(() => expect(screen.getByTestId("discarded")).toHaveTextContent("1"));
    await waitFor(() => expect(route.page).toBe("people"));
  });

  it("does not leave while a save is running, and does not ask", async () => {
    render(Harness, { dirty: true, saving: true });
    visit("#people");
    await waitFor(() => expect(location.hash).toBe("#trips"));
    expect(route.page).toBe("trips");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(leave(() => { throw new Error("must not run"); })).toBe(false);
  });

  it("warns before the tab is closed or reloaded only while a form is changed", () => {
    const view = render(Harness, { dirty: false });
    const quiet = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(quiet);
    expect(quiet.defaultPrevented).toBe(false);
    view.unmount();
    render(Harness, { dirty: true });
    const loud = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(loud);
    expect(loud.defaultPrevented).toBe(true);
  });

  it("forgets a form once it is gone", () => {
    const view = render(Harness, { dirty: true });
    expect(anyDirty()).toBe(true);
    view.unmount();
    expect(anyDirty()).toBe(false);
  });
});
