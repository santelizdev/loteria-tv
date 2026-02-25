// ============================================
// service-worker.js — NO-CACHE agresivo
// FIX: el SW anterior tenía fetch vacío, lo que en algunos browsers/WebView
//      causa que la respuesta del SW sea "vacía" o caiga al caché de red del browser.
//
// Esta versión:
//   1. Fuerza bypass total del caché para todas las requests de la app.
//   2. Limpia cualquier caché viejo al activarse.
//   3. Toma control inmediato de todos los clientes (tabs/WebViews abiertos).
// ============================================

const CACHE_NAME = "loteriatv-v20260225"; // <-- cambia en cada deploy

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE_NAME));
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // API: directo a red sin caché
  if (url.hostname === "api.ssganador.lat") {
    event.respondWith(fetch(event.request, { cache: "no-store" }));
    return;
  }

  // Assets: network-first sin caché
  event.respondWith(fetch(event.request, { cache: "no-store" }));
});
