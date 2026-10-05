// The web app's reports to Sentry, only when Waypoint is set up for them (SENTRY_DSN; see waypoint/monitoring.py), with
// everything on: tracing, profiling, logs and feedback. Loaded on demand, so nothing of Sentry's is fetched otherwise.
// What's sent never holds what's on the page: no console or click breadcrumbs (they'd hold amounts and names), no query
// strings, no search terms in addresses. Waypoint never records sessions or sends replays: Session Replay isn't used
// (replayIntegration is never imported, so it isn't in the bundle), and the SDK's replay events are dropped.
import type { SentryConfig } from "./types";

let started = false;

// An address's query string: "https://x/y?a=1", "/api/y?a=1", or the app's own "/#transactions?q=rent" and
// "#transactions?q=rent" (its searches are in the hash), but not the "?" ending a sentence.
const URL_QUERY = /((?:[a-z][a-z0-9+.-]*:\/\/[^\s?#"']*|\/[\w.~%:|/-]*)(?:#[\w/-]*)?|#[\w/-]+)\?[^\s#"']+/gi;
const USERINFO = /([a-z][a-z0-9+.-]*:\/\/)[^/\s@"']+@/gi;

/** Any text that may hold addresses: queries blanked, credentials removed. */
export const scrubText = <T>(text: T): T =>
  typeof text === "string"
    ? (text.replace(USERINFO, "$1[Filtered]@").replace(URL_QUERY, "$1?[Filtered]") as T)
    : text;

/** "/#upcoming?q=paris" → "/#upcoming": the page, not what was searched. */
export const pathOnly = (url: string | undefined) => {
  if (!url) return url;
  try {
    const u = new URL(url, location.origin);
    return u.origin + u.pathname + u.hash.split("?")[0];
  } catch { return scrubText(url.split("?")[0]); }
};

/** A page's name in traces: "/#upcoming", whatever was searched on it. */
export const pageName = () => "/#" + ((location.hash || "#upcoming").slice(1).split("?")[0] || "upcoming");

type Data = Record<string, unknown> | undefined;
const URL_KEYS = ["url", "url.full", "http.url", "from", "to"];
const cleanData = (data: Data) => {
  if (!data) return;
  for (const k of ["http.query", "http.fragment", "url.query", "url.fragment"]) delete data[k];
  for (const [k, v] of Object.entries(data)) {
    if (typeof v === "string") data[k] = URL_KEYS.includes(k) ? pathOnly(v) : scrubText(v);
  }
};

/** A span as it's sent (the SDK streams them): its name and attributes, cleaned of searches. */
export function scrubSpan<S extends { name: string; attributes?: Data }>(span: S): S {
  span.name = scrubText(span.name);
  cleanData(span.attributes);
  return span;
}

/** Of whoever the SDK has on an event, only the id: the code Waypoint gave it (startMonitoring), never a name or address. */
export const onlyId = <E extends { user?: { id?: unknown } | null }>(event: E): E => {
  const id = event.user?.id;
  delete event.user;
  if (typeof id === "string" && id) event.user = { id };
  return event;
};

type Event = {
  type?: string; request?: { url?: string }; user?: { id?: unknown } | null;
  contexts?: { feedback?: { url?: string; message?: string } };
};

/** Feedback (it doesn't go through beforeSend): addresses cleaned wherever they're kept. */
function scrubEvent<E extends Event>(event: E): E {
  if (event.request) event.request = { url: pathOnly(event.request.url) };
  onlyId(event);
  if (event.contexts?.feedback?.url) event.contexts.feedback.url = pathOnly(event.contexts.feedback.url);
  return event;
}

export async function startMonitoring(cfg: SentryConfig | null | undefined): Promise<void> {
  if (!cfg || started) return;
  started = true;
  // Only what is named here is bundled (a whole-module import would carry all of the SDK, Session Replay included).
  const { init, breadcrumbsIntegration, browserTracingIntegration, browserProfilingIntegration, consoleLoggingIntegration,
          feedbackIntegration, setUser, addEventProcessor } = await import("@sentry/browser");
  init({
    dsn: cfg.dsn, environment: cfg.environment, release: cfg.release,
    dataCollection: { userInfo: false, cookies: false, httpHeaders: false, httpBodies: [], urlQueryParams: false },
    tracesSampleRate: 1,
    // Trace headers only to Waypoint itself, so its server's trace joins the page's.
    tracePropagationTargets: [/^\/(?!\/)/, new RegExp("^" + location.origin.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "(/|$)")],
    // The browser's own profiler (Chrome and Edge), while a sampled trace runs; the page asks for it with a header.
    profileSessionSampleRate: 1, profileLifecycle: "trace",
    // No console breadcrumbs (Console) or click breadcrumbs (Breadcrumbs' dom): they'd carry what's on screen. And never
    // Session Replay, should a version of the SDK ever count it among its defaults.
    integrations: (defaults) => [
      ...defaults.filter((i) => !["Console", "Breadcrumbs", "Replay", "ReplayCanvas"].includes(i.name)),
      breadcrumbsIntegration({ dom: false }),
      // Pages are the hash (#upcoming), so name page loads and navigations by it, never by what's searched.
      browserTracingIntegration({ beforeStartSpan: (o) => ({ ...o, name: pageName() }) }),
      browserProfilingIntegration(),
      // Console warnings and errors as Sentry Logs (their text is Waypoint's own messages, cleaned like the rest).
      consoleLoggingIntegration({ levels: ["warn", "error"] }),
      // "Send feedback" in Settings opens it: anonymous (the name and email fields are hidden), and no screenshot.
      feedbackIntegration({
        autoInject: false, showName: false, showEmail: false, enableScreenshot: false, showBranding: false,
        colorScheme: "system", formTitle: "Send feedback", messagePlaceholder: "What's wrong, or what would make Waypoint better?",
      }),
    ],
    beforeSend(event) {
      if (event.request) event.request = { url: pathOnly(event.request.url) };
      onlyId(event);
      // An error's text can name an address or a row (a failed fetch says where), so it's cleaned like the server's.
      if (event.message) event.message = scrubText(event.message);
      const entry: { message?: string; formatted?: string } | undefined = event.logentry;   // "formatted" isn't in the SDK's type
      if (entry?.message) entry.message = scrubText(entry.message);
      if (entry?.formatted) entry.formatted = scrubText(entry.formatted);
      for (const exc of event.exception?.values ?? []) if (exc.value) exc.value = scrubText(exc.value);
      return event;
    },
    // Spans are streamed (SDK 11's default), so they're cleaned here; beforeSendTransaction would never run.
    beforeSendSpan: (span) => scrubSpan(span as Parameters<typeof scrubSpan>[0]) as typeof span,
    beforeSendLog(log) {
      log.message = scrubText(log.message);
      for (const [k, v] of Object.entries(log.attributes ?? {})) if (typeof v === "string") log.attributes![k] = scrubText(v);
      return log;
    },
    beforeBreadcrumb(crumb) {
      if (crumb.data?.url) crumb.data.url = pathOnly(crumb.data.url);
      if (crumb.data?.to) crumb.data.to = pathOnly(crumb.data.to);
      if (crumb.data?.from) crumb.data.from = pathOnly(crumb.data.from);
      return crumb;
    },
  });
  // Who's signed in, as Waypoint's code for them: errors, traces and profiles count people, not "anonymous".
  if (cfg.user_id) setUser({ id: cfg.user_id });
  // Feedback doesn't go through beforeSend; this runs for every event. A replay is never sent, whatever starts one.
  addEventProcessor((event) => {
    if ((event.type as string | undefined) === "replay_event") return null;
    return event.type === "feedback" ? scrubEvent(event as Event) as typeof event : event;
  });
}

/** Whether "Send feedback" can be offered (reporting has started). */
export const feedbackAvailable = () => started;

/** Open Sentry's feedback form. */
export async function openFeedback(): Promise<void> {
  if (!feedbackAvailable()) return;
  const { getFeedback } = await import("@sentry/browser");
  const form = await getFeedback()?.createForm();
  form?.appendToDom();
  form?.open();
}
