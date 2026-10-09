import { api, newPage } from "./api";
import type { AppState } from "./types";
import { errMsg } from "./act";
import { syncSavedTrip } from "./offline.svelte";

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
  if ((page || "upcoming") !== route.page) newPage();
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
readHash();
window.addEventListener("hashchange", readHash);

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
  try { await refreshState(); app.bootError = ""; app.offline = false; }
  catch (err) { console.error(err); app.bootError = errMsg(err); app.offline = (err as { status?: number }).status === 0; return; }
  void syncSavedTrip();
  if (booted) return;
  booted = true;
  onBoot.splice(0).forEach((fn) => fn());
}
window.addEventListener("online", () => { if (!booted) boot(); else void syncSavedTrip(); });
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && booted) { checkIn(); void syncSavedTrip(); }
});
export function checkIn(): void {
  if (app.sessionExpired) return;
  if (booted) refreshState(true).catch((err) => console.error(err)); else boot();
}
setInterval(checkIn, 60_000);
