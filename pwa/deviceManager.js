// ============================================
// File: pwa/deviceManager.js
// FIX Android 9 (WebView ~Chromium 69):
//   - Eliminado export default (ES module) → asignación a window.DeviceManager
//   - Eliminado ?. (optional chaining) → condicionales explícitos
// IMPORTANTE: En index.html cargar este script ANTES de app.js,
//             ambos sin type="module":
//   <script src="deviceManager.js"></script>
//   <script src="app.js"></script>
// ============================================

var ENDPOINTS = {
  results:   "/api/results/",
  animalitos: "/api/animalitos/",
  heartbeat: "/api/devices/heartbeat/",
  status:    "/api/devices/status/",
  register:  "/api/devices/register/",
};

function getApiBase() {
  // FIX: window.__APP_CONFIG__?.API_BASE → condicional explícito
  return (window.__APP_CONFIG__ && window.__APP_CONFIG__.API_BASE)
    ? window.__APP_CONFIG__.API_BASE
    : window.location.origin;
}

function getWsBase() {
  // FIX: window.__APP_CONFIG__?.WS_BASE → condicional explícito
  return (window.__APP_CONFIG__ && window.__APP_CONFIG__.WS_BASE)
    ? window.__APP_CONFIG__.WS_BASE
    : ((window.location.protocol === "https:" ? "wss://" : "ws://") + window.location.host);
}

function getHeartbeatIntervalMs() {
  var cfg = window.__APP_CONFIG__ || {};
  var value = Number(cfg.HEARTBEAT_INTERVAL_MS || 60000);
  return value >= 15000 ? value : 60000;
}

function getHeartbeatJitterMs() {
  var cfg = window.__APP_CONFIG__ || {};
  var value = Number(cfg.HEARTBEAT_JITTER_MS || 15000);
  return value >= 0 ? value : 15000;
}

function getNextHeartbeatDelayMs() {
  var base = getHeartbeatIntervalMs();
  var jitter = getHeartbeatJitterMs();
  if (!jitter) return base;
  return base + Math.floor(Math.random() * jitter);
}

function getCookieValue(name) {
  var prefix = String(name || "") + "=";
  var raw = String(document.cookie || "");
  if (!raw) return "";

  var parts = raw.split(";");
  for (var i = 0; i < parts.length; i++) {
    var entry = String(parts[i] || "").trim();
    if (entry.indexOf(prefix) !== 0) continue;
    return decodeURIComponent(entry.slice(prefix.length));
  }
  return "";
}

function setCookieValue(name, value) {
  var encoded = encodeURIComponent(String(value || "").trim());
  document.cookie = [
    String(name || "") + "=" + encoded,
    "Path=/",
    "Max-Age=" + String(60 * 60 * 24 * 365 * 5),
    "SameSite=Lax"
  ].join("; ");
}

function removeCookieValue(name) {
  document.cookie = [
    String(name || "") + "=",
    "Path=/",
    "Max-Age=0",
    "SameSite=Lax"
  ].join("; ");
}

function getPersistentValue(key) {
  var value = "";
  try {
    value = String(localStorage.getItem(key) || "").trim();
  } catch (e) {}

  if (value) return value;

  value = String(getCookieValue(key) || "").trim();
  if (!value) return "";

  try {
    localStorage.setItem(key, value);
  } catch (e) {}
  return value;
}

function setPersistentValue(key, value) {
  var normalized = String(value || "").trim();
  if (!normalized) return;

  try {
    localStorage.setItem(key, normalized);
  } catch (e) {}
  setCookieValue(key, normalized);
}

function removePersistentValue(key) {
  try {
    localStorage.removeItem(key);
  } catch (e) {}
  removeCookieValue(key);
}

function buildFormBody(data) {
  var parts = [];
  var key;
  for (key in data) {
    if (!Object.prototype.hasOwnProperty.call(data, key)) continue;
    if (data[key] === null || data[key] === undefined) continue;
    parts.push(
      encodeURIComponent(String(key)) + "=" + encodeURIComponent(String(data[key]))
    );
  }
  return parts.join("&");
}

