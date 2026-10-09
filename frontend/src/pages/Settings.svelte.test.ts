// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import { app, route } from "$lib/app.svelte";
import { flightStatus } from "$lib/flightstatus.svelte";
import * as offlineModule from "$lib/offline";
import { state } from "../test/fixtures";
import Settings from "./Settings.svelte";

const file = (name = "backup.json.gz") => new File(["x"], name, { type: "application/gzip" });
const inspected = { created: "2026-09-01T10:00:00Z", source: "sqlite", counts: { trips: 3, loyalty_ids: 2 }, current: { trips: 1 }, database: "sqlite" };

beforeEach(() => { vi.mocked(api).mockReset(); app.state = state(); });
afterEach(() => { app.state = null; flightStatus.list = null; route.sub = ""; route.query = ""; history.replaceState(null, "", "/"); });

describe("Settings flight status", () => {
  const usage = (extra = {}) => ({ enabled: true, month: "2026-11", used: 12, limit: 400, paused: null, statuses: [], ...extra });

  it("shows the calls used this month out of the limit", async () => {
    vi.mocked(api).mockImplementation(async (path: string) => (path === "/api/flight-status" ? usage() : {}) as never);
    render(Settings);
    expect(await screen.findByText("12 of 400 calls used this month")).toBeInTheDocument();
    expect(screen.getByText("Flight status")).toBeInTheDocument();
  });

  it("says it’s off without the key", async () => {
    vi.mocked(api).mockImplementation(async (path: string) => (path === "/api/flight-status" ? usage({ enabled: false, used: 0 }) : {}) as never);
    render(Settings);
    expect(await screen.findByText(/Off \(RAPIDAPI_KEY isn’t set\)/)).toBeInTheDocument();
  });

  it("shows nothing until it knows", () => {
    render(Settings);
    expect(screen.queryByTestId("flight-status-usage")).toBeNull();
  });
});

