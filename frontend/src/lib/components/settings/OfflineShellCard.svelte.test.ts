// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { toast } from "svelte-sonner";
import { offline } from "$lib/offline.svelte";
import { installShell, type FakeShell } from "../../../test/fake-shell";
import OfflineShellCard from "./OfflineShellCard.svelte";

const NOW = Date.UTC(2026, 10, 20, 12, 0);
const entry = (id: number, name: string) => ({ savedAt: NOW, messages: [], trip: { id, name } });
const TEN = ["Lisbon in June", "Denver offsite", "Kyoto in spring", "Oslo, long weekend", "Cape Town visit", "Lima and Cusco", "Berlin conference", "Hobart family trip", "Montreal in October", "Reykjavik stopover"];
const BACKUPS = "The saved copy can be part of your iCloud and computer backups.";
const FRESH = { syncing: false, oldApp: false, checked: false, setUp: false, hasCopy: false, savedAt: null, off: false, damaged: false, supported: true, reason: "", declined: false, failed: false, trips: [] };

let shell: FakeShell;
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"], now: NOW + 12 * 60_000 });
  Object.assign(offline, FRESH);
  vi.mocked(toast.error).mockReset();
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

const open = async (initial: Parameters<typeof installShell>[0]) => {
  shell = installShell(initial);
  render(OfflineShellCard);
  await screen.findByRole("switch", { name: "Save my upcoming trips" });
};

