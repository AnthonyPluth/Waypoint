// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { Trip } from "$lib/api-types";
import { app } from "$lib/app.svelte";
import { toast } from "svelte-sonner";
import { segment, state, trip } from "../../test/fixtures";
import TripDetails from "./TripDetails.svelte";

const dates = "Nov 20 – Nov 21";
const automatic = trip([segment()], { name: "Trip to London", destination: "United Kingdom", destination_manual: false, notes: null });
const written = trip([segment()], { name: "Trip to London", destination: "Colorado & Texas", destination_manual: true, notes: null });
const noted = trip([segment()], { name: "Trip to London", destination: "United Kingdom", destination_manual: false, notes: "Pack light" });
let onsaved: Mock<(next: Trip) => void>;

const show = (t = automatic) => render(TripDetails, { trip: t, dates, onsaved });
const editButton = () => screen.getByRole("button", { name: "Edit trip details" });
const openForm = async (u = userEvent.setup()) => { await u.click(editButton()); return u; };
const form = () => screen.getByRole("form", { name: "Edit trip details" });
const saveButton = () => within(form()).getByRole("button", { name: "Save" });
const cancelButton = () => within(form()).getByRole("button", { name: "Cancel" });
const posts = () => vi.mocked(api).mock.calls.filter(([, o]) => o?.method === "POST");

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(toast.success).mockReset();
  vi.mocked(toast.error).mockReset();
  app.state = state({ ai: false });
  onsaved = vi.fn<(next: Trip) => void>();
});
afterEach(() => { app.state = null; });

