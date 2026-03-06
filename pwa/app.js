// ============================================
// File: pwa/app.js
// Compatible: Android 8+ (WebView Chromium 67+)
// - Sin ?. ni ?? ni const/let ni arrow functions
// - byTime es objeto plano {}, acceso con byTime[t] (NO .get())
// - index.html debe cargar: config.js → deviceManager.js → app.js (sin type="module")
// ============================================

var ROTATION_MS            = 40000;
var ANIMALITOS_REFRESH_MS  = 60000;
var ANIMALITOS_INTERVAL_MS = 40000;

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
var themeToggleEl = document.getElementById("themeToggle");

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
  return h12 + ":" + (m < 10 ? "0" : "") + m + " " + ampm;
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

function timeToMinuteSlot(timeStr) {
  var s = String(timeStr || "").trim();
  if (!s) return null;

  var match12 = s.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/i);
  if (match12) {
    var h12 = Number(match12[1]);
    var mm = Number(match12[2]);
    var mer = match12[3].toUpperCase();
    if (mer === "AM" && h12 === 12) h12 = 0;
    if (mer === "PM" && h12 !== 12) h12 += 12;
    if (isNaN(h12) || isNaN(mm) || h12 < 0 || h12 > 23 || mm < 0 || mm > 59) return null;
    return (h12 < 10 ? "0" : "") + h12 + ":" + (mm < 10 ? "0" : "") + mm;
  }

  var match24 = s.match(/^(\d{1,2}):(\d{2})$/);
  if (match24) {
    var h = Number(match24[1]);
    var m = Number(match24[2]);
    if (isNaN(h) || isNaN(m) || h < 0 || h > 23 || m < 0 || m > 59) return null;
    return (h < 10 ? "0" : "") + h + ":" + (m < 10 ? "0" : "") + m;
  }

  return null;
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
    state.clientLogoUrl = "";
    console.log("Logo oculto. URL invalida:", url);
    return;
  }
  img.onerror = function () { console.log("Logo ERROR:", url); };
  img.onload  = function () { console.log("Logo OK:", url); };
  img.src     = url;
  img.style.display = "block";
  state.clientLogoUrl = url;
}

