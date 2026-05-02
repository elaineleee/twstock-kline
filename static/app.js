/* 台股K線早報 — phone-friendly front-end */

const STATE = {
  universeSize: 100,
  section: "daily",
  cache: new Map(),  // size -> brief json
  watchlist: [],
};

const WATCHLIST_KEY = "candleBrief.tw.watchlist.v1";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

// ── Watchlist storage ────────────────────────────────
function loadWatchlist() {
  try {
    const raw = localStorage.getItem(WATCHLIST_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr.filter((t) => typeof t === "string") : [];
  } catch { return []; }
}
function saveWatchlist(list) {
  try { localStorage.setItem(WATCHLIST_KEY, JSON.stringify(list)); } catch {}
}
function normalizeTicker(s) {
  if (!s) return null;
  const trimmed = String(s).trim().toUpperCase();
  if (!trimmed) return null;
  // 4-digit numeric → default to .TW
  if (/^\d{4}$/.test(trimmed)) return trimmed + ".TW";
  // 6-digit numeric → default to .TWO (TPEx ETFs)
  if (/^\d{6}$/.test(trimmed)) return trimmed + ".TWO";
  // Already has suffix
  if (/^\d{4,6}\.(TW|TWO)$/.test(trimmed)) return trimmed;
  return trimmed;
}
function parseWatchlistInput(text) {
  const lines = String(text || "").split(/[\s,;]+/).map(normalizeTicker).filter(Boolean);
  const seen = new Set();
  const out = [];
  for (const t of lines) { if (!seen.has(t)) { seen.add(t); out.push(t); } }
  return out;
}

// ── Brief fetch ─────────────────────────────────────
async function loadBrief(size) {
  if (STATE.cache.has(size)) return STATE.cache.get(size);
  const r = await fetch(`/api/brief/${size}`, { cache: "no-store" });
  if (!r.ok) {
    const txt = await r.text();
    throw new Error(`HTTP ${r.status}: ${txt.slice(0, 200)}`);
  }
  const brief = await r.json();
  STATE.cache.set(size, brief);
  return brief;
}

// ── Rendering ───────────────────────────────────────
function renderMeta(brief) {
  const totalDaily = brief.daily.length;
  const totalWeekly = brief.weekly.length;
  $("#meta").textContent =
    `${brief.signal_date_pretty}  ·  Top ${brief.universe_size}  ·  ` +
    `日 ${totalDaily}  週 ${totalWeekly}  ·  資料新鮮度 ${brief.freshness.ok}/${brief.freshness.total}`;
}

function rsiHelp(rsi) {
  if (rsi == null) return "—";
  if (rsi >= 70) return `RSI ${rsi.toFixed(1)}（過熱區，反向動能風險升高）`;
  if (rsi >= 55) return `RSI ${rsi.toFixed(1)}（偏強，上行動能未衰）`;
  if (rsi >= 45) return `RSI ${rsi.toFixed(1)}（中性，方向未定）`;
  if (rsi >= 30) return `RSI ${rsi.toFixed(1)}（偏弱，跌勢未消化完）`;
  return `RSI ${rsi.toFixed(1)}（超賣區，反彈/換手機率上升）`;
}
function pctTone(v) {
  if (v == null) return "";
  return v >= 0 ? "up" : "down";
}
function fmtPct(v) {
  if (v == null) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

function renderSignal(s) {
  const tpl = $("#signalTpl").content.cloneNode(true);
  const root = tpl.querySelector(".signal");
  root.dataset.direction = s.direction;
  const tag = $("[data-field=\"tag\"]", root);
  tag.hidden = false;
  // Buy patterns clear the strict |t|>2 gate → "buy watch".
  // Sell patterns are softer (gate is N≥30 only) → "risk reminder".
  tag.textContent = s.direction === "買入" ? "買入觀察" : "風險提醒";
  tag.dataset.direction = s.direction;
  $(".signal__code", root).textContent = s.code;
  $(".signal__name", root).textContent = s.name || "";
  $(".signal__pattern", root).textContent = s.pattern;
  $("[data-field=\"plain\"]", root).textContent =
    s.kind === "weekly" ? `週線形態（截至 ${s.date}）` : `日線形態（${s.date}）`;
  $("[data-field=\"close\"]", root).textContent = s.close.toFixed(2);
  const rsiEl = $("[data-field=\"rsi\"]", root);
  rsiEl.textContent = s.rsi == null ? "—" : s.rsi.toFixed(1);
  if (s.rsi != null) {
    if (s.rsi >= 70) rsiEl.dataset.tone = "hot";
    else if (s.rsi <= 30) rsiEl.dataset.tone = "cold";
  }
  const ma20El = $("[data-field=\"ma20\"]", root);
  ma20El.textContent = fmtPct(s.ma_dist?.ma20);
  ma20El.dataset.tone = pctTone(s.ma_dist?.ma20);
  const ma200El = $("[data-field=\"ma200\"]", root);
  ma200El.textContent = fmtPct(s.ma_dist?.ma200_d);
  ma200El.dataset.tone = pctTone(s.ma_dist?.ma200_d);
  $("[data-field=\"rsihelp\"]", root).textContent = rsiHelp(s.rsi);
  const cta = $("[data-field=\"chartcta\"]", root);
  cta.addEventListener("click", () => openModal(s));
  return tpl;
}

function renderEmpty(msg) {
  return `<div class="empty">${msg}</div>`;
}

function renderSection(brief, section) {
  const c = $("#content");
  c.innerHTML = "";
  if (section === "watchlist") return renderWatchlist(brief);
  const list = section === "weekly" ? brief.weekly : brief.daily;
  if (!list.length) {
    c.innerHTML = renderEmpty(
      section === "weekly"
        ? `本週（截至 ${brief.weekly_signal_date_pretty}）暫無高確信信號。`
        : `${brief.signal_date_pretty} 暫無高確信信號。`
    );
    return;
  }
  for (const s of list) c.appendChild(renderSignal(s));
}

function renderWatchlist(brief) {
  const c = $("#content");
  const list = STATE.watchlist;
  if (!list.length) {
    c.innerHTML = renderEmpty("尚未設定自選股。點下方「編輯」加入代碼。");
    return;
  }
  const dailyMap = new Map(brief.daily.map((s) => [s.code, s]));
  const weeklyMap = new Map(brief.weekly.map((s) => [s.code, s]));
  for (const code of list) {
    const d = dailyMap.get(code);
    const w = weeklyMap.get(code);
    if (d) c.appendChild(renderSignal(d));
    if (w) c.appendChild(renderSignal(w));
    if (!d && !w) {
      const tpl = $("#nosignalTpl").content.cloneNode(true);
      $(".signal__code", tpl).textContent = code;
      c.appendChild(tpl);
    }
  }
}

function refreshWatchlistToolbar() {
  const bar = $("#watchlistToolbar");
  const visible = STATE.section === "watchlist";
  bar.hidden = !visible;
  if (visible) {
    $("#watchlistCount").textContent = STATE.watchlist.length
      ? `已加入 ${STATE.watchlist.length} 隻自選股`
      : "未設定自選股。";
  }
}

// ── Modal chart ─────────────────────────────────────
function openModal(s) {
  const modal = $("#modal");
  modal.setAttribute("aria-hidden", "false");
  $(".modal__code", modal).textContent = `${s.code}  ${s.name || ""}`;
  $(".modal__pattern", modal).textContent = `${s.pattern}（${s.direction}） · ${s.date}`;
  modal.dataset.daily = s.charts.daily;
  modal.dataset.weekly = s.charts.weekly;
  loadModalChart("daily");
}

function loadModalChart(kind) {
  const modal = $("#modal");
  const slot = $(".modal__chart", modal);
  const path = modal.dataset[kind];
  slot.innerHTML = `<iframe src="/${path}" loading="lazy"></iframe>`;
  $$(".modal__tab", modal).forEach((el) => {
    el.classList.toggle("is-active", el.dataset.chartTab === kind);
  });
}

function closeModal() {
  $("#modal").setAttribute("aria-hidden", "true");
  $(".modal__chart").innerHTML = "";
}

// ── App boot & wiring ───────────────────────────────
async function refresh() {
  $("#content").innerHTML = `<div class="loading">載入訊號⋯</div>`;
  try {
    const brief = await loadBrief(STATE.universeSize);
    renderMeta(brief);
    renderSection(brief, STATE.section);
    refreshWatchlistToolbar();
  } catch (err) {
    $("#content").innerHTML = renderEmpty(
      `載入失敗：${err.message}<br>請確認伺服器已執行 morning_brief.py 至少一次。`
    );
  }
}

function wireUniverseChips() {
  $$(".chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".chip").forEach((b) => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      STATE.universeSize = parseInt(btn.dataset.n, 10);
      refresh();
    });
  });
}

