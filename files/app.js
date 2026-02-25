// ============================================
// File: pwa/app.js
// FIX Android 9 (WebView ~Chromium 69):
//   - Eliminado ?? (nullish coalescing) → operador ternario
//   - Eliminado ?. (optional chaining) → acceso condicional explícito
//   - Eliminado import ES module → DeviceManager como global (ver deviceManager.js)
//   - Fix bug: ctx era usada fuera del scope del IIFE
// ============================================

// DeviceManager ya no se importa; se carga como <script> en index.html
// y queda disponible como global window.DeviceManager

// Rotación
var ROTATION_MS = 20000;
var ANIMALITOS_REFRESH_MS = 60000;
var ANIMALITOS_INTERVAL_MS = 15000;

// Slots internos siempre en 24h "HH:00"
var SLOTS = (function () {
  var out = [];
  for (var h = 8; h <= 20; h++) out.push((h < 10 ? "0" : "") + h + ":00");
  return out;
})();

var deviceManager = new DeviceManager(typeof DEVICE_ID !== "undefined" ? DEVICE_ID : null);

// DOM
var gridEl     = document.getElementById("grid");
var titleEl    = document.getElementById("resultsTitle");
var clockEl    = document.getElementById("vzClock");
var progressEl = document.getElementById("progressBar");
var logoEl     = document.getElementById("clientLogo");

function setClientLogo(url) {
  var img = document.getElementById("clientLogo");
  if (!img) return;

  var isAbsolute = typeof url === "string" && /^https?:\/\//i.test(url);

  if (!isAbsolute) {
    img.removeAttribute("src");
    img.style.display = "none";
    console.log("Logo oculto. URL inválida:", url);
    return;
  }

  img.onerror = function () { console.log("Logo ERROR:", url); };
  img.onload  = function () { console.log("Logo OK:", url); };
  img.src = url;
  img.style.display = "block";
}

function esc(v) {
  // FIX: v ?? "" → v !== null && v !== undefined ? v : ""
  return String(v !== null && v !== undefined ? v : "")
    .split("&").join("&amp;")
    .split("<").join("&lt;")
    .split(">").join("&gt;")
    .split('"').join("&quot;")
    .split("'").join("&#039;");
}

// Convierte slot interno "HH:00" (24h) a display "HH:MM AM/PM"
function slotTo12h(hhmm) {
  var parts = String(hhmm || "").split(":");
  var h = Number(parts[0]);
  var m = Number(parts[1]);
  if (isNaN(h) || isNaN(m)) return hhmm;
  var ampm = h >= 12 ? "PM" : "AM";
  var h12 = ((h + 11) % 12) + 1;
  return (h12 < 10 ? "0" : "") + h12 + ":" + (m < 10 ? "0" : "") + m + " " + ampm;
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
  var s = String(timeStr || "").trim();
  if (!s) return null;

  var match12 = s.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/i);
  if (match12) {
    var h = Number(match12[1]);
    var meridiem = match12[3].toUpperCase();
    if (meridiem === "AM" && h === 12) h = 0;
    if (meridiem === "PM" && h !== 12) h += 12;
    if (h < 8 || h > 20) return null;
    return (h < 10 ? "0" : "") + h + ":00";
  }

  var hh = Number(s.split(":")[0]);
  if (isNaN(hh)) return null;
  if (hh < 8 || hh > 20) return null;
  return (hh < 10 ? "0" : "") + hh + ":00";
}

