// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { LoyaltyEntry, LoyaltyList, Person } from "$lib/api-types";
import { app } from "$lib/app.svelte";
import { state } from "../test/fixtures";
import People from "./People.svelte";

const jane: Person = { id: 1, display_name: "Jane Doe", first_name: "Jane", legal_name: null, aliases: [], member: true, links: [] };
const mia: Person = { id: 2, display_name: "Mia Doe", first_name: "Mia", legal_name: "Mia Rose Doe", aliases: ["DOE/MIA MISS"], member: false, links: [] };

const PROGRAMS = { airline: ["American AAdvantage", "Other"], hotel: ["Marriott Bonvoy", "Other"], car: ["Other"], known_traveler: ["TSA PreCheck", "Other"], redress: ["DHS TRIP", "Other"] };
const aa: LoyaltyEntry = { id: 11, person_id: 1, kind: "airline", program: "American AAdvantage", masked: "••••4567", readable: true, expiry: null, notes: null };
const tsa: LoyaltyEntry = { id: 12, person_id: 1, kind: "known_traveler", program: "TSA PreCheck", masked: "••••2345", readable: true, expiry: "2029-03-31", notes: null };

/** The server, with its people kept in `held` and their memberships in `ids`: answers the calls the page makes. */
let held: Person[];
let ids: LoyaltyEntry[];
let conflicts: LoyaltyList["conflicts"];
function serve() {
  vi.mocked(api).mockImplementation(async (path, opts) => {
    if (path === "/api/loyalty" && !opts) return { loyalty: ids, programs: PROGRAMS, conflicts };
    if (path.startsWith("/api/loyalty")) {
      const id = Number(path.split("/")[3]);
      if (path.endsWith("/reveal")) return { number: "DEMO1234567" };
      if (opts?.method === "DELETE") { ids = ids.filter((m) => m.id !== id); return { ok: true }; }
      const b = opts?.body as { person_id: number; kind: string; program: string; number?: string; expiry: string; notes: string };
      const next: LoyaltyEntry = { id: id || 20, person_id: b.person_id, kind: b.kind, program: b.program, masked: b.number ? `••••${b.number.slice(-4)}` : ids.find((m) => m.id === id)?.masked ?? "••••",
        readable: true, expiry: b.expiry || null, notes: b.notes || null };
      ids = id ? ids.map((m) => (m.id === id ? next : m)) : [...ids, next];
      return next;
    }
    const id = Number(path.split("/")[3]);
    if (path.endsWith("/claim")) {   // the signed-in member (Jane) takes the guest
      const guest = held.find((p) => p.id === id)!;
      held = held.filter((p) => p.id !== id).map((p) => (p.id === 1 ? { ...p, links: [{ guest: guest.display_name, by: p.display_name, on: "2026-10-05" }] } : p));
      return held[0];
    }
    if (opts?.method === "DELETE") { held = held.filter((p) => p.id !== id); return { ok: true }; }
    if (opts?.method === "POST") {
      const b = opts.body as { display_name: string; first_name: string; legal_name: string; aliases: string[] };
      const next: Person = { id: id || 9, display_name: b.display_name, first_name: b.first_name || null, legal_name: b.legal_name || null,
        aliases: b.aliases.filter(Boolean), member: held.find((p) => p.id === id)?.member ?? false, links: [] };
      held = id ? held.map((p) => (p.id === id ? next : p)) : [...held, next];
      return next;
    }
    return { people: held };
  });
}

beforeEach(() => { vi.mocked(api).mockReset(); held = [jane, mia]; ids = [aa, tsa]; conflicts = []; app.state = state(); serve(); });

