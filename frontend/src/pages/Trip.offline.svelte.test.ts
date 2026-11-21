// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { Trip as TripT } from "$lib/api-types";
import { arrival } from "$lib/arrival.svelte";
import { route } from "$lib/app.svelte";
import { flightStatus } from "$lib/flightstatus.svelte";
import { offline } from "$lib/offline.svelte";
import { lock, save, saveAll, setUp } from "$lib/offline-vault";
import { installShell } from "../test/fake-shell";
import { installDevice, type Behaviour, type Device } from "../test/webauthn";
import { segment, trip } from "../test/fixtures";
import TripPage from "./Trip.svelte";

const flight = segment({ id: 1, confirmation: "QX7R2M" });
let held: TripT;
let device: Device;
const withDevice = (b: Behaviour = {}) => { device = installDevice(b); };

function serve() {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === "/api/people") return { people: [] };
    if (path === "/api/loyalty") return { loyalty: [], programs: {} };
    if (path === "/api/distance-unit") return { distance_unit: "mi" };
    if (String(path).endsWith("/summary")) throw new Error("no summary");
    if (path === "/api/offline") return { trips: [{ trip: held, messages: [] }] };
    return held;
  });
}

function goOffline() {
  vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
  vi.mocked(api).mockRejectedValue(new Error("Failed to fetch"));
}

beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([{}] as unknown as DOMRectList);
  vi.mocked(api).mockReset();
  held = { ...trip([flight]), name: "Trip to Springfield" };
  Object.assign(offline, { checked: false, setUp: false, hasCopy: false, savedAt: null, off: false, damaged: false, supported: true, reason: "", declined: false, failed: false, trips: [] });
  route.page = "trip"; route.sub = "1"; route.query = ""; location.hash = "#trip/1";
  withDevice();
  serve();
});
afterEach(() => { lock(); vi.restoreAllMocks(); vi.unstubAllGlobals(); flightStatus.list = null; });

