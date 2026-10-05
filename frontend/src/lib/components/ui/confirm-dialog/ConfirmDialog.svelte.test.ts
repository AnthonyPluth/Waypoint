// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ConfirmHarness from "./ConfirmHarness.test.svelte";

describe("ConfirmDialog", () => {
  it("is a labelled dialog that takes focus, closes with Esc and gives focus back", async () => {
    const onconfirm = vi.fn();
    render(ConfirmHarness, { onconfirm });
    const user = userEvent.setup();
    const trigger = screen.getByRole("button", { name: "Delete it" });
    await user.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "Delete the thing?" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleDescription("It goes for good.");
    await waitFor(() => expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus());
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(onconfirm).not.toHaveBeenCalled();
  });

  it("closes from Cancel without confirming", async () => {
    const onconfirm = vi.fn();
    render(ConfirmHarness, { onconfirm, open: true });
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(onconfirm).not.toHaveBeenCalled();
  });

  it("waits for the typed word, shows it's busy, then closes", async () => {
    let finish = () => {};
    const onconfirm = vi.fn(() => new Promise<void>((r) => (finish = r)));
    render(ConfirmHarness, { onconfirm, typeToConfirm: "RESTORE", open: true });
    const user = userEvent.setup();
    const go = await screen.findByRole("button", { name: "Delete" });
    expect(go).toBeDisabled();
    const box = screen.getByLabelText(/Type RESTORE to confirm/);
    await waitFor(() => expect(box).toHaveFocus());
    await user.type(box, "restore");
    expect(go).toBeDisabled();
    await user.clear(box);
    await user.type(box, "RESTORE");
    expect(go).toBeEnabled();
    await user.click(go);
    expect(onconfirm).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Deleting…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    finish();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("confirms with Enter, and stays open when onconfirm returns false", async () => {
    const onconfirm = vi.fn(async () => false);
    render(ConfirmHarness, { onconfirm, typeToConfirm: "RESTORE", open: true });
    const user = userEvent.setup();
    const box = await screen.findByLabelText(/Type RESTORE to confirm/);
    await user.type(box, "RESTORE{Enter}");
    expect(onconfirm).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.getByRole("button", { name: "Delete" })).toBeEnabled());
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
