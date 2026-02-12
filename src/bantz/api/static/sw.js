/* Bantz PWA Service Worker (Issue #847) */
const CACHE_NAME = "bantz-pwa-v1";
const OFFLINE_URL = "/mobile";

const PRECACHE_URLS = [OFFLINE_URL, "/static/manifest.json"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  if (e.request.mode === "navigate") {
    e.respondWith(
      fetch(e.request).catch(() => caches.match(OFFLINE_URL))
    );
    return;
  }
  e.respondWith(
    caches.match(e.request).then((r) => r || fetch(e.request))
  );
});

/* Push notification support */
self.addEventListener("push", (e) => {
  const data = e.data ? e.data.json() : { title: "Bantz", body: "Yeni bildirim" };
  e.waitUntil(
    self.registration.showNotification(data.title || "Bantz", {
      body: data.body || "",
      icon: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🧠</text></svg>",
      badge: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🧠</text></svg>",
      tag: data.tag || "bantz-notification",
      data: data,
    })
  );
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  e.waitUntil(
    clients.matchAll({ type: "window" }).then((list) => {
      for (const c of list) {
        if (c.url.includes("/mobile") && "focus" in c) return c.focus();
      }
      return clients.openWindow("/mobile");
    })
  );
});
