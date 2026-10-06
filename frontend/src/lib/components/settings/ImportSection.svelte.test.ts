// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn(), warning: vi.fn() }) }));

import { api } from "$lib/api";
import type { ImportPreview, ImportRow } from "$lib/api-types";
import { toast } from "svelte-sonner";
import ImportSection from "./ImportSection.svelte";

const row = (line: number, extra: Partial<ImportRow> = {}): ImportRow => ({
  line, status: "new", reason: null, day: "2025-03-01", origin: "JFK", destination: "LAX", flight_number: "DL1001", airline: "DL",
  start_local: "2025-03-01T08:12", end_local: "2025-03-01T11:29", seat: null, cabin: null, ...extra,
});
const preview = (rows: ImportRow[], me: number | null = 1): ImportPreview => ({ format: "Flighty", me, rows });
const people = { people: [
  { id: 1, display_name: "Jane Doe", first_name: null, legal_name: null, aliases: [], member: true },
  { id: 2, display_name: "Mia Doe", first_name: null, legal_name: null, aliases: [], member: false },
] };
const csv = (size = 10) => new File(["x".repeat(size)], "flights.csv", { type: "text/csv" });

function serve(reply: ImportPreview | Error, saved: (body: { flights: unknown[]; person_ids: number[] }) => unknown = () => ({ added: 1, existing: 0 })) {
  vi.mocked(api).mockImplementation((async (path: string, opts?: { body?: unknown }) => {
    if (path === "/api/import/preview") { if (reply instanceof Error) throw reply; return reply; }
    if (path === "/api/people") return people;
    if (path === "/api/import") return saved(opts!.body as { flights: unknown[]; person_ids: number[] });
    throw new Error(`unexpected ${path}`);
  }) as never);
}
const choose = (file: File) => userEvent.upload(document.querySelector("input[type=file]") as HTMLInputElement, file);

beforeEach(() => { vi.mocked(api).mockReset(); vi.mocked(toast.success).mockReset(); });

