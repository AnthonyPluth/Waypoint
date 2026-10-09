// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { installDevice, type Behaviour, type Device } from "../../test/webauthn";
import { offline, refreshOffline } from "$lib/offline.svelte";
import { lock } from "$lib/offline-vault";
import OfflineSetup from "./OfflineSetup.svelte";

let device: Device;
const withDevice = async (b: Behaviour = {}) => { device = installDevice(b); await refreshOffline(); };

beforeEach(async () => {
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([{}] as unknown as DOMRectList);
  Object.assign(offline, { checked: false, setUp: false, hasCopy: false, damaged: false, supported: true, reason: "", declined: false });
  await withDevice();
});
afterEach(() => { lock(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("OfflineSetup", () => {
  it("explains the lock in the device's own words and turns on with the device check", async () => {
    const onenabled = vi.fn();
    render(OfflineSetup, { props: { open: true, onenabled } });
    expect(await screen.findByRole("dialog", { name: "Keep this trip available offline" })).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: /^Turn on with / }));
    await waitFor(() => expect(onenabled).toHaveBeenCalled());
    expect(device.calls.create).toBe(1);
    expect(offline.setUp).toBe(true);
    expect(device.files.size).toBe(1);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("leaves offline off and writes nothing on Not now", async () => {
    const onenabled = vi.fn();
    render(OfflineSetup, { props: { open: true, onenabled } });
    await userEvent.setup().click(await screen.findByRole("button", { name: "Not now" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(onenabled).not.toHaveBeenCalled();
    expect(offline.declined).toBe(true);
    expect(offline.setUp).toBe(false);
    expect(device.calls).toEqual({ create: 0, get: 0, deleted: 0 });
    expect(device.writes).toEqual([]);
  });

  it("counts closing the sheet as Not now", async () => {
    render(OfflineSetup, { props: { open: true } });
    await userEvent.setup().click(await screen.findByRole("button", { name: "Close" }));
    await waitFor(() => expect(offline.declined).toBe(true));
    expect(device.writes).toEqual([]);
  });

  it("stays open with a plain message when the check is cancelled, and stores nothing", async () => {
    await withDevice({ failCreate: "NotAllowedError" });
    const onenabled = vi.fn();
    render(OfflineSetup, { props: { open: true, onenabled } });
    await userEvent.setup().click(await screen.findByRole("button", { name: /^Turn on with / }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nothing was turned on");
    expect(onenabled).not.toHaveBeenCalled();
    expect(offline.setUp).toBe(false);
    expect(device.writes).toEqual([]);
  });

  it("says why on a device whose passkey has no PRF, and stores nothing", async () => {
    await withDevice({ prfOnCreate: "none" });
    render(OfflineSetup, { props: { open: true } });
    await userEvent.setup().click(await screen.findByRole("button", { name: /^Turn on with / }));
    expect(await screen.findByText(/can’t make a passkey that works offline/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Turn on with / })).not.toBeInTheDocument();
    expect(offline.supported).toBe(false);
    expect(device.writes).toEqual([]);
  });

  it("shows no way to turn on when the device is already known not to support it", async () => {
    await withDevice({ deviceCheck: false });
    render(OfflineSetup, { props: { open: true } });
    expect(await screen.findByText(/can’t make a passkey that works offline/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Turn on with / })).not.toBeInTheDocument();
    expect(device.calls.create).toBe(0);
  });
});
