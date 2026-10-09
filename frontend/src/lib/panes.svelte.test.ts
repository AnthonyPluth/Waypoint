import { afterEach, describe, expect, it, vi } from "vitest";

function media(initial: boolean) {
  const listeners: (() => void)[] = [];
  const mq = { matches: initial, addEventListener: (_: string, fn: () => void) => listeners.push(fn) };
  const matchMedia = vi.fn(() => mq);
  vi.stubGlobal("matchMedia", matchMedia);
  return { matchMedia, set: (matches: boolean) => { mq.matches = matches; listeners.forEach((fn) => fn()); } };
}
const load = async () => { vi.resetModules(); return import("./panes.svelte"); };

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("panes", () => {
  it("asks the browser the one query, and starts as it says", async () => {
    const m = media(true);
    const { panes, TWO_PANES_QUERY } = await load();
    expect(m.matchMedia).toHaveBeenCalledExactlyOnceWith(TWO_PANES_QUERY);
    expect(TWO_PANES_QUERY).toBe("(min-width: 1024px)");
    expect(panes.two).toBe(true);
  });

  it("follows the screen once it has settled", async () => {
    vi.useFakeTimers();
    const m = media(false);
    const { panes, SETTLE_MS } = await load();
    m.set(true);
    expect(panes.two).toBe(false);
    vi.advanceTimersByTime(SETTLE_MS);
    expect(panes.two).toBe(true);
  });

  it("ignores a change that flips back at once, so the open trip isn’t rebuilt", async () => {
    vi.useFakeTimers();
    const m = media(true);
    const { panes, SETTLE_MS } = await load();
    m.set(false);
    m.set(true);
    vi.advanceTimersByTime(SETTLE_MS);
    expect(panes.two).toBe(true);
  });

  it("is a single pane where there is no matchMedia", async () => {
    vi.stubGlobal("matchMedia", undefined);
    expect((await load()).panes.two).toBe(false);
  });
});
