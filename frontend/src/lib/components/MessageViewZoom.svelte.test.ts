// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { tick } from "svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ apiImage: vi.fn() }));

import MessageView from "./MessageView.svelte";

type Watcher = { callback: ResizeObserverCallback; target: Element | null };
const watchers: Watcher[] = [];

class FakeResizeObserver {
  watcher: Watcher = { callback: () => {}, target: null };
  constructor(callback: ResizeObserverCallback) { this.watcher.callback = callback; watchers.push(this.watcher); }
  observe(target: Element) { this.watcher.target = target; }
  unobserve() {}
  disconnect() { this.watcher.target = null; }
}

async function resizeTo(width: number, height = 480, which = "first") {
  const live = watchers.filter((w) => w.target);
  const chosen = which === "first" ? live[0] : live[live.length - 1];
  chosen.callback([{ contentRect: { width, height } } as ResizeObserverEntry], {} as ResizeObserver);
  await tick();
}

const frameOf = () => screen.getByTestId("preview-html") as HTMLIFrameElement;
const pageOf = () => frameOf().getAttribute("srcdoc") ?? "";
const level = () => screen.getByTestId("zoom-level").textContent;
const sizerOf = () => screen.getByTestId("preview-sizer") as HTMLElement;
const FIXED = '<table width="600"><tr><td>Gate B12</td></tr></table>';
const SANDBOX = ["allow-popups", "allow-popups-to-escape-sandbox"];

beforeEach(() => {
  watchers.length = 0;
  vi.stubGlobal("ResizeObserver", FakeResizeObserver);
});

describe("fitting and zooming the email", () => {
  it("scales a layout wider than its box down to fit, with no sideways scroll", async () => {
    render(MessageView, { text: "Hi", html: FIXED, width: 600 });
    await resizeTo(300);
    expect(level()).toBe("50%");
    expect(frameOf().style.width).toBe("600px");
    expect(frameOf().style.transform).toBe("scale(0.5)");
    expect(sizerOf().style.width).toBe("300px");
    expect(sizerOf().style.height).toBe("480px");
    expect(frameOf().style.height).toBe("960px");
  });

  it("keeps a narrower layout, a flexible one and a missing width at 100%", async () => {
    const { unmount } = render(MessageView, { text: "Hi", html: FIXED, width: 600 });
    await resizeTo(900);
    expect(level()).toBe("100%");
    expect(frameOf().style.transform).toBe("scale(1)");
    expect(frameOf().style.width).toBe("900px");
    unmount();
    watchers.length = 0;
    render(MessageView, { text: "Hi", html: "<p>Hi</p>", width: null });
    await resizeTo(320);
    expect(level()).toBe("100%");
    expect(frameOf().style.width).toBe("320px");
    expect(sizerOf().style.width).toBe("320px");
  });

  it("zooms in and out in steps of 25% between fit and 300%, and Fit restores the default", async () => {
    render(MessageView, { text: "Hi", html: FIXED, width: 600 });
    await resizeTo(420);
    expect(level()).toBe("70%");
    const zoomIn = screen.getByRole("button", { name: "Zoom in" });
    const zoomOut = screen.getByRole("button", { name: "Zoom out" });
    const fit = screen.getByRole("button", { name: "Fit" });
    expect(zoomOut).toBeDisabled();
    expect(fit).toBeDisabled();
    const seen: string[] = [];
    for (let i = 0; i < 12; i++) { await userEvent.click(zoomIn); seen.push(level() ?? ""); }
    expect(seen.slice(0, 4)).toEqual(["75%", "100%", "125%", "150%"]);
    expect(seen[seen.length - 1]).toBe("300%");
    expect(zoomIn).toBeDisabled();
    expect(sizerOf().style.width).toBe("1800px");
    await userEvent.click(zoomOut);
    expect(level()).toBe("275%");
    await userEvent.click(fit);
    expect(level()).toBe("70%");
    expect(fit).toBeDisabled();
    await userEvent.click(zoomIn);
    await userEvent.click(zoomOut);
    expect(level()).toBe("70%");
  });

  it("zooms a flexible layout from 100% as well", async () => {
    render(MessageView, { text: "Hi", html: "<p>Hi</p>" });
    await resizeTo(400);
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(level()).toBe("125%");
    expect(frameOf().style.width).toBe("400px");
    expect(sizerOf().style.width).toBe("500px");
  });

  it("has real buttons that work from the keyboard and announces the new zoom politely", async () => {
    render(MessageView, { text: "Hi", html: FIXED, width: 600 });
    await resizeTo(300);
    const live = screen.getByTestId("zoom-level");
    expect(live.getAttribute("aria-live")).toBe("polite");
    const zoomIn = screen.getByRole("button", { name: "Zoom in" });
    zoomIn.focus();
    await userEvent.keyboard("{Enter}");
    expect(live).toHaveTextContent("75%");
    await userEvent.keyboard(" ");
    expect(live).toHaveTextContent("100%");
    screen.getByRole("button", { name: "Zoom out" }).focus();
    await userEvent.keyboard("{Enter}");
    expect(live).toHaveTextContent("75%");
    screen.getByRole("button", { name: "Fit" }).focus();
    await userEvent.keyboard("{Enter}");
    expect(live).toHaveTextContent("50%");
  });

  it("refits when its container is resized and keeps a zoom that is still above the fit", async () => {
    render(MessageView, { text: "Hi", html: FIXED, width: 600 });
    await resizeTo(300);
    expect(level()).toBe("50%");
    await resizeTo(450);
    expect(level()).toBe("75%");
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(level()).toBe("125%");
    await resizeTo(200);
    expect(level()).toBe("125%");
    await resizeTo(1000);
    expect(level()).toBe("125%");
    expect(sizerOf().style.width).toBe("1250px");
  });

  it("has no zoom controls for a message kept before originals could be shown or one with no markup", async () => {
    const old = render(MessageView, { text: "Gate B12", html: "<p>Gate B12</p>", original: false });
    expect(screen.queryByRole("button", { name: "Zoom in" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Larger view/ })).toBeNull();
    expect(screen.getByTestId("message-old")).toBeInTheDocument();
    old.unmount();
    render(MessageView, { text: "Gate B12" });
    expect(screen.queryByRole("button", { name: "Zoom in" })).toBeNull();
    expect(screen.queryByTestId("zoom-level")).toBeNull();
    expect(screen.getByText("Gate B12")).toBeInTheDocument();
  });

  it("starts every preview at fit and writes nothing to the browser’s storage", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const first = render(MessageView, { text: "Hi", html: FIXED, width: 600 });
    await resizeTo(300);
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(level()).toBe("75%");
    first.unmount();
    watchers.length = 0;
    render(MessageView, { text: "Hi", html: FIXED, width: 600 });
    await resizeTo(300);
    expect(level()).toBe("50%");
    expect(setItem).not.toHaveBeenCalled();
    setItem.mockRestore();
  });

  it("keeps the frame’s sandbox and policy as they were, however it is scaled, and puts none of the email in the page", async () => {
    render(MessageView, { text: "Hi", html: FIXED, width: 600 });
    await resizeTo(300);
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect((frameOf().getAttribute("sandbox") ?? "").split(" ").sort()).toEqual(SANDBOX);
    expect(pageOf()).toContain("default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'");
    expect(document.querySelector("table")).toBeNull();
    expect(document.body.textContent).not.toContain("Gate B12");
  });
});

