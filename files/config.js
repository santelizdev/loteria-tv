// pwa/config.js
(() => {
  const isLocal =
    location.hostname === "localhost" ||
    location.hostname === "127.0.0.1" ||
    location.hostname.endsWith(".local");

  const API_BASE = isLocal ? "http://127.0.0.1:8000" : "https://api.ssganador.lat";
  const WS_BASE  = isLocal ? "ws://127.0.0.1:8000"  : "wss://api.ssganador.lat";

  // Puedes setear el logo por entorno sin pisar API/WS
  const CLIENT_LOGO = isLocal ? "" : "https://.../logo.png";

  window.__APP_CONFIG__ = { API_BASE, WS_BASE, CLIENT_LOGO, isLocal };
})();
