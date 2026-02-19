// ============================================
// File: pwa/app.js
// Renders into: #grid, #resultsTitle, #vzClock, #progressBar
// ============================================

import DeviceManager from "./deviceManager.js";

const DEVICE_ID = "TV_TEST_001";

// Rotación
const ROTATION_MS = 20_000; // cambio de página/grupo
const ANIMALITOS_REFRESH_MS = 60_000; // refrescar cache hoy
const ANIMALITOS_INTERVAL_MS = 15_000; // alterna HOY/AYER

// Slots 08:00-20:00
const SLOTS = (() => {
  const out = [];
  for (let h = 8; h <= 20; h++) out.push(`${String(h).padStart(2, "0")}:00`);
  return out;
})();

const deviceManager = new DeviceManager(DEVICE_ID);

// DOM
const gridEl = document.getElementById("grid");
const titleEl = document.getElementById("resultsTitle");
const clockEl = document.getElementById("vzClock");
const progressEl = document.getElementById("progressBar");

const logoEl = document.getElementById("clientLogo");

function setClientLogo(src) {
  if (!logoEl) return;
  const url = String(src || "").trim();
  if (!url) {
    logoEl.style.display = "none";
    logoEl.removeAttribute("src");
    return;
  }
  logoEl.src = url;
  logoEl.style.display = "block";
}

