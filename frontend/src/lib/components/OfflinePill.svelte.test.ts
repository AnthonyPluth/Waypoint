// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/offline.svelte", async (importOriginal) => ({ ...(await importOriginal<typeof import("$lib/offline.svelte")>()), refreshOffline: vi.fn() }));

import { offline, refreshOffline } from "$lib/offline.svelte";
import OfflinePill from "./OfflinePill.svelte";

const working = { checked: true, setUp: true, hasCopy: true, savedAt: Date.now(), off: false, damaged: false, supported: true, reason: "", declined: false, failed: false, syncing: false, oldApp: false, trips: [{ id: 7, name: "Trip to Springfield" }] };
beforeEach(() => { Object.assign(offline, working); vi.mocked(refreshOffline).mockReset(); });

describe("OfflinePill", () => {
  it("shows Saved for offline, linking to the offline settings, while saving is working", () => {
    render(OfflinePill);
    expect(screen.getByRole("link", { name: "Saved for offline" })).toHaveAttribute("href", "#settings/offline");
    expect(refreshOffline).not.toHaveBeenCalled();
  });

  it.each([
    ["offline saving is off", { off: true }],
    ["the last save failed", { failed: true }],
    ["the saved copy can't be read", { damaged: true }],
    ["offline access isn't set up", { setUp: false }],
    ["nothing is saved", { hasCopy: false, savedAt: null }],
    ["the device can't save", { supported: false }],
  ])("shows nothing when %s", (_why, state) => {
    Object.assign(offline, state);
    render(OfflinePill);
    expect(screen.queryByTestId("offline-pill")).not.toBeInTheDocument();
  });

  it("checks the device once on its own when nothing has checked yet, so the pill can appear", () => {
    offline.checked = false;
    render(OfflinePill);
    expect(refreshOffline).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("offline-pill")).not.toBeInTheDocument();
  });
});
