// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearExecuted, executed, outside, payloads, poke, violations, watchNetwork, type Network } from "../test/hostile";
import { attachEmail, buildEmail, renderEmail, safeHref, safeStyle, showPictures } from "./email-render";

let network: Network;
let host: HTMLElement;
let root: ShadowRoot;

beforeEach(() => {
  clearExecuted();
  network = watchNetwork();
  host = document.createElement("div");
  host.setAttribute("data-email-host", "");
  document.body.append(host);
  root = attachEmail(host);
});

afterEach(() => {
  network.restore();
  host.remove();
  clearExecuted();
});

const wrapperOf = () => root.querySelector(".email") as HTMLElement;
const PICTURE = "data:image/png;base64,AAAA";

function renderChecked(markup: string, pictures: Record<number, string> = {}) {
  const before = outside();
  renderEmail(root, markup, pictures, false);
  poke(root);
  return {
    violations: violations(wrapperOf()),
    executed: executed(),
    network: network.calls(),
    changedPage: outside() !== before,
  };
}

describe("the hostile corpus through the inline renderer", () => {
  for (const found of payloads) {
    for (const [label, markup] of [["raw", found.html], ["cleaned", found.cleaned], ["cleaned with pictures", found.cleanedWithPictures]] as const) {
      it(`${found.name} comes out inert (${label})`, () => {
        const result = renderChecked(markup, { 0: PICTURE });
        expect(result.violations).toEqual([]);
        expect(result.executed).toEqual([]);
        expect(result.network).toEqual([]);
        expect(result.changedPage).toBe(false);
        expect(root.querySelectorAll("style")).toHaveLength(1);
        if (label !== "raw" && !found.canary.startsWith("<img")) expect(wrapperOf().innerHTML).not.toContain(found.canary);
      }, 30_000);
    }
  }

  it("keeps a hostile document bounded: nesting, nodes and the page around it", () => {
    const deep = payloads.find((p) => p.name === "deeply nested divs");
    renderEmail(root, deep?.html ?? "", {}, false);
    let depth = 0;
    for (let node: Element | null = wrapperOf().querySelector("div"); node; node = node.querySelector(":scope > div")) depth++;
    expect(depth).toBeLessThanOrEqual(41);
    expect(wrapperOf().textContent).toContain("deep");
  });
});

