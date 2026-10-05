import { beforeEach, describe, expect, it, vi } from "vitest";

const error = vi.hoisted(() => vi.fn());
vi.mock("svelte-sonner", () => ({ toast: { error } }));

import { act, actGet, errMsg } from "./act";

beforeEach(() => error.mockReset());

describe("errMsg", () => {
  it("is the message of an error, or of anything shaped like one", () => {
    expect(errMsg(new Error("Nope"))).toBe("Nope");
    expect(errMsg({ message: "Refused" })).toBe("Refused");
  });
  it("copes with what isn't an error", () => {
    expect(errMsg("plain")).toBe("plain");
    expect(errMsg(null)).toBe("null");
    expect(errMsg(undefined)).toBe("undefined");
  });
});

describe("act", () => {
  it("resolves to true when it worked, and says nothing", async () => {
    const fn = vi.fn().mockResolvedValue(undefined);
    expect(await act(fn)).toBe(true);
    expect(fn).toHaveBeenCalledOnce();
    expect(error).not.toHaveBeenCalled();
  });

  it("toasts the message and resolves to false when it fails, without rejecting", async () => {
    expect(await act(async () => { throw new Error("The server said no"); })).toBe(false);
    expect(error).toHaveBeenCalledExactlyOnceWith("The server said no");
  });

  it("catches a throw from a function that isn't async", async () => {
    expect(await act(() => { throw new Error("Sync trouble"); })).toBe(false);
    expect(error).toHaveBeenCalledWith("Sync trouble");
  });

  it("holds busy for the length of the action, success or failure", async () => {
    const seen: boolean[] = [];
    let release!: () => void;
    const done = act(() => new Promise<void>((r) => { release = r; }), { busy: (on) => seen.push(on) });
    expect(seen).toEqual([true]);
    release();
    await done;
    expect(seen).toEqual([true, false]);
    seen.length = 0;
    await act(async () => { throw new Error("x"); }, { busy: (on) => seen.push(on) });
    expect(seen).toEqual([true, false]);
  });

  it("hands a failure to onError instead of a toast", async () => {
    const onError = vi.fn(), boom = new Error("Refused");
    expect(await act(async () => { throw boom; }, { onError })).toBe(false);
    expect(onError).toHaveBeenCalledWith("Refused", boom);
    expect(error).not.toHaveBeenCalled();
  });
});

describe("actGet", () => {
  it("resolves to what the action returned", async () => {
    expect(await actGet(async () => ({ id: 3 }))).toEqual({ id: 3 });
  });
  it("resolves to null, with a toast, when it fails", async () => {
    expect(await actGet(async () => { throw new Error("Gone"); })).toBeNull();
    expect(error).toHaveBeenCalledWith("Gone");
  });
});
