// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login", onDenied: vi.fn() }));
vi.mock("svelte-sonner", () => ({ Toaster: vi.fn(), toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import { app } from "$lib/app.svelte";
import { offline } from "$lib/offline.svelte";
import { installShell, type FakeShell } from "./test/fake-shell";
import { segment, trip } from "./test/fixtures";
import App from "./App.svelte";

const flight = segment({ id: 1, confirmation: "QX7R2M", start_local: "2026-11-20T19:00", end_local: "2026-11-21T07:10", details: { flight_number: "AA 101" } });
const copy = (id: number, name: string, savedAt: number) => ({ savedAt, messages: [], trip: { ...trip([flight]), id, name, end_date: "2026-11-24" } });
const go = async (hash: string) => { location.hash = hash; window.dispatchEvent(new HashChangeEvent("hashchange")); await Promise.resolve(); };
let shell: FakeShell;

beforeEach(async () => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockRejectedValue(new Error("Can’t reach Waypoint."));
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
  vi.setSystemTime(new Date(2026, 10, 20, 12, 0));
  Object.assign(offline, { checked: false, setUp: false, hasCopy: false, savedAt: null, off: false, damaged: false, supported: true, reason: "", declined: false, failed: false, trips: [] });
  app.state = null; app.bootError = "Can’t reach Waypoint. Check your connection and try again."; app.offline = true;
  await go("#upcoming");
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); app.bootError = ""; app.offline = false; });

describe("opening the iPhone app with no connection", () => {
  it("shows the saved trip read over the bridge, with no unlock screen", async () => {
    shell = installShell({ trips: [copy(1, "Trip to London", Date.now() - 2 * 3_600_000)], savedAt: Date.now() - 2 * 3_600_000 });
    render(App);
    expect(await screen.findByText("QX7R2M")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Saved trip is locked" })).not.toBeInTheDocument();
    expect(shell.posts.map((p) => p.type)).toEqual(["status", "load"]);
  });

  it("offers the choice when several trips are saved", async () => {
    shell = installShell({ trips: [copy(1, "Trip to London", Date.now()), copy(2, "Trip to Paris", Date.now())], savedAt: Date.now() });
    render(App);
    expect(await screen.findByTestId("saved-trips")).toBeInTheDocument();
    expect(screen.getByText("Trip to Paris")).toBeInTheDocument();
  });

  it("says nothing is saved when saving is off, and asks for no trips", async () => {
    shell = installShell({ saving: false });
    render(App);
    expect(await screen.findByText("Saving trips for offline use is switched off on this device.")).toBeInTheDocument();
    expect(shell.posts.map((p) => p.type)).toEqual(["status"]);
  });

  it("drops a trip that ended more than 3 days ago and asks the app to remove the copy", async () => {
    shell = installShell({ trips: [{ ...copy(1, "Trip to London", Date.now()), trip: { ...copy(1, "x", 0).trip, name: "Trip to London", end_date: "2026-11-10" } }], savedAt: Date.now() });
    render(App);
    expect(await screen.findByText("You’re offline, and no trip is saved on this device")).toBeInTheDocument();
    expect(shell.posts.map((p) => p.type)).toEqual(["status", "load", "remove", "status"]);
  });

  it("says the trips can't be opened when the app's reply is unreadable, and tries again", async () => {
    shell = installShell({ trips: [copy(1, "Trip to London", Date.now())], savedAt: Date.now() });
    shell.replies.set("load", { version: 9, trips: [] });
    render(App);
    expect(await screen.findByTestId("shell-unreadable")).toBeInTheDocument();
    shell.replies.delete("load");
    await userEvent.setup().click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByText("QX7R2M")).toBeInTheDocument());
  });
});
