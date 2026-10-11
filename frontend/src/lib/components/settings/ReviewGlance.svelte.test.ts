// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn(), warning: vi.fn() }) }));

import { api } from "$lib/api";
import type { Mailbox, ReviewGlance as Glance } from "$lib/api-types";
import { toast } from "svelte-sonner";
import ReviewGlance, { reviewLink } from "./ReviewGlance.svelte";
import GmailSection from "./GmailSection.svelte";

const box: Mailbox = { id: 1, address: "ana@gmail.example", status: "connected", last_error: null, last_scan: null, scan_error: null, scanning: false, scan_notice: null, scan_summary: null, reading_again: null, share_review: false, labels_picked: 0 };
const glance = (extra: Partial<Glance> = {}): Glance => ({
  waiting: 6, days: 30,
  reasons: [{ reason: "no_markup", waiting: 3, recent: 2 }, { reason: "incomplete", waiting: 2, recent: 2 }, { reason: "match", waiting: 1, recent: 0 }],
  gaps: [{ label: "no place", count: 2 }, { label: "no end time", count: 1 }],
  domains: [
    { domain: "seaside-stays.example", count: 4, reason: "no_markup", item_id: 11, known_sender: false },
    { domain: "united.com", count: 1, reason: "incomplete", item_id: 12, known_sender: true },
    { domain: "", count: 1, reason: "match", item_id: null, known_sender: false },
  ],
  scans: [{ at: "2026-10-02T09:00:00+00:00", added: 3 }, { at: "2026-10-01T09:00:00+00:00", added: 1 }],
  ...extra,
});
const serve = (found: Glance | Error, onchange = vi.fn()) => {
  vi.mocked(api).mockImplementation((async (path: string, opts?: { method?: string }) => {
    if (path === "/api/mailboxes/1/review-glance") { if (found instanceof Error) throw found; return found; }
    if (path === "/api/review/11/ignore" && opts?.method === "POST") return { ok: true, mailbox_id: 1, domain: "seaside-stays.example" };
    if (path === "/api/mailboxes/1/unignore") return { started: true };
    return {};
  }) as never);
  return onchange;
};

beforeEach(() => { vi.mocked(api).mockReset(); vi.mocked(toast.success).mockReset(); });
afterEach(() => { vi.unstubAllGlobals(); });

