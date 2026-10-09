// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { Person, Review, ReviewItem, ReviewMatch, WhoIsThis } from "$lib/api-types";
import { viewport } from "$lib/phone.svelte";
import { toast } from "svelte-sonner";
import ReviewPage, { providerFrom, REASONS } from "./Review.svelte";

const item = (extra: Partial<ReviewItem> = {}): ReviewItem => ({
  id: 1, address: "ana@gmail.example", owner: "Ana Doe", mine: true, sender_domain: "example-air.example", subject: null, has_email: true, received: "2026-10-17",
  reason: "no_markup", gmail_url: "https://mail.google.com/mail/?authuser=ana%40gmail.example#all/abc", suggestion: null, suggestion_error: null, ...extra });
const who = (extra: Partial<WhoIsThis> = {}): WhoIsThis => ({
  id: 7, name: "DOE/MIA MISS", segment_id: 3, trip_id: 2, kind: "flight", provider: "Example Air", origin: "JFK", destination: "SFO",
  start_local: "2026-12-08T08:00", start_zone: "America/New_York", ...extra });
const candidate = (extra: Partial<ReviewMatch["candidates"][number]> = {}): ReviewMatch["candidates"][number] => ({
  segment_id: 11, trip_id: 4, trip_name: "Trip to London", kind: "hotel", provider: null, origin: "Harbour Hotel", destination: null,
  start_local: "2026-11-21T15:00", end_local: "2026-11-27T10:00", ...extra });
const held_match = (extra: Partial<ReviewMatch> = {}): ReviewMatch => ({
  item_id: 9, index: 0, subject: "Your stay: Harbour Hotel", received: "2026-10-18", mine: true,
  booking: { kind: "hotel", provider: "Example Hotels", confirmation: "H88231", origin: "Harbour Hotel", destination: null, start_local: "2026-11-21T15:00", end_local: "2026-11-27T10:00" },
  candidates: [candidate(), candidate({ segment_id: 12, trip_id: 5, trip_name: "Second trip" })], ...extra });
const mia: Person = { id: 2, display_name: "Mia Doe", first_name: null, legal_name: null, aliases: [], member: false, links: [] };
const jane: Person = { id: 1, display_name: "Jane Doe", first_name: null, legal_name: null, aliases: [], member: true, links: [] };

const SUGGESTION = { kind: "flight" as const, provider: "Example Air", confirmation: "QW4R7T", origin: "BOS", destination: "DEN",
  start_local: "2026-12-02T07:15", end_local: "2026-12-02T10:05" } as unknown as NonNullable<ReviewItem["suggestion"]>;
const PREVIEW = "Hello Jane,\nYour flight EX 410 leaves Boston at 7:15 am on 2 January.";
let previewFails = "";
let suggestFails = "";
let suggestGate: Promise<void> | null = null;
let truncated = false;
let held: Review;
let calls: [string, string | undefined, unknown][];
function serve(failOn?: string) {
  vi.mocked(api).mockImplementation(async (path: string, opts?: { method?: string; body?: unknown }) => {
    calls.push([path, opts?.method, opts?.body]);
    if (failOn && path.startsWith(failOn)) throw new Error("Refused.");
    if (path === "/api/people") return { people: [jane, mia] } as never;
    if (path === "/api/review") return held as never;
    if (path === "/api/state") return {} as never;
    if (path === "/api/segments") return { id: 42 } as never;
    if (path.endsWith("/preview")) { if (previewFails) throw new Error(previewFails); return { text: PREVIEW, html: null, truncated } as never; }
    if (path.endsWith("/suggest")) { if (suggestGate) await suggestGate; if (suggestFails) throw new Error(suggestFails); held = { ...held, items: held.items.map((i) => ({ ...i, suggestion: SUGGESTION })) }; return { ok: true } as never; }
    if (opts?.method === "DELETE" || path.endsWith("/ignore")) { const id = Number(path.split("/")[3]?.split("?")[0]); held = { ...held, items: held.items.filter((i) => i.id !== id), matches: held.matches.filter((m) => m.item_id !== id) }; return { ok: true } as never; }
    if (path.endsWith("/match")) { const id = Number(path.split("/")[3]); held = { ...held, matches: held.matches.filter((m) => m.item_id !== id) }; return { ok: true } as never; }
    if (path.startsWith("/api/review/who/")) { const id = Number(path.split("/")[4]); held = { ...held, who: held.who.filter((w) => w.id !== id) }; return { ok: true, matched: 2 } as never; }
    throw new Error(`unexpected ${path}`);
  });
}

