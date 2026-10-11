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

async function measure(testid: string, width: number, height: number, which: "first" | "last" = "first") {
  const live = watchers.filter((w) => w.target?.getAttribute("data-testid") === testid);
  const chosen = which === "first" ? live[0] : live[live.length - 1];
  chosen.callback([{ contentRect: { width, height } } as ResizeObserverEntry], {} as ResizeObserver);
  await tick();
}

async function lay(box: number, layout: number, height = 400, which: "first" | "last" = "first") {
  await measure("preview-viewport", box, 480, which);
  await measure("preview-html", layout, height, which);
}

const hostOf = () => screen.getByTestId("preview-html");
const level = () => screen.getByTestId("zoom-level").textContent;
const sizerOf = () => screen.getByTestId("preview-sizer") as HTMLElement;
const FIXED = '<table width="600"><tr><td>Gate B12</td></tr></table>';

beforeEach(() => {
  watchers.length = 0;
  vi.stubGlobal("ResizeObserver", FakeResizeObserver);
});

describe("fitting and zooming the email", () => {
  it("scales a layout wider than its box down to fit, with no sideways scroll", async () => {
    render(MessageView, { text: "Hi", html: FIXED });
    await lay(300, 600);
    expect(level()).toBe("50%");
    expect(hostOf().style.transform).toBe("scale(0.5)");
    expect(sizerOf().style.width).toBe("300px");
    expect(sizerOf().style.height).toBe("200px");
  });

  it("fits at phone, tablet and desktop widths", async () => {
    const seen: Record<string, string | null> = {};
    for (const [name, box] of [["phone", 375], ["tablet", 768], ["desktop", 1280]] as const) {
      watchers.length = 0;
      const view = render(MessageView, { text: "Hi", html: FIXED });
      await lay(box, Math.max(600, box));
      seen[name] = level();
      expect(sizerOf().style.width, name).toBe(`${Math.min(box, Math.max(600, box)) * 1}px`);
      view.unmount();
    }
    expect(seen).toEqual({ phone: "63%", tablet: "100%", desktop: "100%" });
  });

  it("keeps a narrower layout and a flexible one at 100%", async () => {
    const { unmount } = render(MessageView, { text: "Hi", html: FIXED });
    await lay(900, 900);
    expect(level()).toBe("100%");
    expect(hostOf().style.transform).toBe("scale(1)");
    unmount();
    watchers.length = 0;
    render(MessageView, { text: "Hi", html: "<p>Hi</p>" });
    await lay(320, 320);
    expect(level()).toBe("100%");
    expect(sizerOf().style.width).toBe("320px");
  });

  it("zooms in and out in steps of 25% between fit and 300%, and Fit restores the default", async () => {
    render(MessageView, { text: "Hi", html: FIXED });
    await lay(420, 600);
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
    await lay(400, 400);
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(level()).toBe("125%");
    expect(sizerOf().style.width).toBe("500px");
    expect(hostOf().style.transform).toBe("scale(1.25)");
  });

  it("has real buttons that work from the keyboard and announces the new zoom politely", async () => {
    render(MessageView, { text: "Hi", html: FIXED });
    await lay(300, 600);
    const live = screen.getByTestId("zoom-level");
    expect(live.getAttribute("aria-live")).toBe("polite");
    screen.getByRole("button", { name: "Zoom in" }).focus();
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
    render(MessageView, { text: "Hi", html: FIXED });
    await lay(300, 600);
    expect(level()).toBe("50%");
    await lay(450, 600);
    expect(level()).toBe("75%");
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(level()).toBe("125%");
    await lay(200, 600);
    expect(level()).toBe("125%");
    await lay(1000, 1000);
    expect(level()).toBe("125%");
    expect(sizerOf().style.width).toBe("1250px");
  });

  it("has no zoom controls in the plain-text view or for a message kept before originals could be shown", async () => {
    const old = render(MessageView, { text: "Gate B12", html: "<p>Gate B12</p>", original: false });
    expect(screen.queryByRole("button", { name: "Zoom in" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Larger view/ })).toBeNull();
    expect(screen.getByTestId("message-old")).toBeInTheDocument();
    old.unmount();
    render(MessageView, { text: "Gate B12", html: FIXED });
    await userEvent.click(screen.getByRole("button", { name: "Show as plain text" }));
    expect(screen.queryByRole("button", { name: "Zoom in" })).toBeNull();
    expect(screen.queryByTestId("zoom-level")).toBeNull();
    expect(screen.getByText("Gate B12")).toBeInTheDocument();
  });

  it("starts every preview at fit and writes nothing to the browser’s storage", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const first = render(MessageView, { text: "Hi", html: FIXED });
    await lay(300, 600);
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(level()).toBe("75%");
    first.unmount();
    watchers.length = 0;
    render(MessageView, { text: "Hi", html: FIXED });
    await lay(300, 600);
    expect(level()).toBe("50%");
    expect(setItem).not.toHaveBeenCalled();
    setItem.mockRestore();
  });

  it("puts the email in a shadow root with no frame, and none of it in the page", async () => {
    render(MessageView, { text: "Hi", html: FIXED });
    await lay(300, 600);
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(document.querySelector("iframe")).toBeNull();
    expect(hostOf().shadowRoot?.querySelector("table")).not.toBeNull();
    expect(document.querySelector("table")).toBeNull();
    expect(document.body.textContent).not.toContain("Gate B12");
  });
});

describe("the larger view", () => {
  it("opens at fit with the same controls, and closes with its button, returning focus", async () => {
    render(MessageView, { subject: "Your itinerary", text: "Hi", html: FIXED });
    await lay(300, 600);
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    const opener = screen.getByRole("button", { name: "Larger view" });
    await userEvent.click(opener);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("The email: Your itinerary")).toBeInTheDocument();
    await lay(560, 600, 400, "last");
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
    render(MessageView, { text: "Hi", html: FIXED });
    await lay(300, 600);
    const opener = screen.getByRole("button", { name: "Larger view" });
    await userEvent.click(opener);
    let dialog = await screen.findByRole("dialog");
    await lay(560, 600, 400, "last");
    await userEvent.click(within(dialog).getByRole("button", { name: "Zoom in" }));
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(opener).toHaveFocus();
    await waitFor(() => expect(document.body.style.pointerEvents).not.toBe("none"));
    await userEvent.click(opener);
    dialog = await screen.findByRole("dialog");
    await lay(560, 600, 400, "last");
    expect(within(dialog).getByTestId("zoom-level")).toHaveTextContent("93%");
  });

  it("shows the same email in its own shadow root, with the same markup", async () => {
    render(MessageView, { text: "Hi", html: FIXED });
    const outside = hostOf().shadowRoot?.innerHTML;
    await userEvent.click(screen.getByRole("button", { name: "Larger view" }));
    const dialog = await screen.findByRole("dialog");
    const inside = within(dialog).getByTestId("preview-html");
    expect(inside).not.toBe(screen.getAllByTestId("preview-html")[0]);
    expect(inside.shadowRoot?.innerHTML).toBe(outside);
    expect(dialog.querySelector("iframe")).toBeNull();
  });
});
