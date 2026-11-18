// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), apiImage: vi.fn(async () => { throw new TypeError("Failed to fetch"); }), newPage: vi.fn(), signInUrl: () => "/auth/login", onDenied: vi.fn() }));
vi.mock("svelte-sonner", () => ({ Toaster: vi.fn(), toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import { app } from "$lib/app.svelte";
import { resetArrival } from "$lib/arrival.svelte";
import { offline } from "$lib/offline.svelte";
import { installShell, type FakeShell } from "./test/fake-shell";
import { segment, trip } from "./test/fixtures";
import App from "./App.svelte";

const flight = segment({ id: 1, confirmation: "QX7R2M", start_local: "2026-11-20T19:00", end_local: "2026-11-21T07:10", details: { flight_number: "AA 101" } });
const copy = (id: number, name: string, savedAt: number) => ({ savedAt, messages: [], trip: { ...trip([flight]), id, name, end_date: "2026-11-24" } });
const go = async (hash: string) => { location.hash = hash; window.dispatchEvent(new HashChangeEvent("hashchange")); await Promise.resolve(); };
let shell: FakeShell;
const asked = () => shell.posts.map((p) => p.type).filter((type) => type !== "pendingArrival" && type !== "arrivalHere");

beforeEach(async () => {
  resetArrival();
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
    expect(asked()).toEqual(["status", "load"]);
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
    expect(asked()).toEqual(["status"]);
  });

  it("drops a trip that ended more than 3 days ago and asks the app to remove the copy", async () => {
    shell = installShell({ trips: [{ ...copy(1, "Trip to London", Date.now()), trip: { ...copy(1, "x", 0).trip, name: "Trip to London", end_date: "2026-11-10" } }], savedAt: Date.now() });
    render(App);
    expect(await screen.findByText("You’re offline, and no trip is saved on this device")).toBeInTheDocument();
    expect(asked()).toEqual(["status", "load", "remove", "status"]);
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

describe("when the app's status or a trip's end date changes under the open screen", () => {
  it("shows the can't-be-opened state, not 'nothing saved', when status fails, and Try again retries status and load over the bridge", async () => {
    shell = installShell({ trips: [copy(1, "Trip to London", Date.now())], savedAt: Date.now() });
    shell.replies.set("status", Promise.reject(new Error("gone")));
    render(App);
    expect(await screen.findByTestId("shell-unreadable")).toBeInTheDocument();
    expect(screen.queryByText("You’re offline, and no trip is saved on this device")).not.toBeInTheDocument();
    shell.replies.delete("status");
    shell.posts.length = 0;
    await userEvent.setup().click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByText("QX7R2M")).toBeInTheDocument());
    expect(asked()).toEqual(["status", "load"]);
  });

  it("drops a trip that expires while the app is suspended when it comes back to the foreground, and asks the app to remove the copy", async () => {
    shell = installShell({ trips: [copy(1, "Trip to London", Date.now())], savedAt: Date.now() });
    render(App);
    expect(await screen.findByText("QX7R2M")).toBeInTheDocument();
    shell.posts.length = 0;
    vi.setSystemTime(new Date(2026, 10, 29, 12, 0));
    document.dispatchEvent(new Event("visibilitychange"));
    expect(await screen.findByText("You’re offline, and no trip is saved on this device")).toBeInTheDocument();
    expect(screen.queryByText("QX7R2M")).not.toBeInTheDocument();
    expect(shell.posts.map((p) => p.type)).toContain("remove");
    expect(shell.trips).toEqual([]);
  });

  it("drops it at the nearest expiry time while the app stays open", async () => {
    vi.useRealTimers();
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(new Date(2026, 10, 27, 12, 0));
    shell = installShell({ trips: [copy(1, "Trip to London", Date.now())], savedAt: Date.now() });
    render(App);
    await vi.advanceTimersByTimeAsync(50);
    expect(screen.getByText("QX7R2M")).toBeInTheDocument();
    await vi.advanceTimersByTimeAsync(2 * 86_400_000);
    expect(screen.queryByText("QX7R2M")).not.toBeInTheDocument();
    expect(screen.getByText("You’re offline, and no trip is saved on this device")).toBeInTheDocument();
    expect(shell.posts.map((p) => p.type)).toContain("remove");
  });
});

describe("an arrival with no connection, on the cached page", () => {
  const lot = segment({
    id: 5, trip_id: 1, kind: "parking", origin: "Harbour Parking, Lot B", provider: null, destination: null, confirmation: "HP-48213",
    start_local: "2026-11-20T09:00", start_zone: "America/Denver", end_local: "2026-11-23T18:00", end_zone: "America/Denver", details: {}, gate_code: { state: "ready", day: "2026-10-16" },
  });
  const rental = segment({ id: 6, trip_id: 1, kind: "car", provider: "Sol Rent a Car", origin: "Lisbon Airport", destination: null, confirmation: "SR-7Q2K9", start_local: "2026-11-20T13:30", start_zone: "America/Denver", end_local: "2026-11-23T10:00", end_zone: "America/Denver", details: {} });
  const saved = (withPicture: boolean) => ({ savedAt: Date.now(), messages: [], codes: withPicture ? [{ segment_id: 5, type: "image/png", data: "QUJD" }] : [], trip: { ...trip([lot, rental]), id: 1, name: "Trip to Denver", end_date: "2026-11-24" } });

  it("opens the QR code of the booking from the saved picture after a tap on the notification", async () => {
    shell = installShell({ trips: [saved(true)], savedAt: Date.now() });
    shell.replies.set("pendingArrival", { version: 1, segmentId: 5, tripId: 1 });
    render(App);
    const dialog = await screen.findByRole("dialog", { name: "QR code" });
    expect(location.hash).toBe("#trip/1");
    expect(await within(dialog).findByRole("img", { name: "QR code for Harbour Parking, Lot B" })).toHaveAttribute("src", "data:image/png;base64,QUJD");
  });

  it("opens the confirmation of a rental pickup the same way", async () => {
    shell = installShell({ trips: [saved(true)], savedAt: Date.now() });
    shell.replies.set("pendingArrival", { version: 1, segmentId: 6, tripId: 1 });
    render(App);
    expect(await screen.findByRole("dialog", { name: "Pickup" })).toHaveTextContent("SR-7Q2K9");
  });

  it("shows the failure line and the confirmation number when no picture was saved for the booking", async () => {
    shell = installShell({ trips: [saved(false)], savedAt: Date.now() });
    shell.replies.set("pendingArrival", { version: 1, segmentId: 5, tripId: 1 });
    render(App);
    expect(await screen.findByRole("alert")).toHaveTextContent("The code can’t be shown right now");
    expect(screen.getByTestId("code-confirmation")).toHaveTextContent("Confirmation HP-48213");
  });

  it("gives the saved trip page a Show QR code button for its parking booking, and no way to choose a picture", async () => {
    shell = installShell({ trips: [saved(true)], savedAt: Date.now() });
    render(App);
    await go("#trip/1");
    await userEvent.setup({ pointerEventsCheck: 0 }).click(await screen.findByRole("button", { name: "Show QR code for Harbour Parking, Lot B" }));
    expect(await screen.findByRole("img", { name: "QR code for Harbour Parking, Lot B" })).toHaveAttribute("src", "data:image/png;base64,QUJD");
    expect(screen.queryByRole("button", { name: /Choose/ })).toBeNull();
  });

  it("puts the card on the saved trips’ Upcoming when the app says you are at a booking, and opens nothing by itself", async () => {
    shell = installShell({ trips: [saved(true)], savedAt: Date.now() });
    shell.replies.set("arrivalHere", { version: 1, segmentId: 6, tripId: 1 });
    render(App);
    const card = await screen.findByRole("status", { name: "You’re at Sol Rent a Car · Lisbon Airport" });
    expect(card).toHaveTextContent("Your code is one tap away.");
    expect(screen.queryByRole("dialog")).toBeNull();
    await userEvent.setup({ pointerEventsCheck: 0 }).click(screen.getByRole("button", { name: "Show pickup" }));
    expect(await screen.findByRole("dialog", { name: "Pickup" })).toBeInTheDocument();
    expect(location.hash).toBe("#trip/1");
    expect(screen.getByTestId("offline-banner")).toBeInTheDocument();
    await userEvent.setup({ pointerEventsCheck: 0 }).click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("heading", { name: "Trip to Denver" })).toBeInTheDocument();
  });
});