beforeEach(() => { vi.mocked(api).mockReset(); vi.mocked(toast.success).mockReset(); vi.mocked(toast.error).mockReset(); calls = []; previewFails = suggestFails = ""; suggestGate = null; truncated = false; held = { matches: [], items: [item()], who: [who()], ai: false }; serve(); });

describe("Review", () => {
  it("lists mail Waypoint couldn’t read, with who it came from and why, and never any text", async () => {
    render(ReviewPage);
    const list = await screen.findByRole("list", { name: "Couldn’t read" });
    expect(within(list).getByText("Mail from example-air.example on 2026-10-17")).toBeInTheDocument();
    expect(within(list).getByText("Sent 2026-10-17 · to ana@gmail.example")).toBeInTheDocument();
    expect(within(list).getByText(REASONS.no_markup)).toBeInTheDocument();
    const open = within(list).getByRole("link", { name: /Open .Mail from example-air.example on 2026-10-17. in Gmail/ });
    expect(open).toHaveAttribute("href", "https://mail.google.com/mail/?authuser=ana%40gmail.example#all/abc");
    expect(open).toHaveAttribute("rel", "noopener noreferrer");
    expect(open).toHaveAttribute("target", "_blank");
  });

  it("names an item by its message's subject, and says who it came from beside it", async () => {
    held = { matches: [], items: [item({ subject: "Your itinerary: EX 410" })], who: [], ai: false };
    render(ReviewPage);
    const list = await screen.findByRole("list", { name: "Couldn’t read" });
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
    expect(screen.getAllByRole("button", { name: /Ignore/ })).toHaveLength(1);
  });

  it("shows an item shared by another member with whose mailbox it is, and only Add by hand and Dismiss", async () => {
    held = { matches: [], items: [item({ id: 4, mine: false, owner: "Sam Doe", gmail_url: null, address: "sam@gmail.example" })], who: [], ai: true };
    render(ReviewPage);
    const row = await screen.findByTestId("review-item");
    expect(row).toHaveTextContent("in Sam Doe’s mailbox, shared with the household");
    expect(row).not.toHaveTextContent("sam@gmail.example");
    expect(within(row).getByRole("button", { name: /Add .Mail from example-air.example.* by hand/ })).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: /Dismiss/ })).toBeInTheDocument();
    for (const name of [/Open .* in Gmail/, /Ask AI about/, /Ignore example-air.example/]) expect(within(row).queryByRole("button", { name }) ?? within(row).queryByRole("link", { name })).toBeNull();
    expect(screen.queryByRole("button", { name: /Ask AI about all/ })).toBeNull();
  });

  it("opens a shared item's message beside the form like any other, and dismisses it", async () => {
    held = { matches: [], items: [item({ id: 4, mine: false, owner: "Sam Doe", gmail_url: null }), item({ id: 5, mine: true })], who: [], ai: false };
    render(ReviewPage);
    const row = (await screen.findAllByTestId("review-item"))[0];
    await userEvent.click(within(row).getByRole("button", { name: /by hand/ }));
    expect(await screen.findByLabelText(/Confirmation/)).toBeInTheDocument();
    expect(calls).toContainEqual(["/api/review/4/preview", undefined, undefined]);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.click(within(row).getByRole("button", { name: /Dismiss/ }));
    await waitFor(() => expect(calls).toContainEqual(["/api/review/4", "DELETE", undefined]));
  });

  it("dismisses an item", async () => {
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Dismiss .Mail from example-air.example/ }));
    await waitFor(() => expect(calls).toContainEqual(["/api/review/1", "DELETE", undefined]));
    expect(toast.success).toHaveBeenCalledWith("Dismissed");
    await waitFor(() => expect(screen.queryByTestId("review-item")).toBeNull());
  });

  it("ignores a sender only after asking", async () => {
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: "Ignore example-air.example" }));
    expect(await screen.findByText("Ignore example-air.example?")).toBeInTheDocument();
    expect(calls.some(([p]) => p.endsWith("/ignore"))).toBe(false);
    await userEvent.click((await screen.findByRole("dialog")).querySelector("button[type=submit]")!);
    await waitFor(() => expect(calls).toContainEqual(["/api/review/1/ignore", "POST", undefined]));
    expect(toast.success).toHaveBeenCalledWith("Ignoring example-air.example");
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
    expect(screen.getByText(/time zones come from its airports/)).toBeInTheDocument();
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
    await userEvent.type(screen.getByLabelText(/^Time zone/), "Europe/London");
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(calls).toContainEqual(["/api/segments", "POST", expect.objectContaining({
      kind: "hotel", origin: "Harbour Hotel", start_zone: "Europe/London" })]));
    expect(calls.find(([p]) => p === "/api/segments")?.[2]).not.toHaveProperty("end_zone");
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
    expect(screen.queryByRole("form")).toBeNull();
  });

  it("says when a booking was added but its item couldn’t be taken off the list", async () => {
    serve("/api/review/1");
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
    const list = await screen.findByRole("list", { name: "Who is this?" });
    expect(within(list).getByText("DOE/MIA MISS")).toBeInTheDocument();
    expect(within(list).getByText("Flight JFK → SFO on 2026-12-08 (Example Air)")).toBeInTheDocument();
    const button = within(list).getByRole("button", { name: "Match DOE/MIA MISS" });
    expect(button).toBeDisabled();
    await userEvent.selectOptions(within(list).getByLabelText("Who is DOE/MIA MISS?"), "Mia Doe");
    await userEvent.click(button);
    await waitFor(() => expect(calls).toContainEqual(["/api/review/who/7", "POST", { person_id: 2 }]));
    expect(toast.success).toHaveBeenCalledWith("Matched on 2 bookings");
    await waitFor(() => expect(screen.queryByRole("list", { name: "Who is this?" })).toBeNull());
  });

  it("adds a guest for a name nobody is", async () => {
    render(ReviewPage);
    const list = await screen.findByRole("list", { name: "Who is this?" });
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
    const list = await screen.findByRole("list", { name: "Could be one of your bookings" });
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
    await waitFor(() => expect(calls).toContainEqual(["/api/review/9/match", "POST", { index: 0, segment_id: 12 }]));
    expect(toast.success).toHaveBeenCalledWith("Filled in");
    expect(await screen.findByText(/Nothing to review/)).toBeInTheDocument();
  });

  it("adds it as a booking of its own, or dismisses it", async () => {
    held = { matches: [held_match(), held_match({ item_id: 10 })], items: [], who: [], ai: false };
    render(ReviewPage);
    await userEvent.click((await screen.findAllByRole("button", { name: "It’s a new booking" }))[0]);
    await waitFor(() => expect(calls).toContainEqual(["/api/review/9/match", "POST", { index: 0, segment_id: null }]));
    expect(toast.success).toHaveBeenCalledWith("Added to your trips");
    await userEvent.click(await screen.findByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(calls).toContainEqual(["/api/review/10", "DELETE", undefined]));
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
    expect(await screen.findByRole("list", { name: "Couldn’t read" })).toBeInTheDocument();
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
    held = { matches: [], items: [item({ suggestion })], who: [], ai: false };
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

  it("opens a cruise suggestion with its port labels and saves its ports and zones", async () => {
    const cruise = { kind: "cruise" as const, provider: "Example Cruise Line", confirmation: "QW4R7T", origin: "Miami", destination: "Nassau",
      start_local: "2026-12-02T16:00", end_local: "2026-12-09T07:00", start_zone: "America/New_York", end_zone: "America/Nassau" };
    held = { matches: [], items: [item({ suggestion: cruise })], who: [], ai: false };
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

  it("shows a message's HTML as formatted text, with a switch to its plain text and back", async () => {
    vi.mocked(api).mockImplementation(async (path: string) => (path.endsWith("/preview")
      ? { text: "Gate B12", html: "<p>Gate <b>B12</b></p><table><tr><td>Seat</td><td>12A</td></tr></table>", truncated: false }
      : path === "/api/people" ? { people: [] } : held) as never);
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /by hand/ }));
    const formatted = await screen.findByTestId("preview-html");
    expect(formatted.querySelector("b")).toHaveTextContent("B12");
    expect(formatted.querySelector("td")).toHaveTextContent("Seat");
    await userEvent.click(screen.getByRole("button", { name: "Show as plain text" }));
    expect(screen.queryByTestId("preview-html")).toBeNull();
    expect(screen.getByTestId("preview")).toHaveTextContent("Gate B12");
    await userEvent.click(screen.getByRole("button", { name: "Show as formatted" }));
    expect(await screen.findByTestId("preview-html")).toBeInTheDocument();
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
    expect(await screen.findByText(/Cut short here/)).toBeInTheDocument();
  });

  it("says why it couldn’t be fetched, and tries again when asked again", async () => {
    previewFails = "That message is no longer in Gmail.";
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /by hand/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That message is no longer in Gmail.");
    previewFails = "";
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
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
    held = { matches: [], items: [item(), item({ id: 2 }), item({ id: 3, suggestion: null })], who: [], ai: true };
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: "Ask AI about all 3" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Asked the AI about 3 messages"));
    expect(calls.filter((c) => c[0].endsWith("/suggest")).map((c) => c[0])).toEqual(["/api/review/1/suggest", "/api/review/2/suggest", "/api/review/3/suggest"]);
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

describe("Review on a phone", () => {
  beforeEach(() => { viewport.phone = true; });
  afterEach(() => { viewport.phone = false; });

  it("opens Add by hand in a sheet with the message above the form, and Cancel closes it", async () => {
    render(ReviewPage);
    const u = userEvent.setup();
    const open = await screen.findByRole("button", { name: /Add .* by hand/ });
    await u.click(open);
    const sheet = await screen.findByRole("dialog", { name: "Add this booking by hand" });
    expect(sheet).toHaveAttribute("data-side", "bottom");
    expect(await within(sheet).findByText(/Your flight EX 410/)).toBeInTheDocument();
    expect(within(sheet).getByLabelText("Provider")).toHaveValue("Example Air");
    expect(within(sheet).getAllByRole("heading", { name: "Add this booking by hand" })).toHaveLength(1);
    expect(screen.queryByTestId("review-item")?.closest("ul")?.querySelector("form")).toBeNull();
    await u.click(within(sheet).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("adds the booking from the sheet and closes it", async () => {
    render(ReviewPage);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: /Add .* by hand/ }));
    const sheet = await screen.findByRole("dialog");
    await u.type(within(sheet).getByLabelText("From (airport code)"), "JFK");
    await u.type(within(sheet).getByLabelText("To (airport code)"), "SFO");
    await u.type(within(sheet).getByLabelText("Departs"), "2026-12-08T08:00");
    await u.type(within(sheet).getByLabelText("Arrives"), "2026-12-08T11:00");
    await u.click(within(sheet).getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(calls.some(([path, method]) => path === "/api/segments" && method === "POST")).toBe(true));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
