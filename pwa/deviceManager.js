// ============================================
// File: pwa/deviceManager.js
// ============================================

const ENDPOINTS = {
  results: "/api/results/",
  animalitos: "/api/animalitos/",
  heartbeat: "/api/devices/heartbeat/",
  status: "/api/devices/status/",
  register: "/api/devices/register/",
};

function getApiBase() {
  return window.__APP_CONFIG__?.API_BASE || "https://api.ssganador.lat";
}

function getWsBase() {
  return window.__APP_CONFIG__?.WS_BASE || "wss://api.ssganador.lat";
}

function getQueryParam(name) {
  const url = new URL(window.location.href);
  return url.searchParams.get(name);
}

function getDeviceId() {
  let id = localStorage.getItem("device_id");
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem("device_id", id);
  }
  return id;
}

function getActivationCode() {
  const urlCode = (getQueryParam("code") || "").trim();
  if (urlCode) {
    localStorage.setItem("activation_code", urlCode);
    return urlCode;
  }
  return (localStorage.getItem("activation_code") || "").trim();
}

export default class DeviceManager {
  constructor(deviceId) {
    this.deviceId = deviceId || getDeviceId();

    this.activationCode = getActivationCode();

    // Estado
    this.isActive = false;
    this.branchId = null;

    // Timers
    this.resultsInterval = null;
    this.heartbeatInterval = null;

    // WebSocket
    this.ws = null;
    this.wsRetryAttempt = 0;
    this.wsRetryTimer = null;
  }

  /**
   * Ensures we have an activation code.
   * - If URL/localStorage has it -> use it
   * - Else -> auto-register and store it
   */
  async ensureActivationCode() {
    let code = getActivationCode();
    if (code) {
      this.activationCode = code;
      return code;
    }

    const apiBase = getApiBase();
    const res = await fetch(`${apiBase}${ENDPOINTS.register}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({ device_id: this.deviceId }),
    });

    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Register failed: ${res.status} ${text}`);
    }

    const data = await res.json();
    code = String(data.activation_code || "").trim();
    if (!code) throw new Error("Register did not return activation_code");

    localStorage.setItem("activation_code", code);
    this.activationCode = code;

    return code;
  }

  /* -----------------------------
     WEBSOCKET CON BACKOFF LIMPIO
  ------------------------------*/
  connectSocket() {
    if (!this.activationCode) return;

    // evita dobles conexiones
    if (
      this.ws &&
      (this.ws.readyState === WebSocket.OPEN ||
        this.ws.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    // limpia retry pendiente
    if (this.wsRetryTimer) {
      clearTimeout(this.wsRetryTimer);
      this.wsRetryTimer = null;
    }

    const wsBase = getWsBase();
    const url = `${wsBase}/ws/device/${encodeURIComponent(this.activationCode)}/`;
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      console.log("WebSocket conectado:", url);
      this.wsRetryAttempt = 0;
    };

    this.ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        this.handleSocketMessage(msg);
      } catch (e) {
        console.warn("WS parse error:", e);
      }
    };

    this.ws.onclose = () => {
      console.warn("WebSocket desconectado, reintentando...");
      this.scheduleReconnect();
    };

    this.ws.onerror = () => {
      // no reconectar aquí
    };
  }

  scheduleReconnect() {
    // backoff: 1s, 2s, 4s, 8s... max 15s
    const attempt = (this.wsRetryAttempt || 0) + 1;
    this.wsRetryAttempt = attempt;

    const delay = Math.min(15000, 1000 * Math.pow(2, attempt - 1));

    if (this.wsRetryTimer) clearTimeout(this.wsRetryTimer);

    this.wsRetryTimer = setTimeout(() => {
      this.wsRetryTimer = null;
      this.connectSocket();
    }, delay);
  }

  /* -----------------------------
     MENSAJES DEL BACKEND
  ------------------------------*/
  handleSocketMessage(data) {
    // Device asignado a branch
    if (data?.type === "device_assigned") {
      if (!data.branch_id) return;
      if (this.isActive && this.branchId === data.branch_id) return;
      this.activate(data.branch_id);
      return;
    }

    // Cambio de branch
    if (data?.type === "branch_changed") {
      if (this.branchId !== data.branch_id) {
        this.branchId = data.branch_id;
        window.dispatchEvent(new CustomEvent("branchChanged", { detail: data }));
      }
    }
  }

  activate(branchId) {
    if (!branchId) return;

    // idempotente
    if (this.isActive && this.branchId === branchId) return;

    this.isActive = true;
    this.branchId = branchId;

    this.startHeartbeat();
    this.startResultsPolling();

    window.dispatchEvent(new CustomEvent("deviceActivated", { detail: { branchId } }));

    // primer fetch inmediato
    void this.fetchResultsOnce();
  }

  /* -----------------------------
     HEARTBEAT
  ------------------------------*/
  startHeartbeat() {
    if (this.heartbeatInterval) return;
    if (!this.activationCode) return;

    const apiBase = getApiBase();

    this.heartbeatInterval = setInterval(() => {
      fetch(`${apiBase}${ENDPOINTS.heartbeat}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify({
          device_id: this.deviceId,
          code: this.activationCode,
        }),
      }).catch(() => {});
    }, 30000);
  }

  /* -----------------------------
     RESULTADOS
  ------------------------------*/
  startResultsPolling() {
    if (this.resultsInterval) return;
    if (!this.activationCode) return;

    const apiBase = getApiBase();

    this.resultsInterval = setInterval(async () => {
      try {
        const res = await fetch(
          `${apiBase}${ENDPOINTS.results}?code=${encodeURIComponent(this.activationCode)}`,
          { cache: "no-store" }
        );
        if (!res.ok) return;

        const data = await res.json();
        window.dispatchEvent(new CustomEvent("resultsUpdated", { detail: data }));
      } catch (e) {
        console.warn("Error obteniendo resultados");
      }
    }, 60000);
  }

  async fetchResultsOnce() {
    if (!this.activationCode) return;

    const apiBase = getApiBase();

    try {
      const res = await fetch(
        `${apiBase}${ENDPOINTS.results}?code=${encodeURIComponent(this.activationCode)}`,
        { cache: "no-store" }
      );
      if (!res.ok) return;

      const data = await res.json();
      window.dispatchEvent(new CustomEvent("resultsUpdated", { detail: data }));
    } catch (e) {}
  }

  /* -----------------------------
     FALLBACK: STATUS
  ------------------------------*/
  async syncStatusOnce() {
    if (!this.activationCode) return;

    const apiBase = getApiBase();
    const res = await fetch(
      `${apiBase}${ENDPOINTS.status}?code=${encodeURIComponent(this.activationCode)}`,
      { cache: "no-store" }
    );
    if (!res.ok) return;

    const data = await res.json();
    if (data.is_active && data.branch_id && !this.isActive) {
      this.activate(data.branch_id);
    }
  }

  /* -----------------------------
     MANEJO DE RED
  ------------------------------*/
  handleOffline() {
    console.warn("Sin conexión a internet");
    if (this.resultsInterval) clearInterval(this.resultsInterval);
    if (this.heartbeatInterval) clearInterval(this.heartbeatInterval);
    this.resultsInterval = null;
    this.heartbeatInterval = null;
  }

  handleOnline() {
    console.log("Conexión restaurada");
    if (this.isActive) {
      this.startHeartbeat();
      this.startResultsPolling();
    }
    this.connectSocket();
  }
}
