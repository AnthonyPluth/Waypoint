// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn(), warning: vi.fn() }) }));

import { api } from "$lib/api";
import type { Mailbox, MailboxList, ReviewGlance } from "$lib/api-types";
import { toast } from "svelte-sonner";
import GmailSection from "./GmailSection.svelte";

const box = (extra: Partial<Mailbox> = {}): Mailbox => ({ id: 1, address: "ana@gmail.example", status: "connected", last_error: null, last_scan: null, scan_error: null, scanning: false, scan_notice: null, scan_summary: null, reading_again: null, share_review: false, labels_picked: 0, ...extra });
const list = (mailboxes: Mailbox[] = [], configured = true): MailboxList => ({ configured, mailboxes });
const NOTHING_WAITING: ReviewGlance = { waiting: 0, days: 30, reasons: [], gaps: [], domains: [], scans: [] };
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const mockApi = (reply: (...args: any[]) => unknown) =>
  vi.mocked(api).mockImplementation((async (path: string, ...rest: unknown[]) => (/\/review-glance$/.test(path) ? NOTHING_WAITING : reply(path, ...rest))) as never);
const serve = (reply: MailboxList, others: (path: string) => unknown = () => ({}), ignored: Record<number, string[]> = {}) =>
  mockApi(async (path: string) => {
    if (path === "/api/mailboxes") return reply as never;
    const listed = /^\/api\/mailboxes\/(\d+)\/ignored$/.exec(path);
    if (listed) return { domains: ignored[Number(listed[1])] ?? [] } as never;
    return others(path) as never;
  });

beforeEach(() => { vi.mocked(api).mockReset(); vi.mocked(toast.success).mockReset(); vi.mocked(toast.warning).mockReset(); });
afterEach(() => { vi.unstubAllGlobals(); history.replaceState(null, "", "/"); });

