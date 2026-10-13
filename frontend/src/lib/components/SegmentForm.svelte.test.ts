// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { chooseZone } from "../../test/zone";
import { blank, type Draft, type Kind } from "$lib/segment-form";
import SegmentForm from "./SegmentForm.svelte";

const KINDS: Kind[] = ["flight", "hotel", "car", "train", "cruise", "parking"];
const REMOVED = [
  /Check-in and check-out are both at the hotel/,
  /Entry and exit are both at the lot/,
  /Leave this empty to work it out/,
];

const draft = (kind: Kind, extra: Partial<Draft> = {}): Draft => ({
  ...blank(1), kind, origin: "Harbour Hotel", start_local: "2026-12-02T15:00", end_local: "2026-12-05T11:00", people: [1], ...extra,
});

const mount = (initial: Draft, onsaved = vi.fn()) => render(SegmentForm, { props: { initial, people: [], onsaved, oncancel: vi.fn() } });

describe("SegmentForm: a rental car", () => {
  it("has one pick-up place, no pick-up address, and a drop-off that says it is the same as pick-up", () => {
    mount(draft("car", { origin: "Example Rental" }));
    expect(screen.getByLabelText("Pick-up place")).toHaveValue("Example Rental");
    expect(screen.queryByLabelText(/address/i)).toBeNull();
    expect(screen.getByLabelText("Drop-off place")).toHaveAttribute("placeholder", "Same as pick-up");
    expect(screen.getByLabelText("Car class")).toBeInTheDocument();
    expect(screen.getByLabelText("Phone")).toBeInTheDocument();
  });
});

describe("SegmentForm: a rental car's kept address", () => {
  const kept = "1 Rental Way, Bristol BS48 3DY";

  it("shows a Pick-up address field only for a car whose address differs from its pick-up", () => {
    mount({ ...draft("car", { origin: "Example Rental", details: { address: kept } }), addressField: true });
    expect(screen.getByLabelText(/^Pick-up address/)).toHaveValue(kept);
  });

  it("shows no address field for a new car, or one whose address equals its pick-up", () => {
    mount(draft("car", { origin: "Example Rental", details: { address: "Example Rental" } }));
    expect(screen.queryByLabelText(/address/i)).toBeNull();
  });

  it("lets the address be edited and cleared, and a cleared one follows the pick-up again", async () => {
    const initial = { ...draft("car", { origin: "Example Rental", pickup: "Example Rental", details: { address: kept } }), addressField: true };
    mount(initial);
    const field = screen.getByLabelText(/^Pick-up address/);
    await userEvent.clear(field);
    await userEvent.type(field, "2 Depot Road");
    expect(field).toHaveValue("2 Depot Road");
    await userEvent.clear(field);
    expect(field).toHaveValue("");
  });
});

describe("SegmentForm: who is travelling", () => {
  const withPeople = (initial: Draft) => render(SegmentForm, { props: { initial, people: [{ id: 1, display_name: "Jane Doe" }, { id: 2, display_name: "Sam Doe" }] as never, onsaved: vi.fn(), oncancel: vi.fn() } });

  it.each(["hotel", "car", "parking"] as const)("asks nobody for a %s", (kind) => {
    withPeople(draft(kind));
    expect(screen.queryByText("Who’s travelling")).toBeNull();
    expect(screen.queryByLabelText("Sam Doe")).toBeNull();
  });

  it.each(["flight", "cruise", "train"] as const)("lets you choose who is on a %s", (kind) => {
    withPeople(draft(kind));
    expect(screen.getByText("Who’s travelling")).toBeInTheDocument();
    expect(screen.getByLabelText("Sam Doe")).toBeInTheDocument();
  });

  it("shows the choice again when the booking is changed from a stay to a flight", async () => {
    withPeople(draft("hotel"));
    expect(screen.queryByLabelText("Sam Doe")).toBeNull();
    await userEvent.selectOptions(screen.getByLabelText("What is it"), "Flight");
    expect(screen.getByLabelText("Sam Doe")).toBeInTheDocument();
  });
});

