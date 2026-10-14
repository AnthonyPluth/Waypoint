// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn() }));

import { api } from "$lib/api";
import LogosSection from "./LogosSection.svelte";

describe("Settings → Brand logos", () => {
  it("explains bundled logos without requiring a connection or a key", () => {
    render(LogosSection);
    expect(screen.getByText(/included with Waypoint/)).toBeInTheDocument();
    expect(screen.getByText(/no account or API key/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
    expect(api).not.toHaveBeenCalled();
  });
});
