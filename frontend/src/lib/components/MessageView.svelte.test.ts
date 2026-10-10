// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ apiImage: vi.fn() }));

import { apiImage } from "$lib/api";
import MessageView from "./MessageView.svelte";

const frameOf = () => screen.getByTestId("preview-html") as HTMLIFrameElement;
const pageOf = () => frameOf().getAttribute("srcdoc") ?? "";

beforeEach(() => { vi.mocked(apiImage).mockReset(); });

describe("MessageView", () => {
  it("shows the subject and the text, and says when it was cut short", () => {
    render(MessageView, { subject: "Your itinerary", text: "Gate B12", truncated: true });
    expect(screen.getByTestId("message-subject")).toHaveTextContent("Your itinerary");
    expect(screen.getByText("Gate B12")).toBeInTheDocument();
    expect(screen.getByText("This email was cut short.")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows the email in a sandboxed frame that can run no script and reach nothing but its own pictures", () => {
    render(MessageView, { text: "Gate B12", html: "<table><tr><td style=\"color:#112233\">Gate <b>B12</b></td></tr></table>" });
    const sandbox = frameOf().getAttribute("sandbox") ?? "";
    expect(sandbox.split(" ").sort()).toEqual(["allow-popups", "allow-popups-to-escape-sandbox"]);
    expect(sandbox).not.toContain("allow-scripts");
    expect(sandbox).not.toContain("allow-same-origin");
    expect(frameOf().getAttribute("referrerpolicy")).toBe("no-referrer");
    const page = pageOf();
    expect(page).toContain("<b>B12</b>");
    expect(page).toContain('http-equiv="Content-Security-Policy"');
    expect(page).toContain("default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'");
    expect(page).not.toMatch(/<script/i);
    expect(screen.queryByTestId("message-old")).toBeNull();
  });

  it("shows markup formatted, with a switch to its plain text and back", async () => {
    render(MessageView, { text: "Gate B12", html: "<p>Gate <b>B12</b></p>" });
    await userEvent.click(screen.getByRole("button", { name: "Show as plain text" }));
    expect(screen.queryByTestId("preview-html")).toBeNull();
    expect(screen.getByText("Gate B12")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show as formatted" }));
    expect(screen.getByTestId("preview-html")).toBeInTheDocument();
  });

  it("fetches each kept picture through the app’s own route and puts it in the page as data, never as an address", async () => {
    vi.mocked(apiImage).mockImplementation(async (path) => `data:image/png;base64,${path.endsWith("/0") ? "AAAA" : "BBBB"}`);
    render(MessageView, { text: "Hi", html: '<p>Hi</p><img data-i="0" alt="Logo" width="64"><img data-i="1" alt="">', images: 2, imagesAt: "/api/review/7/images/" });
    await waitFor(() => expect(pageOf()).toContain('src="data:image/png;base64,AAAA"'));
    expect(pageOf()).toContain('src="data:image/png;base64,BBBB"');
    expect(pageOf()).not.toContain("data-i");
    expect(vi.mocked(apiImage).mock.calls.map((c) => c[0]).sort()).toEqual(["/api/review/7/images/0", "/api/review/7/images/1"]);
    expect(pageOf()).not.toMatch(/https?:/);
  });

  it("leaves out a picture that can’t be fetched and still shows the email", async () => {
    vi.mocked(apiImage).mockImplementation(async (path) => { if (path.endsWith("/1")) throw new Error("gone"); return "data:image/png;base64,AAAA"; });
    render(MessageView, { text: "Hi", html: '<p>Hi</p><img data-i="0" alt="A"><img data-i="1" alt="B">', images: 2, imagesAt: "/api/segments/3/emails/0/images/" });
    await waitFor(() => expect(pageOf()).toContain('src="data:image/png;base64,AAAA"'));
    expect(pageOf()).toContain('alt="B"');
    expect(pageOf()).not.toContain('data-i="1" src');
    expect(pageOf()).toContain("<p>Hi</p>");
  });

  it("asks for no pictures when it has none, or no place to ask", () => {
    render(MessageView, { text: "Hi", html: '<img data-i="0" alt="A">', images: 1 });
    render(MessageView, { text: "Hi", html: "<p>Hi</p>", images: 0, imagesAt: "/api/review/7/images/" });
    expect(apiImage).not.toHaveBeenCalled();
  });

  it("says when an email was kept before the original could be shown", () => {
    render(MessageView, { text: "Gate B12", html: "<p>Gate B12</p>", original: false });
    expect(screen.getByTestId("message-old")).toHaveTextContent("can’t be shown");
    expect(pageOf()).toContain("<p>Gate B12</p>");
  });

  it("is not cut short until the server says it was", () => {
    const long = "word ".repeat(40_000);
    const { unmount } = render(MessageView, { text: long, html: `<p>${long}</p>`, truncated: false });
    expect(screen.queryByText(/cut short/)).toBeNull();
    expect(pageOf().length).toBeGreaterThan(190_000);
    unmount();
    render(MessageView, { text: "Gate B12", truncated: true });
    expect(screen.getByText("This email was cut short.")).toBeInTheDocument();
  });

  it("says when a message has no text", () => {
    render(MessageView, { text: "" });
    expect(screen.getByText("(This message has no text.)")).toBeInTheDocument();
  });
});