describe("Settings → Gmail → Ignored senders", () => {
  it("lists the domains a mailbox ignores, with a count in the heading", async () => {
    serve(list([box()]), undefined, { 1: ["example-air.example", "mail.seaside-stays.example"] });
    render(GmailSection);
    const section = await screen.findByTestId("ignored-senders");
    expect(await within(section).findByRole("heading", { name: "Ignored senders (2)" })).toBeInTheDocument();
    expect(within(section).getByText("example-air.example")).toBeInTheDocument();
    expect(within(section).getByRole("button", { name: "Stop ignoring example-air.example" })).toBeInTheDocument();
    expect(within(section).getByRole("button", { name: "Stop ignoring mail.seaside-stays.example" })).toBeInTheDocument();
  });

  it("says None when a mailbox ignores nobody", async () => {
    serve(list([box()]));
    render(GmailSection);
    const section = await screen.findByTestId("ignored-senders");
    expect(await within(section).findByRole("heading", { name: "Ignored senders (0)" })).toBeInTheDocument();
    expect(within(section).getByText("None")).toBeInTheDocument();
    expect(within(section).queryByRole("button")).toBeNull();
  });

  it("lists each mailbox’s own ignored senders", async () => {
    serve(list([box(), box({ id: 2, address: "work@gmail.example" })]), undefined, { 1: ["example-air.example"], 2: [] });
    render(GmailSection);
    const sections = await screen.findAllByTestId("ignored-senders");
    await waitFor(() => expect(within(sections[0]).getByText("example-air.example")).toBeInTheDocument());
    expect(within(sections[1]).getByText("None")).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith("/api/mailboxes/2/ignored");
  });

  it("says when the list couldn’t be loaded", async () => {
    mockApi((async (path: string) => {
      if (path === "/api/mailboxes") return list([box()]);
      throw new Error("Nope.");
    }) as never);
    render(GmailSection);
    expect(await screen.findByText("Couldn’t load the list.")).toBeInTheDocument();
  });

  it("asks before it stops ignoring, then removes the row and shows the scan starting", async () => {
    let gone = false;
    mockApi((async (path: string) => {
      if (path === "/api/mailboxes") return list([box({ scanning: gone, reading_again: gone ? "example-air.example" : null })]);
      if (path === "/api/mailboxes/1/ignored") return { domains: gone ? [] : ["example-air.example"] };
      if (path === "/api/mailboxes/1/unignore") { gone = true; return { started: true }; }
      return {};
    }) as never);
    render(GmailSection);
    await userEvent.click(await screen.findByRole("button", { name: "Stop ignoring example-air.example" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Stop ignoring example-air.example?")).toBeInTheDocument();
    expect(within(dialog).getByText("Waypoint will read mail from this sender again and look back through what it skipped.")).toBeInTheDocument();
    expect(api).not.toHaveBeenCalledWith("/api/mailboxes/1/unignore", expect.anything());
    await userEvent.click(dialog.querySelector("button[type=submit]")!);
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/mailboxes/1/unignore", { method: "POST", body: { domain: "example-air.example" }, failed: "Couldn’t stop ignoring it" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Reading again what was skipped from example-air.example"));
    expect(await screen.findByText("Reading again what was skipped from example-air.example…")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("None")).toBeInTheDocument());
  });

  it("leaves the row alone when the confirm is cancelled", async () => {
    serve(list([box()]), undefined, { 1: ["example-air.example"] });
    render(GmailSection);
    await userEvent.click(await screen.findByRole("button", { name: "Stop ignoring example-air.example" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }));
    expect(api).not.toHaveBeenCalledWith("/api/mailboxes/1/unignore", expect.anything());
    expect(screen.getByText("example-air.example")).toBeInTheDocument();
  });

  it("says a running scan will need a look-back when one is already going", async () => {
    mockApi((async (path: string) => {
      if (path === "/api/mailboxes") return list([box()]);
      if (path === "/api/mailboxes/1/ignored") return { domains: ["example-air.example"] };
      if (path === "/api/mailboxes/1/unignore") return { started: false };
      return {};
    }) as never);
    render(GmailSection);
    await userEvent.click(await screen.findByRole("button", { name: "Stop ignoring example-air.example" }));
    await userEvent.click((await screen.findByRole("dialog")).querySelector("button[type=submit]")!);
    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.stringContaining("Look back through all mail")));
  });
});

