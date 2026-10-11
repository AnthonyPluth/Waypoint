// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { clearExecuted, executed, naiveRenderers, outside, payloads, poke, violations, watchNetwork, type Network } from "./hostile";

const SIZES = /deeply|stray|huge|thousands/;
let network: Network;
let host: HTMLElement;
let shadow: ShadowRoot;

beforeEach(() => {
  clearExecuted();
  network = watchNetwork();
  host = document.createElement("div");
  host.setAttribute("data-email-host", "");
  document.body.append(host);
  shadow = host.attachShadow({ mode: "open" });
});

afterEach(() => {
  network.restore();
  host.remove();
  clearExecuted();
});

function flagged(render: (into: ShadowRoot, html: string) => void, html: string): string[] {
  const before = outside();
  try { render(shadow, html); } catch (e) { return [`threw ${String(e)}`]; }
  poke(shadow);
  return [...violations(shadow), ...executed().map((c) => `executed ${c}`), ...network.calls(), ...(outside() === before ? [] : ["changed the page"])];
}

describe("the hostile corpus", () => {
  it("is large and covers each kind of payload", () => {
    expect(payloads.length).toBeGreaterThan(60);
    expect(new Set(payloads.map((p) => p.name)).size).toBe(payloads.length);
    for (const p of payloads) expect(p.canary.length, p.name).toBeGreaterThan(0);
  });

  for (const naive of naiveRenderers) {
    it(`fails against a naive inline render: ${naive.name}`, () => {
      const caught: string[] = [];
      const missed: string[] = [];
      const small = payloads.filter((p) => !SIZES.test(p.name));
      for (const p of small) {
        host.replaceChildren();
        shadow.replaceChildren();
        clearExecuted();
        const found = flagged(naive.render, p.html);
        (found.length ? caught : missed).push(p.name);
      }
      expect(caught.length).toBeGreaterThanOrEqual(small.length * 0.7);
      expect(caught).toEqual(expect.arrayContaining([
        "script tag", "click handler", "img onerror", "javascript link", "background url", "nested forms", "remote pixel",
      ]));
    });
  }

  it("shows a naive render really runs a handler and a revived script, so a canary that never fires means something", () => {
    shadow.innerHTML = '<p onclick="window.CANARY_proof=1">x</p>';
    poke(shadow);
    expect(executed()).toContain("CANARY_proof");
    clearExecuted();
    const revived = naiveRenderers[3];
    revived.render(shadow, "<script>window.CANARY_revived=1</script>");
    expect(executed()).toContain("CANARY_revived");
  });
});