function getQueryParam(name) {
  var query = String(window.location.search || "");
  if (query.charAt(0) === "?") query = query.slice(1);
  if (!query) return null;

  var parts = query.split("&");
  for (var i = 0; i < parts.length; i++) {
    var pair = parts[i].split("=");
    var key = decodeURIComponent(pair[0] || "");
    if (key !== name) continue;
    return decodeURIComponent((pair[1] || "").replace(/\+/g, " "));
  }
  return null;
}
// UUID v4 compatible with older Android WebView (e.g., Android 9)
// - Prefer crypto.randomUUID when available
// - Fallback to crypto.getRandomValues
// - Final fallback to time+Math.random (avoids crash, but weaker uniqueness)
function uuidv4() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }

  if (window.crypto && typeof window.crypto.getRandomValues === "function") {
    var bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);

    // RFC 4122 version 4
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;

    var hex = "";
    for (var i = 0; i < bytes.length; i++) {
      var value = bytes[i].toString(16);
      if (value.length < 2) value = "0" + value;
      hex += value;
    }

    return (
      hex.slice(0, 8) +
      "-" +
      hex.slice(8, 12) +
      "-" +
      hex.slice(12, 16) +
      "-" +
      hex.slice(16, 20) +
      "-" +
      hex.slice(20)
    );
  }

  return (
    "tv-" +
    Date.now().toString(16) +
    "-" +
    Math.random().toString(16).slice(2) +
    "-" +
    Math.random().toString(16).slice(2)
  );
}
function getDeviceId() {
  var id = getPersistentValue("device_id");
  if (!id) {
    id = uuidv4();
    setPersistentValue("device_id", id);
  }
  return id;
}

function getActivationCode() {
  var urlCode = (getQueryParam("code") || "").trim();
  if (urlCode) {
    setPersistentValue("activation_code", urlCode);
    return urlCode;
  }
  return getPersistentValue("activation_code");
}

function clearActivationCode() {
  removePersistentValue("activation_code");
}

// ============================================
// DeviceManager como función constructora
// (compatible con Android 9, sin class/export)
// ============================================
function DeviceManager(deviceId) {
  this.deviceId       = deviceId || getDeviceId();
  this.activationCode = getActivationCode();

  this.isActive  = false;
  this.branchId  = null;
  this.wsEnabled = false;

  this.resultsInterval   = null;
  this.heartbeatInterval = null;

  this.ws             = null;
  this.wsRetryAttempt = 0;
  this.wsRetryTimer   = null;
  this.wsDisabledUntil = 0;
  this.wsFallbackNoticeAt = 0;
  this.lastRealtimeResultsRefreshAt = 0;
}

DeviceManager.prototype.closeSocket = function (suppressReconnect) {
  var self = this;

  if (self.wsRetryTimer) {
    clearTimeout(self.wsRetryTimer);
    self.wsRetryTimer = null;
  }

  self.wsRetryAttempt = 0;
  self.wsDisabledUntil = 0;
  self.wsFallbackNoticeAt = 0;

  if (!self.ws) return;

  try {
    if (suppressReconnect) {
      self.ws.onclose = function () {};
      self.ws.onerror = function () {};
    }

    if (
      self.ws.readyState === WebSocket.OPEN ||
      self.ws.readyState === WebSocket.CONNECTING
    ) {
      self.ws.close();
    }
  } catch (e) {}

  self.ws = null;
};

DeviceManager.prototype.deactivate = function (reason) {
  var wasActive = !!(this.isActive || this.branchId);

  this.isActive = false;
  this.branchId = null;
  this.wsEnabled = false;

  if (this.resultsInterval) clearInterval(this.resultsInterval);
  if (this.heartbeatInterval) clearTimeout(this.heartbeatInterval);
  this.resultsInterval = null;
  this.heartbeatInterval = null;

  this.closeSocket(true);

  if (wasActive) {
    window.dispatchEvent(new CustomEvent("deviceDeactivated", {
      detail: { reason: String(reason || "").trim() }
    }));
  }
};

DeviceManager.prototype.fetchContextOnce = function () {
  var self = this;
  if (!self.activationCode) return Promise.resolve(null);

  var apiBase = getApiBase();
  return fetch(
    apiBase + ENDPOINTS.status + "?code=" + encodeURIComponent(self.activationCode),
      { cache: "no-store" }
  ).then(function (res) {
    if (!res.ok) return null;
    return res.json();
  });
};

DeviceManager.prototype.ensureActivationCode = function () {
  var self = this;
  var code = getActivationCode();
  if (!code) {
    return self.registerDevice();
  }

  self.activationCode = code;

  var apiBase = getApiBase();
  return fetch(
    apiBase + ENDPOINTS.status + "?code=" + encodeURIComponent(code),
    { cache: "no-store" }
  ).then(function (res) {
    if (res.ok) return code;
    if (res.status !== 404) return code;

    clearActivationCode();
    self.activationCode = "";
    return self.registerDevice();
  }).catch(function () {
    return code;
  });
};

