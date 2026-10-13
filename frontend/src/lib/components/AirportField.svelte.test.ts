// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "$lib/api";
import AirportField from "./AirportField.svelte";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));

const heathrow = { code: "LHR", name: "Heathrow Airport", city: "London", country: "GB", zone: "Europe/London" };

const HIDDEN = { hidden: true };
const gatwick = { code: "LGW", name: "Gatwick Airport", city: "London", country: "GB", zone: "Europe/London" };
const field = () => screen.getByRole("combobox");

const typeInto = async (text: string) => {
  render(AirportField, { props: { value: "", placeholder: "LHR", field: "origin" } });
  await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).type(screen.getByPlaceholderText("LHR"), text);
  await vi.advanceTimersByTimeAsync(300);
};

describe("AirportField", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(api).mockReset();
  });
  afterEach(() => vi.useRealTimers());

  it("offers airports found by city or name as codes with their names", async () => {
    vi.mocked(api).mockResolvedValue({ airports: [heathrow, gatwick] } as never);
    await typeInto("lond");
    expect(api).toHaveBeenCalledWith("/api/airports?q=lond");
    const options = screen.getAllByRole("option", HIDDEN);
    expect(options).toHaveLength(2);
    expect(options[0]).toHaveAttribute("aria-label", "LHR, Heathrow Airport, London, GB");
    expect(options[0]).toHaveTextContent("LHR");
    expect(options[0]).toHaveTextContent("Heathrow Airport");
    expect(options[1]).toHaveTextContent("LGW");
  });

  it("is a combobox that points at its list while it is open", async () => {
    vi.mocked(api).mockResolvedValue({ airports: [heathrow, gatwick] } as never);
    await typeInto("lond");
    expect(field()).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("listbox", HIDDEN)).toHaveAttribute("id", field().getAttribute("aria-controls"));
  });

  it("moves through the options with the arrow keys and takes one with Enter", async () => {
    vi.mocked(api).mockResolvedValue({ airports: [heathrow, gatwick] } as never);
    await typeInto("lond");
    await userEvent.keyboard("{ArrowDown}");
    await userEvent.keyboard("{ArrowDown}");
    expect(field().getAttribute("aria-activedescendant")).toBe(screen.getAllByRole("option", HIDDEN)[1]!.id);
    await userEvent.keyboard("{Enter}");
    expect(field()).toHaveValue("LGW");
    expect(field()).toHaveAttribute("aria-expanded", "false");
  });

  it("takes an option by clicking it", async () => {
    vi.mocked(api).mockResolvedValue({ airports: [heathrow, gatwick] } as never);
    await typeInto("lond");
    await userEvent.click(screen.getAllByRole("option", HIDDEN)[0]!);
    expect(field()).toHaveValue("LHR");
  });

  it("closes on Escape and keeps what was typed", async () => {
    vi.mocked(api).mockResolvedValue({ airports: [heathrow, gatwick] } as never);
    await typeInto("lond");
    await userEvent.keyboard("{Escape}");
    expect(field()).toHaveAttribute("aria-expanded", "false");
    expect(field()).toHaveValue("lond");
  });

  it("keeps a typed code that matches nothing", async () => {
    vi.mocked(api).mockResolvedValue({ airports: [] } as never);
    await typeInto("xyz");
    expect(screen.queryAllByRole("option", HIDDEN)).toHaveLength(0);
    expect(field()).toHaveValue("xyz");
  });

  it("keeps the invalid mark and the description link", () => {
    render(AirportField, { props: { value: "", placeholder: "LHR", field: "origin", invalid: true, describedby: "why" } });
    expect(field()).toHaveAttribute("aria-invalid", "true");
    expect(field()).toHaveAttribute("aria-describedby", "why");
  });

  it("does not ask for a single character", async () => {
    await typeInto("l");
    expect(api).not.toHaveBeenCalled();
  });

  it("offers nothing when the search fails", async () => {
    vi.mocked(api).mockRejectedValue(new Error("offline"));
    await typeInto("lon");
    expect(screen.queryAllByRole("option", HIDDEN)).toHaveLength(0);
  });
});
