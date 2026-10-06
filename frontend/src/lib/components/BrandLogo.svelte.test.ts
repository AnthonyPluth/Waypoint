// @vitest-environment jsdom
import { fireEvent, render } from "@testing-library/svelte";
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

  it("shows nothing without a logo", () => {
    const { container } = render(BrandLogo, { src: null });
    expect(container.querySelector("img")).toBeNull();
  });

  it("shows nothing when the image fails to load", async () => {
    const { container } = render(BrandLogo, { src: "/api/segments/4/logo" });
    await fireEvent.error(container.querySelector("img")!);
    expect(container.querySelector("img")).toBeNull();
  });
});
