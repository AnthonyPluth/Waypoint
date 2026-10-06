import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";

function media(initial: boolean) {
  const listeners: ((e: { matches: boolean }) => void)[] = [];
  const mq = { matches: initial, addEventListener: (_: string, fn: (e: { matches: boolean }) => void) => listeners.push(fn) };
  const matchMedia = vi.fn(() => mq);
  vi.stubGlobal("matchMedia", matchMedia);
  return { matchMedia, fire: (matches: boolean) => { mq.matches = matches; listeners.forEach((fn) => fn({ matches })); } };
}
const load = async () => { vi.resetModules(); return import("./phone.svelte"); };

afterEach(() => { vi.unstubAllGlobals(); });

describe("isPhone", () => {
  it("asks the browser the one phone query, once", async () => {
    const m = media(false);
    const { PHONE_QUERY } = await load();
    expect(m.matchMedia).toHaveBeenCalledExactlyOnceWith(PHONE_QUERY);
  });

  it("counts a narrow screen and a short touch screen (a phone turned sideways), and nothing else", async () => {
    const { PHONE_QUERY } = await load();
    expect(PHONE_QUERY).toBe("(max-width: 767px), (max-height: 500px) and (pointer: coarse)");
  });

  it("starts as the query says", async () => {
    media(true);
    expect((await load()).isPhone()).toBe(true);
    media(false);
    expect((await load()).isPhone()).toBe(false);
  });

  it("follows the screen when it changes (rotating, resizing)", async () => {
    const m = media(false);
    const { isPhone } = await load();
    m.fire(true);
    expect(isPhone()).toBe(true);
    m.fire(false);
    expect(isPhone()).toBe(false);
  });

  it("is a computer where there is no matchMedia", async () => {
    vi.stubGlobal("matchMedia", undefined);
    expect((await load()).isPhone()).toBe(false);
  });

  it("is the same query the phone: and desktop: styles use", async () => {
    const { PHONE_QUERY } = await load();
    const css = readFileSync(new URL("../app.css", import.meta.url), "utf8");
    expect(css).toContain(`@custom-variant phone (@media ${PHONE_QUERY});`);
    expect(css).toContain(`@custom-variant desktop (@media not ((max-width: 767px) or ((max-height: 500px) and (pointer: coarse))));`);
  });
});
