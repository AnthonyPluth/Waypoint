// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ apiImage: vi.fn() }));

import { apiImage } from "$lib/api";
import MessageView from "./MessageView.svelte";

const hostOf = () => screen.getByTestId("preview-html");
const pageOf = () => hostOf().shadowRoot?.innerHTML ?? "";

beforeEach(() => { vi.mocked(apiImage).mockReset(); });

describe("MessageView", () => {
  it("shows the subject and the text, and says when it was cut short", () => {
    render(MessageView, { subject: "Your itinerary", text: "Gate B12", truncated: true });
    expect(screen.getByTestId("message-subject")).toHaveTextContent("Your itinerary");
    expect(screen.getByText("Gate B12")).toBeInTheDocument();
    expect(screen.getByText("This email was cut short.")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows the email inline in a shadow root, with no frame, no script and nothing but its own pictures", () => {
    render(MessageView, { text: "Gate B12", html: "<table><tr><td style=\"color:#112233\">Gate <b>B12</b></td></tr></table>" });
    expect(document.querySelector("iframe")).toBeNull();
    const root = hostOf().shadowRoot as ShadowRoot;
    expect(root.querySelector("b")?.textContent).toBe("B12");
    expect(root.querySelector("td")?.getAttribute("style")).toBe("color:#112233");
    expect(root.querySelector("script, iframe, form, [onclick]")).toBeNull();
    expect(document.body.textContent).not.toContain("Gate B12");
    expect(screen.queryByTestId("message-old")).toBeNull();
  });

  it("gives the email the app’s own colours in one wrapper, so a dark app never shows dark on dark", () => {
    render(MessageView, { text: "Gate B12", html: "<p>Gate B12</p>" });
    const root = hostOf().shadowRoot as ShadowRoot;
    const sheet = root.querySelector("style")?.textContent ?? "";
    expect(sheet).toContain("background:var(--muted);color:var(--foreground)");
    expect(root.querySelectorAll(".email")).toHaveLength(1);
    expect(root.querySelector(".email p")).not.toBeNull();
    expect(hostOf().getAttribute("style")).toMatch(/^all: initial;/);
  });

  it("isolates styles in both directions", () => {
    const appStyle = document.createElement("style");
    appStyle.textContent = "p{color:red;display:none}";
    document.head.append(appStyle);
    const head = document.head.innerHTML;
    render(MessageView, { text: "Hi", html: '<p style="color:#ff0000;background-color:#00ff00">Hi</p><div style="position:fixed;top:0">x</div><style>p{display:none}</style>' });
    const root = hostOf().shadowRoot as ShadowRoot;
    expect(document.head.innerHTML).toBe(head);
    expect(document.querySelectorAll("p")).toHaveLength(0);
    expect(Array.from(document.querySelectorAll("[style]")).some((e) => /ff0000|position/.test(e.getAttribute("style") ?? ""))).toBe(false);
    expect(root.querySelectorAll("style")).toHaveLength(1);
    expect(root.querySelector("style")?.textContent).not.toContain("display:none");
    expect(root.querySelector("p")?.getAttribute("style")).toBe("color:#ff0000;background-color:#00ff00");
    expect(root.querySelector("div")?.hasAttribute("style")).toBe(false);
    appStyle.remove();
  });

  it("contains the email: the sizer clips it and the host is cut off from the app's layout", () => {
    render(MessageView, { text: "Hi", html: '<div style="margin:-9999px;width:99999px;height:99999px">x</div>' });
    expect(screen.getByTestId("preview-sizer").className).toContain("overflow-hidden");
    expect(hostOf().getAttribute("style")).toMatch(/all: initial;/);
    expect(hostOf().getAttribute("style")).toContain("contain: paint");
    expect(hostOf().shadowRoot?.querySelector(".email div")?.hasAttribute("style")).toBe(false);
  });

  it("opens a link in a new tab without the opener, and a click never reaches or navigates the app", async () => {
    const reached = vi.fn();
    document.addEventListener("click", reached);
    const before = location.href;
    render(MessageView, { text: "Hi", html: '<p><a href="https://example.com/a?b=1" onclick="alert(1)" target="_self">go</a> <a href="javascript:alert(1)">bad</a> <a href="http://example.com">plain</a></p>' });
    const root = hostOf().shadowRoot as ShadowRoot;
    const links = Array.from(root.querySelectorAll("a"));
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["https://example.com/a?b=1", null, null]);
    expect(links[0].getAttribute("target")).toBe("_blank");
    expect(links[0].getAttribute("rel")).toBe("noopener noreferrer");
    expect(links[0].hasAttribute("onclick")).toBe(false);
    links[0].addEventListener("click", (e) => e.preventDefault());
    await userEvent.click(links[0]);
    expect(reached).not.toHaveBeenCalled();
    expect(location.href).toBe(before);
    document.removeEventListener("click", reached);
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
    expect(vi.mocked(apiImage).mock.calls.map((c) => c[0]).sort()).toEqual(["/api/review/7/images/0", "/api/review/7/images/1"]);
    expect(pageOf()).not.toMatch(/https?:/);
  });

  it("leaves out a picture that can’t be fetched and still shows the email", async () => {
    vi.mocked(apiImage).mockImplementation(async (path) => { if (path.endsWith("/1")) throw new Error("gone"); return "data:image/png;base64,AAAA"; });
    render(MessageView, { text: "Hi", html: '<p>Hi</p><img data-i="0" alt="A"><img data-i="1" alt="B">', images: 2, imagesAt: "/api/segments/3/emails/0/images/" });
    await waitFor(() => expect(pageOf()).toContain('src="data:image/png;base64,AAAA"'));
    expect(pageOf()).toContain('alt="B"');
    expect(hostOf().shadowRoot?.querySelector('img[data-i="1"]')?.hasAttribute("src")).toBe(false);
    expect(pageOf()).toContain("<p>Hi</p>");
  });

  it("stops asking for pictures at the first refusal to sign in, so the sign-out handlers run once", async () => {
    vi.mocked(apiImage).mockRejectedValue(Object.assign(new Error("denied"), { status: 403 }));
    render(MessageView, { text: "Hi", html: '<p>Hi</p><img data-i="0" alt="A"><img data-i="1" alt="B"><img data-i="2" alt="C">', images: 3, imagesAt: "/api/review/7/images/" });
    await waitFor(() => expect(hostOf().getAttribute("aria-busy")).toBe("false"));
    expect(apiImage).toHaveBeenCalledTimes(1);
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
    expect(hostOf().shadowRoot?.textContent?.length).toBeGreaterThan(190_000);
    unmount();
    render(MessageView, { text: "Gate B12", truncated: true });
    expect(screen.getByText("This email was cut short.")).toBeInTheDocument();
  });

  it("says when a message has no text", () => {
    render(MessageView, { text: "" });
    expect(screen.getByText("(This message has no text.)")).toBeInTheDocument();
  });
});
