// @vitest-environment jsdom
import { chooseZone } from "../test/zone";
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import { forgetAirportZones } from "$lib/airport-zones";
import type { Person, Review, ReviewCandidate, ReviewItem, ReviewMatch, WhoIsThis } from "$lib/api-types";
import { setQuery } from "$lib/app.svelte";
import { viewport } from "$lib/phone.svelte";
import { toast } from "svelte-sonner";
import ReviewPage, { providerFrom, REASONS } from "./Review.svelte";

const settled = () => waitFor(() => { expect(screen.queryByRole("dialog")).toBeNull(); expect(document.body.style.pointerEvents).not.toBe("none"); });

const item = (extra: Partial<ReviewItem> = {}): ReviewItem => ({
  id: 1, address: "ana@gmail.example", owner: "Ana Doe", mine: true, sender_domain: "example-air.example", known_sender: false, holds_bookings: false, subject: null, has_email: true, received: "2026-10-17",
  reason: "no_markup", suggestions: [], suggestion_error: null, auto_read: false, count: 1, others: [], ...extra });
const who = (extra: Partial<WhoIsThis> = {}): WhoIsThis => ({
  id: 7, name: "DOE/MIA MISS", segment_id: 3, trip_id: 2, kind: "flight", provider: "Example Air", origin: "JFK", destination: "SFO",
  start_local: "2026-12-08T08:00", start_zone: "America/New_York", ...extra });
const candidate = (extra: Partial<ReviewMatch["candidates"][number]> = {}): ReviewMatch["candidates"][number] => ({
  segment_id: 11, trip_id: 4, trip_name: "Trip to London", kind: "hotel", provider: null, origin: "Harbour Hotel", destination: null,
  start_local: "2026-11-21T15:00", end_local: "2026-11-27T10:00", ...extra });
const held_match = (extra: Partial<ReviewMatch> = {}): ReviewMatch => ({
  item_id: 9, entry: 1, subject: "Your stay: Harbour Hotel", received: "2026-10-18", mine: true,
  booking: { kind: "hotel", provider: "Example Hotels", confirmation: "H88231", origin: "Harbour Hotel", destination: null, start_local: "2026-11-21T15:00", end_local: "2026-11-27T10:00" },
  candidates: [candidate(), candidate({ segment_id: 12, trip_id: 5, trip_name: "Second trip" })], ...extra });
const mia: Person = { id: 2, display_name: "Mia Doe", first_name: null, legal_name: null, aliases: [], member: false, links: [] };
const jane: Person = { id: 1, display_name: "Jane Doe", first_name: null, legal_name: null, aliases: [], member: true, links: [] };

const SUGGESTION = { kind: "flight" as const, provider: "Example Air", confirmation: "QW4R7T", origin: "BOS", destination: "DEN",
  start_local: "2026-12-02T07:15", end_local: "2026-12-02T10:05" } as unknown as ReviewItem["suggestions"][number];
const PREVIEW = "Hello Jane,\nYour flight EX 410 leaves Boston at 7:15 am on 2 January.";
let previewFails = "";
let suggestFails = "";
let suggestOkFirst = 0;
let suggestGate: Promise<void> | null = null;
let segmentsMade = 0;
let secondSegmentFails = "";
let takeOffGate: Promise<void> | null = null;
let takeOffFails = "";
const ZONES: Record<string, string> = { BOS: "America/New_York", DEN: "America/Denver" };
let truncated = false;
let held: Review;
let sameAs: ReviewCandidate | null = null;
let sameFails = "";
let sameQueue: (ReviewCandidate | null)[] = [];
let calls: [string, string | undefined, unknown][];
function serve(failOn?: string) {
  vi.mocked(api).mockImplementation(async (path: string, opts?: { method?: string; body?: unknown }) => {
    calls.push([path, opts?.method, opts?.body]);
    if (failOn && path.startsWith(failOn)) throw new Error("Refused.");
    if (path === "/api/people") return { people: [jane, mia] } as never;
    if (path === "/api/review") return held as never;
    if (path === "/api/state") return {} as never;
    if (path.startsWith("/api/airports/")) { const code = path.split("/")[3] ?? ""; if (!ZONES[code]) throw new Error("No such airport"); return { code, name: code, city: code, country: "US", zone: ZONES[code] } as never; }
    if (path === "/api/segments") { if (secondSegmentFails && segmentsMade === 1) throw new Error(secondSegmentFails); return { id: 42 + segmentsMade++ } as never; }
    if (path.endsWith("/same")) { if (sameFails) throw new Error(sameFails); return { booking: sameQueue.length ? sameQueue.shift() ?? null : sameAs } as never; }
    if (path.endsWith("/attach")) return { ok: true, segment_id: 99 } as never;
    if (path.endsWith("/preview")) { if (previewFails) throw new Error(previewFails); return { text: PREVIEW, html: null, truncated } as never; }
    if (path.endsWith("/suggest")) { if (suggestGate) await suggestGate; if (suggestFails && suggestOkFirst-- <= 0) throw new Error(suggestFails); held = { ...held, items: held.items.map((i) => ({ ...i, suggestions: [SUGGESTION] })) }; return { ok: true } as never; }
    if (path.endsWith("/unignore")) return { started: true } as never;
    if (path.endsWith("/ignore")) { const id = Number(path.split("/")[3]); const domain = held.items.find((i) => i.id === id)?.sender_domain ?? ""; held = { ...held, items: held.items.filter((i) => i.id !== id) }; return { ok: true, mailbox_id: 5, domain } as never; }
    if (opts?.method === "DELETE" && path.includes("?suggestion=")) { const id = Number(path.split("/")[3]?.split("?")[0]); const gone = path.split("?")[1]?.split("&").map((q) => Number(q.split("=")[1])) ?? []; held = { ...held, items: held.items.map((i) => (i.id === id ? { ...i, suggestions: i.suggestions.filter((_, n) => !gone.includes(n + 1)) } : i)) }; return { ok: true } as never; }
    if (opts?.method === "DELETE" && path.includes("?segment=")) { if (takeOffGate) await takeOffGate; if (takeOffFails) throw new Error(takeOffFails); }
    if (opts?.method === "DELETE") { const id = Number(path.split("/")[3]?.split("?")[0]); held = { ...held, items: held.items.filter((i) => i.id !== id), matches: held.matches.filter((m) => m.item_id !== id) }; return { ok: true } as never; }
    if (path.endsWith("/match")) { const id = Number(path.split("/")[3]); held = { ...held, matches: held.matches.filter((m) => m.item_id !== id) }; return { ok: true } as never; }
    if (path.startsWith("/api/review/who/")) { const id = Number(path.split("/")[4]); held = { ...held, who: held.who.filter((w) => w.id !== id) }; return { ok: true, matched: 2 } as never; }
    throw new Error(`unexpected ${path}`);
  });
}

afterEach(() => { setQuery(""); });
beforeEach(() => { sameQueue = []; sameAs = null; sameFails = ""; vi.mocked(api).mockReset(); vi.mocked(toast.success).mockReset(); vi.mocked(toast.error).mockReset(); calls = []; segmentsMade = 0; secondSegmentFails = ""; takeOffGate = null; takeOffFails = ""; forgetAirportZones(); previewFails = suggestFails = ""; suggestOkFirst = 0; suggestGate = null; truncated = false; held = { matches: [], items: [item()], who: [who()], ai: false }; serve(); });

