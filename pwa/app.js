// ============================================
// File: pwa/app.js
// FIX v2: timeToHourSlot ahora parsea tanto "HH:MM" (24h) como "HH:MM AM/PM" (12h)
//         para que resultados PM no sean descartados silenciosamente.
// ============================================

import DeviceManager from "./deviceManager.js";

const DEVICE_ID = "TV_TEST_001";

// Rotación
const ROTATION_MS = 20000;
const ANIMALITOS_REFRESH_MS = 60000;
const ANIMALITOS_INTERVAL_MS = 15000;

// Slots internos siempre en 24h "HH:00" — solo para lógica, nunca se muestran directamente
const SLOTS = (() => {
  const out = [];
  for (let h = 8; h <= 20; h++) out.push(`${String(h).padStart(2, "0")}:00`);
  return out;
})();

const deviceManager = new DeviceManager(DEVICE_ID);

// DOM
const gridEl    = document.getElementById("grid");
const titleEl   = document.getElementById("resultsTitle");
const clockEl   = document.getElementById("vzClock");
const progressEl = document.getElementById("progressBar");
const logoEl    = document.getElementById("clientLogo");

function setClientLogo(src) {
  if (!logoEl) return;
  const url = String(src || "").trim();
  if (!url) { logoEl.style.display = "none"; logoEl.removeAttribute("src"); return; }
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

// Convierte slot interno "HH:00" (24h) a display "HH:MM AM/PM"
function slotTo12h(hhmm) {
  const [hh, mm] = String(hhmm || "").split(":");
  const h = Number(hh);
  const m = Number(mm);
  if (Number.isNaN(h) || Number.isNaN(m)) return hhmm;
  const ampm = h >= 12 ? "PM" : "AM";
  const h12 = ((h + 11) % 12) + 1;
  return `${String(h12).padStart(2, "0")}:${String(m).padStart(2, "0")} ${ampm}`;
}

// ─────────────────────────────────────────────────────────────────────────────
// FIX CRÍTICO: timeToHourSlot
//
// ANTES (roto): asumía que timeStr siempre era "HH:MM" (24h).
//   "07:15 PM" → split(":")[0] → "07" → 7 < 8 → null → DESCARTADO
//   "01:00 PM" → "01" → 1 < 8 → null → DESCARTADO
//
// AHORA (correcto): detecta formato 12h y convierte a 24h antes de evaluar.
//   "07:15 PM" → 19 → slot "19:00" ✓
//   "01:00 PM" → 13 → slot "13:00" ✓
//   "12:00 PM" → 12 → slot "12:00" ✓
//   "08:00 AM" →  8 → slot "08:00" ✓
//   "13:00"    → 13 → slot "13:00" ✓  (formato 24h también soportado)
// ─────────────────────────────────────────────────────────────────────────────
function timeToHourSlot(timeStr) {
  const s = String(timeStr || "").trim();
  if (!s) return null;

  // Detectar si viene en formato 12h: "HH:MM AM" o "HH:MM PM"
  const match12 = s.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/i);
  if (match12) {
    let h = Number(match12[1]);
    const meridiem = match12[3].toUpperCase();
    // Conversión estándar 12h → 24h
    if (meridiem === "AM" && h === 12) h = 0;
    if (meridiem === "PM" && h !== 12) h += 12;
    if (h < 8 || h > 20) return null;
    return `${String(h).padStart(2, "0")}:00`;
  }

  // Formato 24h: "HH:MM" o "HH:MM:SS"
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
    clockEl.textContent = `${String(h12).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")} ${ampm}`;
  };
  tick();
  setInterval(tick, 1000);
}

