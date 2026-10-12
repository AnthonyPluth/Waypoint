const HTML_NAMESPACE = "http://www.w3.org/1999/xhtml";
const MAX_DEPTH = 40;
const MAX_NODES = 60_000;
const MAX_TEXT = 1_000_000;
const MAX_STYLE = 200;
const MAX_TITLE = 300;
const IMAGE_DATA = /^data:image\/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]*$/;
const PICTURE_INDEX = /^\d{1,3}$/;

const TAGS = new Set(["p", "div", "span", "br", "hr", "b", "strong", "i", "em", "u", "s", "small", "sub", "sup", "blockquote", "pre", "code",
  "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "dl", "dt", "dd", "table", "thead", "tbody", "tfoot", "tr", "td", "th",
  "caption", "a", "center", "font", "section", "article", "header", "footer", "main", "aside", "figure", "figcaption",
  "address", "colgroup", "col", "img"]);
const VOID = new Set(["br", "hr", "img"]);
const DROPPED = new Set(["script", "style", "head", "title", "template", "noscript", "iframe", "frame", "frameset", "object", "embed", "applet", "svg", "math", "select",
  "textarea", "button", "audio", "video", "canvas", "input", "link", "meta", "base", "form", "details", "dialog", "slot"]);

const SIDES = ["top", "right", "bottom", "left"];
const PROPERTIES = new Set([
  "color", "background-color", "border-color", "text-align", "vertical-align", "font-weight", "font-style", "text-decoration", "text-transform", "white-space",
  "border-collapse", "display", "word-break", "list-style-type", "border-style", "font-size", "font-family", "width", "height", "max-width", "min-width", "min-height",
  "max-height", "line-height", "letter-spacing", "text-indent", "border-width", "border-radius", "border-spacing", "padding", "margin", "border",
  ...SIDES.flatMap((side) => [`border-${side}-color`, `border-${side}-width`, `padding-${side}`, `margin-${side}`, `border-${side}`]),
]);
const LENGTH = "(?:\\d{1,4}(?:\\.\\d{1,3})?(?:px|em|rem|pt|ex|ch|%)?|auto)";
const LENGTHS = new RegExp(`^${LENGTH}(?:\\s+${LENGTH}){0,3}$`);
const LENGTH_PROPERTIES = new Set(["width", "height", "max-width", "min-width", "min-height", "max-height", "font-size", "line-height", "letter-spacing", "text-indent",
  "border-width", "border-radius", "border-spacing", "padding", "margin", ...SIDES.flatMap((side) => [`padding-${side}`, `margin-${side}`, `border-${side}-width`])]);
