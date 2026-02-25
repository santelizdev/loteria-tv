// ============================================
// File: pwa/app.js
// Compatible: Android 8+ (WebView Chromium 67+)
// - Sin ?. ni ?? ni const/let ni arrow functions
// - byTime es objeto plano {}, acceso con byTime[t] (NO .get())
// - index.html debe cargar: config.js → deviceManager.js → app.js (sin type="module")
// ============================================

var ROTATION_MS            = 20000;
var ANIMALITOS_REFRESH_MS  = 60000;
var ANIMALITOS_INTERVAL_MS = 15000;

var SLOTS = (function () {
  var out = [];
  for (var h = 8; h <= 20; h++) {
    out.push((h < 10 ? "0" : "") + h + ":00");
  }
  return out;
})();

var deviceManager = new DeviceManager(
  typeof DEVICE_ID !== "undefined" ? DEVICE_ID : null
);

var gridEl     = document.getElementById("grid");
var titleEl    = document.getElementById("resultsTitle");
var clockEl    = document.getElementById("vzClock");
var progressEl = document.getElementById("progressBar");

// ---------- HELPERS ----------
function esc(v) {
  return String(v !== null && v !== undefined ? v : "")
    .split("&").join("&amp;")
    .split("<").join("&lt;")
    .split(">").join("&gt;")
    .split('"').join("&quot;")
    .split("'").join("&#039;");
}

function slotTo12h(hhmm) {
  var parts = String(hhmm || "").split(":");
  var h = Number(parts[0]);
  var m = Number(parts[1]);
  if (isNaN(h) || isNaN(m)) return hhmm;
  var ampm = h >= 12 ? "PM" : "AM";
  var h12  = ((h + 11) % 12) + 1;
  return (h12 < 10 ? "0" : "") + h12 + ":" + (m < 10 ? "0" : "") + m + " " + ampm;
}

function timeToHourSlot(timeStr) {
  var s = String(timeStr || "").trim();
  if (!s) return null;

  var match12 = s.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/i);
  if (match12) {
    var h12 = Number(match12[1]);
    var mer = match12[3].toUpperCase();
    if (mer === "AM" && h12 === 12) h12 = 0;
    if (mer === "PM" && h12 !== 12) h12 += 12;
    if (h12 < 8 || h12 > 20) return null;
    return (h12 < 10 ? "0" : "") + h12 + ":00";
  }

  var hh = Number(s.split(":")[0]);
  if (isNaN(hh) || hh < 8 || hh > 20) return null;
  return (hh < 10 ? "0" : "") + hh + ":00";
}

function chunk(arr, size) {
  var out = [];
  for (var i = 0; i < arr.length; i += size) {
    out.push(arr.slice(i, i + size));
  }
  return out;
}

function setProgress(startTs, durationMs) {
  if (!progressEl) return;
  var pct = Math.min(100, ((Date.now() - startTs) / durationMs) * 100);
  progressEl.style.width = pct + "%";
}

function startClock() {
  if (!clockEl) return;
  var tick = function () {
    var d    = new Date();
    var h    = d.getHours();
    var m    = d.getMinutes();
    var s    = d.getSeconds();
    var ampm = h >= 12 ? "PM" : "AM";
    var h12  = ((h + 11) % 12) + 1;
    clockEl.textContent =
      (h12 < 10 ? "0" : "") + h12 + ":" +
      (m   < 10 ? "0" : "") + m   + ":" +
      (s   < 10 ? "0" : "") + s   + " " + ampm;
  };
  tick();
  setInterval(tick, 1000);
}

function setClientLogo(url) {
  var img = document.getElementById("clientLogo");
  if (!img) return;
  var isAbsolute = typeof url === "string" && /^https?:\/\//i.test(url);
  if (!isAbsolute) {
    img.removeAttribute("src");
    img.style.display = "none";
    console.log("Logo oculto. URL invalida:", url);
    return;
  }
  img.onerror = function () { console.log("Logo ERROR:", url); };
  img.onload  = function () { console.log("Logo OK:", url); };
  img.src     = url;
  img.style.display = "block";
}

// ---------- STATE ----------
var state = {
  deviceCode: "----",
  mode: "triples",

  triplesTodayRows:     [],
  triplesYesterdayRows: [],
  triplesProviders:     [],
  triplesDay: "today",

  animalitosTodayRows:     [],
  animalitosYesterdayRows: [],
  animalitosProviders:     [],
  animalitosDay: "today",
  animalitosGroupIndex: 0,

  pageIndex: 0,
};

var rotationTimer = null;
var rafTimer      = null;
var tickStart     = 0;

