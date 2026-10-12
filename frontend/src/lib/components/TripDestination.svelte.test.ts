// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { Trip } from "$lib/api-types";
import { app } from "$lib/app.svelte";
import { toast } from "svelte-sonner";
import { segment, state, trip } from "../../test/fixtures";
import TripDestination from "./TripDestination.svelte";

const dates = "Nov 20 – Nov 21";
const automatic = trip([segment()], { destination: "United Kingdom", destination_manual: false });
const written = trip([segment()], { destination: "Colorado & Texas", destination_manual: true });
let onsaved: Mock<(next: Trip) => void>;

const show = (t = automatic) => render(TripDestination, { trip: t, dates, onsaved });
const open = async () => { await userEvent.click(screen.getByRole("button", { name: "Edit destination" })); return screen.getByLabelText("Destination"); };

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(toast.success).mockReset();
  vi.mocked(toast.error).mockReset();
  app.state = state({ ai: false });
  onsaved = vi.fn<(next: Trip) => void>();
});
afterEach(() => { app.state = null; });

describe("TripDestination", () => {
  it("shows the dates and the destination under the name", () => {
    show();
    expect(screen.getByText("Nov 20 – Nov 21 · United Kingdom")).toBeInTheDocument();
  });

  it("shows only the dates when there is no destination", () => {
    show(trip([segment()], { destination: null }));
    expect(screen.getByText(dates)).toBeInTheDocument();
  });

  it("opens an empty field for an automatic destination, showing the automatic one as its placeholder, and says Waypoint keeps it up to date", async () => {
    show();
    const field = await open();
    expect(field).toHaveValue("");
    expect(field).toHaveAttribute("placeholder", "United Kingdom");
    expect(screen.getByText(/Waypoint picks this from the places of your bookings and updates it whenever they change/)).toBeInTheDocument();
  });

  it("opens a destination the person wrote with its text and says Waypoint won’t change it", async () => {
    show(written);
    const field = await open();
    expect(field).toHaveValue("Colorado & Texas");
    expect(screen.getByText(/You set this, so Waypoint won’t change it when you add, move, merge or remove bookings/)).toBeInTheDocument();
  });

  it("changes the helper text as the person types and clears", async () => {
    show();
    const field = await open();
    await userEvent.type(field, "Utah");
    expect(screen.getByText(/You set this, so Waypoint won’t change it/)).toBeInTheDocument();
    await userEvent.clear(field);
    expect(screen.getByText(/Waypoint picks this from the places/)).toBeInTheDocument();
  });

  it("saves what was typed as the destination", async () => {
    const saved = trip([segment()], { destination: "Utah", destination_manual: true });
    vi.mocked(api).mockResolvedValue(saved);
    show();
    await userEvent.type(await open(), "  Utah ");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onsaved).toHaveBeenCalledWith(saved));
    expect(api).toHaveBeenCalledWith("/api/trips/1", { method: "POST", body: { destination: "Utah" } });
    expect(toast.success).toHaveBeenCalledWith("Saved");
    expect(screen.queryByLabelText("Destination")).toBeNull();
  });

  it("returns to automatic when the field is cleared and saved", async () => {
    vi.mocked(api).mockResolvedValue(automatic);
    show(written);
    await userEvent.clear(await open());
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onsaved).toHaveBeenCalledWith(automatic));
    expect(api).toHaveBeenCalledWith("/api/trips/1", { method: "POST", body: { destination: null } });
  });

  it("shows the reason when saving fails and keeps the field open", async () => {
    vi.mocked(api).mockRejectedValue(new Error("The destination is too long (at most 100 characters)"));
    show();
    await userEvent.type(await open(), "x");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("too long");
    expect(onsaved).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Destination")).toHaveValue("x");
  });

  it("cancels without saving", async () => {
    show();
    await userEvent.type(await open(), "Utah");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(api).not.toHaveBeenCalled();
    expect(screen.getByText("Nov 20 – Nov 21 · United Kingdom")).toBeInTheDocument();
  });

  describe("the sparkle button", () => {
    it("is hidden, with its note, while the AI fallback is off", async () => {
      show();
      await open();
      expect(screen.queryByRole("button", { name: "Suggest a destination with AI" })).toBeNull();
      expect(screen.queryByText(/sends only the trip’s name and the places/)).toBeNull();
    });

    describe("with the AI fallback on", () => {
      beforeEach(() => { app.state = state({ ai: true }); });

      it("says what it sends", async () => {
        show();
        await open();
        expect(screen.getByText(/sends only the trip’s name and the places of its bookings to your AI service, never dates, names, codes or emails/)).toBeInTheDocument();
      });

      it("fills the field with the suggestion without saving it", async () => {
        vi.mocked(api).mockResolvedValue({ suggestion: "Colorado & Texas" });
        show();
        const field = await open();
        await userEvent.click(screen.getByRole("button", { name: "Suggest a destination with AI" }));
        await waitFor(() => expect(field).toHaveValue("Colorado & Texas"));
        expect(api).toHaveBeenCalledTimes(1);
        expect(api).toHaveBeenCalledWith("/api/trips/1/destination/suggest", { method: "POST" });
        expect(onsaved).not.toHaveBeenCalled();
        expect(screen.getByText(/You set this, so Waypoint won’t change it/)).toBeInTheDocument();
      });

      it("is disabled and busy while it asks", async () => {
        let answer: (v: { suggestion: string }) => void = () => {};
        vi.mocked(api).mockReturnValue(new Promise((resolve) => { answer = resolve; }) as never);
        show();
        await open();
        await userEvent.click(screen.getByRole("button", { name: "Suggest a destination with AI" }));
        const button = screen.getByRole("button", { name: "Suggest a destination with AI" });
        expect(button).toBeDisabled();
        expect(button).toHaveAttribute("aria-busy", "true");
        expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
        answer({ suggestion: "Utah" });
        await waitFor(() => expect(screen.getByRole("button", { name: "Suggest a destination with AI" })).toBeEnabled());
        expect(screen.getByLabelText("Destination")).toHaveValue("Utah");
      });

      it("shows a toast and leaves what was typed when the AI can’t answer", async () => {
        vi.mocked(api).mockRejectedValue(new Error("Waypoint couldn’t reach the AI service."));
        show();
        const field = await open();
        await userEvent.type(field, "Utah");
        await userEvent.click(screen.getByRole("button", { name: "Suggest a destination with AI" }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Waypoint couldn’t reach the AI service."));
        expect(field).toHaveValue("Utah");
        expect(screen.getByRole("button", { name: "Suggest a destination with AI" })).toBeEnabled();
      });
    });
  });
});
