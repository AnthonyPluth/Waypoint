// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn(), warning: vi.fn() }) }));

import { api } from "$lib/api";
import type { McpConnection, McpSettings } from "$lib/api-types";
import { toast } from "svelte-sonner";
import McpSection from "./McpSection.svelte";

const URL_ = "https://trips.example.com/mcp";
const view = (extra: Partial<McpSettings> = {}): McpSettings =>
  ({ allow_ids: false, allow_writes: false, oauth: true, url: URL_, reason: null, connections: [], ...extra });
const conn = (extra: Partial<McpConnection> = {}): McpConnection =>
  ({ id: 1, client: "Claude", who: "ana@example.com", scope: ["read"], created: "2026-09-01T10:00:00+00:00", last_used: null, ...extra });

type Opts = { method?: string; body?: { allow?: boolean } };
/** Answers GET /api/mcp-settings with what `current()` says (the switches’ posts update it); anything else with `others`. */
function serve(current: () => McpSettings, others: (path: string, opts?: Opts) => unknown = () => undefined) {
  vi.mocked(api).mockImplementation((async (path: string, opts?: Opts) => others(path, opts) ?? current()) as never);
}
const posts = (route: string) => vi.mocked(api).mock.calls.filter((c) => c[0] === route).map((c) => (c[1] as { body: unknown }).body);

beforeEach(() => { vi.mocked(api).mockReset(); vi.mocked(toast).mockReset(); vi.mocked(toast.success).mockReset(); vi.mocked(toast.error).mockReset(); });
afterEach(() => vi.unstubAllGlobals());

