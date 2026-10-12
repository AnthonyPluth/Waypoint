// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import ZoneSelect from "./ZoneSelect.svelte";

const HIDDEN = { hidden: true };
const field = () => screen.getByRole("combobox", { name: "Zone" });
const optionNames = () => screen.queryAllByRole("option", HIDDEN).map((option) => option.getAttribute("aria-label") ?? option.textContent ?? "");

async function open(value = "", blank = "Work it out from the airport") {
  const result = render(ZoneSelect, { value, blank, label: "Zone" });
  await userEvent.click(field());
  return result;
}

afterEach(() => vi.unstubAllGlobals());

describe("ZoneSelect", () => {
  it("is a combobox named by its label that shows the blank wording while empty", async () => {
    render(ZoneSelect, { value: "", blank: "Work it out from the airport", label: "Zone" });
    expect(field().tagName).toBe("INPUT");
    expect(field()).toHaveAttribute("aria-expanded", "false");
    expect(field()).toHaveAttribute("placeholder", "Work it out from the airport");
    expect(field()).toHaveValue("");
  });

  it("offers the blank choice first when empty", async () => {
    await open();
    const first = screen.getAllByRole("option", HIDDEN)[0]!;
    expect(first).toHaveTextContent("Work it out from the airport");
    expect(field()).toHaveAttribute("aria-expanded", "true");
  });

  it("filters as you type and fills the field with the choice", async () => {
    await open();
    await userEvent.keyboard("Chicago");
    expect(optionNames()[0]).toBe("America/Chicago, Central Time");
    await userEvent.click(screen.getAllByRole("option", HIDDEN)[0]!);
    expect(field()).toHaveValue("America/Chicago");
    expect(field()).toHaveAttribute("aria-expanded", "false");
  });

  it("shows underscores as spaces", () => {
    render(ZoneSelect, { value: "America/Los_Angeles", blank: "None", label: "Zone" });
    expect(field()).toHaveValue("America/Los Angeles");
  });

  it("finds a state, a common name and a country", async () => {
    await open();
    await userEvent.keyboard("Illinois");
    expect(optionNames()).toContain("America/Chicago, Central Time");
    await userEvent.clear(field());
    await userEvent.keyboard("Japan");
    expect(optionNames()).toContain("Asia/Tokyo, Japan Standard Time");
  });

  it("shows at most ten matches", async () => {
    await open();
    await userEvent.keyboard("a");
    expect(screen.getAllByRole("option", HIDDEN).length).toBeLessThanOrEqual(10);
  });

  it("says when nothing matches", async () => {
    await open();
    await userEvent.keyboard("qqqqzzzz");
    expect(optionNames()).toEqual(["No matching time zone"]);
    expect(screen.getByText("No matching time zone")).toHaveAttribute("data-disabled");
  });

  it("offers Clear with the field's own wording when it has a value, and clears", async () => {
    render(ZoneSelect, { value: "Europe/London", blank: "Same as where it starts", label: "Zone" });
    await userEvent.click(field());
    const clear = screen.getAllByRole("option", HIDDEN)[0]!;
    expect(clear).toHaveTextContent("Clear");
    expect(clear).toHaveTextContent("Same as where it starts");
    await userEvent.click(clear);
    await waitFor(() => expect(field()).toHaveValue(""));
  });

  it("keeps a stored zone that isn't in the list", async () => {
    render(ZoneSelect, { value: "Etc/Made_Up", blank: "None", label: "Zone" });
    expect(field()).toHaveValue("Etc/Made Up");
    await userEvent.click(field());
    expect(screen.getAllByRole("option", HIDDEN).some((option) => option.textContent?.includes("Etc/Made Up"))).toBe(true);
    await userEvent.keyboard("{Escape}");
    expect(field()).toHaveValue("Etc/Made Up");
  });

  it("puts back the previous value when what was typed matches nothing and the field is left", async () => {
    render(ZoneSelect, { value: "Europe/London", blank: "None", label: "Zone" });
    await userEvent.click(field());
    await userEvent.clear(field());
    await userEvent.keyboard("nonsense");
    await userEvent.tab();
    await waitFor(() => expect(field()).toHaveValue("Europe/London"));
  });

  it("puts back the previous value on Escape", async () => {
    render(ZoneSelect, { value: "Europe/London", blank: "None", label: "Zone" });
    await userEvent.click(field());
    await userEvent.keyboard("Paris");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(field()).toHaveValue("Europe/London"));
    expect(field()).toHaveAttribute("aria-expanded", "false");
  });

  it("moves with Up and Down and picks with Enter", async () => {
    await open();
    await userEvent.keyboard("chi");
    const options = () => screen.getAllByRole("option", HIDDEN);
    await waitFor(() => expect(options().length).toBeGreaterThan(1));
    await waitFor(() => expect(field().getAttribute("aria-activedescendant")).toBe(options()[0]!.id));
    await userEvent.keyboard("{ArrowDown}");
    expect(field().getAttribute("aria-activedescendant")).toBe(options()[1]!.id);
    await userEvent.keyboard("{ArrowUp}");
    expect(field().getAttribute("aria-activedescendant")).toBe(options()[0]!.id);
    await userEvent.keyboard("{Enter}");
    expect(field()).toHaveValue("America/Chicago");
  });

  it("picks the highlighted match on Tab", async () => {
    await open();
    await userEvent.keyboard("tokyo");
    await waitFor(() => expect(field().getAttribute("aria-activedescendant")).toBeTruthy());
    await userEvent.tab();
    await waitFor(() => expect(field()).toHaveValue("Asia/Tokyo"));
  });

  it("points at its list and names each option with its current name", async () => {
    await open();
    await userEvent.keyboard("chicago");
    const listbox = screen.getByRole("listbox", HIDDEN);
    expect(field().getAttribute("aria-controls")).toBe(listbox.id);
    expect(optionNames()).toContain("America/Chicago, Central Time");
  });

  it("falls back to a plain text input when the browser can't list zones", async () => {
    vi.stubGlobal("Intl", { ...Intl, supportedValuesOf: undefined, DateTimeFormat: Intl.DateTimeFormat });
    render(ZoneSelect, { value: "", blank: "Work it out", label: "Zone" });
    const input = screen.getByLabelText("Zone");
    expect(input.tagName).toBe("INPUT");
    expect(input).not.toHaveAttribute("role", "combobox");
    await userEvent.type(input, "America/Denver");
    expect(input).toHaveValue("America/Denver");
  });
});