describe("SegmentForm: the explanatory text is gone", () => {
  it.each(KINDS)("the %s form shows none of the removed lines", (kind) => {
    mount(draft(kind));
    for (const text of REMOVED) expect(screen.queryByText(text)).toBeNull();
    for (const el of document.querySelectorAll("[aria-describedby]")) {
      for (const id of el.getAttribute("aria-describedby")!.split(" ")) expect(document.getElementById(id), `aria-describedby ${id}`).not.toBeNull();
    }
  });

  it.each(["hotel", "parking"] as const)("keeps the blank zone choice for a %s", async (kind) => {
    mount(draft(kind));
    await userEvent.click(screen.getByRole("button", { name: "Set the time zone by hand" }));
    expect(screen.getByPlaceholderText("Work it out from the address")).toBeInTheDocument();
  });

  it("still says what to enter when a stay has neither a time zone nor an address", async () => {
    const onsaved = vi.fn();
    mount(draft("hotel"), onsaved);
    await userEvent.click(screen.getByRole("button", { name: "Add booking" }));
    expect(await screen.findByText(/Enter the time zone of the stay/)).toBeInTheDocument();
    await waitFor(() => expect(onsaved).not.toHaveBeenCalled());
  });
});

describe("SegmentForm: the cost", () => {
  it("has an amount and a currency, filled from the booking, with a note when an email supplied it", () => {
    mount(draft("hotel", { id: 5, cost: "310.00", currency: "EUR", costSource: "email" }));
    expect(screen.getByLabelText("Cost amount")).toHaveValue("310.00");
    expect(screen.getByLabelText("Cost currency")).toHaveValue("EUR");
    expect(screen.getByText(/Read from an email\. Change it and your amount is kept/)).toBeInTheDocument();
  });
  it("says nothing about an email for a cost entered by hand or none, and starts in the given currency", () => {
    mount(draft("hotel", { currency: "GBP" }));
    expect(screen.getByLabelText("Cost amount")).toHaveValue("");
    expect(screen.getByLabelText("Cost currency")).toHaveValue("GBP");
    expect(screen.queryByText(/Read from an email/)).toBeNull();
  });
  it("refuses an amount it can't read, before saving", async () => {
    const onsaved = vi.fn();
    mount(draft("hotel", { start_zone: "Europe/London", cost: "abc" }), onsaved);
    await userEvent.click(screen.getByRole("button", { name: "Add booking" }));
    expect(await screen.findByText(/Enter the cost as an amount like 1240.00/)).toBeInTheDocument();
    expect(onsaved).not.toHaveBeenCalled();
  });
});

