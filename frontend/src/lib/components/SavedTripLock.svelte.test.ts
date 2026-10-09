// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { installDevice, type Device } from "../../test/webauthn";
import { offline, refreshOffline } from "$lib/offline.svelte";
import { lock, save, setUp } from "$lib/offline-vault";
import SavedTripLock from "./SavedTripLock.svelte";

const TRIP = { id: 1, name: "Trip to London", segments: [] };
let device: Device;

beforeEach(async () => {
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([{}] as unknown as DOMRectList);
  Object.assign(offline, { checked: false, setUp: false, hasCopy: false, damaged: false, supported: true, reason: "", declined: false });
  device = installDevice();
  await setUp();
  await save(TRIP);
  await refreshOffline();
});
afterEach(() => { lock(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("SavedTripLock", () => {
  it("says the saved trip is locked and gives it only after an unlock", async () => {
    const onunlocked = vi.fn();
    render(SavedTripLock, { props: { onunlocked } });
    expect(screen.getByRole("heading", { name: "Saved trip is locked" })).toBeInTheDocument();
    expect(onunlocked).not.toHaveBeenCalled();
    await userEvent.setup().click(screen.getByRole("button", { name: "Unlock" }));
    await waitFor(() => expect(onunlocked).toHaveBeenCalledWith(TRIP));
  });

  it("stays locked with Try again when the unlock is cancelled, and never gives the data", async () => {
    const onunlocked = vi.fn();
    render(SavedTripLock, { props: { onunlocked } });
    const user = userEvent.setup();
    device.b.failGet = "NotAllowedError";
    await user.click(screen.getByRole("button", { name: "Unlock" }));
    expect(await screen.findByText(/Unlocking was cancelled/)).toBeInTheDocument();
    expect(onunlocked).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Saved trip is locked" })).toBeInTheDocument();
    device.b.failGet = undefined;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(onunlocked).toHaveBeenCalledWith(TRIP));
  });

  it("stays locked on another failure", async () => {
    const onunlocked = vi.fn();
    render(SavedTripLock, { props: { onunlocked } });
    device.b.failGet = "SecurityError";
    await userEvent.setup().click(screen.getByRole("button", { name: "Unlock" }));
    expect(await screen.findByText(/That didn’t work/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(onunlocked).not.toHaveBeenCalled();
  });

  it("offers to remove the saved trip when the passkey is gone, and removes it", async () => {
    const onunlocked = vi.fn();
    const onremoved = vi.fn();
    render(SavedTripLock, { props: { onunlocked, onremoved } });
    const user = userEvent.setup();
    device.b.failGet = "InvalidStateError";
    await user.click(screen.getByRole("button", { name: "Unlock" }));
    expect(await screen.findByText(/can’t unlock it/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Unlock" })).not.toBeInTheDocument();
    expect(onunlocked).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Remove saved trip" }));
    await user.click(await screen.findByRole("button", { name: "Remove" }));
    await waitFor(() => expect(onremoved).toHaveBeenCalled());
    expect(device.files.size).toBe(0);
    expect(offline.setUp).toBe(false);
  });

  it("treats a receiver that can't use the data as a failed unlock", async () => {
    const onunlocked = vi.fn(() => { throw new Error("unreadable"); });
    render(SavedTripLock, { props: { onunlocked } });
    await userEvent.setup().click(screen.getByRole("button", { name: "Unlock" }));
    expect(await screen.findByText(/That didn’t work/)).toBeInTheDocument();
  });
});