DeviceManager.prototype.registerDevice = function () {
  var self = this;
  var apiBase = getApiBase();

  return fetch(apiBase + ENDPOINTS.register, {
    method: "POST",
    cache: "no-store",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
    },
    body: buildFormBody({ device_id: self.deviceId }),
  }).then(function (res) {
    if (!res.ok) {
      return res.text().then(function (text) {
        throw new Error("Register failed: " + res.status + " " + text);
      });
    }
    return res.json();
  }).then(function (data) {
    var c = String(data.activation_code || "").trim();
    if (!c) throw new Error("Register did not return activation_code");
    setPersistentValue("activation_code", c);
    setPersistentValue("device_id", self.deviceId);
    self.activationCode = c;
    return c;
  });
};

DeviceManager.prototype.connectSocket = function () {
  var self = this;
  if (!self.activationCode) return;
  if (!self.isActive || !self.branchId) return;
  if (!self.wsEnabled) return;
  if (Date.now() < self.wsDisabledUntil) return;

  if (
    self.ws &&
    (self.ws.readyState === WebSocket.OPEN ||
      self.ws.readyState === WebSocket.CONNECTING)
  ) {
    return;
  }

  if (self.wsRetryTimer) {
    clearTimeout(self.wsRetryTimer);
    self.wsRetryTimer = null;
  }

  var wsBase = getWsBase();
  var url    = wsBase + "/ws/device/" + encodeURIComponent(self.activationCode) + "/";
  self.ws    = new WebSocket(url);

  self.ws.onopen = function () {
    console.log("WebSocket conectado:", url);
    self.wsRetryAttempt = 0;
    self.wsDisabledUntil = 0;
    self.wsFallbackNoticeAt = 0;
  };

  self.ws.onmessage = function (ev) {
    try {
      var msg = JSON.parse(ev.data);
      self.handleSocketMessage(msg);
    } catch (e) {
      console.warn("WS parse error:", e);
    }
  };

  self.ws.onclose = function (event) {
    self.ws = null;

    if (event && event.code === 4403) {
      self.wsRetryAttempt = 0;
      self.wsDisabledUntil = Date.now() + 60000;
      console.warn("WebSocket rechazado por backend; revalidando estado del device.");
      self.syncStatusOnce().catch(function () {});
      return;
    }

    console.warn("WebSocket desconectado, reintentando...");
    self.scheduleReconnect();
  };

  self.ws.onerror = function () {};
};

DeviceManager.prototype.scheduleReconnect = function () {
  var self    = this;
  if (!self.isActive || !self.branchId) return;
  if (!self.wsEnabled) return;
  var attempt = (self.wsRetryAttempt || 0) + 1;
  self.wsRetryAttempt = attempt;

  var delay = Math.min(300000, 1000 * Math.pow(2, attempt - 1));

  if (attempt >= 5) {
    self.wsDisabledUntil = Date.now() + 5 * 60 * 1000;
    delay = 5 * 60 * 1000;
    if (!self.wsFallbackNoticeAt || (Date.now() - self.wsFallbackNoticeAt) > (5 * 60 * 1000)) {
      self.wsFallbackNoticeAt = Date.now();
      console.warn("WebSocket no disponible; continuando con polling y reintentando luego.");
    }
  }

  if (self.wsRetryTimer) clearTimeout(self.wsRetryTimer);

  self.wsRetryTimer = setTimeout(function () {
    self.wsRetryTimer = null;
    self.connectSocket();
  }, delay);
};

DeviceManager.prototype.handleSocketMessage = function (data) {
  // FIX: data?.type → data && data.type
  if (data && data.type === "refresh_results_now") {
    this.dispatchRealtimeResultsRefresh(data);
    return;
  }

  if (data && data.type === "device_assigned") {
    if (!data.branch_id) return;
    if (this.isActive && this.branchId === data.branch_id) return;
    this.activate(data.branch_id);
    return;
  }

  if (data && data.type === "branch_changed") {
    if (this.branchId !== data.branch_id) {
      this.branchId = data.branch_id;
      window.dispatchEvent(new CustomEvent("branchChanged", { detail: data }));
    }
  }
};

DeviceManager.prototype.dispatchRealtimeResultsRefresh = function (data) {
  var now = Date.now();
  if ((now - (this.lastRealtimeResultsRefreshAt || 0)) < 1500) {
    return;
  }

  this.lastRealtimeResultsRefreshAt = now;
  window.dispatchEvent(new CustomEvent("resultsUpdated", {
    detail: data || { type: "refresh_results_now", source: "websocket" }
  }));
};

DeviceManager.prototype.activate = function (branchId, options) {
  if (!branchId) return;
  if (options && typeof options.wsEnabled === "boolean") {
    this.wsEnabled = options.wsEnabled;
  }
  if (this.isActive && this.branchId === branchId) return;

  this.isActive  = true;
  this.branchId  = branchId;

  this.startHeartbeat();
  this.startResultsPolling();
  this.connectSocket();

  window.dispatchEvent(new CustomEvent("deviceActivated", { detail: { branchId: branchId } }));

  this.fetchResultsOnce();
};