describe("Settings → AI assistants (MCP)", () => {
  it("says it is loading, then shows the address to add and a link to the docs", async () => {
    serve(() => view());
    render(McpSection);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(await screen.findByLabelText("MCP address")).toHaveValue(URL_);
    expect(screen.getByRole("link", { name: "Learn more" })).toHaveAttribute("href", "https://anthonypluth.github.io/waypoint/start/mcp/");
    expect(screen.getByRole("heading", { name: "AI assistants (MCP)" })).toBeInTheDocument();
  });

  it("says why it can’t be reached, and tries again", async () => {
    serve(() => view());
    vi.mocked(api).mockRejectedValueOnce(new Error("down"));
    render(McpSection);
    expect(await screen.findByText("down")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByLabelText("MCP address")).toBeInTheDocument();
  });

  it("copies the address", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    serve(() => view());
    render(McpSection);
    await userEvent.click(await screen.findByRole("button", { name: "Copy" }));
    expect(writeText).toHaveBeenCalledWith(URL_);
    expect(toast.success).toHaveBeenCalledWith("Copied");
  });

  it("selects the address, and says so, where the browser has no clipboard (plain http)", async () => {
    vi.stubGlobal("navigator", { clipboard: undefined });
    serve(() => view());
    render(McpSection);
    const box = (await screen.findByLabelText("MCP address")) as HTMLInputElement;
    await userEvent.click(screen.getByRole("button", { name: "Copy" }));
    expect(box.selectionEnd).toBe(URL_.length);
    expect(toast).toHaveBeenCalledWith(expect.stringMatching(/^Couldn’t copy it: it’s selected/));
  });

  it("gives the reason, and no address to copy, when assistants can’t connect", async () => {
    serve(() => view({ oauth: false, url: null, reason: "Set WAYPOINT_PUBLIC_URL to the address you open Waypoint at." }));
    render(McpSection);
    expect(await screen.findByText(/Set WAYPOINT_PUBLIC_URL/)).toBeInTheDocument();
    expect(screen.queryByLabelText("MCP address")).toBeNull();
    expect(screen.queryByRole("button", { name: "Copy" })).toBeNull();
    expect(screen.getByRole("checkbox", { name: /Let assistants change trips/ })).toBeInTheDocument();   // the switches stay
  });

  it("starts with both switches off and says what each allows", async () => {
    serve(() => view());
    render(McpSection);
    const ids = await screen.findByRole("checkbox", { name: /Let assistants see full ID numbers/ });
    const writes = screen.getByRole("checkbox", { name: /Let assistants change trips/ });
    expect(ids).not.toBeChecked();
    expect(writes).not.toBeChecked();
    expect(ids).toHaveAccessibleDescription(/never the number/);
    expect(writes).toHaveAccessibleDescription(/ask before each change/);
  });

  it.each([
    ["ids", /Let assistants see full ID numbers/],
    ["writes", /Let assistants change trips/],
  ])("switches %s on and off, and shows what the server kept", async (route, name) => {
    let now = view();
    serve(() => now, (path, opts) => {
      if (path !== `/api/mcp-settings/${route}`) return undefined;
      now = { ...now, [route === "ids" ? "allow_ids" : "allow_writes"]: !!opts?.body?.allow };
      return { allow: !!opts?.body?.allow };
    });
    render(McpSection);
    const box = await screen.findByRole("checkbox", { name });
    await userEvent.click(box);
    await waitFor(() => expect(posts(`/api/mcp-settings/${route}`)).toEqual([{ allow: true }]));
    await waitFor(() => expect(box).toBeChecked());
    expect(vi.mocked(api)).toHaveBeenCalledWith(`/api/mcp-settings/${route}`, expect.objectContaining({ method: "POST" }));
    const other = screen.getByRole("checkbox", { name: route === "ids" ? /change trips/ : /full ID numbers/ });
    expect(other).not.toBeChecked();   // apart from each other
    await waitFor(() => expect(box).toBeEnabled());
    await userEvent.click(box);
    await waitFor(() => expect(posts(`/api/mcp-settings/${route}`)).toEqual([{ allow: true }, { allow: false }]));
    await waitFor(() => expect(box).not.toBeChecked());
  });

  it("shows what the server answers, not what was clicked", async () => {
    serve(() => view(), (path) => (path === "/api/mcp-settings/writes" ? { allow: false } : undefined));
    render(McpSection);
    const box = await screen.findByRole("checkbox", { name: /Let assistants change trips/ });
    await userEvent.click(box);
    await waitFor(() => expect(posts("/api/mcp-settings/writes")).toEqual([{ allow: true }]));
    await waitFor(() => expect(box).not.toBeChecked());
  });

  it.each([
    ["ids", /Let assistants see full ID numbers/, false],
    ["writes", /Let assistants change trips/, true],
  ])("puts the %s switch back and says why when the server refuses", async (route, name, wasOn) => {
    const now = view({ allow_ids: wasOn, allow_writes: wasOn });
    serve(() => now, (path) => { if (path === `/api/mcp-settings/${route}`) throw new Error("Waypoint is busy"); return undefined; });
    render(McpSection);
    const box = (await screen.findByRole("checkbox", { name })) as HTMLInputElement;
    expect(box.checked).toBe(wasOn);
    await userEvent.click(box);
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Waypoint is busy"));
    await waitFor(() => expect(box.checked).toBe(wasOn));
    await waitFor(() => expect(box).toBeEnabled());
  });

  it("lists each connected assistant with who approved it, when it was last used and what it may do", async () => {
    serve(() => view({ connections: [
      conn({ scope: ["read"] }),
      conn({ id: 2, client: null, who: null, scope: ["read", "ids:read", "write"], last_used: "2026-09-03T10:00:00+00:00" }),
    ] }));
    render(McpSection);
    expect(await screen.findByText("Claude")).toBeInTheDocument();
    expect(screen.getByText("Unnamed app")).toBeInTheDocument();
    const [first, second] = screen.getAllByTestId("assistant");
    expect(first).toHaveTextContent(/Approved by ana@example\.com .*2026.*\. Not used yet\./);
    expect(first).toHaveTextContent("Read");
    expect(first).not.toHaveTextContent("Change trips");
    expect(second).toHaveTextContent(/Last used .*2026.*\./);
    expect(second).toHaveTextContent("Full ID numbers");
    expect(second).toHaveTextContent("Change trips");
    expect(second).not.toHaveTextContent("by ");
  });

  it("disconnects after asking, then lists again", async () => {
    let connections = [conn(), conn({ id: 2, client: "Desktop app" })];
    serve(() => view({ connections }), (path, opts) => {
      if (opts?.method === "DELETE") { connections = connections.filter((c) => `/api/mcp-settings/connections/${c.id}` !== path); return { ok: true }; }
      return undefined;
    });
    render(McpSection);
    await userEvent.click((await screen.findAllByRole("button", { name: "Disconnect" }))[0]);
    expect(await screen.findByText("Disconnect Claude?")).toBeInTheDocument();
    expect(api).not.toHaveBeenCalledWith("/api/mcp-settings/connections/1", expect.anything());   // not until confirmed
    await userEvent.click((await screen.findByRole("dialog")).querySelector("button[type=submit]")!);
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/mcp-settings/connections/1", { method: "DELETE", failed: "Couldn’t disconnect" }));
    await waitFor(() => expect(screen.queryByText("Claude")).toBeNull());
    expect(screen.getByText("Desktop app")).toBeInTheDocument();
    expect(toast.success).toHaveBeenCalledWith("Claude is disconnected");
  });

  it("keeps the assistant listed when disconnecting fails", async () => {
    serve(() => view({ connections: [conn()] }), (_path, opts) => { if (opts?.method === "DELETE") throw new Error("That connection isn’t there any more."); return undefined; });
    render(McpSection);
    await userEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
    await userEvent.click((await screen.findByRole("dialog")).querySelector("button[type=submit]")!);
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("That connection isn’t there any more."));
    expect(toast.success).not.toHaveBeenCalled();
    expect(screen.getByText("Claude")).toBeInTheDocument();
  });
});