describe("TripDetails", () => {
  it("shows the name, the dates and destination, and one edit button with no second pencil", () => {
    show();
    expect(screen.getByRole("heading", { name: "Trip to London" })).toBeInTheDocument();
    expect(screen.getByText("Nov 20 – Nov 21 · United Kingdom")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Edit trip details" })).toHaveLength(1);
    expect(screen.queryAllByRole("button", { name: /rename|destination/i })).toHaveLength(0);
  });

  it("shows only the dates when there is no destination", () => {
    show(trip([segment()], { destination: null }));
    expect(screen.getByText(dates)).toBeInTheDocument();
  });

  it("opens one form with Name and Destination, and Notes only when the trip has notes", async () => {
    show();
    await openForm();
    expect(form()).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("Trip to London");
    expect(screen.getByLabelText("Destination")).toHaveValue("");
    expect(screen.queryByLabelText("Notes")).toBeNull();
  });

  it("shows the notes field, with the notes, when the trip has notes", async () => {
    show(noted);
    await openForm();
    expect(screen.getByLabelText("Notes")).toHaveValue("Pack light");
  });

  it("opens an empty destination for an automatic one, showing the automatic one as its placeholder, and says Waypoint keeps it up to date", async () => {
    show();
    await openForm();
    expect(screen.getByLabelText("Destination")).toHaveAttribute("placeholder", "United Kingdom");
    expect(screen.getByText(/Waypoint picks this from the places of your bookings and updates it whenever they change/)).toBeInTheDocument();
  });

  it("opens a destination the person wrote with its text and says Waypoint won’t change it", async () => {
    show(written);
    await openForm();
    expect(screen.getByLabelText("Destination")).toHaveValue("Colorado & Texas");
    expect(screen.getByText(/You set this, so Waypoint won’t change it when you add, move, merge or remove bookings/)).toBeInTheDocument();
  });

  it("changes the helper text as the person types and clears", async () => {
    show();
    const u = await openForm();
    await u.type(screen.getByLabelText("Destination"), "Utah");
    expect(screen.getByText(/You set this, so Waypoint won’t change it/)).toBeInTheDocument();
    await u.clear(screen.getByLabelText("Destination"));
    expect(screen.getByText(/Waypoint picks this from the places/)).toBeInTheDocument();
  });

  it("moves focus to Name when it opens and back to the edit button when it closes", async () => {
    show();
    const u = await openForm();
    expect(screen.getByLabelText("Name")).toHaveFocus();
    await u.click(cancelButton());
    await waitFor(() => expect(editButton()).toHaveFocus());
  });

  it("saves the changed name and destination in one update, with only those fields", async () => {
    const saved = trip([segment()], { name: "Lisbon in spring", destination: "Utah", destination_manual: true, notes: null });
    vi.mocked(api).mockResolvedValue(saved);
    show();
    const u = await openForm();
    await u.clear(screen.getByLabelText("Name"));
    await u.type(screen.getByLabelText("Name"), "  Lisbon in spring ");
    await u.type(screen.getByLabelText("Destination"), " Utah ");
    await u.click(saveButton());
    await waitFor(() => expect(onsaved).toHaveBeenCalledWith(saved));
    expect(posts()).toEqual([["/api/trips/1", { method: "POST", body: { name: "Lisbon in spring", destination: "Utah" } }]]);
    expect(toast.success).toHaveBeenCalledWith("Saved");
    expect(screen.queryByRole("form", { name: "Edit trip details" })).toBeNull();
  });

  it("sends only the notes when only the notes changed", async () => {
    vi.mocked(api).mockResolvedValue({ ...noted, notes: "Pack warm" });
    show(noted);
    const u = await openForm();
    await u.clear(screen.getByLabelText("Notes"));
    await u.type(screen.getByLabelText("Notes"), "Pack warm");
    await u.click(saveButton());
    await waitFor(() => expect(onsaved).toHaveBeenCalled());
    expect(posts()).toEqual([["/api/trips/1", { method: "POST", body: { notes: "Pack warm" } }]]);
  });

  it("sends nothing and just closes when nothing changed", async () => {
    show();
    await openForm();
    await userEvent.click(saveButton());
    await waitFor(() => expect(screen.queryByRole("form", { name: "Edit trip details" })).toBeNull());
    expect(api).not.toHaveBeenCalled();
    expect(onsaved).not.toHaveBeenCalled();
  });

  it("hands a cleared destination back to Waypoint as null", async () => {
    vi.mocked(api).mockResolvedValue(automatic);
    show(written);
    const u = await openForm();
    await u.clear(screen.getByLabelText("Destination"));
    await u.click(saveButton());
    await waitFor(() => expect(onsaved).toHaveBeenCalledWith(automatic));
    expect(posts()).toEqual([["/api/trips/1", { method: "POST", body: { destination: null } }]]);
  });

  it("won't save an empty name, says why, and keeps the form open without sending", async () => {
    show();
    const u = await openForm();
    await u.clear(screen.getByLabelText("Name"));
    await u.click(saveButton());
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter a name for the trip");
    expect(form()).toBeInTheDocument();
    expect(posts()).toHaveLength(0);
  });

  it("shows a failed save in the form and keeps everything that was typed", async () => {
    vi.mocked(api).mockRejectedValue(new Error("The name is too long"));
    show();
    const u = await openForm();
    await u.type(screen.getByLabelText("Name"), " again");
    await u.type(screen.getByLabelText("Destination"), "Utah");
    await u.click(saveButton());
    expect(await screen.findByRole("alert")).toHaveTextContent("The name is too long");
    expect(onsaved).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Name")).toHaveValue("Trip to London again");
    expect(screen.getByLabelText("Destination")).toHaveValue("Utah");
    expect(form()).toBeInTheDocument();
  });

  it("Cancel closes an untouched form without asking", async () => {
    show();
    const u = await openForm();
    await u.click(cancelButton());
    expect(screen.queryByRole("form", { name: "Edit trip details" })).toBeNull();
    expect(screen.queryByRole("dialog", { name: "Discard changes?" })).toBeNull();
    expect(api).not.toHaveBeenCalled();
  });

  it("Escape closes an untouched form without asking", async () => {
    show();
    await openForm();
    await fireEvent.keyDown(screen.getByLabelText("Name"), { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("form", { name: "Edit trip details" })).toBeNull());
    expect(screen.queryByRole("dialog", { name: "Discard changes?" })).toBeNull();
  });

  it("Cancel asks before discarding a change, and Keep editing returns to what was typed", async () => {
    show();
    const u = await openForm();
    await u.type(screen.getByLabelText("Name"), " again");
    await u.click(cancelButton());
    expect(await screen.findByRole("dialog", { name: "Discard changes?" })).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(screen.getByLabelText("Name")).toHaveValue("Trip to London again");
    expect(api).not.toHaveBeenCalled();
  });

  it("Escape asks before discarding a change, and Discard closes the form and returns focus to the edit button", async () => {
    show();
    const u = await openForm();
    await u.type(screen.getByLabelText("Destination"), "Utah");
    await fireEvent.keyDown(screen.getByLabelText("Name"), { key: "Escape" });
    expect(await screen.findByRole("dialog", { name: "Discard changes?" })).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Discard changes" }));
    await waitFor(() => expect(screen.queryByRole("form", { name: "Edit trip details" })).toBeNull());
    expect(editButton()).toHaveFocus();
    expect(api).not.toHaveBeenCalled();
  });

  it("with the trip’s bookings, shows its dates read-only in the form and never sends them", async () => {
    vi.mocked(api).mockResolvedValue(automatic);
    show();
    const u = await openForm();
    expect(within(form()).getByText("Nov 20 – Nov 21")).toBeInTheDocument();
    expect(within(form()).queryByRole("textbox", { name: /date/i })).toBeNull();
    expect(form().querySelectorAll("input[type=date]")).toHaveLength(0);
    await u.type(screen.getByLabelText("Name"), "!");
    await u.click(saveButton());
    await waitFor(() => expect(onsaved).toHaveBeenCalled());
    expect(posts()).toEqual([["/api/trips/1", { method: "POST", body: { name: "Trip to London!" } }]]);
  });

  it("Escape closes an untouched form from Save and from Cancel, not only from its fields", async () => {
    show();
    const u = await openForm();
    await fireEvent.keyDown(saveButton(), { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("form", { name: "Edit trip details" })).toBeNull());
    await u.click(editButton());
    await fireEvent.keyDown(cancelButton(), { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("form", { name: "Edit trip details" })).toBeNull());
    expect(screen.queryByRole("dialog", { name: "Discard changes?" })).toBeNull();
    expect(api).not.toHaveBeenCalled();
  });

  it("Escape from Save asks before discarding a change", async () => {
    show();
    const u = await openForm();
    await u.type(screen.getByLabelText("Name"), " again");
    await fireEvent.keyDown(saveButton(), { key: "Escape" });
    expect(await screen.findByRole("dialog", { name: "Discard changes?" })).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(screen.getByLabelText("Name")).toHaveValue("Trip to London again");
  });

  describe("Escape from the sparkle button", () => {
    beforeEach(() => { app.state = state({ ai: true }); });

    it("closes an untouched form without asking", async () => {
      show();
      await openForm();
      await fireEvent.keyDown(screen.getByRole("button", { name: "Suggest a destination with AI" }), { key: "Escape" });
      await waitFor(() => expect(screen.queryByRole("form", { name: "Edit trip details" })).toBeNull());
      expect(screen.queryByRole("dialog", { name: "Discard changes?" })).toBeNull();
    });

    it("asks before discarding a change", async () => {
      show();
      const u = await openForm();
      await u.type(screen.getByLabelText("Name"), " again");
      await fireEvent.keyDown(screen.getByRole("button", { name: "Suggest a destination with AI" }), { key: "Escape" });
      expect(await screen.findByRole("dialog", { name: "Discard changes?" })).toBeInTheDocument();
    });
  });

  describe("the sparkle button", () => {
    it("is hidden, with its note, while the AI fallback is off", async () => {
      show();
      await openForm();
      expect(screen.queryByRole("button", { name: "Suggest a destination with AI" })).toBeNull();
      expect(screen.queryByText(/sends only the trip’s name and the places/)).toBeNull();
    });

    describe("with the AI fallback on", () => {
      beforeEach(() => { app.state = state({ ai: true }); });

      it("says what it sends", async () => {
        show();
        await openForm();
        expect(screen.getByText(/sends only the trip’s name and the places of its bookings to your AI service, never dates, names, codes or emails/)).toBeInTheDocument();
      });

      it("fills the destination with the suggestion without saving it", async () => {
        vi.mocked(api).mockResolvedValue({ suggestion: "Colorado & Texas" });
        show();
        await openForm();
        await userEvent.click(screen.getByRole("button", { name: "Suggest a destination with AI" }));
        await waitFor(() => expect(screen.getByLabelText("Destination")).toHaveValue("Colorado & Texas"));
        expect(api).toHaveBeenCalledTimes(1);
        expect(api).toHaveBeenCalledWith("/api/trips/1/destination/suggest", { method: "POST", body: { name: "Trip to London" } });
        expect(onsaved).not.toHaveBeenCalled();
        expect(screen.getByText(/You set this, so Waypoint won’t change it/)).toBeInTheDocument();
      });

      it("sends the name in the form, not the saved one, so the suggestion uses what is on screen", async () => {
        vi.mocked(api).mockResolvedValue({ suggestion: "Utah" });
        show();
        const u = await openForm();
        await u.clear(screen.getByLabelText("Name"));
        await u.type(screen.getByLabelText("Name"), "  Summer in Utah ");
        await u.click(screen.getByRole("button", { name: "Suggest a destination with AI" }));
        await waitFor(() => expect(screen.getByLabelText("Destination")).toHaveValue("Utah"));
        expect(api).toHaveBeenCalledWith("/api/trips/1/destination/suggest", { method: "POST", body: { name: "Summer in Utah" } });
        expect(api).not.toHaveBeenCalledWith("/api/trips/1", expect.anything());
      });

      it("is disabled and busy while it asks", async () => {
        let answer: (v: { suggestion: string }) => void = () => {};
        vi.mocked(api).mockReturnValue(new Promise((resolve) => { answer = resolve; }) as never);
        show();
        await openForm();
        await userEvent.click(screen.getByRole("button", { name: "Suggest a destination with AI" }));
        const button = screen.getByRole("button", { name: "Suggest a destination with AI" });
        expect(button).toBeDisabled();
        expect(button).toHaveAttribute("aria-busy", "true");
        expect(saveButton()).toBeDisabled();
        answer({ suggestion: "Utah" });
        await waitFor(() => expect(screen.getByRole("button", { name: "Suggest a destination with AI" })).toBeEnabled());
        expect(screen.getByLabelText("Destination")).toHaveValue("Utah");
      });

      it("shows a toast and leaves what was typed when the AI can’t answer", async () => {
        vi.mocked(api).mockRejectedValue(new Error("Waypoint couldn’t reach the AI service."));
        show();
        const u = await openForm();
        await u.type(screen.getByLabelText("Destination"), "Utah");
        await u.click(screen.getByRole("button", { name: "Suggest a destination with AI" }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Waypoint couldn’t reach the AI service."));
        expect(screen.getByLabelText("Destination")).toHaveValue("Utah");
        expect(screen.getByRole("button", { name: "Suggest a destination with AI" })).toBeEnabled();
      });
    });
  });
});
