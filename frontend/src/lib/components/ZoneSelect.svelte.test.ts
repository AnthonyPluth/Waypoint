// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import ZoneSelect from "./ZoneSelect.svelte";

describe("ZoneSelect", () => {
  it("is a drop-down with a blank choice that says what happens when nothing is chosen", async () => {
    render(ZoneSelect, { value: "", blank: "Work it out from the airport", label: "Zone" });
    const select = screen.getByRole("combobox", { name: "Zone" });
    expect(select.tagName).toBe("SELECT");
    expect(screen.getByRole("option", { name: "Work it out from the airport" })).toBeInTheDocument();
    await userEvent.selectOptions(select, "Europe/London");
    expect(select).toHaveValue("Europe/London");
  });

  it("keeps a stored zone that isn't in the list", () => {
    render(ZoneSelect, { value: "Etc/Made_Up", blank: "None", label: "Zone" });
    expect(screen.getByRole("combobox", { name: "Zone" })).toHaveValue("Etc/Made_Up");
  });
});
