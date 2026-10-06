// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn(), warning: vi.fn() }) }));

import { api } from "$lib/api";
import type { Mailbox, MailboxList } from "$lib/api-types";
import { toast } from "svelte-sonner";
import GmailSection from "./GmailSection.svelte";

const box = (extra: Partial<Mailbox> = {}): Mailbox => ({ id: 1, address: "ana@gmail.example", status: "connected", last_error: null, last_scan: null, scan_error: null, scanning: false, scan_notice: null, share_review: false, ...extra });
const list = (mailboxes: Mailbox[] = [], configured = true): MailboxList => ({ configured, mailboxes });
const serve = (reply: MailboxList, others: (path: string) => unknown = () => ({})) =>
  vi.mocked(api).mockImplementation(async (path: string) => (path === "/api/mailboxes" ? reply : others(path)) as never);

beforeEach(() => { vi.mocked(api).mockReset(); vi.mocked(toast.success).mockReset(); vi.mocked(toast.warning).mockReset(); });
afterEach(() => { vi.unstubAllGlobals(); history.replaceState(null, "", "/"); });

describe("Settings → Gmail", () => {
  it("says Gmail isn’t set up, and offers no Connect, until the server has Google’s client", async () => {
    serve(list([], false));
    render(GmailSection);
    expect(await screen.findByText("Gmail isn’t set up")).toBeInTheDocument();
    expect(screen.getByText("GOOGLE_CLIENT_ID")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Connect/ })).toBeNull();
  });

  it("connects by sending the browser to Google’s address", async () => {
    const where = { href: "", pathname: "/", search: "", hash: "#settings" };
    vi.stubGlobal("location", where);
    serve(list(), (path) => (path === "/api/mailboxes/connect" ? { url: "https://accounts.example/consent?state=s1" } : {}));
    render(GmailSection);
    await userEvent.click(await screen.findByRole("button", { name: "Connect Gmail" }));
    expect(api).toHaveBeenCalledWith("/api/mailboxes/connect", { method: "POST" });
    await waitFor(() => expect(where.href).toBe("https://accounts.example/consent?state=s1"));
  });

  it("lists the member’s own Gmail accounts, each connected, and offers to add another", async () => {
    serve(list([box(), box({ id: 2, address: "work@gmail.example" })]));
    render(GmailSection);
    expect(await screen.findByText("ana@gmail.example")).toBeInTheDocument();
    expect(screen.getByText("work@gmail.example")).toBeInTheDocument();
    expect(screen.getAllByText("Connected")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Connect another" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reconnect" })).toBeNull();
  });

  it("shares a mailbox's unread mail with the household only when its owner ticks the box, and the box follows what the server kept", async () => {
    let shared = false;
    vi.mocked(api).mockImplementation((async (path: string, opts?: { method?: string; body?: { share: boolean } }) => {
      if (path === "/api/mailboxes") return list([box({ share_review: shared })]);
      if (path === "/api/mailboxes/1/share") { shared = opts!.body!.share; return { ok: true }; }
      return {};
    }) as never);
    render(GmailSection);
    const sharing = await screen.findByRole("checkbox", { name: /Show this mailbox’s unread mail to the household/ });
    expect(sharing).not.toBeChecked();
    await userEvent.click(sharing);
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/mailboxes/1/share", expect.objectContaining({ method: "POST", body: { share: true } })));
    await waitFor(() => expect(screen.getByRole("checkbox", { name: /Show this mailbox/ })).toBeChecked());
    expect(toast.success).toHaveBeenCalledWith("Shared with the household");
    await userEvent.click(screen.getByRole("checkbox", { name: /Show this mailbox/ }));
    await waitFor(() => expect(screen.getByRole("checkbox", { name: /Show this mailbox/ })).not.toBeChecked());
  });

  it("puts the box back, and says so, when the server refuses to change it", async () => {
    vi.mocked(api).mockImplementation((async (path: string) => {
      if (path === "/api/mailboxes") return list([box()]);
      throw new Error("Refused.");
    }) as never);
    render(GmailSection);
    const sharing = await screen.findByRole("checkbox", { name: /Show this mailbox/ });
    await userEvent.click(sharing);
    await waitFor(() => expect(vi.mocked(toast.error)).toHaveBeenCalled());
    expect(screen.getByRole("checkbox", { name: /Show this mailbox/ })).not.toBeChecked();
  });

  it("shows a grant Google dropped as Reconnect, with what happened, not as an error", async () => {
    const where = { href: "", pathname: "/", search: "", hash: "" };
    vi.stubGlobal("location", where);
    serve(list([box({ status: "reconnect", last_error: "Google no longer lets Waypoint read this mailbox." })]),
      () => ({ url: "https://accounts.example/consent" }));
    render(GmailSection);
    expect(await screen.findByText("Google no longer lets Waypoint read this mailbox.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Reconnect" }));
    await waitFor(() => expect(where.href).toBe("https://accounts.example/consent"));
  });

  it("says when Google couldn’t be reached, without asking for a reconnect", async () => {
    serve(list([box({ status: "error", last_error: "Couldn’t reach Google just now." })]));
    render(GmailSection);
    expect(await screen.findByText("Couldn’t reach Google")).toBeInTheDocument();
    expect(screen.getByText("Couldn’t reach Google just now.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reconnect" })).toBeNull();
  });

  it("disconnects after asking, then lists again", async () => {
    let mailboxes = [box()];
    vi.mocked(api).mockImplementation(async (path: string, opts?: { method?: string }) => {
      if (opts?.method === "DELETE") { mailboxes = []; return { ok: true, revoked: true } as never; }
      return list(mailboxes) as never;
    });
    render(GmailSection);
    await userEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
    expect(await screen.findByText("Disconnect ana@gmail.example?")).toBeInTheDocument();
    expect(api).not.toHaveBeenCalledWith("/api/mailboxes/1", expect.anything());
    await userEvent.click((await screen.findByRole("dialog")).querySelector("button[type=submit]")!);
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/mailboxes/1", { method: "DELETE", failed: "Couldn’t disconnect" }));
    await waitFor(() => expect(screen.queryByText("ana@gmail.example")).toBeNull());
    expect(toast.success).toHaveBeenCalledWith("Disconnected");
  });

  it("says when a connection was removed without being able to tell Google", async () => {
    let mailboxes = [box()];
    vi.mocked(api).mockImplementation(async (_path: string, opts?: { method?: string }) => {
      if (opts?.method === "DELETE") { mailboxes = []; return { ok: true, revoked: false } as never; }
      return list(mailboxes) as never;
    });
    render(GmailSection);
    await userEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
    await userEvent.click((await screen.findByRole("dialog")).querySelector("button[type=submit]")!);
    await waitFor(() => expect(toast.warning).toHaveBeenCalledWith(expect.stringContaining("myaccount.google.com/permissions")));
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("keeps the connection on screen when disconnecting fails", async () => {
    vi.mocked(api).mockImplementation(async (_path: string, opts?: { method?: string }) => {
      if (opts?.method === "DELETE") throw new Error("Couldn’t reach Google to revoke Waypoint’s access, so the mailbox is still connected.");
      return list([box()]) as never;
    });
    render(GmailSection);
    await userEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
    await userEvent.click((await screen.findByRole("dialog")).querySelector("button[type=submit]")!);
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("still connected")));
    expect(screen.getByText("ana@gmail.example")).toBeInTheDocument();
  });

  it.each([
    ["connected", "Gmail connected."],
    ["denied", "access wasn’t allowed"],
    ["scope", "Waypoint needs permission to read your email"],
    ["refused", "didn’t start here"],
    ["failed", "couldn’t connect it"],
  ])("says how Google’s return went (%s), once", async (code, words) => {
    history.replaceState(null, "", `/?gmail=${code}#settings`);
    serve(list());
    render(GmailSection);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(words));
    expect(location.search).toBe("");
    expect(location.hash).toBe("#settings");
  });

  it("ignores a return code it doesn’t know", async () => {
    history.replaceState(null, "", "/?gmail=<b>hi</b>#settings");
    serve(list());
    render(GmailSection);
    await screen.findByRole("button", { name: "Connect Gmail" });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says when a mailbox was last scanned, or that it hasn’t been", async () => {
    serve(list([box({ last_scan: "2026-09-30T07:02:00+00:00" }), box({ id: 2, address: "work@gmail.example" })]));
    render(GmailSection);
    expect(await screen.findByText(/^Last scanned .*2026/)).toBeInTheDocument();
    expect(screen.getByText("Not scanned yet.")).toBeInTheDocument();
  });

  it("scans now, and says when one is already running", async () => {
    let started = true;
    vi.mocked(api).mockImplementation(async (path: string, opts?: { method?: string }) =>
      (opts?.method === "POST" ? { started } : list([box()])) as never);
    render(GmailSection);
    await userEvent.click(await screen.findByRole("button", { name: "Scan now" }));
    expect(api).toHaveBeenCalledWith("/api/mailboxes/1/scan", { method: "POST", failed: "Couldn’t start the scan" });
    expect(toast).not.toHaveBeenCalled();
    started = false;
    await userEvent.click(screen.getByRole("button", { name: "Scan now" }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith("A scan of this mailbox is already running."));
  });

  it("looks back 18 months, and says when a scan is already running", async () => {
    serve(list([box()]), (path) => (path === "/api/mailboxes/1/backfill" ? { started: false } : {}));
    render(GmailSection);
    await userEvent.click(await screen.findByRole("button", { name: "Look back 18 months" }));
    expect(api).toHaveBeenCalledWith("/api/mailboxes/1/backfill", { method: "POST", failed: "Couldn’t start the look-back" });
    await waitFor(() => expect(toast).toHaveBeenCalledWith("A scan of this mailbox is already running."));
  });

  it("says a scan is running, and checks until it’s done", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      let scanning = true;
      vi.mocked(api).mockImplementation(async () => list([box({ scanning, last_scan: scanning ? null : "2026-09-30T07:02:00+00:00" })]) as never);
      render(GmailSection);
      expect(await screen.findByText("Scanning for bookings…")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Scanning…" })).toBeDisabled();
      scanning = false;
      await vi.advanceTimersByTimeAsync(3100);
      expect(await screen.findByRole("button", { name: "Scan now" })).toBeEnabled();
      expect(screen.queryByText("Scanning for bookings…")).toBeNull();
      const calls = vi.mocked(api).mock.calls.length;
      await vi.advanceTimersByTimeAsync(10_000);
      expect(vi.mocked(api).mock.calls.length).toBe(calls);
    } finally { vi.useRealTimers(); }
  });

  it("says what stopped the last scan, and that nothing was lost", async () => {
    serve(list([box({ scan_error: "Couldn’t reach Google while reading the mailbox." })]));
    render(GmailSection);
    expect(await screen.findByText(/The last scan stopped: Couldn’t reach Google while reading the mailbox\. What it had read is kept/)).toBeInTheDocument();
  });

  it("says why a scan couldn’t start, which isn’t a failed scan", async () => {
    serve(list([box({ scan_notice: "Google refused to refresh the connection just now." })]));
    render(GmailSection);
    expect(await screen.findByText("The scan couldn’t start: Google refused to refresh the connection just now.")).toBeInTheDocument();
    expect(screen.queryByText(/The last scan stopped/)).toBeNull();
  });

  it("looks again for a moment after Scan now, so a scan that couldn’t start says why", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      let notice: string | null = null;
      vi.mocked(api).mockImplementation(async (_path: string, opts?: { method?: string }) =>
        (opts?.method === "POST" ? { started: true } : list([box({ scan_notice: notice })])) as never);
      render(GmailSection);
      await userEvent.click(await screen.findByRole("button", { name: "Scan now" }));
      notice = "Google refused to refresh the connection just now.";
      await vi.advanceTimersByTimeAsync(3100);
      expect(await screen.findByText(/The scan couldn’t start: Google refused/)).toBeInTheDocument();
      await vi.advanceTimersByTimeAsync(10_000);
      const calls = vi.mocked(api).mock.calls.length;
      await vi.advanceTimersByTimeAsync(10_000);
      expect(vi.mocked(api).mock.calls.length).toBe(calls);
    } finally { vi.useRealTimers(); }
  });

  it("doesn’t show a stale notice for a connection that needs reconnecting", async () => {
    serve(list([box({ status: "reconnect", last_error: "Google no longer lets Waypoint read this mailbox.", scan_notice: "Old." })]));
    render(GmailSection);
    await screen.findByRole("button", { name: "Reconnect" });
    expect(screen.queryByText(/The scan couldn’t start/)).toBeNull();
  });

  it("offers no scan for a connection that needs reconnecting", async () => {
    serve(list([box({ status: "reconnect", last_error: "Google no longer lets Waypoint read this mailbox." })]));
    render(GmailSection);
    await screen.findByRole("button", { name: "Reconnect" });
    expect(screen.queryByRole("button", { name: "Scan now" })).toBeNull();
    expect(screen.queryByText("Not scanned yet.")).toBeNull();
  });

  it("says when the list can’t be loaded, and tries again", async () => {
    let up = false;
    vi.mocked(api).mockImplementation(async () => {
      if (!up) throw new Error("Waypoint is restarting or unreachable.");
      return list([box()]) as never;
    });
    render(GmailSection);
    expect(await screen.findByText("Waypoint is restarting or unreachable.")).toBeInTheDocument();
    up = true;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("ana@gmail.example")).toBeInTheDocument();
    expect(screen.queryByText("Waypoint is restarting or unreachable.")).toBeNull();
  });
});
