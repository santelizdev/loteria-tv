// ============================================
// service-worker.js — shell cache liviano para Android TV
// Objetivo:
//   1. Mantener disponible el shell de la PWA ante timeouts de navegación.
//   2. NO cachear API, websockets ni recursos cross-origin pesados.
//   3. Reducir presión de memoria/almacenamiento en WebView viejos.
// ============================================

var CACHE_NAME = "loteriatv-shell-v20260318-low-memory";
var APP_SHELL = [
  "./",
  "./index.html",
  "./config.js",
  "./deviceManager.js",
  "./telemetry.js",
  "./app.js",
  "./src/styles.css",
  "./manifest.json",
  "./Favicon.ico"
];

function isHttpRequest(request) {
  return request && request.url && request.url.indexOf("http") === 0;
}

function isSameOrigin(url) {
  return url.origin === self.location.origin;
}

function isApiRequest(url) {
  return (
    url.hostname === "api.ssganador.lat" ||
    url.pathname.indexOf("/api/") === 0 ||
    url.pathname.indexOf("/ws/") === 0
  );
}

function isNavigationRequest(request) {
  return request.mode === "navigate" || (request.headers.get("accept") || "").indexOf("text/html") >= 0;
}

function isCacheableShellAsset(request, url) {
  if (!isSameOrigin(url)) return false;
  if (request.method !== "GET") return false;
  if (isNavigationRequest(request)) return false;
  if (isApiRequest(url)) return false;
  return (
    url.pathname === "/" ||
    url.pathname === "/index.html" ||
    url.pathname.indexOf("/src/") === 0 ||
    url.pathname.indexOf("/pwa/") === 0 ||
    /\.js$/i.test(url.pathname) ||
    /\.css$/i.test(url.pathname) ||
    /\.json$/i.test(url.pathname) ||
    /\.ico$/i.test(url.pathname)
  );
}

function fetchWithTimeout(request, timeoutMs) {
  return new Promise(function (resolve, reject) {
    var didFinish = false;
    var timer = setTimeout(function () {
      if (didFinish) return;
      didFinish = true;
      reject(new Error("SW_FETCH_TIMEOUT"));
    }, timeoutMs);

    fetch(request, { cache: "no-store" })
      .then(function (response) {
        if (didFinish) return;
        didFinish = true;
        clearTimeout(timer);
        resolve(response);
      })
      .catch(function (error) {
        if (didFinish) return;
        didFinish = true;
        clearTimeout(timer);
        reject(error);
      });
  });
}

self.addEventListener("install", function (event) {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(function (cache) {
      return cache.addAll(APP_SHELL);
    })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys
          .filter(function (key) { return key !== CACHE_NAME; })
          .map(function (key) { return caches.delete(key); })
      );
    }).then(function () {
      return self.clients.claim();
    })
  );
});

self.addEventListener("fetch", function (event) {
  var request = event.request;

  if (!isHttpRequest(request) || request.method !== "GET") {
    return;
  }

  var url = new URL(request.url);

  if (isApiRequest(url) || !isSameOrigin(url)) {
    event.respondWith(fetch(request, { cache: "no-store" }));
    return;
  }

  if (isNavigationRequest(request)) {
    event.respondWith(
      fetchWithTimeout(request, 8000)
        .then(function (response) {
          if (!response || !response.ok) return response;
          var copy = response.clone();
          caches.open(CACHE_NAME).then(function (cache) {
            cache.put("./index.html", copy);
          });
          return response;
        })
        .catch(function () {
          return caches.match("./index.html").then(function (cached) {
            return cached || caches.match("./");
          });
        })
    );
    return;
  }

  if (isCacheableShellAsset(request, url)) {
    event.respondWith(
      caches.match(request).then(function (cached) {
        if (cached) return cached;
        return fetch(request, { cache: "no-store" }).then(function (response) {
          if (!response || !response.ok) return response;
          var copy = response.clone();
          caches.open(CACHE_NAME).then(function (cache) {
            cache.put(request, copy);
          });
          return response;
        });
      })
    );
    return;
  }

  event.respondWith(fetch(request, { cache: "no-store" }));
});
