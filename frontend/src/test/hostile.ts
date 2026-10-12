import { vi } from "vitest";
import corpus from "./hostile-corpus.json";

export type Payload = { name: string; html: string; canary: string; cleaned: string; cleanedWithPictures: string };

export const payloads: Payload[] = corpus;

const FORBIDDEN_TAGS = new Set(["script", "style", "iframe", "frame", "frameset", "object", "embed", "applet", "svg", "math", "form", "input", "button", "select", "textarea",
  "link", "meta", "base", "template", "noscript", "audio", "video", "source", "track", "picture", "canvas", "image", "details", "dialog", "slot"]);
const RESOURCE_ATTRIBUTES = ["src", "srcset", "poster", "action", "formaction", "background", "data", "ping", "xlink:href", "codebase", "manifest", "cite", "longdesc", "usemap", "icon"];
const IMAGE_DATA = /^data:image\/(png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]*$/;
const STYLE_FORBIDDEN = /url\(|expression|@|\\|\/\*|var\(|--|behavior|binding|position|z-index|transform|filter|opacity|cursor|pointer-events|content/i;
const POKED = 400;
const EVENTS = ["click", "dblclick", "mousedown", "mouseup", "mouseover", "mouseenter", "mouseleave", "pointerdown", "pointerover", "focus", "focusin", "blur", "load", "error", "toggle",
  "animationstart", "animationend", "transitionend", "input", "change", "submit", "keydown", "keyup", "touchstart", "wheel", "scroll", "begin"];

export type Network = { calls: () => string[]; restore: () => void };

export function watchNetwork(): Network {
  const seen: string[] = [];
  const spies = [
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => { seen.push(`fetch ${String(input)}`); return new Response(""); }),
    vi.spyOn(XMLHttpRequest.prototype, "open").mockImplementation(function (this: XMLHttpRequest, method: string, url: string | URL) { seen.push(`xhr ${method} ${String(url)}`); }),
    vi.spyOn(XMLHttpRequest.prototype, "send").mockImplementation(() => { seen.push("xhr send"); }),
    vi.spyOn(window, "open").mockImplementation((url) => { seen.push(`open ${String(url)}`); return null; }),
  ];
  const beacon = vi.fn((url: string) => { seen.push(`beacon ${url}`); return true; });
  Object.defineProperty(navigator, "sendBeacon", { value: beacon, configurable: true });
  const sockets = vi.fn(function (url: string) { seen.push(`websocket ${url}`); });
  vi.stubGlobal("WebSocket", sockets);
  return { calls: () => [...seen], restore: () => { spies.forEach((s) => s.mockRestore()); vi.unstubAllGlobals(); } };
}

export function executed(): string[] {
  const found = new Set<string>();
  const windows: object[] = [window, globalThis];
  const jsdom = (globalThis as { jsdom?: { window: object } }).jsdom;
  if (jsdom) windows.push(jsdom.window);
  for (const w of windows) for (const key of Object.getOwnPropertyNames(w)) if (key.startsWith("CANARY_")) found.add(key);
  return [...found];
}

export function clearExecuted() {
  const windows: object[] = [window, globalThis];
  const jsdom = (globalThis as { jsdom?: { window: object } }).jsdom;
  if (jsdom) windows.push(jsdom.window);
  for (const w of windows) for (const key of Object.getOwnPropertyNames(w)) if (key.startsWith("CANARY_")) Reflect.deleteProperty(w, key);
}

export function poke(root: ParentNode) {
  const targets = Array.from(root.querySelectorAll("*")).filter((e) => e.attributes.length > 0 || e.localName === "script").slice(0, POKED);
  for (const element of targets) {
    for (const type of EVENTS) element.dispatchEvent(new Event(type, { bubbles: false, cancelable: true }));
    if (element instanceof HTMLElement) { element.focus(); }
  }
}

export function violations(root: ParentNode): string[] {
  const found: string[] = [];
  for (const element of root.querySelectorAll("*")) {
    const tag = element.localName;
    if (FORBIDDEN_TAGS.has(tag)) found.push(`element ${tag}`);
    if (element.namespaceURI !== "http://www.w3.org/1999/xhtml") found.push(`namespace ${element.namespaceURI}`);
    for (const { name, value } of Array.from(element.attributes)) {
      if (/^on/i.test(name)) found.push(`handler ${name}`);
      if (RESOURCE_ATTRIBUTES.includes(name) && !(tag === "img" && name === "src" && IMAGE_DATA.test(value))) found.push(`address ${name}=${value.slice(0, 40)}`);
      if (["id", "name", "class", "slot", "is", "contenteditable", "draggable", "tabindex", "autofocus", "popover"].includes(name)) found.push(`attribute ${name}`);
      if (name === "href" && !(tag === "a" && /^(https:|mailto:)/i.test(value))) found.push(`link ${value.slice(0, 40)}`);
      if (name === "style" && STYLE_FORBIDDEN.test(value)) found.push(`style ${value.slice(0, 60)}`);
    }
    if (tag === "a" && element.hasAttribute("href") && (element.getAttribute("target") !== "_blank" || element.getAttribute("rel") !== "noopener noreferrer")) found.push("link keeps the opener or the app");
  }
  return found;
}

export function outside(): string {
  return `${document.head.innerHTML}|${Array.from(document.body.children).filter((e) => !e.hasAttribute("data-email-host")).map((e) => e.outerHTML).join("")}`;
}

export type Naive = { name: string; render: (into: ShadowRoot, html: string) => void };

export const naiveRenderers: Naive[] = [
  { name: "innerHTML", render: (into, html) => { const box = document.createElement("div"); box.innerHTML = html; into.append(box); } },
  { name: "insertAdjacentHTML", render: (into, html) => { const box = document.createElement("div"); into.append(box); box.insertAdjacentHTML("beforeend", html); } },
  { name: "parsed document moved in", render: (into, html) => { const doc = new DOMParser().parseFromString(html, "text/html"); const box = document.createElement("div"); box.append(...Array.from(doc.body.childNodes).map((n) => document.importNode(n, true))); into.append(box); } },
  { name: "fragment with scripts revived", render: (into, html) => {
    const box = document.createElement("div");
    box.innerHTML = html;
    for (const old of Array.from(box.querySelectorAll("script"))) { const fresh = document.createElement("script"); fresh.textContent = old.textContent; old.replaceWith(fresh); }
    into.append(box);
  } },
];