describe("the larger view", () => {
  it("opens at fit with the same controls, and closes with its button, returning focus", async () => {
    render(MessageView, { subject: "Your itinerary", text: "Hi", html: FIXED, width: 600 });
    await resizeTo(300);
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    const opener = screen.getByRole("button", { name: "Larger view" });
    await userEvent.click(opener);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("The email: Your itinerary")).toBeInTheDocument();
    await resizeTo(560, 700, "last");
    expect(within(dialog).getByTestId("zoom-level")).toHaveTextContent("93%");
    expect(within(dialog).getByRole("button", { name: "Zoom out" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Fit" })).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Zoom in" }));
    expect(within(dialog).getByTestId("zoom-level")).toHaveTextContent("100%");
    await userEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(opener).toHaveFocus();
    expect(screen.getByTestId("zoom-level")).toHaveTextContent("75%");
  });

  it("closes with Escape, returns focus to its button and opens at fit again", async () => {
    render(MessageView, { text: "Hi", html: FIXED, width: 600 });
    await resizeTo(300);
    const opener = screen.getByRole("button", { name: "Larger view" });
    await userEvent.click(opener);
    let dialog = await screen.findByRole("dialog");
    await resizeTo(560, 700, "last");
    await userEvent.click(within(dialog).getByRole("button", { name: "Zoom in" }));
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(opener).toHaveFocus();
    await waitFor(() => expect(document.body.style.pointerEvents).not.toBe("none"));
    await userEvent.click(opener);
    dialog = await screen.findByRole("dialog");
    await resizeTo(560, 700, "last");
    expect(within(dialog).getByTestId("zoom-level")).toHaveTextContent("93%");
  });

  it("shows the same page in the same sandbox", async () => {
    render(MessageView, { text: "Hi", html: FIXED, width: 600 });
    const outside = pageOf();
    await userEvent.click(screen.getByRole("button", { name: "Larger view" }));
    const dialog = await screen.findByRole("dialog");
    const inside = within(dialog).getByTestId("preview-html");
    expect((inside.getAttribute("sandbox") ?? "").split(" ").sort()).toEqual(SANDBOX);
    expect(inside.getAttribute("srcdoc")).toBe(outside);
  });
});
