// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));

import { api } from "$lib/api";
import { fake, fakeMk } from "../test/fake-mapkit";
import { forgetMapkit, forgetPreload, LOAD_MS, loadMapkit, PRELOAD_MS, preloadMapkit, RETRY_MS } from "./mapkit";

const SCRIPT = "https://maps.example.test/mapkit.js";
const on = { enabled: true, token: "signed.token.value", expires: 4102444800, script: SCRIPT };
let scripts: HTMLScriptElement[] = [];

beforeEach(() => {
  forgetMapkit();
  forgetPreload();
  fake.reset();
  scripts = [];
  vi.mocked(api).mockReset();
  vi.spyOn(document.head, "append").mockImplementation((...nodes) => { scripts.push(...(nodes as HTMLScriptElement[])); });
});
afterEach(() => { delete (window as { mapkit?: unknown }).mapkit; vi.useRealTimers(); vi.restoreAllMocks(); });

const loaded = () => { (window as { mapkit?: unknown }).mapkit = fakeMk; scripts[0].onload?.(new Event("load")); };
const flush = () => new Promise((r) => setTimeout(r, 0));

describe("loading MapKit", () => {
  it("asks for nothing more when the server says it is off, and remembers that", async () => {
    vi.mocked(api).mockResolvedValue({ enabled: false } as never);
    expect(await loadMapkit()).toBeNull();
    expect(await loadMapkit()).toBeNull();
    expect(api).toHaveBeenCalledTimes(1);
    expect(api).toHaveBeenCalledWith("/api/mapkit/token", { keep: true, background: true });
    expect(scripts).toHaveLength(0);
    expect(fake.inits).toHaveLength(0);
  });

  it("treats an answer it doesn't understand, or a failed request, as off, and tries again next time", async () => {
    vi.mocked(api).mockResolvedValueOnce({ stops: [] } as never).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(undefined as never);
    expect(await loadMapkit()).toBeNull();
    expect(await loadMapkit()).toBeNull();
    expect(await loadMapkit()).toBeNull();
    expect(api).toHaveBeenCalledTimes(3);
    expect(scripts).toHaveLength(0);
  });

  it("is off when the server says on but names no script", async () => {
    vi.mocked(api).mockResolvedValue({ enabled: true, token: "x" } as never);
    expect(await loadMapkit()).toBeNull();
    expect(scripts).toHaveLength(0);
  });

  it("loads the script the server named, with no credentials, and starts MapKit", async () => {
    vi.mocked(api).mockResolvedValue(on as never);
    const pending = loadMapkit();
    await flush();
    expect(scripts).toHaveLength(1);
    expect(scripts[0].src).toBe(SCRIPT);
    expect(scripts[0].crossOrigin).toBe("anonymous");
    loaded();
    const maps = await pending;
    expect(maps?.mk).toBe(fakeMk);
    expect(fake.inits).toHaveLength(1);
    expect(fake.listening("error")).toBe(1);
    expect(await loadMapkit()).toBe(maps);
    expect(scripts).toHaveLength(1);
  });

  it("gives the script the page's nonce, as Apple's policy asks, when the page has one", async () => {
    const mine = document.createElement("script");
    mine.nonce = "abc123";
    mine.setAttribute("nonce", "abc123");
    document.body.append(mine);
    vi.mocked(api).mockResolvedValue(on as never);
    const pending = loadMapkit();
    await flush();
    expect(scripts[0].nonce).toBe("abc123");
    scripts[0].onerror?.(new Event("error"));
    await pending;
    mine.remove();
  });

  it("sets no nonce when the page has none", async () => {
    vi.mocked(api).mockResolvedValue(on as never);
    const pending = loadMapkit();
    await flush();
    expect(scripts[0].nonce).toBe("");
    scripts[0].onerror?.(new Event("error"));
    await pending;
  });

  it("hands MapKit a fresh token each time it asks", async () => {
    vi.mocked(api).mockResolvedValue(on as never);
    const pending = loadMapkit();
    await flush();
    loaded();
    await pending;
    vi.mocked(api).mockResolvedValue({ ...on, token: "second.token.value" } as never);
    const done = vi.fn();
    fake.inits[0].authorizationCallback(done);
    await flush();
    expect(done).toHaveBeenCalledWith("second.token.value");
  });

  it("tells the page when a token can't be had, or MapKit reports an error", async () => {
    vi.mocked(api).mockResolvedValue(on as never);
    const pending = loadMapkit();
    await flush();
    loaded();
    const maps = (await pending)!;
    const failed = vi.fn();
    const stop = maps.onFailure(failed);
    const done = vi.fn();
    vi.mocked(api).mockResolvedValueOnce({ enabled: false } as never);
    fake.inits[0].authorizationCallback(done);
    await flush();
    vi.mocked(api).mockRejectedValueOnce(new Error("offline"));
    fake.inits[0].authorizationCallback(done);
    await flush();
    fake.emit("error", { status: "Too Many Requests" });
    expect(done).not.toHaveBeenCalled();
    expect(failed).toHaveBeenCalledTimes(3);
    stop();
    fake.emit("error");
    expect(failed).toHaveBeenCalledTimes(3);
  });

  it("gives up when the script fails to load, and tries again next time", async () => {
    vi.mocked(api).mockResolvedValue(on as never);
    const pending = loadMapkit();
    await flush();
    scripts[0].onerror?.(new Event("error"));
    expect(await pending).toBeNull();
    expect(fake.inits).toHaveLength(0);
    const again = loadMapkit();
    await flush();
    expect(scripts).toHaveLength(2);
    scripts[1].onerror?.(new Event("error"));
    expect(await again).toBeNull();
  });

  it("gives up when the script never answers", async () => {
    vi.mocked(api).mockResolvedValue(on as never);
    vi.useFakeTimers();
    const pending = loadMapkit();
    await vi.advanceTimersByTimeAsync(LOAD_MS - 1);
    let settled = false;
    void pending.then(() => { settled = true; });
    await vi.advanceTimersByTimeAsync(0);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(2);
    expect(await pending).toBeNull();
  });

  it("gives up when the script loaded but defined nothing", async () => {
    vi.mocked(api).mockResolvedValue(on as never);
    const pending = loadMapkit();
    await flush();
    scripts[0].onload?.(new Event("load"));
    expect(await pending).toBeNull();
  });

  it("gives up when MapKit won't start", async () => {
    vi.mocked(api).mockResolvedValue(on as never);
    const pending = loadMapkit();
    await flush();
    const broken = { ...fakeMk, init: () => { throw new Error("no"); } };
    (window as { mapkit?: unknown }).mapkit = broken;
    scripts[0].onload?.(new Event("load"));
    expect(await pending).toBeNull();
  });

  it("uses MapKit when the page already has it", async () => {
    vi.mocked(api).mockResolvedValue(on as never);
    (window as { mapkit?: unknown }).mapkit = fakeMk;
    expect((await loadMapkit())?.mk).toBe(fakeMk);
    expect(scripts).toHaveLength(0);
  });
});

