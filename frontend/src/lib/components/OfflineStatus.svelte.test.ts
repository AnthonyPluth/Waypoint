// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));
vi.mock("$lib/offline.svelte", async (importOriginal) => ({ ...(await importOriginal<typeof import("$lib/offline.svelte")>()), refreshOffline: vi.fn(), syncSavedTrip: vi.fn() }));

import { offline, syncSavedTrip } from "$lib/offline.svelte";
import OfflineStatus from "./OfflineStatus.svelte";

const reset = { checked: true, setUp: true, hasCopy: false, savedAt: null, off: false, damaged: false, supported: true, reason: "", declined: false, failed: false, tripId: null, tripName: "" };
beforeEach(() => { Object.assign(offline, reset); vi.mocked(syncSavedTrip).mockReset(); });
afterEach(() => vi.restoreAllMocks());

const line = () => screen.getByTestId("offline-status-line");

describe("OfflineStatus", () => {
  it("shows nothing until the device has been checked", () => {
    offline.checked = false;
    render(OfflineStatus);
    expect(screen.queryByTestId("offline-status")).not.toBeInTheDocument();
  });

  it("says the trip is saved and when it was updated", () => {
    Object.assign(offline, { hasCopy: true, savedAt: Date.now() - 2 * 3_600_000, tripId: 7, tripName: "Trip to Springfield" });
    render(OfflineStatus, { tripId: 7 });
    expect(line()).toHaveTextContent("Saved on this device · updated 2 h ago");
  });

  it("names the saved trip on the Upcoming page", () => {
    Object.assign(offline, { hasCopy: true, savedAt: Date.now(), tripId: 7, tripName: "Trip to Springfield" });
    render(OfflineStatus);
    expect(line()).toHaveTextContent("updated just now · “Trip to Springfield”");
  });

  it("says when another trip is the saved one", () => {
    Object.assign(offline, { hasCopy: true, savedAt: Date.now(), tripId: 7, tripName: "Trip to Springfield" });
    render(OfflineStatus, { tripId: 9 });
    expect(line()).toHaveTextContent("Saved on this device: “Trip to Springfield”. This trip isn’t the one saved");
  });

  it("explains what is left out and how it unlocks before anyone relies on it", async () => {
    Object.assign(offline, { hasCopy: true, savedAt: Date.now() });
    render(OfflineStatus, { tripId: 1 });
    await userEvent.setup().click(screen.getByText("What offline includes"));
    expect(screen.getByText(/loyalty and Known Traveler numbers, a parking booking’s gate-code image/)).toBeInTheDocument();
    expect(screen.getByText(/It stays locked until you unlock it/)).toBeInTheDocument();
  });

  it("offers setup when it is not set up", () => {
    offline.setUp = false;
    render(OfflineStatus, { tripId: 1 });
    expect(line()).toHaveTextContent("Not saved for offline use.");
    expect(screen.getByRole("button", { name: "Set up offline access" })).toBeInTheDocument();
  });

  it("says why when the device can’t, with nothing to set up", () => {
    Object.assign(offline, { setUp: false, supported: false, reason: "No passkeys here." });
    render(OfflineStatus, { tripId: 1 });
    expect(line()).toHaveTextContent("Offline access isn’t available on this device. No passkeys here.");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByText("What offline includes")).not.toBeInTheDocument();
  });

  it("shows a failed save, keeps the older copy’s age and retries", async () => {
    Object.assign(offline, { hasCopy: true, savedAt: Date.now() - 3_600_000, failed: true, tripId: 1 });
    render(OfflineStatus, { tripId: 1 });
    expect(line()).toHaveTextContent("Couldn’t save the trip on this device. The copy from 1 h ago is still there.");
    await userEvent.setup().click(screen.getByRole("button", { name: "Try again" }));
    expect(syncSavedTrip).toHaveBeenCalledOnce();
  });

  it("says when saving is off and when the saved trip can’t be read", () => {
    offline.off = true;
    const { unmount } = render(OfflineStatus, { tripId: 1 });
    expect(line()).toHaveTextContent("Offline saving is off on this device.");
    unmount();
    Object.assign(offline, { off: false, damaged: true, setUp: false });
    render(OfflineStatus, { tripId: 1 });
    expect(line()).toHaveTextContent("The saved trip can’t be read.");
  });

  it("says nothing is saved yet when set up with no copy", () => {
    render(OfflineStatus, { tripId: 1 });
    expect(line()).toHaveTextContent("Nothing is saved yet.");
  });
});
