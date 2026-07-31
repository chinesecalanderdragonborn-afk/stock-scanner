/* Trade-ideas dashboard front-end.
 * - Subscribes to /ws for live scan snapshots.
 * - Renders scanner tables, news, halts, index strip.
 * - Draws a candlestick chart for the focused symbol on a <canvas>.
 * No external libraries.
 */
"use strict";

const state = {
  focus: null,
  timeframe: "1m",
  bars: [],
  lastRows: {},        // per-scan: symbol -> mom value, for flash detection
  seenNews: new Set(),
  serverOffset: 0,     // server_time - client_time
};

/* ---------- helpers ---------- */
const $ = (id) => document.getElementById(id);
const fmt = (n, d = 2) =>
  n === undefined || n === null || isNaN(n) ? "—" : Number(n).toFixed(d);
function fmtVol(v) {
  if (v >= 1e9) return (v / 1e9).toFixed(2) + "B";
  if (v >= 1e6) return (v / 1e6).toFixed(2) + "M";
  if (v >= 1e3) return (v / 1e3).toFixed(1) + "K";
  return String(Math.round(v || 0));
}
const cls = (v) => (v > 0 ? "pos" : v < 0 ? "neg" : "muted");
const sign = (v) => (v > 0 ? "+" : "");
function hhmmss(epoch) {
  const d = new Date(epoch * 1000);
  return d.toLocaleTimeString("en-US", { hour12: false });
}

/* ---------- scan tables ---------- */
const SCAN_COLS = {
  momo_up: ["mom_2min_pct", "price", "change_pct", "rvol", "volume"],
  momo_down: ["mom_2min_pct", "price", "change_pct", "rvol", "volume"],
  gappers: ["gap_pct", "price", "change_pct", "rvol", "float_shares"],
  low_float_runners: ["change_pct", "price", "float_shares", "float_rotation", "rvol"],
  near_hod: ["dist_from_hod_pct", "price", "change_pct", "atr_hod", "rvol"],
};
const COL_HEAD = {
  mom_2min_pct: "2Min%", price: "Price", change_pct: "Chg%", rvol: "RVol",
  volume: "Vol", gap_pct: "Gap%", float_shares: "Float", atr_hod: "AtrHoD",
  float_rotation: "Rot", dist_from_hod_pct: "%HoD",
};

function cell(row, key) {
  let v = row[key], text, klass = "";
  switch (key) {
    case "volume": text = fmtVol(v); break;
    case "float_shares": text = fmtVol(v); break;
    case "price": text = fmt(v, v < 1 ? 3 : 2); break;
    case "rvol": text = fmt(v, 1) + "×"; if (v >= 3) klass = "cell-up"; break;
    case "float_rotation": text = fmt(v, 1) + "×"; break;
    case "mom_2min_pct":
    case "change_pct":
    case "gap_pct":
      text = sign(v) + fmt(v, 1) + "%";
      klass = v > 0 ? "cell-up" : v < 0 ? "cell-down" : "";
      break;
    case "dist_from_hod_pct":
      text = fmt(v, 2) + "%"; klass = v >= -0.2 ? "cell-up" : ""; break;
    case "atr_hod": text = fmt(v, 2); break;
    default: text = fmt(v);
  }
  return `<td class="${klass}">${text}</td>`;
}

function renderScan(id, rows) {
  const cols = SCAN_COLS[id];
  const el = $(id);
  if (!rows || !rows.length) {
    el.innerHTML = `<div class="halt-empty">— no signals —</div>`;
    return;
  }
  const prev = state.lastRows[id] || {};
  const now = {};
  const head = `<tr><th>Sym</th>${cols
    .map((c) => `<th>${COL_HEAD[c]}</th>`).join("")}</tr>`;
  const body = rows.map((r) => {
    const key = cols[0];
    now[r.symbol] = r[key];
    const flash = prev[r.symbol] !== undefined && prev[r.symbol] !== r[key];
    return `<tr class="${flash ? "flash" : ""}">
      <td class="sym" data-sym="${r.symbol}">${r.symbol}</td>
      ${cols.map((c) => cell(r, c)).join("")}
    </tr>`;
  }).join("");
  el.innerHTML = `<table>${head}${body}</table>`;
  state.lastRows[id] = now;
  el.querySelectorAll(".sym").forEach((td) =>
    td.addEventListener("click", () => selectFocus(td.dataset.sym)));
}

