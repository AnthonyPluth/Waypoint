import { describe, expect, it } from "vitest";
import { limited } from "./limit";

const gate = () => {
  let open: () => void = () => {};
  const done = new Promise<void>((r) => { open = r; });
  return { done, open };
};

describe("limited", () => {
  it("runs no more than the limit at once and the rest as slots free", async () => {
    const run = limited(2);
    let running = 0, peak = 0;
    const gates = [gate(), gate(), gate(), gate()];
    const results = gates.map((g, i) => run(async () => { running++; peak = Math.max(peak, running); await g.done; running--; return i; }));
    await Promise.resolve();
    expect(running).toBe(2);
    gates.forEach((g) => g.open());
    expect(await Promise.all(results)).toEqual([0, 1, 2, 3]);
    expect(peak).toBe(2);
  });

  it("skips a queued task that has gone stale, and frees its slot", async () => {
    const run = limited(1);
    const first = gate();
    let ran = false;
    const a = run(async () => { await first.done; return "a"; });
    const b = run(async () => { ran = true; return "b"; }, () => true);
    const c = run(async () => "c");
    first.open();
    expect(await Promise.all([a, b, c])).toEqual(["a", undefined, "c"]);
    expect(ran).toBe(false);
  });

  it("frees the slot when a task fails", async () => {
    const run = limited(1);
    await expect(run(async () => { throw new Error("down"); })).rejects.toThrow("down");
    expect(await run(async () => "next")).toBe("next");
  });
});
