// @vitest-environment jsdom
/// <reference types="node" />
import { readFileSync } from "node:fs";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { viewport } from "$lib/phone.svelte";
import SheetHarness from "./SheetHarness.test.svelte";

beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([{}] as unknown as DOMRectList);
});
afterEach(() => { viewport.phone = false; vi.restoreAllMocks(); });

const drag = (handle: Element, from: number, to: number) => {
  handle.dispatchEvent(new MouseEvent("pointerdown", { clientY: from, bubbles: true }));
  handle.dispatchEvent(new MouseEvent("pointermove", { clientY: to, bubbles: true }));
  handle.dispatchEvent(new MouseEvent("pointerup", { clientY: to, bubbles: true }));
};

describe("Sheet", () => {
  it("is a labelled, described dialog that takes focus and gives it back to what opened it on Escape", async () => {
    render(SheetHarness);
    const user = userEvent.setup();
    const trigger = screen.getByRole("button", { name: "Open it" });
    await user.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "Edit this thing" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleDescription("Changes are kept.");
    await waitFor(() => expect(dialog).toContainElement(document.activeElement as HTMLElement));
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("closes from the close button and gives focus back", async () => {
    render(SheetHarness);
    const user = userEvent.setup();
    const trigger = screen.getByRole("button", { name: "Open it" });
    await user.click(trigger);
    await user.click(await screen.findByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("closes when the dimmed page is tapped", async () => {
    render(SheetHarness);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open it" }));
    await screen.findByRole("dialog");
    const overlay = document.querySelector("[data-slot='sheet-overlay']") as HTMLElement;
    overlay.dispatchEvent(new MouseEvent("pointerdown", { clientX: 500, clientY: 500, bubbles: true }));
    overlay.dispatchEvent(new MouseEvent("pointerup", { clientX: 500, clientY: 500, bubbles: true }));
    overlay.dispatchEvent(new MouseEvent("click", { clientX: 500, clientY: 500, bubbles: true }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("traps focus: Tab never leaves the sheet, and focus sent to the page behind comes back inside", async () => {
    render(SheetHarness);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open it" }));
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(dialog).toContainElement(document.activeElement as HTMLElement));
    const save = screen.getByRole("button", { name: "Save it" });
    save.focus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
    await user.tab({ shift: true });
    expect(save).toHaveFocus();
    for (let i = 0; i < 6; i++) {
      await user.tab();
      expect(dialog).toContainElement(document.activeElement as HTMLElement);
    }
    for (let i = 0; i < 6; i++) {
      await user.tab({ shift: true });
      expect(dialog).toContainElement(document.activeElement as HTMLElement);
    }
    screen.getByRole("button", { name: "Elsewhere", hidden: true }).focus();
    await waitFor(() => expect(dialog).toContainElement(document.activeElement as HTMLElement));
  });

  it("is a side panel on a desktop, with no grab handle", async () => {
    render(SheetHarness, { open: true });
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveAttribute("data-side", "right");
    expect(dialog.querySelector("[data-sheet-handle]")).toBeNull();
  });

  describe("on a phone", () => {
    it("is a bottom sheet that closes when swiped down far enough", async () => {
      viewport.phone = true;
      render(SheetHarness, { open: true });
      const dialog = await screen.findByRole("dialog");
      expect(dialog).toHaveAttribute("data-side", "bottom");
      drag(dialog.querySelector("[data-sheet-handle]")!, 100, 260);
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    });

    it("stays open, back in place, when swiped only a little", async () => {
      viewport.phone = true;
      render(SheetHarness, { open: true });
      const dialog = await screen.findByRole("dialog");
      const handle = dialog.querySelector("[data-sheet-handle]")!;
      handle.dispatchEvent(new MouseEvent("pointerdown", { clientY: 100, bubbles: true }));
      handle.dispatchEvent(new MouseEvent("pointermove", { clientY: 140, bubbles: true }));
      await waitFor(() => expect(dialog).toHaveStyle("--sheet-drag: 40px"));
      handle.dispatchEvent(new MouseEvent("pointerup", { clientY: 140, bubbles: true }));
      await waitFor(() => expect(dialog.getAttribute("style") ?? "").not.toContain("--sheet-drag"));
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });

    it("does not move up when dragged upward", async () => {
      viewport.phone = true;
      render(SheetHarness, { open: true });
      const dialog = await screen.findByRole("dialog");
      const handle = dialog.querySelector("[data-sheet-handle]")!;
      await fireEvent(handle, new MouseEvent("pointerdown", { clientY: 200, bubbles: true }));
      await fireEvent(handle, new MouseEvent("pointermove", { clientY: 120, bubbles: true }));
      expect(dialog.getAttribute("style") ?? "").not.toContain("--sheet-drag: 80px");
    });
  });

  it("slides in normally, and has no motion at all for someone who asked for reduced motion", () => {
    const css = readFileSync("src/app.css", "utf8");
    expect(css).toMatch(/\.sheet\[data-side="bottom"\]\[data-state="open"\] \{ animation: sheet-rise/);
    const reduced = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"));
    expect(reduced).toMatch(/animation-duration: 0\.01ms !important/);
    expect(reduced).not.toMatch(/sheet-/);
  });

});
