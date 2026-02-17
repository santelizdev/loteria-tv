import DeviceManager from "./deviceManager.js";

/**
 * ===========================
 * CONFIG
 * ===========================
 */
const DEVICE_ID = "TV_TEST_001";
const ROTATION_MS = 20_000;          // cada cuánto avanza página
const ANIMALITOS_REFRESH_MS = 60_000; // cada cuánto refrescamos animalitos por HTTP

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

// Slots 08:00..20:00
function buildSlots() {
  const slots = [];
  for (let h = 8; h <= 20; h++) slots.push(`${String(h).padStart(2, "0")}:00`);
  return slots;
}
const SLOTS = buildSlots();

// "08:05" -> "08:00" (redondeo hacia abajo a la hora)
function timeToHourSlot(hhmm) {
  const s = String(hhmm || "");
  const [hh] = s.split(":");
  const h = Number(hh);
  if (Number.isNaN(h)) return null;
  if (h < 8 || h > 20) return null;
  return `${String(h).padStart(2, "0")}:00`;
}

function computeProviders(rows) {
  const set = new Set();
  for (const r of rows) if (r.provider) set.add(r.provider);
  return Array.from(set).sort((a, b) => a.localeCompare(b));
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
    rows: [],
    providers: [],
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
    viewTriples.classList.add("view--active");
    viewAnimalitos.classList.remove("view--active");
  } else {
    viewAnimalitos.classList.add("view--active");
    viewTriples.classList.remove("view--active");
  }
}

/**
 * ===========================
 * NORMALIZERS
 * ===========================
 */
async function fetchAnimalitos() {
  try {
    const code = deviceManager.activationCode;
    if (!code) return;

    const resp = await fetch(
      `https://api.ssganador.lat/api/animalitos/?code=${encodeURIComponent(code)}`,
      { cache: "no-store" }
    );

    if (!resp.ok) {
      console.warn("Animalitos HTTP error:", resp.status);
      return;
    }

    const payload = await resp.json();

    state.animalitos.rows = normalizeAnimalitos(payload);
    state.animalitos.providers = computeProviders(state.animalitos.rows);

    console.log("Animalitos rows:", state.animalitos.rows.length);
    console.log("Animalitos providers:", state.animalitos.providers.length);

    if (state.view === "animalitos") {
      renderCurrentPage();
    }
  } catch (e) {
    console.warn("fetchAnimalitos falló:", e);
  }
}


function normalizeTriples(raw) {
  // backend puede venir como:
  // [{provider, time, number}]  o  [{provider, draw_time, winning_number}]
  const out = [];

  for (const r of raw || []) {
    const time = r.time ?? r.draw_time;                 // ✅ compat
    const number = r.number ?? r.winning_number;        // ✅ compat

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

    out.push({
      provider: r.provider,
      time: slot,
      number: String(r.number ?? "").padStart(2, "0"),
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
    // si hay más de un resultado en la misma hora, el último gana
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
      animal: r.animal,   // 🔥 este es el que renderizas
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
        <div class="col__time">${esc(t)}</div>
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

    // ✅ slot vacío
    if (!item) {
      return `
        <div class="col__row col__row--animal">
          <div class="col__time">${esc(t)}</div>
          <div class="col__num col__num--animal"><span class="col__empty">…</span></div>
          <div class="col__nameWrap">
            <div class="col__name"><span class="col__empty">…</span></div>
          </div>
        </div>
      `;
    }

    // ✅ slot con data (blindado)
    const num = item.number ?? "";
    const animal = item.animal ?? "";
    const img = item.image
      ? `<img class="col__icon" src="${esc(item.image)}" alt="" loading="lazy" />`
      : "";

    return `
      <div class="col__row col__row--animal">
        <div class="col__time">${esc(t)}</div>
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


function renderCurrentPage() {
  const isTriples = state.view === "triples";
  const dataset = isTriples ? state.triples : state.animalitos;

  const grid = isTriples ? triplesGrid : animalitosGrid;
  if (!grid) return;

  const start = state.pageIndex * 4;
  const pageProviders = dataset.providers.slice(start, start + 4);

  // Si se acabaron las páginas de esta vista
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

      return renderProviderColumnAnimalitos(
        providerName,
        rowsForProviderAnimalitos(dataset.rows, providerName)
      );
    })
    .join("");

  grid.innerHTML = html;
}


/**
 * ===========================
 * PAGER + PROGRESS
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
  if (state.timerId || state.rafId) return; // idempotente

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
 * ===========================
 * CLOCK (solo UI)
 * ===========================
 */
function startClock() {
  if (!vzClock) return;

  const upd = () => {
    const d = new Date();
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    const ss = String(d.getSeconds()).padStart(2, "0");
    vzClock.textContent = `${hh}:${mm}:${ss}`;
  };

  upd();
  setInterval(upd, 1000);
}


/**
 * ===========================
 * FETCH ANIMALITOS (HTTP)
 * ===========================
 */


/**
 * ===========================
 * EVENTS
 * ===========================
 */
window.addEventListener("deviceActivated", async () => {
  await fetchAnimalitos();
  setInterval(fetchAnimalitos, ANIMALITOS_REFRESH_MS);
});


// Triples vienen por DeviceManager (polling /api/results/)
window.addEventListener("resultsUpdated", (e) => {
  const raw = Array.isArray(e.detail) ? e.detail : [];
  console.log("Triples payload sample:", raw[0]);

  state.triples.rows = normalizeTriples(raw);
  state.triples.providers = computeProviders(state.triples.rows);

  console.log("Triples rows:", state.triples.rows.length);
  console.log("Triples providers:", state.triples.providers.length);

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

  // Register si no hay activation code
  //if (!deviceManager.activationCode) {
  //  await deviceManager.register();
 // }

  // WS
  deviceManager.connectSocket();

  // Status fallback
  try {
    await deviceManager.syncStatusOnce();
  } catch (_) {}

  // ✅ Render inmediato (sin depender del WS)
  await deviceManager.fetchResultsOnce();
  await fetchAnimalitos();

  // ✅ Arranca refresh periódico animalitos aunque no llegue deviceActivated
  setInterval(fetchAnimalitos, ANIMALITOS_REFRESH_MS);
})();

