// What the whole app shares: Waypoint's state (/api/state) and the current page.
import { api, newPage } from "./api";
import type { AppState } from "./types";
import { errMsg } from "./act";

export const app = $state({
  state: null as AppState | null,
  bootError: "" as string,
  /** Signed out while the page was open: App shows a Sign in banner, and Waypoint stops checking in until you do. */
  sessionExpired: false,
});

/** background: Waypoint checking in on its own (see api's `background`), rather than for something you did. */
export async function refreshState(background = false): Promise<void> {
  app.state = await api<AppState>("/api/state", background ? { keep: true, background } : { keep: true });
}

// ------------------------------------------------------------------------------------------ routing
// Hash routes: #upcoming, #settings, ... `sub`: what follows the page's "/" (a tab inside it); `query`: what follows "?".
export const route = $state({ page: "upcoming", sub: "" as string, query: "" as string });

function readHash(): void {
  const [path, query = ""] = (location.hash || "#upcoming").slice(1).split(/\?(.*)/s);
  const [page, sub = ""] = path.split("/");
  if ((page || "upcoming") !== route.page) newPage();   // a tab inside the same page keeps its data and place
  route.page = page || "upcoming";
  route.sub = sub;
  route.query = query;
}

/** Put this query in the address (`#page/sub?query`) without a new history entry or a hashchange: a page's own
 *  filters, as they change. */
export function setQuery(query: string): void {
  if (query === route.query) return;
  const path = (location.hash || "#upcoming").split("?")[0];
  history.replaceState(history.state, "", `${location.pathname}${location.search}${path}${query ? `?${query}` : ""}`);
  route.query = query;
}
readHash();
window.addEventListener("hashchange", readHash);

// ------------------------------------------------------------------------------------------ editors
// True while you're typing or have an editor open, when redrawing the page would throw away what you've entered.
export function editing(): boolean {
  const f = document.activeElement;
  return !!(f && ["INPUT", "TEXTAREA", "SELECT"].includes(f.tagName)) || !!document.querySelector("[data-editor]");
}
// A session that expires while you're editing, or while Waypoint is only checking in, mustn't send you off to sign in
// (see lib/api.ts): App shows a Sign in banner instead.
window.addEventListener("waypoint:signed-out", (e) => {
  if (!e.detail.background && !editing()) return;
  e.preventDefault();
  app.sessionExpired = true;
});

// ------------------------------------------------------------------------------------------ boot
// If Waypoint can't be reached when the app opens (offline, or the server is restarting), say so and keep trying
// every minute (and when you're back online) instead of leaving a blank page.
let booted = false;
const onBoot: (() => void)[] = [];
/** Run `fn` once Waypoint has answered for the first time (straight away if it already has). */
export function whenBooted(fn: () => void): void { if (booted) fn(); else onBoot.push(fn); }
export async function boot(): Promise<void> {
  try { await refreshState(); app.bootError = ""; }
  catch (err) { console.error(err); app.bootError = errMsg(err); return; }
  if (booted) return;
  booted = true;
  onBoot.splice(0).forEach((fn) => fn());
}
window.addEventListener("online", () => { if (!booted) boot(); });
// Coming back to the tab: pick up what changed while it was away.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && booted) checkIn();
});
/** Every minute: pick up what changed meanwhile (or try to boot again, if Waypoint hasn't answered yet). */
export function checkIn(): void {
  if (app.sessionExpired) return;   // nothing more to ask until you've signed in again
  if (booted) refreshState(true).catch((err) => console.error(err)); else boot();
}
setInterval(checkIn, 60_000);
