const CACHE_PREFIX = "ling-child-shell";
const CACHE_NAME = `${CACHE_PREFIX}-v4`;
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
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys
        .filter((key) => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME)
        .map((key) => caches.delete(key)),
    )),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/demo-media/")) return;
  if (url.origin !== self.location.origin) return;
  if (!url.pathname.startsWith("/child/")) return;

  event.respondWith(
    caches.match(request).then((cached) => cached || fetch(request).then((response) => {
      if (!response.ok) return response;
      const copy = response.clone();
      caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
      return response;
    })),
  );
});
