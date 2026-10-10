// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import TopList from "./TopList.svelte";

const longName = "Santa Cruz / Monterey Bay KOA Holiday Resort and Campground, Outer Banks";

describe("TopList", () => {
  it("keeps a long name's value in the same row, to its right, and truncates the name rather than wrapping", () => {
    render(TopList, { title: "Hotels stayed at", rows: [{ key: "a", name: longName, sub: "2 stays", value: "6 nights" }] });
    const name = screen.getByText(longName);
    const value = screen.getByText("6 nights");
    const row = name.closest("li")!;
    expect(row).toContainElement(value);
    expect(row.className).toContain("flex-nowrap");
    expect(name.compareDocumentPosition(value) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(name.className).toContain("truncate");
    expect(value.className).toContain("shrink-0");
    expect(value.className).toContain("whitespace-nowrap");
  });

  it("gives the full name as its title, so a truncated name can still be read", () => {
    render(TopList, { title: "Airlines", rows: [{ key: "a", name: longName, value: "5 flights" }] });
    expect(screen.getByText(longName)).toHaveAttribute("title", longName);
  });

  it("keeps a short name's row in the same layout: rank, name, then the value on the right", () => {
    render(TopList, { title: "Airlines", rows: [{ key: "a", name: "Delta Air Lines", sub: "Atlanta", value: "7 flights" }] });
    const row = screen.getByText("Delta Air Lines").closest("li")!;
    expect(row).toHaveTextContent("1 Delta Air LinesAtlanta 7 flights");
    expect(row.lastElementChild).toHaveTextContent("7 flights");
    expect(row.lastElementChild!.className).toContain("shrink-0");
    expect(screen.getByText("Delta Air Lines")).toHaveAttribute("title", "Delta Air Lines");
  });

  it("truncates a long sub line without moving the value", () => {
    render(TopList, { title: "Airports", rows: [{ key: "a", name: "JFK", sub: longName, value: "10 visits" }] });
    const sub = screen.getByText(longName);
    expect(sub.className).toContain("truncate");
    expect(sub).toHaveAttribute("title", longName);
    expect(sub.closest("li")).toContainElement(screen.getByText("10 visits"));
  });
});