const DISPLAYS = new Set(["none", "block", "inline", "inline-block", "table", "table-row", "table-cell"]);
const STYLE_VALUE = /^[A-Za-z0-9\s#%.,'"()/-]+$/;
const STYLE_FORBIDDEN = /url|expression|image|var\(|attr\(|env\(|javascript|binding|behavior|import|src\(|element\(|paint\(/i;

const ALIGN = new Set(["left", "right", "center", "justify"]);
const VALIGN = new Set(["top", "middle", "bottom", "baseline"]);
const SPAN = /^[1-9]\d?$/;
const SIZE = /^\d{1,4}%?$/;
const COUNT = /^\d{1,3}$/;
const ALIGNED = new Set(["table", "td", "th", "tr", "tbody", "thead", "tfoot", "div", "p", "center", "caption", "h1", "h2", "h3", "h4", "h5", "h6"]);
const VALIGNED = new Set(["td", "th", "tr", "tbody", "thead", "tfoot"]);
const WIDE = new Set(["table", "td", "th", "col", "colgroup"]);
const TALL = new Set(["table", "td", "th", "tr"]);

export function safeStyle(value: string | null): string {
  const kept: string[] = [];
  for (const declaration of (value ?? "").slice(0, 4000).split(";")) {
    const colon = declaration.indexOf(":");
    if (colon < 0) continue;
    const name = declaration.slice(0, colon).trim().toLowerCase();
    const text = declaration.slice(colon + 1).trim();
    if (!PROPERTIES.has(name) || !text || text.length > MAX_STYLE || !STYLE_VALUE.test(text) || STYLE_FORBIDDEN.test(text)) continue;
    if (LENGTH_PROPERTIES.has(name) && !LENGTHS.test(text.toLowerCase())) continue;
    if (name === "display" && !DISPLAYS.has(text.toLowerCase())) continue;
    kept.push(`${name}:${text}`);
  }
  return kept.join(";");
}

export function safeHref(value: string | null): string | null {
  const href = Array.from(value ?? "").filter((c) => { const code = c.charCodeAt(0); return code > 32 && (code < 127 || code > 159); }).join("");
  let parts: URL;
  try { parts = new URL(href); } catch { return null; }
  if (parts.protocol === "https:") return parts.host ? href : null;
  return parts.protocol === "mailto:" ? href : null;
}

function copyAttributes(from: Element, into: HTMLElement, tag: string) {
  const get = (name: string) => (from.getAttribute(name) ?? "").trim();
  const word = (name: string, allowed: Set<string>) => { const value = get(name).toLowerCase(); if (allowed.has(value)) into.setAttribute(name, value); };
  const matching = (name: string, pattern: RegExp) => { const value = get(name).replace(/px$/, ""); if (pattern.test(value)) into.setAttribute(name, value); };
  if (tag === "a") {
    const href = safeHref(from.getAttribute("href"));
    if (href) {
      into.setAttribute("href", href);
      into.setAttribute("target", "_blank");
      into.setAttribute("rel", "noopener noreferrer");
      into.setAttribute("title", href.slice(0, MAX_TITLE));
    }
  }
  if (tag === "img") {
    if (PICTURE_INDEX.test(get("data-i"))) into.setAttribute("data-i", get("data-i"));
    into.setAttribute("alt", get("alt").slice(0, MAX_TITLE));
    matching("width", SIZE);
    matching("height", SIZE);
  }
  if (ALIGNED.has(tag)) word("align", ALIGN);
  if (VALIGNED.has(tag)) word("valign", VALIGN);
  if (tag === "td" || tag === "th") { matching("colspan", SPAN); matching("rowspan", SPAN); }
  if (WIDE.has(tag)) matching("width", SIZE);
  if (TALL.has(tag)) matching("height", SIZE);
  if (tag === "table") { matching("border", COUNT); matching("cellpadding", COUNT); matching("cellspacing", COUNT); }
  const style = safeStyle(from.getAttribute("style"));
  if (style) into.setAttribute("style", style);
}

type Pending = { source: Node; target: Node; depth: number };

export function buildEmail(markup: string): DocumentFragment {
  const fragment = document.createDocumentFragment();
  const parsed = new DOMParser().parseFromString(`<!doctype html><html><body>${markup}</body></html>`, "text/html");
  const stack: Pending[] = [{ source: parsed.body, target: fragment, depth: 0 }];
  let nodes = 0;
  let text = 0;
  while (stack.length) {
    const { source, target, depth } = stack.pop() as Pending;
    let inner = target;
    let innerDepth = depth;
    if (source.nodeType === Node.TEXT_NODE) {
      const data = (source.textContent ?? "").slice(0, Math.max(MAX_TEXT - text, 0));
      text += data.length;
      if (data && nodes++ < MAX_NODES) target.appendChild(document.createTextNode(data));
      continue;
    }
    if (source.nodeType !== Node.ELEMENT_NODE) continue;
    const element = source as Element;
    const tag = element.localName;
    if (element.namespaceURI !== HTML_NAMESPACE || DROPPED.has(tag)) continue;
    if (TAGS.has(tag) && depth < MAX_DEPTH && nodes < MAX_NODES) {
      nodes++;
      const made = document.createElement(tag);
      copyAttributes(element, made, tag);
      target.appendChild(made);
      if (VOID.has(tag)) continue;
      inner = made;
      innerDepth = depth + 1;
    }
    const children = element.childNodes;
    for (let i = children.length - 1; i >= 0; i--) stack.push({ source: children[i], target: inner, depth: innerDepth });
  }
  return fragment;
}

export function showPictures(root: ParentNode, pictures: Record<number, string>) {
  for (const image of root.querySelectorAll("img[data-i]")) {
    const found = pictures[Number(image.getAttribute("data-i"))];
    if (found && IMAGE_DATA.test(found)) image.setAttribute("src", found);
    else image.removeAttribute("src");
  }
}

const SHEET = [
  ":host{all:initial;display:block;color-scheme:light}",
  ".email{box-sizing:border-box;width:100%;min-width:min-content;padding:12px;background:#ffffff;color:#1f1f1f;font:14px/1.5 system-ui,-apple-system,'Segoe UI',sans-serif;"
    + "text-align:left;direction:ltr;letter-spacing:normal;word-spacing:normal;text-transform:none;text-indent:0;white-space:normal;visibility:visible;cursor:auto;overflow-wrap:anywhere}",
  ".legacy{line-height:1.6}",
  ".email img{max-width:100%;height:auto;border:0}",
  ".email a{color:#0b57d0}",
  ".legacy blockquote{border-left:2px solid #747775;margin:8px 0;padding-left:12px}",
  ".legacy td,.legacy th{padding:4px;vertical-align:top}",
  ".legacy p{margin:8px 0}",
].join("");

export function attachEmail(host: HTMLElement): ShadowRoot {
  const root = host.shadowRoot ?? host.attachShadow({ mode: "open" });
  root.addEventListener("click", (event) => {
    const link = event.composedPath().find((n) => n instanceof HTMLAnchorElement);
    if (link) event.stopPropagation();
  });
  return root;
}

export function renderEmail(root: ShadowRoot, markup: string, pictures: Record<number, string>, legacy: boolean) {
  const sheet = document.createElement("style");
  sheet.textContent = SHEET;
  const wrapper = document.createElement("div");
  wrapper.className = legacy ? "email legacy" : "email";
  wrapper.append(buildEmail(markup));
  showPictures(wrapper, pictures);
  root.replaceChildren(sheet, wrapper);
}
