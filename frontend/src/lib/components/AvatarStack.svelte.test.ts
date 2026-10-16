// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import { AVATAR_TONES, avatarTone } from "$lib/avatar";
import AvatarStack from "./AvatarStack.svelte";

const names = ["Jane Doe", "Mia Doe", "Sam Roe", "Lee Poe", "Ann Coe", "Bob Foe"];
const people = names.map((name, i) => ({ id: i + 1, name }));
const circles = (container: HTMLElement) => [...container.querySelectorAll('[data-testid="avatar-stack"] > span')];

describe("AvatarStack", () => {
  it("shows initials and one label listing the names", () => {
    const { container } = render(AvatarStack, { people: people.slice(0, 2) });
    expect(screen.getByRole("img", { name: "Jane Doe, Mia Doe" })).toBeTruthy();
    expect(circles(container).map((c) => c.textContent)).toEqual(["JD", "MD"]);
    expect(circles(container).every((c) => c.getAttribute("aria-hidden") === "true")).toBe(true);
  });
  it("shows up to four people with no overflow", () => {
    const { container } = render(AvatarStack, { people: people.slice(0, 4) });
    expect(circles(container)).toHaveLength(4);
    expect(container.textContent).not.toContain("+");
  });
  it("shows four and a +N circle from five people, the label naming everyone", () => {
    const { container } = render(AvatarStack, { people });
    expect(circles(container).map((c) => c.textContent)).toEqual(["JD", "MD", "SR", "LP", "+2"]);
    expect(screen.getByRole("img").getAttribute("aria-label")).toBe(names.join(", "));
  });
  it("counts one hidden person at five", () => {
    const { container } = render(AvatarStack, { people: people.slice(0, 5) });
    expect(circles(container).at(-1)!.textContent).toBe("+1");
  });
  it("gives the same person the same colour across renders", () => {
    const first = render(AvatarStack, { people: people.slice(0, 3) });
    const before = circles(first.container).map((c) => c.className);
    first.unmount();
    const second = render(AvatarStack, { people: people.slice(0, 3) });
    expect(circles(second.container).map((c) => c.className)).toEqual(before);
  });
  it("picks by id when there is one, and by name for a guest", () => {
    expect(avatarTone({ id: 3, name: "A" })).toBe(avatarTone({ id: 3, name: "B" }));
    expect(avatarTone({ id: 1, name: "A" })).not.toBe(avatarTone({ id: 2, name: "A" }));
    expect(avatarTone({ name: "Guest One" })).toBe(avatarTone({ id: null, name: "Guest One" }));
    expect(AVATAR_TONES).toContain(avatarTone({ name: "Guest One" }));
  });
  it("renders nothing for nobody", () => {
    render(AvatarStack, { people: [] });
    expect(screen.queryByRole("img")).toBeNull();
  });
});
