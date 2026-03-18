// pwa/telemetry.js
// Telemetria pasiva y fail-open para TVs sensibles.
(function () {
  var ENDPOINT = "/api/devices/telemetry/";
  var eventThrottleMs = {
    APP_START: 60 * 1000,
    WEBVIEW_INFO: 6 * 60 * 60 * 1000,
    LOAD_SUCCESS: 60 * 1000,
    LOAD_ERROR: 30 * 1000,
    LOW_MEMORY: 30 * 1000,
    APP_PAUSE: 30 * 1000,
    APP_RESUME: 30 * 1000,
  };
  var lastSentAtByKey = {};
  var sessionFlags = {};

  function getConfig() {
    return window.__APP_CONFIG__ || {};
  }

  function getApiBase() {
    return getConfig().API_BASE || "https://api.ssganador.lat";
  }

  function buildFormBody(data) {
    var body = new URLSearchParams();
    var key;
    for (key in data) {
      if (!Object.prototype.hasOwnProperty.call(data, key)) continue;
      if (data[key] === null || data[key] === undefined) continue;
      body.append(key, String(data[key]));
    }
    return body;
  }

  function normalizeCode(value) {
    return String(value || "").trim().toUpperCase();
  }

  function getActivationCode() {
    var fromStorage = localStorage.getItem("activation_code");
    return normalizeCode(fromStorage);
  }

  function getDeviceId() {
    return String(localStorage.getItem("device_id") || "").trim();
  }

  function isAllowedForCode(code) {
    var cfg = getConfig();
    if (!cfg.TELEMETRY_ENABLED) return false;
    if (cfg.isLocal) return true;

    var allowedCodes = cfg.TELEMETRY_ALLOWED_CODES || [];
    if (!allowedCodes.length) return true;
    return allowedCodes.indexOf(normalizeCode(code)) !== -1;
  }

  function shouldSend(eventType, code) {
    if (!isAllowedForCode(code)) return false;

    var throttleMs = eventThrottleMs[eventType] || 0;
    if (!throttleMs) return true;

    var key = eventType + "::" + normalizeCode(code);
    var now = Date.now();
    var lastSentAt = lastSentAtByKey[key] || 0;
    if ((now - lastSentAt) < throttleMs) return false;

    lastSentAtByKey[key] = now;
    return true;
  }

  function getAndroidVersion() {
    var match = String(navigator.userAgent || "").match(/Android\s+([0-9.]+)/i);
    return match ? match[1] : "";
  }

  function getWebViewVersion() {
    var ua = String(navigator.userAgent || "");
    var chromeMatch = ua.match(/Chrome\/([0-9.]+)/i);
    if (chromeMatch) return chromeMatch[1];
    var versionMatch = ua.match(/Version\/([0-9.]+)/i);
    return versionMatch ? versionMatch[1] : "";
  }

  function getDeviceModel() {
    var ua = String(navigator.userAgent || "");
    var buildMatch = ua.match(/;\s*([^)]+)\s+Build\//i);
    if (buildMatch) return buildMatch[1].trim();
    return "";
  }

  function baseMetadata() {
    return {
      android_version: getAndroidVersion(),
      webview_version: getWebViewVersion(),
      device_model: getDeviceModel(),
      user_agent: String(navigator.userAgent || ""),
    };
  }

  function mergeMetadata(extraMetadata) {
    var merged = baseMetadata();
    var key;
    var extra = extraMetadata || {};
    for (key in extra) {
      if (!Object.prototype.hasOwnProperty.call(extra, key)) continue;
      if (extra[key] === null || extra[key] === undefined || extra[key] === "") continue;
      merged[key] = extra[key];
    }
    return merged;
  }

  function send(eventType, options) {
    var payload = options || {};
    var code = normalizeCode(payload.code || getActivationCode());
    var deviceId = String(payload.deviceId || getDeviceId() || "").trim();

    if (!code || !deviceId) return Promise.resolve(null);
    if (!shouldSend(eventType, code)) return Promise.resolve(null);

    return fetch(getApiBase() + ENDPOINT, {
      method: "POST",
      cache: "no-store",
      body: buildFormBody({
        device_id: deviceId,
        code: code,
        event_type: eventType,
        message: String(payload.message || "").trim(),
        metadata: JSON.stringify(mergeMetadata(payload.metadata)),
      }),
    }).then(function (res) {
      if (!res.ok) return null;
      return res.json();
    }).catch(function (err) {
      console.warn("Telemetry send failed:", eventType, err && err.message ? err.message : err);
      return null;
    });
  }

  function sendOncePerSession(flag, eventType, options) {
    if (sessionFlags[flag]) return Promise.resolve(null);
    sessionFlags[flag] = true;
    return send(eventType, options);
  }

  function reportWebViewInfo(options) {
    return sendOncePerSession("webview_info", "WEBVIEW_INFO", options || {});
  }

  function bindLowMemoryListeners() {
    function report(event) {
      var detail = (event && event.detail) || {};
      send("LOW_MEMORY", {
        message: String(detail.message || "LOW_MEMORY").trim(),
        metadata: detail.metadata || {},
      });
    }

    window.addEventListener("appLowMemory", report);
    window.addEventListener("lowMemory", report);
  }

  function bindVisibilityLifecycle() {
    if (typeof document.hidden === "undefined") return;
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) {
        send("APP_PAUSE", { message: "document.hidden=true" });
        return;
      }
      send("APP_RESUME", { message: "document.hidden=false" });
    });
  }

  bindLowMemoryListeners();
  bindVisibilityLifecycle();

  window.DeviceTelemetry = {
    send: send,
    sendOncePerSession: sendOncePerSession,
    reportWebViewInfo: reportWebViewInfo,
    isAllowedForCode: isAllowedForCode,
    getActivationCode: getActivationCode,
  };
})();
