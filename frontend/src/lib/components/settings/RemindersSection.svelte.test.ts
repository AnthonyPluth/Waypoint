// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn(), warning: vi.fn() }) }));

import { api } from "$lib/api";
import type { Reminders } from "$lib/api-types";
import { toast } from "svelte-sonner";
import RemindersSection from "./RemindersSection.svelte";

const view = (extra: Partial<Reminders> = {}): Reminders => ({ public_key: "BAUQ", check_in: true, day_of: true, devices: [], feed: false, ...extra });
/** Answers GET /api/reminders with what `current()` says; other calls with what `others` says. */
const serve = (current: () => Reminders, others: (path: string, opts?: { method?: string; body?: unknown }) => unknown = () => ({})) =>
  vi.mocked(api).mockImplementation(async (path: string, opts?: { method?: string; body?: unknown }) =>
    (path === "/api/reminders" && !opts?.method ? current() : others(path, opts)) as never);

beforeEach(() => { vi.mocked(api).mockReset(); vi.mocked(toast.success).mockReset(); vi.mocked(toast.error).mockReset(); });
afterEach(() => vi.unstubAllGlobals());

describe("Settings → Reminders", () => {
  it("offers each reminder, both on until the member chooses", async () => {
    serve(() => view());
    render(RemindersSection);
    expect(await screen.findByRole("checkbox", { name: /Check-in opens/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Day-of summary/ })).toBeChecked();
  });

  it("saves a choice with the other one as it was, and shows what the server kept", async () => {
    let now = view();
    serve(() => now, (path, opts) => { if (opts?.method === "POST") now = view({ ...(opts.body as object) }); return now; });
    render(RemindersSection);
    await userEvent.click(await screen.findByRole("checkbox", { name: /Check-in opens/ }));
    expect(api).toHaveBeenCalledWith("/api/reminders", expect.objectContaining({ method: "POST", body: { check_in: false, day_of: true } }));
    await waitFor(() => expect(screen.getByRole("checkbox", { name: /Check-in opens/ })).not.toBeChecked());
  });

  it("says when the server can’t be reached, and tries again", async () => {
    serve(() => view());
    vi.mocked(api).mockRejectedValueOnce(new Error("down"));
    render(RemindersSection);
    await userEvent.click(await screen.findByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("checkbox", { name: /Check-in opens/ })).toBeInTheDocument();
  });

  it("lists the member’s devices and turns one off", async () => {
    let devices = [{ id: 7, service: "push.example.com", created: 1790000000 }];
    serve(() => view({ devices }), (path, opts) => { if (opts?.method === "DELETE") devices = []; return { ok: true }; });
    render(RemindersSection);
    expect(await screen.findByText("Notifications to push.example.com")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Turn off" }));
    expect(api).toHaveBeenCalledWith("/api/reminders/devices/7", expect.objectContaining({ method: "DELETE" }));
    await waitFor(() => expect(screen.queryByTestId("device")).toBeNull());
  });

  it("says a browser that can’t show notifications can’t, and offers no way to turn them on", async () => {
    serve(() => view());
    render(RemindersSection);
    expect(await screen.findByText(/can’t show notifications/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Turn on" })).toBeDisabled();
  });

  it("subscribes this browser with the server’s key and sends the subscription", async () => {
    const sub = { toJSON: () => ({ endpoint: "https://push.example.com/send/a", keys: { p256dh: "pk", auth: "ak" } }) };
    const pushManager = { getSubscription: vi.fn(async () => null), subscribe: vi.fn(async () => sub) };
    vi.stubGlobal("PushManager", class {});
    vi.stubGlobal("Notification", { requestPermission: vi.fn(async () => "granted") });
    Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: { ready: Promise.resolve({ pushManager }) } });
    serve(() => view(), () => ({ id: 1, service: "push.example.com", created: 1 }));
    render(RemindersSection);
    await userEvent.click(await screen.findByRole("button", { name: "Turn on" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/reminders/devices", expect.objectContaining({
      method: "POST", body: { endpoint: "https://push.example.com/send/a", p256dh: "pk", auth: "ak" } })));
    expect(pushManager.subscribe).toHaveBeenCalledWith(expect.objectContaining({ userVisibleOnly: true }));
    expect(toast.success).toHaveBeenCalledWith("Notifications are on for this device");
    // @ts-expect-error: put back what jsdom has
    delete navigator.serviceWorker;
  });

  it("doesn’t subscribe when the browser blocks notifications, and says so", async () => {
    vi.stubGlobal("PushManager", class {});
    vi.stubGlobal("Notification", { requestPermission: vi.fn(async () => "denied") });
    Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: { ready: new Promise(() => {}) } });
    serve(() => view());
    render(RemindersSection);
    await userEvent.click(await screen.findByRole("button", { name: "Turn on" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringMatching(/blocked/)));
    expect(api).not.toHaveBeenCalledWith("/api/reminders/devices", expect.anything());
    // @ts-expect-error: put back what jsdom has
    delete navigator.serviceWorker;
  });

  it("makes a calendar address and shows it, once", async () => {
    let on = false;
    serve(() => view({ feed: on }), (path, opts) => { if (path === "/api/feed" && opts?.method === "POST") { on = true; return { url: "https://wp.example/feed/KEY.ics" }; } return {}; });
    render(RemindersSection);
    await userEvent.click(await screen.findByRole("button", { name: "Make my calendar address" }));
    expect(await screen.findByLabelText("Calendar address")).toHaveValue("https://wp.example/feed/KEY.ics");
    expect(screen.getByText("On")).toBeInTheDocument();
    expect(screen.getByText(/shown only now/)).toBeInTheDocument();
  });

  it("copies the address", async () => {
    const writeText = vi.fn(async () => {});
    vi.stubGlobal("navigator", Object.assign(Object.create(navigator), { clipboard: { writeText } }));
    serve(() => view(), (path) => (path === "/api/feed" ? { url: "https://wp.example/feed/KEY.ics" } : {}));
    render(RemindersSection);
    await userEvent.click(await screen.findByRole("button", { name: "Make my calendar address" }));
    await userEvent.click(await screen.findByRole("button", { name: "Copy" }));
    expect(writeText).toHaveBeenCalledWith("https://wp.example/feed/KEY.ics");
  });

  it("asks before replacing the address, and says the old one stops", async () => {
    serve(() => view({ feed: true }), (path) => (path === "/api/feed" ? { url: "https://wp.example/feed/NEW.ics" } : {}));
    render(RemindersSection);
    await userEvent.click(await screen.findByRole("button", { name: "New address" }));
    expect(screen.getByText(/old address stops working at once/)).toBeInTheDocument();
    expect(api).not.toHaveBeenCalledWith("/api/feed", expect.anything());
    await userEvent.click(screen.getByRole("button", { name: "Make a new address" }));
    expect(await screen.findByLabelText("Calendar address")).toHaveValue("https://wp.example/feed/NEW.ics");
  });

  it("turns the feed off after asking, and forgets the address it showed", async () => {
    let on = true;
    serve(() => view({ feed: on }), (path, opts) => { if (opts?.method === "DELETE") on = false; return { ok: true }; });
    render(RemindersSection);
    await userEvent.click(await screen.findByRole("button", { name: "Turn off" }));
    await userEvent.click(within_dialog());
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/feed", expect.objectContaining({ method: "DELETE" })));
    expect(await screen.findByRole("button", { name: "Make my calendar address" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Calendar address")).toBeNull();
  });
});

/** The confirm button of the open dialog (there's a "Turn off" on the page too). */
function within_dialog() {
  return screen.getAllByRole("button", { name: "Turn off" }).at(-1) as HTMLElement;
}
