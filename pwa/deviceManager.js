// deviceManager.js
const ENDPOINTS = {
  results: "/api/results/",
  animalitos: "/api/animalitos/",
  heartbeat: "/api/devices/heartbeat/",
  status: "/api/devices/status/",
  register: "/api/devices/register/",
};

const DEV_BACKEND = "http://127.0.0.1:8000";
const API_BASE = (location.port === "8080" || location.port === "5173")
  ? DEV_BACKEND
  : `${location.protocol}//${location.host}`;

function wsBaseUrl() {
  // si PWA está en 8080/5173 (dev), WS debe ir al backend 8000
  if (location.port === "8080" || location.port === "5173") {
    return "ws://127.0.0.1:8000";
  }
  const wsProto = location.protocol === "https:" ? "wss" : "ws";
  return `${wsProto}://${location.host}`;
}

class DeviceManager {
  constructor(deviceId) {
    this.deviceId = deviceId;

    // Estado persistente
    this.activationCode = localStorage.getItem("activation_code");

    // Estado en memoria
    this.isActive = false;
    this.branchId = null;

    // Timers
    this.resultsInterval = null;
    this.heartbeatInterval = null;

    // WebSocket
    this.socket = null;
    this.socketRetryTimeout = null;
  }
  retrySocket() {
  if (this.socketRetryTimeout) return;

  this.socketRetryTimeout = setTimeout(() => {
    this.socketRetryTimeout = null;
    this.connectSocket();
  }, 2000);
  this.socket.onclose = () => {
  console.warn("WebSocket desconectado, reintentando...");
  this.retrySocket();
};

}


  /* -----------------------------
     REGISTRO DEL DISPOSITIVO
  ------------------------------*/
  async register() {
    const res = await fetch(`${API_BASE}/api/devices/register/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: this.deviceId }),
    });

    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Register failed: ${res.status} ${text}`);
    }

    const data = await res.json();

    this.activationCode = data.activation_code;
    localStorage.setItem("activation_code", this.activationCode);

    return data;
  }

  /* -----------------------------
     WEBSOCKET CON RECONEXIÓN
  ------------------------------*/
 connectSocket() {
  if (!this.activationCode) return;

  const wsUrl = `${wsBaseUrl()}/ws/device/${this.activationCode}/`;
  this.socket = new WebSocket(wsUrl);

  this.socket.onopen = () => {
    console.log("WebSocket conectado:", wsUrl);
  };

  this.socket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log("WS msg:", data);
    this.handleSocketMessage(data);
  };

  this.socket.onclose = () => {
    console.warn("WebSocket desconectado, reintentando...");
    this.retrySocket();
  };

  this.socket.onerror = () => {
    try { this.socket.close(); } catch (_) {}
  };
}


  /* -----------------------------
     MENSAJES DEL BACKEND
  ------------------------------*/
 handleSocketMessage(data) {
  // 1) Device asignado a branch
if (data.type === "device_assigned") {
  if (!data.branch_id) return; // <-- ignora el evento incompleto
  if (this.isActive && this.branchId === data.branch_id) return;
  this.activate(data.branch_id);
  return;
}


  // 2) Cambio de branch
  if (data.type === "branch_changed") {
    if (this.branchId !== data.branch_id) {
      this.branchId = data.branch_id;
      window.dispatchEvent(new CustomEvent("branchChanged", { detail: data }));
    }
    return;
  }
}

activate(branchId) {
  if (!branchId) return;

  // ✅ idempotente
  if (this.isActive && this.branchId === branchId) return;

  this.isActive = true;
  this.branchId = branchId;

  this.startHeartbeat();
  this.startResultsPolling();

  window.dispatchEvent(
    new CustomEvent("deviceActivated", { detail: { branchId } })
  );
  this.fetchResultsOnce?.();
}


  /* -----------------------------
     HEARTBEAT
  ------------------------------*/
  startHeartbeat() {
    if (this.heartbeatInterval) return;

    this.heartbeatInterval = setInterval(() => {
      fetch(`${API_BASE}/api/devices/heartbeat/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          device_id: this.deviceId,
          code: this.activationCode,
        }),
      }).catch(() => {
        // no rompas el timer por un fallo de red
      });
    }, 30000);
  }

  /* -----------------------------
     RESULTADOS
  ------------------------------*/
  startResultsPolling() {
    if (this.resultsInterval) return;

    this.resultsInterval = setInterval(async () => {
      try {
        const res = await fetch(
          `${API_BASE}/api/results/?code=${encodeURIComponent(this.activationCode)}`
        );

        if (!res.ok) return;

        const data = await res.json();

        window.dispatchEvent(
          new CustomEvent("resultsUpdated", { detail: data })
        );
      } catch (e) {
        console.warn("Error obteniendo resultados");
      }
    }, 60000);
  }
    async fetchResultsOnce() {
    try {
        const res = await fetch(
        `${API_BASE}/api/results/?code=${encodeURIComponent(this.activationCode)}`
        );
        if (!res.ok) return;
        const data = await res.json();
        window.dispatchEvent(new CustomEvent("resultsUpdated", { detail: data }));
    } catch (e) {}
    }

  /* -----------------------------
     FALLBACK: STATUS (OPCIONAL)
     Útil si el WS no envía evento por cualquier razón.
  ------------------------------*/
  async syncStatusOnce() {
    if (!this.activationCode) return;

    const res = await fetch(
      `${API_BASE}/api/devices/status/?code=${encodeURIComponent(this.activationCode)}`
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
    clearInterval(this.resultsInterval);
    clearInterval(this.heartbeatInterval);
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

export default DeviceManager;