describe("People", () => {
  it("lists members and guests, with the names an airline matches", async () => {
    render(People);
    const list = await screen.findByRole("list", { name: "People" });
    expect(within(list).getByText("Member")).toBeInTheDocument();
    expect(within(list).getByText("Guest")).toBeInTheDocument();
    expect(within(list).getByText(/Legal name Mia Rose Doe · Printed as DOE\/MIA MISS/)).toBeInTheDocument();
  });

  it("offers Remove for a guest but never for a member", async () => {
    render(People);
    await screen.findByRole("list", { name: "People" });
    expect(screen.getByRole("button", { name: "Remove Mia Doe" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove Jane Doe" })).toBeNull();
    expect(screen.getByRole("button", { name: "Edit Jane Doe" })).toBeInTheDocument();
  });

  it("offers This is me on a guest to a signed-in member, never on a member, and not without sign-in", async () => {
    render(People);
    await screen.findByRole("list", { name: "People" });
    expect(screen.getByRole("button", { name: "This is me: Mia Doe" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "This is me: Jane Doe" })).toBeNull();
  });

  it("hides This is me on your own machine, where nobody signs in", async () => {
    app.state = state({ user: { name: null, email: null, local: true } });
    render(People);
    await screen.findByRole("list", { name: "People" });
    expect(screen.queryByRole("button", { name: /This is me/ })).toBeNull();
  });

  it("says it can't be undone, links the guest once confirmed and shows the link", async () => {
    render(People);
    await userEvent.click(await screen.findByRole("button", { name: "This is me: Mia Doe" }));
    const dialog = await screen.findByRole("dialog", { name: "Link Mia Doe to you?" });
    expect(dialog).toHaveTextContent(/can’t be undone in Waypoint: restoring a backup is the way back/);
    await userEvent.click(within(dialog).getByRole("button", { name: "This is me" }));
    expect(api).toHaveBeenCalledWith("/api/people/2/claim", { method: "POST" });
    expect(await screen.findByText("Linked from guest Mia Doe by Jane Doe on 2026-10-05")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /This is me/ })).toBeNull();
  });

  it("Cancel keeps the guest unlinked", async () => {
    render(People);
    await userEvent.click(await screen.findByRole("button", { name: "This is me: Mia Doe" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(api).not.toHaveBeenCalledWith("/api/people/2/claim", expect.anything());
  });

  it("flags two numbers for one program rather than picking one", async () => {
    conflicts = [{ person_id: 1, kind: "airline", program: "American AAdvantage" }];
    render(People);
    expect(await screen.findByText(/Two numbers for American AAdvantage/)).toBeInTheDocument();
  });

  it("adds a guest, with its aliases one to a line", async () => {
    render(People);
    await userEvent.click(await screen.findByRole("button", { name: /Add a guest/ }));
    await userEvent.type(screen.getByLabelText("Name"), "Grandpa Joe");
    await userEvent.type(screen.getByLabelText(/Name aliases/), "OHARE/JOE MR{Enter}O HARE/JOE MR");
    await userEvent.click(screen.getByRole("button", { name: "Add guest" }));
    expect(api).toHaveBeenCalledWith("/api/people", { method: "POST", body: { display_name: "Grandpa Joe", first_name: "", legal_name: "", aliases: ["OHARE/JOE MR", "O HARE/JOE MR"] } });
    expect(await screen.findByText("Grandpa Joe")).toBeInTheDocument();
    expect(screen.queryByRole("form")).toBeNull();
  });

  it("edits a member without offering their login", async () => {
    render(People);
    await userEvent.click(await screen.findByRole("button", { name: "Edit Jane Doe" }));
    expect(screen.getByText(/link to their sign-in stays as it is/)).toBeInTheDocument();
    const name = screen.getByLabelText("Name");
    await userEvent.clear(name);
    await userEvent.type(name, "Janie");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(api).toHaveBeenCalledWith("/api/people/1", expect.objectContaining({ method: "POST" }));
    expect(await screen.findByText("Janie")).toBeInTheDocument();
  });

  it("keeps the form open and says why when saving fails", async () => {
    render(People);
    await userEvent.click(await screen.findByRole("button", { name: /Add a guest/ }));
    vi.mocked(api).mockRejectedValueOnce(new Error("Enter the name"));
    await userEvent.type(screen.getByLabelText("Name"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Add guest" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter the name");
    expect(screen.getByLabelText("Name")).toHaveValue("x");
  });

  it("asks before removing a guest, and Cancel keeps them", async () => {
    render(People);
    await userEvent.click(await screen.findByRole("button", { name: "Remove Mia Doe" }));
    const dialog = await screen.findByRole("dialog", { name: "Remove Mia Doe?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(api).not.toHaveBeenCalledWith("/api/people/2", expect.anything());
    expect(screen.getByText("Mia Doe")).toBeInTheDocument();
  });

  it("removes a guest once confirmed", async () => {
    render(People);
    await userEvent.click(await screen.findByRole("button", { name: "Remove Mia Doe" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Remove" }));
    expect(api).toHaveBeenCalledWith("/api/people/2", { method: "DELETE" });
    await waitFor(() => expect(screen.queryByText("Mia Doe")).toBeNull());
  });

  it("shows nothing that could pass for current when it can't load, and tries again", async () => {
    vi.mocked(api).mockRejectedValueOnce(new Error("Can’t reach Waypoint."));
    render(People);
    expect(await screen.findByText("Can’t reach Waypoint.")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "People" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Add a guest/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("list", { name: "People" })).toBeInTheDocument();
  });

  it("says so when there is nobody yet", async () => {
    held = [];
    render(People);
    expect(await screen.findByText(/Nobody yet/)).toBeInTheDocument();
  });

  it("shows each person's memberships grouped by kind, with the number masked", async () => {
    render(People);
    const airline = await screen.findByRole("region", { name: "Jane Doe’s Airline memberships" });
    expect(within(airline).getByText("American AAdvantage")).toBeInTheDocument();
    expect(within(airline).getByText("••••4567")).toBeInTheDocument();
    const kt = screen.getByRole("region", { name: "Jane Doe’s Known Traveler memberships" });
    expect(within(kt).getByText("Expires 2029-03-31")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /Mia Doe/ })).toBeNull();
    expect(screen.queryByText(/DEMO1234567/)).toBeNull();   // no number came with the page
  });

  it("reveals one number on tap, copies it, and hides it on a second tap", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    render(People);
    await userEvent.click(await screen.findByRole("button", { name: "Show and copy American AAdvantage number" }));
    expect(api).toHaveBeenCalledWith("/api/loyalty/11/reveal", { method: "POST" });
    expect(await screen.findByText("DEMO1234567")).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith("DEMO1234567");
    expect(screen.getByText("••••2345")).toBeInTheDocument();   // the other stays masked
    await userEvent.click(screen.getByRole("button", { name: "Hide American AAdvantage number" }));
    expect(screen.queryByText("DEMO1234567")).toBeNull();
    vi.unstubAllGlobals();
  });

  it("still shows the number when it can't be copied", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) } });
    render(People);
    await userEvent.click(await screen.findByRole("button", { name: "Show and copy American AAdvantage number" }));
    expect(await screen.findByText("DEMO1234567")).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("says so when a number can't be read with this key", async () => {
    ids = [{ ...aa, masked: "••••", readable: false }];
    render(People);
    expect(await screen.findByText(/Can’t be read with this key/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Show and copy/ })).toBeNull();
  });

  it("adds a membership for a person, choosing the program from the kind's list", async () => {
    render(People);
    await userEvent.click(await screen.findByRole("button", { name: "Add a membership for Mia Doe" }));
    await userEvent.selectOptions(screen.getByLabelText("Kind"), "hotel");
    expect(screen.getByLabelText("Program")).toHaveValue("Marriott Bonvoy");
    await userEvent.type(screen.getByLabelText("Number"), "DEMO55501234");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(api).toHaveBeenCalledWith("/api/loyalty", { method: "POST", body: { person_id: 2, kind: "hotel", program: "Marriott Bonvoy", number: "DEMO55501234", expiry: "", notes: "" } });
    expect(await screen.findByRole("region", { name: "Mia Doe’s Hotel memberships" })).toBeInTheDocument();
    expect(screen.queryByRole("form")).toBeNull();
  });

  it("doesn't offer a program the person already has, keeps Other, and keeps a membership's own program when editing it", async () => {
    render(People);
    await userEvent.click(await screen.findByRole("button", { name: "Add a membership for Jane Doe" }));
    const program = screen.getByLabelText(/^Program/);
    expect(within(program).queryByRole("option", { name: "American AAdvantage" })).toBeNull();   // (Jane has it)
    expect(within(program).getByRole("option", { name: "Other" })).toBeInTheDocument();
    expect(program).toHaveValue("Other");                                                         // (the first one left)
    await userEvent.selectOptions(screen.getByLabelText("Kind"), "hotel");
    expect(within(screen.getByLabelText(/^Program/)).getByRole("option", { name: "Marriott Bonvoy" })).toBeInTheDocument();   // (not hers)
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button", { name: "Edit Jane Doe’s American AAdvantage" }));
    expect(screen.getByLabelText(/^Program/)).toHaveValue("American AAdvantage");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button", { name: "Add a membership for Mia Doe" }));
    expect(within(screen.getByLabelText(/^Program/)).getByRole("option", { name: "American AAdvantage" })).toBeInTheDocument();   // (Mia doesn't)
  });

  it("has no Tier, and offers an expiry only for Known Traveler and redress numbers", async () => {
    render(People);
    await userEvent.click(await screen.findByRole("button", { name: "Add a membership for Mia Doe" }));
    expect(screen.queryByLabelText("Tier")).toBeNull();
    for (const kind of ["airline", "hotel", "car"]) {
      await userEvent.selectOptions(screen.getByLabelText("Kind"), kind);
      expect(screen.queryByLabelText("Expiry")).toBeNull();
    }
    for (const kind of ["known_traveler", "redress"]) {
      await userEvent.selectOptions(screen.getByLabelText("Kind"), kind);
      expect(screen.getByLabelText("Expiry")).toBeInTheDocument();
    }
  });

  it("changes a membership without asking for the number again", async () => {
    render(People);
    await userEvent.click(await screen.findByRole("button", { name: "Edit Jane Doe’s American AAdvantage" }));
    expect(screen.getByLabelText("Number")).toHaveAttribute("placeholder", "Leave empty to keep ••••4567");
    await userEvent.type(screen.getByLabelText("Notes"), "Platinum");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(api).toHaveBeenCalledWith("/api/loyalty/11", expect.objectContaining({ method: "POST", body: expect.objectContaining({ number: "", notes: "Platinum" }) }));
    expect(await screen.findByText("Platinum")).toBeInTheDocument();
  });

  it("keeps the membership form open and says why when saving fails", async () => {
    render(People);
    await userEvent.click(await screen.findByRole("button", { name: "Add a membership for Jane Doe" }));
    vi.mocked(api).mockRejectedValueOnce(new Error("The number is too long (at most 64 characters)"));
    await userEvent.type(screen.getByLabelText("Number"), "DEMO1");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("too long");
    expect(screen.getByLabelText("Number")).toHaveValue("DEMO1");
  });

  it("asks before removing a membership", async () => {
    render(People);
    await userEvent.click(await screen.findByRole("button", { name: "Remove Jane Doe’s TSA PreCheck" }));
    const dialog = await screen.findByRole("dialog", { name: "Remove TSA PreCheck?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
    expect(api).toHaveBeenCalledWith("/api/loyalty/12", { method: "DELETE" });
    await waitFor(() => expect(screen.queryByRole("region", { name: "Jane Doe’s Known Traveler memberships" })).toBeNull());
  });

  it("shows nothing that could pass for current when the memberships can't load", async () => {
    vi.mocked(api).mockImplementation(async (path) => { if (path === "/api/loyalty") throw new Error("Can’t reach Waypoint."); return { people: held }; });
    render(People);
    expect(await screen.findByText("Can’t reach Waypoint.")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "People" })).toBeNull();
  });
});