/* ---------- halts & news ---------- */
function renderHalts(halts) {
  const el = $("halts");
  if (!halts || !halts.length) {
    el.innerHTML = `<div class="halt-empty">— no active halts —</div>`;
    return;
  }
  el.innerHTML = halts.map((h) => `
    <div class="halt-row">
      <span class="hsym" data-sym="${h.symbol}">${h.symbol}</span>
      <span class="hreason">${h.reason}</span>
      <span class="muted">${fmt(h.price, 2)}</span>
    </div>`).join("");
  el.querySelectorAll(".hsym").forEach((s) =>
    s.addEventListener("click", () => selectFocus(s.dataset.sym)));
}

function renderNews(news) {
  const el = $("news");
  if (!news || !news.length) {
    el.innerHTML = `<div class="news-empty">— wire quiet —</div>`;
    return;
  }
  el.innerHTML = news.map((n) => {
    const isNew = !state.seenNews.has(n.t + n.headline);
    state.seenNews.add(n.t + n.headline);
    return `<div class="news-item ${isNew ? "new" : ""}">
      <span class="ntime">${hhmmss(n.t)}</span>
      <span class="nsym" data-sym="${n.symbol}">${n.symbol}</span>
      <span class="nhead">${n.headline}</span>
    </div>`;
  }).join("");
  el.querySelectorAll(".nsym").forEach((s) =>
    s.addEventListener("click", () => selectFocus(s.dataset.sym)));
}

function renderIndices(indices) {
  $("indices").innerHTML = indices.map((i) => `
    <div class="idx">
      <span class="nm">${i.name}</span>
      <span class="vl ${cls(i.change_pct)}">${sign(i.change_pct)}${fmt(i.change_pct, 2)}%</span>
    </div>`).join("");
}

/* ---------- focus panel + chart ---------- */
async function selectFocus(sym) {
  state.focus = sym;
  await loadBars();
}

async function loadBars() {
  if (!state.focus) return;
  try {
    const r = await fetch(`/api/bars/${state.focus}?interval=${state.timeframe}`);
    if (!r.ok) return;
    const data = await r.json();
    state.bars = data.bars;
    const q = await (await fetch(`/api/quote/${state.focus}`)).json();
    updateFocusHeader(q);
    drawChart();
  } catch (e) { /* ignore */ }
}

