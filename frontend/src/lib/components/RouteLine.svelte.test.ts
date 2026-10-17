// @vitest-environment jsdom
import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import RouteLine, { clampProgress, headingDegrees, travelledPath } from "./RouteLine.svelte";

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
  it("draws the route as one arch, dashed behind and a solid path of the same arch up to the plane", () => {
    const { container } = render(RouteLine, { progress: 0.3 });
    const paths = [...container.querySelectorAll("svg[preserveAspectRatio] path")];
    expect(paths.map((p) => p.getAttribute("d"))).toEqual(["M0 100 Q50 0 100 100", "M0 100 Q15 70 30 58"]);
    expect(paths[0].getAttribute("stroke-dasharray")).toBe("4 4");
    expect(paths[1].getAttribute("stroke-dasharray")).toBeNull();
    expect(container.querySelector("svg[style*='clip-path']")).toBeNull();
  });
  it("draws no solid path at the start and the whole arch at the end", () => {
    const start = render(RouteLine, { progress: 0 });
    expect(start.container.querySelectorAll("svg[preserveAspectRatio] path")).toHaveLength(1);
    start.unmount();
    const end = render(RouteLine, { progress: 1 });
    expect([...end.container.querySelectorAll("svg[preserveAspectRatio] path")].map((p) => p.getAttribute("d"))).toEqual(["M0 100 Q50 0 100 100", "M0 100 Q50 0 100 100"]);
  });
  it("travelledPath stays on the arch: its end is where the plane sits", () => {
    expect(travelledPath(0)).toBe("M0 100 Q0 100 0 100");
    expect(travelledPath(0.5)).toBe("M0 100 Q25 50 50 50");
    expect(travelledPath(1)).toBe("M0 100 Q50 0 100 100");
    expect(travelledPath(2)).toBe(travelledPath(1));
    expect(travelledPath(Number.NaN)).toBe(travelledPath(0));
  });
  it("centres the plane on the arch with one offset, at the start, the top and the end", () => {
    for (const [progress, top] of [[0, "100%"], [0.5, "50%"], [1, "100%"]] as const) {
      const { container, unmount } = render(RouteLine, { progress });
      const plane = container.querySelector("svg.lucide-plane") as SVGElement;
      expect(plane.getAttribute("style")).toContain(`top: ${top}`);
      expect(plane.getAttribute("style")).toContain("translate(-50%, -50%) rotate(45deg)");
      expect(plane.getAttribute("class")).not.toMatch(/translate/);
      unmount();
    }
  });
  it("turns the plane to the arch's slope in pixels: up on the way out, level at the top, down on the way in", () => {
    expect(headingDegrees(0, 300, 40)).toBe(-15);
    expect(headingDegrees(0.5, 300, 40)).toBe(0);
    expect(headingDegrees(1, 300, 40)).toBe(15);
    expect(headingDegrees(0, 100, 40)).toBeLessThan(headingDegrees(0, 300, 40));
    expect(headingDegrees(0, 0, 40)).toBe(0);
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