describe("Review", () => {
  it("lists mail Waypoint couldn’t read, with who it came from and why, and never any text", async () => {
    render(ReviewPage);
    const list = await screen.findByRole("list", { name: "Add missing details" });
    expect(within(list).getByText("Mail from example-air.example on 2026-10-17")).toBeInTheDocument();
    expect(within(list).getByText("Sent 2026-10-17 · to ana@gmail.example")).toBeInTheDocument();
    expect(within(list).getByText(REASONS.no_markup)).toBeInTheDocument();
    expect(within(list).queryByRole("link")).toBeNull();
    expect(within(list).getByRole("button", { name: /View email .Mail from example-air.example on 2026-10-17./ })).toBeInTheDocument();
  });

  it("names an item by its message's subject, and says who it came from beside it", async () => {
    held = { matches: [], items: [item({ subject: "Your itinerary: EX 410" })], who: [], ai: false };
    render(ReviewPage);
    const list = await screen.findByRole("list", { name: "Add missing details" });
    expect(within(list).getByText("Your itinerary: EX 410")).toBeInTheDocument();
    expect(within(list).getByRole("button", { name: "Add “Your itinerary: EX 410” by hand" })).toBeInTheDocument();
    expect(within(list).getByText("Sent 2026-10-17 · to ana@gmail.example")).toBeInTheDocument();
  });

  it("says what it can when the sender or the day isn’t there", async () => {
    held = { matches: [], items: [item({ id: 1, reason: "broken", sender_domain: "", received: null }), item({ id: 2 })], who: [], ai: false };
    render(ReviewPage);
    expect(await screen.findByText("Mail from an unknown sender")).toBeInTheDocument();
    expect(screen.getByText("to ana@gmail.example")).toBeInTheDocument();
    expect(screen.getByText(REASONS.broken)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /ignore/i })).toHaveLength(1);
  });

  it("shows an item shared by another member with whose mailbox it is, and View email, Add by hand, Ask AI and Dismiss", async () => {
    held = { matches: [], items: [item({ id: 4, mine: false, owner: "Sam Doe", address: "sam@gmail.example" })], who: [], ai: true };
    render(ReviewPage);
    const row = await screen.findByTestId("review-item");
    expect(row).toHaveTextContent("in Sam Doe’s mailbox, shared with the household");
    expect(row).not.toHaveTextContent("sam@gmail.example");
    expect(within(row).getByRole("button", { name: /View email .Mail from example-air.example.* on 2026-10-17/ })).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: /Add .Mail from example-air.example.* by hand/ })).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: /Dismiss/ })).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: /Ask AI about/ })).toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: /ignore example-air.example/i })).toBeNull();
    expect(within(row).queryByRole("link")).toBeNull();
  });

  it("offers no Ask AI on a shared item while the AI is off", async () => {
    held = { matches: [], items: [item({ id: 4, mine: false, owner: "Sam Doe" })], who: [], ai: false };
    render(ReviewPage);
    const row = await screen.findByTestId("review-item");
    expect(within(row).queryByRole("button", { name: /Ask AI about/ })).toBeNull();
  });

  it("opens a shared item's message beside the form like any other, and dismisses it", async () => {
    held = { matches: [], items: [item({ id: 4, mine: false, owner: "Sam Doe" }), item({ id: 5, mine: true })], who: [], ai: false };
    render(ReviewPage);
    const row = (await screen.findAllByTestId("review-item"))[0];
    await userEvent.click(within(row).getByRole("button", { name: /by hand/ }));
    expect(await screen.findByLabelText(/Confirmation/)).toBeInTheDocument();
    expect(calls).toContainEqual(["/api/review/4/preview", undefined, undefined]);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await settled();
    await userEvent.click(within(row).getByRole("button", { name: /Dismiss/ }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(calls).toContainEqual(["/api/review/4", "DELETE", undefined]));
  });

  it("dismisses an item", async () => {
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Dismiss .Mail from example-air.example/ }));
    expect(calls.filter(([, method]) => method === "DELETE")).toEqual([]);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/deletes its stored copy of this email/)).toBeInTheDocument();
    expect(within(dialog).getByText(/can’t be undone/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(calls).toContainEqual(["/api/review/1", "DELETE", undefined]));
    expect(toast.success).toHaveBeenCalledWith("Dismissed");
    await waitFor(() => expect(screen.queryByTestId("review-item")).toBeNull());
  });

  it("shows items about one reservation as one row with a count, the newest first, and the others behind a disclosure", async () => {
    held = { ...held, who: [], items: [item({ subject: "Online check-in is open", count: 3, others: [
      { id: 2, subject: "Your payment receipt", has_email: true, received: "2026-10-12" },
      { id: 3, subject: null, has_email: false, received: "2026-10-10" }] })] };
    render(ReviewPage);
    const rows = await screen.findAllByTestId("review-item");
    expect(rows).toHaveLength(1);
    expect(within(rows[0]!).getByText("Online check-in is open")).toBeInTheDocument();
    const disclosure = within(rows[0]!).getByTestId("same-reservation");
    expect(within(disclosure).getByText("3 emails about the same reservation")).toBeInTheDocument();
    expect(disclosure).not.toHaveAttribute("open");
    await userEvent.click(within(disclosure).getByText("3 emails about the same reservation"));
    expect(disclosure).toHaveAttribute("open");
    const others = within(disclosure).getByRole("list", { name: "The other emails about it" });
    expect(within(others).getByText("Your payment receipt · 2026-10-12")).toBeInTheDocument();
    expect(within(others).getByText("Mail from example-air.example on 2026-10-10")).toBeInTheDocument();
  });

  it("shows no disclosure for a single email", async () => {
    render(ReviewPage);
    await screen.findByTestId("review-item");
    expect(screen.queryByTestId("same-reservation")).toBeNull();
  });

  it("dismisses the whole group from its row and says how many went", async () => {
    held = { ...held, who: [], items: [item({ subject: "Online check-in is open", count: 3, others: [
      { id: 2, subject: "Your payment receipt", has_email: true, received: "2026-10-12" },
      { id: 3, subject: "Your reminder", has_email: true, received: "2026-10-10" }] })] };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: "Dismiss all 3 emails about “Online check-in is open”" }));
    expect(within(await screen.findByRole("dialog")).getByText(/all 3 emails about this reservation/)).toBeInTheDocument();
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Dismiss all" }));
    await waitFor(() => expect(calls).toContainEqual(["/api/review/1", "DELETE", undefined]));
    expect(toast.success).toHaveBeenCalledWith("Dismissed 3 emails");
    await waitFor(() => expect(screen.queryByTestId("review-item")).toBeNull());
  });

  it("adds a generic suggestion once by default, and trusts the sender only when asked", async () => {
    const read = { kind: "hotel" as const, provider: "Seaside Inn", confirmation: "SS48213", origin: "Seaside Inn", start_local: "2026-11-21T15:00", end_local: "2026-11-25T11:00", start_zone: "Europe/London", sources: {} };
    held = { matches: [], items: [item({ reason: "generic", sender_domain: "seaside-stays.example", suggestions: [read] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check what Waypoint read/ }));
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(calls).toContainEqual(["/api/review/1?segment=42", "DELETE", undefined]));
  });

  it("sends trust only when its box is ticked", async () => {
    const read = { kind: "hotel" as const, provider: "Seaside Inn", confirmation: "SS48213", origin: "Seaside Inn", start_local: "2026-11-21T15:00", end_local: "2026-11-25T11:00", start_zone: "Europe/London", sources: {} };
    held = { matches: [], items: [item({ reason: "generic", sender_domain: "seaside-stays.example", suggestions: [read] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check what Waypoint read/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /Also trust seaside-stays.example/ }));
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(calls).toContainEqual(["/api/review/1?segment=42&trust=1", "DELETE", undefined]));
  });

  it("adds a booking from a grouped row through the newest item alone", async () => {
    held = { ...held, who: [], items: [item({ subject: "Online check-in is open", count: 2, others: [{ id: 2, subject: "Your payment receipt", has_email: true, received: "2026-10-12" }] })] };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: "Add “Online check-in is open” by hand" }));
    await userEvent.type(screen.getByLabelText("From (airport code)"), "BOS");
    await userEvent.type(screen.getByLabelText("To (airport code)"), "DEN");
    await userEvent.type(screen.getByLabelText("Departs"), "2027-01-02T07:15");
    await userEvent.type(screen.getByLabelText("Arrives"), "2027-01-02T09:40");
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(calls).toContainEqual(["/api/review/1?segment=42", "DELETE", undefined]));
    expect(calls.filter(([path]) => path.startsWith("/api/review/2"))).toEqual([]);
  });

  it("counts every email of a group in the ignore question", async () => {
    held = { ...held, who: [], items: [item({ count: 3, others: [
      { id: 2, subject: null, has_email: true, received: null }, { id: 3, subject: null, has_email: true, received: null }] }), item({ id: 4 })] };
    render(ReviewPage);
    await userEvent.click((await screen.findAllByRole("button", { name: "Not travel: ignore example-air.example" }))[0]!);
    expect(await screen.findByText(/4 items from them \(this one included\) leave this list/)).toBeInTheDocument();
  });

  it("ignores a sender only after asking", async () => {
    held = { ...held, items: [item(), item({ id: 2 }), item({ id: 3, sender_domain: "other-air.example" }), item({ id: 4, address: "bo@gmail.example" })] };
    render(ReviewPage);
    await userEvent.click((await screen.findAllByRole("button", { name: "Not travel: ignore example-air.example" }))[0]!);
    expect(await screen.findByText("Ignore example-air.example?")).toBeInTheDocument();
    expect(await screen.findByText(/2 items from them \(this one included\) leave this list/)).toBeInTheDocument();
    expect(calls.some(([p]) => p.endsWith("/ignore"))).toBe(false);
    await userEvent.click((await screen.findByRole("dialog")).querySelector("button[type=submit]")!);
    await waitFor(() => expect(calls).toContainEqual(["/api/review/1/ignore", "POST", undefined]));
    expect(toast.success).toHaveBeenCalledWith("Ignoring example-air.example", expect.objectContaining({ description: "You can undo this in Settings → Mail & review → Gmail", action: expect.objectContaining({ label: "Undo" }) }));
  });

  it("offers Undo on the toast, and Undo stops ignoring that sender and says the mail is read again", async () => {
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: "Not travel: ignore example-air.example" }));
    await userEvent.click((await screen.findByRole("dialog")).querySelector("button[type=submit]")!);
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Ignoring example-air.example", expect.anything()));
    const options = vi.mocked(toast.success).mock.calls.find(([text]) => text === "Ignoring example-air.example")![1] as unknown as { action: { onClick: () => void } };
    options.action.onClick();
    await waitFor(() => expect(calls).toContainEqual(["/api/mailboxes/5/unignore", "POST", { domain: "example-air.example" }]));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Reading again what was skipped from example-air.example"));
  });

  it("shows only the mail from the sender in the link from Settings, in that mailbox, and everything again on request", async () => {
    held = { ...held, items: [item({ id: 1, sender_domain: "example-air.example" }), item({ id: 2, sender_domain: "seaside-stays.example" }),
      item({ id: 3, sender_domain: "seaside-stays.example", address: "ben@gmail.example", mine: false })] };
    setQuery("sender=seaside-stays.example&mailbox=ana%40gmail.example");
    render(ReviewPage);
    expect(await screen.findAllByTestId("review-item")).toHaveLength(1);
    expect(screen.getByTestId("review-filter")).toHaveTextContent("Showing only mail from seaside-stays.example in ana@gmail.example.");
    await userEvent.click(screen.getByRole("button", { name: "Show everything" }));
    expect(await screen.findAllByTestId("review-item")).toHaveLength(3);
    expect(screen.queryByTestId("review-filter")).toBeNull();
  });

  it("filters by sender alone when no mailbox is named, and says when none is waiting", async () => {
    held = { ...held, items: [item({ id: 1, sender_domain: "example-air.example" }), item({ id: 2, sender_domain: "seaside-stays.example" })] };
    setQuery("sender=seaside-stays.example");
    render(ReviewPage);
    expect(await screen.findAllByTestId("review-item")).toHaveLength(1);
    expect(screen.getByTestId("review-filter")).toHaveTextContent("Showing only mail from seaside-stays.example. Show everything");
    setQuery("sender=gone.example");
    await waitFor(() => expect(screen.queryAllByTestId("review-item")).toHaveLength(0));
    expect(screen.getByTestId("review-filter")).toHaveTextContent("Showing only mail from gone.example, and none is waiting.");
  });

  it("says in the ignore dialog where to undo it", async () => {
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: "Not travel: ignore example-air.example" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("You can undo this in Settings → Mail & review → Gmail.")).toBeInTheDocument();
    expect(within(dialog).queryByTestId("known-sender-warning")).toBeNull();
  });

  it("warns in the ignore dialog when the sender is a travel company Waypoint knows, and still allows it", async () => {
    held = { ...held, items: [item({ sender_domain: "delta.example", known_sender: true })] };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: "Not travel: ignore delta.example" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByTestId("known-sender-warning")).toHaveTextContent("This sender is a travel company Waypoint knows. Ignoring it means its bookings won’t be added.");
    await userEvent.click(dialog.querySelector("button[type=submit]")!);
    await waitFor(() => expect(calls).toContainEqual(["/api/review/1/ignore", "POST", undefined]));
  });

  it("does not count items that hold bookings to settle, since they stay", async () => {
    held = { ...held, items: [item(), item({ id: 2 }), item({ id: 3, holds_bookings: true })] };
    render(ReviewPage);
    await userEvent.click((await screen.findAllByRole("button", { name: "Not travel: ignore example-air.example" }))[0]!);
    expect(await screen.findByText(/2 items from them \(this one included\) leave this list/)).toBeInTheDocument();
  });

  it("says one item when it is the only one from that sender", async () => {
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: "Not travel: ignore example-air.example" }));
    expect(await screen.findByText(/and this item leaves this list/)).toBeInTheDocument();
  });

  it("does nothing when the question is cancelled", async () => {
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: "Not travel: ignore example-air.example" }));
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls.some(([p]) => p.endsWith("/ignore"))).toBe(false);
    expect(screen.getByTestId("review-item")).toBeInTheDocument();
  });

  it("adds a booking by hand with the provider filled in, then takes the item off the list", async () => {
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Add .Mail from example-air.example on 2026-10-17. by hand/ }));
    expect(screen.getByLabelText("Provider")).toHaveValue("Example Air");
    await userEvent.type(screen.getByLabelText("Confirmation code"), "ZZ9Y8X");
    await userEvent.type(screen.getByLabelText("From (airport code)"), "BOS");
    await userEvent.type(screen.getByLabelText("To (airport code)"), "DEN");
    await userEvent.type(screen.getByLabelText("Departs"), "2027-01-02T07:15");
    await userEvent.type(screen.getByLabelText("Arrives"), "2027-01-02T09:40");
    expect(screen.queryByText(/time zones come from its airports/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(calls).toContainEqual(["/api/segments", "POST", {
      kind: "flight", start_local: "2027-01-02T07:15", end_local: "2027-01-02T09:40", provider: "Example Air", confirmation: "ZZ9Y8X",
      origin: "BOS", destination: "DEN" }]));
    await waitFor(() => expect(calls).toContainEqual(["/api/review/1?segment=42", "DELETE", undefined]));
    expect(toast.success).toHaveBeenCalledWith("Added to your trips");
    expect(screen.queryByRole("form")).toBeNull();
  });

  it("asks for a stay’s one time zone, which an airport can’t give", async () => {
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Add .Mail from example-air.example on 2026-10-17. by hand/ }));
    await userEvent.selectOptions(screen.getByLabelText("What is it?"), "hotel");
    expect(screen.getByLabelText("Hotel")).toBeInTheDocument();
    expect(screen.queryByLabelText("To (airport code)")).toBeNull();
    await userEvent.type(screen.getByLabelText("Hotel"), "Harbour Hotel");
    await userEvent.type(screen.getByLabelText("Check-in"), "2026-11-21T15:00");
    await userEvent.type(screen.getByLabelText("Check-out"), "2026-11-27T10:00");
    expect(screen.queryByLabelText("Time zone where it starts")).toBeNull();
    expect(screen.queryByLabelText("Time zone where it ends")).toBeNull();
    await chooseZone(screen.getByLabelText(/^Time zone/), "Europe/London");
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(calls).toContainEqual(["/api/segments", "POST", expect.objectContaining({
      kind: "hotel", origin: "Harbour Hotel", start_zone: "Europe/London" })]));
    expect(calls.find(([p]) => p === "/api/segments")?.[2]).not.toHaveProperty("end_zone");
  });

  it("offers Cruise by hand, shows its port and ship fields and adds it", async () => {
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Add .Mail from example-air.example on 2026-10-17. by hand/ }));
    const kinds = within(screen.getByLabelText("What is it?")).getAllByRole("option").map((o) => o.textContent);
    expect(kinds).toEqual(["Flight", "Hotel stay", "Car rental", "Train", "Cruise", "Parking"]);
    await userEvent.selectOptions(screen.getByLabelText("What is it?"), "cruise");
    await userEvent.type(screen.getByLabelText("Embarkation port"), "Miami");
    await userEvent.type(screen.getByLabelText("Disembarkation port"), "Nassau");
    await userEvent.type(screen.getByLabelText("Departs"), "2026-12-02T16:00");
    await userEvent.type(screen.getByLabelText("Arrives"), "2026-12-09T07:00");
    await userEvent.type(screen.getByLabelText(/^Ship/), "Example Voyager");
    expect(screen.getByLabelText(/^Cabin/)).toBeInTheDocument();
    await chooseZone(screen.getByLabelText("Time zone where it starts"), "America/New_York");
    expect(screen.queryAllByRole("listbox", { hidden: true })).toHaveLength(0);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(calls).toContainEqual(["/api/segments", "POST", expect.objectContaining({
      kind: "cruise", origin: "Miami", destination: "Nassau", start_zone: "America/New_York", end_zone: "America/New_York", details: { ship: "Example Voyager" } })]));
    await waitFor(() => expect(calls).toContainEqual(["/api/review/1?segment=42", "DELETE", undefined]));
  });

  it("preselects Cruise for a cruise suggestion", async () => {
    const cruise = { kind: "cruise" as const, origin: "Miami", destination: "Nassau", start_local: "2026-12-02T16:00", end_local: "2026-12-09T07:00",
      start_zone: "America/New_York", end_zone: "America/Nassau" };
    held = { matches: [], items: [item({ suggestions: [cruise] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    expect(screen.getByLabelText("What is it?")).toHaveValue("cruise");
    expect(screen.getByRole("option", { name: "Cruise" })).toBeInTheDocument();
  });

  it("sends a stay’s address, and no zone, for the server to work the zone out from", async () => {
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Add .Mail from example-air.example on 2026-10-17. by hand/ }));
    await userEvent.selectOptions(screen.getByLabelText("What is it?"), "hotel");
    await userEvent.type(screen.getByLabelText("Hotel"), "Harbour Hotel");
    await userEvent.type(screen.getByLabelText(/^Address/), "1 Quay Road, Bristol BS1 4AA, UK");
    await userEvent.type(screen.getByLabelText("Check-in"), "2026-11-21T15:00");
    await userEvent.type(screen.getByLabelText("Check-out"), "2026-11-27T10:00");
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(calls).toContainEqual(["/api/segments", "POST", expect.objectContaining({
      kind: "hotel", start_zone: null, details: { address: "1 Quay Road, Bristol BS1 4AA, UK" } })]));
  });

  it("asks for a zone or an address for a stay, and sends nothing without either", async () => {
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Add .Mail from example-air.example on 2026-10-17. by hand/ }));
    await userEvent.selectOptions(screen.getByLabelText("What is it?"), "hotel");
    await userEvent.type(screen.getByLabelText("Hotel"), "Harbour Hotel");
    await userEvent.type(screen.getByLabelText("Check-in"), "2026-11-21T15:00");
    await userEvent.type(screen.getByLabelText("Check-out"), "2026-11-27T10:00");
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("time zone");
    expect(calls.some(([p]) => p === "/api/segments")).toBe(false);
  });

  it("adds a parking booking by hand with its lot, entry and exit, and the address to work the zone out from", async () => {
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Add .Mail from example-air.example on 2026-10-17. by hand/ }));
    await userEvent.selectOptions(screen.getByLabelText("What is it?"), "parking");
    expect(screen.queryByLabelText("To (airport code)")).toBeNull();
    await userEvent.type(screen.getByLabelText("Lot"), "Example Long-Term Lot");
    await userEvent.type(screen.getByLabelText(/^Address/), "1 Terminal Road, Jamaica, NY");
    await userEvent.type(screen.getByLabelText("Entry"), "2026-11-21T08:00");
    await userEvent.type(screen.getByLabelText("Exit"), "2026-11-27T21:00");
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(calls).toContainEqual(["/api/segments", "POST", expect.objectContaining({
      kind: "parking", origin: "Example Long-Term Lot", start_zone: null, details: { address: "1 Terminal Road, Jamaica, NY" } })]));
    expect(calls.find(([p]) => p === "/api/segments")?.[2]).not.toHaveProperty("end_zone");
  });

  it("opens a parking suggestion with its lot name and dates and asks for a zone or an address without either", async () => {
    const lot = { kind: "parking" as const, provider: "Example Parking", confirmation: "PK1234", origin: "Example Long-Term Lot",
      start_local: "2026-12-02T08:00", end_local: "2026-12-09T21:00" };
    held = { matches: [], items: [item({ suggestions: [lot] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    expect(screen.getByLabelText("Lot")).toHaveValue("Example Long-Term Lot");
    expect(screen.getByLabelText("Entry")).toHaveValue("2026-12-02T08:00");
    expect(screen.getByLabelText("Exit")).toHaveValue("2026-12-09T21:00");
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("lot’s time zone");
    expect(calls.some(([p]) => p === "/api/segments")).toBe(false);
  });

  it("shows why a booking wasn’t added, and keeps what was typed", async () => {
    serve("/api/segments");
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Add .Mail from example-air.example on 2026-10-17. by hand/ }));
    await userEvent.type(screen.getByLabelText("From (airport code)"), "BOS");
    await userEvent.type(screen.getByLabelText("To (airport code)"), "DEN");
    await userEvent.type(screen.getByLabelText("Departs"), "2027-01-02T07:15");
    await userEvent.type(screen.getByLabelText("Arrives"), "2027-01-02T09:40");
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Refused.");
    expect(screen.getByLabelText("From (airport code)")).toHaveValue("BOS");
    expect(calls.some(([p, m]) => p.startsWith("/api/review/") && m === "DELETE")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.click(await screen.findByRole("button", { name: "Discard changes" }));
    await waitFor(() => expect(screen.queryByRole("form")).toBeNull());
  });

  it("says when a booking was added but its item couldn’t be taken off the list", async () => {
    serve("/api/review/1?");
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Add .Mail from example-air.example on 2026-10-17. by hand/ }));
    await userEvent.type(screen.getByLabelText("From (airport code)"), "BOS");
    await userEvent.type(screen.getByLabelText("To (airport code)"), "DEN");
    await userEvent.type(screen.getByLabelText("Departs"), "2027-01-02T07:15");
    await userEvent.type(screen.getByLabelText("Arrives"), "2027-01-02T09:40");
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(calls.some(([p]) => p === "/api/segments")).toBe(true));
    await waitFor(() => expect(calls.filter(([p]) => p === "/api/review").length).toBeGreaterThan(1));
  });

  it("lists names to match, with the booking each is on, and matches one to a person", async () => {
    render(ReviewPage);
    const list = await screen.findByRole("list", { name: "Match people" });
    expect(within(list).getByText("DOE/MIA MISS")).toBeInTheDocument();
    expect(within(list).getByText("Flight JFK → SFO on 2026-12-08 (Example Air)")).toBeInTheDocument();
    const button = within(list).getByRole("button", { name: "Match DOE/MIA MISS" });
    expect(button).toBeDisabled();
    await userEvent.selectOptions(within(list).getByLabelText("Who is DOE/MIA MISS?"), "Mia Doe");
    await userEvent.click(button);
    await waitFor(() => expect(calls).toContainEqual(["/api/review/who/7", "POST", { person_id: 2 }]));
    expect(toast.success).toHaveBeenCalledWith("Matched on 2 bookings");
    await waitFor(() => expect(screen.queryByRole("list", { name: "Match people" })).toBeNull());
  });

  it("adds a guest for a name nobody is", async () => {
    render(ReviewPage);
    const list = await screen.findByRole("list", { name: "Match people" });
    await userEvent.selectOptions(within(list).getByLabelText("Who is DOE/MIA MISS?"), "A new guest…");
    const button = within(list).getByRole("button", { name: "Match DOE/MIA MISS" });
    expect(button).toBeDisabled();
    await userEvent.type(within(list).getByLabelText("Name for DOE/MIA MISS"), "Mia Rose Doe");
    await userEvent.click(button);
    await waitFor(() => expect(calls).toContainEqual(["/api/review/who/7", "POST", { new_guest: "Mia Rose Doe" }]));
  });

  it("describes each kind of booking a name is on", async () => {
    held = { matches: [], items: [], who: [who({ id: 1, kind: "hotel", origin: "Harbour Hotel", destination: null, provider: null }), who({ id: 2, kind: "car", origin: "SFO", destination: "SFO" }),
      who({ id: 3, kind: "train", origin: null, destination: null })], ai: false };
    render(ReviewPage);
    expect(await screen.findByText("Stay Harbour Hotel on 2026-12-08")).toBeInTheDocument();
    expect(screen.getByText("Rental SFO → SFO on 2026-12-08 (Example Air)")).toBeInTheDocument();
    expect(screen.getByText("Train on 2026-12-08 (Example Air)")).toBeInTheDocument();
  });

  it("lists a booking email that could be more than one of yours, with each candidate and its trip", async () => {
    held = { matches: [held_match()], items: [], who: [], ai: false };
    render(ReviewPage);
    const list = await screen.findByRole("list", { name: "Match bookings" });
    expect(within(list).getByText("Stay Harbour Hotel on 2026-11-21 (Example Hotels) · H88231")).toBeInTheDocument();
    const options = within(within(list).getByRole("list", { name: "It could be" })).getAllByRole("listitem");
    expect(options).toHaveLength(2);
    expect(within(options[0]).getByText("Trip to London")).toBeInTheDocument();
    expect(within(options[1]).getByText("Second trip")).toBeInTheDocument();
    expect(screen.queryByText(/Nothing to review/)).toBeNull();
  });

  it("fills in the one chosen, and the item goes", async () => {
    held = { matches: [held_match()], items: [], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click((await screen.findAllByRole("button", { name: /^It’s Stay Harbour Hotel/ }))[1]);
    await waitFor(() => expect(calls).toContainEqual(["/api/review/9/match", "POST", { entry: 1, segment_id: 12 }]));
    expect(toast.success).toHaveBeenCalledWith("Filled in");
    expect(await screen.findByText(/Nothing to review/)).toBeInTheDocument();
  });

  it("adds it as a booking of its own, or dismisses it", async () => {
    held = { matches: [held_match(), held_match({ item_id: 10, entry: 1 })], items: [], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click((await screen.findAllByRole("button", { name: "It’s a new booking" }))[0]);
    await waitFor(() => expect(calls).toContainEqual(["/api/review/9/match", "POST", { entry: 1, segment_id: null }]));
    expect(toast.success).toHaveBeenCalledWith("Added to your trips");
    await userEvent.click(await screen.findByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(calls).toContainEqual(["/api/review/10?entry=1", "DELETE", undefined]));
  });

  it("says so, and still lets it be added, when none of the candidates are the viewer’s to see", async () => {
    held = { matches: [held_match({ candidates: [], mine: false })], items: [], who: [], ai: false };
    render(ReviewPage);
    expect(await screen.findByText("The bookings it could be aren’t yours to see.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^It’s Stay/ })).toBeNull();
    expect(screen.getByRole("button", { name: "It’s a new booking" })).toBeInTheDocument();
  });

  it("says when nothing is waiting", async () => {
    held = { matches: [], items: [], who: [], ai: false };
    render(ReviewPage);
    expect(await screen.findByText(/Nothing to review/)).toBeInTheDocument();
  });

  it("says when it can’t load, draws nothing that could pass for current, and tries again", async () => {
    let up = false;
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (!up) throw new Error("Waypoint is restarting or unreachable.");
      return (path === "/api/people" ? { people: [jane] } : held) as never;
    });
    render(ReviewPage);
    expect(await screen.findByText("Waypoint is restarting or unreachable.")).toBeInTheDocument();
    expect(screen.queryByRole("list")).toBeNull();
    up = true;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("list", { name: "Add missing details" })).toBeInTheDocument();
  });
});

