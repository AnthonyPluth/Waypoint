// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import AddressLink from "./AddressLink.svelte";

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
});
