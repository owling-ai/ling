const CACHE_PREFIX = "ling-child-shell";
const CACHE_NAME = `${CACHE_PREFIX}-v7`;
const SHELL = [
  "/child/",
  "/child/index.html",
  "/child/styles.css",
  "/child/app.mjs",
  "/child/api.mjs",
  "/child/model.mjs",
  "/child/manifest.webmanifest",
  "/child/icon-192.png",
  "/child/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    const freshShell = SHELL.map((asset) => new Request(
      new URL(asset, self.location.origin),
      { cache: "reload" },
    ));
    await cache.addAll(freshShell);
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(
      keys
        .filter((key) => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME)
        .map((key) => caches.delete(key)),
    );
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/demo-media/")) return;
  if (url.origin !== self.location.origin) return;
  if (!url.pathname.startsWith("/child/")) return;

  event.respondWith((async () => {
    const cached = await caches.match(request);
    if (cached) return cached;
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      await cache.put(request, response.clone());
    }
    return response;
  })());
});
