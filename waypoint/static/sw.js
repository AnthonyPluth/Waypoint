const CACHE = "waypoint-shell-v5";
const SHELL = ["/", "/logo.svg", "/fonts/Inter-latin-Variable.woff2", "/fonts/Inter-latin-ext-Variable.woff2",
  "/fonts/Geist-Variable.woff2", "/manifest.webmanifest"];
const isShell = (path) => SHELL.includes(path) || path.startsWith("/assets/");
const APP_PAGES = ["/", "/plaid/oauth"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) if (key !== CACHE) await caches.delete(key);
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/auth/")) return;
  const navigate = event.request.mode === "navigate";
  if (navigate ? !APP_PAGES.includes(url.pathname) : !isShell(url.pathname)) return;
  const key = navigate ? "/" : url.pathname;
  event.respondWith((async () => {
    try {
      const res = await fetch(event.request);
      const page = event.request.mode !== "navigate" || (res.headers.get("Content-Type") || "").startsWith("text/html");
      if (res.ok && !res.redirected && page) (await caches.open(CACHE)).put(key, res.clone());
      return res;
    } catch (err) {
      const cached = await caches.match(key);
      if (cached) return cached;
      throw err;
    }
  })());
});

self.addEventListener("push", (event) => {
  let msg;
  try { msg = event.data ? event.data.json() : {}; } catch { msg = { body: event.data && event.data.text() }; }
  event.waitUntil(self.registration.showNotification(msg.title || "Waypoint", {
    body: msg.body || "",
    icon: "/icon-192.png",
    badge: "/icon-192.png",
    tag: msg.tag || undefined,
    data: { url: msg.url || "/" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  let target = new URL(event.notification.data?.url || "/", location.origin);
  if (target.origin !== location.origin) target = new URL("/", location.origin);
  target = target.href;
  event.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const w of wins) {
      if (new URL(w.url).origin === location.origin) {
        await w.focus();
        return w.navigate ? w.navigate(target) : undefined;
      }
    }
    return self.clients.openWindow(target);
  })());
});
