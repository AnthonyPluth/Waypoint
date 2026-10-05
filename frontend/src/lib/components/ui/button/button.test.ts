import { describe, expect, it } from "vitest";
import { buttonVariants } from "./button.svelte";

describe("buttonVariants", () => {
  it("makes a button at least 44px on a phone, and an icon button 44px square", () => {
    expect(buttonVariants({ variant: "outline", size: "sm" })).toContain("phone:min-h-11");
    expect(buttonVariants({})).toContain("phone:min-h-11");
    expect(buttonVariants({ variant: "ghost", size: "icon" })).toContain("phone:min-w-11");
  });

  it("leaves a link-styled button its size, as it often sits in a line of text", () => {
    expect(buttonVariants({ variant: "link", size: "sm" })).not.toContain("phone:min-h-11");
  });
});