function esc(v) {
  return String(v ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function slotTo12h(hhmm) {
  const [hh, mm] = String(hhmm || "").split(":");
  const h = Number(hh);
  const m = Number(mm);
  if (Number.isNaN(h) || Number.isNaN(m)) return hhmm;
  const ampm = h >= 12 ? "PM" : "AM";
  const h12 = ((h + 11) % 12) + 1;
  return `${String(h12).padStart(2, "0")}:${String(m).padStart(2, "0")} ${ampm}`;
}

function timeToHourSlot(timeStr) {
  const s = String(timeStr || "");
  const hh = Number(s.split(":")[0]);
  if (Number.isNaN(hh)) return null;
  if (hh < 8 || hh > 20) return null;
  return `${String(hh).padStart(2, "0")}:00`;
}

function chunk(arr, size) {
  const out = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

function setProgress(startTs, durationMs) {
  if (!progressEl) return;
  const elapsed = Date.now() - startTs;
  const pct = Math.min(100, (elapsed / durationMs) * 100);
  progressEl.style.width = `${pct}%`;
}

function startClock() {
  if (!clockEl) return;
  const tick = () => {
    const d = new Date();
    const h = d.getHours();
    const m = d.getMinutes();
    const s = d.getSeconds();
    const ampm = h >= 12 ? "PM" : "AM";
    const h12 = ((h + 11) % 12) + 1;
    clockEl.textContent = `${String(h12).padStart(2, "0")}:${String(m).padStart(
      2,
      "0"
    )}:${String(s).padStart(2, "0")} ${ampm}`;
  };
  tick();
  setInterval(tick, 1000);
}

// ---------- STATE ----------
state.deviceCode = "----";
const state = {
  mode: "triples", // "triples" | "animalitos"
  pageIndex: 0,

  // Triples
  triplesRows: [],
  triplesProviders: [],

  // Animalitos caches
  animalitosTodayRows: [],
  animalitosYesterdayRows: [],
  animalitosProviders: [],

  // Animalitos view alternation
  animalitosDay: "today", // "today" | "yesterday"
  animalitosGroupIndex: 0,
};

let rotationTimer = null;
let rafTimer = null;
let tickStart = 0;

// ---------- NORMALIZERS ----------
function normalizeTriples(raw) {
  const out = [];
  for (const r of raw || []) {
    const slot = timeToHourSlot(r.time ?? r.draw_time);
    if (!slot) continue;
    out.push({
      provider: r.provider,
      time: slot,
      number: String(r.number ?? r.winning_number ?? "").trim(),
    });
  }
  return out;
}

function normalizeAnimalitos(raw) {
  const out = [];
  for (const r of raw || []) {
    const slot = timeToHourSlot(r.time);
    if (!slot) continue;

    // tu API devuelve animalitos con animal/image, pero algunos providers (tipo La Ruca) no traen animal.
    out.push({
      provider: r.provider,
      time: slot,
      number: String(r.number ?? "").trim(),
      animal: String(r.animal ?? "").trim(),
      image: String(r.image ?? "").trim(),
    });
  }
  return out;
}

function computeProviders(rows) {
  const s = new Set();
  for (const r of rows) if (r.provider) s.add(r.provider);
  return Array.from(s).sort((a, b) => a.localeCompare(b));
}

function mapRowsByProvider(rows, provider) {
  const m = new Map();
  for (const r of rows) {
    if (r.provider !== provider) continue;
    m.set(r.time, r);
  }
  return m;
}

// ---------- RENDER ----------
function renderTriplesPage() {
  if (!gridEl) return;

  if (titleEl) titleEl.textContent = "RESULTADOS HOY (TRIPLES)";

  const providers = state.triplesProviders;
  if (!providers.length) {
    gridEl.innerHTML = `<div style="padding:16px;">Sin resultados.</div>`;
    return;
  }

  const groups = chunk(providers, 4);
  const group = groups[state.pageIndex] || groups[0];
  if (!group) return;

  const html = group
    .map((p) => {
      const byTime = mapRowsByProvider(state.triplesRows, p);
      const rowsHtml = SLOTS.map((t) => {
        const rec = byTime.get(t);
        return `
          <div class="col__row">
            <div class="col__time">${esc(slotTo12h(t))}</div>
            <div class="col__num">${rec?.number ? esc(rec.number) : `<span class="col__empty">…</span>`}</div>
          </div>
        `;
      }).join("");

      return `
        <article class="col">
          <div class="col__head"><div class="col__title">${esc(p)}</div></div>
          <div class="col__body">${rowsHtml}</div>
        </article>
      `;
    })
    .join("");

  gridEl.innerHTML = html;
}

function renderAnimalitosGroup(day) {
  if (!gridEl) return;

  const rows = day === "today" ? state.animalitosTodayRows : state.animalitosYesterdayRows;

  if (titleEl) titleEl.textContent = day === "today" ? "RESULTADOS HOY (ANIMALITOS)" : "RESULTADOS AYER (ANIMALITOS)";

  const providers = state.animalitosProviders;
  if (!providers.length) {
    gridEl.innerHTML = `<div style="padding:16px;">Sin animalitos.</div>`;
    return;
  }

  const groups = chunk(providers, 4);
  const group = groups[state.animalitosGroupIndex] || groups[0];
  if (!group) return;

  const html = group
    .map((p) => {
      const byTime = mapRowsByProvider(rows, p);
      const rowsHtml = SLOTS.map((t) => {
        const rec = byTime.get(t);
        const img = rec?.image ? `<img class="col__icon" src="${esc(rec.image)}" alt="" loading="lazy" />` : "";
        const animal = rec?.animal ? esc(rec.animal) : `<span class="col__empty">…</span>`;
        const num = rec?.number ? esc(rec.number) : `<span class="col__empty">…</span>`;

        return `
          <div class="col__row col__row--animal">
            <div class="col__time">${esc(slotTo12h(t))}</div>
            <div class="col__num col__num--animal">${num}</div>
            <div class="col__nameWrap">
              <div class="col__name">${animal}</div>
              ${img}
            </div>
          </div>
        `;
      }).join("");

      return `
        <article class="col">
          <div class="col__head"><div class="col__title">${esc(p)}</div></div>
          <div class="col__body">${rowsHtml}</div>
        </article>
      `;
    })
    .join("");

  gridEl.innerHTML = html;
}

function render() {
  if (state.mode === "triples") renderTriplesPage();
  else renderAnimalitosGroup(state.animalitosDay);
}

// ---------- DATA FETCH (ANIMALITOS) ----------
function getApiBase() {
  return window.__APP_CONFIG__?.API_BASE || "https://api.ssganador.lat";
}

const BUSINESS_TZ = "America/Caracas"; // o "America/Santiago" si tu regla fuese Chile

function getDateISO(offset) {
  const now = new Date();
  // Convertimos 'now' al "día calendario" en la zona BUSINESS_TZ
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: BUSINESS_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);

  const yyyy = parts.find(p => p.type === "year").value;
  const mm   = parts.find(p => p.type === "month").value;
  const dd   = parts.find(p => p.type === "day").value;

  // date base en la TZ negocio (sin horas)
  const base = new Date(`${yyyy}-${mm}-${dd}T00:00:00`);

  base.setDate(base.getDate() + offset);
  const y = base.getFullYear();
  const m = String(base.getMonth() + 1).padStart(2, "0");
  const d = String(base.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}


async function fetchAnimalitosByDate(dateISO) {
  const code = deviceManager.activationCode || localStorage.getItem("activation_code") || "DEV";
  const api = getApiBase();
  const url = `${api}/api/animalitos/?code=${encodeURIComponent(code)}&date=${encodeURIComponent(dateISO)}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) return [];
  const payload = await res.json();
  return normalizeAnimalitos(payload);
}

async function refreshAnimalitosCaches() {
  const todayISO = getDateISO(0);
  const yISO = getDateISO(-1);

  const [todayRows, yRows] = await Promise.all([
    fetchAnimalitosByDate(todayISO),
    fetchAnimalitosByDate(yISO),
  ]);

  state.animalitosTodayRows = todayRows;
  state.animalitosYesterdayRows = yRows;

  // Providers list: usa la unión de ambos días para no “encoger” grupos
  const providers = computeProviders([...todayRows, ...yRows]);
  state.animalitosProviders = providers;
}

// ---------- ROTATION ----------
function stopRotation() {
  if (rotationTimer) clearInterval(rotationTimer);
  rotationTimer = null;
  if (rafTimer) cancelAnimationFrame(rafTimer);
  rafTimer = null;
}

function startRotation(durationMs) {
  stopRotation();
  tickStart = Date.now();

  const raf = () => {
    setProgress(tickStart, durationMs);
    rafTimer = requestAnimationFrame(raf);
  };
  rafTimer = requestAnimationFrame(raf);

  rotationTimer = setInterval(() => {
    tickStart = Date.now();

    if (state.mode === "triples") {
      const groups = chunk(state.triplesProviders, 4);
      state.pageIndex += 1;

      if (state.pageIndex >= groups.length) {
        // cambia a animalitos
        state.mode = "animalitos";
        state.pageIndex = 0;
        state.animalitosDay = "today";
        state.animalitosGroupIndex = 0;
        render();
        startRotation(ANIMALITOS_INTERVAL_MS);
        return;
      }

      render();
      return;
    }

    // animalitos: alterna HOY/AYER y avanza grupo cada ciclo completo
    if (state.animalitosDay === "today") {
      state.animalitosDay = "yesterday";
    } else {
      state.animalitosDay = "today";
      const groups = chunk(state.animalitosProviders, 4);
      state.animalitosGroupIndex = (state.animalitosGroupIndex + 1) % Math.max(1, groups.length);
    }

    render();
  }, durationMs);
}

// ---------- EVENTS ----------
window.addEventListener("resultsUpdated", (e) => {
  const raw = Array.isArray(e.detail) ? e.detail : [];
  state.triplesRows = normalizeTriples(raw);
  state.triplesProviders = computeProviders(state.triplesRows);

  // primer render inmediato si estamos en triples
  if (state.mode === "triples") render();
});

window.addEventListener("deviceActivated", async () => {
  // en tu alpha local, esto puede que no se dispare; igual hacemos refresh por boot
  await refreshAnimalitosCaches();
});

// ---------- BOOT ----------
(async () => {
  startClock();

  renderDeviceCode(deviceManager.activationCode);

  // SHOW COD-ACTIVACION IN HTML
function renderDeviceCode(code) {
  const el = document.getElementById("deviceCode");
  if (el) el.textContent = code ? String(code).toUpperCase() : "----";
}

// pinta lo que haya YA (URL o localStorage)
renderDeviceCode(localStorage.getItem("activation_code") || new URL(location.href).searchParams.get("code"));

const code = await deviceManager.ensureActivationCode();
state.deviceCode = code ? String(code).toUpperCase() : "----";
render(); // asegura que el render lo pinte


  // 2) WS + fallback status + primera carga
  deviceManager.connectSocket();
  await deviceManager.syncStatusOnce();
  await deviceManager.fetchResultsOnce();

  await refreshAnimalitosCaches();
  setInterval(refreshAnimalitosCaches, ANIMALITOS_REFRESH_MS);

  setClientLogo(window.__APP_CONFIG__?.CLIENT_LOGO || "");

  // Render inicial
  render();
  startRotation(ROTATION_MS);
})().catch((e) => {
  console.error("BOOT ERROR:", e);
  if (gridEl) gridEl.innerHTML = `<div style="padding:16px;">Error: ${esc(e.message || e)}</div>`;
});

