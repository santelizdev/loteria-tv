// pwa/config.js
(() => {
  const APP_VERSION = "__APP_VERSION__";
  const isLocal =
    location.hostname === "localhost" ||
    location.hostname === "127.0.0.1" ||
    location.hostname.endsWith(".local");

  const params = new URLSearchParams(location.search);

  const defaultApiBase = isLocal ? "http://127.0.0.1:8000" : "https://api.ssganador.lat";
  const defaultWsBase = isLocal ? "ws://127.0.0.1:8000" : "wss://api.ssganador.lat";

  const queryApiBase = (params.get("api_base") || "").trim();
  const queryWsBase = (params.get("ws_base") || "").trim();

  if (queryApiBase) localStorage.setItem("pwa_api_base", queryApiBase);
  if (queryWsBase) localStorage.setItem("pwa_ws_base", queryWsBase);

  const API_BASE = (localStorage.getItem("pwa_api_base") || defaultApiBase).trim();
  const WS_BASE = (localStorage.getItem("pwa_ws_base") || defaultWsBase).trim();
  const HEARTBEAT_INTERVAL_MS = 60 * 1000;
  const HEARTBEAT_JITTER_MS = 15 * 1000;

  // La allowlist se conserva por si luego queremos acotar o depurar un subconjunto,
  // pero por defecto la telemetria queda activa en produccion.
  const defaultTelemetryAllowedCodes = [];
  const queryTelemetryCodes = (params.get("telemetry_codes") || "").trim();
  if (queryTelemetryCodes) {
    localStorage.setItem("pwa_telemetry_codes", queryTelemetryCodes);
  }
  const storedTelemetryCodes = (localStorage.getItem("pwa_telemetry_codes") || "").trim();
  const telemetryCodesSource = storedTelemetryCodes
    ? storedTelemetryCodes.split(",")
    : defaultTelemetryAllowedCodes;
  const TELEMETRY_ALLOWED_CODES = telemetryCodesSource
    .map((value) => String(value || "").trim().toUpperCase())
    .filter(Boolean);

  const queryTelemetry = (params.get("telemetry") || "").trim().toLowerCase();
  const telemetryExplicitlyDisabled =
    queryTelemetry === "0" ||
    queryTelemetry === "false" ||
    queryTelemetry === "off";
  const TELEMETRY_ENABLED = !telemetryExplicitlyDisabled;

  // Puedes setear el logo por entorno sin pisar API/WS
  const CLIENT_LOGO = isLocal ? "" : "https://.../logo.png";

  window.__APP_CONFIG__ = {
    APP_VERSION,
    API_BASE,
    WS_BASE,
    CLIENT_LOGO,
    TELEMETRY_ENABLED,
    TELEMETRY_ALLOWED_CODES,
    HEARTBEAT_INTERVAL_MS,
    HEARTBEAT_JITTER_MS,
    isLocal,
  };
})();
