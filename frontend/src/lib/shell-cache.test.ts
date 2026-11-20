import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import { loadedAssetPaths, registerShellCache, type Scope } from "./shell-cache";

const ORIGIN = "https://trips.example.test";
const SOURCE = readFileSync(new URL("../../../waypoint/static/sw.js", import.meta.url), "utf8");

type Handler = (event: unknown) => void;

function startWorker(cached: Record<string, Response> = {}, fetcher: (url: string) => Promise<Response> = async () => new Response("body")) {
  const handlers: Record<string, Handler> = {};
  const store = new Map<string, Response>(Object.entries(cached));
  const cache = {
    match: async (key: string) => store.get(key),
    put: async (key: string, res: Response) => { store.set(key, res); },
    addAll: async () => {},
  };
  const scope = {
    addEventListener: (name: string, fn: Handler) => { handlers[name] = fn; },
    skipWaiting: () => {},
    clients: { claim: async () => {} },
  };
  const workerStorage = { open: async () => cache, keys: async () => [], match: async (key: string) => store.get(key), delete: async () => true };
  const fetched: string[] = [];
  const fetchStub = async (target: string) => { fetched.push(target); return fetcher(target); };
  new Function("self", "caches", "location", "fetch", "URL", "Set", SOURCE)(scope, workerStorage, { origin: ORIGIN }, fetchStub, URL, Set);
  const send = async (data: unknown) => {
    const waits: Promise<unknown>[] = [];
    handlers.message({ data, waitUntil: (p: Promise<unknown>) => waits.push(p) });
    await Promise.all(waits);
  };
  return { send, store, fetched };
}

describe("loadedAssetPaths", () => {
  it("keeps this origin's built files, once each, and nothing else", () => {
    const names = [`${ORIGIN}/assets/index-abc.js`, `${ORIGIN}/assets/index-abc.js`, `${ORIGIN}/assets/index-abc.css`, `${ORIGIN}/api/trips`,
      `${ORIGIN}/fonts/Inter-Variable.woff2`, "https://elsewhere.example.test/assets/x.js", "not a url"];
    expect(loadedAssetPaths(names.map((name) => ({ name })), ORIGIN)).toEqual(["/assets/index-abc.js", "/assets/index-abc.css"]);
  });
});

class FakeObserver {
  static entries: { name: string }[] = [];
  constructor(private callback: (list: { getEntries: () => { name: string }[] }) => void) {}
  observe() { queueMicrotask(() => this.callback({ getEntries: () => FakeObserver.entries })); }
  disconnect() {}
}

const pageWith = (entries: { name: string }[], observer: Scope["PerformanceObserver"] = FakeObserver): Scope => {
  FakeObserver.entries = entries;
  return { location: { origin: ORIGIN }, PerformanceObserver: observer };
};

describe("registerShellCache", () => {
  it("hands the service worker what the page loaded, once it is ready and again when it takes control", async () => {
    const postMessage = vi.fn();
    const listeners: Record<string, () => void> = {};
    const container = {
      ready: Promise.resolve({ active: { postMessage } }),
      register: vi.fn(async () => ({})),
      addEventListener: (name: string, fn: () => void) => { listeners[name] = fn; },
    } as unknown as ServiceWorkerContainer;
    registerShellCache(container, pageWith([{ name: `${ORIGIN}/assets/index-abc.js` }, { name: `${ORIGIN}/api/state` }]));
    await vi.waitFor(() => expect(postMessage).toHaveBeenCalledTimes(1));
    expect(container.register).toHaveBeenCalledWith("/sw.js");
    expect(postMessage).toHaveBeenCalledWith({ type: "keep-loaded", paths: ["/assets/index-abc.js"] });
    listeners.controllerchange();
    await vi.waitFor(() => expect(postMessage).toHaveBeenCalledTimes(2));
  });

  it("sends an empty list when the browser has no resource timing, or reports nothing in time", async () => {
    vi.useFakeTimers();
    try {
      const postMessage = vi.fn();
      const container = { ready: Promise.resolve({ active: { postMessage } }), register: async () => ({}), addEventListener: () => {} } as unknown as ServiceWorkerContainer;
      registerShellCache(container, { location: { origin: ORIGIN } });
      await vi.advanceTimersByTimeAsync(0);
      expect(postMessage).toHaveBeenLastCalledWith({ type: "keep-loaded", paths: [] });
      class Silent { observe() {} disconnect() {} }
      registerShellCache(container, pageWith([], Silent));
      await vi.advanceTimersByTimeAsync(1500);
      expect(postMessage).toHaveBeenCalledTimes(2);
    } finally { vi.useRealTimers(); }
  });

  it("does nothing when no worker is active yet", async () => {
    const container = { ready: Promise.resolve({ active: null }), register: async () => ({}), addEventListener: () => {} } as unknown as ServiceWorkerContainer;
    registerShellCache(container, pageWith([]));
    await Promise.resolve();
  });

  it("warns and carries on when the worker can't register", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const container = { ready: new Promise(() => {}), register: async () => { throw new Error("blocked"); }, addEventListener: () => {} } as unknown as ServiceWorkerContainer;
    registerShellCache(container, pageWith([]));
    await vi.waitFor(() => expect(warn).toHaveBeenCalled());
    warn.mockRestore();
  });
});

describe("sw.js keep-loaded", () => {
  it("caches the built files the page loaded before the worker controlled it, so an offline reload can start the app", async () => {
    const worker = startWorker();
    await worker.send({ type: "keep-loaded", paths: ["/assets/index-abc.js", "/assets/index-abc.css", "/assets/index-abc.js"] });
    expect([...worker.store.keys()].sort()).toEqual(["/assets/index-abc.css", "/assets/index-abc.js"]);
    expect(worker.fetched).toEqual(["/assets/index-abc.js", "/assets/index-abc.css"]);
  });

  it("skips what is cached and refuses anything that isn't a built file of this origin", async () => {
    const worker = startWorker({ "/assets/have.js": new Response("kept") });
    await worker.send({ type: "keep-loaded", paths: ["/assets/have.js", "/api/trips", "/auth/session", "https://elsewhere.example.test/assets/x.js", 42, "/assets/new.js"] });
    expect(worker.fetched).toEqual(["/assets/new.js"]);
    expect(await (worker.store.get("/assets/have.js") as Response).text()).toBe("kept");
  });

  it("keeps nothing from a failed, missing or redirected answer, and ignores other messages", async () => {
    const answers: Record<string, () => Promise<Response>> = {
      "/assets/down.js": async () => { throw new TypeError("offline"); },
      "/assets/gone.js": async () => new Response("no", { status: 404 }),
      "/assets/moved.js": async () => Object.defineProperty(new Response("x"), "redirected", { value: true }),
      "/assets/fine.js": async () => new Response("ok"),
    };
    const worker = startWorker({}, (url) => answers[url]());
    await worker.send({ type: "something-else", paths: ["/assets/fine.js"] });
    await worker.send({ type: "keep-loaded", paths: "/assets/fine.js" });
    expect(worker.fetched).toEqual([]);
    await worker.send({ type: "keep-loaded", paths: ["/assets/down.js", "/assets/gone.js", "/assets/moved.js", "/assets/fine.js"] });
    expect([...worker.store.keys()]).toEqual(["/assets/fine.js"]);
  });
});
