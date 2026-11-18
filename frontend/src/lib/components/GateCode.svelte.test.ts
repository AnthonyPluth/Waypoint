// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), apiImage: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

vi.mock("$lib/offline-shell", () => ({ inShell: vi.fn(() => false), shellLoad: vi.fn() }));

import { api, apiImage } from "$lib/api";
import { inShell, shellLoad } from "$lib/offline-shell";
import { segment } from "../../test/fixtures";
import GateCode from "./GateCode.svelte";

const user = userEvent.setup({ pointerEventsCheck: 0 });
const NOW = Date.parse("2026-12-01T12:00:00Z");
const lot = segment({
  id: 7, kind: "parking", origin: "Example Airport Long-Term Lot", destination: null, provider: "Example Parking", confirmation: "PK30417",
  start_local: "2026-12-01T05:15", start_zone: "America/New_York", end_local: "2026-12-04T03:00", end_zone: "America/New_York",
  details: {}, has_email: true, email_update: null, gate_code: { state: "ready", day: "2026-10-16" },
});
const QR = "data:image/png;base64,QUJD";
const OTHER = "data:image/png;base64,REVG";

function serve() {
  vi.mocked(apiImage).mockImplementation(async (path) => (path === "/api/segments/7/code" ? QR : path.endsWith("/emails/0/images/1") ? OTHER : QR));
  vi.mocked(api).mockImplementation(async (path, opts) => {
    if (path === "/api/segments/7/emails") return { emails: [{ subject: "x", sender_domain: "d.example", received: "2026-10-16", text: "", html: null, truncated: false, original: true, images: 2 }] };
    if (path === "/api/segments/7/code" && opts?.method === "POST") return { ...lot, gate_code: { state: "ready", day: "2026-10-16" } };
    return {};
  });
}

let sentinels: { release: ReturnType<typeof vi.fn> }[];
function stubWakeLock() {
  sentinels = [];
  const request = vi.fn(async () => { const s = { release: vi.fn(async () => {}) }; sentinels.push(s); return s; });
  Object.defineProperty(navigator, "wakeLock", { value: { request }, configurable: true });
  return request;
}

beforeEach(() => { vi.mocked(api).mockReset(); vi.mocked(apiImage).mockReset(); vi.mocked(inShell).mockReturnValue(false); vi.mocked(shellLoad).mockReset(); serve(); });
afterEach(() => { Reflect.deleteProperty(navigator, "wakeLock"); vi.clearAllMocks(); });

describe("GateCode button", () => {
  it("shows Show QR code for a parking booking with a code before its exit time", () => {
    render(GateCode, { segment: lot, now: NOW });
    expect(screen.getByRole("button", { name: "Show QR code for Example Airport Long-Term Lot" })).toHaveTextContent("Show QR code");
  });

  it("shows nothing after the exit time, for a cancelled booking, for one with no code or any other kind", () => {
    const after = Date.parse("2026-12-04T09:00:00Z");
    for (const [s, now] of [[lot, after], [{ ...lot, status: "cancelled" as const }, NOW], [{ ...lot, gate_code: null }, NOW], [{ ...lot, kind: "hotel" as const }, NOW]] as const) {
      const { unmount } = render(GateCode, { segment: s, now });
      expect(screen.queryByRole("button")).toBeNull();
      unmount();
    }
  });

  it("is still shown during the last minutes of the booking and gone at the exit time", () => {
    const { unmount } = render(GateCode, { segment: lot, now: Date.parse("2026-12-04T07:59:00Z") });
    expect(screen.getByRole("button", { name: /Show QR code/ })).toBeInTheDocument();
    unmount();
    render(GateCode, { segment: lot, now: Date.parse("2026-12-04T08:00:00Z") });
    expect(screen.queryByRole("button", { name: /Show QR code/ })).toBeNull();
  });
});

