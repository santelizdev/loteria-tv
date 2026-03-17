// pwa/config.js
(() => {
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

  // Rollout seguro: mantener vacio en produccion hasta elegir CODs piloto.
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
  const TELEMETRY_ENABLED =
    isLocal ||
    queryTelemetry === "1" ||
    queryTelemetry === "true" ||
    TELEMETRY_ALLOWED_CODES.length > 0;

  // Puedes setear el logo por entorno sin pisar API/WS
  const CLIENT_LOGO = isLocal ? "" : "https://.../logo.png";

  window.__APP_CONFIG__ = {
    API_BASE,
    WS_BASE,
    CLIENT_LOGO,
    TELEMETRY_ENABLED,
    TELEMETRY_ALLOWED_CODES,
    isLocal,
  };
})();