describe("providerFrom", () => {
  it("makes a provider’s name from the sender’s domain", () => {
    expect(providerFrom("example-air.example")).toBe("Example Air");
    expect(providerFrom("mail.delta.com")).toBe("Delta");
    expect(providerFrom("ana.co.jp")).toBe("Ana");
    expect(providerFrom("localhost")).toBe("Localhost");
    expect(providerFrom("")).toBe("");
  });
});

describe("Review: the AI’s suggestion", () => {
  const suggestion = { kind: "flight" as const, provider: "Example Air", confirmation: "QW4R7T", origin: "BOS", destination: "DEN",
    start_local: "2026-12-02T07:15", end_local: "2026-12-02T10:05" };

  it("offers nothing extra when there is no suggestion", async () => {
    render(ReviewPage);
    await screen.findByTestId("review-item");
    expect(screen.queryByRole("button", { name: /suggestion/ })).toBeNull();
  });

  it("starts the form filled in with it, to confirm or edit, and saves only when added", async () => {
    held = { matches: [], items: [item({ suggestions: [suggestion] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    expect(screen.getByRole("heading", { name: "Check this suggestion" })).toBeInTheDocument();
    expect(screen.getByLabelText("Confirmation code")).toHaveValue("QW4R7T");
    expect(screen.getByLabelText("From (airport code)")).toHaveValue("BOS");
    expect(screen.getByLabelText("Departs")).toHaveValue("2026-12-02T07:15");
    expect(calls.some(([p]) => p === "/api/segments")).toBe(false);
    await userEvent.clear(screen.getByLabelText("Confirmation code"));
    await userEvent.type(screen.getByLabelText("Confirmation code"), "QW4R7U");
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added to your trips"));
    const [, , body] = calls.find(([p]) => p === "/api/segments")!;
    expect(body).toMatchObject({ kind: "flight", confirmation: "QW4R7U", origin: "BOS", destination: "DEN", start_local: "2026-12-02T07:15" });
  });

  it("shows each traveller’s seat outlined, matches a known person, and sends the seats when added", async () => {
    const seated = { ...suggestion, travelers: [{ name: "Doe/Jane", seat: "23A" }, { name: "Sam Printed", seat: "23B" }] };
    held = { matches: [], items: [item({ suggestions: [seated as never] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    expect(screen.getByLabelText("Seat for Doe/Jane")).toHaveValue("23A");
    expect(screen.getByLabelText("Seat for Sam Printed")).toHaveClass("ring-primary");
    await userEvent.clear(screen.getByLabelText("Seat for Sam Printed"));
    await userEvent.type(screen.getByLabelText("Seat for Sam Printed"), "24C");
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added to your trips"));
    const [, , body] = calls.find(([p]) => p === "/api/segments")!;
    expect((body as { travelers: unknown }).travelers).toEqual([{ person_id: 1, seat: "23A" }, { person_id: null, name: "Sam Printed", seat: "24C" }]);
  });

  it("sends no travellers for a suggestion that read no seats", async () => {
    held = { matches: [], items: [item({ suggestions: [suggestion] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    expect(screen.queryByRole("group", { name: "Seats" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added to your trips"));
    expect(calls.find(([p]) => p === "/api/segments")![2]).not.toHaveProperty("travelers");
  });

  it("shows the AI’s address and phone outlined, and sends them when added", async () => {
    const stay = { kind: "hotel" as const, provider: "Example Stays", confirmation: "QW4R7T", origin: "Harbour Hotel", start_local: "2026-12-02T15:00",
      end_local: "2026-12-05T11:00", start_zone: "Europe/London", address: "1 Quay Road, Bristol BS1 4AA, UK", phone: "+44 117 555 0100" };
    held = { matches: [], items: [item({ suggestions: [stay] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    expect(screen.queryByText(/An AI read the email and suggested this/)).toBeNull();
    expect(screen.getByLabelText(/^Address/)).toHaveValue("1 Quay Road, Bristol BS1 4AA, UK");
    expect(screen.getByLabelText(/^Address/)).toHaveClass("ring-2");
    expect(screen.getByLabelText(/^Phone/)).toHaveValue("+44 117 555 0100");
    expect(screen.getByLabelText(/^Phone/)).toHaveClass("ring-2");
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added to your trips"));
    const [, , body] = calls.find(([p]) => p === "/api/segments")!;
    expect(body).toMatchObject({ kind: "hotel", details: { address: "1 Quay Road, Bristol BS1 4AA, UK", phone: "+44 117 555 0100" } });
  });

  it("shows the total the AI read as a cost to check, and sends it in the smallest unit when added", async () => {
    held = { matches: [], items: [item({ suggestions: [{ ...suggestion, price_minor: 124000, price_currency: "USD" }] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    expect(screen.getByLabelText("Cost amount")).toHaveValue("1240.00");
    expect(screen.getByLabelText("Cost amount")).toHaveClass("ring-2");
    expect(screen.getByLabelText("Cost currency")).toHaveValue("USD");
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added to your trips"));
    const [, , body] = calls.find(([p]) => p === "/api/segments")!;
    expect(body).toMatchObject({ price: { amount_minor: 124000, currency: "USD" } });
  });

  it("refuses a cost it can't read and posts nothing", async () => {
    held = { matches: [], items: [item({ suggestions: [suggestion] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    await userEvent.type(screen.getByLabelText("Cost amount"), "abc");
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    expect(await screen.findByText("Enter the cost as an amount like 1240.00 and a three-letter currency code like USD")).toBeInTheDocument();
    expect(calls.some(([p]) => p === "/api/segments" || p.endsWith("/same"))).toBe(false);
  });

  it("sends no cost when the suggestion has none and none is typed", async () => {
    held = { matches: [], items: [item({ suggestions: [suggestion] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    expect(screen.getByLabelText("Cost amount")).toHaveValue("");
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added to your trips"));
    const [, , body] = calls.find(([p]) => p === "/api/segments")!;
    expect(body).not.toHaveProperty("price");
  });

  it("leaves the address empty and unoutlined when the AI found none", async () => {
    const stay = { kind: "hotel" as const, origin: "Harbour Hotel", start_local: "2026-12-02T15:00", end_local: "2026-12-05T11:00", start_zone: "Europe/London" };
    held = { matches: [], items: [item({ suggestions: [stay] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    expect(screen.getByLabelText(/^Address/)).toHaveValue("");
    expect(screen.getByLabelText(/^Address/)).not.toHaveClass("ring-2");
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added to your trips"));
    expect(calls.find(([p]) => p === "/api/segments")?.[2]).not.toHaveProperty("details");
  });

  it("asks a rental for one pick-up place, keeps a different address and saves an empty drop-off as the pick-up", async () => {
    const car = { kind: "car" as const, origin: "Bristol Airport", start_local: "2026-12-02T10:00", end_local: "2026-12-05T10:00", address: "4 Runway Drive, Bristol BS48 3DY" };
    held = { matches: [], items: [item({ suggestions: [car] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    expect(screen.getByLabelText(/^Pick-up address/)).toHaveValue("4 Runway Drive, Bristol BS48 3DY");
    expect(screen.getByPlaceholderText("Same as pick-up")).toHaveValue("");
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added to your trips"));
    expect(calls.find(([p]) => p === "/api/segments")?.[2]).toMatchObject({ destination: "Bristol Airport", details: { address: "4 Runway Drive, Bristol BS48 3DY" } });
  });

  it("lets a kept rental address be cleared, and then the address is the pick-up", async () => {
    const car = { kind: "car" as const, origin: "Bristol Airport", start_local: "2026-12-02T10:00", end_local: "2026-12-05T10:00", address: "4 Runway Drive, Bristol BS48 3DY" };
    held = { matches: [], items: [item({ suggestions: [car] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    await userEvent.clear(screen.getByLabelText(/^Pick-up address/));
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added to your trips"));
    expect(calls.find(([p]) => p === "/api/segments")?.[2]).toMatchObject({ details: { address: "Bristol Airport" } });
  });

  it("shows no address field for a rental whose address is its pick-up, or one without an address", async () => {
    const car = { kind: "car" as const, origin: "Bristol Airport", start_local: "2026-12-02T10:00", end_local: "2026-12-05T10:00" };
    held = { matches: [], items: [item({ suggestions: [{ ...car, address: "Bristol Airport" }] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    expect(screen.queryByLabelText(/address/i)).toBeNull();
  });

  it("sets a rental’s address from the pick-up when the email gave the same text, and keeps a stated drop-off", async () => {
    const car = { kind: "car" as const, origin: "Bristol Airport", destination: "Cardiff Station", start_local: "2026-12-02T10:00", end_local: "2026-12-05T10:00", address: "Bristol Airport" };
    held = { matches: [], items: [item({ suggestions: [car] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added to your trips"));
    expect(calls.find(([p]) => p === "/api/segments")?.[2]).toMatchObject({ destination: "Cardiff Station", details: { address: "Bristol Airport" } });
  });

  it("takes a rental’s pick-up address and a cruise’s terminal, cabin, ship and deck", async () => {
    const car = { kind: "car" as const, origin: "Bristol Airport", destination: "Bristol Airport", start_local: "2026-12-02T10:00", end_local: "2026-12-05T10:00",
      address: "4 Runway Drive, Bristol BS48 3DY" };
    held = { matches: [], items: [item({ suggestions: [car] })], who: [], ai: false };
    const first = render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    expect(screen.getByLabelText(/^Pick-up address/)).toHaveValue("4 Runway Drive, Bristol BS48 3DY");
    expect(screen.getByLabelText(/^Pick-up(?! time| address)/)).toHaveValue("Bristol Airport");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    first.unmount();
    await waitFor(() => expect(document.body.style.pointerEvents).not.toBe("none"));
    const cruise = { kind: "cruise" as const, origin: "Miami", destination: "Nassau", start_local: "2026-12-02T16:00", end_local: "2026-12-09T07:00",
      start_zone: "America/New_York", end_zone: "America/Nassau", address: "1015 North America Way, Miami FL 33132", room: "8123", ship: "Example Voyager", deck: "8" };
    held = { matches: [], items: [item({ suggestions: [cruise] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    expect(screen.getByLabelText(/^Terminal address/)).toHaveValue("1015 North America Way, Miami FL 33132");
    expect(screen.getByLabelText(/^Cabin/)).toHaveValue("8123");
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added to your trips"));
    const [, , body] = calls.find(([p]) => p === "/api/segments")!;
    expect(body).toMatchObject({ kind: "cruise", details: { address: "1015 North America Way, Miami FL 33132", room: "8123", ship: "Example Voyager", deck: "8" } });
  });

  it("opens a cruise suggestion with its port labels and saves its ports and zones", async () => {
    const cruise = { kind: "cruise" as const, provider: "Example Cruise Line", confirmation: "QW4R7T", origin: "Miami", destination: "Nassau",
      start_local: "2026-12-02T16:00", end_local: "2026-12-09T07:00", start_zone: "America/New_York", end_zone: "America/Nassau" };
    held = { matches: [], items: [item({ suggestions: [cruise] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    expect(screen.getByLabelText("Embarkation port")).toHaveValue("Miami");
    expect(screen.getByLabelText("Disembarkation port")).toHaveValue("Nassau");
    expect(screen.getByLabelText("Time zone where it ends")).toHaveValue("America/Nassau");
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added to your trips"));
    const [, , body] = calls.find(([p]) => p === "/api/segments")!;
    expect(body).toMatchObject({ kind: "cruise", origin: "Miami", destination: "Nassau", start_zone: "America/New_York", end_zone: "America/Nassau" });
  });

  it("says why there’s none, and still offers adding by hand", async () => {
    held = { matches: [], items: [item({ suggestion_error: "The AI didn’t find a booking in this message." })], who: [], ai: false };
    render(ReviewPage);
    expect(await screen.findByText("The AI didn’t find a booking in this message.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Check the AI’s suggestion/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /by hand/ }));
    expect(screen.getByRole("heading", { name: "Add this booking by hand" })).toBeInTheDocument();
  });
});

describe("Review: the message beside the form", () => {
  it("shows the message's subject above its text beside the form", async () => {
    vi.mocked(api).mockImplementation(async (path: string) => (path.endsWith("/preview") ? { subject: "Your itinerary", text: "Gate B12", html: null, truncated: false }
      : path === "/api/people" ? { people: [] } : held) as never);
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /by hand/ }));
    expect(await screen.findByTestId("message-subject")).toHaveTextContent("Your itinerary");
  });

  it("shows the message as plain text beside the form, and has no separate Preview button", async () => {
    render(ReviewPage);
    await screen.findByTestId("review-item");
    expect(screen.queryByRole("button", { name: /Preview/ })).toBeNull();
    await userEvent.click(await screen.findByRole("button", { name: /by hand/ }));
    const region = await screen.findByTestId("preview");
    expect(region).toHaveTextContent("Your flight EX 410 leaves Boston at 7:15 am on 2 January.");
    expect(calls).toContainEqual(["/api/review/1/preview", undefined, undefined]);
  });

  it("shows the message as text, never as markup", async () => {
    const hostile = "<img src=x onerror=alert(1)><script>alert(2)</script> Hello";
    vi.mocked(api).mockImplementation(async (path: string) => (path.endsWith("/preview") ? { text: hostile, truncated: false } : path === "/api/people" ? { people: [] } : held) as never);
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /by hand/ }));
    const region = await screen.findByTestId("preview");
    expect(region).toHaveTextContent(hostile);
    expect(region.querySelector("img, script")).toBeNull();
  });

  it("shows a message's HTML as formatted text, with no switch to plain text", async () => {
    vi.mocked(api).mockImplementation(async (path: string) => (path.endsWith("/preview")
      ? { text: "Gate B12", html: "<p>Gate <b>B12</b></p><table><tr><td>Seat</td><td>12A</td></tr></table>", truncated: false }
      : path === "/api/people" ? { people: [] } : held) as never);
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /by hand/ }));
    const formatted = await screen.findByTestId("preview-html");
    expect(formatted.shadowRoot?.innerHTML).toContain("<b>B12</b>");
    expect(formatted.shadowRoot?.innerHTML).toContain("<td>Seat</td>");
    expect(screen.queryByRole("button", { name: /Show as/ })).toBeNull();
  });

  it("offers no switch for a message with no HTML part", async () => {
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /by hand/ }));
    await screen.findByTestId("preview");
    expect(screen.queryByRole("button", { name: /Show as/ })).toBeNull();
    expect(screen.queryByTestId("preview-html")).toBeNull();
  });

  it("says when it was cut short, and when the message has no text", async () => {
    truncated = true;
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /by hand/ }));
    expect(await screen.findByText(/cut short/)).toBeInTheDocument();
  });

  it("says why it couldn’t be fetched, and tries again when asked again", async () => {
    previewFails = "That message is no longer in Gmail.";
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /by hand/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That message is no longer in Gmail.");
    previewFails = "";
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await settled();
    await userEvent.click(screen.getByRole("button", { name: /by hand/ }));
    expect(await screen.findByTestId("preview")).toHaveTextContent("EX 410");
  });

  it("takes the message off the page when the form is cancelled", async () => {
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /by hand/ }));
    await screen.findByTestId("preview");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByTestId("preview")).toBeNull();
  });

  it("opens the message beside the form when adding by hand", async () => {
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Add .Mail from example-air.example on 2026-10-17. by hand/ }));
    expect(await screen.findByTestId("preview")).toHaveTextContent("EX 410");
    expect(screen.getByLabelText("Provider")).toBeInTheDocument();
  });

  it("opens the message from View email without starting the form, and closes it again", async () => {
    render(ReviewPage);
    const view = await screen.findByRole("button", { name: /View email .Mail from example-air.example on 2026-10-17./ });
    expect(view).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(view);
    expect(await screen.findByTestId("preview")).toHaveTextContent("EX 410");
    expect(view).toHaveAttribute("aria-expanded", "true");
    expect(screen.queryByLabelText("Provider")).toBeNull();
    expect(calls).toContainEqual(["/api/review/1/preview", undefined, undefined]);
    await userEvent.click(view);
    expect(screen.queryByTestId("preview")).toBeNull();
    expect(view).toHaveAttribute("aria-expanded", "false");
  });

  it("shows a shared item's message from View email, and the same message as Add by hand", async () => {
    held = { matches: [], items: [item({ id: 4, mine: false, owner: "Sam Doe" })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /View email/ }));
    const viewed = await screen.findByTestId("preview");
    const viewedText = viewed.textContent;
    await userEvent.click(screen.getByRole("button", { name: /Add .Mail from example-air.example on 2026-10-17. by hand/ }));
    expect(within(await screen.findByRole("dialog")).getByTestId("preview").textContent).toBe(viewedText);
    expect(screen.getByLabelText("Provider")).toBeInTheDocument();
  });

  it("keeps the message open when Add by hand is cancelled, if View email opened it", async () => {
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /View email/ }));
    await userEvent.click(await screen.findByRole("button", { name: /by hand/ }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByTestId("preview")).toHaveTextContent("EX 410");
  });

  it("keeps the message nowhere but the page", async () => {
    const stored: string[] = [];
    vi.spyOn(Storage.prototype, "setItem").mockImplementation((_k: string, v: string) => { stored.push(v); });
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /by hand/ }));
    await screen.findByTestId("preview");
    expect(stored).toEqual([]);
    vi.restoreAllMocks();
  });
});

describe("Review: Ask AI", () => {
  it("is offered only when the AI is on", async () => {
    render(ReviewPage);
    await screen.findByTestId("review-item");
    expect(screen.queryByRole("button", { name: /Ask AI/ })).toBeNull();
  });

  it("asks the AI, then offers its suggestion to check", async () => {
    held = { matches: [], items: [item()], who: [], ai: true };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Ask AI about/ }));
    await waitFor(() => expect(calls).toContainEqual(["/api/review/1/suggest", "POST", undefined]));
    expect(await screen.findByRole("button", { name: /Check the AI.s suggestion/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Ask AI about/ })).toHaveTextContent("Ask again");
  });

  it("asks about several messages at once, each showing its own progress", async () => {
    let open: () => void = () => {};
    suggestGate = new Promise((r) => { open = r; });
    held = { matches: [], items: [item(), item({ id: 2 }), item({ id: 3 }), item({ id: 4 })], who: [], ai: true };
    render(ReviewPage);
    const asks = await screen.findAllByRole("button", { name: /Ask AI about “/ });
    await userEvent.click(asks[0]);
    await userEvent.click(asks[1]);
    await waitFor(() => expect(calls.filter((c) => c[0].endsWith("/suggest")).map((c) => c[0])).toEqual(["/api/review/1/suggest", "/api/review/2/suggest"]));
    expect(asks[0]).toHaveTextContent("Asking…");
    expect(asks[1]).toHaveTextContent("Asking…");
    expect(asks[0]).toBeDisabled();
    expect(asks[2]).toBeEnabled();
    expect(screen.getByRole("button", { name: "Ask AI about all 2" })).toBeEnabled();
    open();
    await waitFor(() => expect(screen.getAllByRole("button", { name: /Check the AI.s suggestion/ })).toHaveLength(4));
  });

  it("says when the AI couldn’t be asked", async () => {
    held = { matches: [], items: [item()], who: [], ai: true };
    suggestFails = "Turn on AI suggestions in Settings first.";
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Ask AI about/ }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Turn on AI suggestions in Settings first."));
  });

  it("asks about every message without a suggestion at once", async () => {
    held = { matches: [], items: [item(), item({ id: 2 }), item({ id: 3, suggestions: [] })], who: [], ai: true };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: "Ask AI about all 3" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Asked the AI about 3 messages"));
    expect(calls.filter((c) => c[0].endsWith("/suggest")).map((c) => c[0])).toEqual(["/api/review/1/suggest", "/api/review/2/suggest", "/api/review/3/suggest"]);
  });

  it("asks only about the filtered emails, not the ones the filter hides", async () => {
    held = { matches: [], who: [], ai: true, ai_mode: "openrouter", items: [item({ id: 1, sender_domain: "example-air.example" }), item({ id: 2, sender_domain: "seaside-stays.example" }),
      item({ id: 3, sender_domain: "seaside-stays.example" }), item({ id: 4, sender_domain: "other.example" })] };
    setQuery("sender=seaside-stays.example");
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: "Ask AI about these 2 emails" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Asked the AI about 2 messages"));
    expect(calls.filter((c) => c[0].endsWith("/suggest")).map((c) => c[0])).toEqual(["/api/review/2/suggest", "/api/review/3/suggest"]);
  });

  it("says where the text goes next to the bulk button", async () => {
    held = { matches: [], who: [], ai: true, ai_mode: "openrouter", items: [item(), item({ id: 2 })] };
    const view = render(ReviewPage);
    expect(await screen.findByTestId("ask-all")).toHaveTextContent("The text of these 2 emails goes to OpenRouter, redacted first.");
    view.unmount();
    held = { ...held, ai_mode: "local" };
    render(ReviewPage);
    expect(await screen.findByTestId("ask-all")).toHaveTextContent("to your own Ollama server, unredacted.");
  });

  it("does not widen the scope when the filter has nothing to ask about", async () => {
    held = { matches: [], who: [], ai: true, items: [item({ id: 1, sender_domain: "example-air.example" }), item({ id: 2, sender_domain: "example-air.example" }),
      item({ id: 3, sender_domain: "seaside-stays.example", suggestions: [SUGGESTION] })] };
    setQuery("sender=seaside-stays.example");
    render(ReviewPage);
    expect(await screen.findByTestId("ask-none-here")).toHaveTextContent("2 emails from other senders or mailboxes are hidden by this filter");
    expect(screen.queryByRole("button", { name: /Ask AI about (all|these)/ })).toBeNull();
    expect(calls.filter((c) => c[0].endsWith("/suggest"))).toHaveLength(0);
  });

  it("offers the filtered bulk ask for a single email, and keeps the count when stopped by a failure", async () => {
    held = { matches: [], who: [], ai: true, ai_mode: "local", items: [item({ id: 1, sender_domain: "a.example" }), item({ id: 2, sender_domain: "b.example" }), item({ id: 3, sender_domain: "b.example" })] };
    suggestFails = "Turn on AI suggestions in Settings first.";
    setQuery("sender=b.example");
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: "Ask AI about these 2 emails" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Asked about 0 of 2: Turn on AI suggestions in Settings first."));
    setQuery("sender=a.example");
    expect(await screen.findByRole("button", { name: "Ask AI about these 1 email" })).toBeInTheDocument();
  });

  it("asks about shared items too, alone and in bulk", async () => {
    held = { matches: [], items: [item({ id: 4, mine: false, owner: "Sam Doe" }), item({ id: 5, mine: true })], who: [], ai: true };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: "Ask AI about all 2" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Asked the AI about 2 messages"));
    expect(calls.filter((c) => c[0].endsWith("/suggest")).map((c) => c[0])).toEqual(["/api/review/4/suggest", "/api/review/5/suggest"]);
  });

  it("says how many were asked when a later message fails after earlier ones completed", async () => {
    held = { matches: [], items: [item(), item({ id: 2 }), item({ id: 3 })], who: [], ai: true };
    suggestFails = "The AI didn’t answer.";
    suggestOkFirst = 1;
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: "Ask AI about all 3" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Asked about 1 of 3: The AI didn’t answer."));
    expect(toast.success).not.toHaveBeenCalled();
    expect(calls.filter((c) => c[0].endsWith("/suggest")).map((c) => c[0])).toEqual(["/api/review/1/suggest", "/api/review/2/suggest"]);
  });

  it("stops the bulk ask at the first failure and says how far it got", async () => {
    held = { matches: [], items: [item(), item({ id: 2 })], who: [], ai: true };
    suggestFails = "Turn on AI suggestions in Settings first.";
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: "Ask AI about all 2" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Asked about 0 of 2: Turn on AI suggestions in Settings first."));
    expect(calls.filter((c) => c[0].endsWith("/suggest"))).toHaveLength(1);
  });
});

describe.each([["a phone", true, "bottom"], ["a desktop", false, "right"]] as const)("Review on %s", (_name, phone, side) => {
  beforeEach(() => { viewport.phone = phone; });
  afterEach(() => { viewport.phone = false; });

  it("opens View email's message on the page, not in a sheet", async () => {
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /View email/ }));
    expect(await screen.findByTestId("preview")).toHaveTextContent("EX 410");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens Add by hand in a sheet with the message above the form, and Cancel closes it", async () => {
    render(ReviewPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: /Add .* by hand/ }));
    const sheet = await screen.findByRole("dialog", { name: "Add this booking by hand" });
    expect(sheet).toHaveAttribute("data-side", side);
    const peek = await within(sheet).findByTestId("preview");
    expect(peek).toHaveTextContent("Your flight EX 410");
    const form = within(sheet).getByRole("form", { name: "Add this booking by hand" });
    expect(peek.compareDocumentPosition(form) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(sheet).getByLabelText("Provider")).toHaveValue("Example Air");
    expect(within(sheet).getAllByRole("heading", { name: "Add this booking by hand" })).toHaveLength(1);
    const list = screen.getByRole("list", { name: "Add missing details" });
    expect(list.querySelector("form")).toBeNull();
    expect(within(list).queryByTestId("preview")).toBeNull();
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);
    await u.click(within(sheet).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("opens Check suggestion in the sheet with the message above the form", async () => {
    held = { matches: [], items: [item({ suggestions: [SUGGESTION] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    const sheet = await screen.findByRole("dialog", { name: "Check this suggestion" });
    expect(sheet).toHaveAttribute("data-side", side);
    expect(await within(sheet).findByTestId("preview")).toHaveTextContent("EX 410");
    expect(within(sheet).getByLabelText("Confirmation code")).toHaveValue("QW4R7T");
    expect(within(sheet).queryByText(/An AI read the email/)).toBeNull();
    expect(screen.getByRole("list", { name: "Check suggestions" }).querySelector("form")).toBeNull();
  });

  it("closes an untouched form with Escape, the close button, Cancel or an outside click without asking", async () => {
    render(ReviewPage);
    const u = userEvent.setup();
    const open = await screen.findByRole("button", { name: /Add .* by hand/ });
    const gone = settled;
    await u.click(open);
    await screen.findByRole("dialog");
    await u.keyboard("{Escape}");
    await gone();
    await u.click(open);
    await u.click(await screen.findByRole("button", { name: "Close" }));
    await gone();
    await u.click(open);
    await u.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }));
    await gone();
    await u.click(open);
    await screen.findByRole("dialog");
    const overlay = document.querySelector("[data-slot='sheet-overlay']") as HTMLElement;
    overlay.dispatchEvent(new MouseEvent("pointerdown", { clientX: 5, clientY: 5, bubbles: true }));
    overlay.dispatchEvent(new MouseEvent("pointerup", { clientX: 5, clientY: 5, bubbles: true }));
    overlay.dispatchEvent(new MouseEvent("click", { clientX: 5, clientY: 5, bubbles: true }));
    await gone();
    expect(screen.queryByText("Discard changes?")).toBeNull();
  });

  it("asks before discarding a changed form, keeps it on Keep editing and closes it on Discard", async () => {
    render(ReviewPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: /Add .* by hand/ }));
    const sheet = await screen.findByRole("dialog", { name: "Add this booking by hand" });
    if (phone) await u.click(within(sheet).getByRole("button", { name: "Booking" }));
    await u.type(within(sheet).getByLabelText("From (airport code)"), "JFK");
    await u.keyboard("{Escape}");
    const ask = await screen.findByRole("dialog", { name: "Discard changes?" });
    await u.click(within(ask).getByRole("button", { name: "Keep editing" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Discard changes?" })).toBeNull());
    expect(screen.getByRole("dialog", { name: "Add this booking by hand" })).toBeInTheDocument();
    expect(within(sheet).getByLabelText("From (airport code)")).toHaveValue("JFK");
    await u.click(within(sheet).getByRole("button", { name: "Close" }));
    await u.click(within(await screen.findByRole("dialog", { name: "Discard changes?" })).getByRole("button", { name: "Discard changes" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls.some(([path]) => path === "/api/segments")).toBe(false);
  });

  it("treats a field changed back to what it was as untouched", async () => {
    render(ReviewPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: /Add .* by hand/ }));
    const sheet = await screen.findByRole("dialog");
    if (phone) await u.click(within(sheet).getByRole("button", { name: "Booking" }));
    await u.type(within(sheet).getByLabelText("From (airport code)"), "J");
    await u.clear(within(sheet).getByLabelText("From (airport code)"));
    await u.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("moves focus into the form on open and back to the button on close", async () => {
    render(ReviewPage);
    const u = userEvent.setup();
    const open = await screen.findByRole("button", { name: /Add .* by hand/ });
    await u.click(open);
    const sheet = await screen.findByRole("dialog");
    if (phone) await waitFor(() => expect(within(sheet).getByRole("heading", { name: "Add this booking by hand" })).toHaveFocus());
    else await waitFor(() => expect(within(sheet).getByLabelText("What is it?")).toHaveFocus());
    await u.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(open).toHaveFocus());
  });

  it("moves focus to the heading for a suggestion", async () => {
    held = { matches: [], items: [item({ suggestions: [SUGGESTION] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    const sheet = await screen.findByRole("dialog", { name: "Check this suggestion" });
    await waitFor(() => expect(within(sheet).getByRole("heading", { name: "Check this suggestion" })).toHaveFocus());
  });

  it("collapses the email to its subject and opens it again", async () => {
    render(ReviewPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: /Add .* by hand/ }));
    const sheet = await screen.findByRole("dialog");
    if (phone) {
      const email = within(sheet).getByRole("button", { name: "Email" });
      const booking = within(sheet).getByRole("button", { name: "Booking" });
      expect(email).toHaveAttribute("aria-pressed", "true");
      expect(await within(sheet).findByText(/Your flight EX 410/)).toBeVisible();
      expect(within(sheet).getByTestId("booking-fields")).not.toBeVisible();
      expect(within(sheet).getByRole("button", { name: "Add to my trips" })).toBeVisible();
      await u.click(booking);
      expect(booking).toHaveAttribute("aria-pressed", "true");
      expect(within(sheet).getByText(/Your flight EX 410/)).not.toBeVisible();
      expect(within(sheet).getByTestId("booking-fields")).toBeVisible();
      expect(within(sheet).getByRole("button", { name: "Add to my trips" })).toBeVisible();
      await u.click(email);
      expect(within(sheet).getByText(/Your flight EX 410/)).toBeVisible();
      return;
    }
    const toggle = within(sheet).getByRole("button", { name: "Hide the email" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(await within(sheet).findByText(/Your flight EX 410/)).toBeVisible();
    await u.click(toggle);
    const closed = within(sheet).getByRole("button", { name: "Show the email" });
    expect(closed).toHaveAttribute("aria-expanded", "false");
    expect(within(sheet).getByText(/Your flight EX 410/)).not.toBeVisible();
    expect(within(sheet).getByText("Mail from example-air.example on 2026-10-17")).toBeVisible();
    await u.click(closed);
    expect(within(sheet).getByRole("button", { name: "Hide the email" })).toHaveAttribute("aria-expanded", "true");
    expect(within(sheet).getByText(/Your flight EX 410/)).toBeVisible();
  });

  it("replaces the open form when another item’s Add by hand is used", async () => {
    held = { matches: [], items: [item({ id: 1, subject: "First booking" }), item({ id: 2, subject: "Second booking" })], who: [], ai: false };
    render(ReviewPage);
    await screen.findByText("First booking");
    const first = screen.getByRole("button", { name: "Add “First booking” by hand" });
    const second = screen.getByRole("button", { name: "Add “Second booking” by hand" });
    first.click();
    await screen.findByRole("dialog");
    await waitFor(() => expect(calls.some(([path]) => path === "/api/review/1/preview")).toBe(true));
    second.click();
    await waitFor(() => expect(calls.some(([path]) => path === "/api/review/2/preview")).toBe(true));
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(screen.getAllByTestId("preview")).toHaveLength(1);
    expect(screen.getAllByRole("form")).toHaveLength(1);
  });

  it("adds the booking from the sheet and closes it", async () => {
    render(ReviewPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: /Add .* by hand/ }));
    const sheet = await screen.findByRole("dialog");
    if (phone) await u.click(within(sheet).getByRole("button", { name: "Booking" }));
    await u.type(within(sheet).getByLabelText("From (airport code)"), "JFK");
    await u.type(within(sheet).getByLabelText("To (airport code)"), "SFO");
    await u.type(within(sheet).getByLabelText("Departs"), "2026-12-08T08:00");
    await u.type(within(sheet).getByLabelText("Arrives"), "2026-12-08T11:00");
    await u.click(within(sheet).getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(calls.some(([path, method]) => path === "/api/segments" && method === "POST")).toBe(true));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("keeps the sheet open while adding, and shows a failure in it with what was typed", async () => {
    render(ReviewPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: /Add .* by hand/ }));
    const sheet = await screen.findByRole("dialog");
    if (phone) await u.click(within(sheet).getByRole("button", { name: "Booking" }));
    await u.type(within(sheet).getByLabelText("From (airport code)"), "JFK");
    await u.type(within(sheet).getByLabelText("To (airport code)"), "SFO");
    await u.type(within(sheet).getByLabelText("Departs"), "2026-12-08T08:00");
    await u.type(within(sheet).getByLabelText("Arrives"), "2026-12-08T11:00");
    let fail: (e: Error) => void = () => {};
    const inner = vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation(async (path: string, opts?: { method?: string; body?: unknown }) => {
      if (path === "/api/segments") return new Promise((_, reject) => { fail = reject; });
      return inner(path, opts as Parameters<typeof inner>[1]);
    });
    await u.click(within(sheet).getByRole("button", { name: "Add to my trips" }));
    await u.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBe(sheet);
    fail(new Error("Couldn’t add it"));
    expect(await within(sheet).findByRole("alert")).toHaveTextContent("Couldn’t add it");
    expect(within(sheet).getByLabelText("From (airport code)")).toHaveValue("JFK");
  });

  it("marks a suggestion the scan asked for on its own as read automatically, and one asked for by hand not", async () => {
    const hotel = { kind: "hotel" as const, provider: "Seaside Inn", origin: "Seaside Inn", start_local: "2026-11-21T15:00", end_local: "2026-11-25T11:00", start_zone: "Europe/London" };
    held = { matches: [], items: [item({ id: 1, suggestions: [hotel], auto_read: true }), item({ id: 2, suggestions: [hotel] }), item({ id: 3 })], who: [], ai: true };
    render(ReviewPage);
    expect(await screen.findAllByText("AI suggestion")).toHaveLength(2);
    expect(screen.getAllByText("read automatically")).toHaveLength(1);
  });

  it("shows a booking Waypoint read itself with its source fields outlined, and not as an AI suggestion", async () => {
    const read = { kind: "hotel" as const, provider: "Seaside Inn", confirmation: "SS48213", origin: "Seaside Inn", address: "12 Beach Road, Brighton, UK",
      start_local: "2026-11-21T15:00", end_local: "2026-11-25T11:00", start_zone: "Europe/London",
      sources: { origin: "property", start_local: "check-in", end_local: "check-out", confirmation: "confirmation number", address: "address" } };
    held = { matches: [], items: [item({ reason: "generic", sender_domain: "seaside-stays.example", suggestions: [read] })], who: [], ai: true };
    render(ReviewPage);
    expect(await screen.findByText("Read from the email")).toBeInTheDocument();
    expect(screen.queryByText("AI suggestion")).toBeNull();
    expect(screen.queryByRole("button", { name: /Ask AI/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Check what Waypoint read/ }));
    expect(screen.getByText(/later mail from seaside-stays.example is still checked with you first/)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Also trust seaside-stays.example/ })).not.toBeChecked();
    const checkin = screen.getByLabelText(/^Check-in/);
    expect(checkin).toHaveValue("2026-11-21T15:00");
    expect(checkin).toHaveClass("ring-2");
    expect(screen.getByText("from “check-in”")).toBeInTheDocument();
    expect(screen.getByLabelText(/^Address/)).toHaveValue("12 Beach Road, Brighton, UK");
    expect(screen.getByLabelText(/^Address/)).toHaveClass("ring-2");
    expect(screen.getByLabelText(/^Hotel/)).toHaveClass("ring-2");
  });
});

describe("Review: a booking email with several flights", () => {
  const outbound = { kind: "flight" as const, provider: "Delta", confirmation: "Q7M2KD", origin: "BOS", destination: "DEN", flight_number: "DL 1204", cabin: "Economy",
    start_local: "2026-12-05T07:15", end_local: "2026-12-05T10:05" };
  const back = { kind: "flight" as const, provider: "Delta", confirmation: "Q7M2KD", origin: "DEN", destination: "BOS", flight_number: "DL 1377", cabin: "Economy",
    start_local: "2026-12-11T16:20", end_local: "2026-12-11T21:50" };
  const open = async () => {
    held = { matches: [], items: [item({ suggestions: [outbound, back] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s 2 suggestions/ }));
  };

  it("offers one button for the item and shows one suggestion per leg, in order, each with its own fields", async () => {
    await open();
    expect(screen.getByRole("button", { name: /Check the AI’s 2 suggestions/ })).toHaveTextContent("Check 2 suggestions");
    expect(screen.getByRole("heading", { name: "Check these suggestions" })).toBeInTheDocument();
    const legs = screen.getAllByTestId("leg");
    expect(legs.map((l) => l.querySelector("legend")?.textContent)).toEqual(["Flight 1 of 2: BOS → DEN", "Flight 2 of 2: DEN → BOS"]);
    expect(within(legs[0]).getByLabelText("From (airport code)")).toHaveValue("BOS");
    expect(within(legs[0]).getByLabelText("Departs")).toHaveValue("2026-12-05T07:15");
    expect(within(legs[0]).getByLabelText(/Flight number/)).toHaveValue("DL 1204");
    expect(within(legs[1]).getByLabelText("From (airport code)")).toHaveValue("DEN");
    expect(within(legs[1]).getByLabelText("Arrives")).toHaveValue("2026-12-11T21:50");
    expect(within(legs[1]).getByLabelText(/Flight number/)).toHaveValue("DL 1377");
    expect(screen.getByRole("button", { name: "Add 2 flights" })).toBeInTheDocument();
    expect(calls.some(([p]) => p === "/api/segments")).toBe(false);
  });

  it("adds both legs together, each as it was edited, and takes the item off the list with both bookings", async () => {
    await open();
    const second = screen.getAllByTestId("leg")[1];
    await userEvent.clear(within(second).getByLabelText("Departs"));
    await userEvent.type(within(second).getByLabelText("Departs"), "2026-12-11T17:00");
    await userEvent.click(screen.getByRole("button", { name: "Add 2 flights" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added 2 flights to your trips"));
    const posted = calls.filter(([p]) => p === "/api/segments");
    expect(posted.map(([, , b]) => b)).toMatchObject([
      { kind: "flight", origin: "BOS", destination: "DEN", start_local: "2026-12-05T07:15", end_local: "2026-12-05T10:05", confirmation: "Q7M2KD", details: { flight_number: "DL 1204", cabin: "Economy" } },
      { kind: "flight", origin: "DEN", destination: "BOS", start_local: "2026-12-11T17:00", end_local: "2026-12-11T21:50", details: { flight_number: "DL 1377" } }]);
    expect(posted.map(([, m]) => m)).toEqual(["POST", "POST"]);
    expect(calls.filter(([p, m]) => m === "DELETE" && p.startsWith("/api/review/"))).toEqual([["/api/review/1?segment=42&segment=43", "DELETE", undefined]]);
    expect(screen.queryByTestId("leg")).toBeNull();
  });

  it("lets one leg be dismissed before adding, and then adds the other as a single booking", async () => {
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Dismiss Flight 1 of 2: BOS → DEN" }));
    expect(screen.queryByTestId("leg")).toBeNull();
    expect(screen.getByLabelText("From (airport code)")).toHaveValue("DEN");
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added to your trips"));
    expect(calls.filter(([p]) => p === "/api/segments").map(([, , b]) => (b as { origin: string }).origin)).toEqual(["DEN"]);
  });

  it("keeps the leg that failed in the form, says how many were added and does not take the item off the list", async () => {
    secondSegmentFails = "The flight was refused.";
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Add 2 flights" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Added 1 of 2, but couldn’t add the rest: The flight was refused.");
    expect(screen.getByLabelText("From (airport code)")).toHaveValue("DEN");
    expect(screen.getByRole("button", { name: "Add to my trips" })).toBeInTheDocument();
    expect(calls.some(([p, m]) => m === "DELETE" && p.startsWith("/api/review/"))).toBe(false);
  });

  it("sends every booking it added on the final take-off, even when one leg had to be retried", async () => {
    secondSegmentFails = "The flight was refused.";
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Add 2 flights" }));
    await screen.findByRole("alert");
    secondSegmentFails = "";
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(calls.filter(([p, m]) => m === "DELETE" && p.startsWith("/api/review/")).map(([p]) => p)).toEqual(["/api/review/1?segment=42&segment=43"]);
  });

  it("keeps the last leg in the form until the item is off the list, then reports a failed take-off and clears the email preview", async () => {
    let release: () => void = () => {};
    takeOffGate = new Promise<void>((resolve) => { release = resolve; });
    takeOffFails = "The list is busy.";
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Add 2 flights" }));
    await waitFor(() => expect(calls.filter(([p]) => p === "/api/segments")).toHaveLength(2));
    await waitFor(() => expect(calls.some(([p, m]) => m === "DELETE" && p.includes("?segment="))).toBe(true));
    expect(screen.getByLabelText("From (airport code)")).toHaveValue("DEN");
    release();
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Added, but couldn’t take it off this list: The list is busy."));
    expect(toast.success).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByLabelText("From (airport code)")).toBeNull());
    const previews = () => calls.filter(([p]) => p.endsWith("/preview")).length;
    expect(previews()).toBe(1);
    await settled();
    expect(calls).toContainEqual(["/api/review/1?suggestion=1&suggestion=2", "DELETE", undefined]);
    await userEvent.click(await screen.findByRole("button", { name: /Add .* by hand/ }));
    await waitFor(() => expect(previews()).toBe(2));
  });

  it("does the same for an item with a single suggestion", async () => {
    takeOffFails = "The list is busy.";
    held = { matches: [], items: [item({ suggestions: [outbound] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Added, but couldn’t take it off this list: The list is busy."));
    expect(toast.success).not.toHaveBeenCalled();
    await settled();
    await userEvent.click(await screen.findByRole("button", { name: /Add .* by hand/ }));
    await waitFor(() => expect(calls.filter(([p]) => p.endsWith("/preview"))).toHaveLength(2));
  });

  it("takes the leg that was added off the item's suggestions when the rest is cancelled, so it is not offered again", async () => {
    secondSegmentFails = "The flight was refused.";
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Add 2 flights" }));
    await screen.findByRole("alert");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.click(await screen.findByRole("button", { name: "Discard changes" }));
    await waitFor(() => expect(calls).toContainEqual(["/api/review/1?suggestion=1", "DELETE", undefined]));
    expect(calls.some(([p, m]) => m === "DELETE" && p.includes("?segment="))).toBe(false);
    secondSegmentFails = "";
    await settled();
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    expect(screen.getByLabelText("From (airport code)")).toHaveValue("DEN");
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added to your trips"));
    expect(calls.filter(([p]) => p === "/api/segments").map(([, , b]) => (b as { origin: string }).origin)).toEqual(["BOS", "DEN", "DEN"]);
  });

  it("closes without adding anything on Cancel", async () => {
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByTestId("leg")).toBeNull();
    expect(calls.some(([p]) => p === "/api/segments")).toBe(false);
  });

  it("looks as before for an item with one suggestion", async () => {
    held = { matches: [], items: [item({ suggestions: [outbound] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    expect(screen.getByRole("heading", { name: "Check this suggestion" })).toBeInTheDocument();
    expect(screen.queryByTestId("leg")).toBeNull();
    expect(screen.getByRole("button", { name: "Add to my trips" })).toBeInTheDocument();
  });

  it("warns, without blocking, when a suggested flight is far longer than any flight", async () => {
    held = { matches: [], items: [item({ suggestions: [{ ...outbound, end_local: "2026-12-11T21:50" }] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    expect(await screen.findByText("This flight is 6 days long. Check the times.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added to your trips"));
  });

  it("shows no warning for an ordinary flight, and the warning goes when the time is put right", async () => {
    held = { matches: [], items: [item({ suggestions: [{ ...outbound, end_local: "2026-12-11T21:50" }] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    await screen.findByText(/This flight is/);
    await userEvent.clear(screen.getByLabelText("Arrives"));
    await userEvent.type(screen.getByLabelText("Arrives"), "2026-12-05T10:05");
    await waitFor(() => expect(screen.queryByText(/This flight is/)).toBeNull());
  });
});

describe("Review: several legs or bookings added by hand from one email", () => {
  type User = ReturnType<typeof userEvent.setup>;
  const openByHand = async () => {
    render(ReviewPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: /Add .* by hand/ }));
    await screen.findByRole("dialog");
    return u;
  };
  const typeLeg = async (u: User, leg: HTMLElement, fields: Record<string, string>) => {
    for (const [label, value] of Object.entries(fields)) {
      await u.clear(within(leg).getByLabelText(label));
      await u.type(within(leg).getByLabelText(label), value);
    }
  };
  const outbound = { "From (airport code)": "BOS", "To (airport code)": "DEN", Departs: "2027-01-02T07:15", Arrives: "2027-01-02T09:40" };
  const inbound = { "To (airport code)": "BOS", Departs: "2027-01-09T16:00", Arrives: "2027-01-09T21:30" };
  const roundTrip = async () => {
    const u = await openByHand();
    await u.type(screen.getByLabelText("Confirmation code"), "ZZ9Y8X");
    await typeLeg(u, screen.getByRole("dialog"), outbound);
    await u.click(screen.getByRole("button", { name: "Add another leg or booking" }));
    await typeLeg(u, screen.getAllByTestId("leg")[1], inbound);
    return u;
  };
  const posted = () => calls.filter(([p]) => p === "/api/segments").map(([, , b]) => b);
  const takeOffs = () => calls.filter(([p, m]) => m === "DELETE" && p.startsWith("/api/review/")).map(([p]) => p);
  const discardAsked = () => screen.queryByRole("dialog", { name: "Discard changes?" });

  it("offers the button under a single leg without changing the single-leg form", async () => {
    const u = await openByHand();
    expect(screen.getByRole("button", { name: "Add another leg or booking" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add to my trips" })).toBeInTheDocument();
    expect(screen.queryByTestId("leg")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Dismiss (Flight|Booking)/ })).toBeNull();
    await u.click(screen.getByRole("button", { name: "Cancel" }));
    await settled();
  });

  it("adds a leg with the same kind, provider and code, and a flight starting where the last one ended", async () => {
    const u = await openByHand();
    await u.type(screen.getByLabelText("Confirmation code"), "ZZ9Y8X");
    await u.type(screen.getByLabelText("From (airport code)"), "BOS");
    await u.type(screen.getByLabelText("To (airport code)"), "DEN");
    await u.click(screen.getByRole("button", { name: "Add another leg or booking" }));
    const legs = screen.getAllByTestId("leg");
    expect(legs.map((l) => l.querySelector("legend")?.textContent)).toEqual(["Flight 1 of 2: BOS → DEN", "Flight 2 of 2"]);
    expect(within(legs[1]).getByLabelText("What is it?")).toHaveValue("flight");
    expect(within(legs[1]).getByLabelText("Provider")).toHaveValue("Example Air");
    expect(within(legs[1]).getByLabelText("Confirmation code")).toHaveValue("ZZ9Y8X");
    expect(within(legs[1]).getByLabelText("From (airport code)")).toHaveValue("DEN");
    expect(within(legs[1]).getByLabelText("To (airport code)")).toHaveValue("");
    expect(within(legs[1]).getByLabelText("Departs")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Add 2 flights" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add another leg or booking" })).toBeInTheDocument();
    expect(within(legs[1]).getByLabelText("What is it?")).toHaveFocus();
  });

  it("adds a rental car leg whose drop-off says Same as pick-up and saves as the pick-up", async () => {
    const u = await openByHand();
    await u.selectOptions(screen.getByLabelText("What is it?"), "car");
    await u.click(screen.getByRole("button", { name: "Add another leg or booking" }));
    const legs = screen.getAllByTestId("leg");
    expect(within(legs[1]).getByLabelText("What is it?")).toHaveValue("car");
    expect(within(legs[1]).getByPlaceholderText("Same as pick-up")).toHaveValue("");
    expect(within(legs[1]).queryByLabelText(/address/i)).toBeNull();
    await u.click(screen.getByRole("button", { name: "Cancel" }));
  });

  it("adds a round trip as two flights from one email and takes the item off the list once", async () => {
    const u = await roundTrip();
    await u.click(screen.getByRole("button", { name: "Add 2 flights" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added 2 flights to your trips"));
    expect(posted()).toEqual([
      { kind: "flight", start_local: "2027-01-02T07:15", end_local: "2027-01-02T09:40", provider: "Example Air", confirmation: "ZZ9Y8X", origin: "BOS", destination: "DEN" },
      { kind: "flight", start_local: "2027-01-09T16:00", end_local: "2027-01-09T21:30", provider: "Example Air", confirmation: "ZZ9Y8X", origin: "DEN", destination: "BOS" }]);
    expect(calls.filter(([p]) => p.endsWith("/same"))).toHaveLength(2);
    expect(takeOffs()).toEqual(["/api/review/1?segment=42&segment=43"]);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("adds a flight and a hotel from one email, clearing the flight’s places when the kind changes", async () => {
    const u = await openByHand();
    await u.type(screen.getByLabelText("Confirmation code"), "ZZ9Y8X");
    await typeLeg(u, screen.getByRole("dialog"), outbound);
    await u.click(screen.getByRole("button", { name: "Add another leg or booking" }));
    const second = screen.getAllByTestId("leg")[1];
    expect(within(second).getByLabelText("From (airport code)")).toHaveValue("DEN");
    await u.selectOptions(within(second).getByLabelText("What is it?"), "hotel");
    expect(within(second).getByLabelText("Hotel")).toHaveValue("");
    expect(within(second).getByLabelText("Provider")).toHaveValue("Example Air");
    expect(screen.getByRole("button", { name: "Add 2 bookings" })).toBeInTheDocument();
    await typeLeg(u, second, { Provider: "Example Hotels", Hotel: "Harbour Hotel", "Check-in": "2027-01-02T15:00", "Check-out": "2027-01-05T11:00", Address: "1 Harbour Road, Denver" });
    await u.click(screen.getByRole("button", { name: "Add 2 bookings" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added 2 bookings to your trips"));
    expect(posted()).toMatchObject([
      { kind: "flight", origin: "BOS", destination: "DEN" },
      { kind: "hotel", provider: "Example Hotels", confirmation: "ZZ9Y8X", origin: "Harbour Hotel", start_local: "2027-01-02T15:00", end_local: "2027-01-05T11:00", details: { address: "1 Harbour Road, Denver" } }]);
    expect(takeOffs()).toEqual(["/api/review/1?segment=42&segment=43"]);
  });

  it("adds one more leg to the AI’s suggestions", async () => {
    held = { matches: [], items: [item({ suggestions: [SUGGESTION] })], who: [], ai: false };
    render(ReviewPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    await u.click(await screen.findByRole("button", { name: "Add another leg or booking" }));
    const legs = screen.getAllByTestId("leg");
    expect(legs.map((l) => l.querySelector("legend")?.textContent)).toEqual(["Flight 1 of 2: BOS → DEN", "Flight 2 of 2"]);
    expect(within(legs[1]).getByLabelText("Confirmation code")).toHaveValue("QW4R7T");
    expect(within(legs[1]).getByLabelText("From (airport code)")).toHaveValue("DEN");
    expect(screen.getByRole("heading", { name: "Check these suggestions" })).toBeInTheDocument();
    await typeLeg(u, legs[1], { "To (airport code)": "BOS", Departs: "2026-12-09T10:00", Arrives: "2026-12-09T15:00" });
    await u.click(screen.getByRole("button", { name: "Add 2 flights" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added 2 flights to your trips"));
    expect(posted()).toMatchObject([{ origin: "BOS", destination: "DEN" }, { origin: "DEN", destination: "BOS", confirmation: "QW4R7T" }]);
    expect(takeOffs()).toEqual(["/api/review/1?segment=42&segment=43"]);
  });

  it("dismisses a leg, leaving the last one as a plain form with nothing to dismiss", async () => {
    const u = await openByHand();
    await u.type(screen.getByLabelText("From (airport code)"), "BOS");
    await u.click(screen.getByRole("button", { name: "Add another leg or booking" }));
    expect(screen.getAllByRole("button", { name: /^Dismiss Flight/ })).toHaveLength(2);
    await u.click(screen.getByRole("button", { name: "Dismiss Flight 2 of 2" }));
    expect(screen.queryByTestId("leg")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Dismiss (Flight|Booking)/ })).toBeNull();
    expect(screen.getByLabelText("From (airport code)")).toHaveValue("BOS");
    expect(screen.getByRole("button", { name: "Add to my trips" })).toBeInTheDocument();
  });

  it("validates every leg before adding any", async () => {
    const u = await openByHand();
    await u.type(screen.getByLabelText("Confirmation code"), "ZZ9Y8X");
    await typeLeg(u, screen.getByRole("dialog"), outbound);
    await u.click(screen.getByRole("button", { name: "Add another leg or booking" }));
    const second = screen.getAllByTestId("leg")[1];
    await u.selectOptions(within(second).getByLabelText("What is it?"), "hotel");
    await typeLeg(u, second, { Hotel: "Harbour Hotel", "Check-in": "2027-01-02T15:00", "Check-out": "2027-01-05T11:00" });
    await u.click(screen.getByRole("button", { name: "Add 2 bookings" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter the hotel’s time zone");
    expect(calls.some(([p]) => p === "/api/segments" || p.endsWith("/same"))).toBe(false);
  });

  it("keeps the leg that failed, drops the one that was added, and leaves the item on the list until it is added", async () => {
    secondSegmentFails = "The flight was refused.";
    const u = await roundTrip();
    await u.click(screen.getByRole("button", { name: "Add 2 flights" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Added 1 of 2, but couldn’t add the rest: The flight was refused.");
    expect(screen.queryByTestId("leg")).toBeNull();
    expect(screen.getByLabelText("From (airport code)")).toHaveValue("DEN");
    expect(screen.getByLabelText("To (airport code)")).toHaveValue("BOS");
    expect(takeOffs()).toEqual([]);
    secondSegmentFails = "";
    await u.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(takeOffs()).toEqual(["/api/review/1?segment=42&segment=43"]));
    await waitFor(() => expect(screen.queryByTestId("review-item")).toBeNull());
  });

  it("asks before discarding a leg that was only added, and closes on Discard", async () => {
    const u = await openByHand();
    await u.click(screen.getByRole("button", { name: "Add another leg or booking" }));
    await u.keyboard("{Escape}");
    await u.click(within(await screen.findByRole("dialog", { name: "Discard changes?" })).getByRole("button", { name: "Keep editing" }));
    await waitFor(() => expect(discardAsked()).toBeNull());
    expect(screen.getAllByTestId("leg")).toHaveLength(2);
    await u.keyboard("{Escape}");
    await u.click(within(await screen.findByRole("dialog", { name: "Discard changes?" })).getByRole("button", { name: "Discard changes" }));
    await settled();
    expect(calls.some(([p]) => p === "/api/segments")).toBe(false);
  });

  it("asks before discarding when the only leg left is an added one that was changed", async () => {
    const u = await openByHand();
    await u.click(screen.getByRole("button", { name: "Add another leg or booking" }));
    await u.type(within(screen.getAllByTestId("leg")[1]).getByLabelText("To (airport code)"), "SFO");
    await u.click(screen.getByRole("button", { name: "Dismiss Flight 1 of 2" }));
    expect(screen.queryByTestId("leg")).toBeNull();
    await u.keyboard("{Escape}");
    expect(await screen.findByRole("dialog", { name: "Discard changes?" })).toBeInTheDocument();
  });

  it("closes without asking once the added leg is dismissed again", async () => {
    const u = await openByHand();
    await u.click(screen.getByRole("button", { name: "Add another leg or booking" }));
    await u.click(screen.getByRole("button", { name: "Dismiss Flight 2 of 2" }));
    await u.keyboard("{Escape}");
    await settled();
    expect(discardAsked()).toBeNull();
  });

  it("still hides and shows the email with several legs", async () => {
    const u = await openByHand();
    await u.click(screen.getByRole("button", { name: "Add another leg or booking" }));
    const sheet = screen.getByRole("dialog");
    await u.click(within(sheet).getByRole("button", { name: "Hide the email" }));
    expect(within(sheet).getByText(/Your flight EX 410/)).not.toBeVisible();
    expect(within(sheet).getAllByTestId("leg")).toHaveLength(2);
    await u.click(within(sheet).getByRole("button", { name: "Show the email" }));
    expect(within(sheet).getByText(/Your flight EX 410/)).toBeVisible();
  });

  it("hides the button while the same-booking question is asked, then adds the legs", async () => {
    sameQueue = [null, candidate({ kind: "flight", origin: "DEN", destination: "BOS" })];
    const u = await roundTrip();
    await u.click(screen.getByRole("button", { name: "Add 2 flights" }));
    expect(await screen.findByTestId("same-booking")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add another leg or booking" })).toBeNull();
    await u.click(screen.getByRole("button", { name: "Add as a separate booking" }));
    await waitFor(() => expect(takeOffs()).toEqual(["/api/review/1?segment=42&segment=43"]));
  });
});

describe("Review: the form's explanatory text is gone", () => {
  const KINDS = ["flight", "hotel", "car", "train", "cruise", "parking"];
  const REMOVED = [
    /Waypoint works the time zone out/,
    /Check-in and check-out are both at the hotel/,
    /Entry and exit are both at the lot/,
    /A flight’s time zones come from its airports/,
    /An AI read the email and suggested this/,
    /The email was sent/,
    /Leave this empty to work it out/,
  ];
  const noRemovedText = () => {
    for (const text of REMOVED) expect(screen.queryByText(text)).toBeNull();
  };
  const noDanglingDescribedBy = () => {
    for (const el of document.querySelectorAll("[aria-describedby]")) {
      for (const id of el.getAttribute("aria-describedby")!.split(" ")) expect(document.getElementById(id), `aria-describedby ${id}`).not.toBeNull();
    }
  };
  const suggestionOf = (kind: string, extra: Record<string, unknown> = {}) => ({
    kind, provider: "Example Stays", confirmation: "QW4R7T", origin: "Harbour Hotel", destination: "Harbour Hotel",
    start_local: "2026-12-02T15:00", end_local: "2026-12-05T11:00", start_zone: "Europe/London", address: "1 Quay Road, Bristol BS1 4AA, UK", ...extra,
  }) as unknown as ReviewItem["suggestions"][number];

  it.each(KINDS.flatMap((kind) => [[kind, "2026-10-17"], [kind, null]]))("the suggestion form for %s, received %s, shows none of it", async (kind, received) => {
    held = { matches: [], items: [item({ suggestions: [suggestionOf(kind)], received })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    expect(screen.getByRole("heading", { name: "Check this suggestion" })).toBeInTheDocument();
    noRemovedText();
    noDanglingDescribedBy();
  });

  it.each(["flight", "hotel", "car", "train", "parking"].flatMap((kind) => [[kind, "2026-10-17"], [kind, null]]))("the form by hand for %s, received %s, shows none of it", async (kind, received) => {
    held = { matches: [], items: [item({ received })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /by hand/ }));
    await userEvent.selectOptions(screen.getByLabelText(/What is it/), kind);
    noRemovedText();
    noDanglingDescribedBy();
  });

  it("keeps the blank zone choice, the generic-reading note and the outlines of a suggestion", async () => {
    held = { matches: [], items: [item({ reason: "generic", suggestions: [suggestionOf("hotel")] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check what Waypoint read/ }));
    expect(screen.getByPlaceholderText("Work it out from the address")).toBeInTheDocument();
    expect(screen.getByText(/Waypoint read this from labelled lines in the email/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Address/)).toHaveClass("ring-2");
  });

  it("still says what to enter when a stay has neither a time zone nor an address", async () => {
    held = { matches: [], items: [item({ suggestions: [suggestionOf("hotel", { address: undefined, start_zone: undefined })] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    expect(await screen.findByText(/Enter the hotel’s time zone/)).toBeInTheDocument();
    expect(calls.some(([p]) => p === "/api/segments")).toBe(false);
  });
});

describe("Review: a suggestion that is a booking already in your trips", () => {
  const suggestion = { kind: "flight" as const, provider: "Example Air", confirmation: "QW4R7T", origin: "BOS", destination: "DEN",
    start_local: "2026-12-02T07:15", end_local: "2026-12-02T10:05", flight_number: "EX 204" };
  const back = { ...suggestion, origin: "DEN", destination: "BOS", start_local: "2026-12-08T16:20", end_local: "2026-12-08T21:50", flight_number: "EX 205" };
  const existing = (): ReviewCandidate => ({ segment_id: 31, trip_id: 6, trip_name: "Denver in December", kind: "flight", provider: "Example Air", origin: "BOS", destination: "DEN",
    start_local: "2026-12-02T07:15", end_local: "2026-12-02T10:05" });
  const open = async (...legs: (typeof suggestion)[]) => {
    held = { matches: [], items: [item({ suggestions: legs.length ? legs : [suggestion] })], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Check the AI’s/ }));
    await userEvent.click(screen.getByRole("button", { name: /^Add (to my trips|2 flights)$/ }));
  };

  it("adds as before, with one question to the server first, when it is not the same as anything", async () => {
    await open();
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added to your trips"));
    expect(calls.map(([p]) => p).filter((p) => p.endsWith("/same") || p.endsWith("/attach") || p === "/api/segments")).toEqual(["/api/review/1/same", "/api/segments"]);
    expect(screen.queryByTestId("same-booking")).toBeNull();
  });

  it("says so in the confirm step and adds nothing until the person chooses", async () => {
    sameAs = existing();
    await open();
    const panel = await screen.findByTestId("same-booking");
    expect(panel).toHaveTextContent("This looks like a booking you already have");
    expect(panel).toHaveTextContent("Flight BOS → DEN on 2026-12-02 (Example Air), in Denver in December");
    expect(screen.queryByRole("button", { name: "Add to my trips" })).toBeNull();
    expect(calls.some(([p]) => p === "/api/segments" || p.endsWith("/attach"))).toBe(false);
  });

  it("adds the email to the existing booking instead of making another", async () => {
    sameAs = existing();
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "Add the email to that booking" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added the email to your existing booking"));
    expect(calls.some(([p]) => p === "/api/segments")).toBe(false);
    expect(calls.filter(([p]) => p.endsWith("/attach")).map(([p, m]) => [p, m])).toEqual([["/api/review/1/attach", "POST"]]);
    expect(calls.some(([p, m]) => m === "DELETE" && p === "/api/review/1?segment=99")).toBe(true);
  });

  it("adds a separate booking when the person says it is another one", async () => {
    sameAs = existing();
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "Add as a separate booking" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added to your trips"));
    expect(calls.some(([p]) => p.endsWith("/attach"))).toBe(false);
    expect(calls.filter(([p]) => p === "/api/segments")).toHaveLength(1);
  });

  it("goes back to the form from the confirm step", async () => {
    sameAs = existing();
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "Go back" }));
    expect(screen.queryByTestId("same-booking")).toBeNull();
    expect(screen.getByRole("button", { name: "Add to my trips" })).toBeInTheDocument();
  });

  it("shows the server's reason and adds nothing when the check fails", async () => {
    sameFails = "The time zone is unknown.";
    await open();
    expect(await screen.findByRole("alert")).toHaveTextContent("The time zone is unknown.");
    expect(calls.some(([p]) => p === "/api/segments")).toBe(false);
  });

  it("attaches the legs that match and adds the rest when there are several", async () => {
    sameQueue = [existing(), null];
    await open(suggestion, back);
    await userEvent.click(await screen.findByRole("button", { name: "Add the email to that booking" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added 2 flights to your trips"));
    expect(calls.filter(([p]) => p.endsWith("/attach"))).toHaveLength(1);
    expect(calls.filter(([p]) => p === "/api/segments")).toHaveLength(1);
  });
});

describe("Review as a queue of decisions", () => {
  const many = (n: number, withSuggestion: (i: number) => boolean) => Array.from({ length: n }, (_, i) =>
    item({ id: i + 1, subject: `Message ${i + 1}`, sender_domain: `sender${i % 3}.example`, suggestions: withSuggestion(i) ? [SUGGESTION] : [] }));

  it("says in one line why the emails are waiting, and keeps the long explanation in a closed disclosure", async () => {
    render(ReviewPage);
    expect(await screen.findByText("These emails need your help before they can become bookings.")).toBeInTheDocument();
    const privacy = screen.getByTestId("review-privacy");
    expect(privacy).not.toHaveAttribute("open");
    expect(within(privacy).getByText("How Waypoint handles these emails")).toBeInTheDocument();
    expect(privacy).toHaveTextContent("encrypted");
    expect(privacy).toHaveTextContent("for as long as a booking you add from it exists");
  });

  it("groups by the decision needed, with counts, and omits a group with nothing in it", async () => {
    held = { matches: [held_match()], items: [item({ id: 1, suggestions: [SUGGESTION] }), item({ id: 2 }), item({ id: 3 })], who: [who()], ai: false };
    render(ReviewPage);
    const headings = (await screen.findAllByRole("heading", { level: 2 })).map((h) => h.textContent?.replace(/\s+/g, " ").trim());
    expect(headings).toEqual(["Check suggestions 1", "Add missing details 2", "Match bookings 1", "Match people 1"]);
    expect(within(screen.getByRole("list", { name: "Check suggestions" })).getAllByTestId("review-item")).toHaveLength(1);
    expect(within(screen.getByRole("list", { name: "Add missing details" })).getAllByTestId("review-item")).toHaveLength(2);
  });

  it("shows only the groups that have something, and no jump links for a single group", async () => {
    held = { matches: [], items: [item()], who: [], ai: false };
    render(ReviewPage);
    await screen.findByRole("list", { name: "Add missing details" });
    expect(screen.queryByRole("heading", { name: /Check suggestions/ })).toBeNull();
    expect(screen.queryByRole("heading", { name: /Match/ })).toBeNull();
    expect(screen.queryByRole("navigation", { name: "Jump to a group" })).toBeNull();
  });

  it("moves a partly read email out of the unreadable group, under the suggestion to check", async () => {
    held = { matches: [], items: [item({ reason: "incomplete", suggestions: [SUGGESTION] })], who: [], ai: false };
    render(ReviewPage);
    const list = await screen.findByRole("list", { name: "Check suggestions" });
    expect(within(list).getByText(REASONS.incomplete)).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Add missing details" })).toBeNull();
  });

  it("gives each email one prominent next step: check the suggestion if there is one, else add by hand", async () => {
    held = { matches: [], items: [item({ id: 1, suggestions: [SUGGESTION] }), item({ id: 2 })], who: [], ai: true };
    render(ReviewPage);
    const [suggested, bare] = await screen.findAllByTestId("review-item");
    const prominent = (row: HTMLElement) => within(row).getAllByRole("button").filter((b) => /(^| )bg-primary( |$)/.test(b.className));
    expect(prominent(suggested!).map((b) => b.textContent)).toEqual(["Check suggestion"]);
    expect(prominent(bare!).map((b) => b.textContent)).toEqual(["Add by hand"]);
    expect(within(suggested!).getByRole("button", { name: /View email/ }).className).toContain("bg-secondary");
  });

  it("puts the uncommon actions under a menu labelled More, with this email apart from all future mail from its sender", async () => {
    held = { matches: [], items: [item({ subject: "Your itinerary" })], who: [], ai: true };
    render(ReviewPage);
    const row = await screen.findByTestId("review-item");
    const menu = within(row).getByTestId("action-menu");
    expect(within(menu).getByText("More")).toBeInTheDocument();
    expect(within(row).getByLabelText("More actions for “Your itinerary”")).toBeInTheDocument();
    const mine = within(menu).getByRole("group", { name: "This email" });
    expect(within(mine).getByRole("button", { name: "Ask AI about “Your itinerary”" })).toBeInTheDocument();
    expect(within(mine).getByRole("button", { name: "Dismiss “Your itinerary”" })).toBeInTheDocument();
    expect(within(mine).queryByRole("button", { name: /ignore/ })).toBeNull();
    const future = within(menu).getByRole("group", { name: "All future mail from example-air.example" });
    expect(within(future).getByRole("button", { name: "Not travel: ignore example-air.example" })).toBeInTheDocument();
    expect(within(future).queryByRole("button", { name: /Dismiss/ })).toBeNull();
  });

  it("offers Add by hand inside the menu for an email with a suggestion", async () => {
    held = { matches: [], items: [item({ subject: "Your itinerary", suggestions: [SUGGESTION] })], who: [], ai: false };
    render(ReviewPage);
    const menu = within(await screen.findByTestId("action-menu"));
    await userEvent.click(menu.getByText("More"));
    await userEvent.click(menu.getByRole("button", { name: "Add “Your itinerary” by hand" }));
    expect(await screen.findByRole("dialog", { name: "Add this booking by hand" })).toBeInTheDocument();
  });

  it("closes the menu on Escape and gives focus back to its button, and on a click elsewhere", async () => {
    render(ReviewPage);
    const u = userEvent.setup();
    const menu = await screen.findByTestId("action-menu");
    const summary = within(menu).getByText("More").closest("summary") as HTMLElement;
    await u.click(summary);
    expect(menu).toHaveAttribute("open");
    await u.keyboard("{Escape}");
    expect(menu).not.toHaveAttribute("open");
    expect(summary).toHaveFocus();
    await u.click(summary);
    expect(menu).toHaveAttribute("open");
    await u.click(document.body);
    expect(menu).not.toHaveAttribute("open");
  });

  it("closes the menu when an action in it is chosen, and returns focus to it when the question is cancelled", async () => {
    render(ReviewPage);
    const u = userEvent.setup();
    const menu = await screen.findByTestId("action-menu");
    const summary = within(menu).getByText("More").closest("summary") as HTMLElement;
    await u.click(summary);
    await u.click(within(menu).getByRole("button", { name: /^Dismiss/ }));
    expect(menu).not.toHaveAttribute("open");
    const dialog = await screen.findByRole("dialog");
    await u.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(summary).toHaveFocus());
    expect(calls.filter(([, method]) => method === "DELETE")).toEqual([]);
  });

  it("keeps the warning about where the text goes beside the button that sends it", async () => {
    held = { matches: [], items: many(2, () => false), who: [], ai: true };
    render(ReviewPage);
    const ask = await screen.findByTestId("ask-all");
    expect(within(ask).getByRole("button", { name: "Ask AI about all 2" })).toBeInTheDocument();
    expect(ask).toHaveTextContent("OpenRouter, redacted first");
    expect(screen.getByRole("list", { name: "Add missing details" })).toBeInTheDocument();
  });

  it("handles a six-item queue: counts in the headings, jump links, one primary step per row", async () => {
    held = { matches: [held_match()], items: many(4, (i) => i < 2), who: [who()], ai: false };
    render(ReviewPage);
    const jump = await screen.findByRole("navigation", { name: "Jump to a group" });
    expect(within(jump).getAllByRole("button").map((b) => b.textContent?.replace(/\s+/g, " ").trim())).toEqual(["Check suggestions 2", "Add missing details 2", "Match bookings 1", "Match people 1"]);
    expect(screen.getAllByTestId("review-item")).toHaveLength(4);
    const u = userEvent.setup();
    await u.click(within(jump).getByRole("button", { name: /Match people/ }));
    expect(screen.getByRole("heading", { name: /Match people/ })).toHaveFocus();
  });

  it("handles a fifty-item queue: every row is there under its group, each with one primary step", async () => {
    held = { matches: [], items: many(50, (i) => i % 5 === 0), who: [], ai: true };
    render(ReviewPage);
    const rows = await screen.findAllByTestId("review-item");
    expect(rows).toHaveLength(50);
    expect(screen.getByRole("heading", { name: /Check suggestions/ })).toHaveTextContent("10");
    expect(screen.getByRole("heading", { name: /Add missing details/ })).toHaveTextContent("40");
    expect(screen.getByRole("button", { name: "Ask AI about all 40" })).toBeInTheDocument();
    for (const row of rows) {
      const primary = within(row).getAllByRole("button").filter((b) => /^(Check|Add by hand)/.test(b.textContent ?? "") && /(^| )bg-primary( |$)/.test(b.className));
      expect(primary).toHaveLength(1);
    }
  });

  it("keeps the filter note and the bulk-ask scoping from a sender link", async () => {
    held = { matches: [], items: many(6, () => false), who: [], ai: true };
    setQuery("sender=sender1.example");
    render(ReviewPage);
    expect(await screen.findByTestId("review-filter")).toHaveTextContent("Showing only mail from sender1.example");
    expect(screen.getByRole("button", { name: "Ask AI about these 2 emails" })).toBeInTheDocument();
    expect(screen.getAllByTestId("review-item")).toHaveLength(2);
  });
});

describe("Review's sheet on a wide screen", () => {
  beforeEach(() => { viewport.split = true; });
  afterEach(() => { viewport.split = false; });

  it("shows the email beside the form, with no Hide the email button", async () => {
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Add .* by hand/ }));
    const sheet = await screen.findByRole("dialog");
    expect(sheet).toHaveAttribute("data-split");
    expect(await within(sheet).findByText(/Your flight EX 410/)).toBeVisible();
    expect(within(sheet).queryByRole("button", { name: "Hide the email" })).toBeNull();
    expect(within(sheet).getByLabelText("Confirmation code")).toBeVisible();
  });

  it("is not split below that width, and the email can be hidden there", async () => {
    viewport.split = false;
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Add .* by hand/ }));
    const sheet = await screen.findByRole("dialog");
    await userEvent.click(within(sheet).getByRole("button", { name: "Hide the email" }));
    expect(within(sheet).getByText(/Your flight EX 410/)).not.toBeVisible();
  });
});

describe("Review's sheet on a phone", () => {
  beforeEach(() => { viewport.phone = true; });
  afterEach(() => { viewport.phone = false; });

  it("starts a hand entry on the email, and a suggestion on the booking", async () => {
    held = { matches: [], items: [item({ id: 1, subject: "By hand" }), item({ id: 2, subject: "Suggested", suggestions: [SUGGESTION] })], who: [], ai: false };
    render(ReviewPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Add “By hand” by hand" }));
    let sheet = await screen.findByRole("dialog");
    expect(within(sheet).getByRole("button", { name: "Email" })).toHaveAttribute("aria-pressed", "true");
    await u.click(within(sheet).getByRole("button", { name: "Cancel" }));
    await settled();
    await u.click(screen.getByRole("button", { name: /Check the AI’s suggestion/ }));
    sheet = await screen.findByRole("dialog");
    expect(within(sheet).getByRole("button", { name: "Booking" })).toHaveAttribute("aria-pressed", "true");
    expect(within(sheet).getByLabelText("Confirmation code")).toBeVisible();
  });

  it("saves from the email pane too, by showing the booking fields it needs first", async () => {
    held = { matches: [], items: [item({ id: 1, suggestions: [SUGGESTION] })], who: [], ai: false };
    render(ReviewPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: /Check the AI’s suggestion/ }));
    const sheet = await screen.findByRole("dialog");
    await u.click(within(sheet).getByRole("button", { name: "Email" }));
    expect(within(sheet).getByTestId("booking-fields")).not.toBeVisible();
    await u.click(within(sheet).getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(calls.some(([path]) => path === "/api/segments")).toBe(true));
  });

  it("keeps the save action in a sticky bar at the bottom of the sheet", async () => {
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Add .* by hand/ }));
    const sheet = await screen.findByRole("dialog");
    const bar = within(sheet).getByTestId("form-actions");
    expect(bar).toHaveClass("review-actions");
    expect(within(bar).getByRole("button", { name: "Add to my trips" })).toBeInTheDocument();
    expect(within(bar).getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });
});
