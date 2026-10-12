// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "$lib/api";
import { blank, MAX_VISITS, type Draft } from "$lib/segment-form";
import { segment } from "../../test/fixtures";
import SegmentForm from "./SegmentForm.svelte";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

const people = [{ id: 1, display_name: "Jane Doe" }] as never;
const past = (extra: Partial<Draft> = {}): Draft => ({ ...blank(), kind: "visit", people: [1], ...extra });
const mount = (initial: Draft, onsaved = vi.fn()) => render(SegmentForm, { props: { initial, people, onsaved, oncancel: vi.fn() } });
const sent = () => vi.mocked(api).mock.calls.map(([, opts]) => (opts as { body: Record<string, unknown> }).body);

async function fill(index: number, country: string, first: string, last: string) {
  const countries = screen.getAllByRole("combobox").filter((el) => el.querySelector('option[value="EC"]'));
  await userEvent.selectOptions(countries[index], country);
  const firsts = screen.getAllByLabelText(/^First day/), lasts = screen.getAllByLabelText(/^Last day/);
  await fireEvent.input(firsts[index], { target: { value: first } });
  await fireEvent.input(lasts[index], { target: { value: last } });
}

beforeEach(() => {
  vi.mocked(api).mockReset();
});

describe("SegmentForm: a past trip with several countries", () => {
  it("looks as before with one country", () => {
    mount(past());
    expect(screen.getAllByLabelText("Country")).toHaveLength(1);
    expect(screen.getByLabelText("First day")).toBeInTheDocument();
    expect(screen.getByLabelText("Last day")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Remove country/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Add another country" })).toBeInTheDocument();
  });

  it("adds a row that starts on the previous row's last day and can be removed", async () => {
    mount(past({ destination: "EC", start_local: "2005-03-01T00:00", end_local: "2005-03-10T00:00" }));
    await userEvent.click(screen.getByRole("button", { name: "Add another country" }));
    expect(screen.getByLabelText("Country 2")).toHaveValue("");
    expect(screen.getByLabelText("First day 2")).toHaveValue("2005-03-10");
    expect(screen.getByLabelText("Last day 2")).toHaveValue("2005-03-10");
    await userEvent.click(screen.getByRole("button", { name: "Remove country 2" }));
    expect(screen.queryByLabelText("Country 2")).toBeNull();
    expect(screen.getByLabelText("Country")).toHaveValue("EC");
  });

  it("removes the first row by moving the next one up", async () => {
    mount(past({ destination: "EC", start_local: "2005-03-01T00:00", end_local: "2005-03-10T00:00", more: [{ destination: "PE", start_local: "2005-03-10T00:00", end_local: "2005-03-20T00:00" }] }));
    await userEvent.click(screen.getByRole("button", { name: "Remove country 1" }));
    expect(screen.getByLabelText("Country")).toHaveValue("PE");
    expect(screen.getByLabelText("First day")).toHaveValue("2005-03-10");
  });

  it("stops offering more at the limit", async () => {
    const more = Array.from({ length: MAX_VISITS - 2 }, () => ({ destination: "PE", start_local: "2005-03-10T00:00", end_local: "2005-03-20T00:00" }));
    mount(past({ destination: "EC", start_local: "2005-03-01T00:00", end_local: "2005-03-10T00:00", more }));
    const add = screen.getByRole("button", { name: "Add another country" });
    await userEvent.click(add);
    expect(screen.getAllByLabelText(/^Country \d+$/)).toHaveLength(MAX_VISITS);
    expect(add).toBeDisabled();
  });

  it("creates the trip with all its countries from one Add", async () => {
    vi.mocked(api).mockImplementation(async (_path, opts) => segment({ id: vi.mocked(api).mock.calls.length, trip_id: 7, kind: "visit", destination: (opts as { body: { destination: string } }).body.destination }));
    const onsaved = vi.fn();
    mount(past(), onsaved);
    await fill(0, "EC", "2005-03-01", "2005-03-10");
    await userEvent.click(screen.getByRole("button", { name: "Add another country" }));
    await fill(1, "PE", "2005-03-10", "2005-03-20");
    await userEvent.click(screen.getByRole("button", { name: "Add another country" }));
    await fill(2, "EC", "2005-03-21", "2005-03-25");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(onsaved).toHaveBeenCalledTimes(1));
    expect(sent().map((b) => [b.destination, b.start_local, b.end_local, b.trip_id])).toEqual([
      ["EC", "2005-03-01T00:00", "2005-03-10T00:00", null], ["PE", "2005-03-10T00:00", "2005-03-20T00:00", 7], ["EC", "2005-03-21T00:00", "2005-03-25T00:00", 7],
    ]);
    expect(onsaved.mock.calls[0][0]).toMatchObject({ trip_id: 7 });
  });

  it("adds every country to the trip it is opened from", async () => {
    vi.mocked(api).mockImplementation(async (_path, opts) => segment({ trip_id: 3, kind: "visit", destination: (opts as { body: { destination: string } }).body.destination }));
    const onsaved = vi.fn();
    mount(past({ tripId: 3 }), onsaved);
    await fill(0, "ES", "2008-06-01", "2008-06-05");
    await userEvent.click(screen.getByRole("button", { name: "Add another country" }));
    await fill(1, "FR", "2008-06-05", "2008-06-09");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(onsaved).toHaveBeenCalledTimes(1));
    expect(sent().map((b) => b.trip_id)).toEqual([3, 3]);
  });

  it("names the row that is wrong and sends nothing", async () => {
    const onsaved = vi.fn();
    mount(past(), onsaved);
    await fill(0, "EC", "2005-03-01", "2005-03-10");
    await userEvent.click(screen.getByRole("button", { name: "Add another country" }));
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Country 2: Choose the country");
    expect(api).not.toHaveBeenCalled();
    expect(onsaved).not.toHaveBeenCalled();
  });

  it("says which country the server refused and keeps the rest to try again, without repeating the saved ones", async () => {
    vi.mocked(api).mockImplementationOnce(async () => segment({ trip_id: 7, kind: "visit", destination: "EC" })).mockRejectedValueOnce(new Error("Too many requests"));
    const onsaved = vi.fn();
    mount(past(), onsaved);
    await fill(0, "EC", "2005-03-01", "2005-03-10");
    await userEvent.click(screen.getByRole("button", { name: "Add another country" }));
    await fill(1, "PE", "2005-03-10", "2005-03-20");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Country 2: Too many requests The countries before it were saved.");
    expect(onsaved).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Country")).toHaveValue("PE");
    expect(screen.queryByLabelText("Country 2")).toBeNull();
    vi.mocked(api).mockImplementationOnce(async () => segment({ trip_id: 7, kind: "visit", destination: "PE" }));
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(onsaved).toHaveBeenCalledTimes(1));
    expect(sent().map((b) => [b.destination, b.trip_id])).toEqual([["EC", null], ["PE", 7], ["PE", 7]]);
  });

  it("does not offer another country while editing one", () => {
    mount(past({ id: 4, tripId: 1, destination: "EC", start_local: "2005-03-01T00:00", end_local: "2005-03-10T00:00" }));
    expect(screen.queryByRole("button", { name: "Add another country" })).toBeNull();
  });
});
