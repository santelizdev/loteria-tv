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

const CACHE_NAME = "loteriatv-v20260225"; // cambia este string en cada deploy

self.addEventListener("install", function (event) {
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE_NAME));
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys.filter(function (k) { return k !== CACHE_NAME; })
            .map(function (k) { return caches.delete(k); })
      );
    }).then(function () {
      return self.clients.claim();
    })
  );
});

self.addEventListener("fetch", function (event) {
  var url = new URL(event.request.url);

  // ✅ API: siempre red, sin caché
  if (url.hostname === "api.ssganador.lat") {
    event.respondWith(fetch(event.request, { cache: "no-store" }));
    return;
  }

  // ✅ Assets: red primero, fallback a caché si está offline
  event.respondWith(
    fetch(event.request, { cache: "no-store" })
      .then(function (resp) {
        var copy = resp.clone();
        caches.open(CACHE_NAME).then(function (cache) {
          cache.put(event.request, copy);
        });
        return resp;
      })
      .catch(function () {
        return caches.match(event.request);
      })
  );
});