DeviceManager.prototype.startHeartbeat = function () {
  var self = this;
  if (self.heartbeatInterval) return;
  if (!self.activationCode) return;
  if (!self.isActive || !self.branchId) return;

  self.scheduleHeartbeat(getNextHeartbeatDelayMs());
  self.sendHeartbeatOnce();
};

DeviceManager.prototype.scheduleHeartbeat = function (delayMs) {
  var self = this;
  if (self.heartbeatInterval) return;

  self.heartbeatInterval = setTimeout(function tickHeartbeat() {
    self.heartbeatInterval = null;
    self.sendHeartbeatOnce().then(function () {
      if (!self.isActive || navigator.onLine === false) return;
      self.scheduleHeartbeat(getNextHeartbeatDelayMs());
    });
  }, delayMs);
};

DeviceManager.prototype.sendHeartbeatOnce = function () {
  var self = this;
  if (!self.activationCode) return Promise.resolve(null);

  var apiBase = getApiBase();
  return fetch(apiBase + ENDPOINTS.heartbeat, {
    method: "POST",
    cache: "no-store",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
    },
    body: buildFormBody({
      device_id: self.deviceId,
      code: self.activationCode,
    }),
  }).then(function (res) {
    if (res && (res.status === 403 || res.status === 404)) {
      self.deactivate("heartbeat_" + String(res.status));
      return null;
    }
    return res;
  }).catch(function () {
    return null;
  });
};

DeviceManager.prototype.startResultsPolling = function () {
  var self = this;
  if (self.resultsInterval) return;
  if (!self.activationCode) return;
  if (!self.isActive || !self.branchId) return;

  var apiBase = getApiBase();

  self.resultsInterval = setInterval(function () {
    fetch(
      apiBase + ENDPOINTS.results + "?code=" + encodeURIComponent(self.activationCode) + "&nocache=1",
          { cache: "no-store" }
    ).then(function (res) {
        if (res && (res.status === 403 || res.status === 404)) {
          self.deactivate("results_" + String(res.status));
          return;
        }
        if (!res.ok) return;
      return res.json().then(function (data) {
        window.dispatchEvent(new CustomEvent("resultsUpdated", { detail: data }));
      });
    }).catch(function (e) {
      console.warn("Error obteniendo resultados", e);
    });
    }, 60000);
};

DeviceManager.prototype.fetchResultsOnce = function () {
  var self = this;
  if (!self.activationCode) return Promise.resolve();
  if (!self.isActive || !self.branchId) return Promise.resolve();

  var apiBase = getApiBase();

  return fetch(
    apiBase + ENDPOINTS.results + "?code=" + encodeURIComponent(self.activationCode) + "&nocache=1",
        { cache: "no-store" }
  ).then(function (res) {
      if (res && (res.status === 403 || res.status === 404)) {
        self.deactivate("results_once_" + String(res.status));
        return;
      }
      if (!res.ok) return;
    return res.json().then(function (data) {
      window.dispatchEvent(new CustomEvent("resultsUpdated", { detail: data }));
    });
  }).catch(function () {});
};

DeviceManager.prototype.syncStatusOnce = function () {
  var self = this;
  if (!self.activationCode) return Promise.resolve();

  var apiBase = getApiBase();
  return fetch(
    apiBase + ENDPOINTS.status + "?code=" + encodeURIComponent(self.activationCode),
      { cache: "no-store" }
  ).then(function (res) {
    if (!res.ok) {
      if (res.status === 403 || res.status === 404) {
        self.deactivate("status_" + String(res.status));
      }
      return null;
    }
    return res.json().then(function (data) {
      self.wsEnabled = !!(data && data.realtime_enabled);
      if (data && data.is_active && data.branch_id) {
        self.activate(data.branch_id, { wsEnabled: self.wsEnabled });
      } else {
        self.deactivate("status_inactive");
      }
      return data;
    });
  });
};

DeviceManager.prototype.handleOffline = function () {
  console.warn("Sin conexión a internet");
  if (this.resultsInterval)   clearInterval(this.resultsInterval);
  if (this.heartbeatInterval) clearTimeout(this.heartbeatInterval);
  this.resultsInterval   = null;
  this.heartbeatInterval = null;
};

DeviceManager.prototype.handleOnline = function () {
  console.log("Conexión restaurada");
  this.syncStatusOnce();
};

// Exponer globalmente para que app.js lo use sin import
window.DeviceManager = DeviceManager;
