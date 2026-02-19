/**
 * ===========================
 * CONFIG
 * ===========================
 */
const DEVICE_ID = "TV_TEST_001";

const ROTATION_MS = 20_000;            // triples: cada cuánto avanza página
const ANIMALITOS_REFRESH_MS = 60_000;  // animalitos: cada cuánto refrescamos cache interno
const ANIMALITOS_INTERVAL_MS = 15_000; // animalitos: HOY 15s + AYER 15s

const deviceManager = new DeviceManager(DEVICE_ID);
/**
 * ===========================
 * DOM
 * ===========================
 */
const triplesGrid = document.getElementById("triplesGrid");
const animalitosGrid = document.getElementById("animalitosGrid");

const viewTriples = document.getElementById("viewTriples");
const viewAnimalitos = document.getElementById("viewAnimalitos");

const progressBar = document.getElementById("progressBar");
const vzClock = document.getElementById("vzClock");

// Banner/título (debe existir en tu HTML)
const resultsBanner = document.getElementById("resultsBanner"); // "RESULTADOS HOY/AYER"
const liveBadge = document.getElementById("liveBadge");         // si tienes un "EN VIVO" con id

/**
 * ===========================
 * HELPERS
 * ===========================
 */
function esc(v) {
  return String(v ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function buildSlots() {
  const slots = [];
  for (let h = 8; h <= 20; h++) slots.push(`${String(h).padStart(2, "0")}:00`);
  return slots;
}
const SLOTS = buildSlots();

// "08:05" -> "08:00" (redondeo hacia abajo a la hora)
function parseHourFromTimeString(t) {
  if (!t) return null;
  const s = String(t).trim();
  // Accept "HH:MM", "H:MM", "HH:MM AM", "HH:MM PM"
  const m = s.match(/^(\d{1,2}):(\d{2})(?:\s*([AaPp][Mm]))?$/);
  if (!m) return null;

  let hh = parseInt(m[1], 10);
  const ampm = m[3] ? m[3].toUpperCase() : null;

  if (ampm) {
    // 12-hour -> 24-hour
    if (ampm === "AM") {
      if (hh === 12) hh = 0;
    } else if (ampm === "PM") {
      if (hh !== 12) hh += 12;
    }
  }
  if (Number.isNaN(hh)) return null;
  return hh;
}

function timeToHourSlot(timeStr) {
  const h = parseHourFromTimeString(timeStr);
  if (h === null) return null;
  // Horas visibles en el tablero: 08:00 -> 20:00
  if (h < 8 || h > 20) return null;
  return h;
}

function computeProviders(rows) {
  const set = new Set();
  for (const r of rows) if (r.provider) set.add(r.provider);
  return Array.from(set).sort((a, b) => a.localeCompare(b));
}

function chunk(arr, size) {
  const out = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

// YYYY-MM-DD con offset en días (0 = hoy, -1 = ayer)
function getDateISO(dayOffset) {
  const d = new Date();
  d.setDate(d.getDate() + dayOffset);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

// 12h con AM/PM (para el reloj)
function to12hFull(dateObj) {
  const h = dateObj.getHours();
  const m = dateObj.getMinutes();
  const s = dateObj.getSeconds();
  const ampm = h >= 12 ? "PM" : "AM";
  const h12 = ((h + 11) % 12) + 1;
  return `${String(h12).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")} ${ampm}`;
}

// (Opcional) mostrar slots en 12h en tabla: "08:00" -> "08:00 AM"
function slotTo12h(hhmm) {
  const [hh, mm] = String(hhmm || "").split(":");
  const h = Number(hh);
  const m = Number(mm);
  if (Number.isNaN(h) || Number.isNaN(m)) return hhmm;
  const ampm = h >= 12 ? "PM" : "AM";
  const h12 = ((h + 11) % 12) + 1;
  return `${String(h12).padStart(2, "0")}:${String(m).padStart(2, "0")} ${ampm}`;
}

function setBanner(text) {
  if (resultsBanner) resultsBanner.textContent = text;
}

/**
 * API base: si estás sirviendo la PWA en 5173/8080, backend vive en 8000
 */
function getApiBase() {
  if (location.port === "8080" || location.port === "5173") return "http://127.0.0.1:8000";
  return "https://api.ssganador.lat";
}

/**
 * ===========================
 * STATE
 * ===========================
 */
const state = {
  view: "triples", // "triples" | "animalitos"
  pageIndex: 0,
  startTs: 0,
  timerId: null,
  rafId: null,

  triples: {
    rows: [],
    providers: [],
  },

  animalitos: {
    rows: [],       // cache "hoy" (sin fecha)
    providers: [],
  },

  // Rotación HOY/AYER (solo para animalitos)
  animalitosRotation: {
    enabled: false,
    intervalId: null,
    mode: "today",     // "today" | "yesterday"
    groupIndex: 0,
    providerGroups: [],
    startTs: 0,         // para progress 15s
    lastRenderedDate: null,
  },
};

/**
 * ===========================
 * VIEW SWITCH (animación)
 * ===========================
 */
function setActiveView(next) {
  state.view = next;

  if (next === "triples") {
    viewTriples?.classList.add("view--active");
    viewAnimalitos?.classList.remove("view--active");
  } else {
    viewAnimalitos?.classList.add("view--active");
    viewTriples?.classList.remove("view--active");
  }
}

/**
 * ===========================
 * NORMALIZERS
 * ===========================
 */
function normalizeTriples(raw) {
  const out = [];

  for (const r of raw || []) {
    const time = r.time ?? r.draw_time;
    const number = r.number ?? r.winning_number;

    const slot = timeToHourSlot(time);
    if (!slot) continue;

    out.push({
      provider: r.provider,
      time: slot,
      number: String(number ?? "").trim(),
    });
  }

  return out;
}

function normalizeAnimalitos(raw) {
  const out = [];

  for (const r of raw || []) {
    const slot = timeToHourSlot(r.time);
    if (!slot) continue;

    const rawNum = String(r.number ?? "").trim(); // ✅ NO convertir a int / zfill

    out.push({
      provider: r.provider,
      time: slot,
      number: rawNum,
      animal: (r.animal ?? r.name ?? "").trim(),
      image: r.image ?? "",
    });
  }

  return out;
}

/**
 * ===========================
 * LOOKUPS
 * ===========================
 */
function rowsForProviderTriples(rows, provider) {
  const map = new Map(); // slot -> number
  for (const r of rows) {
    if (r.provider !== provider) continue;
    map.set(r.time, r.number);
  }
  return map;
}

function rowsForProviderAnimalitos(rows, provider) {
  const map = new Map();
  for (const r of rows) {
    if (r.provider !== provider) continue;
    map.set(r.time, {
      number: r.number,
      animal: r.animal,
      image: r.image,
    });
  }
  return map;
}

/**
 * ===========================
 * RENDER
 * ===========================
 */
function renderProviderColumnTriples(providerName, rowsMap) {
  const body = SLOTS.map((t) => {
    const num = rowsMap.get(t);
    return `
      <div class="col__row">
        <div class="col__time">${esc(slotTo12h(t))}</div>
        <div class="col__num">${num ? esc(num) : `<span class="col__empty">…</span>`}</div>
      </div>
    `;
  }).join("");

  return `
    <article class="col">
      <div class="col__head">
        <div class="col__title">${esc(providerName)}</div>
      </div>
      <div class="col__body">${body}</div>
    </article>
  `;
}

function renderProviderColumnAnimalitos(providerName, rowsMap) {
  const body = SLOTS.map((t) => {
    const item = rowsMap.get(t);

    if (!item) {
      return `
        <div class="col__row col__row--animal">
          <div class="col__time">${esc(slotTo12h(t))}</div>
          <div class="col__num col__num--animal"><span class="col__empty">…</span></div>
          <div class="col__nameWrap">
            <div class="col__name"><span class="col__empty">…</span></div>
          </div>
        </div>
      `;
    }

    const num = item.number ?? "";
    const animal = item.animal ?? "";
    const img = item.image
      ? `<img class="col__icon" src="${esc(item.image)}" alt="" loading="lazy" />`
      : "";

    return `
      <div class="col__row col__row--animal">
        <div class="col__time">${esc(slotTo12h(t))}</div>
        <div class="col__num col__num--animal">${esc(num)}</div>
        <div class="col__nameWrap">
          <div class="col__name">${esc(animal)}</div>
          ${img}
        </div>
      </div>
    `;
  }).join("");

  return `
    <article class="col">
      <div class="col__head">
        <div class="col__title">${esc(providerName)}</div>
      </div>
      <div class="col__body">${body}</div>
    </article>
  `;
}

/**
 * Render estándar (triples) por página de 4 providers
 */
function renderCurrentPage() {
  const isTriples = state.view === "triples";
  const dataset = isTriples ? state.triples : state.animalitos;

  const grid = isTriples ? triplesGrid : animalitosGrid;
  if (!grid) return;

  const start = state.pageIndex * 4;
  const pageProviders = dataset.providers.slice(start, start + 4);

  if (!pageProviders.length && dataset.providers.length) {
    state.pageIndex = 0;

    // alternar vista
    setActiveView(isTriples ? "animalitos" : "triples");
    return renderCurrentPage();
  }

  const html = pageProviders
    .map((providerName) => {
      if (isTriples) {
        return renderProviderColumnTriples(
          providerName,
          rowsForProviderTriples(dataset.rows, providerName)
        );
      }

      // animalitos (modo "normal"): usa cache state.animalitos.rows
      return renderProviderColumnAnimalitos(
        providerName,
        rowsForProviderAnimalitos(dataset.rows, providerName)
      );
    })
    .join("");

  grid.innerHTML = html;
}

/**
 * Render animalitos para un grupo específico (4 providers) con data ya filtrada
 */
function renderAnimalitosGroup(rows, providersInGroup) {
  if (!animalitosGrid) return;

  const html = providersInGroup
    .map((providerName) => {
      return renderProviderColumnAnimalitos(
        providerName,
        rowsForProviderAnimalitos(rows, providerName)
      );
    })
    .join("");

  animalitosGrid.innerHTML = html;
}

/**
 * ===========================
 * PAGER + PROGRESS (triples)
 * ===========================
 */
function stopPager() {
  if (state.timerId) clearInterval(state.timerId);
  state.timerId = null;

  if (state.rafId) cancelAnimationFrame(state.rafId);
  state.rafId = null;

  state.startTs = 0;
}

function startPager() {
  if (state.timerId || state.rafId) return;

  state.startTs = Date.now();

  const tick = () => {
    if (progressBar && state.startTs) {
      const elapsed = Date.now() - state.startTs;
      const pct = Math.min(100, (elapsed / ROTATION_MS) * 100);
      progressBar.style.width = `${pct}%`;
    }
    state.rafId = requestAnimationFrame(tick);
  };
  state.rafId = requestAnimationFrame(tick);

  state.timerId = setInterval(() => {
    state.pageIndex += 1;
    state.startTs = Date.now();
    renderCurrentPage();
  }, ROTATION_MS);
}

/**
 * Progress bar para animalitos (15s)
 */
function startAnimalitosProgress() {
  const rot = state.animalitosRotation;
  rot.startTs = Date.now();

  const tick = () => {
    if (!rot.enabled) return;

    if (progressBar && rot.startTs) {
      const elapsed = Date.now() - rot.startTs;
      const pct = Math.min(100, (elapsed / ANIMALITOS_INTERVAL_MS) * 100);
      progressBar.style.width = `${pct}%`;
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

/**
 * ===========================
 * CLOCK (UI)
 * ===========================
 */
function startClock() {
  if (!vzClock) return;

  const upd = () => {
    const d = new Date();
    vzClock.textContent = to12hFull(d);
  };

  upd();
  setInterval(upd, 1000);
}

/**
 * ===========================
 * FETCH ANIMALITOS (HTTP)
 * ===========================
 */

// Refresh "hoy" (sin fecha) para cache local state.animalitos
async function refreshAnimalitosTodayCache() {
  try {
    const code = deviceManager.activationCode;
    if (!code) return;

    const apiBase = getApiBase();
    const resp = await fetch(
      `${apiBase}/api/animalitos/?code=${encodeURIComponent(code)}`,
      { cache: "no-store" }
    );

    if (!resp.ok) {
      console.warn("Animalitos HTTP error:", resp.status);
      return;
    }

    const payload = await resp.json();

    state.animalitos.rows = normalizeAnimalitos(payload);
    state.animalitos.providers = computeProviders(state.animalitos.rows);

    // actualiza grupos para rotación
    state.animalitosRotation.providerGroups = chunk(state.animalitos.providers, 4);

    // si estás en vista animalitos y NO está activa rotación, render normal
    if (state.view === "animalitos" && !state.animalitosRotation.enabled) {
      renderCurrentPage();
    }
  } catch (e) {
    console.warn("refreshAnimalitosTodayCache falló:", e);
  }
}

// Fetch animalitos por fecha (HOY/AYER)
async function fetchAnimalitosByDate(dateISO) {
  const code = deviceManager.activationCode;
  if (!code) return [];

  const apiBase = getApiBase();
  const url = `${apiBase}/api/animalitos/?code=${encodeURIComponent(code)}&date=${encodeURIComponent(dateISO)}`;

  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`Animalitos HTTP ${res.status}`);
  const payload = await res.json();
  return normalizeAnimalitos(payload);
}

/**
 * ===========================
 * ROTACIÓN ANIMALITOS HOY/AYER (15s + 15s)
 * ===========================
 */
function stopAnimalitosRotation() {
  const rot = state.animalitosRotation;
  rot.enabled = false;
  if (rot.intervalId) clearInterval(rot.intervalId);
  rot.intervalId = null;
}

async function animalitosTick() {
  const rot = state.animalitosRotation;
  if (!rot.providerGroups.length) return;

  const providersInGroup = rot.providerGroups[rot.groupIndex] || [];
  if (!providersInGroup.length) return;

  const dateISO = rot.mode === "today" ? getDateISO(0) : getDateISO(-1);

  // Banner
  setBanner(rot.mode === "today" ? "RESULTADOS HOY" : "RESULTADOS AYER");

  // Live badge si existe
  if (liveBadge) liveBadge.textContent = "EN VIVO";

  try {
    const rows = await fetchAnimalitosByDate(dateISO);

    // filtra solo providers del grupo
    const filtered = rows.filter(x => providersInGroup.includes(x.provider));

    // renderiza SOLO animalitos grid
    renderAnimalitosGroup(filtered, providersInGroup);
  } catch (e) {
    console.error("animalitosTick error:", e);
  }

  // progress 15s
  startAnimalitosProgress();

  // alterna HOY/AYER, y al terminar AYER avanza grupo
  if (rot.mode === "today") {
    rot.mode = "yesterday";
  } else {
    rot.mode = "today";
    rot.groupIndex = (rot.groupIndex + 1) % rot.providerGroups.length;
  }
}

function startAnimalitosRotation() {
  const rot = state.animalitosRotation;

  // solo rota si estás en vista animalitos
  if (state.view !== "animalitos") return;

  rot.enabled = true;
  rot.groupIndex = 0;
  rot.mode = "today";

  // asegura grupos (por si todavía no llegaron providers)
  rot.providerGroups = chunk(state.animalitos.providers, 4);

  // tick inmediato + interval
  animalitosTick();
  rot.intervalId = setInterval(animalitosTick, ANIMALITOS_INTERVAL_MS);
}

/**
 * ===========================
 * EVENTS
 * ===========================
 */
window.addEventListener("deviceActivated", async () => {
  await refreshAnimalitosTodayCache();
  setInterval(refreshAnimalitosTodayCache, ANIMALITOS_REFRESH_MS);
});

// Triples vienen por DeviceManager (polling /api/results/)
window.addEventListener("resultsUpdated", (e) => {
  const raw = Array.isArray(e.detail) ? e.detail : [];

  state.triples.rows = normalizeTriples(raw);
  state.triples.providers = computeProviders(state.triples.rows);

  if (!state.triples.providers.length) return;

  if (state.view === "triples") renderCurrentPage();
  startPager();
});

/**
 * ===========================
 * BOOT
 * ===========================
 */
(async () => {
  startClock();
  setActiveView("triples");
  setBanner("EN VIVO"); // banner inicial (si quieres)

  // WS
  deviceManager.connectSocket();

  // Status fallback
  try {
    await deviceManager.syncStatusOnce();
  } catch (_) {}

  // Render inmediato
  await deviceManager.fetchResultsOnce();

  // precarga animalitos (cache hoy)
  await refreshAnimalitosTodayCache();

  // refresco periódico cache hoy
  setInterval(refreshAnimalitosTodayCache, ANIMALITOS_REFRESH_MS);

  // cuando cambies manualmente a animalitos, arranca rotación
  // (si tu UI cambia sola, lo activamos cuando alternes vista)
  // Aquí lo dejamos listo: cuando el pager cambie a animalitos, se inicia
})();

/**
 * IMPORTANTE:
 * Tu pager actual alterna vistas automáticamente cuando se acaban páginas.
 * Cuando entramos a animalitos, queremos rotación HOY/AYER, NO el pager normal.
 *
 * Solución mínima: intercepta el cambio de vista en renderCurrentPage().
 * Como no vamos a reescribir renderCurrentPage(), hacemos este "watch" simple:
 */
setInterval(() => {
  if (state.view === "animalitos") {
    // detener pager triples para no pelear por progress
    stopPager();

    // iniciar rotación si no está corriendo
    if (!state.animalitosRotation.enabled) startAnimalitosRotation();
  } else {
    // si volvimos a triples, apagar rotación animalitos
    if (state.animalitosRotation.enabled) stopAnimalitosRotation();
  }
}, 500);
