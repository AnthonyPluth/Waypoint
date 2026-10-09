// @vitest-environment jsdom
import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import RouteLine, { clampProgress } from "./RouteLine.svelte";

const line = (container: HTMLElement) => container.firstElementChild as HTMLElement;
const along = (container: HTMLElement) => (container.querySelector("[style*='--along']") as HTMLElement).style.getPropertyValue("--along");

describe("RouteLine", () => {
  it("puts the plane at the origin with no progress", () => {
    const { container } = render(RouteLine);
    expect(line(container).dataset.progress).toBe("0");
    expect(along(container)).toBe("0%");
  });
  it("places the plane at 0, halfway and at 1", () => {
    for (const [progress, percent] of [[0, "0%"], [0.5, "50%"], [1, "100%"]] as const) {
      const { container, unmount } = render(RouteLine, { progress });
      expect(line(container).dataset.progress).toBe(String(progress));
      expect(along(container)).toBe(percent);
      unmount();
    }
  });
  it("keeps the plane on the line", () => {
    expect(clampProgress(-1)).toBe(0);
    expect(clampProgress(2)).toBe(1);
    expect(clampProgress(Number.NaN)).toBe(0);
    expect(clampProgress(null)).toBe(0);
    expect(clampProgress(undefined)).toBe(0);
    expect(clampProgress(0.25)).toBe(0.25);
  });
  it("is decoration unless it has a label", () => {
    const { container, unmount } = render(RouteLine, { progress: 0.4 });
    expect(line(container).getAttribute("aria-hidden")).toBe("true");
    expect(line(container).getAttribute("role")).toBeNull();
    unmount();
    const labelled = render(RouteLine, { progress: 0.4, label: "Based on the booked times" });
    expect(line(labelled.container).getAttribute("role")).toBe("img");
    expect(line(labelled.container).getAttribute("aria-label")).toBe("Based on the booked times");
    expect(line(labelled.container).getAttribute("aria-hidden")).toBeNull();
  });
});