describe("Settings account", () => {
  it("says who is signed in, with a Sign out button", () => {
    render(Settings);
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("says it runs without sign-in, and has nothing to sign out of", () => {
    app.state = state({ user: { name: null, email: null, local: true } });
    render(Settings);
    expect(screen.getByText("Running without sign-in")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign out" })).toBeNull();
  });

  it("signs out, then goes where the server says", async () => {
    const fake = { href: "" };
    vi.stubGlobal("location", fake);
    vi.mocked(api).mockResolvedValue({ redirect: "/auth/signed-out" });
    render(Settings);
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(api).toHaveBeenCalledWith("/auth/logout", { method: "POST" });
    await waitFor(() => expect(fake.href).toBe("/auth/signed-out"));
    vi.unstubAllGlobals();
  });

  it("clears the trip saved on this device before the session ends", async () => {
    const order: string[] = [];
    vi.spyOn(offlineModule, "clearSaved").mockImplementation(async () => { order.push("cleared"); });
    vi.mocked(api).mockImplementation((async (path: string) => { order.push(path); return { redirect: "/auth/signed-out" }; }) as never);
    vi.stubGlobal("location", { href: "", pathname: "/", hash: "" });
    render(Settings);
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(order).toContain("/auth/logout"));
    expect(order.indexOf("cleared")).toBeLessThan(order.indexOf("/auth/logout"));
    vi.unstubAllGlobals();
  });

  it("shows the version and the database", () => {
    app.state = state({ database: "postgres" });
    render(Settings);
    expect(screen.getByText("1.2.3")).toBeInTheDocument();
    expect(screen.getByText("Postgres")).toBeInTheDocument();
  });
});

describe("Settings tabs", () => {
  const tabs = () => within(screen.getByRole("navigation", { name: "Settings sections" }));

  it("opens on Account, with a link to each group kept in the address", () => {
    render(Settings);
    expect(tabs().getAllByRole("link").map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ["Account", "#settings/account"], ["Mail and AI", "#settings/mail"], ["Travel", "#settings/travel"], ["Data", "#settings/data"]]);
    expect(tabs().getByRole("link", { name: "Account" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("Signed in as")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Download backup" })).toBeNull();
  });

  it("shows each group's sections on its own tab", () => {
    const heading = (name: string) => screen.queryByRole("heading", { name });
    const onTab = (sub: string) => { route.sub = sub; return render(Settings); };
    let view = onTab("mail");
    expect(heading("Gmail")).not.toBeNull();
    expect(heading("AI")).not.toBeNull();
    expect(heading("Account")).toBeNull();
    view.unmount();
    view = onTab("travel");
    for (const name of ["Reminders and calendar", "Distances", "Brand logos", "Import past flights"]) expect(heading(name)).not.toBeNull();
    expect(heading("Gmail")).toBeNull();
    view.unmount();
    view = onTab("data");
    for (const name of ["AI assistants (MCP)", "Data"]) expect(heading(name)).not.toBeNull();
    expect(tabs().getByRole("link", { name: "Data" })).toHaveAttribute("aria-current", "page");
    view.unmount();
  });

  it("falls back to Account for a tab it doesn't have", () => {
    route.sub = "nope";
    render(Settings);
    expect(tabs().getByRole("link", { name: "Account" })).toHaveAttribute("aria-current", "page");
  });

  it("opens on the mail tab when Google sends you back", () => {
    history.replaceState(null, "", "/?gmail=connected#settings");
    render(Settings);
    expect(tabs().getByRole("link", { name: "Mail and AI" })).toHaveAttribute("aria-current", "page");
  });
});

describe("Settings data", () => {
  beforeEach(() => { route.sub = "data"; });

  it("links to the backup download and says when the last one was", () => {
    app.state = state({ last_backup: new Date().toISOString() });
    render(Settings);
    expect(screen.getByRole("link", { name: "Download backup" })).toHaveAttribute("href", "/api/backup");
    expect(screen.getByText(/Last backup/)).toBeInTheDocument();
  });

  it("says when no backup has been downloaded", () => {
    render(Settings);
    expect(screen.getByText(/No backup downloaded yet/)).toBeInTheDocument();
  });

  it("reads a chosen file and shows what it holds before anything is replaced", async () => {
    vi.mocked(api).mockResolvedValue(inspected);
    const { container } = render(Settings);
    const restore = screen.getByRole("button", { name: "Restore…" });
    expect(restore).toBeDisabled();
    await userEvent.upload(container.querySelector("[aria-labelledby=data-title] input[type=file]")!, file());
    const summary = await screen.findByTestId("backup-summary");
    expect(summary).toHaveTextContent("5 rows");
    expect(summary).toHaveTextContent("loyalty ids");
    expect(restore).toBeEnabled();
    expect(api).toHaveBeenCalledWith("/api/backup/inspect", expect.objectContaining({ method: "POST" }));
  });

  it("says why a file can't be read", async () => {
    vi.mocked(api).mockRejectedValue(new Error("Couldn’t read that backup (400)"));
    const { container } = render(Settings);
    await userEvent.upload(container.querySelector("[aria-labelledby=data-title] input[type=file]")!, file());
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn’t read that backup");
    expect(screen.getByRole("button", { name: "Restore…" })).toBeDisabled();
  });

  it("restores only after RESTORE is typed, then reports the safety copy and unreadable secrets", async () => {
    vi.mocked(api).mockImplementation(async (path: string) => (path === "/api/restore"
      ? { ok: true, created: "2026-09-01T10:00:00Z", source: "sqlite", counts: {}, safety_copy: "/data/before-restore.gz", unreadable_secrets: ["mail_password"] }
      : path === "/api/state" ? state() : inspected) as never);
    const { container } = render(Settings);
    await userEvent.upload(container.querySelector("[aria-labelledby=data-title] input[type=file]")!, file());
    await userEvent.click(await screen.findByRole("button", { name: "Restore…" }));
    const go = await screen.findByRole("button", { name: "Restore" });
    expect(go).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox"), "RESTORE");
    await userEvent.click(go);
    expect(await screen.findByText("/data/before-restore.gz")).toBeInTheDocument();
    expect(screen.getByText(/mail_password/)).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith("/api/restore", expect.objectContaining({ method: "POST" }));
  });
});
