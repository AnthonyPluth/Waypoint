// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { Person, Trip } from "$lib/api-types";
import { toast } from "svelte-sonner";
import { segment, trip } from "../../test/fixtures";
import TripPeopleSheet from "./TripPeopleSheet.svelte";

const person = (id: number, display_name: string, member = true): Person => ({ id, display_name, first_name: null, legal_name: null, aliases: [], member, links: [] });
const jane = person(1, "Jane Doe");
const sam = person(2, "Sam Doe");
const mia = person(3, "Mia Doe", false);
const joan = person(4, "Joan Roe", false);
const household = [jane, sam, mia, joan];

const flight = segment({ id: 1, travelers: [{ id: 1, person_id: 1, name: "Jane Doe", seat: null }] });
const stay = segment({ id: 2, kind: "hotel", travelers: [{ id: 2, person_id: 1, name: "Jane Doe", seat: null }, { id: 3, person_id: 2, name: "Sam Doe", seat: null }] });
const shared = () => trip([flight, stay], { people: [1, 2] });
const posts = () => vi.mocked(api).mock.calls.filter(([, o]) => o?.method === "POST");
const sheet = () => screen.getByRole("dialog", { name: "People on this trip" });
let onsaved: Mock<(next: Trip) => void>;
let onguest: Mock<(guest: Person) => void>;

const show = (t: Trip = shared(), me: number | null = 1, people: Person[] = household) => {
  render(TripPeopleSheet, { props: { open: true, trip: t, people, me, onsaved, onguest } });
  return userEvent.setup();
};

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(toast.success).mockReset();
  vi.mocked(toast.error).mockReset();
  onsaved = vi.fn<(next: Trip) => void>();
  onguest = vi.fn<(guest: Person) => void>();
  vi.mocked(api).mockImplementation(async (path, opts) => {
    if (path === "/api/people") return { ...person(5, String((opts?.body as { display_name: string }).display_name), false) } as never;
    return trip([flight, stay], { people: (opts?.body as { people: number[] }).people }) as never;
  });
});
afterEach(() => { document.body.style.pointerEvents = ""; });

