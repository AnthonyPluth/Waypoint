// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import { membership } from "../../test/fixtures";
import LoyaltyNumber from "./LoyaltyNumber.svelte";

describe("LoyaltyNumber", () => {
  it("keeps a phone-sized tap target without making its row taller than the text beside it", () => {
    render(LoyaltyNumber, { entry: membership() });
    const button = screen.getByRole("button", { name: /Show and copy .* number/ });
    expect(button).toHaveTextContent("••••");
    expect(button.className).toContain("phone:min-h-11");
    expect(button.className).toContain("phone:-my-3");
  });

  it("says when a number can't be read with this key", () => {
    render(LoyaltyNumber, { entry: membership({ readable: false }) });
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/Can’t be read with this key/)).toBeInTheDocument();
  });
});
