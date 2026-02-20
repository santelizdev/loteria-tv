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

const SW_VERSION = "v3"; // <— incrementar con cada deploy para forzar update

self.addEventListener("install", (event) => {
  console.log(`[SW ${SW_VERSION}] install`);
  // Activa este SW inmediatamente sin esperar que el viejo cierre
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  console.log(`[SW ${SW_VERSION}] activate — limpiando cachés viejos`);
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.map((key) => {
        console.log(`[SW ${SW_VERSION}] borrando caché: ${key}`);
        return caches.delete(key);
      }))
    ).then(() => {
      // Toma control de todos los clientes abiertos inmediatamente
      return self.clients.claim();
    })
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // No interceptar requests a la API — dejar que vayan directo a la red
  // El DeviceManager ya usa { cache: "no-store" } pero esto lo refuerza
  if (url.hostname === "api.ssganador.lat") {
    event.respondWith(
      fetch(event.request, { cache: "no-store" }).catch(() =>
        new Response(JSON.stringify([]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      )
    );
    return;
  }

  // Para assets de la PWA (app.js, config.js, etc.): network-first sin caché
  // Esto evita que el WebView del TV Box sirva un app.js viejo indefinidamente
  event.respondWith(
    fetch(event.request, { cache: "no-store" }).catch(() =>
      // Fallback: si no hay red, al menos no romper con error
      caches.match(event.request)
    )
  );
});
