const CACHE_NAME = "ling-parent-shell-v4";
const SHELL = [
  "/parent/",
  "/parent/index.html",
  "/parent/styles.css",
  "/parent/api.mjs",
  "/parent/model.mjs",
  "/parent/app.mjs",
  "/parent/manifest.webmanifest",
  "/parent/icon-192.png",
  "/parent/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    await cache.addAll(SHELL);
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(
      names
        .filter((name) => name.startsWith("ling-parent-shell-") && name !== CACHE_NAME)
        .map((name) => caches.delete(name)),
    );
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  if (!url.pathname.startsWith("/parent/")) return;

  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).catch(async () => (
        (await caches.match("/parent/"))
          || (await caches.match("/parent/index.html"))
          || new Response("家长端暂时离线，请恢复网络后重试。", {
            status: 503,
            headers: { "Content-Type": "text/plain; charset=utf-8" },
          })
      )),
    );
    return;
  }

  event.respondWith((async () => {
    const cached = await caches.match(event.request);
    if (cached) return cached;
    const response = await fetch(event.request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      await cache.put(event.request, response.clone());
    }
    return response;
  })());
});
