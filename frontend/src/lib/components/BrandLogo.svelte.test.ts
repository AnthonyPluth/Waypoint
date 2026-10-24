// @vitest-environment jsdom
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import BrandLogo from "./BrandLogo.svelte";

describe("BrandLogo", () => {
  it("shows the logo it is given, as decoration, at its size", () => {
    const { container } = render(BrandLogo, { src: "/api/segments/4/logo", size: 32 });
    const img = container.querySelector("img")!;
    expect(img.getAttribute("src")).toBe("/api/segments/4/logo");
    expect(img.getAttribute("alt")).toBe("");
    expect(img.getAttribute("width")).toBe("32");
  });

  it("fits the logo inside a white tile of its size, whatever the image's own shape", () => {
    const { container } = render(BrandLogo, { src: "/api/segments/4/logo", size: 36 });
    const tile = container.querySelector("img")!.parentElement as HTMLElement;
    expect(tile.style.width).toBe("36px");
    expect(tile.style.height).toBe("36px");
    expect(tile.style.padding).toBe("5px");
    expect(tile).toHaveClass("bg-white", "overflow-hidden");
    expect(container.querySelector("img")).toHaveClass("h-full", "w-full", "object-contain");
  });

  it("names the hotel brand under its group's logo, and only when it is given one", async () => {
    const { container, rerender } = render(BrandLogo, { src: "/api/segments/4/logo", label: "Hyatt Regency" });
    expect(container.textContent).toContain("Hyatt Regency");
    await rerender({ src: "/api/segments/4/logo", label: null });
    expect(container.textContent?.trim()).toBe("");
  });

  it("shows nothing without a logo", () => {
    const { container } = render(BrandLogo, { src: null, label: "Hyatt Regency" });
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent?.trim()).toBe("");
  });

  it("shows nothing when the image fails to load", async () => {
    const { container } = render(BrandLogo, { src: "/api/segments/4/logo" });
    await fireEvent.error(container.querySelector("img")!);
    expect(container.querySelector("img")).toBeNull();
  });

  it("shows a monogram circle of the given size in place of a missing or broken logo, only when asked to", async () => {
    const { container, rerender } = render(BrandLogo, { src: null, size: 20, monogram: "global Entry" });
    const mark = container.querySelector("span[aria-hidden='true']") as HTMLElement;
    expect(mark.textContent).toBe("g");
    expect(mark.style.width).toBe("20px");
    expect(mark.style.height).toBe("20px");
    await rerender({ src: null, size: 20, monogram: null });
    expect(container.querySelector("span")).toBeNull();
    await rerender({ src: "/api/loyalty/1/logo", size: 20, monogram: "Hilton Honors" });
    container.querySelector("img")!.dispatchEvent(new Event("error"));
    await waitFor(() => expect(container.querySelector("img")).toBeNull());
    expect(container.querySelector("span[aria-hidden='true']")?.textContent).toBe("H");
  });
});
