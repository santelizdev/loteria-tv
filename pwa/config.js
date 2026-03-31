// pwa/config.js
(function () {
  function getQueryParam(name) {
    var query = String(window.location.search || "");
    if (query.charAt(0) === "?") query = query.slice(1);
    if (!query) return "";

    var parts = query.split("&");
    for (var i = 0; i < parts.length; i++) {
      var pair = parts[i].split("=");
      var key = decodeURIComponent(pair[0] || "");
      if (key !== name) continue;
      return decodeURIComponent((pair[1] || "").replace(/\+/g, " "));
    }
    return "";
  }

  function normalizeCsv(raw) {
    var input = String(raw || "").trim();
    if (!input) return [];
    var list = input.split(",");
    var out = [];
    for (var i = 0; i < list.length; i++) {
      var value = String(list[i] || "").trim().toUpperCase();
      if (value) out.push(value);
    }
    return out;
  }

  var APP_VERSION = "__APP_VERSION__";
  var origin = window.location.origin;
  var wsOrigin = (location.protocol === "https:" ? "wss" : "ws") + "://" + location.host;
  var hostname = String(location.hostname || "");
  var isLocal =
    hostname === "localhost" ||
    hostname === "127.0.0.1" ||
    /(?:^|\.)local$/.test(hostname);

  var defaultApiBase = origin;
  var defaultWsBase = wsOrigin;

  var queryApiBase = String(getQueryParam("api_base") || "").trim();
  var queryWsBase = String(getQueryParam("ws_base") || "").trim();

  if (queryApiBase) localStorage.setItem("pwa_api_base", queryApiBase);
  if (queryWsBase) localStorage.setItem("pwa_ws_base", queryWsBase);

  var API_BASE = String(localStorage.getItem("pwa_api_base") || defaultApiBase).trim();
  var WS_BASE = String(localStorage.getItem("pwa_ws_base") || defaultWsBase).trim();
  var HEARTBEAT_INTERVAL_MS = 60 * 1000;
  var HEARTBEAT_JITTER_MS = 15 * 1000;

  var defaultTelemetryAllowedCodes = [];
  var queryTelemetryCodes = String(getQueryParam("telemetry_codes") || "").trim();
  if (queryTelemetryCodes) {
    localStorage.setItem("pwa_telemetry_codes", queryTelemetryCodes);
  }

  var storedTelemetryCodes = String(localStorage.getItem("pwa_telemetry_codes") || "").trim();
  var telemetryCodesSource = storedTelemetryCodes
    ? normalizeCsv(storedTelemetryCodes)
    : defaultTelemetryAllowedCodes;

  var TELEMETRY_ALLOWED_CODES = [];
  for (var i = 0; i < telemetryCodesSource.length; i++) {
    if (telemetryCodesSource[i]) {
      TELEMETRY_ALLOWED_CODES.push(telemetryCodesSource[i]);
    }
  }

  var queryTelemetry = String(getQueryParam("telemetry") || "").trim().toLowerCase();
  var telemetryExplicitlyDisabled =
    queryTelemetry === "0" ||
    queryTelemetry === "false" ||
    queryTelemetry === "off";
  var TELEMETRY_ENABLED = !telemetryExplicitlyDisabled;

  var CLIENT_LOGO = isLocal ? "" : "https://.../logo.png";

  window.__APP_CONFIG__ = {
    APP_VERSION: APP_VERSION,
    API_BASE: API_BASE,
    WS_BASE: WS_BASE,
    CLIENT_LOGO: CLIENT_LOGO,
    TELEMETRY_ENABLED: TELEMETRY_ENABLED,
    TELEMETRY_ALLOWED_CODES: TELEMETRY_ALLOWED_CODES,
    HEARTBEAT_INTERVAL_MS: HEARTBEAT_INTERVAL_MS,
    HEARTBEAT_JITTER_MS: HEARTBEAT_JITTER_MS,
    isLocal: isLocal
  };
})();
