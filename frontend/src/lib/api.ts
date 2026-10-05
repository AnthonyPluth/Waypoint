// Talking to Waypoint's server. Reads belong to the page that asked for them: moving to another page cancels them,
// and a cancelled read never answers, so a slow reply can't draw the old page over the new one. `keep` opts out.

let pageLoads = new AbortController();

/** Called by the router when the page changes. */
export function newPage(): void {
  pageLoads.abort();
  pageLoads = new AbortController();
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

/** `background`: a call Waypoint makes on its own (the state poll, the sync on opening), not one you asked for.
 * `body`: sent as JSON, except a file (Blob), which goes up as it is (a backup). `failed`: what to call a refusal that
 * says nothing ("Restore failed (500)"), instead of "Request failed (500)". */
export type Options = { method?: "GET" | "POST" | "DELETE"; body?: unknown; keep?: boolean; background?: boolean; failed?: string };

// When the session has expired, sending you to sign in throws away the page, and whatever you're typing on it. So
// this event goes out first, and the app (lib/app.svelte.ts) cancels it while you're editing, and always for a
// background call; it then shows a Sign in banner instead, and the page stays as it is.
declare global {
  interface WindowEventMap { "waypoint:signed-out": CustomEvent<{ background: boolean }> }
}

/** Sign in again, then come back to this page. */
export function signInUrl(): string {
  return "/auth/login?next=" + encodeURIComponent(location.pathname + location.hash);
}

const OFFLINE = "Can’t reach Waypoint. Check your connection and try again.";
const UNREACHABLE = "Waypoint is restarting or unreachable. Try again in a moment.";   // what a proxy says while it's down

export async function api<T = unknown>(path: string, opts: Options = {}): Promise<T> {
  const init: RequestInit = { method: opts.method ?? "GET", headers: {} };
  const headers = init.headers as Record<string, string>;
  if (init.method !== "GET") headers["X-Waypoint"] = "1";   // Waypoint refuses state changes without it (CSRF)
  if (opts.body instanceof Blob) { headers["Content-Type"] = "application/octet-stream"; init.body = opts.body; }
  else if (opts.body !== undefined) { headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opts.body); }
  const page = init.method === "GET" && !opts.keep ? pageLoads : null;
  if (page) init.signal = page.signal;
  let res: Response;
  try { res = await fetch(path, init); }
  catch (err) {
    if (page?.signal.aborted) return new Promise(() => {});
    // fetch fails with a TypeError when there's no answer at all; each browser words it differently
    throw err instanceof TypeError ? new ApiError(OFFLINE, 0) : err;
  }
  if (res.status === 401) {   // signed out (session expired)
    const leave = window.dispatchEvent(new CustomEvent("waypoint:signed-out", { cancelable: true, detail: { background: !!opts.background } }));
    if (!leave || opts.background) throw new ApiError("Your session expired. Sign in again to keep going.", 401);
    location.href = signInUrl();   // sign in, then come back here
    throw new ApiError("Signing you in again…", 401);
  }
  const data = await res.json().catch(() => ({}));
  if (page?.signal.aborted) return new Promise(() => {});
  if (!res.ok) {
    const said = opts.failed ? `${opts.failed} (${res.status})` : [502, 503, 504].includes(res.status) ? UNREACHABLE : `Request failed (${res.status})`;
    throw new ApiError(data.error || said, res.status);
  }
  return data as T;
}
