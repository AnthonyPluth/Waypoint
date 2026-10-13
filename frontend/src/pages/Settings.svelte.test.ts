// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { toast } from "svelte-sonner";
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
  beforeEach(() => { route.sub = "account"; });

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
    expect(await screen.findByText(/Live flight status has not been enabled by your administrator/)).toBeInTheDocument();
  });

  it("shows nothing until it knows", () => {
    render(Settings);
    expect(screen.queryByTestId("flight-status-usage")).toBeNull();
  });
});

describe("Settings account", () => {
  beforeEach(() => { route.sub = "account"; });

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

  it("stays signed in, and says why, when the saved trip can't be removed", async () => {
    vi.spyOn(offlineModule, "clearSaved").mockRejectedValue(new Error("Couldn’t remove the saved trip from this device."));
    render(Settings);
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Couldn’t remove the saved trip from this device."));
    expect(api).not.toHaveBeenCalledWith("/auth/logout", expect.anything());
  });

  it("shows the version and the database", () => {
    app.state = state({ database: "postgres" });
    render(Settings);
    expect(screen.getByText("1.2.3")).toBeInTheDocument();
    expect(screen.getByText("Postgres")).toBeInTheDocument();
  });
});

describe("Settings index", () => {
  const index = () => within(screen.getByRole("navigation", { name: "Settings sections" }));

  it("opens on an index of task groups, each linked by its address", () => {
    render(Settings);
    expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => [h.textContent, h.querySelector("a")?.getAttribute("href")])).toEqual([
      ["Account & household", "#settings/account"], ["Mail & review", "#settings/mail"], ["Travel preferences", "#settings/travel"],
      ["Offline & notifications", "#settings/offline"], ["Connected assistants", "#settings/assistants"], ["Backup & import", "#settings/backup"]]);
    expect(screen.queryByText("Signed in as")).toBeNull();
  });

  it.each([
    ["Offline access", "#settings/offline"], ["Calendar subscription", "#settings/offline"], ["Import past flights", "#settings/backup"],
    ["Connect or reconnect Gmail", "#settings/mail"], ["Download a backup", "#settings/backup"], ["Connect an assistant", "#settings/assistants"],
  ])("lists %s where it lives", (task, href) => {
    render(Settings);
    expect(index().getByRole("link", { name: task })).toHaveAttribute("href", href);
  });

  it("shows each group's sections on its own page, with a way back", () => {
    const heading = (name: string) => screen.queryByRole("heading", { name });
    const open = (sub: string) => { route.sub = sub; return render(Settings); };
    let view = open("mail");
    expect(heading("Gmail")).not.toBeNull();
    expect(heading("AI")).not.toBeNull();
    expect(heading("Account")).toBeNull();
    expect(index().getByRole("link", { name: "All settings" })).toHaveAttribute("href", "#settings");
    view.unmount();
    view = open("travel");
    for (const name of ["Home", "Distances", "Brand logos"]) expect(heading(name)).not.toBeNull();
    expect(heading("Gmail")).toBeNull();
    view.unmount();
    view = open("offline");
    for (const name of ["Offline access", "Reminders and calendar"]) expect(heading(name)).not.toBeNull();
    view.unmount();
    view = open("assistants");
    expect(heading("AI assistants (MCP)")).not.toBeNull();
    view.unmount();
    view = open("backup");
    for (const name of ["Data", "Import past flights"]) expect(heading(name)).not.toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: "Backup & import" })).toBeInTheDocument();
    view.unmount();
  });

  it("keeps the database and flight status under an advanced heading, with a link to People", () => {
    route.sub = "account";
    render(Settings);
    expect(screen.getByRole("heading", { name: "Advanced: for whoever runs Waypoint" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open People" })).toHaveAttribute("href", "#people");
  });

  it("opens an old Data link on Backup & import", () => {
    route.sub = "data";
    render(Settings);
    expect(screen.getByRole("heading", { level: 1, name: "Backup & import" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download backup" })).toBeInTheDocument();
  });

  it("shows the index for a group it doesn't have", () => {
    route.sub = "nope";
    render(Settings);
    expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
  });

  it("opens on the mail group when Google sends you back", () => {
    history.replaceState(null, "", "/?gmail=connected#settings");
    render(Settings);
    expect(screen.getByRole("heading", { level: 1, name: "Mail & review" })).toBeInTheDocument();
  });

  it("leaves the mail group for the index after Google sends you back", async () => {
    history.replaceState(null, "", "/?gmail=connected#settings");
    route.sub = "";
    render(Settings);
    await waitFor(() => expect(location.hash).toBe("#settings/mail"));
    route.sub = "";
    await waitFor(() => expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument());
  });
});

describe("Settings data", () => {
  beforeEach(() => { route.sub = "backup"; });

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