describe("opened by the app on arrival", () => {
  it("opens the dialog without a button when it is told to, and closes it for its owner", async () => {
    render(GateCode, { segment: lot, now: NOW, buttons: false, showing: true });
    expect(screen.queryByRole("button", { name: /Show QR code/ })).toBeNull();
    const dialog = await screen.findByRole("dialog", { name: "QR code" });
    expect(await within(dialog).findByRole("img", { name: "QR code for Example Airport Long-Term Lot" })).toHaveAttribute("src", QR);
    await user.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows only Show QR code, no way to choose a picture, when it is read only", () => {
    render(GateCode, { segment: lot, now: NOW, readOnly: true });
    expect(screen.getByRole("button", { name: /Show QR code/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Choose/ })).toBeNull();
  });

  it("shows nothing when read only and no code is chosen yet", () => {
    render(GateCode, { segment: { ...lot, gate_code: { state: "choose", day: null } }, now: NOW, readOnly: true });
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("the full-screen code", () => {
  it("shows the picture centred on white with sharp pixels, the lot and the times, and the brightness reminder", async () => {
    render(GateCode, { segment: lot, now: NOW });
    await user.click(screen.getByRole("button", { name: /Show QR code/ }));
    const dialog = await screen.findByRole("dialog", { name: "QR code" });
    const picture = await within(dialog).findByRole("img", { name: "QR code for Example Airport Long-Term Lot" });
    expect(picture).toHaveAttribute("src", QR);
    expect(picture.getAttribute("style")).toContain("image-rendering: pixelated");
    const square = within(dialog).getByTestId("code-square");
    expect(square).toHaveClass("bg-white");
    expect(square).toContainElement(picture);
    expect(square.parentElement).toHaveClass("items-center", "justify-center");
    expect(within(dialog).getByTestId("code-lot")).toHaveTextContent("Example Airport Long-Term Lot");
    const times = within(dialog).getByTestId("code-times");
    expect(times).toHaveTextContent(/Entry .*Dec 1.*5:15\s?AM.*Exit .*Dec 4.*3:00\s?AM/);
    expect(dialog).toHaveTextContent("Turn your screen brightness up");
    expect(apiImage).toHaveBeenCalledWith("/api/segments/7/code");
  });

  it("leaves a clear margin of at least four modules around the code on the square", async () => {
    render(GateCode, { segment: lot, now: NOW });
    await user.click(screen.getByRole("button", { name: /Show QR code/ }));
    const picture = await screen.findByRole("img", { name: /QR code for/ });
    const share = Number(/width:\s*([\d.]+)%/.exec(picture.getAttribute("style") ?? "")?.[1]);
    expect(share).toBeGreaterThan(0);
    const margin = (100 - share) / 2;
    expect((margin / share) * 21).toBeGreaterThanOrEqual(4);
  });

  it("sizes the square from the picture once it has loaded", async () => {
    render(GateCode, { segment: lot, now: NOW });
    await user.click(screen.getByRole("button", { name: /Show QR code/ }));
    const picture = await screen.findByRole("img", { name: /QR code for/ });
    Object.defineProperty(picture, "naturalWidth", { value: 290, configurable: true });
    await fireEvent.load(picture);
    expect(screen.getByTestId("code-square")).toBeInTheDocument();
  });

  it("asks the browser to keep the screen on while it is open and lets go when it closes", async () => {
    const request = stubWakeLock();
    render(GateCode, { segment: lot, now: NOW });
    await user.click(screen.getByRole("button", { name: /Show QR code/ }));
    await screen.findByRole("dialog", { name: "QR code" });
    await waitFor(() => expect(request).toHaveBeenCalledWith("screen"));
    await user.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(sentinels[0].release).toHaveBeenCalled());
  });

  it("asks again when the page comes back to the front", async () => {
    const request = stubWakeLock();
    render(GateCode, { segment: lot, now: NOW });
    await user.click(screen.getByRole("button", { name: /Show QR code/ }));
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    document.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() => expect(request).toHaveBeenCalledTimes(2));
  });

  it("works when the browser has no wake lock or refuses it", async () => {
    render(GateCode, { segment: lot, now: NOW });
    await user.click(screen.getByRole("button", { name: /Show QR code/ }));
    expect(await screen.findByRole("img", { name: /QR code for/ })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const request = vi.fn(async () => { throw new Error("denied"); });
    Object.defineProperty(navigator, "wakeLock", { value: { request }, configurable: true });
    await user.click(screen.getByRole("button", { name: /Show QR code/ }));
    expect(await screen.findByRole("img", { name: /QR code for/ })).toBeInTheDocument();
    expect(request).toHaveBeenCalled();
  });

  it("closes with its button and with Escape and returns focus to the button", async () => {
    render(GateCode, { segment: lot, now: NOW });
    const button = screen.getByRole("button", { name: /Show QR code/ });
    await user.click(button);
    await screen.findByRole("dialog", { name: "QR code" });
    await user.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(button).toHaveFocus());
    await user.click(button);
    await screen.findByRole("dialog", { name: "QR code" });
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(button).toHaveFocus());
  });

  it("says so, and keeps no picture, when the code can’t be fetched", async () => {
    vi.mocked(apiImage).mockRejectedValue(new Error("offline"));
    render(GateCode, { segment: lot, now: NOW });
    await user.click(screen.getByRole("button", { name: /Show QR code/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The code can’t be shown right now");
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("fetches the picture afresh each time it opens and forgets it when it closes", async () => {
    render(GateCode, { segment: lot, now: NOW });
    const button = screen.getByRole("button", { name: /Show QR code/ });
    await user.click(button);
    await screen.findByRole("img", { name: /QR code for/ });
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await user.click(button);
    await screen.findByRole("img", { name: /QR code for/ });
    expect(vi.mocked(apiImage).mock.calls.filter(([p]) => p === "/api/segments/7/code")).toHaveLength(2);
  });

  it("says the times are not recorded when the booking has none", async () => {
    render(GateCode, { segment: { ...lot, details: { time_unknown: "yes" } }, now: NOW });
    await user.click(screen.getByRole("button", { name: /Show QR code/ }));
    expect(await screen.findByTestId("code-times")).toHaveTextContent("time not recorded");
  });
});

describe("Choose the code", () => {
  const pending = { ...lot, gate_code: { state: "choose" as const, day: "2026-10-16" } };

  it("is offered when several pictures qualify, lists the email’s pictures and saves the choice", async () => {
    const changed = vi.fn();
    render(GateCode, { segment: pending, now: NOW, onchanged: changed });
    expect(screen.queryByRole("button", { name: /Show QR code/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Choose the code for Example Airport Long-Term Lot" }));
    const list = await screen.findByRole("list", { name: "Pictures in the emails" });
    const choices = within(list).getAllByRole("button");
    expect(choices).toHaveLength(2);
    expect(apiImage).toHaveBeenCalledWith("/api/segments/7/emails/0/images/0");
    expect(apiImage).toHaveBeenCalledWith("/api/segments/7/emails/0/images/1");
    await user.click(choices[1]);
    await waitFor(() => expect(changed).toHaveBeenCalledOnce());
    expect(api).toHaveBeenCalledWith("/api/segments/7/code", { method: "POST", body: { email: 0, image: 1 } });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("keeps the sheet open and says why when the choice can’t be saved", async () => {
    const changed = vi.fn();
    const answer = vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation(async (path, opts) => { if (opts?.method === "POST") throw new Error("Choose one of the pictures"); return answer(path, opts); });
    render(GateCode, { segment: pending, now: NOW, onchanged: changed });
    await user.click(screen.getByRole("button", { name: /Choose the code/ }));
    const list = await screen.findByRole("list", { name: "Pictures in the emails" });
    await user.click(within(list).getAllByRole("button")[0]);
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/segments/7/code", expect.objectContaining({ method: "POST" })));
    expect(changed).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Choose the code" })).toBeInTheDocument();
  });

  it("says when the emails have no pictures and when they can’t be fetched", async () => {
    vi.mocked(api).mockImplementation(async () => ({ emails: [] }));
    const { unmount } = render(GateCode, { segment: pending, now: NOW });
    await user.click(screen.getByRole("button", { name: /Choose the code/ }));
    expect(await screen.findByText("These emails have no pictures to choose from.")).toBeInTheDocument();
    unmount();
    vi.mocked(api).mockRejectedValue(new Error("down"));
    render(GateCode, { segment: pending, now: NOW });
    await user.click(screen.getByRole("button", { name: /Choose the code/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The pictures can’t be shown right now.");
  });

  it("skips a picture that fails to load and stops at a sign-out", async () => {
    vi.mocked(apiImage).mockImplementation(async (path) => { if (path.endsWith("/images/0")) throw Object.assign(new Error("x"), { status: 404 }); return OTHER; });
    render(GateCode, { segment: pending, now: NOW });
    await user.click(screen.getByRole("button", { name: /Choose the code/ }));
    const list = await screen.findByRole("list", { name: "Pictures in the emails" });
    expect(within(list).getAllByRole("button")).toHaveLength(1);
  });

  it("stops listing pictures when the session has ended", async () => {
    vi.mocked(apiImage).mockRejectedValue(Object.assign(new Error("x"), { status: 401 }));
    render(GateCode, { segment: pending, now: NOW });
    await user.click(screen.getByRole("button", { name: /Choose the code/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The pictures can’t be shown right now.");
  });

  it("also offers another picture beside a code that is shown, only when the booking has emails", async () => {
    const { unmount } = render(GateCode, { segment: lot, now: NOW });
    await user.click(screen.getByRole("button", { name: /Choose another picture/ }));
    expect(await screen.findByRole("dialog", { name: "Choose the code" })).toBeInTheDocument();
    unmount();
    render(GateCode, { segment: { ...lot, has_email: false }, now: NOW });
    expect(screen.queryByRole("button", { name: /Choose another picture/ })).toBeNull();
  });
});

describe("the saved picture in the iPhone app with no connection", () => {
  const saved = (codes: { segment_id: number; type: string; data: string }[] | undefined) => ({ trip: { id: 1, segments: [lot] }, messages: [], savedAt: 1, ...(codes ? { codes } : {}) });
  const offlineShell = (...copies: unknown[]) => {
    vi.mocked(inShell).mockReturnValue(true);
    vi.mocked(shellLoad).mockResolvedValue(copies);
    vi.mocked(apiImage).mockRejectedValue(new TypeError("Failed to fetch"));
  };

  it("shows the picture saved with the trip for a ready booking", async () => {
    offlineShell(saved([{ segment_id: 3, type: "image/png", data: "AAAA" }, { segment_id: 7, type: "image/png", data: "QUJD" }]));
    render(GateCode, { segment: lot, now: NOW });
    await user.click(screen.getByRole("button", { name: /Show QR code/ }));
    expect(await screen.findByRole("img", { name: "QR code for Example Airport Long-Term Lot" })).toHaveAttribute("src", "data:image/png;base64,QUJD");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows the failure line and the confirmation number when the ready booking has no saved picture (frame B2)", async () => {
    offlineShell(saved([{ segment_id: 3, type: "image/png", data: "AAAA" }]), saved(undefined));
    render(GateCode, { segment: lot, now: NOW });
    await user.click(screen.getByRole("button", { name: /Show QR code/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The code can’t be shown right now");
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByTestId("code-confirmation")).toHaveTextContent("Confirmation PK30417");
  });

  it("shows the failure line and the confirmation number when the saved trips can’t be read", async () => {
    offlineShell();
    vi.mocked(shellLoad).mockRejectedValue(new Error("unreadable"));
    render(GateCode, { segment: lot, now: NOW });
    await user.click(screen.getByRole("button", { name: /Show QR code/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The code can’t be shown right now");
    expect(screen.getByTestId("code-confirmation")).toBeInTheDocument();
  });

  it("treats a gateway failure from a proxy or tunnel like no connection", async () => {
    for (const status of [502, 503, 504]) {
      offlineShell(saved([{ segment_id: 7, type: "image/png", data: "QUJD" }]));
      vi.mocked(apiImage).mockRejectedValue(Object.assign(new Error("Bad gateway"), { status }));
      const { unmount } = render(GateCode, { segment: lot, now: NOW });
      await user.click(screen.getByRole("button", { name: /Show QR code/ }));
      expect(await screen.findByRole("img", { name: "QR code for Example Airport Long-Term Lot" })).toHaveAttribute("src", "data:image/png;base64,QUJD");
      unmount();
    }
  });

  it("does not look in the saved trips when the server answers, even in the app", async () => {
    vi.mocked(inShell).mockReturnValue(true);
    vi.mocked(shellLoad).mockResolvedValue([saved([{ segment_id: 7, type: "image/png", data: "QUJD" }])]);
    vi.mocked(apiImage).mockRejectedValue(Object.assign(new Error("No such image"), { status: 404 }));
    render(GateCode, { segment: lot, now: NOW });
    await user.click(screen.getByRole("button", { name: /Show QR code/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The code can’t be shown right now");
    expect(shellLoad).not.toHaveBeenCalled();
    expect(screen.queryByTestId("code-confirmation")).toBeNull();
  });

  it("is unchanged in a browser: no saved picture and no confirmation number", async () => {
    vi.mocked(apiImage).mockRejectedValue(new TypeError("Failed to fetch"));
    render(GateCode, { segment: lot, now: NOW });
    await user.click(screen.getByRole("button", { name: /Show QR code/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The code can’t be shown right now");
    expect(shellLoad).not.toHaveBeenCalled();
    expect(screen.queryByTestId("code-confirmation")).toBeNull();
  });
});
