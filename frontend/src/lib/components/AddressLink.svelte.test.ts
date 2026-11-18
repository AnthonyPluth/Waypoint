// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import AddressLink from "./AddressLink.svelte";

const toasts = vi.hoisted(() => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));
vi.mock("svelte-sonner", () => toasts);

function toastCalls() { const t = toasts.toast; return t.mock.calls.length + t.success.mock.calls.length + t.error.mock.calls.length; }

describe("AddressLink", () => {
  it("copies the full address and offers directions", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(AddressLink, { address: "1 Main St, Austin, TX 78701", text: "Austin, TX" });
    await userEvent.click(screen.getByRole("button", { name: /copy address/i }));
    expect(writeText).toHaveBeenCalledWith("1 Main St, Austin, TX 78701");
    expect(await screen.findByRole("link", { name: "Google Maps" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Uber" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Lyft" })).toBeTruthy();
  });

  it("shows no toast on a tap, so nothing covers the sheet's options", async () => {
    Object.defineProperty(navigator, "clipboard", { value: { writeText: vi.fn().mockResolvedValue(undefined) }, configurable: true });
    render(AddressLink, { address: "1 Main St, Austin, TX 78701", text: "Austin, TX" });
    await userEvent.click(screen.getByRole("button", { name: /copy address/i }));
    for (const name of ["Google Maps", "Uber", "Lyft"]) expect(await screen.findByRole("link", { name })).toBeTruthy();
    expect(toastCalls()).toBe(0);
  });

  it("shows no toast and still opens the sheet when the copy fails", async () => {
    Object.defineProperty(navigator, "clipboard", { value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) }, configurable: true });
    render(AddressLink, { address: "1 Main St, Austin, TX 78701" });
    await userEvent.click(screen.getByRole("button", { name: /copy address/i }));
    expect(await screen.findByRole("link", { name: "Uber" })).toBeTruthy();
    expect(toastCalls()).toBe(0);
  });
});
