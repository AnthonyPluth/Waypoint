// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";

const init = vi.fn();
const addEventProcessor = vi.fn();
const setUser = vi.fn();
const form = { appendToDom: vi.fn(), open: vi.fn() };
const createForm = vi.fn(async () => form);
const named = (name: string) => vi.fn((opts?: unknown) => ({ name, opts }));
vi.mock("@sentry/browser", () => ({
  init, addEventProcessor, setUser, getFeedback: () => ({ createForm }),
  breadcrumbsIntegration: named("Breadcrumbs"), browserTracingIntegration: named("BrowserTracing"),
  browserProfilingIntegration: named("BrowserProfiling"),
  consoleLoggingIntegration: named("ConsoleLogging"), feedbackIntegration: named("Feedback"),
}));

type Integration = { name: string; opts?: Record<string, unknown> };
type Options = Record<string, unknown> & {
  dsn: string; integrations: (d: Integration[]) => Integration[];
  beforeSend: (e: Record<string, unknown>) => Record<string, unknown>;
  beforeSendSpan: (s: { name: string; attributes: Record<string, unknown> }) => { name: string; attributes: Record<string, unknown> };
  beforeSendLog: (l: { message: string; attributes?: Record<string, unknown> }) => { message: string; attributes?: Record<string, unknown> };
  beforeBreadcrumb: (c: { data?: Record<string, string> }) => { data?: Record<string, string> };
};
const cfg = { dsn: "https://k@o.ingest/1", environment: "prod", release: "1.2.3" };

async function started(config: Record<string, unknown>) {
  vi.resetModules();
  init.mockClear();
  addEventProcessor.mockClear();
  setUser.mockClear();
  const m = await import("./monitoring");
  await m.startMonitoring(config as typeof cfg);
  return { m, opts: init.mock.calls[0][0] as Options };
}