// ---------- NORMALIZERS ----------
function normalizeTriples(raw) {
  var out  = [];
  var list = raw || [];
  for (var i = 0; i < list.length; i++) {
    var r    = list[i];
    var time = (r.time !== null && r.time !== undefined) ? r.time : r.draw_time;
    var slot = timeToHourSlot(time);
    if (!slot) continue;
    var num  = (r.number !== null && r.number !== undefined)
      ? r.number
      : ((r.winning_number !== null && r.winning_number !== undefined) ? r.winning_number : "");
    out.push({ provider: r.provider, time: slot, number: String(num).trim() });
  }
  return out;
}

function normalizeAnimalitos(raw) {
  var out  = [];
  var list = raw || [];
  for (var i = 0; i < list.length; i++) {
    var r    = list[i];
    var slot = timeToHourSlot(r.time);
    if (!slot) continue;
    out.push({
      provider: r.provider,
      time:     slot,
      number:   String(r.number !== null && r.number !== undefined ? r.number : "").trim(),
      animal:   String(r.animal !== null && r.animal !== undefined ? r.animal : "").trim(),
      image:    String(r.image  !== null && r.image  !== undefined ? r.image  : "").trim(),
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
    '<div style="display:flex;flex-direction:column;align-items:center;' +
    'justify-content:center;padding:24px;gap:12px;">' +
      '<div style="font-size:22px;font-weight:700;">ACTIVAR TV</div>' +
      '<div style="opacity:.9;">Ingresa este codigo en el panel para asignar una sucursal</div>' +
      '<div style="font-size:42px;font-weight:900;letter-spacing:4px;margin-top:8px;">' +
        esc(state.deviceCode || "----") +
      '</div>' +
      '<div style="opacity:.8;margin-top:8px;">Esperando asignacion...</div>' +
    '</div>';
}

function renderTriplesPage() {
  if (!gridEl) return;

  var rows = (state.triplesDay === "today")
    ? state.triplesTodayRows
    : state.triplesYesterdayRows;

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
  var group  = groups[state.pageIndex] || groups[0];
  if (!group) return;

  var html = "";
  for (var gi = 0; gi < group.length; gi++) {
    var p      = group[gi];
    var byTime = mapRowsByProvider(rows, p);
    var rowsHtml = "";

    for (var si = 0; si < SLOTS.length; si++) {
      var t   = SLOTS[si];
      var rec = byTime[t]; // objeto plano, NO .get()
      var num = (rec && rec.number)
        ? esc(rec.number)
        : '<span class="col__empty">\u2026</span>';

      rowsHtml +=
        '<div class="col__row">' +
          '<div class="col__time">' + esc(slotTo12h(t)) + '</div>' +
          '<div class="col__num">'  + num + '</div>' +
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

function renderAnimalitosGroup(day) {
  if (!gridEl) return;

  var rows = (day === "today")
    ? state.animalitosTodayRows
    : state.animalitosYesterdayRows;

  if (titleEl) {
    titleEl.textContent = (day === "today")
      ? "RESULTADOS HOY (ANIMALITOS)"
      : "RESULTADOS AYER (ANIMALITOS)";
  }

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
    var p        = group[gi];
    var byTime   = mapRowsByProvider(rows, p);
    var rowsHtml = "";

    for (var si = 0; si < SLOTS.length; si++) {
      var t      = SLOTS[si];
      var rec    = byTime[t]; // objeto plano, NO .get()
      var img    = (rec && rec.image)
        ? '<img class="col__icon" src="' + esc(rec.image) + '" alt="" />'
        : "";
      var animal = (rec && rec.animal)
        ? esc(rec.animal)
        : '<span class="col__empty">\u2026</span>';
      var num    = (rec && rec.number)
        ? esc(rec.number)
        : '<span class="col__empty">\u2026</span>';

      rowsHtml +=
        '<div class="col__row col__row--animal">' +
          '<div class="col__time">' + esc(slotTo12h(t)) + '</div>' +
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
  return (window.__APP_CONFIG__ && window.__APP_CONFIG__.API_BASE)
    ? window.__APP_CONFIG__.API_BASE
    : "https://api.ssganador.lat";
}

var BUSINESS_TZ = "America/Caracas";

function getDateISO(offset) {
  var now   = new Date();
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

function fetchTriplesByDate(dateISO) {
  var code = deviceManager.activationCode
    || localStorage.getItem("activation_code")
    || "DEV";
  var url = getApiBase() + "/api/results/?code=" +
            encodeURIComponent(code) + "&date=" + encodeURIComponent(dateISO);
  return fetch(url, { cache: "no-store" })
    .then(function (res) {
      if (!res.ok) return [];
      return res.json().then(function (data) {
        return Array.isArray(data) ? normalizeTriples(data) : [];
      });
    })
    .catch(function () { return []; });
}

function refreshTriplesCaches() {
  return Promise.all([
    fetchTriplesByDate(getDateISO(0)),
    fetchTriplesByDate(getDateISO(-1)),
  ]).then(function (results) {
    state.triplesTodayRows     = results[0];
    state.triplesYesterdayRows = results[1];
  });
}

function fetchAnimalitosByDate(dateISO) {
  var code = deviceManager.activationCode
    || localStorage.getItem("activation_code")
    || "DEV";
  var url = getApiBase() + "/api/animalitos/?code=" +
            encodeURIComponent(code) + "&date=" + encodeURIComponent(dateISO);
  return fetch(url, { cache: "no-store" })
    .then(function (res) {
      if (!res.ok) return [];
      return res.json().then(function (data) { return normalizeAnimalitos(data); });
    })
    .catch(function () { return []; });
}

function refreshAnimalitosCaches() {
  return Promise.all([
    fetchAnimalitosByDate(getDateISO(0)),
    fetchAnimalitosByDate(getDateISO(-1)),
  ]).then(function (results) {
    state.animalitosTodayRows     = results[0];
    state.animalitosYesterdayRows = results[1];
    state.animalitosProviders     = computeProviders(results[0].concat(results[1]));
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
      var rows      = (state.triplesDay === "today")
        ? state.triplesTodayRows
        : state.triplesYesterdayRows;
      var providers = computeProviders(rows);
      var groups    = chunk(providers, 4);

      state.pageIndex += 1;

      if (state.pageIndex >= groups.length) {
        if (state.triplesDay === "today") {
          state.triplesDay = "yesterday";
          state.pageIndex  = 0;
          render();
          return;
        }
        // Fin triples ayer → animalitos
        state.mode               = "animalitos";
        state.pageIndex          = 0;
        state.animalitosDay      = "today";
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
      state.animalitosGroupIndex =
        (state.animalitosGroupIndex + 1) % Math.max(1, groups2.length);
    }
    render();
  }, durationMs);
}

// resultsUpdated: fired by WebSocket push (real-time update for TODAY only)
// We only update triplesTodayRows here — yesterday comes from refreshTriplesCaches()
window.addEventListener("resultsUpdated", function (e) {
  var d = e.detail;

  if (Array.isArray(d)) {
    state.triplesTodayRows = normalizeTriples(d);
  }

  if (d && typeof d === "object" && !Array.isArray(d)) {
    if (Array.isArray(d.today))   state.triplesTodayRows = normalizeTriples(d.today);
    if (Array.isArray(d.results)) state.triplesTodayRows = normalizeTriples(d.results);
    if (d.triples) {
      if (Array.isArray(d.triples)) {
        state.triplesTodayRows = normalizeTriples(d.triples);
      } else if (typeof d.triples === "object" && Array.isArray(d.triples.today)) {
        state.triplesTodayRows = normalizeTriples(d.triples.today);
      }
    }
    // yesterday from WS push (bonus — if backend ever sends it)
    if (Array.isArray(d.yesterday)) state.triplesYesterdayRows = normalizeTriples(d.yesterday);
    if (d.triples && typeof d.triples === "object" && Array.isArray(d.triples.yesterday)) {
      state.triplesYesterdayRows = normalizeTriples(d.triples.yesterday);
    }
  }

  var rows = (state.triplesDay === "today")
    ? state.triplesTodayRows
    : state.triplesYesterdayRows;
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

  deviceManager.ensureActivationCode()
    .then(function (code) {
      state.deviceCode = String(code || "----").toUpperCase();
      renderDeviceCode(state.deviceCode);
      render();
      deviceManager.connectSocket();
      return deviceManager.syncStatusOnce();
    })
    .then(function () {
      return deviceManager.fetchContextOnce();
    })
    .then(function (ctx) {
      var logoUrl = (ctx && ctx.client_logo_url)
        ? ctx.client_logo_url
        : ((window.__APP_CONFIG__ && window.__APP_CONFIG__.CLIENT_LOGO)
            ? window.__APP_CONFIG__.CLIENT_LOGO
            : "");
      setClientLogo(logoUrl);
      console.log("status ctx:", ctx);
      console.log("client_logo_url:", (ctx && ctx.client_logo_url) ? ctx.client_logo_url : null);
      return refreshTriplesCaches();
    })
    .then(function () {
      setInterval(refreshTriplesCaches, ANIMALITOS_REFRESH_MS);
      return refreshAnimalitosCaches();
    })
    .then(function () {
      setInterval(refreshAnimalitosCaches, ANIMALITOS_REFRESH_MS);
      render();
      startRotation(ROTATION_MS);
    })
    .catch(function (e) {
      console.error("BOOT ERROR:", e);
      if (gridEl) {
        gridEl.innerHTML = '<div style="padding:16px;">Error: ' + esc(e.message || e) + '</div>';
      }
    });
})();