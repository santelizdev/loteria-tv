// ============================================
// File: pwa/deviceManager.js
// Compatible: Android 8+ (WebView Chromium 67+)
// - Sin export default, sin ?., sin const/let dentro de funciones
// - Expone window.DeviceManager como global
// ============================================

var ENDPOINTS = {
  results:   "/api/results/",
  animalitos: "/api/animalitos/",
  heartbeat: "/api/devices/heartbeat/",
  status:    "/api/devices/status/",
  register:  "/api/devices/register/",
};

function getApiBase() {
  return (window.__APP_CONFIG__ && window.__APP_CONFIG__.API_BASE)
    ? window.__APP_CONFIG__.API_BASE
    : "https://api.ssganador.lat";
}

function getWsBase() {
  return (window.__APP_CONFIG__ && window.__APP_CONFIG__.WS_BASE)
    ? window.__APP_CONFIG__.WS_BASE
    : "wss://api.ssganador.lat";
}

function getQueryParam(name) {
  var url = new URL(window.location.href);
  return url.searchParams.get(name);
}

// UUID v4 — compatible Android 8+
// Prioridad: randomUUID → getRandomValues → fallback time+random
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
      var b = bytes[i].toString(16);
      hex += (b.length < 2 ? "0" : "") + b;
    }
    return (
      hex.slice(0, 8)  + "-" +
      hex.slice(8, 12) + "-" +
      hex.slice(12, 16) + "-" +
      hex.slice(16, 20) + "-" +
      hex.slice(20)
    );
  }

  // Fallback débil pero no crashea
  return "tv-" +
    Date.now().toString(16) + "-" +
    Math.random().toString(16).slice(2) + "-" +
    Math.random().toString(16).slice(2);
}

function getDeviceId() {
  var id = localStorage.getItem("device_id");
  if (!id) {
    id = uuidv4();
    localStorage.setItem("device_id", id);
  }
  return id;
}

function getActivationCode() {
  var urlCode = (getQueryParam("code") || "").trim();
  if (urlCode) {
    localStorage.setItem("activation_code", urlCode);
    return urlCode;
  }
  return (localStorage.getItem("activation_code") || "").trim();
}

// ============================================
// DeviceManager — función constructora
// ============================================
function DeviceManager(deviceId) {
  this.deviceId       = deviceId || getDeviceId();
  this.activationCode = getActivationCode();

  this.isActive  = false;
  this.branchId  = null;

  this.resultsInterval   = null;
  this.heartbeatInterval = null;

  this.ws             = null;
  this.wsRetryAttempt = 0;
  this.wsRetryTimer   = null;
}

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
  }).catch(function () { return null; });
};

DeviceManager.prototype.ensureActivationCode = function () {
  var self = this;
  var code = getActivationCode();
  if (code) {
    self.activationCode = code;
    return Promise.resolve(code);
  }

  var apiBase = getApiBase();
  return fetch(apiBase + ENDPOINTS.register, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    body: JSON.stringify({ device_id: self.deviceId }),
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
    localStorage.setItem("activation_code", c);
    self.activationCode = c;
    return c;
  });
};

DeviceManager.prototype.connectSocket = function () {
  var self = this;
  if (!self.activationCode) return;

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
  };

  self.ws.onmessage = function (ev) {
    try {
      var msg = JSON.parse(ev.data);
      self.handleSocketMessage(msg);
    } catch (e) {
      console.warn("WS parse error:", e);
    }
  };

  self.ws.onclose = function () {
    console.warn("WebSocket desconectado, reintentando...");
    self.scheduleReconnect();
  };

  self.ws.onerror = function () {};
};

DeviceManager.prototype.scheduleReconnect = function () {
  var self    = this;
  var attempt = (self.wsRetryAttempt || 0) + 1;
  self.wsRetryAttempt = attempt;
  var delay   = Math.min(15000, 1000 * Math.pow(2, attempt - 1));

  if (self.wsRetryTimer) clearTimeout(self.wsRetryTimer);
  self.wsRetryTimer = setTimeout(function () {
    self.wsRetryTimer = null;
    self.connectSocket();
  }, delay);
};

DeviceManager.prototype.handleSocketMessage = function (data) {
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

DeviceManager.prototype.activate = function (branchId) {
  if (!branchId) return;
  if (this.isActive && this.branchId === branchId) return;

  this.isActive = true;
  this.branchId = branchId;

  this.startHeartbeat();
  this.startResultsPolling();

  window.dispatchEvent(new CustomEvent("deviceActivated", { detail: { branchId: branchId } }));
  this.fetchResultsOnce();
};

DeviceManager.prototype.startHeartbeat = function () {
  var self = this;
  if (self.heartbeatInterval) return;
  if (!self.activationCode) return;

  var apiBase = getApiBase();
  self.heartbeatInterval = setInterval(function () {
    fetch(apiBase + ENDPOINTS.heartbeat, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({ device_id: self.deviceId, code: self.activationCode }),
    }).catch(function () {});
  }, 30000);
};

DeviceManager.prototype.startResultsPolling = function () {
  var self = this;
  if (self.resultsInterval) return;
  if (!self.activationCode) return;

  var apiBase = getApiBase();
  self.resultsInterval = setInterval(function () {
    fetch(
      apiBase + ENDPOINTS.results + "?code=" + encodeURIComponent(self.activationCode),
      { cache: "no-store" }
    ).then(function (res) {
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
  var apiBase = getApiBase();
  return fetch(
    apiBase + ENDPOINTS.results + "?code=" + encodeURIComponent(self.activationCode),
    { cache: "no-store" }
  ).then(function (res) {
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
    if (!res.ok) return;
    return res.json().then(function (data) {
      if (data.is_active && data.branch_id && !self.isActive) {
        self.activate(data.branch_id);
      }
    });
  }).catch(function () {});
};

DeviceManager.prototype.handleOffline = function () {
  console.warn("Sin conexion a internet");
  if (this.resultsInterval)   clearInterval(this.resultsInterval);
  if (this.heartbeatInterval) clearInterval(this.heartbeatInterval);
  this.resultsInterval   = null;
  this.heartbeatInterval = null;
};

DeviceManager.prototype.handleOnline = function () {
  console.log("Conexion restaurada");
  if (this.isActive) {
    this.startHeartbeat();
    this.startResultsPolling();
  }
  this.connectSocket();
};

// Global para app.js
window.DeviceManager = DeviceManager;