function chunk(arr, size) {
  var out = [];
  for (var i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

function setProgress(startTs, durationMs) {
  if (!progressEl) return;
  var elapsed = Date.now() - startTs;
  var pct = Math.min(100, (elapsed / durationMs) * 100);
  progressEl.style.width = pct + "%";
}

function startClock() {
  if (!clockEl) return;
  var tick = function () {
    var d = new Date();
    var h = d.getHours();
    var m = d.getMinutes();
    var s = d.getSeconds();
    var ampm = h >= 12 ? "PM" : "AM";
    var h12 = ((h + 11) % 12) + 1;
    clockEl.textContent =
      (h12 < 10 ? "0" : "") + h12 + ":" +
      (m < 10 ? "0" : "") + m + ":" +
      (s < 10 ? "0" : "") + s + " " + ampm;
  };
  tick();
  setInterval(tick, 1000);
}

// ---------- STATE ----------
var state = {
  deviceCode: "----",
  mode: "triples",
  pageIndex: 0,
   // Triples (por día)
  triplesTodayRows: [],
  triplesYesterdayRows: [],
  triplesProviders: [],
  triplesDay: "today", // "today" | "yesterday"
  // Animalitos 
  animalitosTodayRows: [],
  animalitosYesterdayRows: [],
  animalitosProviders: [],
  animalitosDay: "today",
  animalitosGroupIndex: 0,
};

var rotationTimer = null;
var rafTimer = null;
var tickStart = 0;

// ---------- NORMALIZERS ----------
function normalizeTriples(raw) {
  var out = [];
  var list = raw || [];
  for (var i = 0; i < list.length; i++) {
    var r = list[i];
    // FIX: r.time ?? r.draw_time → r.time !== ... ? r.time : r.draw_time
    var slot = timeToHourSlot(r.time !== null && r.time !== undefined ? r.time : r.draw_time);
    if (!slot) continue;
    // FIX: r.number ?? r.winning_number ?? ""
    var num = r.number !== null && r.number !== undefined ? r.number :
              (r.winning_number !== null && r.winning_number !== undefined ? r.winning_number : "");
    out.push({
      provider: r.provider,
      time: slot,
      number: String(num).trim(),
    });
  }
  return out;
}

function normalizeAnimalitos(raw) {
  var out = [];
  var list = raw || [];
  for (var i = 0; i < list.length; i++) {
    var r = list[i];
    var slot = timeToHourSlot(r.time);
    if (!slot) continue;
    // FIX: ?? "" → ternario
    out.push({
      provider: r.provider,
      time: slot,
      number: String(r.number !== null && r.number !== undefined ? r.number : "").trim(),
      animal: String(r.animal !== null && r.animal !== undefined ? r.animal : "").trim(),
      image:  String(r.image  !== null && r.image  !== undefined ? r.image  : "").trim(),
    });
  }
  return out;
}

function computeProviders(rows) {
  var seen = {};
  var out  = [];
  for (var i = 0; i < rows.length; i++) {
    var p = rows[i].provider;
    if (p && !seen[p]) { seen[p] = true; out.push(p); }
  }
  return out.sort(function (a, b) { return a.localeCompare(b); });
}

// Retorna objeto plano {}  — acceder con byTime[t], NUNCA byTime.get(t)
function mapRowsByProvider(rows, provider) {
  var m = {};
  for (var i = 0; i < rows.length; i++) {
    if (rows[i].provider !== provider) continue;
    m[rows[i].time] = rows[i];
  }
  return m;
}

// ---------- RENDER ----------
function renderDeviceCode(code) {
  var el = document.getElementById("deviceCode");
  if (el) el.textContent = code ? String(code).toUpperCase() : "----";
}

function renderWaitingForActivation() {
  if (!gridEl) return;
  gridEl.innerHTML =
    '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:24px;gap:12px;">' +
      '<div style="font-size:22px;font-weight:700;">ACTIVAR TV</div>' +
      '<div style="opacity:.9;">Ingresa este código en el panel para asignar una sucursal</div>' +
      '<div style="font-size:42px;font-weight:900;letter-spacing:4px;margin-top:8px;">' +
        esc(state.deviceCode || "----") +
      '</div>' +
      '<div style="opacity:.8;margin-top:8px;">Esperando asignación...</div>' +
    '</div>';
}

function renderTriplesPage() {
  if (!gridEl) return;

  var rows = (state.triplesDay === "today") ? state.triplesTodayRows : state.triplesYesterdayRows;

  if (titleEl) {
    titleEl.textContent = (state.triplesDay === "today")
      ? "RESULTADOS HOY (TRIPLES)"
      : "RESULTADOS AYER (TRIPLES)";
  }

  var providers = computeProviders(rows);
  state.triplesProviders = providers;

  if (!providers.length) {
    gridEl.innerHTML = '<div style="padding:16px;">Sin resultados.</div>';
    return;
  }

  var groups = chunk(providers, 4);
  var group = groups[state.pageIndex] || groups[0];
  if (!group) return;

  var html = group.map(function (p) {
    var byTime = mapRowsByProvider(rows, p);

    var rowsHtml = SLOTS.map(function (t) {
      var rec = byTime.get(t);
      var num = (rec && rec.number) ? esc(rec.number) : '<span class="col__empty">…</span>';

      return (
        '\n<div class="col__row">' +
        '\n  <div class="col__time">' + esc(slotTo12h(t)) + '</div>' +
        '\n  <div class="col__num">' + num + '</div>' +
        '\n</div>\n'
      );
    }).join("");

    return (
      '\n<article class="col">' +
      '\n  <div class="col__head"><div class="col__title">' + esc(p) + '</div></div>' +
      '\n  <div class="col__body">' + rowsHtml + '</div>' +
      '\n</article>\n'
    );
  }).join("");

  gridEl.innerHTML = html;
}

function renderAnimalitosGroup(day) {
  if (!gridEl) return;
  var rows = day === "today" ? state.animalitosTodayRows : state.animalitosYesterdayRows;
  if (titleEl) titleEl.textContent = day === "today" ? "RESULTADOS HOY (ANIMALITOS)" : "RESULTADOS AYER (ANIMALITOS)";

  var providers = state.animalitosProviders;
  if (!providers.length) {
    gridEl.innerHTML = '<div style="padding:16px;">Sin animalitos.</div>';
    return;
  }

  var groups = chunk(providers, 4);
  var group  = groups[state.animalitosGroupIndex] || groups[0];
  if (!group) return;

  var html = "";
  for (var gi = 0; gi < group.length; gi++) {
    var p = group[gi];
    var byTime = mapRowsByProvider(rows, p);
    var rowsHtml = "";
    for (var si = 0; si < SLOTS.length; si++) {
      var t   = SLOTS[si];
      var rec = byTime[t];
      // FIX: rec?.image, rec?.animal, rec?.number → condicionales explícitos
      var img    = (rec && rec.image)  ? '<img class="col__icon" src="' + esc(rec.image) + '" alt="" />' : "";
      var animal = (rec && rec.animal) ? esc(rec.animal) : '<span class="col__empty">…</span>';
      var num    = (rec && rec.number) ? esc(rec.number) : '<span class="col__empty">…</span>';
      rowsHtml +=
        '<div class="col__row col__row--animal">' +
          '<div class="col__time">'   + esc(slotTo12h(t)) + '</div>' +
          '<div class="col__num col__num--animal">' + num + '</div>' +
          '<div class="col__nameWrap">' +
            '<div class="col__name">' + animal + '</div>' +
            img +
          '</div>' +
        '</div>';
    }

    html +=
      '<article class="col">' +
        '<div class="col__head"><div class="col__title">' + esc(p) + '</div></div>' +
        '<div class="col__body">' + rowsHtml + '</div>' +
      '</article>';
  }

  gridEl.innerHTML = html;
}

function render() {
  if (state.mode === "triples") renderTriplesPage();
  else renderAnimalitosGroup(state.animalitosDay);
}

// ---------- DATA FETCH ----------
function getApiBase() {
  // FIX: window.__APP_CONFIG__?.API_BASE → condicional explícito
  return (window.__APP_CONFIG__ && window.__APP_CONFIG__.API_BASE)
    ? window.__APP_CONFIG__.API_BASE
    : "https://api.ssganador.lat";
}

var BUSINESS_TZ = "America/Caracas";

function getDateISO(offset) {
  var now = new Date();
  var parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: BUSINESS_TZ,
    year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(now);
  var yyyy = null, mm = null, dd = null;
  for (var i = 0; i < parts.length; i++) {
    if (parts[i].type === "year")  yyyy = parts[i].value;
    if (parts[i].type === "month") mm   = parts[i].value;
    if (parts[i].type === "day")   dd   = parts[i].value;
  }
  var base = new Date(yyyy + "-" + mm + "-" + dd + "T00:00:00");
  base.setDate(base.getDate() + offset);
  var y = base.getFullYear();
  var m = String(base.getMonth() + 1);
  var d = String(base.getDate());
  if (m.length < 2) m = "0" + m;
  if (d.length < 2) d = "0" + d;
  return y + "-" + m + "-" + d;
}

function fetchAnimalitosByDate(dateISO) {
  var code = deviceManager.activationCode || localStorage.getItem("activation_code") || "DEV";
  var api  = getApiBase();
  var url  = api + "/api/animalitos/?code=" + encodeURIComponent(code) + "&date=" + encodeURIComponent(dateISO);
  return fetch(url, { cache: "no-store" }).then(function (res) {
      if (!res.ok) return [];
      return res.json().then(function (data) { return normalizeAnimalitos(data); });
  });
}

function refreshAnimalitosCaches() {
  return Promise.all([
    fetchAnimalitosByDate(getDateISO(0)),
    fetchAnimalitosByDate(getDateISO(-1)),
  ]).then(function (results) {
    var todayRows = results[0];
    var yRows     = results[1];
  state.animalitosTodayRows     = todayRows;
  state.animalitosYesterdayRows = yRows;
    state.animalitosProviders     = computeProviders(todayRows.concat(yRows));
  });
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

  var raf = function () {
    setProgress(tickStart, durationMs);
    rafTimer = requestAnimationFrame(raf);
  };
  rafTimer = requestAnimationFrame(raf);

  rotationTimer = setInterval(function () {
    tickStart = Date.now();

    if (state.mode === "triples") {
      var rows = (state.triplesDay === "today") ? state.triplesTodayRows : state.triplesYesterdayRows;
      var providers = computeProviders(rows);
      var groups = chunk(providers, 4);

      state.pageIndex += 1;

      if (state.pageIndex >= groups.length) {
        if (state.triplesDay === "today") {
          state.triplesDay = "yesterday";
          state.pageIndex = 0;
          render();
          return;
        }

        // ya terminó AYER -> pasa a animalitos
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

    // Modo animalitos
    if (state.animalitosDay === "today") {
      state.animalitosDay = "yesterday";
    } else {
      state.animalitosDay = "today";
      var groups2 = chunk(state.animalitosProviders, 4);
      state.animalitosGroupIndex = (state.animalitosGroupIndex + 1) % Math.max(1, groups2.length);
    }
    render();
  }, durationMs);
}

// ---------- EVENTS ----------
window.addEventListener("resultsUpdated", function (e) {
  var d = e.detail;

  // Caso A: backend devuelve array => asumimos HOY
  if (Array.isArray(d)) {
    state.triplesTodayRows = normalizeTriples(d);
  }

  // Caso B: backend devuelve objeto => buscamos varias formas comunes
  if (d && typeof d === "object" && !Array.isArray(d)) {
    // 1) {today:[], yesterday:[]}
    if (Array.isArray(d.today)) state.triplesTodayRows = normalizeTriples(d.today);
    if (Array.isArray(d.yesterday)) state.triplesYesterdayRows = normalizeTriples(d.yesterday);

    // 2) {results:[]}
    if (Array.isArray(d.results)) state.triplesTodayRows = normalizeTriples(d.results);

    // 3) {triples:{today:[],yesterday:[]}} o {triples:[]}
    if (d.triples) {
      if (Array.isArray(d.triples)) state.triplesTodayRows = normalizeTriples(d.triples);
      if (d.triples && typeof d.triples === "object") {
        if (Array.isArray(d.triples.today)) state.triplesTodayRows = normalizeTriples(d.triples.today);
        if (Array.isArray(d.triples.yesterday)) state.triplesYesterdayRows = normalizeTriples(d.triples.yesterday);
      }
    }
  }

  // providers dependen del día actual
  var rows = (state.triplesDay === "today") ? state.triplesTodayRows : state.triplesYesterdayRows;
  state.triplesProviders = computeProviders(rows);

  if (state.mode === "triples") render();
});

// ---------- BOOT ----------
(function boot() {
  startClock();

  renderDeviceCode(
    localStorage.getItem("activation_code") ||
    new URL(location.href).searchParams.get("code")
  );

  deviceManager.ensureActivationCode().then(function (code) {
      state.deviceCode = String(code || "----").toUpperCase();
      renderDeviceCode(state.deviceCode);
      render();

      deviceManager.connectSocket();

      return deviceManager.syncStatusOnce();
  }).then(function () {
      return deviceManager.fetchContextOnce();
  }).then(function (ctx) {
    // FIX: ctx era usada fuera del IIFE — ahora correctamente dentro del scope
    // FIX: ctx?.client_logo_url → condicional explícito
    var logoUrl =
      (ctx && ctx.client_logo_url
        ? ctx.client_logo_url
        : ((window.__APP_CONFIG__ && window.__APP_CONFIG__.CLIENT_LOGO)
            ? window.__APP_CONFIG__.CLIENT_LOGO
            : ""));

      setClientLogo(logoUrl);

    // debug logs — ahora ctx SÍ está en scope
      console.log("status ctx:", ctx);
    console.log("client_logo_url:", ctx && ctx.client_logo_url ? ctx.client_logo_url : null);
    console.log("img src antes:", document.getElementById("clientLogo") ? document.getElementById("clientLogo").src : null);

      return deviceManager.fetchResultsOnce();
  }).then(function () {
      return refreshAnimalitosCaches();
  }).then(function () {
      setInterval(refreshAnimalitosCaches, ANIMALITOS_REFRESH_MS);
      render();
      startRotation(ROTATION_MS);
  }).catch(function (e) {
      console.error("BOOT ERROR:", e);
    if (gridEl) gridEl.innerHTML = '<div style="padding:16px;">Error: ' + esc(e.message || e) + '</div>';
    });
})();