describe("Settings → Gmail", () => {
  it("says in one line what the last scan found, read, filed, couldn't read and skipped, and nothing else", async () => {
    serve(list([box({ last_scan: "2026-10-05T10:00:00+00:00", scan_summary: { found: 24, read: 6, bookings: 3, review: 2, skipped: 15, capped: false, labels_dropped: 0, triaged: 0, total: 0, not_travel: 9, followups: 0, with_facts: 0, attached: 0, ai_asked: 0 } })]));
    render(GmailSection);
    expect(await screen.findByTestId("scan-summary")).toHaveTextContent("24 new messages found, 6 read, 3 bookings added or changed, 2 couldn’t be read, 15 skipped (9 as not travel).");
  });

  it("counts, and only counts, how many messages the AI was asked about on its own", async () => {
    serve(list([box({ scan_summary: { found: 30, read: 25, bookings: 2, review: 23, skipped: 5, capped: false, labels_dropped: 0, triaged: 0, total: 0, not_travel: 0, followups: 0, with_facts: 0, attached: 0, ai_asked: 20 } })]));
    render(GmailSection);
    expect(await screen.findByTestId("scan-summary")).toHaveTextContent("5 skipped. AI asked about 20.");
  });

  it("counts the follow-ups attached to bookings, and those with details it did not apply", async () => {
    serve(list([box({ scan_summary: { found: 9, read: 8, bookings: 1, review: 0, skipped: 0, capped: false, labels_dropped: 0, triaged: 0, total: 0, not_travel: 0, followups: 4, with_facts: 1, attached: 0, ai_asked: 0 } })]));
    render(GmailSection);
    expect(await screen.findByTestId("scan-summary")).toHaveTextContent("0 couldn’t be read, 4 follow-ups attached (1 with details not applied), 0 skipped.");
  });

  it("leaves the follow-up figure out when there were none", async () => {
    serve(list([box({ scan_summary: { found: 1, read: 1, bookings: 1, review: 0, skipped: 0, capped: false, labels_dropped: 0, triaged: 0, total: 0, not_travel: 0, followups: 1, with_facts: 0, attached: 0, ai_asked: 0 } })]));
    render(GmailSection);
    expect(await screen.findByTestId("scan-summary")).toHaveTextContent("1 follow-up attached, 0 skipped.");
  });

  it("counts the emails attached to a booking Waypoint already had, as a number only", async () => {
    serve(list([box({ scan_summary: { found: 5, read: 5, bookings: 1, review: 0, skipped: 0, capped: false, labels_dropped: 0, triaged: 0, total: 0, not_travel: 0, followups: 0, with_facts: 0, attached: 3, ai_asked: 0 } })]));
    render(GmailSection);
    expect(await screen.findByTestId("scan-summary")).toHaveTextContent("0 couldn’t be read, 3 emails attached to an existing booking, 0 skipped.");
  });

  it("says when more messages are waiting after the cap", async () => {
    serve(list([box({ scan_summary: { found: 1, read: 1, bookings: 1, review: 0, skipped: 0, capped: true, labels_dropped: 0, triaged: 40, total: 900, not_travel: 0, followups: 0, with_facts: 0, attached: 0, ai_asked: 0 } })]));
    render(GmailSection);
    expect(await screen.findByTestId("scan-summary")).toHaveTextContent("1 new message found, 1 read, 1 booking added or changed, 0 couldn’t be read, 0 skipped. Looked at 40 of 900 messages so far; the scan carries on by itself.");
  });

  it("shows no summary when there hasn't been a scan", async () => {
    serve(list([box()]));
    render(GmailSection);
    await screen.findByText("Not scanned yet.");
    expect(screen.queryByTestId("scan-summary")).toBeNull();
  });

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
    mockApi((async (path: string, opts?: { method?: string; body?: { share: boolean } }) => {
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
    mockApi((async (path: string) => {
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
    mockApi(async (path: string, opts?: { method?: string }) => {
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
    mockApi(async (_path: string, opts?: { method?: string }) => {
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
    mockApi(async (_path: string, opts?: { method?: string }) => {
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
    mockApi(async (path: string, opts?: { method?: string }) =>
      (opts?.method === "POST" ? { started } : list([box()])) as never);
    render(GmailSection);
    await userEvent.click(await screen.findByRole("button", { name: "Scan now" }));
    expect(api).toHaveBeenCalledWith("/api/mailboxes/1/scan", { method: "POST", failed: "Couldn’t start the scan" });
    expect(toast).not.toHaveBeenCalled();
    started = false;
    await userEvent.click(screen.getByRole("button", { name: "Scan now" }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith("A scan of this mailbox is already running."));
  });

  it("asks before looking back through all mail, then starts it, and says when a scan is already running", async () => {
    serve(list([box()]), (path) => (path === "/api/mailboxes/1/backfill" ? { started: false } : {}));
    render(GmailSection);
    await userEvent.click(await screen.findByRole("button", { name: "Look back through all mail" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/reads every message in the mailbox, newest first, and can take hours for a large inbox\. Bookings found are added as past trips\./)).toBeInTheDocument();
    expect(api).not.toHaveBeenCalledWith("/api/mailboxes/1/backfill", expect.anything());
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    document.body.style.pointerEvents = "";
    expect(api).not.toHaveBeenCalledWith("/api/mailboxes/1/backfill", expect.anything());
    await userEvent.click(screen.getByRole("button", { name: "Look back through all mail" }));
    await userEvent.click((await screen.findByRole("dialog")).querySelector("button[type=submit]")!);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/mailboxes/1/backfill", { method: "POST", failed: "Couldn’t start the look-back" }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith("A scan of this mailbox is already running."));
  });

  it("says what stopped a look-back that started, and that nothing was lost", async () => {
    let stopped = false;
    mockApi(async (_path: string, opts?: { method?: string }) =>
      (opts?.method === "POST" ? { started: true } : list([box({ scan_error: stopped ? "Couldn’t reach Google while reading the mailbox." : null })])) as never);
    render(GmailSection);
    await userEvent.click(await screen.findByRole("button", { name: "Look back through all mail" }));
    await userEvent.click((await screen.findByRole("dialog")).querySelector("button[type=submit]")!);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/mailboxes/1/backfill", { method: "POST", failed: "Couldn’t start the look-back" }));
    expect(toast).not.toHaveBeenCalled();
    document.body.style.pointerEvents = "";
    stopped = true;
    await userEvent.click(screen.getByRole("button", { name: "Scan now" }));
    expect(await screen.findByText(/The last scan stopped: Couldn’t reach Google while reading the mailbox\. What it had read is kept/)).toBeInTheDocument();
  });

  it("says a scan is running, and checks until it’s done", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      let scanning = true;
      mockApi(async () => list([box({ scanning, last_scan: scanning ? null : "2026-09-30T07:02:00+00:00" })]) as never);
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
      mockApi(async (_path: string, opts?: { method?: string }) =>
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
    mockApi(async () => {
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

  describe("labels to read in full", () => {
    const labels = [{ id: "Label_1", name: "Japan 2026", count: 12, picked: false }, { id: "Label_2", name: "Taxes", count: 3, picked: false }];
    const serveLabels = (picked = 0) => serve(list([box({ labels_picked: picked })]), (path) => (path === "/api/mailboxes/1/labels" ? { labels } : {}));

    it("picks none by default and lists only the user's own labels, with counts", async () => {
      serveLabels();
      render(GmailSection);
      expect(await screen.findByText(/pick your own labels to read in full/)).toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: "Choose labels" }));
      const group = await screen.findByRole("group", { name: /Labels to read in full/ });
      expect(within(group).getAllByRole("checkbox").map((c) => (c as HTMLInputElement).checked)).toEqual([false, false]);
      expect(within(group).getByText(/Japan 2026/)).toBeInTheDocument();
      expect(within(group).getByText(/12 messages/)).toBeInTheDocument();
      expect(within(group).queryByText(/INBOX|CATEGORY/)).toBeNull();
    });

    it("saves exactly the labels ticked", async () => {
      serveLabels();
      render(GmailSection);
      await userEvent.click(await screen.findByRole("button", { name: "Choose labels" }));
      await userEvent.click(await screen.findByRole("checkbox", { name: /Japan 2026/ }));
      await userEvent.click(screen.getByRole("button", { name: "Save labels" }));
      await waitFor(() => expect(api).toHaveBeenCalledWith("/api/mailboxes/1/labels", expect.objectContaining({ method: "POST", body: { labels: ["Label_1"] } })));
      expect(toast.success).toHaveBeenCalledWith("Labels saved. The next scan reads everything in them.");
    });

    it("says how many are picked and notes labels deleted in Gmail", async () => {
      serve(list([box({ labels_picked: 2, scan_summary: { found: 1, read: 1, bookings: 0, review: 0, skipped: 0, capped: false, labels_dropped: 1, triaged: 0, total: 0, not_travel: 0, followups: 0, with_facts: 0, attached: 0, ai_asked: 0 } })]));
      render(GmailSection);
      expect(await screen.findByText(/Reading everything in 2 labels you picked/)).toBeInTheDocument();
      expect(screen.getByTestId("scan-summary")).toHaveTextContent("1 label you picked was deleted in Gmail and was dropped.");
    });
  });
});