describe("SegmentForm: a past trip's state", () => {
  const visit = (destination: string, extra: Partial<Draft> = {}) => mount({ ...blank(1), kind: "visit", destination, start_local: "2006-07-02T00:00", end_local: "2006-07-12T00:00", people: [1], ...extra });

  it("offers a State only when the country is the United States", async () => {
    visit("JP");
    expect(screen.queryByLabelText("State (optional)")).toBeNull();
    await userEvent.selectOptions(screen.getByLabelText("Country"), "US");
    expect(screen.getByLabelText("State (optional)")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Country"), "CA");
    expect(screen.queryByLabelText("State (optional)")).toBeNull();
  });

  it("shows the state a visit has, and clears it with Any state", async () => {
    visit("US", { details: { state: "AK" } });
    expect(screen.getByLabelText("State (optional)")).toHaveValue("AK");
    await userEvent.selectOptions(screen.getByLabelText("State (optional)"), "");
    expect(screen.getByLabelText("State (optional)")).toHaveValue("");
    await userEvent.selectOptions(screen.getByLabelText("State (optional)"), "HI");
    expect(screen.getByLabelText("State (optional)")).toHaveValue("HI");
  });
});

describe("SegmentForm: the time zone field", () => {
  it("searches the start zone of a stay and fills it in", async () => {
    mount(draft("hotel"));
    await userEvent.click(screen.getByRole("button", { name: "Set the time zone by hand" }));
    const field = screen.getByLabelText("Time zone");
    await chooseZone(field, "America/Chicago");
    expect(field).toHaveValue("America/Chicago");
    expect(screen.queryAllByRole("listbox", { hidden: true })).toHaveLength(0);
  });

  it("searches a cruise port’s zone with one list open at a time", async () => {
    mount(draft("cruise", { itinerary: [{ name: "Nassau", zone: "", arrive: "", depart: "" }] }));
    const port = screen.getByLabelText("Port 1 time zone");
    await userEvent.click(port);
    await userEvent.keyboard("nassau");
    expect(screen.getAllByRole("listbox", { hidden: true })).toHaveLength(1);
    await userEvent.keyboard("{Enter}");
    expect(port).toHaveValue("America/Nassau");
    expect(screen.queryAllByRole("listbox", { hidden: true })).toHaveLength(0);
  });
});

describe("SegmentForm: grouped fields and errors at their fields", () => {
  const headings = () => screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);

  it("groups a flight as Booking, When and where, Travelers, with the rest under More details", () => {
    render(SegmentForm, { props: { initial: draft("flight", { origin: "JFK", destination: "LHR" }), people: [{ id: 1, display_name: "Jane Doe" }] as never, onsaved: vi.fn(), oncancel: vi.fn() } });
    expect(headings()).toEqual(["Booking", "When and where", "Travelers"]);
    expect(screen.getByText("More details").closest("details")).not.toHaveAttribute("open");
    expect(screen.getByLabelText("From (airport)")).toBeVisible();
  });

  it("has no Travelers group for a hotel, and no time zone field until asked for", () => {
    mount(draft("hotel"));
    expect(headings()).toEqual(["Booking", "When and where"]);
    expect(screen.queryByLabelText("Time zone")).toBeNull();
    expect(screen.getByLabelText("Address")).toBeInTheDocument();
  });

  it("keeps the ports of a cruise visible and its time zone required", () => {
    mount(draft("cruise", { start_zone: "America/Nassau" }));
    expect(screen.getByLabelText("Time zone")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add a port" })).toBeVisible();
  });

  it("opens More details on an edit that has something in it", () => {
    mount(draft("hotel", { id: 4, manage_url: "https://example.com/manage" }));
    expect(screen.getByText("More details").closest("details")).toHaveAttribute("open");
  });

  it("explains a bad airport at its field, links it with aria, focuses it and keeps what was typed", async () => {
    const onsaved = vi.fn();
    render(SegmentForm, { props: { initial: draft("flight", { origin: "New York", destination: "LHR", end_local: "" }), people: [{ id: 1, display_name: "Jane Doe" }] as never, onsaved, oncancel: vi.fn() } });
    await userEvent.click(screen.getByRole("button", { name: "Add booking" }));
    const from = screen.getByLabelText("From (airport)");
    expect(from).toHaveAttribute("aria-invalid", "true");
    expect(from).toHaveFocus();
    expect(from).toHaveValue("New York");
    const described = document.getElementById(from.getAttribute("aria-describedby")!);
    expect(described).toHaveTextContent(/Choose the airport it leaves from/);
    const end = screen.getByLabelText(/^Arrives/);
    expect(end).toHaveAttribute("aria-invalid", "true");
    expect(document.getElementById(end.getAttribute("aria-describedby")!)).toHaveTextContent("Enter when it ends");
    expect(onsaved).not.toHaveBeenCalled();
  });

  it("clears an error once its field is fixed", async () => {
    mount(draft("hotel", { origin: "" }));
    await userEvent.click(screen.getByRole("button", { name: "Add booking" }));
    const name = screen.getByLabelText("Hotel name");
    expect(name).toHaveAttribute("aria-invalid", "true");
    await userEvent.type(name, "Harbour Hotel");
    expect(name).not.toHaveAttribute("aria-invalid");
  });

  it("opens More details and focuses the manage link when that is what is wrong", async () => {
    mount(draft("hotel", { start_zone: "Europe/London", manage_url: "ftp://nope" }));
    await userEvent.click(screen.getByRole("button", { name: "Add booking" }));
    expect(screen.getByText("More details").closest("details")).toHaveAttribute("open");
    expect(screen.getByLabelText("Manage link")).toHaveFocus();
  });

  it("shows the time zone field, with the error, when a stay has neither zone nor address", async () => {
    mount(draft("hotel"));
    await userEvent.click(screen.getByRole("button", { name: "Add booking" }));
    expect(await screen.findByLabelText(/^Time zone/)).toHaveAttribute("aria-invalid", "true");
  });

  it("labels the buttons Add booking and Save changes", () => {
    mount(draft("hotel"));
    expect(screen.getByRole("button", { name: "Add booking" })).toBeInTheDocument();
    mount(draft("hotel", { id: 3 }));
    expect(screen.getByRole("button", { name: "Save changes" })).toBeInTheDocument();
  });
});