// ---------- STATE ----------
const state = {
  deviceCode: "----",
  mode: "triples",
  pageIndex: 0,
  triplesRows: [],
  triplesProviders: [],
  animalitosTodayRows: [],
  animalitosYesterdayRows: [],
  animalitosProviders: [],
  animalitosDay: "today",
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
function renderDeviceCode(code) {
  const el = document.getElementById("deviceCode");
  if (el) el.textContent = code ? String(code).toUpperCase() : "----";
}

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

  const html = group.map((p) => {
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
  }).join("");

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

  const html = group.map((p) => {
    const byTime = mapRowsByProvider(rows, p);
    const rowsHtml = SLOTS.map((t) => {
      const rec = byTime.get(t);
      const img    = rec?.image  ? `<img class="col__icon" src="${esc(rec.image)}" alt="" loading="lazy" />` : "";
      const animal = rec?.animal ? esc(rec.animal) : `<span class="col__empty">…</span>`;
      const num    = rec?.number ? esc(rec.number) : `<span class="col__empty">…</span>`;
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
  }).join("");

  gridEl.innerHTML = html;
}

function render() {
  if (state.mode === "triples") renderTriplesPage();
  else renderAnimalitosGroup(state.animalitosDay);
}

// ---------- DATA FETCH ----------
function getApiBase() {
  return window.__APP_CONFIG__?.API_BASE || "https://api.ssganador.lat";
}

const BUSINESS_TZ = "America/Caracas";

function getDateISO(offset) {
  const now = new Date();
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: BUSINESS_TZ,
    year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(now);
  const yyyy = parts.find(p => p.type === "year").value;
  const mm   = parts.find(p => p.type === "month").value;
  const dd   = parts.find(p => p.type === "day").value;
  const base = new Date(`${yyyy}-${mm}-${dd}T00:00:00`);
  base.setDate(base.getDate() + offset);
  const y = base.getFullYear();
  const m = String(base.getMonth() + 1).padStart(2, "0");
  const d = String(base.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

async function fetchAnimalitosByDate(dateISO) {
  const code = deviceManager.activationCode || localStorage.getItem("activation_code") || "DEV";
  const api  = getApiBase();
  const url  = `${api}/api/animalitos/?code=${encodeURIComponent(code)}&date=${encodeURIComponent(dateISO)}`;
  const res  = await fetch(url, { cache: "no-store" });
  if (!res.ok) return [];
  return normalizeAnimalitos(await res.json());
}

async function refreshAnimalitosCaches() {
  const [todayRows, yRows] = await Promise.all([
    fetchAnimalitosByDate(getDateISO(0)),
    fetchAnimalitosByDate(getDateISO(-1)),
  ]);
  state.animalitosTodayRows     = todayRows;
  state.animalitosYesterdayRows = yRows;
  state.animalitosProviders     = computeProviders([...todayRows, ...yRows]);
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

  const raf = () => { setProgress(tickStart, durationMs); rafTimer = requestAnimationFrame(raf); };
  rafTimer = requestAnimationFrame(raf);

  rotationTimer = setInterval(() => {
    tickStart = Date.now();

    if (state.mode === "triples") {
      const groups = chunk(state.triplesProviders, 4);
      state.pageIndex += 1;
      if (state.pageIndex >= groups.length) {
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
  state.triplesRows     = normalizeTriples(raw);
  state.triplesProviders = computeProviders(state.triplesRows);
  if (state.mode === "triples") render();
});

window.addEventListener("deviceActivated", async () => {
  await refreshAnimalitosCaches();
});

// ---------- BOOT ----------
(async () => {
  startClock();

  // Mostrar código desde URL/localStorage de inmediato
  renderDeviceCode(
    localStorage.getItem("activation_code") ||
    new URL(location.href).searchParams.get("code")
  );

  const code = await deviceManager.ensureActivationCode();
  state.deviceCode = String(code || "----").toUpperCase();
  renderDeviceCode(state.deviceCode);

  render();

  deviceManager.connectSocket();
  await deviceManager.syncStatusOnce();
  await deviceManager.fetchResultsOnce();

  await refreshAnimalitosCaches();
  setInterval(refreshAnimalitosCaches, ANIMALITOS_REFRESH_MS);

  setClientLogo(window.__APP_CONFIG__?.CLIENT_LOGO || "");

  render();
  startRotation(ROTATION_MS);
})().catch((e) => {
  console.error("BOOT ERROR:", e);
  if (gridEl) gridEl.innerHTML = `<div style="padding:16px;">Error: ${esc(e.message || e)}</div>`;
});