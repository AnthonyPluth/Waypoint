// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { Trip as TripT } from "$lib/api-types";
import { route } from "$lib/app.svelte";
import { flightStatus } from "$lib/flightstatus.svelte";
import { offline } from "$lib/offline.svelte";
import { lock, save, setUp } from "$lib/offline-vault";
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
    if (path === "/api/offline") return { trip: held, messages: [] };
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
  Object.assign(offline, { checked: false, setUp: false, hasCopy: false, savedAt: null, off: false, damaged: false, supported: true, reason: "", declined: false });
  route.page = "trip"; route.sub = "1"; route.query = ""; location.hash = "#trip/1";
  withDevice();
  serve();
});
afterEach(() => { lock(); vi.restoreAllMocks(); vi.unstubAllGlobals(); flightStatus.list = null; });

describe("Trip: the saved offline copy", () => {
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
});
