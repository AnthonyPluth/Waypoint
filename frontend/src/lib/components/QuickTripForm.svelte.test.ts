// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "$lib/api";
import { segment, trip } from "../../test/fixtures";
import QuickTripForm from "./QuickTripForm.svelte";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

const made = trip([segment()], { id: 7, name: "Lisbon" });
const mount = (me: number | null = 1, oncreated = vi.fn(), oncancel = vi.fn()) => render(QuickTripForm, { props: { me, oncreated, oncancel } });
const sentBody = () => (vi.mocked(api).mock.calls.find(([path]) => path === "/api/trips")![1] as { body: Record<string, unknown> }).body;

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockResolvedValue(made as never);
});

describe("QuickTripForm", () => {
  it("asks for a name and two optional days, with the name focused", () => {
    mount();
    expect(screen.getByLabelText("Where to, or a name")).toHaveFocus();
    expect(screen.getByLabelText("First day (optional)")).toBeInTheDocument();
    expect(screen.getByLabelText("Last day (optional)")).toBeInTheDocument();
  });

  it("creates a trip from only a name, with the signed-in person on it", async () => {
    const oncreated = vi.fn();
    mount(1, oncreated);
    await userEvent.type(screen.getByLabelText("Where to, or a name"), "Lisbon");
    await userEvent.click(screen.getByRole("button", { name: "Add trip" }));
    await waitFor(() => expect(oncreated).toHaveBeenCalledWith(made));
    expect(sentBody()).toEqual({ name: "Lisbon", people: [1] });
  });

  it("sends the days it was given", async () => {
    mount();
    await userEvent.type(screen.getByLabelText("Where to, or a name"), "Lisbon");
    await fireEvent.input(screen.getByLabelText("First day (optional)"), { target: { value: "2026-12-01" } });
    await fireEvent.input(screen.getByLabelText("Last day (optional)"), { target: { value: "2026-12-08" } });
    await userEvent.click(screen.getByRole("button", { name: "Add trip" }));
    await waitFor(() => expect(api).toHaveBeenCalled());
    expect(sentBody()).toMatchObject({ name: "Lisbon", start_date: "2026-12-01", end_date: "2026-12-08" });
  });

  it("names no one when the signed-in person is not known", async () => {
    mount(null);
    await userEvent.type(screen.getByLabelText("Where to, or a name"), "Lisbon");
    await userEvent.click(screen.getByRole("button", { name: "Add trip" }));
    await waitFor(() => expect(api).toHaveBeenCalled());
    expect(sentBody()).toEqual({ name: "Lisbon" });
  });

  it("marks a missing name, sends nothing and keeps the days", async () => {
    mount();
    await fireEvent.input(screen.getByLabelText("First day (optional)"), { target: { value: "2026-12-01" } });
    await userEvent.click(screen.getByRole("button", { name: "Add trip" }));
    const name = screen.getByLabelText("Where to, or a name");
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(name).toHaveFocus();
    expect(screen.getByText("Enter where you’re going, or a name for the trip")).toBeInTheDocument();
    expect(screen.getByLabelText("First day (optional)")).toHaveValue("2026-12-01");
    expect(api).not.toHaveBeenCalled();
  });

  it("marks a last day before the first", async () => {
    mount();
    await userEvent.type(screen.getByLabelText("Where to, or a name"), "Lisbon");
    await fireEvent.input(screen.getByLabelText("First day (optional)"), { target: { value: "2026-12-08" } });
    await fireEvent.input(screen.getByLabelText("Last day (optional)"), { target: { value: "2026-12-01" } });
    await userEvent.click(screen.getByRole("button", { name: "Add trip" }));
    expect(screen.getByLabelText("Last day (optional)")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("The last day can’t be before the first")).toBeInTheDocument();
    expect(api).not.toHaveBeenCalled();
  });

  it("keeps what was typed and says why when the server refuses", async () => {
    vi.mocked(api).mockRejectedValue(new Error("A trip can’t end before it starts"));
    const oncreated = vi.fn();
    mount(1, oncreated);
    await userEvent.type(screen.getByLabelText("Where to, or a name"), "Lisbon");
    await userEvent.click(screen.getByRole("button", { name: "Add trip" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A trip can’t end before it starts");
    expect(screen.getByLabelText("Where to, or a name")).toHaveValue("Lisbon");
    expect(oncreated).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Add trip" })).toBeEnabled();
  });

  it("closes on Cancel when nothing was typed", async () => {
    const oncancel = vi.fn();
    mount(1, vi.fn(), oncancel);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(oncancel).toHaveBeenCalled();
  });
});
