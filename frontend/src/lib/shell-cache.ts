import { ignoreFailure } from "./act";

const GIVE_UP_MS = 1000;

export function loadedAssetPaths(entries: { name: string }[], origin: string): string[] {
  const paths = new Set<string>();
  for (const { name } of entries) {
    let url: URL;
    try { url = new URL(name); } catch { continue; }
    if (url.origin === origin && url.pathname.startsWith("/assets/")) paths.add(url.pathname);
  }
  return [...paths];
}

type Entries = { getEntries: () => { name: string }[] };
type Observer = { observe: (options: { type: string; buffered: boolean }) => void; disconnect: () => void };
export type Scope = { location: { origin: string }; PerformanceObserver?: new (callback: (list: Entries) => void) => Observer };

function loadedResources(win: Scope): Promise<{ name: string }[]> {
  return new Promise((resolve) => {
    const Watcher = win.PerformanceObserver;
    if (!Watcher) return resolve([]);
    const finish = (entries: { name: string }[]) => { observer.disconnect(); clearTimeout(timer); resolve(entries); };
    const observer = new Watcher((list) => finish(list.getEntries()));
    const timer = setTimeout(() => finish([]), GIVE_UP_MS);
    observer.observe({ type: "resource", buffered: true });
  });
}

export function registerShellCache(container: ServiceWorkerContainer, win: Scope): void {
  const hand = async () => {
    const reg = await container.ready;
    reg.active?.postMessage({ type: "keep-loaded", paths: loadedAssetPaths(await loadedResources(win), win.location.origin) });
  };
  container.addEventListener("controllerchange", () => { hand().catch(ignoreFailure); });
  container.register("/sw.js").then(hand).catch((err) => console.warn("Service worker:", err));
}
