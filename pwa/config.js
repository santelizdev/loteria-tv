// pwa/config.js
(() => {
  const isLocal =
    location.hostname === "localhost" ||
    location.hostname === "127.0.0.1" ||
    location.hostname.endsWith(".local");

  const API_BASE = isLocal ? "http://127.0.0.1:8000" : "https://api.ssganador.lat";
  const WS_BASE = isLocal ? "ws://127.0.0.1:8000" : "wss://api.ssganador.lat";

  window.__APP_CONFIG__ = { API_BASE, WS_BASE, isLocal };
})();
window.__APP_CONFIG__ = {
  API_BASE: "http://127.0.0.1:8000",
  WS_BASE: "ws://127.0.0.1:8000",
  CLIENT_LOGO: "https://.../logo.png"
};
