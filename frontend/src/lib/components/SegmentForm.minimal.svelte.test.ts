// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "$lib/api";
import { blank, MAX_PORTS, type Draft, type PortDraft } from "$lib/segment-form";
import { segment } from "../../test/fixtures";
import SegmentForm from "./SegmentForm.svelte";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

const people = [{ id: 1, display_name: "Jane Doe" }] as never;
const mount = (initial: Draft, onsaved = vi.fn()) => render(SegmentForm, { props: { initial, people, onsaved, oncancel: vi.fn() } });
const sentBody = () => (vi.mocked(api).mock.calls.find(([path]) => path === "/api/segments")![1] as { body: Record<string, unknown> }).body;

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async (path: string) => (path.startsWith("/api/airports") ? { airports: [] } : segment({ trip_id: 1 })) as never);
});

describe("SegmentForm: the minimal flight and hotel", () => {
  it("saves a flight from only its airports, times and traveller, never opening More details", async () => {
    const onsaved = vi.fn();
    mount({ ...blank(1), people: [1] }, onsaved);
    await userEvent.type(screen.getByLabelText("From (airport)"), "jfk");
    await userEvent.type(screen.getByLabelText("To (airport)"), "lhr");
    await fireEvent.input(screen.getByLabelText(/^Departs/), { target: { value: "2026-12-01T19:00" } });
    await fireEvent.input(screen.getByLabelText(/^Arrives/), { target: { value: "2026-12-02T07:00" } });
    expect(screen.getByText("More details").closest("details")).not.toHaveAttribute("open");
    await userEvent.click(screen.getByRole("button", { name: "Add booking" }));
    await waitFor(() => expect(onsaved).toHaveBeenCalled());
    expect(sentBody()).toMatchObject({ kind: "flight", origin: "JFK", destination: "LHR", travelers: [{ person_id: 1 }] });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("saves a hotel from its name, times and address, without a time zone", async () => {
    const onsaved = vi.fn();
    mount({ ...blank(1), kind: "hotel" }, onsaved);
    await userEvent.type(screen.getByLabelText("Hotel name"), "Harbour Hotel");
    await fireEvent.input(screen.getByLabelText(/^Check-in/), { target: { value: "2026-12-02T15:00" } });
    await fireEvent.input(screen.getByLabelText(/^Check-out/), { target: { value: "2026-12-05T11:00" } });
    await userEvent.type(screen.getByLabelText("Address"), "1 Quay Street, London");
    await userEvent.click(screen.getByRole("button", { name: "Add booking" }));
    await waitFor(() => expect(onsaved).toHaveBeenCalled());
    expect(sentBody()).toMatchObject({ kind: "hotel", origin: "Harbour Hotel", start_zone: null });
  });

  it("keeps everything typed when the airport is wrong, and saves once it is fixed", async () => {
    const onsaved = vi.fn();
    mount({ ...blank(1), people: [1], origin: "Londn", destination: "JFK", start_local: "2026-12-01T19:00", end_local: "2026-12-01T22:00", provider: "Example Air" }, onsaved);
    await userEvent.click(screen.getByRole("button", { name: "Add booking" }));
    const from = screen.getByLabelText("From (airport)");
    expect(from).toHaveFocus();
    expect(from).toHaveValue("Londn");
    expect(screen.getByLabelText("To (airport)")).toHaveValue("JFK");
    expect(screen.getByLabelText("Airline")).toHaveValue("Example Air");
    expect(api).not.toHaveBeenCalledWith("/api/segments", expect.anything());
    await userEvent.clear(from);
    await userEvent.type(from, "LHR");
    await userEvent.click(screen.getByRole("button", { name: "Add booking" }));
    await waitFor(() => expect(onsaved).toHaveBeenCalled());
  });

  it("keeps the values and says why next to the form's buttons when the server refuses", async () => {
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path.startsWith("/api/airports")) return { airports: [] } as never;
      throw new Error("Waypoint is busy.");
    });
    mount({ ...blank(1), people: [1], origin: "JFK", destination: "LHR", start_local: "2026-12-01T19:00", end_local: "2026-12-02T07:00" });
    await userEvent.click(screen.getByRole("button", { name: "Add booking" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Waypoint is busy.");
    expect(screen.getByLabelText("From (airport)")).toHaveValue("JFK");
  });
});

describe("SegmentForm: zones entered for an unknown airport", () => {
  it("stay visible, with their values, after the airport changes to a known one", async () => {
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path === "/api/airports/XYZ") throw new Error("No such airport");
      if (path === "/api/airports/CDG") return { code: "CDG", name: "Charles de Gaulle Airport", city: "Paris", country: "FR", zone: "Europe/Paris" } as never;
      return (path.startsWith("/api/airports") ? { airports: [] } : segment({ trip_id: 1 })) as never;
    });
    mount({ ...blank(1), people: [1], origin: "JFK", destination: "XYZ", start_local: "2026-12-01T19:00", end_local: "2026-12-02T07:00", end_zone: "Asia/Tokyo" });
    const arrival = await screen.findByLabelText(/^Arrival time zone/);
    expect(arrival).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("To (airport)"));
    await userEvent.type(screen.getByLabelText("To (airport)"), "CDG");
    await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalledWith("/api/airports/CDG", { keep: true }));
    expect(screen.getByLabelText(/^Arrival time zone/)).toBeInTheDocument();
  });
});

describe("SegmentForm: a long cruise itinerary", () => {
  const ports = (n: number): PortDraft[] => Array.from({ length: n }, (_, i) => ({ name: `Port ${i + 1} name`, zone: "America/Nassau", arrive: "", depart: "" }));
  const cruise = (itinerary: PortDraft[]): Draft => ({ ...blank(1), kind: "cruise", people: [1], origin: "Miami", destination: "Miami", start_local: "2026-03-01T16:00", end_local: "2026-03-20T08:00", start_zone: "America/New_York", itinerary });

  it("shows every one of the most ports a cruise can have and saves them in order", async () => {
    const onsaved = vi.fn();
    mount(cruise(ports(MAX_PORTS)), onsaved);
    expect(document.querySelectorAll("[data-port]")).toHaveLength(MAX_PORTS);
    expect(screen.getByRole("button", { name: "Add a port" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Add booking" }));
    await waitFor(() => expect(onsaved).toHaveBeenCalled());
    const sent = sentBody().itinerary as { name: string }[];
    expect(sent).toHaveLength(MAX_PORTS);
    expect(sent[MAX_PORTS - 1].name).toBe(`Port ${MAX_PORTS} name`);
  }, 30000);

  it("marks and focuses the one port that is wrong, far down a long list", async () => {
    const list = ports(30);
    list[24] = { ...list[24], name: "" };
    list[27] = { ...list[27], arrive: "2026-03-10T10:00", depart: "2026-03-10T08:00" };
    const onsaved = vi.fn();
    mount(cruise(list), onsaved);
    await userEvent.click(screen.getByRole("button", { name: "Add booking" }));
    const name = screen.getByLabelText("Port 25 name");
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(name).toHaveFocus();
    expect(document.getElementById(name.getAttribute("aria-describedby")!)).toHaveTextContent("Name port 25");
    expect(screen.getByLabelText("Port 28 departure")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Port 1 name")).not.toHaveAttribute("aria-invalid");
    expect(onsaved).not.toHaveBeenCalled();
  }, 30000);
});