describe("preloading MapKit", () => {
  it("asks for the token in a way that moving to another page does not cancel", async () => {
    vi.mocked(api).mockResolvedValue({ enabled: false } as never);
    await loadMapkit();
    expect(vi.mocked(api).mock.calls[0][1]).toMatchObject({ keep: true, background: true });
  });

  it("also asks for the refresh the same way, so a lapsed session shows the banner and does not redirect", async () => {
    vi.mocked(api).mockResolvedValue(on as never);
    const pending = loadMapkit();
    await flush();
    loaded();
    await pending;
    const done = vi.fn();
    fake.inits[0].authorizationCallback(done);
    await flush();
    expect(vi.mocked(api).mock.calls.at(-1)?.[1]).toMatchObject({ keep: true, background: true });
  });

  it("tells a replay that opens after MapKit already failed, at once", async () => {
    vi.mocked(api).mockResolvedValue(on as never);
    const pending = loadMapkit();
    await flush();
    loaded();
    const maps = await pending;
    fake.emit("error", { status: "Unauthorized" });
    const lost = vi.fn();
    maps?.onFailure(lost);
    await flush();
    expect(lost).toHaveBeenCalledOnce();
    const cancelled = vi.fn();
    maps?.onFailure(cancelled)();
    await flush();
    expect(cancelled).not.toHaveBeenCalled();
  });

  it("forgets a failure once a later token refresh succeeds", async () => {
    vi.mocked(api).mockResolvedValue(on as never);
    const pending = loadMapkit();
    await flush();
    loaded();
    const maps = (await pending)!;
    expect(maps.failed()).toBe(false);
    fake.emit("error", { status: "Unauthorized" });
    expect(maps.failed()).toBe(true);
    const done = vi.fn();
    fake.inits[0].authorizationCallback(done);
    await flush();
    expect(done).toHaveBeenCalledWith("signed.token.value");
    expect(maps.failed()).toBe(false);
    const lost = vi.fn();
    maps.onFailure(lost);
    await flush();
    expect(lost).not.toHaveBeenCalled();
  });

  it("keeps a failure while the token refresh itself fails", async () => {
    vi.mocked(api).mockResolvedValue(on as never);
    const pending = loadMapkit();
    await flush();
    loaded();
    const maps = (await pending)!;
    vi.mocked(api).mockRejectedValueOnce(new Error("offline"));
    fake.inits[0].authorizationCallback(vi.fn());
    await flush();
    expect(maps.failed()).toBe(true);
  });

  it("forgets a failure when MapKit reports it initialized again", async () => {
    vi.mocked(api).mockResolvedValue(on as never);
    const pending = loadMapkit();
    await flush();
    loaded();
    const maps = (await pending)!;
    fake.emit("error", { status: "Unauthorized" });
    expect(maps.failed()).toBe(true);
    fake.emit("configuration-change", { status: "Refreshed" });
    expect(maps.failed()).toBe(true);
    fake.emit("configuration-change", { status: "Initialized" });
    expect(maps.failed()).toBe(false);
  });

  it("forgets a failure after a short backoff, and not before", async () => {
    vi.mocked(api).mockResolvedValue(on as never);
    const pending = loadMapkit();
    await flush();
    loaded();
    const maps = (await pending)!;
    vi.useFakeTimers();
    fake.emit("error", { status: "Unauthorized" });
    vi.advanceTimersByTime(RETRY_MS - 1);
    expect(maps.failed()).toBe(true);
    vi.advanceTimersByTime(1);
    expect(maps.failed()).toBe(false);
  });

  it("does not strand later replays when the token request never settles, as when a page change cancelled it", async () => {
    vi.useFakeTimers();
    vi.mocked(api).mockReturnValueOnce(new Promise(() => {}) as never);
    const first = loadMapkit();
    await vi.advanceTimersByTimeAsync(LOAD_MS);
    expect(await first).toBeNull();
    vi.mocked(api).mockResolvedValue({ enabled: false } as never);
    expect(await loadMapkit()).toBeNull();
    expect(api).toHaveBeenCalledTimes(2);
  });

  it("asks once, a few seconds in, when the browser is idle, and not before", async () => {
    vi.useFakeTimers();
    const idle = vi.fn((run: () => void) => { run(); return 1; });
    vi.stubGlobal("requestIdleCallback", idle);
    vi.stubGlobal("cancelIdleCallback", vi.fn());
    vi.mocked(api).mockResolvedValue({ enabled: false } as never);
    preloadMapkit();
    await vi.advanceTimersByTimeAsync(PRELOAD_MS - 1);
    expect(api).not.toHaveBeenCalled();
    expect(idle).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(idle).toHaveBeenCalledOnce();
    expect(api).toHaveBeenCalledOnce();
    preloadMapkit();
    await vi.advanceTimersByTimeAsync(PRELOAD_MS);
    expect(api).toHaveBeenCalledOnce();
    vi.unstubAllGlobals();
  });

  it("falls back to a timer when the browser has no idle callback, and a failure is not retried", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("requestIdleCallback", undefined);
    vi.mocked(api).mockRejectedValue(new Error("offline"));
    preloadMapkit();
    await vi.advanceTimersByTimeAsync(PRELOAD_MS * 5);
    expect(api).toHaveBeenCalledOnce();
    expect(scripts).toHaveLength(0);
    vi.unstubAllGlobals();
  });

  it("does nothing when it is cancelled first", async () => {
    vi.useFakeTimers();
    vi.mocked(api).mockResolvedValue(on as never);
    preloadMapkit()();
    await vi.advanceTimersByTimeAsync(PRELOAD_MS * 5);
    expect(api).not.toHaveBeenCalled();
    expect(scripts).toHaveLength(0);
  });
});