// ---------- STATE ----------
var state = {
  deviceCode: "----",
  clientLogoUrl: "",
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
    var slot = timeToMinuteSlot(time);
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

var PROVIDER_ORDER = {
  "Triple Chance A": 0,
  "Triple Chance B": 1,
  "Triple Chance C": 2,
  "Triple Caracas A": 3,
  "Triple Caracas B": 4,
  "Triple Caracas C": 5,
  "Triple Tachira A": 6,
  "Triple Tachira B": 7,
  "Triple Tachira C": 8,
  "Triple Zulia A": 9,
  "Triple Zulia B": 10,
  "Triple Zulia C": 11,
  "Triple Caliente A": 12,
  "Triple Caliente B": 13,
  "Triple Caliente C": 14,
  "Triple Zamorano A": 15,
  "Triple Zamorano B": 16,
  "Triple Zamorano C": 17
};

function computeProviders(rows) {
  var seen = {};
  var out  = [];
  for (var i = 0; i < rows.length; i++) {
    var p = rows[i].provider;
    if (p && !seen[p]) { seen[p] = true; out.push(p); }
  }
  return out.sort(function (a, b) {
    var ra = PROVIDER_ORDER[a];
    var rb = PROVIDER_ORDER[b];
    var ha = typeof ra === "number";
    var hb = typeof rb === "number";
    if (ha && hb) return ra - rb;
    if (ha && !hb) return -1;
    if (!ha && hb) return 1;
    return a.localeCompare(b);
  });
}

function parseTripleGroupProvider(name) {
  var normalized = String(name || "").replace(/\s+/g, " ").trim();
  var m = normalized.match(/^(.*)\s([ABC])$/);
  if (!m) return null;
  var base = String(m[1] || "").trim();
  var group = String(m[2] || "").toUpperCase();
  if (!base || (group !== "A" && group !== "B" && group !== "C")) return null;
  return { base: base, group: group };
}

function groupColumnsForProvider(provider) {
  if (provider === "Triple Zamorano") return ["A", "C"];
  return ["A", "B", "C"];
}

function groupedSlotsForProvider(provider) {
  if (provider === "Triple Caracas" || provider === "Triple Caliente") {
    return ["13:00", "16:30", "19:10"];
  }
  if (provider === "Triple Tachira") {
    return ["13:15", "16:45", "22:00"];
  }
  if (provider === "Triple Zamorano") {
    return ["10:00", "12:00", "14:00"];
  }
  if (provider === "Triple Chance") {
    return ["13:00", "16:00", "19:00"];
  }
  if (provider === "Triple Zulia") {
    return ["12:45", "16:45", "19:05"];
  }
  return ["10:00", "13:00", "19:00"];
}

function _timeToMinutes(hhmm) {
  var p = String(hhmm || "").split(":");
  var h = Number(p[0]);
  var m = Number(p[1]);
  if (isNaN(h) || isNaN(m)) return -1;
  return (h * 60) + m;
}

function mapToGroupedSlot(provider, slot) {
  var slots = groupedSlotsForProvider(provider);
  var src = String(slot || "");
  if (!src || !slots.length) return "";
  for (var i = 0; i < slots.length; i++) {
    if (slots[i] === src) return slots[i];
  }
  return "";
}

function buildTripleCards(todayRows, yesterdayRows) {
  var grouped = {};
  var singleToday = {};
  var singleYesterday = {};
  var i;

  function isGroupedBase(base) {
    return base === "Triple Chance" ||
      base === "Triple Caracas" ||
      base === "Triple Tachira" ||
      base === "Triple Zulia" ||
      base === "Triple Caliente" ||
      base === "Triple Zamorano";
  }

  function pushGrouped(base, group, source, row) {
    if (!grouped[base]) {
      grouped[base] = {
        today: { A: {}, B: {}, C: {} },
        yesterday: { A: {}, B: {}, C: {} }
      };
    }
    var mapped = mapToGroupedSlot(base, row.time);
    if (!mapped) return;
    grouped[base][source][group][mapped] = row.number;
  }

  function isLegacyGroupedProvider(name) {
    return name === "Triple Chance" ||
      name === "Triple Caracas" ||
      name === "Triple Tachira" ||
      name === "Triple Zulia" ||
      name === "Triple Caliente" ||
      name === "Triple Zamorano";
  }

  function ingest(rows, source) {
    for (var j = 0; j < rows.length; j++) {
      var r = rows[j];
      var parsed = parseTripleGroupProvider(r.provider);
      if (parsed && isGroupedBase(parsed.base)) {
        pushGrouped(parsed.base, parsed.group, source, r);
      } else if (isLegacyGroupedProvider(r.provider)) {
        // Compatibilidad con data legacy guardada sin sufijo A/B/C.
        // Se ubica en columna C para evitar duplicados en tablas secundarias.
        pushGrouped(r.provider, "C", source, r);
      } else {
        var target = source === "today" ? singleToday : singleYesterday;
        if (!target[r.provider]) target[r.provider] = [];
        target[r.provider].push({ time: r.time, number: r.number });
      }
    }
  }

  ingest(todayRows || [], "today");
  ingest(yesterdayRows || [], "yesterday");

  function rowsByTimeMap(arr) {
    var m = {};
    for (var j = 0; j < arr.length; j++) m[arr[j].time] = arr[j].number;
    return m;
  }

  var cards = [];
  var basesPriority = ["Triple Chance", "Triple Caracas", "Triple Tachira", "Triple Zulia", "Triple Caliente", "Triple Zamorano"];
  for (i = 0; i < basesPriority.length; i++) {
    var bp = basesPriority[i];
    if (!grouped[bp]) {
      grouped[bp] = {
        today: { A: {}, B: {}, C: {} },
        yesterday: { A: {}, B: {}, C: {} }
      };
    }
    cards.push({
      kind: "grouped",
      provider: bp,
      columns: groupColumnsForProvider(bp),
      slots: groupedSlotsForProvider(bp),
      today: grouped[bp].today,
      yesterday: grouped[bp].yesterday
    });
    delete grouped[bp];
  }

  var extraBases = [];
  for (var k in grouped) if (grouped.hasOwnProperty(k)) extraBases.push(k);
  extraBases.sort(function (a, b) { return a.localeCompare(b); });
  for (i = 0; i < extraBases.length; i++) {
    var eb = extraBases[i];
    cards.push({
      kind: "grouped",
      provider: eb,
      columns: groupColumnsForProvider(eb),
      slots: groupedSlotsForProvider(eb),
      today: grouped[eb].today,
      yesterday: grouped[eb].yesterday
    });
  }

  var singleProvidersMap = {};
  for (k in singleToday) if (singleToday.hasOwnProperty(k)) singleProvidersMap[k] = true;
  for (k in singleYesterday) if (singleYesterday.hasOwnProperty(k)) singleProvidersMap[k] = true;

  var singleProviders = [];
  for (k in singleProvidersMap) if (singleProvidersMap.hasOwnProperty(k)) singleProviders.push(k);
  singleProviders.sort(function (a, b) { return a.localeCompare(b); });

  for (i = 0; i < singleProviders.length; i++) {
    var sp = singleProviders[i];
    var todayList = (singleToday[sp] || []).sort(function (a, b) {
      return String(a.time).localeCompare(String(b.time));
    });
    var ydayList = (singleYesterday[sp] || []).sort(function (a, b) {
      return String(a.time).localeCompare(String(b.time));
    });
    var tm = rowsByTimeMap(todayList);
    var ym = rowsByTimeMap(ydayList);

    var timesMap = {};
    for (var tt in tm) if (tm.hasOwnProperty(tt)) timesMap[tt] = true;
    for (tt in ym) if (ym.hasOwnProperty(tt)) timesMap[tt] = true;
    var times = [];
    for (tt in timesMap) if (timesMap.hasOwnProperty(tt)) times.push(tt);
    times.sort(function (a, b) { return String(a).localeCompare(String(b)); });

    var rowsDual = [];
    for (var ti = 0; ti < times.length; ti++) {
      var t = times[ti];
      rowsDual.push({
        time: t,
        today: tm[t] || "",
        yesterday: ym[t] || "",
      });
    }
    cards.push({ kind: "single", provider: sp, rows: rowsDual });
  }

  return cards;
}

function applyTheme(theme) {
  var t = (theme === "light") ? "light" : "dark";
  if (document.body) {
    document.body.className = (t === "light") ? "theme-light" : "theme-dark";
  }
  try { localStorage.setItem("theme_mode", t); } catch (e) {}
  if (themeToggleEl) {
    themeToggleEl.textContent = (t === "light") ? "DIA" : "NOCHE";
  }
}

function initThemeToggle() {
  var saved = "dark";
  try { saved = localStorage.getItem("theme_mode") || "dark"; } catch (e) {}
  applyTheme(saved);
  if (!themeToggleEl) return;
  themeToggleEl.onclick = function () {
    var curr = document.body ? document.body.className : "theme-dark";
    applyTheme(curr === "theme-light" ? "dark" : "light");
  };
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

  var rowsToday = state.triplesTodayRows || [];
  var rowsYesterday = state.triplesYesterdayRows || [];

  if (titleEl) {
    titleEl.textContent = "RESULTADOS HOY/AYER (TRIPLES)";
  }

  var cards = buildTripleCards(rowsToday, rowsYesterday);
  state.triplesProviders = [];
  for (var ci = 0; ci < cards.length; ci++) state.triplesProviders.push(cards[ci].provider);

  if (!cards.length) {
    gridEl.innerHTML = '<div style="padding:16px;">Sin resultados.</div>';
    return;
  }

  var groups = chunk(cards, 4);
  var group  = groups[state.pageIndex] || groups[0];
  if (!group) return;

  var html = "";
  for (var gi = 0; gi < group.length; gi++) {
    var card = group[gi];
    if (card.kind === "grouped") {
      var cols = card.columns;
      var slots = card.slots;

      function renderGroupedSection(label, sourceMap) {
        var acClass = cols.length === 2 ? " col__abc-head--ac" : "";
        var rowAcClass = cols.length === 2 ? " col__abc-row--ac" : "";
        var head = '<div class="col__abc-head' + acClass + '"><div class="col__abc-time-head">HORA</div>';
        for (var hc = 0; hc < cols.length; hc++) head += '<div class="col__abc-col-head">' + cols[hc] + '</div>';
        head += '</div>';

        var rows2 = '<div class="col__abc-rows">';
        for (var rs = 0; rs < slots.length; rs++) {
          var tm = slots[rs];
          rows2 += '<div class="col__abc-row' + rowAcClass + '"><div class="col__abc-time">' + esc(slotTo12h(tm)) + '</div>';
          for (var cc = 0; cc < cols.length; cc++) {
            var c = cols[cc];
            var v = (sourceMap && sourceMap[c] && sourceMap[c][tm]) ? sourceMap[c][tm] : "";
            var cellClass = /[A-Za-z]/.test(v) ? " col__abc-cell col__abc-cell--sign" : " col__abc-cell";
            rows2 += '<div class="' + cellClass + '">' + (v ? esc(v) : '<span class="col__empty">\u2026</span>') + '</div>';
          }
          rows2 += '</div>';
        }
        rows2 += '</div>';
        return (
          '<section class="col__group">' +
            head + rows2 +
          '</section>'
        );
      }

      var bodyHtml = "";
      bodyHtml += renderGroupedSection("HOY", card.today);
      bodyHtml += renderGroupedSection("AYER", card.yesterday);

      html +=
        '<article class="col col--grouped">' +
          '<div class="col__head"><div class="col__title">' + esc(card.provider) + '</div></div>' +
          '<div class="col__body col__body--grouped">' + bodyHtml + '</div>' +
        '</article>';
    } else {
      var p      = card.provider;
      var rowsHtml = "";

      if (!card.rows.length) {
        rowsHtml =
          '<div class="col__num2-head"><div class="col__num2-head-item">HOY</div><div class="col__num2-head-item">AYER</div></div>' +
          '<div class="col__row col__row--dual">' +
            '<div class="col__time">\u2026</div>' +
            '<div class="col__num2">' +
              '<div class="col__num2-col"><div class="col__num"><span class="col__empty">\u2026</span></div></div>' +
              '<div class="col__num2-col"><div class="col__num"><span class="col__empty">\u2026</span></div></div>' +
            '</div>' +
          '</div>';
      } else {
        rowsHtml += '<div class="col__num2-head"><div class="col__num2-head-item">HOY</div><div class="col__num2-head-item">AYER</div></div>';
        for (var si = 0; si < card.rows.length; si++) {
          var rr = card.rows[si];
          var nToday = rr.today ? esc(rr.today) : '<span class="col__empty">\u2026</span>';
          var nYday = rr.yesterday ? esc(rr.yesterday) : '<span class="col__empty">\u2026</span>';
          rowsHtml +=
            '<div class="col__row col__row--dual">' +
              '<div class="col__time">' + esc(slotTo12h(rr.time)) + '</div>' +
              '<div class="col__num2">' +
                '<div class="col__num2-col">' +
                  '<div class="col__num">' + nToday + '</div>' +
                '</div>' +
                '<div class="col__num2-col">' +
                  '<div class="col__num">' + nYday + '</div>' +
                '</div>' +
              '</div>' +
            '</div>';
        }
      }

      html +=
        '<article class="col">' +
          '<div class="col__head"><div class="col__title">' + esc(p) + '</div></div>' +
          '<div class="col__body">' + rowsHtml + '</div>' +
        '</article>';
    }
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
      var imgUrl = (rec && rec.image) ? rec.image : state.clientLogoUrl;
      var img    = imgUrl ? '<img class="col__icon" src="' + esc(imgUrl) + '" alt="" />' : "";
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
      var tripleCards = buildTripleCards(state.triplesTodayRows || [], state.triplesYesterdayRows || []);
      var groups    = chunk(tripleCards, 4);

      state.pageIndex += 1;

      if (state.pageIndex >= groups.length) {
        // Fin triples (HOY/AYER juntos) → animalitos
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
    var groups2      = chunk(state.animalitosProviders, 4);
    var totalGroups2 = Math.max(1, groups2.length);

    if (state.animalitosDay === "today") {
      state.animalitosDay = "yesterday";
      render();
      return;
    }

    // Estábamos en "yesterday". Si aún quedan grupos, avanzamos al siguiente.
    if (state.animalitosGroupIndex + 1 < totalGroups2) {
      state.animalitosGroupIndex += 1;
      state.animalitosDay = "today";
      render();
      return;
    }

    // Fin de animalitos (hoy/ayer y todos los grupos) -> volver a triples.
    state.mode                = "triples";
    state.triplesDay          = "today";
    state.pageIndex           = 0;
    state.animalitosDay       = "today";
    state.animalitosGroupIndex = 0;
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

  var cards = buildTripleCards(state.triplesTodayRows || [], state.triplesYesterdayRows || []);
  state.triplesProviders = [];
  for (var ci = 0; ci < cards.length; ci++) state.triplesProviders.push(cards[ci].provider);

  if (state.mode === "triples") render();
});

// ---------- BOOT ----------
(function boot() {
  initThemeToggle();
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
