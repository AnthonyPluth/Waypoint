// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Person } from "$lib/api-types";
import TravellerAvatars from "./TravellerAvatars.svelte";

const person = (id: number, display_name: string): Person => ({ id, display_name, first_name: display_name.split(" ")[0], legal_name: null, aliases: [], member: true, links: [] });
const twins = [person(1, "Jane Doe"), person(3, "Jane Doe"), person(2, "Sam Doe")];

describe("TravellerAvatars", () => {
  it("names each person and keeps (you) on the signed-in one when two share a name", () => {
    render(TravellerAvatars, { people: twins, selected: 1, onpick: () => {}, me: 1 });
    expect(screen.getByRole("button", { name: "Jane Doe (you)" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Jane Doe" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Sam Doe" })).toHaveAttribute("data-initials", "SD");
  });

  it("presses a person to pick them and the selected one to clear", async () => {
    const onpick = vi.fn();
    render(TravellerAvatars, { people: [person(1, "Jane Doe"), person(2, "Sam Doe")], selected: 2, onpick });
    await userEvent.click(screen.getByRole("button", { name: "Sam Doe" }));
    await userEvent.click(screen.getByRole("button", { name: "Jane Doe" }));
    expect(onpick).toHaveBeenNthCalledWith(1, null);
    expect(onpick).toHaveBeenNthCalledWith(2, 1);
  });

  it("shows an Everyone chip only when asked", async () => {
    const pick = vi.fn();
    const { unmount } = render(TravellerAvatars, { people: [], selected: null, onpick: () => {} });
    expect(screen.queryByRole("button", { name: "Everyone" })).toBeNull();
    unmount();
    render(TravellerAvatars, { people: [], selected: null, onpick: () => {}, everyone: { on: true, onpick: pick } });
    const chip = screen.getByRole("button", { name: "Everyone" });
    expect(chip).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(chip);
    expect(pick).toHaveBeenCalledOnce();
  });
});
