// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { LoyaltyEntry, LoyaltyList, Person } from "$lib/api-types";
import { app } from "$lib/app.svelte";
import { viewport } from "$lib/phone.svelte";
import { state } from "../test/fixtures";
import People from "./People.svelte";

const jane: Person = { id: 1, display_name: "Jane Doe", first_name: "Jane", legal_name: null, aliases: [], member: true, links: [] };
const mia: Person = { id: 2, display_name: "Mia Doe", first_name: "Mia", legal_name: "Mia Rose Doe", aliases: ["DOE/MIA MISS"], member: false, links: [] };

const PROGRAMS = { airline: ["American AAdvantage", "Other"], hotel: ["Marriott Bonvoy", "Other"], car: ["Other"], cruise: ["Disney Castaway Club", "Other"], known_traveler: ["TSA PreCheck", "Other"], redress: ["DHS TRIP", "Other"] };
const aa: LoyaltyEntry = { id: 11, person_id: 1, kind: "airline", program: "American AAdvantage", masked: "••••4567", readable: true, expiry: null, notes: null, logo: null };
const tsa: LoyaltyEntry = { id: 12, person_id: 1, kind: "known_traveler", program: "TSA PreCheck", masked: "••••2345", readable: true, expiry: "2029-03-31", notes: null, logo: null };

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
        readable: true, expiry: b.expiry || null, notes: b.notes || null, logo: null };
      ids = id ? ids.map((m) => (m.id === id ? next : m)) : [...ids, next];
      return next;
    }
    const id = Number(path.split("/")[3]);
    if (path.endsWith("/claim")) {
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

  it("shows a logo beside every kind of program that has one, decoratively, and a monogram in its space for a row without", async () => {
    const delta: LoyaltyEntry = { ...aa, id: 13, program: "Delta SkyMiles", logo: "/api/loyalty/13/logo" };
    const other: LoyaltyEntry = { ...aa, id: 14, program: "Other" };
    const marriott: LoyaltyEntry = { ...aa, id: 15, kind: "hotel", program: "Marriott Bonvoy", logo: "/api/loyalty/15/logo" };
    const hertz: LoyaltyEntry = { ...aa, id: 16, kind: "car", program: "Hertz Gold Plus Rewards", logo: "/api/loyalty/16/logo" };
    const disney: LoyaltyEntry = { ...aa, id: 17, kind: "cruise", program: "Disney Castaway Club", logo: "/api/loyalty/17/logo" };
    const global: LoyaltyEntry = { ...tsa, id: 18, program: "Global Entry" };
    ids = [{ ...aa, logo: "/api/loyalty/11/logo" }, delta, other, marriott, hertz, disney, { ...tsa, logo: "/api/loyalty/12/logo" }, global];
    const { container } = render(People);
    await screen.findByRole("list", { name: "People" });
    const rows = (name: string) => screen.getByText(name).closest("li") as HTMLElement;
    const logos: Record<string, number> = { "American AAdvantage": 11, "Delta SkyMiles": 13, "Marriott Bonvoy": 15, "Hertz Gold Plus Rewards": 16, "Disney Castaway Club": 17, "TSA PreCheck": 12 };
    for (const [name, id] of Object.entries(logos)) {
      const img = rows(name).querySelector("img");
      expect(img).toHaveAttribute("src", `/api/loyalty/${id}/logo`);
      expect(img).toHaveAttribute("alt", "");
    }
    expect(container.querySelectorAll("img")).toHaveLength(6);
    for (const name of ["Global Entry", "Other"]) {
      const row = rows(name);
      expect(row.querySelector("img")).toBeNull();
      const mark = row.querySelector("span[aria-hidden='true']") as HTMLElement;
      expect(mark.textContent).toBe(name[0]);
      expect(mark.style.width).toBe("20px");
      expect(mark.className).toContain("rounded-full");
    }
    expect(screen.getByRole("button", { name: "Edit Jane Doe’s Delta SkyMiles" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove Jane Doe’s Delta SkyMiles" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show and copy Delta SkyMiles number" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show and copy Global Entry number" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit Jane Doe’s Other" })).toBeInTheDocument();
  });

  it("reserves no logo space in a kind where no row has a logo", async () => {
    ids = [{ ...aa, logo: "/api/loyalty/11/logo" }, { ...aa, id: 14, program: "Other" }, tsa, { ...tsa, id: 18, program: "Global Entry" }];
    const { container } = render(People);
    await screen.findByRole("list", { name: "People" });
    const known = screen.getByRole("region", { name: "Jane Doe’s Known Traveler memberships" });
    expect(known.querySelector("img")).toBeNull();
    expect(known.querySelector("span[aria-hidden='true']")).toBeNull();
    const airline = screen.getByRole("region", { name: "Jane Doe’s Airline memberships" });
    expect(airline.querySelectorAll("img")).toHaveLength(1);
    expect(airline.querySelectorAll("span[aria-hidden='true']")).toHaveLength(1);
    expect(container.querySelectorAll("img")).toHaveLength(1);
  });

  it("keeps a membership's logo, program name and number together on one line", async () => {
    ids = [{ ...aa, logo: "/api/loyalty/11/logo" }];
    render(People);
    const number = await screen.findByRole("button", { name: "Show and copy American AAdvantage number" });
    const line = number.parentElement!;
    expect(line.className).toContain("flex");
    expect(line.querySelector("img")).not.toBeNull();
    expect(within(line).getByText("American AAdvantage")).toBeInTheDocument();
  });

  it("falls back to the plain program name when the logo can't load", async () => {
    ids = [{ ...aa, logo: "/api/loyalty/11/logo" }];
    const { container } = render(People);
    await screen.findByRole("list", { name: "People" });
    const img = container.querySelector("img")!;
    img.dispatchEvent(new Event("error"));
    await waitFor(() => expect(container.querySelector("img")).toBeNull());
    expect(screen.getByText("American AAdvantage")).toBeInTheDocument();
    expect(screen.getByText("A", { selector: "span[aria-hidden='true']" })).toBeInTheDocument();
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

  it("hides This is me on every guest once your own person has a linked guest", async () => {
    held = [{ ...jane, links: [{ guest: "Jane D.", by: "Jane Doe", on: "2026-10-05" }] }, mia];
    render(People);
    await screen.findByRole("list", { name: "People" });
    expect(screen.queryByRole("button", { name: /This is me/ })).toBeNull();
  });

  it("says who can see saved numbers before saving, and reveals nothing until asked", async () => {
    render(People);
    expect(await screen.findByText(/visible to every signed-in household member/)).toBeInTheDocument();
    expect(api).not.toHaveBeenCalledWith(expect.stringContaining("/reveal"), expect.anything());
    await userEvent.click(screen.getAllByRole("button", { name: /Add a loyalty or traveler number for Mia Doe/ })[0]);
    expect(await screen.findByText(/Every signed-in household member can see this number/)).toBeInTheDocument();
  });

  it("opens a new membership's form under that person, not at the top of the page", async () => {
    render(People);
    await screen.findByRole("list", { name: "People" });
    await userEvent.click(screen.getByRole("button", { name: "Add a loyalty or traveler number for Mia Doe" }));
    const heading = await screen.findByRole("heading", { name: /Add a loyalty or traveler number for Mia Doe/ });
    const row = heading.closest("li");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("Mia Doe", { selector: "span" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { name: /Add a loyalty or traveler number/ })).toHaveLength(1);
    const janes = screen.getByText("Jane Doe", { selector: "span" }).closest("li") as HTMLElement;
    expect(within(janes).queryByRole("heading", { name: /Add a loyalty or traveler number/ })).toBeNull();
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
    await userEvent.type(screen.getByLabelText(/^Display name/), "Grandpa Joe");
    await userEvent.type(screen.getByLabelText(/Name aliases/), "OHARE/JOE MR{Enter}O HARE/JOE MR");
    await userEvent.click(screen.getByRole("button", { name: "Add guest" }));
    expect(api).toHaveBeenCalledWith("/api/people", { method: "POST", body: { display_name: "Grandpa Joe", first_name: "", legal_name: "", aliases: ["OHARE/JOE MR", "O HARE/JOE MR"] } });
    expect(await screen.findByText("Grandpa Joe")).toBeInTheDocument();
    expect(screen.queryByRole("form")).toBeNull();
  });

  it("keeps Advanced matching open while the last alias is deleted or replaced", async () => {
    render(People);
    await userEvent.click(await screen.findByRole("button", { name: "Edit Mia Doe" }));
    const details = screen.getByText("Advanced matching").closest("details")!;
    expect(details.open).toBe(true);
    const aliases = screen.getByLabelText(/Name aliases/);
    await userEvent.clear(aliases);
    expect(details.open).toBe(true);
    await userEvent.type(aliases, "DOE/MIA");
    expect(details.open).toBe(true);
    expect(screen.getByLabelText(/Name aliases/)).toBeVisible();
  });

  it("starts Advanced matching closed for a person with no aliases", async () => {
    render(People);
    await userEvent.click(await screen.findByRole("button", { name: "Edit Jane Doe" }));
    expect(screen.getByText("Advanced matching").closest("details")!.open).toBe(false);
  });

  it("edits a member without offering their login", async () => {
    render(People);
    await userEvent.click(await screen.findByRole("button", { name: "Edit Jane Doe" }));
    expect(screen.getByText(/link to their sign-in stays as it is/)).toBeInTheDocument();
    const name = screen.getByLabelText(/^Display name/);
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
    await userEvent.type(screen.getByLabelText(/^Display name/), "x");
    await userEvent.click(screen.getByRole("button", { name: "Add guest" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter the name");
    expect(screen.getByLabelText(/^Display name/)).toHaveValue("x");
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
    expect(screen.queryByText(/DEMO1234567/)).toBeNull();
  });

  it("reveals one number on tap, copies it, and hides it on a second tap", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    render(People);
    await userEvent.click(await screen.findByRole("button", { name: "Show and copy American AAdvantage number" }));
    expect(api).toHaveBeenCalledWith("/api/loyalty/11/reveal", { method: "POST" });
    expect(await screen.findByText("DEMO1234567")).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith("DEMO1234567");
    expect(screen.getByText("••••2345")).toBeInTheDocument();
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
    await userEvent.click(await screen.findByRole("button", { name: "Add a loyalty or traveler number for Mia Doe" }));
    await userEvent.selectOptions(screen.getByLabelText("Kind"), "hotel");
    expect(screen.getByLabelText("Program")).toHaveValue("Marriott Bonvoy");
    await userEvent.type(screen.getByLabelText("Number"), "DEMO55501234");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(api).toHaveBeenCalledWith("/api/loyalty", { method: "POST", body: { person_id: 2, kind: "hotel", program: "Marriott Bonvoy", number: "DEMO55501234", expiry: "", notes: "" } });
    expect(await screen.findByRole("region", { name: "Mia Doe’s Hotel memberships" })).toBeInTheDocument();
    expect(screen.queryByRole("form")).toBeNull();
  });

  it("adds a cruise membership, choosing the cruise line's program", async () => {
    render(People);
    await userEvent.click(await screen.findByRole("button", { name: "Add a loyalty or traveler number for Mia Doe" }));
    await userEvent.selectOptions(screen.getByLabelText("Kind"), "cruise");
    expect(screen.getByLabelText("Program")).toHaveValue("Disney Castaway Club");
    await userEvent.type(screen.getByLabelText("Number"), "DEMOCC0042");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(api).toHaveBeenCalledWith("/api/loyalty", { method: "POST", body: { person_id: 2, kind: "cruise", program: "Disney Castaway Club", number: "DEMOCC0042", expiry: "", notes: "" } });
    expect(await screen.findByRole("region", { name: "Mia Doe’s Cruise memberships" })).toBeInTheDocument();
  });

  it("doesn't offer a program the person already has, keeps Other, and keeps a membership's own program when editing it", async () => {
    render(People);
    await userEvent.click(await screen.findByRole("button", { name: "Add a loyalty or traveler number for Jane Doe" }));
    const program = screen.getByLabelText(/^Program/);
    expect(within(program).queryByRole("option", { name: "American AAdvantage" })).toBeNull();
    expect(within(program).getByRole("option", { name: "Other" })).toBeInTheDocument();
    expect(program).toHaveValue("Other");
    await userEvent.selectOptions(screen.getByLabelText("Kind"), "hotel");
    expect(within(screen.getByLabelText(/^Program/)).getByRole("option", { name: "Marriott Bonvoy" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.click(await screen.findByRole("button", { name: "Discard changes" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    document.body.style.pointerEvents = "";
    await userEvent.click(screen.getByRole("button", { name: "Edit Jane Doe’s American AAdvantage" }));
    expect(screen.getByLabelText(/^Program/)).toHaveValue("American AAdvantage");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button", { name: "Add a loyalty or traveler number for Mia Doe" }));
    expect(within(screen.getByLabelText(/^Program/)).getByRole("option", { name: "American AAdvantage" })).toBeInTheDocument();
  });

  it("has no Tier, and offers an expiry only for Known Traveler and redress numbers", async () => {
    render(People);
    await userEvent.click(await screen.findByRole("button", { name: "Add a loyalty or traveler number for Mia Doe" }));
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
    await userEvent.click(await screen.findByRole("button", { name: "Add a loyalty or traveler number for Jane Doe" }));
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

describe("People on a phone", () => {
  beforeEach(() => { viewport.phone = true; });
  afterEach(() => { viewport.phone = false; });

  it("adds a guest in a sheet and closes it when saved", async () => {
    render(People);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: /Add a guest/ }));
    const sheet = await screen.findByRole("dialog", { name: "Add a guest" });
    expect(sheet).toHaveAttribute("data-side", "bottom");
    expect(within(sheet).getAllByRole("heading", { name: "Add a guest" })).toHaveLength(1);
    await u.type(within(sheet).getByLabelText(/^Display name/), "Sam Doe");
    await u.click(within(sheet).getByRole("button", { name: "Add guest" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(await screen.findByText("Sam Doe")).toBeInTheDocument();
  });

  it("edits a person in a sheet and Cancel changes nothing", async () => {
    render(People);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Edit Mia Doe" }));
    const sheet = await screen.findByRole("dialog", { name: "Edit Mia Doe" });
    expect(within(sheet).getByLabelText(/Legal name/)).toHaveValue("Mia Rose Doe");
    await u.click(within(sheet).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(vi.mocked(api).mock.calls.some(([, o]) => o?.method === "POST")).toBe(false);
  });

  it("adds a membership in a sheet, keeping the masked number rule", async () => {
    render(People);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Add a loyalty or traveler number for Mia Doe" }));
    const sheet = await screen.findByRole("dialog", { name: "Add a loyalty or traveler number for Mia Doe" });
    await u.type(within(sheet).getByLabelText("Number"), "DEMO7654321");
    await u.click(within(sheet).getByRole("button", { name: "Add" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.queryByText("DEMO7654321")).toBeNull();
    expect(await screen.findByText("••••4321")).toBeInTheDocument();
  });

  it("keeps the sheet open while a save is in flight and shows the failure in it", async () => {
    render(People);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Edit Mia Doe" }));
    const sheet = await screen.findByRole("dialog", { name: "Edit Mia Doe" });
    const name = within(sheet).getByLabelText(/^Display name/);
    await u.clear(name);
    await u.type(name, "Mia R");
    expect(screen.getByRole("dialog", { name: "Edit Mia Doe" })).toBe(sheet);
    let fail: (e: Error) => void = () => {};
    const inner = vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation(async (path, opts) => {
      if (opts?.method === "POST") return new Promise((_, reject) => { fail = reject; });
      return inner(path, opts);
    });
    await u.click(within(sheet).getByRole("button", { name: "Save" }));
    await u.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBe(sheet);
    fail(new Error("Couldn’t save"));
    expect(await within(sheet).findByRole("alert")).toHaveTextContent("Couldn’t save");
    expect(within(sheet).getByLabelText(/^Display name/)).toHaveValue("Mia R");
  });

  it("asks before any way of dismissing a changed guest form, keeps what was typed on Keep editing and drops it on Discard changes", async () => {
    render(People);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: /Add a guest/ }));
    const sheet = await screen.findByRole("dialog", { name: "Add a guest" });
    await u.type(within(sheet).getByLabelText(/^Display name/), "Sam Doe");
    await u.keyboard("{Escape}");
    await u.click(within(await screen.findByRole("dialog", { name: "Discard changes?" })).getByRole("button", { name: "Keep editing" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Discard changes?" })).toBeNull());
    expect(within(sheet).getByLabelText(/^Display name/)).toHaveValue("Sam Doe");
    await u.click(within(sheet).getByRole("button", { name: "Close" }));
    await u.click(within(await screen.findByRole("dialog", { name: "Discard changes?" })).getByRole("button", { name: "Keep editing" }));
    await u.click(within(sheet).getByRole("button", { name: "Cancel" }));
    await u.click(within(await screen.findByRole("dialog", { name: "Discard changes?" })).getByRole("button", { name: "Discard changes" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(vi.mocked(api).mock.calls.some(([, o]) => o?.method === "POST")).toBe(false);
  });

  it("asks before dropping a typed membership number, which is kept nowhere but in memory", async () => {
    render(People);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Add a loyalty or traveler number for Mia Doe" }));
    const sheet = await screen.findByRole("dialog", { name: "Add a loyalty or traveler number for Mia Doe" });
    await u.type(within(sheet).getByLabelText("Number"), "DEMO7654321");
    await u.keyboard("{Escape}");
    const ask = await screen.findByRole("dialog", { name: "Discard changes?" });
    await u.click(within(ask).getByRole("button", { name: "Discard changes" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.queryByText("DEMO7654321")).toBeNull();
  });

  it("closes an unchanged form without asking, and a changed one only once it has been saved", async () => {
    render(People);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Edit Mia Doe" }));
    await screen.findByRole("dialog", { name: "Edit Mia Doe" });
    await u.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("cannot be dismissed while it is saving", async () => {
    let finish: (v: unknown) => void = () => {};
    const slow = new Promise((resolve) => { finish = resolve; });
    const before = vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation(async (path, opts) => (opts?.method === "POST" && path === "/api/people" ? slow : before(path, opts)));
    render(People);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: /Add a guest/ }));
    const sheet = await screen.findByRole("dialog", { name: "Add a guest" });
    await u.type(within(sheet).getByLabelText(/^Display name/), "Sam Doe");
    await u.click(within(sheet).getByRole("button", { name: "Add guest" }));
    await within(sheet).findByRole("button", { name: "Saving…" });
    await u.keyboard("{Escape}");
    await u.click(within(sheet).getByRole("button", { name: "Close" }));
    expect(screen.getByRole("dialog", { name: "Add a guest" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Discard changes?" })).toBeNull();
    finish({ id: 9, display_name: "Sam Doe", first_name: null, legal_name: null, aliases: [], member: false, links: [] });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
