// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "$lib/api";
import AirportField from "./AirportField.svelte";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));

const heathrow = { code: "LHR", name: "Heathrow Airport", city: "London", country: "GB", zone: "Europe/London" };

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
    vi.mocked(api).mockResolvedValue({ airports: [heathrow] } as never);
    await typeInto("lond");
    expect(api).toHaveBeenCalledWith("/api/airports?q=lond");
    const option = document.querySelector("datalist option") as HTMLOptionElement;
    expect(option.value).toBe("LHR");
    expect(option.label).toBe("Heathrow Airport, London, GB");
  });

  it("does not ask for a single character", async () => {
    await typeInto("l");
    expect(api).not.toHaveBeenCalled();
  });

  it("offers nothing when the search fails", async () => {
    vi.mocked(api).mockRejectedValue(new Error("offline"));
    await typeInto("lon");
    expect(document.querySelectorAll("datalist option")).toHaveLength(0);
  });
});
