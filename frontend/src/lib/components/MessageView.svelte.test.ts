// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import MessageView from "./MessageView.svelte";

const LAYOUT = '<table width="600"><tr><td style="color: #0b3d91"><img data-image="0" alt="Example Air logo" width="200"></td></tr><tr><td>Gate <b>B12</b></td></tr></table>';
const png = { type: "image/png", data: "iVBORw0KGgo=" };

function frame(): HTMLIFrameElement {
  return screen.getByTestId("email-frame") as HTMLIFrameElement;
}

describe("MessageView", () => {
  it("shows the subject and the text, and says when it was cut short", () => {
    render(MessageView, { subject: "Your itinerary", text: "Gate B12", truncated: true });
    expect(screen.getByTestId("message-subject")).toHaveTextContent("Your itinerary");
    expect(screen.getByText("Gate B12")).toBeInTheDocument();
    expect(screen.getByText("This email was cut short because it is very long.")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("is not cut short unless the server says it went past the cap, however long it is", () => {
    render(MessageView, { text: "word ".repeat(200_000), truncated: false, full: true });
    expect(screen.queryByTestId("cut-short")).toBeNull();
    expect(screen.getByText(/word word word/).textContent).toHaveLength(1_000_000);
  });

  it("shows markup formatted, with a switch to its plain text and back", async () => {
    render(MessageView, { text: "Gate B12", html: "<p>Gate <b>B12</b></p>" });
    expect(screen.queryByTestId("message-subject")).toBeNull();
    expect(screen.getByTestId("preview-html").querySelector("b")).toHaveTextContent("B12");
    await userEvent.click(screen.getByRole("button", { name: "Show as plain text" }));
    expect(screen.queryByTestId("preview-html")).toBeNull();
    expect(screen.getByText("Gate B12")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show as formatted" }));
    expect(screen.getByTestId("preview-html")).toBeInTheDocument();
  });

  it("says when a message has no text", () => {
    render(MessageView, { text: "" });
    expect(screen.getByText("(This message has no text.)")).toBeInTheDocument();
  });

  it("shows a whole message in a sandboxed frame that can't run script or reach out, with its pictures", async () => {
    const loadImages = vi.fn().mockResolvedValue([png]);
    render(MessageView, { subject: "Your itinerary", text: "Gate B12", html: "<p>Old</p>", layout: LAYOUT, images: 1, loadImages, full: true });
    await waitFor(() => expect(screen.getByTestId("email-frame")).toBeInTheDocument());
    const box = frame();
    expect(box.getAttribute("sandbox")).toBe("allow-popups allow-popups-to-escape-sandbox");
    expect(box.getAttribute("sandbox")).not.toMatch(/allow-scripts|allow-same-origin/);
    expect(box.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(box.getAttribute("title")).toBe("The email: Your itinerary");
    const page = box.getAttribute("srcdoc") ?? "";
    expect(page).toContain("Content-Security-Policy");
    expect(page).toContain("img-src data:");
    expect(page).toContain("default-src 'none'");
    expect(page).not.toMatch(/<script|onerror|onclick|src="https?:/i);
    expect(page).toContain('src="data:image/png;base64,iVBORw0KGgo="');
    expect(page).toContain("Gate <b>B12</b>");
    expect(page).toContain('style="color: #0b3d91"');
    expect(loadImages).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("preview-html")).toBeNull();
    expect(screen.queryByTestId("original-unavailable")).toBeNull();
  });

  it("waits for the pictures before showing the frame, and shows the email without them when they can't be loaded", async () => {
    let fail: (e: Error) => void = () => {};
    const loadImages = vi.fn(() => new Promise<never>((_, reject) => { fail = reject; }));
    render(MessageView, { text: "Gate B12", layout: LAYOUT, images: 1, loadImages });
    expect(screen.getByRole("status")).toHaveTextContent("Opening the email");
    expect(screen.queryByTestId("email-frame")).toBeNull();
    fail(new Error("Waypoint is busy."));
    expect(await screen.findByRole("alert")).toHaveTextContent("The pictures couldn’t be loaded: Waypoint is busy.");
    const page = frame().getAttribute("srcdoc") ?? "";
    expect(page).toContain("Example Air logo");
    expect(page).not.toContain("<img");
  });

  it("opens straight away when the message has no pictures", () => {
    const loadImages = vi.fn();
    render(MessageView, { text: "Gate B12", layout: LAYOUT.replace(/<img[^>]*>/, ""), images: 0, loadImages });
    expect(screen.getByTestId("email-frame")).toBeInTheDocument();
    expect(loadImages).not.toHaveBeenCalled();
  });

  it("switches between the frame and the plain text", async () => {
    render(MessageView, { text: "Gate B12 in plain words", layout: LAYOUT, images: 0 });
    await userEvent.click(screen.getByRole("button", { name: "Show as plain text" }));
    expect(screen.queryByTestId("email-frame")).toBeNull();
    expect(screen.getByText("Gate B12 in plain words")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show as formatted" }));
    expect(screen.getByTestId("email-frame")).toBeInTheDocument();
  });

  it("shows a message kept before the full message was kept as it was, with a line saying the original can't be shown", () => {
    render(MessageView, { text: "Gate B12", html: "<p>Gate <b>B12</b></p>", full: false, layout: null, images: 0 });
    expect(screen.getByTestId("original-unavailable")).toHaveTextContent("The original can’t be shown for this email");
    expect(screen.getByTestId("preview-html").querySelector("b")).toHaveTextContent("B12");
    expect(screen.queryByTestId("email-frame")).toBeNull();
  });

  it("says the device keeps the text when the email is the copy saved for offline use", () => {
    render(MessageView, { text: "Gate B12", html: "<p>Gate B12</p>", full: false, offline: true });
    expect(screen.getByTestId("not-saved-here")).toHaveTextContent("This device keeps the text of the email");
    expect(screen.queryByTestId("original-unavailable")).toBeNull();
  });

  it("shows a text-only message whole without any note", () => {
    render(MessageView, { text: "Just words", full: true, layout: null });
    expect(screen.getByText("Just words")).toBeInTheDocument();
    expect(screen.queryByTestId("original-unavailable")).toBeNull();
  });
});