describe("the Offline access card inside the iPhone app", () => {
  it("shows two saved trips with when, when each is removed and the backups line", async () => {
    await open({ trips: [entry(1, "Lisbon in June"), entry(2, "Denver offsite")], savedAt: NOW });
    expect(screen.getByText("On for this device")).toBeInTheDocument();
    expect(screen.getByText("Saved")).toBeInTheDocument();
    expect(screen.getByTestId("offline-saved")).toHaveTextContent("Saved 12 min ago: “Lisbon in June”, “Denver offsite”.");
    expect(screen.getByText("Each trip is removed 3 days after it ends.")).toBeInTheDocument();
    expect(screen.getByText(BACKUPS)).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Save my upcoming trips" })).toBeChecked();
  });

  it("never offers a Remove button, a passkey or a device check, and carries no storage sentence", async () => {
    await open({ trips: [entry(1, "Lisbon in June")], savedAt: NOW });
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByText(/Remove from/)).not.toBeInTheDocument();
    expect(screen.queryByText(/isn’t available/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Face ID|Touch ID|passkey|encrypted/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/private storage/)).not.toBeInTheDocument();
  });

  it("shows ten trips as three names and 7 more, with Show all and Show fewer", async () => {
    await open({ trips: TEN.map((n, i) => entry(i + 1, n)), savedAt: NOW });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    expect(screen.getByTestId("offline-saved")).toHaveTextContent("Saved 12 min ago: “Lisbon in June”, “Denver offsite”, “Kyoto in spring” and 7 more.");
    await user.click(screen.getByRole("button", { name: "Show all 10" }));
    expect(screen.getAllByRole("listitem")).toHaveLength(10);
    expect(screen.getByTestId("offline-saved")).toHaveTextContent("Saved 12 min ago.");
    await user.click(screen.getByRole("button", { name: "Show fewer" }));
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
    expect(screen.getByText(/and 7 more/)).toBeInTheDocument();
  });

  it("shows three trips with no Show all", async () => {
    await open({ trips: TEN.slice(0, 3).map((n, i) => entry(i + 1, n)), savedAt: NOW });
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByTestId("offline-saved")).not.toHaveTextContent("more");
  });

  it("says nothing is saved yet when saving is on and no copy exists", async () => {
    await open({});
    expect(screen.getByText("On for this device")).toBeInTheDocument();
    expect(screen.getByTestId("offline-saved")).toHaveTextContent(/^Nothing is saved yet\. Your trips under way/);
    expect(screen.getByText("The first save happens when you open Waypoint online after signing in.")).toBeInTheDocument();
    expect(screen.getByText(BACKUPS)).toBeInTheDocument();
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
  });

  it("shows Saving your trips with the switch disabled while the app is fetching, then the result", async () => {
    await open({ syncing: true });
    expect(screen.getByText("Saving your trips…")).toBeInTheDocument();
    expect(screen.getByRole("switch")).toBeDisabled();
    expect(screen.queryByText(BACKUPS)).not.toBeInTheDocument();
    shell.syncing = false;
    shell.trips = [entry(1, "Kyoto in spring")];
    shell.savedAt = NOW;
    await vi.advanceTimersByTimeAsync(1000);
    await waitFor(() => expect(screen.getByTestId("offline-saved")).toHaveTextContent("Saved 12 min ago: “Kyoto in spring”."));
    expect(screen.getByRole("switch")).toBeEnabled();
  });

  it("says a save failed and an older copy is kept", async () => {
    await open({ lastSaveFailed: true, trips: [entry(1, "Lisbon in June"), entry(2, "Denver offsite")], savedAt: NOW - 2 * 3_600_000 + 12 * 60_000 });
    expect(screen.getByText("Couldn’t save the trips")).toBeInTheDocument();
    expect(screen.getByText("Not updated")).toBeInTheDocument();
    expect(screen.getByTestId("offline-saved")).toHaveTextContent("The copy from 2 h ago is still there: “Lisbon in June”, “Denver offsite”.");
    expect(screen.getByText("Saving is tried again each time you open Waypoint online.")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByText(BACKUPS)).not.toBeInTheDocument();
  });

  it("says a save failed with nothing saved yet", async () => {
    await open({ lastSaveFailed: true });
    expect(screen.getByText("Not saved")).toBeInTheDocument();
    expect(screen.getByText("Nothing is saved on this device yet.")).toBeInTheDocument();
  });

  it("says the saved trips can't be read and how to start afresh, then recovers by switching off", async () => {
    shell = installShell({ trips: [entry(1, "Lisbon in June")], savedAt: NOW });
    shell.replies.set("status", { version: 9 });
    render(OfflineShellCard);
    await screen.findByText("The saved trips can’t be read");
    expect(screen.getByText("Damaged")).toBeInTheDocument();
    expect(screen.getByText("Switch saving off to delete them, then switch it on again to save your trips afresh.")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    shell.replies.delete("status");
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(screen.getByRole("switch"));
    await screen.findByText("Off on this device");
    expect(offline.damaged).toBe(false);
  });

  it("turns saving off at once, with no confirmation, and on again", async () => {
    await open({ trips: [entry(1, "Lisbon in June")], savedAt: NOW });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(screen.getByRole("switch"));
    expect(await screen.findByText("Off on this device")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(shell.posts.filter((p) => p.type !== "status")).toEqual([{ type: "setSaving", on: false }]);
    expect(shell.trips).toEqual([]);
    expect(screen.getByText(/Anything saved before was deleted when you switched it off\./)).toBeInTheDocument();
    expect(screen.getByRole("switch")).not.toBeChecked();
    expect(screen.getByText(BACKUPS)).toBeInTheDocument();
    shell.syncing = true;
    await user.click(screen.getByRole("switch"));
    expect(shell.posts.filter((p) => p.type === "setSaving").at(-1)).toEqual({ type: "setSaving", on: true });
    expect(await screen.findByText("Saving your trips…")).toBeInTheDocument();
  });

  it("keeps polling the status for a few seconds after saving is switched on, then stops", async () => {
    await open({ saving: false });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(screen.getByRole("switch"));
    const before = shell.posts.filter((p) => p.type === "status").length;
    await vi.advanceTimersByTimeAsync(10_000);
    const polled = shell.posts.filter((p) => p.type === "status").length - before;
    expect(polled).toBeGreaterThanOrEqual(3);
    expect(polled).toBeLessThanOrEqual(4);
  });

  it("says so when the app can't change saving", async () => {
    await open({ trips: [entry(1, "Lisbon in June")], savedAt: NOW });
    shell.replies.set("setSaving", null);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(screen.getByRole("switch"));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Couldn’t change saving on this device"));
  });
});
