// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login", onDenied: vi.fn() }));
vi.mock("svelte-sonner", () => ({ Toaster: vi.fn(), toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import { app } from "$lib/app.svelte";
import { expiryOf, type SavedCopy } from "$lib/offline";
import { offline } from "$lib/offline.svelte";
import { lock, save, setUp } from "$lib/offline-vault";
import { installDevice, type Device } from "./test/webauthn";
import { segment, trip } from "./test/fixtures";
import App from "./App.svelte";

const CANARY = "message-canary-91b3d2c7";
let device: Device;

const flight = segment({ id: 1, confirmation: "QX7R2M", has_email: true, start_local: "2026-11-20T19:00", end_local: "2026-11-21T07:10", details: { flight_number: "AA 101", seat: "14C" } });
const hotel = segment({ id: 2, kind: "hotel", confirmation: "H77231", provider: "Harbour Hotel", origin: "Harbour Hotel", destination: null, start_local: "2026-11-21T15:00", end_local: "2026-11-24T11:00",
  start_zone: "Europe/London", end_zone: "Europe/London", details: { address: "1 Quay Street, London", room: "King" }, links: { app: null, directions: "https://maps.example/q", call: "tel:+442079460000" } });

const copyOf = (savedAt: number): SavedCopy => ({
  savedAt, trip: { ...trip([flight, hotel]), name: "Trip to London" },
  messages: [{ segment_id: 1, emails: [{ subject: "Your itinerary", sender_domain: "air.example", received: "2026-11-01", text: CANARY, html: `<p>${CANARY}</p>`, truncated: false, original: true, images: 0 }] }],
});

const go = async (hash: string) => { location.hash = hash; window.dispatchEvent(new HashChangeEvent("hashchange")); await Promise.resolve(); };

async function saveCopy(savedAt = Date.now() - 2 * 3_600_000, copy = copyOf(savedAt)) {
  await setUp();
  await save(copy, { savedAt, expiresAt: expiryOf(copy) });
}

beforeEach(async () => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockRejectedValue(new Error("Can’t reach Waypoint."));
  device = installDevice();
  vi.setSystemTime(new Date(2026, 10, 20, 12, 0));
  Object.assign(offline, { checked: false, setUp: false, hasCopy: false, savedAt: null, off: false, damaged: false, supported: true, reason: "", declined: false });
  app.state = null; app.bootError = "Can’t reach Waypoint. Check your connection and try again."; app.offline = true;
  await go("#upcoming");
});
afterEach(() => { lock(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); app.bootError = ""; app.offline = false; });

describe("opening the app with no connection", () => {
  it("shows the unlock screen first, with no trip on it", async () => {
    await saveCopy();
    render(App);
    expect(await screen.findByRole("heading", { name: "Saved trip is locked" })).toBeInTheDocument();
    expect(screen.queryByText("Trip to London")).not.toBeInTheDocument();
    expect(screen.queryByText("QX7R2M")).not.toBeInTheDocument();
  });

  it("then shows the saved trip, read-only, under the offline banner", async () => {
    await saveCopy();
    render(App);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Unlock" }));
    expect(await screen.findByRole("heading", { name: "Trip to London" })).toBeInTheDocument();
    expect(screen.getByTestId("offline-banner")).toHaveTextContent("Offline. Saved 2 h ago.");
    expect(screen.getByTestId("offline-banner")).toHaveTextContent("Editing and adding need a connection");
    expect(screen.getAllByText("QX7R2M").length).toBeGreaterThan(0);
    expect(screen.getByText("H77231")).toBeInTheDocument();
    expect(screen.getByText(/14C/)).toBeInTheDocument();
    expect(screen.getByText("King")).toBeInTheDocument();
    expect(screen.getByText("1 Quay Street, London")).toBeInTheDocument();
    for (const name of [/^Edit/, /^Remove/, /Add a booking/, /Rename/]) expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    expect(api).not.toHaveBeenCalledWith("/api/flight-status", expect.anything());
    expect(screen.queryByText(/as of/)).not.toBeInTheDocument();
  });

  it("shows the booking's stored message when asked", async () => {
    await saveCopy();
    render(App);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Unlock" }));
    await screen.findByRole("heading", { name: "Trip to London" });
    const region = screen.getByRole("region", { name: /The email for/ });
    expect(within(region).getByText("Your itinerary")).toBeInTheDocument();
    expect(region).toHaveTextContent("air.example");
    expect(within(region).getByTestId("preview-html").getAttribute("srcdoc")).toContain(CANARY);
    expect(within(region).getByTestId("preview-html")).toHaveAttribute("sandbox", "allow-popups allow-popups-to-escape-sandbox");
  });

  it("keeps the check-in countdown and the route line going from the booked times and the device clock", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(new Date(2026, 10, 20, 12, 0));
    await saveCopy(Date.now() - 3_600_000);
    render(App);
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(await screen.findByRole("button", { name: "Unlock" }));
    await screen.findByRole("heading", { name: "Trip to London" });
    const card = document.querySelector("[data-kind=flight]") as HTMLElement;
    const before = card.querySelector("[data-headline]")?.textContent;
    const progress = card.getAttribute("data-progress");
    expect(before).toBeTruthy();
    vi.setSystemTime(new Date(2026, 10, 20, 21, 0));
    vi.advanceTimersByTime(60_000);
    await waitFor(() => expect(card.querySelector("[data-headline]")?.textContent).not.toBe(before));
    expect(card.getAttribute("data-progress")).not.toBe(progress);
  });

  it("goes back to the unlock screen when the app locks", async () => {
    await saveCopy();
    render(App);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Unlock" }));
    await screen.findByRole("heading", { name: "Trip to London" });
    window.dispatchEvent(new Event("pagehide"));
    expect(await screen.findByRole("heading", { name: "Saved trip is locked" })).toBeInTheDocument();
    expect(screen.queryByText("QX7R2M")).not.toBeInTheDocument();
  });

  it("says so when nothing is saved", async () => {
    render(App);
    expect(await screen.findByText("You’re offline, and no trip is saved on this device")).toBeInTheDocument();
    expect(screen.getByText(/Set up offline access in Settings/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Saved trip is locked" })).not.toBeInTheDocument();
  });

  it("says saving is switched off when it is", async () => {
    await setUp();
    device.files.set("/offline-vault/keys", new TextEncoder().encode(JSON.stringify({ ...device.fields("/offline-vault/keys"), off: true })));
    render(App);
    expect(await screen.findByText(/switched off on this device/)).toBeInTheDocument();
  });

  it("says a copy that ran out is gone instead of showing it", async () => {
    const savedAt = Date.now() - 6 * 86_400_000;
    const old = copyOf(savedAt);
    old.trip = { ...old.trip!, end_date: "2026-11-10" };
    await saveCopy(savedAt, old);
    render(App);
    expect(await screen.findByText("You’re offline, and no trip is saved on this device")).toBeInTheDocument();
  });

  it("treats a saved copy that opens to something else as a failed unlock", async () => {
    await setUp();
    await save({ nothing: "useful" });
    render(App);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Unlock" }));
    expect(await screen.findByText(/That didn’t work/)).toBeInTheDocument();
  });

  it("tells every other page it needs a connection", async () => {
    await saveCopy();
    for (const page of ["trips", "stats", "people", "review", "settings"]) {
      await go(`#${page}`);
      const { unmount } = render(App);
      expect(await screen.findByText("This page needs a connection")).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "Saved trip is locked" })).not.toBeInTheDocument();
      unmount();
    }
  });

  it("opens the saved trip on its own page address too", async () => {
    await saveCopy();
    await go("#trip/1");
    render(App);
    expect(await screen.findByRole("heading", { name: "Saved trip is locked" })).toBeInTheDocument();
  });

  it("is the normal app when the failure was not a lost connection", async () => {
    app.offline = false;
    await saveCopy();
    render(App);
    expect(await screen.findByText("Can’t reach Waypoint")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Saved trip is locked" })).not.toBeInTheDocument();
  });
});
