// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import AirportCode from "./AirportCode.svelte";

describe("AirportCode", () => {
  it("shows the code in the large monospace type", () => {
    render(AirportCode, { code: "MSP" });
    const el = screen.getByText("MSP");
    expect(el.tagName).toBe("SPAN");
    expect(el.className).toContain("font-mono");
    expect(el.className).toContain("text-display");
  });
  it("names the airport when it is given one", () => {
    render(AirportCode, { code: "LAX", name: "Los Angeles" });
    const el = screen.getByText("LAX");
    expect(el.tagName).toBe("ABBR");
    expect(el.getAttribute("title")).toBe("Los Angeles");
  });
  it("comes in three sizes", () => {
    for (const [size, cls] of [["large", "text-display"], ["medium", "text-title"], ["small", "text-heading"]] as const) {
      const { unmount } = render(AirportCode, { code: size, size });
      expect(screen.getByText(size).className).toContain(cls);
      unmount();
    }
  });
});
