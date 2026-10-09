// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { installDevice, type Behaviour, type Device } from "../../../test/webauthn";
import { offline } from "$lib/offline.svelte";
import { hasSavedTrip, isSavingOff, lock, save, setUp } from "$lib/offline-vault";
import OfflineSection from "./OfflineSection.svelte";

let device: Device;
const withDevice = (b: Behaviour = {}) => { device = installDevice(b); };

beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([{}] as unknown as DOMRectList);
  Object.assign(offline, { checked: false, setUp: false, hasCopy: false, savedAt: null, off: false, damaged: false, supported: true, reason: "", declined: false });
  withDevice();
});
afterEach(() => { lock(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("Settings → Offline access", () => {
  it("offers to set it up, and sets it up from the sheet", async () => {
    render(OfflineSection);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Set up offline access" }));
    expect(await screen.findByRole("dialog", { name: "Set up offline access" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Turn on with / }));
    expect(await screen.findByText("On for this device")).toBeInTheDocument();
    expect(device.calls.create).toBe(1);
    expect(screen.getByText(/Nothing is saved yet/)).toBeInTheDocument();
  });

  it("says why when the device can't do it, and offers nothing to set up", async () => {
    withDevice({ deviceCheck: false });
    render(OfflineSection);
    expect(await screen.findByText("Offline access isn’t available on this device")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/can’t make a passkey that works offline/);
    expect(screen.getByText("Waypoint works online as always.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Set up offline access" })).not.toBeInTheDocument();
    expect(device.writes).toEqual([]);
  });

  it("says why in a browser without the pieces", async () => {
    vi.stubGlobal("caches", undefined);
    render(OfflineSection);
    expect(await screen.findByRole("status")).toHaveTextContent(/browser can’t keep an encrypted copy/);
  });

  it("shows it is on, and removes the saved trip after a confirmation", async () => {
    await setUp();
    await save({ id: 1 });
    render(OfflineSection);
    const user = userEvent.setup();
    expect(await screen.findByText("On for this device")).toBeInTheDocument();
    expect(screen.queryByText(/Nothing is saved yet/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove from this device" }));
    await user.click(await screen.findByRole("button", { name: "Remove" }));
    expect(await screen.findByRole("button", { name: "Set up offline access" })).toBeInTheDocument();
    expect(device.files.size).toBe(0);
  });

  it("shows when the trip was saved", async () => {
    await setUp();
    await save({ id: 1 }, { savedAt: Date.now() - 3 * 3_600_000, expiresAt: null });
    render(OfflineSection);
    expect(await screen.findByTestId("offline-saved")).toHaveTextContent("Saved 3 h ago.");
  });

  it("turns saving off with the switch, clearing the copy, and back on", async () => {
    await setUp();
    await save({ id: 1 }, { savedAt: Date.now(), expiresAt: null });
    render(OfflineSection);
    const user = userEvent.setup();
    const toggle = await screen.findByRole("switch", { name: "Save my current trip on this device" });
    expect(toggle).toBeChecked();
    await user.click(toggle);
    await waitFor(() => expect(screen.getByRole("switch")).not.toBeChecked());
    expect(await isSavingOff()).toBe(true);
    expect(await hasSavedTrip()).toBe(false);
    expect(screen.getByText("Off on this device")).toBeInTheDocument();
    expect(screen.getByTestId("offline-saved")).toHaveTextContent("Nothing is saved on this device.");
    await user.click(screen.getByRole("switch"));
    await waitFor(() => expect(screen.getByRole("switch")).toBeChecked());
    expect(await isSavingOff()).toBe(false);
  });

  it("offers to remove a saved trip that can't be read", async () => {
    await setUp();
    device.files.set("/offline-vault/keys", new TextEncoder().encode("garbage"));
    render(OfflineSection);
    const user = userEvent.setup();
    expect(await screen.findByText("The saved trip can’t be read")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove from this device" }));
    await user.click(await screen.findByRole("button", { name: "Remove" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Set up offline access" })).toBeInTheDocument());
  });
});
