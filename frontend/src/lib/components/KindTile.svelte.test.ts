// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import KindTile from "./KindTile.svelte";

const NAMES = [
  ["flight", "flight"],
  ["hotel", "stay"],
  ["car", "rental car"],
  ["train", "train"],
  ["cruise", "cruise"],
  ["parking", "parking"],
  ["visit", "past visit"],
] as const;

describe("KindTile", () => {
  it.each(NAMES)("names a %s tile %s", (kind, name) => {
    render(KindTile, { kind });
    const tile = screen.getByRole("img", { name });
    expect(tile.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  });
  it("is hidden from assistive tech when decorative", () => {
    const { container } = render(KindTile, { kind: "flight", decorative: true });
    expect(screen.queryByRole("img")).toBeNull();
    const tile = container.querySelector("[data-tile]")!;
    expect(tile.getAttribute("aria-hidden")).toBe("true");
    expect(tile.getAttribute("aria-label")).toBeNull();
  });
  it("comes in 28 and 36 pixel sizes", () => {
    const small = render(KindTile, { kind: "hotel" });
    expect(small.container.querySelector("[data-tile]")!.className).toContain("size-7");
    small.unmount();
    const large = render(KindTile, { kind: "hotel", size: 36 });
    expect(large.container.querySelector("[data-tile]")!.className).toContain("size-9");
  });
  it("uses the kind's colour on its tint", () => {
    const { container } = render(KindTile, { kind: "train" });
    const cls = container.querySelector("[data-tile]")!.className;
    expect(cls).toContain("bg-kind-train-soft");
    expect(cls).toContain("text-kind-train");
  });
  it("uses the quiet pair for cruise, parking and a past visit", () => {
    for (const kind of ["cruise", "parking", "visit"] as const) {
      const { container, unmount } = render(KindTile, { kind });
      expect(container.querySelector("[data-tile]")!.className).toContain("bg-kind-quiet-soft");
      unmount();
    }
  });
});