describe("what the renderer builds", () => {
  it("rebuilds only allowed elements and attributes, from the cleaner’s output", () => {
    const into = buildEmail('<table width="600" border="1" cellpadding="4"><tr><td colspan="2" align="center" style="color:#112233;font-weight:bold">Gate <b>B12</b></td></tr></table>');
    const box = document.createElement("div");
    box.append(into);
    expect(box.innerHTML).toBe('<table width="600" border="1" cellpadding="4"><tbody><tr><td align="center" colspan="2" style="color:#112233;font-weight:bold">Gate <b>B12</b></td></tr></tbody></table>');
  });

  it("drops what runs or loads together with what is inside it, and unwraps unknown elements", () => {
    const box = document.createElement("div");
    box.append(buildEmail('<p>a</p><script>1</script><svg><text>t</text></svg><noscript><p>n</p></noscript><x-note onclick="1"><b>kept</b></x-note><select><option>o</option></select>'));
    expect(box.innerHTML).toBe("<p>a</p><b>kept</b>");
  });

  it("puts a picture in only from a data address of an image type, never from the markup", () => {
    renderEmail(root, '<img data-i="0" src="https://t.example/p.gif" alt="A"><img data-i="1" alt="B"><img data-i="x" alt="C"><img src="data:image/png;base64,ZZZZ" alt="D">', {
      0: PICTURE, 1: "javascript:alert(1)", 2: "https://t.example/p.gif",
    }, false);
    const images = Array.from(root.querySelectorAll("img"));
    expect(images.map((i) => i.getAttribute("src"))).toEqual([PICTURE, null, null, null]);
    expect(images.map((i) => i.getAttribute("alt"))).toEqual(["A", "B", "C", "D"]);
    showPictures(root, { 1: "data:image/svg+xml;base64,AAAA" });
    expect(images[1].hasAttribute("src")).toBe(false);
    showPictures(root, { 1: "data:image/webp;base64,AAAA" });
    expect(images[1].getAttribute("src")).toBe("data:image/webp;base64,AAAA");
  });

  it("keeps https and mailto links only, opening in a new tab without the opener", () => {
    for (const [href, kept] of [["https://example.com/a?b=1&c=2", true], ["mailto:help@example.com", true], ["HTTPS://EXAMPLE.COM", true], ["http://example.com", false],
      ["javascript:alert(1)", false], ["  JaVa\tScRiPt:alert(1)", false], ["data:text/html,x", false], ["//example.com", false], ["/relative", false], ["https:", false], ["", false], ["https://[bad", false]] as const) {
      expect(safeHref(href) !== null, href).toBe(kept);
    }
    renderEmail(root, '<a href="https://example.com" target="_self" rel="opener">x</a><a href="javascript:1">y</a>', {}, false);
    const [good, bad] = Array.from(root.querySelectorAll("a"));
    expect([good.target, good.rel]).toEqual(["_blank", "noopener noreferrer"]);
    expect(bad.hasAttribute("href")).toBe(false);
  });

  it("keeps plain presentation and nothing that loads or positions", () => {
    expect(safeStyle("color:#112233; font-size: 14px;font-family:'Segoe UI',Arial;border:1px solid #ccc;text-align:center")).toBe(
      "color:#112233;font-size:14px;font-family:'Segoe UI',Arial;border:1px solid #ccc;text-align:center");
    for (const bad of ["background:url(https://t.example/x)", "color:expression(alert(1))", "position:fixed", "z-index:9", "color:red;background-image:url(x)",
      "background-color:\\75rl(x)", "font-family:a;b", "--x:1", "behavior:url(x)", "opacity:0", "transform:scale(9)", "width:var(--x)", "color:@import"]) {
      expect(safeStyle(bad), bad).not.toMatch(/url|position|z-index|expression|--|opacity|transform|var\(|@/);
    }
    expect(safeStyle(null)).toBe("");
  });

  it("drops negative, huge and odd lengths and displays, so a style can't move or grow the email out of its box", () => {
    expect(safeStyle("margin:-9999px;margin-left:-1px;padding:-5px 2px;width:99999px;height:calc(1px);display:contents;display:flex;display:grid;text-indent:-9999px")).toBe("");
    expect(safeStyle("margin:0 auto;padding:4px 8px;width:600px;height:50%;display:block;line-height:1.5")).toBe("margin:0 auto;padding:4px 8px;width:600px;height:50%;display:block;line-height:1.5");
    renderEmail(root, '<div style="margin:-9999px;width:99999px;display:flex;color:#112233">x</div>', {}, false);
    expect(root.querySelector(".email div")?.getAttribute("style")).toBe("color:#112233");
  });

  it("stops a click on a link from reaching the page", () => {
    const reached = vi.fn();
    document.addEventListener("click", reached);
    renderEmail(root, '<p>text</p><a href="https://example.com">go</a>', {}, false);
    root.querySelector("p")?.dispatchEvent(new MouseEvent("click", { bubbles: true, composed: true }));
    expect(reached).toHaveBeenCalledTimes(1);
    root.querySelector("a")?.dispatchEvent(new MouseEvent("click", { bubbles: true, composed: true, cancelable: true }));
    expect(reached).toHaveBeenCalledTimes(1);
    document.removeEventListener("click", reached);
  });

  it("renders again over the last render, and a second attach reuses the root", () => {
    renderEmail(root, "<p>one</p>", {}, true);
    renderEmail(root, "<p>two</p>", {}, true);
    expect(root.querySelectorAll(".email")).toHaveLength(1);
    expect(wrapperOf().className).toBe("email legacy");
    expect(wrapperOf().textContent).toBe("two");
    expect(attachEmail(host)).toBe(root);
  });
});