describe("Trip: the saved offline copy", () => {
  it("does not show an offline notice or setup prompt for a past trip", async () => {
    held = trip([segment({ start_local: "2020-04-08T10:00", end_local: "2020-04-08T11:30" })], { name: "Past journey" });
    Object.assign(offline, { checked: true, setUp: true, hasCopy: true, trips: [{ id: 9, name: "Next cruise" }] });
    render(TripPage);
    await screen.findByRole("heading", { name: "Past journey" });
    expect(screen.queryByRole("dialog", { name: "Keep this trip available offline" })).not.toBeInTheDocument();
    expect(device.writes).toEqual([]);
  });

  it("asks once, after the trip loads online, and saves nothing until the person says yes", async () => {
    render(TripPage);
    expect(await screen.findByRole("dialog", { name: "Keep this trip available offline" })).toBeInTheDocument();
    expect(device.writes).toEqual([]);
    expect(device.calls.create).toBe(0);
  });

  it("leaves offline off on Not now, and writes nothing", async () => {
    render(TripPage);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Not now" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(device.writes).toEqual([]);
    expect(device.calls).toEqual({ create: 0, get: 0, deleted: 0 });
    expect(offline.setUp).toBe(false);
  });

  it("saves this trip, encrypted, once it is turned on", async () => {
    render(TripPage);
    await userEvent.setup().click(await screen.findByRole("button", { name: /^Turn on with / }));
    await waitFor(() => expect(device.files.size).toBe(2));
    expect(device.appears("Springfield")).toBe(false);
    expect(device.appears("QX7R2M")).toBe(false);
  });

  it("saves quietly, with no authenticator call, when it is already on", async () => {
    await setUp();
    const before = { ...device.calls };
    render(TripPage);
    await screen.findByRole("heading", { name: "Trip to Springfield" });
    await waitFor(() => expect(device.files.size).toBe(2));
    expect(device.calls).toEqual(before);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(device.appears("Springfield")).toBe(false);
  });

  it("neither asks nor saves on a device that can't do it", async () => {
    withDevice({ deviceCheck: false });
    render(TripPage);
    await screen.findByRole("heading", { name: "Trip to Springfield" });
    await waitFor(() => expect(offline.checked).toBe(true));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(device.writes).toEqual([]);
    expect(device.calls).toEqual({ create: 0, get: 0, deleted: 0 });
  });

  it("shows the locked screen offline, and the saved trip only after an unlock", async () => {
    await setUp();
    await save(held);
    goOffline();
    render(TripPage);
    expect(await screen.findByRole("heading", { name: "Saved trip is locked" })).toBeInTheDocument();
    expect(screen.queryByText("Trip to Springfield")).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Unlock" }));
    expect(await screen.findByRole("heading", { name: "Trip to Springfield" })).toBeInTheDocument();
    expect(screen.getByText("QX7R2M")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Saved trip is locked" })).not.toBeInTheDocument();
  });

  it("goes back to the locked screen when the vault locks", async () => {
    await setUp();
    await save(held);
    goOffline();
    render(TripPage);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Unlock" }));
    await screen.findByRole("heading", { name: "Trip to Springfield" });
    window.dispatchEvent(new Event("pagehide"));
    expect(await screen.findByRole("heading", { name: "Saved trip is locked" })).toBeInTheDocument();
    expect(screen.queryByText("QX7R2M")).not.toBeInTheDocument();
  });

  it("keeps showing the error when offline with nothing saved", async () => {
    goOffline();
    render(TripPage);
    expect(await screen.findByText("Failed to fetch")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Saved trip is locked" })).not.toBeInTheDocument();
  });

  it("keeps showing the error when the server fails while online", async () => {
    await setUp();
    await save(held);
    vi.mocked(api).mockRejectedValue(new Error("Server error"));
    render(TripPage);
    expect(await screen.findByText("Server error")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Saved trip is locked" })).not.toBeInTheDocument();
  });

  it("treats a saved copy that isn't a trip as a failed unlock", async () => {
    await setUp();
    await save({ nothing: "useful" });
    goOffline();
    render(TripPage);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Unlock" }));
    expect(await screen.findByText(/That didn’t work/)).toBeInTheDocument();
  });

  it("opens this trip from several saved copies after one unlock", async () => {
    await setUp();
    const other = { ...held, id: 2, name: "Trip to Paris" };
    const copies = [held, other].map((t) => ({ value: { trip: t, messages: [], savedAt: 1 }, info: { savedAt: 1, expiresAt: null, tripId: t.id } }));
    await saveAll(copies);
    goOffline();
    render(TripPage);
    const asked = device.calls.get;
    await userEvent.setup().click(await screen.findByRole("button", { name: "Unlock" }));
    expect(await screen.findByRole("heading", { name: "Trip to Springfield" })).toBeInTheDocument();
    expect(device.calls.get).toBe(asked + 1);
  });

  it("says plainly when this trip isn't one of the saved copies, and offers the saved ones", async () => {
    await setUp();
    const other = { ...held, id: 2, name: "Trip to Paris" };
    await saveAll([{ value: { trip: other, messages: [], savedAt: 1 }, info: { savedAt: 1, expiresAt: null, tripId: 2 } }]);
    goOffline();
    render(TripPage);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Unlock" }));
    expect(await screen.findByRole("heading", { name: "This trip isn’t saved on this device" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Trip to Paris" })).toHaveAttribute("href", "#trip/2");
    expect(screen.queryByText("QX7R2M")).not.toBeInTheDocument();
  });

});

describe("Trip: a warm iPhone app that lost its connection", () => {
  const lot = segment({
    id: 5, trip_id: 1, kind: "parking", origin: "Harbour Parking, Lot B", provider: null, destination: null, confirmation: "HP-48213",
    start_local: "2099-12-01T09:00", start_zone: "America/Denver", end_local: "2099-12-05T18:00", end_zone: "America/Denver", details: {}, gate_code: { state: "ready", day: "2026-10-16" },
  });
  const saved = (id = 1) => ({ savedAt: Date.now(), messages: [], codes: [{ segment_id: 5, type: "image/png", data: "QUJD" }], trip: { ...trip([lot]), id, name: "Trip to Denver" } });

  afterEach(() => { arrival.target = null; });

  it("shows the saved trip, and opens the booking’s code the notification was for, instead of a connection error", async () => {
    installShell({ trips: [saved()] });
    arrival.target = { segmentId: 5, tripId: 1, at: Date.now() };
    vi.mocked(api).mockRejectedValue(new TypeError("Failed to fetch"));
    render(TripPage);
    expect(await screen.findByTestId("offline-banner")).toBeInTheDocument();
    expect(screen.queryByText("Failed to fetch")).not.toBeInTheDocument();
    expect(await screen.findByRole("dialog", { name: "QR code" })).toBeInTheDocument();
    expect(arrival.target).toBeNull();
  });

  describe("when the saved copy passes its retention deadline while the page stays open", () => {
    const ended = () => ({ ...saved(), trip: { ...trip([lot]), id: 1, name: "Trip to Denver", start_date: "2026-11-18", end_date: "2026-11-20" } });
    const deadline = new Date(2026, 10, 24, 0, 0).getTime();
    afterEach(() => { vi.useRealTimers(); });

    function open() {
      vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout"] });
      vi.setSystemTime(new Date(2026, 10, 22, 12, 0));
      installShell({ trips: [ended()] });
      vi.mocked(api).mockRejectedValue(new TypeError("Failed to fetch"));
      return render(TripPage);
    }

    it("clears it at the deadline, without any other event", async () => {
      open();
      expect(await screen.findByTestId("offline-banner")).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Trip to Denver" })).toBeInTheDocument();
      await vi.advanceTimersByTimeAsync(deadline - Date.now() + 1);
      await vi.waitFor(() => expect(screen.queryByTestId("offline-banner")).not.toBeInTheDocument());
      expect(screen.queryByRole("heading", { name: "Trip to Denver" })).not.toBeInTheDocument();
      expect(await screen.findByText("Failed to fetch")).toBeInTheDocument();
    });

    it("clears it when the app comes back to the front after the deadline", async () => {
      open();
      expect(await screen.findByTestId("offline-banner")).toBeInTheDocument();
      vi.setSystemTime(deadline + 60_000);
      document.dispatchEvent(new Event("visibilitychange"));
      await vi.waitFor(() => expect(screen.queryByTestId("offline-banner")).not.toBeInTheDocument());
      expect(screen.queryByRole("heading", { name: "Trip to Denver" })).not.toBeInTheDocument();
    });

    it("keeps it while it is still within its retention", async () => {
      open();
      expect(await screen.findByTestId("offline-banner")).toBeInTheDocument();
      vi.setSystemTime(deadline - 60_000);
      window.dispatchEvent(new Event("focus"));
      await vi.advanceTimersByTimeAsync(1_000);
      expect(screen.getByTestId("offline-banner")).toBeInTheDocument();
    });

    it("does not show a copy the phone handed over after its deadline", async () => {
      vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout"] });
      vi.setSystemTime(deadline + 60_000);
      installShell({ trips: [ended()] });
      vi.mocked(api).mockRejectedValue(new TypeError("Failed to fetch"));
      render(TripPage);
      expect(await screen.findByText("Failed to fetch")).toBeInTheDocument();
      expect(screen.queryByTestId("offline-banner")).not.toBeInTheDocument();
    });
  });

  it("keeps the error when the server answered, or when this trip is not saved", async () => {
    installShell({ trips: [saved()] });
    vi.mocked(api).mockRejectedValue(Object.assign(new Error("Server error"), { status: 500 }));
    const { unmount } = render(TripPage);
    expect(await screen.findByText("Server error")).toBeInTheDocument();
    unmount();
    vi.unstubAllGlobals();
    installShell({ trips: [saved(2)] });
    vi.mocked(api).mockRejectedValue(new TypeError("Failed to fetch"));
    render(TripPage);
    expect(await screen.findByText("Failed to fetch")).toBeInTheDocument();
  });

  it("keeps the error when the saved trips cannot be read, and in a browser", async () => {
    const shell = installShell({ trips: [saved()] });
    shell.replies.set("load", { version: 9, trips: [] });
    vi.mocked(api).mockRejectedValue(new TypeError("Failed to fetch"));
    const { unmount } = render(TripPage);
    expect(await screen.findByText("Failed to fetch")).toBeInTheDocument();
    unmount();
    vi.unstubAllGlobals();
    render(TripPage);
    expect(await screen.findByText("Failed to fetch")).toBeInTheDocument();
  });
});