function updateFocusHeader(q) {
  if (!q || q.error) return;
  $("focus-sym").textContent = q.symbol;
  $("focus-price").textContent = fmt(q.price, q.price < 1 ? 3 : 2);
  const chg = $("focus-chg");
  chg.textContent = `${sign(q.change_pct)}${fmt(q.change_pct, 2)}%`;
  chg.className = "focus-chg " + cls(q.change_pct);
  $("focus-meta").textContent =
    `${q.exchange} · Float ${fmtVol(q.float_shares)} · RVol ${fmt(q.rvol, 1)}×`;
  const stats = [
    ["VWAP", fmt(q.vwap, 2)], ["HOD", fmt(q.hod, 2)], ["LOD", fmt(q.lod, 2)],
    ["ATR", fmt(q.atr, 3)], ["Gap%", sign(q.gap_pct) + fmt(q.gap_pct, 1)],
    ["Rot", fmt(q.float_rotation, 1) + "×"],
  ];
  $("focus-stats").innerHTML = stats.map(([k, v]) =>
    `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");
}

function drawChart() {
  const canvas = $("chart");
  const bars = state.bars;
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth, H = canvas.clientHeight;
  canvas.width = W * dpr; canvas.height = H * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, W, H);
  if (!bars || !bars.length) return;

  const padR = 52, padB = 34, padT = 8, padL = 6;
  const plotW = W - padR - padL, plotH = H - padB - padT;
  const volH = plotH * 0.22, priceH = plotH - volH - 6;

  let hi = -Infinity, lo = Infinity, maxV = 0;
  for (const b of bars) { hi = Math.max(hi, b.h); lo = Math.min(lo, b.l); maxV = Math.max(maxV, b.v); }
  const pad = (hi - lo) * 0.08 || 1;
  hi += pad; lo -= pad;

  const x = (i) => padL + (i + 0.5) * (plotW / bars.length);
  const y = (p) => padT + (1 - (p - lo) / (hi - lo)) * priceH;
  const vy = (v) => padT + priceH + 6 + (1 - v / maxV) * volH;

  // grid + price axis
  ctx.strokeStyle = "#161c28"; ctx.fillStyle = "#5a6578";
  ctx.font = "9px monospace"; ctx.textAlign = "left";
  const steps = 5;
  for (let i = 0; i <= steps; i++) {
    const p = lo + (hi - lo) * (i / steps);
    const yy = y(p);
    ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(padL + plotW, yy); ctx.stroke();
    ctx.fillText(p.toFixed(p < 1 ? 3 : 2), padL + plotW + 4, yy + 3);
  }

  // VWAP line
  let pv = 0, cv = 0;
  const vwapPts = bars.map((b) => {
    const tp = (b.h + b.l + b.c) / 3; pv += tp * b.v; cv += b.v;
    return cv ? pv / cv : b.c;
  });
  ctx.strokeStyle = "#f5a623"; ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
  ctx.beginPath();
  vwapPts.forEach((p, i) => { const xx = x(i), yy = y(p); i ? ctx.lineTo(xx, yy) : ctx.moveTo(xx, yy); });
  ctx.stroke(); ctx.setLineDash([]);

  // candles + volume
  const cw = Math.max(1, (plotW / bars.length) * 0.62);
  bars.forEach((b, i) => {
    const up = b.c >= b.o;
    const color = up ? "#21d07a" : "#ff4d5e";
    const xx = x(i);
    // volume
    ctx.fillStyle = up ? "rgba(33,208,122,0.35)" : "rgba(255,77,94,0.35)";
    const vY = vy(b.v), vBot = padT + priceH + 6 + volH;
    ctx.fillRect(xx - cw / 2, vY, cw, vBot - vY);
    // wick
    ctx.strokeStyle = color; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(xx, y(b.h)); ctx.lineTo(xx, y(b.l)); ctx.stroke();
    // body
    ctx.fillStyle = color;
    const yo = y(b.o), yc = y(b.c);
    ctx.fillRect(xx - cw / 2, Math.min(yo, yc), cw, Math.max(1, Math.abs(yc - yo)));
  });

  // last price line
  const last = bars[bars.length - 1].c;
  const upDay = last >= bars[0].o;
  ctx.strokeStyle = upDay ? "#21d07a" : "#ff4d5e"; ctx.setLineDash([2, 2]);
  ctx.beginPath(); ctx.moveTo(padL, y(last)); ctx.lineTo(padL + plotW, y(last)); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = upDay ? "#21d07a" : "#ff4d5e";
  ctx.fillRect(padL + plotW, y(last) - 7, padR, 14);
  ctx.fillStyle = "#06080c"; ctx.textAlign = "left";
  ctx.fillText(last.toFixed(last < 1 ? 3 : 2), padL + plotW + 4, y(last) + 3);

  // time axis (a few labels)
  ctx.fillStyle = "#5a6578"; ctx.textAlign = "center";
  const labels = 5;
  for (let i = 0; i <= labels; i++) {
    const idx = Math.min(bars.length - 1, Math.round((bars.length - 1) * (i / labels)));
    ctx.fillText(new Date(bars[idx].t * 1000)
      .toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit" }),
      x(idx), H - padB + 14);
  }
}

/* ---------- clock ---------- */
function serverNow() { return Date.now() / 1000 + state.serverOffset; }
function tickClock() {
  const now = serverNow();
  $("clock").textContent = hhmmss(now);
  // countdown to 16:00 local
  const d = new Date(now * 1000);
  const close = new Date(d); close.setHours(16, 0, 0, 0);
  let secs = Math.floor((close - d) / 1000);
  if (secs < 0) secs = 0;
  const h = String(Math.floor(secs / 3600)).padStart(2, "0");
  const m = String(Math.floor((secs % 3600) / 60)).padStart(2, "0");
  const s = String(secs % 60).padStart(2, "0");
  $("countdown").textContent = `${h}:${m}:${s}`;
}

/* ---------- snapshot ---------- */
let lastUpdated = -1;
function applySnapshot(msg) {
  if (!msg || msg.updated === lastUpdated) return;   // skip duplicates
  lastUpdated = msg.updated;
  state.serverOffset = msg.server_time - Date.now() / 1000;

  const tag = $("provider-tag");
  tag.textContent = msg.provider === "yahoo" ? "LIVE" : "SIM";
  tag.className = "tag " + (msg.provider === "yahoo" ? "live" : "sim");

  if (msg.loading) {
    $("status").textContent = "● loading market data…";
    $("status").className = "";
    return;   // nothing to render yet
  }

  Object.keys(SCAN_COLS).forEach((id) => renderScan(id, msg.scans[id]));
  renderHalts(msg.halts);
  renderNews(msg.news);
  renderIndices(msg.indices);

  if (!state.focus) {
    // default to the strongest runner so the chart opens on something moving
    const first = (msg.scans.gappers[0] || msg.scans.momo_up[0] ||
                   msg.scans.low_float_runners[0] ||
                   (msg.focus && { symbol: msg.focus[0] }));
    if (first && first.symbol) selectFocus(first.symbol);
  } else {
    loadBars();   // keep the focused chart fresh
  }
  $("last-update").textContent =
    (msg.provider === "yahoo" ? "live · " : "sim · ") + "updated " + hhmmss(msg.updated);
}

/* ---------- data transport: HTTP first, websocket for live push ---------- */
async function fetchSnapshotOnce() {
  try {
    const r = await fetch("/api/snapshot", { cache: "no-store" });
    if (r.ok) applySnapshot(await r.json());
    return true;
  } catch (e) { return false; }
}

let wsConnected = false;
function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  let sock;
  try { sock = new WebSocket(`${proto}://${location.host}/ws`); }
  catch (e) { return; }
  const st = $("status");
  sock.onopen = () => {
    wsConnected = true;
    st.textContent = "● live"; st.className = "ok";
  };
  sock.onmessage = (ev) => applySnapshot(JSON.parse(ev.data));
  sock.onclose = () => {
    wsConnected = false;
    st.textContent = "● reconnecting…"; st.className = "err";
    setTimeout(connectWS, 2000);
  };
  sock.onerror = () => { try { sock.close(); } catch (e) {} };
}

/* Polling fallback: if the websocket never connects (e.g. blocked by a
 * firewall/proxy), keep the dashboard live over plain HTTP. */
function startPollingFallback() {
  setInterval(() => { if (!wsConnected) fetchSnapshotOnce(); }, 5000);
}

/* ---------- boot ---------- */
document.querySelectorAll(".tf").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tf").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.timeframe = btn.dataset.tf;
    loadBars();
  });
});
window.addEventListener("resize", () => drawChart());
setInterval(tickClock, 1000);
tickClock();

// Render whatever's available right now over HTTP, then attach the live feed.
$("status").textContent = "● loading…";
fetchSnapshotOnce();
connectWS();
startPollingFallback();
// keep retrying the first fetch until data arrives
const bootPoll = setInterval(async () => {
  if (lastUpdated > 0) { clearInterval(bootPoll); return; }
  await fetchSnapshotOnce();
}, 1500);
