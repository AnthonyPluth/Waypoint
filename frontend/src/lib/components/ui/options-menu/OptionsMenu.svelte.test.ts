// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import Harness from "./OptionsMenuHarness.test.svelte";
import PopupHarness from "./OptionsMenuPopupHarness.test.svelte";

describe("OptionsMenu", () => {
  it("keeps its choices out of the way until it is opened, and says whether it is open", async () => {
    render(Harness, { onmerge: vi.fn(), ondelete: vi.fn() });
    const trigger = screen.getByRole("button", { name: "Trip options" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: "Delete trip" })).toBeNull();
    await userEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(trigger).not.toHaveAttribute("aria-haspopup");
    expect(trigger).toHaveAttribute("aria-controls", screen.getByRole("group", { name: "Trip options" }).id);
    expect(screen.getByRole("button", { name: "Merge another trip" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete trip" })).toBeInTheDocument();
  });

  it("opens and chooses from the keyboard, closing and keeping focus on its button", async () => {
    const ondelete = vi.fn();
    render(Harness, { onmerge: vi.fn(), ondelete });
    const user = userEvent.setup();
    const trigger = screen.getByRole("button", { name: "Trip options" });
    trigger.focus();
    await user.keyboard("{Enter}");
    await user.tab();
    await user.tab();
    expect(screen.getByRole("button", { name: "Delete trip" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(ondelete).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: "Delete trip" })).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("closes with Escape and returns focus to its button", async () => {
    render(Harness, { onmerge: vi.fn(), ondelete: vi.fn() });
    const user = userEvent.setup();
    const trigger = screen.getByRole("button", { name: "Trip options" });
    await user.click(trigger);
    await user.tab();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("button", { name: "Merge another trip" })).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("closes when focus or a click goes elsewhere, without choosing anything", async () => {
    const onmerge = vi.fn();
    const ondelete = vi.fn();
    render(Harness, { onmerge, ondelete });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Trip options" }));
    await user.click(screen.getByRole("button", { name: "After" }));
    expect(screen.queryByRole("button", { name: "Delete trip" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Trip options" }));
    await user.tab({ shift: true });
    expect(screen.queryByRole("button", { name: "Delete trip" })).toBeNull();
    expect(onmerge).not.toHaveBeenCalled();
    expect(ondelete).not.toHaveBeenCalled();
  });

  it("is a menu of menu items, with its icons and a divider, when it is told it is a popup", async () => {
    render(PopupHarness, { onmerge: vi.fn(), ondelete: vi.fn() });
    const trigger = screen.getByRole("button", { name: "Trip options" });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    await userEvent.click(trigger);
    const menu = screen.getByRole("menu", { name: "Trip options" });
    expect(trigger).toHaveAttribute("aria-controls", menu.id);
    expect(screen.queryByRole("group", { name: "Trip options" })).toBeNull();
    const items = within(menu).getAllByRole("menuitem");
    expect(items.map((i) => i.textContent?.trim())).toEqual(["Merge another trip", "Delete trip"]);
    expect(items.every((i) => i.querySelector("svg"))).toBe(true);
    expect(within(menu).getByRole("separator")).toBeInTheDocument();
    await userEvent.click(items[1]);
    expect(screen.queryByRole("menu")).toBeNull();
    expect(trigger).toHaveFocus();
  });
});