describe("startMonitoring", () => {
  it("names who's signed in by Waypoint's code for them, and no one when there isn't one", async () => {
    await started({ ...cfg, user_id: "3f2a9c1d0b7e4a65" });
    expect(setUser).toHaveBeenCalledWith({ id: "3f2a9c1d0b7e4a65" });
    await started({ ...cfg, user_id: null });
    expect(setUser).not.toHaveBeenCalled();
  });

  it("does nothing when Waypoint isn't set up for error reports", async () => {
    const { startMonitoring } = await import("./monitoring");
    await startMonitoring(null);
    await startMonitoring(undefined);
    expect(init).not.toHaveBeenCalled();
  });

  it("starts once, however often it's asked", async () => {
    const { m } = await started(cfg);
    await m.startMonitoring(cfg);
    expect(init).toHaveBeenCalledOnce();
    expect(init.mock.calls[0][0]).toMatchObject({ dsn: cfg.dsn, environment: "prod", release: "1.2.3" });
  });

  it("turns everything on, at full rate", async () => {
    const { m, opts } = await started(cfg);
    expect(opts).toMatchObject({ tracesSampleRate: 1, profileSessionSampleRate: 1, profileLifecycle: "trace" });
    const list = opts.integrations([]);
    expect(list.map((i) => i.name)).toEqual(["Breadcrumbs", "BrowserTracing", "BrowserProfiling", "ConsoleLogging", "Feedback"]);
    expect(list.find((i) => i.name === "Feedback")?.opts).toMatchObject({ autoInject: false, showName: false, showEmail: false, enableScreenshot: false });
    expect(list.find((i) => i.name === "ConsoleLogging")?.opts).toEqual({ levels: ["warn", "error"] });
    expect(m.feedbackAvailable()).toBe(true);
  });

  it("never turns on Session Replay: no replay integration and no replay sample rates", async () => {
    const { opts } = await started(cfg);
    expect(Object.keys(opts).filter((k) => /replay/i.test(k))).toEqual([]);
    const list = opts.integrations([{ name: "Replay" }, { name: "ReplayCanvas" }, { name: "Dedupe" }]);
    expect(list.map((i) => i.name).filter((n) => /replay/i.test(n))).toEqual([]);
    expect(list.map((i) => i.name)).toContain("Dedupe");
  });

  it("isn't written to use Session Replay", async () => {
    const { readFileSync } = await import("node:fs");
    const source = readFileSync(`${process.cwd()}/src/lib/monitoring.ts`, "utf8");
    expect(source).not.toMatch(/replayIntegration\(|replaysSessionSampleRate|replaysOnErrorSampleRate/);
  });

  it("sends trace headers to Waypoint only", async () => {
    const { opts } = await started(cfg);
    const targets = opts.tracePropagationTargets as (RegExp | string)[];
    const matches = (url: string) => targets.some((t) => (typeof t === "string" ? url.startsWith(t) : t.test(url)));
    expect(matches("/api/state")).toBe(true);
    expect(matches(location.origin + "/api/state")).toBe(true);
    expect(matches("https://production.plaid.com/link")).toBe(false);
    expect(matches("//evil.example/x")).toBe(false);
    expect(matches(`https://evil.example/?next=${location.origin}/api`)).toBe(false);
    expect(matches(location.origin + ".evil.example/x")).toBe(false);
  });

  it("names a page by its hash, not what's searched on it", async () => {
    const { opts } = await started(cfg);
    const tracing = opts.integrations([]).find((i) => i.name === "BrowserTracing")!;
    const rename = tracing.opts!.beforeStartSpan as (o: { name: string; op: string }) => { name: string };
    location.hash = "#settings?q=rent";
    expect(rename({ name: "/", op: "navigation" }).name).toBe("/#settings");
    location.hash = "";
    expect(rename({ name: "/", op: "pageload" }).name).toBe("/#upcoming");
  });

  describe("what it sends", () => {
    let opts: Options;
    beforeEach(async () => { ({ opts } = await started(cfg)); });

    it("drops the query string from the page URL (it holds what you searched for) and the user", () => {
      const e = opts.beforeSend({ request: { url: "https://waypoint.test/#transactions?q=rent", headers: { a: "b" } }, user: { id: 1 }, message: "boom" });
      expect(e.request).toEqual({ url: "https://waypoint.test/#transactions" });
      expect(e).not.toHaveProperty("user");
      expect(e.message).toBe("boom");
    });

    it("keeps only the code Waypoint gave the user, never their name, email or address", () => {
      const e = opts.beforeSend({ user: { id: "3f2a9c1d0b7e4a65", email: "a@b.c", username: "Ann", ip_address: "{{auto}}" } });
      expect(e.user).toEqual({ id: "3f2a9c1d0b7e4a65" });
    });

    it("cleans addresses in an error's message and exception text", () => {
      const e = opts.beforeSend({
        message: "load https://u:p@x.test/a?q=rent failed",
        logentry: { message: "GET /api/tx?q=rent", formatted: "GET /api/tx?q=rent 500", params: [] },
        exception: { values: [{ type: "TypeError", value: "NetworkError: https://u:p@waypoint.test/api/transactions?q=starbucks" }, { type: "Error" }] },
      });
      const { exception, logentry } = e as { exception: { values: unknown[] }; logentry: { formatted: string } };
      expect(JSON.stringify(e)).not.toMatch(/rent|starbucks|u:p/);
      expect(exception.values[0]).toEqual({ type: "TypeError", value: "NetworkError: https://[Filtered]@waypoint.test/api/transactions?[Filtered]" });
      expect(exception.values[1]).toEqual({ type: "Error" });
      expect(logentry.formatted).toBe("GET /api/tx?[Filtered] 500");
    });

    it("leaves an event without a request alone", () => {
      expect(opts.beforeSend({ message: "x" })).toEqual({ message: "x" });
    });

    it("cleans URLs in navigation and fetch breadcrumbs", () => {
      const c = opts.beforeBreadcrumb({ data: { url: "https://waypoint.test/api/tx?q=a", from: "https://waypoint.test/#a?x=1", to: "https://waypoint.test/#b?y=2" } });
      expect(c.data).toEqual({ url: "https://waypoint.test/api/tx", from: "https://waypoint.test/#a", to: "https://waypoint.test/#b" });
    });

    it("drops console and click breadcrumbs, which would carry what's on screen", () => {
      const kept = opts.integrations([{ name: "Console" }, { name: "Breadcrumbs" }, { name: "Dedupe" }]);
      expect(kept.map((i) => i.name).slice(0, 2)).toEqual(["Dedupe", "Breadcrumbs"]);
    });

    it("keeps searches out of traces", () => {
      expect(opts).not.toHaveProperty("beforeSendTransaction");
      const fetch = opts.beforeSendSpan({ name: "GET /api/transactions?q=rent&limit=50", attributes: {
        "url.full": "https://waypoint.test/api/transactions?q=rent", "http.query": "q=rent", "sentry.op": "http.client", "http.response.status_code": 200 } });
      expect(fetch).toEqual({ name: "GET /api/transactions?[Filtered]", attributes: {
        "url.full": "https://waypoint.test/api/transactions", "sentry.op": "http.client", "http.response.status_code": 200 } });
    });

    it("cleans console logs and feedback events", () => {
      const log = opts.beforeSendLog({ message: "fetch /api/transactions?q=rent failed", attributes: { "sentry.message.parameter.0": "https://u:p@x.test/a?b=1" } });
      expect(JSON.stringify(log)).not.toMatch(/rent|u:p|b=1/);
      const processor = addEventProcessor.mock.calls[0][0] as (e: Record<string, unknown>) => Record<string, unknown>;
      const fb = processor({ type: "feedback", contexts: { feedback: { url: "https://waypoint.test/#transactions?q=rent", message: "It's slow" } } });
      expect(fb.contexts).toEqual({ feedback: { url: "https://waypoint.test/#transactions", message: "It's slow" } });
      const error = { message: "x?y=1" };
      expect(processor(error)).toBe(error);
    });

    it("never sends a replay", () => {
      const processor = addEventProcessor.mock.calls[0][0] as (e: Record<string, unknown>) => Record<string, unknown> | null;
      expect(processor({ type: "replay_event", urls: ["https://waypoint.test/#reports"] })).toBeNull();
    });
  });

  it("opens the feedback form only once reporting has started", async () => {
    vi.resetModules();
    createForm.mockClear();
    const before = await import("./monitoring");
    await before.openFeedback();
    expect(createForm).not.toHaveBeenCalled();
    const { m } = await started(cfg);
    await m.openFeedback();
    expect(createForm).toHaveBeenCalledOnce();
    expect(form.appendToDom).toHaveBeenCalled();
    expect(form.open).toHaveBeenCalled();
  });
});

describe("scrubText", () => {
  it("blanks queries and credentials, and leaves prose alone", async () => {
    const { scrubText } = await import("./monitoring");
    expect(scrubText("GET /api/tx?q=rent and https://a:b@x.test/y?z=1")).toBe("GET /api/tx?[Filtered] and https://[Filtered]@x.test/y?[Filtered]");
    expect(scrubText("Really? Yes.")).toBe("Really? Yes.");
    expect(scrubText("http://localhost:8799/#transactions?q=Grocer")).toBe("http://localhost:8799/#transactions?[Filtered]");
    expect(scrubText("went /#reports/merchants?name=Target then #budget?m=1")).toBe("went /#reports/merchants?[Filtered] then #budget?[Filtered]");
    expect(scrubText(undefined)).toBeUndefined();
  });
});
