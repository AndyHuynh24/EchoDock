// Service worker: makes Dock installable and works offline. Network first.
const CACHE = "dock-v1";
const FILES = ["./index.html", "./style.css", "./app.js", "./focus.js", "./config.js", "./icon.svg", "./icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(FILES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  // Only Dock's own files.
  if (event.request.method !== "GET" || url.origin !== location.origin || url.pathname.endsWith("address.json")) return;
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const copy = response.clone();
        if (response.ok) caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request, { ignoreSearch: true })),
  );
});
