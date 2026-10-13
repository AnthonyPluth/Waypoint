import { api, newPage } from "./api";
import type { AppState } from "./types";
import { errMsg } from "./act";
import { dropEarly, startEarly } from "./early";
import { syncSavedTrip } from "./offline.svelte";
import { anyDirty, anySaving, leave } from "./drafts.svelte";

export const app = $state({
  state: null as AppState | null,
  bootError: "" as string,
  offline: false,
  sessionExpired: false,
});

export async function refreshState(background = false): Promise<void> {
  app.state = await api<AppState>("/api/state", background ? { keep: true, background } : { keep: true });
}

export const route = $state({ page: "upcoming", sub: "" as string, query: "" as string });

function readHash(): void {
  const [path, query = ""] = (location.hash || "#upcoming").slice(1).split(/\?(.*)/s);
  const [page, sub = ""] = path.split("/");
  if ((page || "upcoming") !== route.page) { newPage(); dropEarly(); }
  route.page = page || "upcoming";
  route.sub = sub;
  route.query = query;
}

export function setQuery(query: string): void {
  if (query === route.query) return;
  const path = (location.hash || "#upcoming").split("?")[0];
  history.replaceState(history.state, "", `${location.pathname}${location.search}${path}${query ? `?${query}` : ""}`);
  route.query = query;
}

let undoing = false;
const entryOf = (): number => {
  const n = (history.state as { wp?: number } | null)?.wp;
  if (typeof n === "number") return n;
  const index = history.length - 1;
  history.replaceState({ ...(history.state ?? {}), wp: index }, "");
  return index;
};
let here = entryOf();

function onHashChange(): void {
  if (undoing) { undoing = false; return; }
  const target = location.hash;
  const there = (history.state as { wp?: number } | null)?.wp;
  if (!anyDirty() && !anySaving()) { here = entryOf(); readHash(); return; }
  const back = typeof there === "number" ? here - there : -1;
  if (back !== 0) { undoing = true; history.go(back); }
  leave(() => { location.hash = target; });
}
readHash();
window.addEventListener("hashchange", onHashChange);

export function editing(): boolean {
  const f = document.activeElement;
  return !!(f && ["INPUT", "TEXTAREA", "SELECT"].includes(f.tagName)) || !!document.querySelector("[data-editor]");
}
window.addEventListener("waypoint:signed-out", (e) => {
  if (!e.detail.background && !editing()) return;
  e.preventDefault();
  app.sessionExpired = true;
});

let booted = false;
const onBoot: (() => void)[] = [];
export function whenBooted(fn: () => void): void { if (booted) fn(); else onBoot.push(fn); }
export async function boot(): Promise<void> {
  if (!booted) { dropEarly(); startEarly(route.page); }
  try { await refreshState(); app.bootError = ""; app.offline = false; }
  catch (err) { console.error(err); app.bootError = errMsg(err); app.offline = (err as { status?: number }).status === 0; return; }
  void syncSavedTrip();
  if (booted) return;
  booted = true;
  onBoot.splice(0).forEach((fn) => fn());
}
window.addEventListener("online", () => { if (!booted) boot(); else void syncSavedTrip(); });
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible" || !booted) return;
  if (app.sessionExpired) { void signedBackIn(); return; }
  checkIn();
  void syncSavedTrip();
});
async function signedBackIn(): Promise<void> {
  try { await refreshState(true); app.sessionExpired = false; }
  catch (err) { console.error(err); }
}
export function checkIn(): void {
  if (app.sessionExpired) return;
  if (booted) refreshState(true).catch((err) => console.error(err)); else boot();
}
setInterval(checkIn, 60_000);