describe("TripPeopleSheet", () => {
  it("lists the trip’s people, marks the viewer, and offers the rest of the household to add", async () => {
    show();
    const on = within(await screen.findByRole("region", { name: /On this trip/ }));
    expect(on.getAllByRole("listitem")).toHaveLength(2);
    expect(on.getByText("Jane Doe")).toBeInTheDocument();
    expect(on.getByText("(you)")).toBeInTheDocument();
    expect(on.getByText("Sam Doe")).toBeInTheDocument();
    expect(on.getAllByRole("button").map((b) => b.getAttribute("aria-label"))).toEqual(["Remove Jane Doe from this trip", "Remove Sam Doe from this trip"]);
    const add = within(screen.getByRole("region", { name: "Add someone" }));
    expect(add.getAllByRole("button").filter((b) => b.textContent === "Add").map((b) => b.getAttribute("aria-label"))).toEqual(["Add Mia Doe to this trip", "Add Joan Roe to this trip"]);
    expect(sheet()).toHaveTextContent("Everyone here sees the trip and all its bookings.");
  });

  it("lists a person who is on the trip but on none of its bookings", async () => {
    show(trip([stay], { people: [1, 2, 3] }));
    expect(await screen.findByRole("button", { name: "Remove Mia Doe from this trip" })).toBeEnabled();
  });

  it("says so when nobody is on the trip, and when everyone already is", async () => {
    const { unmount } = render(TripPeopleSheet, { props: { open: true, trip: trip([]), people: household, me: 1, onsaved, onguest } });
    expect(await screen.findByText("Nobody is on this trip yet.")).toBeInTheDocument();
    unmount();
    show(trip([stay], { people: [1, 2, 3, 4] }));
    expect(await screen.findByText("Everyone in People is already on this trip.")).toBeInTheDocument();
  });

  it("won’t remove someone who is on one of the trip’s flights, and says why", async () => {
    show();
    const remove = await screen.findByRole("button", { name: "Remove Jane Doe from this trip" });
    expect(remove).toBeDisabled();
    expect(remove).toHaveAccessibleDescription("On a flight in this trip. Take them off the flight first.");
    expect(screen.getByRole("button", { name: "Remove Sam Doe from this trip" })).toBeEnabled();
  });

  it("asks before taking someone off, then sends the list without them and says so", async () => {
    const u = show();
    await u.click(await screen.findByRole("button", { name: "Remove Sam Doe from this trip" }));
    const dialog = await screen.findByRole("dialog", { name: "Remove Sam Doe from this trip?" });
    expect(dialog).toHaveTextContent("stop seeing the trip unless they booked it");
    expect(dialog).not.toHaveTextContent("That is you");
    expect(posts()).toHaveLength(0);
    await u.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/trips/1", { method: "POST", body: { people: [1] } }));
    await waitFor(() => expect(onsaved).toHaveBeenCalledTimes(1));
    expect(onsaved.mock.calls[0][0].people).toEqual([1]);
    expect(toast.success).toHaveBeenCalledWith("Sam Doe removed");
  });

  it("changes nothing when the removal is cancelled", async () => {
    const u = show();
    await u.click(await screen.findByRole("button", { name: "Remove Sam Doe from this trip" }));
    const dialog = await screen.findByRole("dialog", { name: "Remove Sam Doe from this trip?" });
    await u.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Remove Sam Doe from this trip?" })).toBeNull());
    expect(posts()).toHaveLength(0);
    expect(onsaved).not.toHaveBeenCalled();
  });

  it("warns when the person being taken off is the viewer", async () => {
    const u = show(shared(), 2);
    await u.click(await screen.findByRole("button", { name: "Remove Sam Doe from this trip" }));
    expect(await screen.findByRole("dialog", { name: "Remove Sam Doe from this trip?" })).toHaveTextContent("That is you. You won’t see this trip any more");
  });

  it("adds a household person by sending the whole list and the new person", async () => {
    const u = show();
    await u.click(await screen.findByRole("button", { name: "Add Mia Doe to this trip" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/trips/1", { method: "POST", body: { people: [1, 2, 3] } }));
    await waitFor(() => expect(onsaved).toHaveBeenCalledTimes(1));
    expect(toast.success).toHaveBeenCalledWith("Mia Doe added");
    expect(screen.queryByRole("dialog", { name: "Share this trip with them?" })).toBeNull();
  });

  it("asks who would newly see the trip before sharing it, and sends the confirmation only when told to", async () => {
    vi.mocked(api).mockImplementation(async (_path, opts) => {
      if (!(opts?.body as { confirm?: boolean }).confirm) throw Object.assign(new Error("Adding people changes who sees what."), { status: 409, data: { see_booking: [], see_trip: [{ id: 3, name: "Mia Doe" }] } });
      return trip([flight, stay], { people: (opts?.body as { people: number[] }).people }) as never;
    });
    const u = show();
    await u.click(await screen.findByRole("button", { name: "Add Mia Doe to this trip" }));
    const dialog = await screen.findByRole("dialog", { name: "Share this trip with them?" });
    expect(dialog).toHaveTextContent("Will newly see this trip: Mia Doe");
    expect(posts().filter(([, o]) => (o?.body as { confirm?: boolean }).confirm)).toHaveLength(0);
    expect(onsaved).not.toHaveBeenCalled();
    await u.click(within(dialog).getByRole("button", { name: "Share anyway" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/trips/1", { method: "POST", body: { people: [1, 2, 3], confirm: true } }));
    await waitFor(() => expect(onsaved).toHaveBeenCalledTimes(1));
  });

  it("adds nothing when the sharing question is declined", async () => {
    vi.mocked(api).mockImplementation(async () => { throw Object.assign(new Error("Adding people changes who sees what."), { status: 409, data: { see_booking: [], see_trip: [{ id: 3, name: "Mia Doe" }] } }); });
    const u = show();
    await u.click(await screen.findByRole("button", { name: "Add Mia Doe to this trip" }));
    const dialog = await screen.findByRole("dialog", { name: "Share this trip with them?" });
    await u.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Share this trip with them?" })).toBeNull());
    expect(posts()).toHaveLength(1);
    expect(onsaved).not.toHaveBeenCalled();
  });

  it("makes a guest, hands it to the page and adds it to the trip", async () => {
    const u = show();
    const add = await screen.findByRole("button", { name: "Add guest" });
    expect(add).toBeDisabled();
    await u.type(screen.getByLabelText("Someone new"), "  Zed Guest ");
    await u.click(add);
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/people", { method: "POST", body: { display_name: "Zed Guest" } }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/trips/1", { method: "POST", body: { people: [1, 2, 5] } }));
    expect(onguest).toHaveBeenCalledWith(expect.objectContaining({ id: 5, display_name: "Zed Guest" }));
    expect(toast.success).toHaveBeenCalledWith("Zed Guest added");
    expect(screen.getByLabelText("Someone new")).toHaveValue("");
  });

  it("does not add a guest to another trip when the page moved to it while the guest was being made", async () => {
    let finish: (guest: unknown) => void = () => {};
    vi.mocked(api).mockImplementation(async (path, opts) => {
      if (path === "/api/people") return new Promise((resolve) => { finish = resolve; }) as never;
      return trip([stay], { id: 9, people: (opts?.body as { people: number[] }).people }) as never;
    });
    const view = render(TripPeopleSheet, { props: { open: true, trip: shared(), people: household, me: 1, onsaved, onguest } });
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText("Someone new"), "Zed Guest");
    await u.click(screen.getByRole("button", { name: "Add guest" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/people", expect.anything()));
    await view.rerender({ open: true, trip: trip([stay], { id: 9, people: [3] }), people: household, me: 1, onsaved, onguest });
    finish(person(5, "Zed Guest", false));
    await waitFor(() => expect(onguest).toHaveBeenCalledOnce());
    expect(posts()).toHaveLength(1);
    expect(onsaved).not.toHaveBeenCalled();
  });

  it("closes when the page moves to another trip, and ignores an answer that arrives for the old one", async () => {
    let finish: (next: unknown) => void = () => {};
    vi.mocked(api).mockImplementation(() => new Promise((resolve) => { finish = resolve; }) as never);
    const view = render(TripPeopleSheet, { props: { open: true, trip: shared(), people: household, me: 1, onsaved, onguest } });
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Add Mia Doe to this trip" }));
    await waitFor(() => expect(api).toHaveBeenCalledOnce());
    await view.rerender({ open: true, trip: trip([stay], { id: 9, people: [3] }), people: household, me: 1, onsaved, onguest });
    finish(trip([flight, stay], { people: [1, 2, 3] }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "People on this trip" })).toBeNull());
    expect(onsaved).not.toHaveBeenCalled();
  });

  it("keeps the sheet busy until the page has taken the saved trip, so a second change never sends a stale list", async () => {
    let release: () => void = () => {};
    onsaved.mockImplementation(() => new Promise<void>((resolve) => { release = resolve; }));
    const u = show();
    await u.click(await screen.findByRole("button", { name: "Add Mia Doe to this trip" }));
    await waitFor(() => expect(onsaved).toHaveBeenCalledOnce());
    expect(screen.getByRole("button", { name: "Add Joan Roe to this trip" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove Sam Doe from this trip" })).toBeDisabled();
    expect(toast.success).not.toHaveBeenCalled();
    release();
    await waitFor(() => expect(screen.getByRole("button", { name: "Add Joan Roe to this trip" })).toBeEnabled());
    expect(toast.success).toHaveBeenCalledWith("Mia Doe added");
    expect(posts()).toHaveLength(1);
  });

  it("shows what the server says when a change is refused, and leaves the page’s trip alone", async () => {
    vi.mocked(api).mockImplementation(async () => { throw Object.assign(new Error("Add at most 40 people"), { status: 400 }); });
    const u = show();
    await u.click(await screen.findByRole("button", { name: "Add Joan Roe to this trip" }));
    expect(await within(sheet()).findByRole("alert")).toHaveTextContent("Add at most 40 people");
    expect(onsaved).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("shows what the server says when a guest can’t be made, and adds nobody", async () => {
    vi.mocked(api).mockImplementation(async () => { throw Object.assign(new Error("Enter a name"), { status: 400 }); });
    const u = show();
    await u.type(await screen.findByLabelText("Someone new"), "x");
    await u.click(screen.getByRole("button", { name: "Add guest" }));
    expect(await within(sheet()).findByRole("alert")).toHaveTextContent("Enter a name");
    expect(onguest).not.toHaveBeenCalled();
    expect(posts()).toHaveLength(1);
  });

  it("closes with the Close button", async () => {
    const u = show();
    await u.type(await screen.findByLabelText("Someone new"), "Zed");
    await u.click(within(sheet()).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