describe("Settings → Gmail → Review at a glance", () => {
  it("shows the number waiting, the reasons with their counts, the gaps, the busiest domains and the scans", async () => {
    serve(glance());
    render(ReviewGlance, { mailbox: box, onchange: vi.fn() });
    const section = await screen.findByTestId("review-glance");
    expect(await within(section).findByText(/6 items are waiting in Review/)).toBeInTheDocument();
    const reasons = within(within(section).getByTestId("glance-reasons")).getAllByRole("row").map((r) => r.textContent);
    expect(reasons).toEqual(["ReasonWaitingAdded in the last 30 days", "No booking data found32", "Dates or place missing22", "Could be one of your bookings10"]);
    expect(within(within(section).getByTestId("glance-gaps")).getAllByRole("listitem").map((r) => r.textContent)).toEqual(["No place2", "No end time1"]);
    const domains = within(section).getByTestId("glance-domains");
    expect(within(domains).getAllByRole("listitem").map((r) => r.textContent?.replace(/\s+/g, " ").trim())).toEqual([
      "seaside-stays.example 4 items · mostly no booking data found Ignore this sender",
      "united.com 1 item · mostly dates or place missing Ignore this sender",
      "Unknown sender 1 item · mostly could be one of your bookings",
    ]);
    expect(within(section).getByTestId("glance-scans").querySelectorAll("li")).toHaveLength(2);
    expect(within(section).getByText("3 items")).toBeInTheDocument();
    expect(section.textContent).not.toMatch(/CANARY/);
  });

  it("links each domain to Review filtered to that sender in that mailbox", async () => {
    serve(glance());
    render(ReviewGlance, { mailbox: box, onchange: vi.fn() });
    const link = await screen.findByRole("link", { name: "Show seaside-stays.example in Review" });
    expect(link).toHaveAttribute("href", "#review?sender=seaside-stays.example&mailbox=ana%40gmail.example");
    expect(reviewLink("a.example", "x+y@gmail.example")).toBe("#review?sender=a.example&mailbox=x%2By%40gmail.example");
    expect(screen.queryByRole("link", { name: /Unknown/ })).toBeNull();
  });

  it("says so when nothing is waiting, and leaves out the tables", async () => {
    serve(glance({ waiting: 0, reasons: [], gaps: [], domains: [], scans: [] }));
    render(ReviewGlance, { mailbox: box, onchange: vi.fn() });
    expect(await screen.findByText("Nothing from this mailbox is waiting in Review.")).toBeInTheDocument();
    expect(screen.queryByTestId("glance-reasons")).toBeNull();
  });

  it("leaves the gaps out when none was recorded, and says no scan added anything in the last 30 days", async () => {
    serve(glance({ gaps: [], scans: [] }));
    render(ReviewGlance, { mailbox: box, onchange: vi.fn() });
    expect(await screen.findByText("None in the last 30 days.")).toBeInTheDocument();
    expect(screen.queryByTestId("glance-gaps")).toBeNull();
  });

  it("says when it couldn’t be loaded", async () => {
    serve(new Error("Nope."));
    render(ReviewGlance, { mailbox: box, onchange: vi.fn() });
    expect(await screen.findByText("Couldn’t load it.")).toBeInTheDocument();
  });

  it("asks before it ignores a travel company Waypoint knows, and ignores nothing when cancelled", async () => {
    serve(glance());
    render(ReviewGlance, { mailbox: box, onchange: vi.fn() });
    await userEvent.click(await screen.findByRole("button", { name: "Ignore united.com" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByTestId("known-sender-warning")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(api).not.toHaveBeenCalledWith("/api/review/12/ignore", expect.anything());
  });

  it("asks before it ignores a sender, then ignores it, reloads and offers the undo", async () => {
    const onchange = serve(glance());
    render(ReviewGlance, { mailbox: box, onchange });
    await userEvent.click(await screen.findByRole("button", { name: "Ignore seaside-stays.example" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Ignore seaside-stays.example?")).toBeInTheDocument();
    expect(within(dialog).queryByTestId("known-sender-warning")).toBeNull();
    await userEvent.click(dialog.querySelector("button[type=submit]")!);
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/review/11/ignore", { method: "POST" }));
    await waitFor(() => expect(onchange).toHaveBeenCalled());
    const [title, options] = vi.mocked(toast.success).mock.calls[0] as unknown as [string, { action: { label: string; onClick: () => void } }];
    expect(title).toBe("Ignoring seaside-stays.example");
    expect(options.action.label).toBe("Undo");
    options.action.onClick();
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/mailboxes/1/unignore", { method: "POST", body: { domain: "seaside-stays.example" }, failed: "Couldn’t undo that" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Reading again what was skipped from seaside-stays.example"));
  });
});

describe("Settings → Gmail", () => {
  const mailboxes = (...boxes: Mailbox[]) => vi.mocked(api).mockImplementation((async (path: string) => {
    if (path === "/api/mailboxes") return { configured: true, mailboxes: boxes };
    if (path.endsWith("/review-glance")) return glance();
    if (path.endsWith("/ignored")) return { domains: [] };
    return {};
  }) as never);

  it("shows Review at a glance under each connected mailbox", async () => {
    mailboxes(box, { ...box, id: 2, address: "work@gmail.example" });
    render(GmailSection);
    expect(await screen.findAllByTestId("review-glance")).toHaveLength(2);
    expect(api).toHaveBeenCalledWith("/api/mailboxes/2/review-glance");
  });

  it("shows it for no mailbox that needs reconnecting, and for none when there is no mailbox", async () => {
    mailboxes({ ...box, status: "reconnect" });
    const { unmount } = render(GmailSection);
    await screen.findByText("Reconnect", { selector: "button" });
    expect(screen.queryByTestId("review-glance")).toBeNull();
    unmount();
    mailboxes();
    render(GmailSection);
    await screen.findByText("Connect Gmail");
    expect(screen.queryByTestId("review-glance")).toBeNull();
  });
});
