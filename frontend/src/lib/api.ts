
let pageLoads = new AbortController();

export function newPage(): void {
  pageLoads.abort();
  pageLoads = new AbortController();
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

export type Options = { method?: "GET" | "POST" | "DELETE"; body?: unknown; keep?: boolean; background?: boolean; failed?: string };

declare global {
  interface WindowEventMap { "waypoint:signed-out": CustomEvent<{ background: boolean }> }
}

export function signInUrl(): string {
  return "/auth/login?next=" + encodeURIComponent(location.pathname + location.hash);
}

const OFFLINE = "Can’t reach Waypoint. Check your connection and try again.";
const UNREACHABLE = "Waypoint is restarting or unreachable. Try again in a moment.";

export async function api<T = unknown>(path: string, opts: Options = {}): Promise<T> {
  const init: RequestInit = { method: opts.method ?? "GET", headers: {} };
  const headers = init.headers as Record<string, string>;
  if (init.method !== "GET") headers["X-Waypoint"] = "1";
  if (opts.body instanceof Blob) { headers["Content-Type"] = "application/octet-stream"; init.body = opts.body; }
  else if (opts.body !== undefined) { headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opts.body); }
  const page = init.method === "GET" && !opts.keep ? pageLoads : null;
  if (page) init.signal = page.signal;
  let res: Response;
  try { res = await fetch(path, init); }
  catch (err) {
    if (page?.signal.aborted) return new Promise(() => {});
    throw err instanceof TypeError ? new ApiError(OFFLINE, 0) : err;
  }
  if (res.status === 401) {
    const leave = window.dispatchEvent(new CustomEvent("waypoint:signed-out", { cancelable: true, detail: { background: !!opts.background } }));
    if (!leave || opts.background) throw new ApiError("Your session expired. Sign in again to keep going.", 401);
    location.href = signInUrl();
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
