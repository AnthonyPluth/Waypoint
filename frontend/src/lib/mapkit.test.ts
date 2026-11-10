// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));

import { api } from "$lib/api";
import { fake, fakeMk } from "../test/fake-mapkit";
import { forgetMapkit, LOAD_MS, loadMapkit } from "./mapkit";

const SCRIPT = "https://maps.example.test/mapkit.js";
const on = { enabled: true, token: "signed.token.value", expires: 4102444800, script: SCRIPT };
let scripts: HTMLScriptElement[] = [];

beforeEach(() => {
  forgetMapkit();
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
    expect(api).toHaveBeenCalledWith("/api/mapkit/token");
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
