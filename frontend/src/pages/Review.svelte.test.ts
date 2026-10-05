// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { Person, Review, ReviewItem, WhoIsThis } from "$lib/api-types";
import { toast } from "svelte-sonner";
import ReviewPage, { providerFrom, REASONS } from "./Review.svelte";

const item = (extra: Partial<ReviewItem> = {}): ReviewItem => ({
  id: 1, address: "ana@gmail.example", sender_domain: "example-air.example", received: "2026-10-17",
  reason: "no_markup", gmail_url: "https://mail.google.com/mail/u/ana@gmail.example/#all/abc", ...extra });
const who = (extra: Partial<WhoIsThis> = {}): WhoIsThis => ({
  id: 7, name: "DOE/MIA MISS", segment_id: 3, trip_id: 2, kind: "flight", provider: "Example Air", origin: "JFK", destination: "SFO",
  start_local: "2026-12-08T08:00", start_zone: "America/New_York", ...extra });
const mia: Person = { id: 2, display_name: "Mia Doe", first_name: null, legal_name: null, aliases: [], member: false };
const jane: Person = { id: 1, display_name: "Jane Doe", first_name: null, legal_name: null, aliases: [], member: true };

/** The server, with what's waiting kept in `held`: answers the calls the page makes. */
let held: Review;
let calls: [string, string | undefined, unknown][];
function serve(failOn?: string) {
  vi.mocked(api).mockImplementation(async (path: string, opts?: { method?: string; body?: unknown }) => {
    calls.push([path, opts?.method, opts?.body]);
    if (failOn && path.startsWith(failOn)) throw new Error("Refused.");
    if (path === "/api/people") return { people: [jane, mia] } as never;
    if (path === "/api/review") return held as never;
    if (path === "/api/state") return {} as never;
    if (path === "/api/segments") return {} as never;
    if (opts?.method === "DELETE" || path.endsWith("/ignore")) { const id = Number(path.split("/")[3]); held = { ...held, items: held.items.filter((i) => i.id !== id) }; return { ok: true } as never; }
    if (path.startsWith("/api/review/who/")) { const id = Number(path.split("/")[4]); held = { ...held, who: held.who.filter((w) => w.id !== id) }; return { ok: true, matched: 2 } as never; }
    throw new Error(`unexpected ${path}`);
  });
}

beforeEach(() => { vi.mocked(api).mockReset(); vi.mocked(toast.success).mockReset(); vi.mocked(toast.error).mockReset(); calls = []; held = { items: [item()], who: [who()] }; serve(); });

describe("Review", () => {
  it("lists mail Waypoint couldn’t read, with who it came from and why, and never any text", async () => {
    render(ReviewPage);
    const list = await screen.findByRole("list", { name: "Couldn’t read" });
    expect(within(list).getByText("example-air.example")).toBeInTheDocument();
    expect(within(list).getByText("Mail from example-air.example on 2026-10-17")).toBeInTheDocument();
    expect(within(list).getByText("Sent 2026-10-17 · to ana@gmail.example")).toBeInTheDocument();
    expect(within(list).getByText(REASONS.no_markup)).toBeInTheDocument();
    const open = within(list).getByRole("link", { name: /Open .Mail from example-air.example on 2026-10-17. in Gmail/ });
    expect(open).toHaveAttribute("href", "https://mail.google.com/mail/u/ana@gmail.example/#all/abc");
    expect(open).toHaveAttribute("rel", "noopener noreferrer");
    expect(open).toHaveAttribute("target", "_blank");
  });

  it("says what it can when the sender or the day isn’t there", async () => {
    held = { items: [item({ id: 1, reason: "broken", sender_domain: "", received: null }), item({ id: 2 })], who: [] };
    render(ReviewPage);
    expect(await screen.findByText("Mail from an unknown sender")).toBeInTheDocument();
    expect(screen.getByText("to ana@gmail.example")).toBeInTheDocument();
    expect(screen.getByText(REASONS.broken)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Ignore/ })).toHaveLength(1);   // nothing to ignore for no sender
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
    expect(calls.some(([p]) => p.endsWith("/ignore"))).toBe(false);   // not until confirmed
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
    await waitFor(() => expect(calls).toContainEqual(["/api/review/1", "DELETE", undefined]));
    expect(toast.success).toHaveBeenCalledWith("Added to your trips");
    expect(screen.queryByRole("form")).toBeNull();
  });

  it("asks for a stay’s time zones, which an airport can’t give", async () => {
    render(ReviewPage);
    await userEvent.click(await screen.findByRole("button", { name: /Add .Mail from example-air.example on 2026-10-17. by hand/ }));
    await userEvent.selectOptions(screen.getByLabelText("What is it?"), "hotel");
    expect(screen.getByLabelText("Hotel")).toBeInTheDocument();
    expect(screen.queryByLabelText("To (airport code)")).toBeNull();
    await userEvent.type(screen.getByLabelText("Hotel"), "Harbour Hotel");
    await userEvent.type(screen.getByLabelText("Check-in"), "2026-11-21T15:00");
    await userEvent.type(screen.getByLabelText("Check-out"), "2026-11-27T10:00");
    await userEvent.type(screen.getByLabelText("Time zone where it starts"), "Europe/London");
    await userEvent.click(screen.getByRole("button", { name: "Add to my trips" }));
    await waitFor(() => expect(calls).toContainEqual(["/api/segments", "POST", expect.objectContaining({
      kind: "hotel", origin: "Harbour Hotel", start_zone: "Europe/London", end_zone: "Europe/London" })]));
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
    await waitFor(() => expect(calls.filter(([p]) => p === "/api/review").length).toBeGreaterThan(1));   // reloaded either way
  });

  it("lists names to match, with the booking each is on, and matches one to a person", async () => {
    render(ReviewPage);
    const list = await screen.findByRole("list", { name: "Who is this?" });
    expect(within(list).getByText("DOE/MIA MISS")).toBeInTheDocument();
    expect(within(list).getByText("Flight JFK → SFO on 2026-12-08 (Example Air)")).toBeInTheDocument();
    const button = within(list).getByRole("button", { name: "Match DOE/MIA MISS" });
    expect(button).toBeDisabled();   // until someone is chosen
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
    expect(button).toBeDisabled();   // until they have a name
    await userEvent.type(within(list).getByLabelText("Name for DOE/MIA MISS"), "Mia Rose Doe");
    await userEvent.click(button);
    await waitFor(() => expect(calls).toContainEqual(["/api/review/who/7", "POST", { new_guest: "Mia Rose Doe" }]));
  });

  it("describes each kind of booking a name is on", async () => {
    held = { items: [], who: [who({ id: 1, kind: "hotel", origin: "Harbour Hotel", destination: null, provider: null }), who({ id: 2, kind: "car", origin: "SFO", destination: "SFO" }),
      who({ id: 3, kind: "train", origin: null, destination: null })] };
    render(ReviewPage);
    expect(await screen.findByText("Stay Harbour Hotel on 2026-12-08")).toBeInTheDocument();
    expect(screen.getByText("Rental SFO → SFO on 2026-12-08 (Example Air)")).toBeInTheDocument();
    expect(screen.getByText("Train on 2026-12-08 (Example Air)")).toBeInTheDocument();
  });

  it("says when nothing is waiting", async () => {
    held = { items: [], who: [] };
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
