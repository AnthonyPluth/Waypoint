// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { installDevice, type Behaviour, type Device } from "../../../test/webauthn";
import { offline } from "$lib/offline.svelte";
import { lock, save, setUp } from "$lib/offline-vault";
import OfflineSection from "./OfflineSection.svelte";

let device: Device;
const withDevice = (b: Behaviour = {}) => { device = installDevice(b); };

beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([{}] as unknown as DOMRectList);
  Object.assign(offline, { checked: false, setUp: false, hasCopy: false, damaged: false, supported: true, reason: "", declined: false });
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
    await user.click(screen.getByRole("button", { name: "Remove saved trip" }));
    await user.click(await screen.findByRole("button", { name: "Remove" }));
    expect(await screen.findByRole("button", { name: "Set up offline access" })).toBeInTheDocument();
    expect(device.files.size).toBe(0);
  });

  it("offers to remove a saved trip that can't be read", async () => {
    await setUp();
    device.files.set("/offline-vault/keys", new TextEncoder().encode("garbage"));
    render(OfflineSection);
    const user = userEvent.setup();
    expect(await screen.findByText("The saved trip can’t be read")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove saved trip" }));
    await user.click(await screen.findByRole("button", { name: "Remove" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Set up offline access" })).toBeInTheDocument());
  });
});