describe("Settings → Import past flights", () => {
  it("shows what each row would add before anything is saved, marked new, already here or can’t be read", async () => {
    serve(preview([row(2), row(3, { status: "exists", reason: "Already in Waypoint", origin: "SEA", destination: "SFO" }),
      row(4, { status: "unreadable", reason: "Waypoint doesn’t know the airport ZZZ", day: null, origin: null, destination: null }), row(5, { start_local: null, end_local: null, origin: "LAX", destination: "JFK" })]));
    render(ImportSection);
    await choose(csv());
    const box = await screen.findByTestId("import-preview");
    expect(within(box).getByText("Flighty export:")).toBeInTheDocument();
    expect(box).toHaveTextContent("2 new flights, 1 already in Waypoint, 1 can’t be read.");
    expect(within(box).getByText(/doesn’t know the airport ZZZ/)).toBeInTheDocument();
    expect(within(box).getByText(/no times/)).toBeInTheDocument();
    expect(within(box).getAllByText("New")).toHaveLength(2);
    expect(vi.mocked(api).mock.calls.map((c) => c[0])).not.toContain("/api/import");
    expect(vi.mocked(api).mock.calls[0][1]).toMatchObject({ method: "POST", body: expect.any(File) });
  });

  it("defaults the flights to the importer and sends back only the new rows, with who was on them", async () => {
    const saved = vi.fn(() => ({ added: 2, existing: 0 }));
    serve(preview([row(2), row(3, { status: "exists", reason: "Already in Waypoint" }), row(4, { origin: "LAX", destination: "JFK", flight_number: null })]), saved);
    render(ImportSection);
    await choose(csv());
    await screen.findByTestId("import-preview");
    expect(screen.getByRole("checkbox", { name: /Jane Doe/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Mia Doe/ })).not.toBeChecked();
    await userEvent.click(screen.getByRole("checkbox", { name: /Mia Doe/ }));
    await userEvent.click(screen.getByRole("button", { name: "Add 2 flights" }));
    await waitFor(() => expect(saved).toHaveBeenCalled());
    const sent = saved.mock.calls[0] as unknown as [{ flights: { origin: string; notes?: string }[]; person_ids: number[] }];
    expect(sent[0].person_ids).toEqual([1, 2]);
    expect(sent[0].flights.map((f) => f.origin)).toEqual(["JFK", "LAX"]);
    expect(toast.success).toHaveBeenCalledWith("Added 2 flights");
    await waitFor(() => expect(screen.queryByTestId("import-preview")).toBeNull());
  });

  it("sends the new flights in date order, whatever order the file had", async () => {
    const saved = vi.fn(() => ({ added: 3, existing: 0 }));
    serve(preview([row(2, { day: "2025-05-01", origin: "SEA" }), row(3, { day: "2025-03-01", origin: "JFK" }), row(4, { day: "2025-04-01", origin: "ORD" })]), saved);
    render(ImportSection);
    await choose(csv());
    await screen.findByTestId("import-preview");
    await userEvent.click(screen.getByRole("button", { name: "Add 3 flights" }));
    await waitFor(() => expect(saved).toHaveBeenCalled());
    const sent = saved.mock.calls[0] as unknown as [{ flights: { origin: string }[] }];
    expect(sent[0].flights.map((f) => f.origin)).toEqual(["JFK", "ORD", "SEA"]);
  });

  it("sends a long file back a thousand flights at a time", async () => {
    const saved = vi.fn((b: { flights: unknown[] }) => ({ added: b.flights.length, existing: 0 }));
    serve(preview(Array.from({ length: 2300 }, (_, i) => row(i + 2, { origin: "JFK", day: "2025-03-01" }))), saved);
    render(ImportSection);
    await choose(csv());
    await screen.findByTestId("import-preview");
    expect(screen.getByText(/first 200 of 2,300 rows/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add 2,300 flights" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added 2,300 flights"));
    expect(saved.mock.calls.map((c) => c[0].flights.length)).toEqual([1000, 1000, 300]);
  });

  it("says why a file can’t be used, and offers nothing to add", async () => {
    serve(new Error("Waypoint can import CSV exports from Flighty, myFlightRadar24, OpenFlights and App in the Air. This file’s columns don’t match any of them."));
    render(ImportSection);
    await choose(csv());
    expect(await screen.findByRole("alert")).toHaveTextContent("columns don’t match");
    expect(screen.queryByRole("button", { name: /Add/ })).toBeNull();
  });

  it("refuses a file over 5 MB without sending it", async () => {
    serve(preview([]));
    render(ImportSection);
    await choose(csv(5 * 1024 * 1024 + 1));
    expect(await screen.findByRole("alert")).toHaveTextContent("That file is larger than 5 MB.");
    expect(api).not.toHaveBeenCalled();
  });

  it("has nothing to add when every flight is already here", async () => {
    serve(preview([row(2, { status: "exists", reason: "Already in Waypoint" })]));
    render(ImportSection);
    await choose(csv());
    expect(await screen.findByRole("button", { name: "Nothing new to add" })).toBeDisabled();
  });

  it("keeps the preview and says how far it got when a save fails", async () => {
    let calls = 0;
    serve(preview(Array.from({ length: 1500 }, (_, i) => row(i + 2))), (b) => {
      if (++calls === 2) throw new Error("Waypoint is busy saving something else.");
      return { added: b.flights.length, existing: 0 };
    });
    render(ImportSection);
    await choose(csv());
    await screen.findByTestId("import-preview");
    await userEvent.click(screen.getByRole("button", { name: "Add 1,500 flights" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Added 1,000 flights before this stopped: Waypoint is busy saving something else.");
    expect(screen.getByTestId("import-preview")).toBeInTheDocument();
    expect(toast.success).not.toHaveBeenCalled();
  });
});
