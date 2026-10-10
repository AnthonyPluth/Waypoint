// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import TopList, { type Row } from "./TopList.svelte";

const longName = "Santa Cruz / Monterey Bay KOA Holiday Resort and Campground at the Beach";
const rows: Row[] = [
  { key: "long", name: longName, sub: "2 stays", value: "6 nights" },
  { key: "short", name: "Quay Inn", sub: null, value: "4 nights" },
];

describe("TopList", () => {
  it("keeps a long name's value in the same row, to its right, without wrapping", () => {
    render(TopList, { title: "Hotels stayed at", rows });
    const row = screen.getByText(longName).closest("li")!;
    const value = within(row).getByText("6 nights");
    expect(row.className).toContain("flex-nowrap");
    expect(value.className).toContain("shrink-0");
    expect(value.className).toContain("whitespace-nowrap");
  });

  it("truncates a long name instead of wrapping it, and keeps the full name as its title", () => {
    render(TopList, { title: "Hotels stayed at", rows });
    const name = screen.getByText(longName);
    expect(name.className).toContain("truncate");
    expect(name.getAttribute("title")).toBe(longName);
    expect(within(name.closest("li")!).getByText("2 stays")).toBeInTheDocument();
  });

  it("truncates a long sub line too, with its full text as the title", () => {
    const longSub = "Seven stays across three different cities in one long trip";
    render(TopList, { title: "Cities stayed in", rows: [{ key: "s", name: "London", sub: longSub, value: "9 nights" }] });
    const sub = screen.getByText(longSub);
    expect(sub.className).toContain("truncate");
    expect(sub.getAttribute("title")).toBe(longSub);
  });

  it("keeps a short-name row as before, with its rank, name and value on one row", () => {
    render(TopList, { title: "Hotels stayed at", rows });
    const row = screen.getByText("Quay Inn").closest("li")!;
    expect(within(row).getByText("2")).toBeInTheDocument();
    expect(within(row).getByText("4 nights").className).toContain("shrink-0");
    expect(screen.getByText("Quay Inn").getAttribute("title")).toBe("Quay Inn");
    expect(row.querySelector("p.text-sm")).toBeNull();
  });
});