function wireTabs() {
  $$(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".tab").forEach((b) => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      STATE.section = btn.dataset.section;
      const brief = STATE.cache.get(STATE.universeSize);
      if (brief) renderSection(brief, STATE.section);
      refreshWatchlistToolbar();
    });
  });
}

function wireTutorial() {
  const panel = $("#tutorialPanel");
  $("#tutorialToggle").addEventListener("click", () => {
    const collapsed = panel.dataset.collapsed === "true";
    panel.dataset.collapsed = collapsed ? "false" : "true";
    $("#tutorialToggle").setAttribute("aria-expanded", collapsed ? "true" : "false");
  });
}

function wireRefresh() {
  $("#refreshBtn").addEventListener("click", () => {
    STATE.cache.clear();
    refresh();
  });
}

function wireWatchlist() {
  $("#watchlistEdit").addEventListener("click", openEditor);

  $$("#editor [data-close]").forEach((el) =>
    el.addEventListener("click", closeEditor)
  );
  $("#watchlistSave").addEventListener("click", () => {
    STATE.watchlist = parseWatchlistInput($("#watchlistInput").value);
    saveWatchlist(STATE.watchlist);
    closeEditor();
    refresh();
  });
  $$("#watchlistQuickadd button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const ta = $("#watchlistInput");
      const cur = parseWatchlistInput(ta.value);
      const add = btn.dataset.add;
      if (!cur.includes(add)) cur.push(add);
      ta.value = cur.join("\n");
    });
  });
}

function openEditor() {
  $("#watchlistInput").value = STATE.watchlist.join("\n");
  $("#editor").setAttribute("aria-hidden", "false");
}
function closeEditor() {
  $("#editor").setAttribute("aria-hidden", "true");
}

function wireModal() {
  $(".modal__close").addEventListener("click", closeModal);
  $(".modal__scrim").addEventListener("click", closeModal);
  $$(".modal__tab").forEach((btn) =>
    btn.addEventListener("click", () => loadModalChart(btn.dataset.chartTab))
  );
}

document.addEventListener("DOMContentLoaded", () => {
  STATE.watchlist = loadWatchlist();
  wireUniverseChips();
  wireTabs();
  wireTutorial();
  wireRefresh();
  wireWatchlist();
  wireModal();
  refresh();
});
