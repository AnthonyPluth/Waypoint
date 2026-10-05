// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { Person } from "$lib/api-types";
import People from "./People.svelte";

const jane: Person = { id: 1, display_name: "Jane Doe", first_name: "Jane", legal_name: null, aliases: [], member: true };
const mia: Person = { id: 2, display_name: "Mia Doe", first_name: "Mia", legal_name: "Mia Rose Doe", aliases: ["DOE/MIA MISS"], member: false };

/** The server, with its people kept in `held`: answers the calls the page makes. */
let held: Person[];
function serve() {
  vi.mocked(api).mockImplementation(async (path, opts) => {
    const id = Number(path.split("/")[3]);
    if (opts?.method === "DELETE") { held = held.filter((p) => p.id !== id); return { ok: true }; }
    if (opts?.method === "POST") {
      const b = opts.body as { display_name: string; first_name: string; legal_name: string; aliases: string[] };
      const next: Person = { id: id || 9, display_name: b.display_name, first_name: b.first_name || null, legal_name: b.legal_name || null,
        aliases: b.aliases.filter(Boolean), member: held.find((p) => p.id === id)?.member ?? false };
      held = id ? held.map((p) => (p.id === id ? next : p)) : [...held, next];
      return next;
    }
    return { people: held };
  });
}

beforeEach(() => { vi.mocked(api).mockReset(); held = [jane, mia]; serve(); });

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
});
