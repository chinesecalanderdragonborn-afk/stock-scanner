/* SCOUT front-end — minimal momentum scanner driven by the live backend.
 * Loads over plain HTTP first, upgrades to a websocket for live push, and
 * falls back to HTTP polling if the socket is unavailable. No dependencies.
 */
"use strict";

const $ = (id) => document.getElementById(id);
const fmt = (n, d = 2) => (n == null || isNaN(n)) ? "—" : Number(n).toFixed(d);
const sgn = (v) => (v > 0 ? "+" : "");
function fvol(v) {
  if (v >= 1e9) return (v / 1e9).toFixed(2) + "B";
  if (v >= 1e6) return (v / 1e6).toFixed(2) + "M";
  if (v >= 1e3) return (v / 1e3).toFixed(1) + "K";
  return String(Math.round(v || 0));
}
function hhmmss(t) { return new Date(t * 1000).toLocaleTimeString("en-US", { hour12: false }); }

const state = {
  rows: [], bySym: {}, focus: null, tab: "Trade Ideas", tf: "1m",
  bars: [], serverOffset: 0, provider: null, lastUpdated: -1, wsOK: false,
};

/* ---- signal state derived from metrics ---- */
function signal(m) {
  if (m.halted) return "HALT";
  if (m.change_pct > 0 && Math.abs(m.dist_from_hod_pct) <= 0.6) return "HOD";
  if (m.mom_2min_pct >= 0.4 && m.change_pct > 0) return "RUN";
  if (m.change_pct < 0 && m.mom_2min_pct < 0) return "FADE";
  return m.change_pct >= 0 ? "UP" : "DN";
}

/* ---- tab filters (computed from the full row set) ---- */
const TABS = {
  "Trade Ideas": (rs) => rs.filter((m) => m.price >= 0.5 && m.price <= 2000)
      .map((m) => [m, Math.abs(m.change_pct) * 0.4 + m.mom_2min_pct * 3 + (m.rvol - 1) * 8])
      .sort((a, b) => b[1] - a[1]).map((x) => x[0]),
  "Momentum": (rs) => rs.filter((m) => Math.abs(m.mom_2min_pct) > 0.05).sort((a, b) => b.mom_2min_pct - a.mom_2min_pct),
  "Gappers": (rs) => rs.filter((m) => m.gap_pct >= 2).sort((a, b) => b.gap_pct - a.gap_pct),
  "Low Float": (rs) => rs.filter((m) => m.float_shares > 0 && m.float_shares <= 50e6 && m.change_pct > 0).sort((a, b) => b.change_pct - a.change_pct),
  "Near HOD": (rs) => rs.filter((m) => m.change_pct > 0 && Math.abs(m.dist_from_hod_pct) <= 1).sort((a, b) => b.dist_from_hod_pct - a.dist_from_hod_pct),
  "Halted": (rs) => rs.filter((m) => m.halted),
};

/* ---- render: tabs + table ---- */
function renderTabs() {
  const el = $("tabs"); el.innerHTML = "";
  Object.keys(TABS).forEach((name) => {
    const b = document.createElement("button");
    b.className = "tab" + (name === state.tab ? " active" : "");
    b.textContent = name;
    b.onclick = () => { state.tab = name; renderTabs(); renderTable(); };
    el.appendChild(b);
  });
}
function renderTable() {
  const rows = TABS[state.tab](state.rows).slice(0, 16);
  const tb = $("rows"); tb.innerHTML = "";
  if (!rows.length) {
    tb.innerHTML = '<tr><td colspan="6" class="muted" style="text-align:center;padding:24px">— no names match this filter right now —</td></tr>';
    return;
  }
  for (const m of rows) {
    const s = signal(m);
    const tr = document.createElement("tr");
    if (m.symbol === state.focus) tr.className = "sel";
    const chgCls = m.change_pct > 0 ? "up" : m.change_pct < 0 ? "down" : "muted";
    tr.innerHTML = `<td class="sym">${m.symbol}</td>
      <td class="mono">${fmt(m.price, m.price < 1 ? 3 : 2)}</td>
      <td class="mono ${chgCls}"><span class="pill ${m.change_pct > 0 ? "pos" : m.change_pct < 0 ? "neg" : ""}">${sgn(m.change_pct)}${fmt(m.change_pct, 1)}%</span></td>
      <td class="mono">${fmt(m.rvol, 1)}×</td>
      <td class="mono sub">${m.float_shares ? fvol(m.float_shares) : "—"}</td>
      <td><span class="state s-${s}">${s}</span></td>`;
    tr.onclick = () => selectFocus(m.symbol);
    tb.appendChild(tr);
  }
}

/* ---- render: detail + chart ---- */
async function selectFocus(sym) {
  state.focus = sym;
  renderTable();
  renderDetailHeader();
  await loadBars();
}
function renderDetailHeader() {
  const m = state.bySym[state.focus];
  if (!m) return;
  $("cSym").textContent = m.symbol;
  $("cPrice").textContent = fmt(m.price, m.price < 1 ? 3 : 2);
  const cc = $("cChg");
  cc.textContent = `${sgn(m.change_pct)}${fmt(m.change_pct, 2)}%`;
  cc.className = "cc mono " + (m.change_pct > 0 ? "up" : m.change_pct < 0 ? "down" : "muted");
  $("cMeta").textContent =
    `${m.exchange || m.sector || ""} · Float ${m.float_shares ? fvol(m.float_shares) : "—"} · RVol ${fmt(m.rvol, 1)}× · Rot ${fmt(m.float_rotation, 2)}×`;
  const st = [["VWAP", fmt(m.vwap, 2)], ["HOD", fmt(m.hod, 2)], ["LOD", fmt(m.lod, 2)],
    ["ATR", fmt(m.atr, 3)], ["Gap%", sgn(m.gap_pct) + fmt(m.gap_pct, 1)],
    ["2-Min", sgn(m.mom_2min_pct) + fmt(m.mom_2min_pct, 1) + "%"]];
  $("stats").innerHTML = st.map(([k, v]) =>
    `<div class="stat"><div class="k">${k}</div><div class="v mono">${v}</div></div>`).join("");
}
async function loadBars() {
  if (!state.focus) return;
  try {
    const r = await fetch(`/api/bars/${state.focus}?interval=${state.tf}`, { cache: "no-store" });
    if (!r.ok) { state.bars = []; drawChart(); return; }
    state.bars = (await r.json()).bars || [];
    drawChart();
  } catch (e) { /* ignore */ }
}
function css(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }
function drawChart() {
  const cv = $("chart"), wrap = cv.parentElement, bars = state.bars;
  const dpr = window.devicePixelRatio || 1;
  const W = wrap.clientWidth, H = wrap.clientHeight;
  cv.width = W * dpr; cv.height = H * dpr;
  const x = cv.getContext("2d"); x.setTransform(dpr, 0, 0, dpr, 0, 0); x.clearRect(0, 0, W, H);
  if (!bars.length) return;
  const padR = 54, padB = 22, padT = 10, padL = 8;
  const pw = W - padR - padL, ph = H - padB - padT, volH = ph * 0.20, priceH = ph - volH - 6;
  let hi = -1e9, lo = 1e9, mv = 0;
  for (const b of bars) { hi = Math.max(hi, b.h); lo = Math.min(lo, b.l); mv = Math.max(mv, b.v); }
  const pad = (hi - lo) * 0.08 || 1; hi += pad; lo -= pad;
  const px = (i) => padL + (i + 0.5) * (pw / bars.length);
  const py = (p) => padT + (1 - (p - lo) / (hi - lo)) * priceH;
  const vy = (v) => padT + priceH + 6 + (1 - v / mv) * volH;
  const cUp = css("--up"), cDn = css("--down"), cLine = css("--line"), cMut = css("--faint"), cAcc = css("--accent"), cBg = css("--bg");
  x.strokeStyle = cLine; x.fillStyle = cMut; x.font = '10px "SF Mono",Menlo,monospace'; x.lineWidth = 1;
  for (let i = 0; i <= 4; i++) { const p = lo + (hi - lo) * i / 4, yy = py(p); x.globalAlpha = .5; x.beginPath(); x.moveTo(padL, yy); x.lineTo(padL + pw, yy); x.stroke(); x.globalAlpha = 1; x.fillText(p.toFixed(p < 1 ? 3 : 2), padL + pw + 6, yy + 3); }
  let pv = 0, cv2 = 0;
  const vw = bars.map((b) => { const tp = (b.h + b.l + b.c) / 3; pv += tp * b.v; cv2 += b.v; return cv2 ? pv / cv2 : b.c; });
  x.strokeStyle = cAcc; x.globalAlpha = .85; x.setLineDash([4, 3]); x.beginPath();
  vw.forEach((p, i) => { const xx = px(i), yy = py(p); i ? x.lineTo(xx, yy) : x.moveTo(xx, yy); }); x.stroke(); x.setLineDash([]); x.globalAlpha = 1;
  const cw = Math.max(1, (pw / bars.length) * 0.62);
  bars.forEach((b, i) => {
    const up = b.c >= b.o, col = up ? cUp : cDn, xx = px(i);
    x.globalAlpha = .28; x.fillStyle = col; const vY = vy(b.v), vB = padT + priceH + 6 + volH; x.fillRect(xx - cw / 2, vY, cw, vB - vY); x.globalAlpha = 1;
    x.strokeStyle = col; x.beginPath(); x.moveTo(xx, py(b.h)); x.lineTo(xx, py(b.l)); x.stroke();
    x.fillStyle = col; const yo = py(b.o), yc = py(b.c); x.fillRect(xx - cw / 2, Math.min(yo, yc), cw, Math.max(1, Math.abs(yc - yo)));
  });
  const last = bars[bars.length - 1].c, upDay = last >= bars[0].o, col = upDay ? cUp : cDn;
  x.strokeStyle = col; x.globalAlpha = .6; x.setLineDash([2, 2]); x.beginPath(); x.moveTo(padL, py(last)); x.lineTo(padL + pw, py(last)); x.stroke(); x.setLineDash([]); x.globalAlpha = 1;
  x.fillStyle = col; x.fillRect(padL + pw, py(last) - 8, padR, 16); x.fillStyle = cBg; x.fillText(last.toFixed(last < 1 ? 3 : 2), padL + pw + 6, py(last) + 3);
}

/* ---- indices / news ---- */
function renderIdx(indices) {
  $("idx").innerHTML = (indices || []).map((i) => {
    const cls = i.change_pct >= 0 ? "up" : "down";
    return `<div class="i"><span class="n">${i.name}</span><span class="v mono ${cls}">${sgn(i.change_pct)}${fmt(i.change_pct, 2)}%</span></div>`;
  }).join("");
}
function renderNews(news) {
  const el = $("news");
  if (!news || !news.length) { el.innerHTML = '<div class="row muted">— wire quiet —</div>'; return; }
  el.innerHTML = news.slice(0, 3).map((n) =>
    `<div class="row"><span class="tm mono">${hhmmss(n.t)}</span><span class="sy" data-sym="${n.symbol}">${n.symbol}</span><span class="hd">${n.headline}</span></div>`).join("");
  el.querySelectorAll(".sy").forEach((s) => s.onclick = () => selectFocus(s.dataset.sym));
}

/* ---- clock ---- */
function serverNow() { return Date.now() / 1000 + state.serverOffset; }
function clock() {
  $("clock").textContent = hhmmss(serverNow());
  const d = new Date(serverNow() * 1000), cl = new Date(d); cl.setHours(16, 0, 0, 0);
  let s = Math.max(0, Math.floor((cl - d) / 1000));
  $("cd").textContent = `${String(Math.floor(s / 3600)).padStart(2, "0")}:${String(Math.floor(s % 3600 / 60)).padStart(2, "0")}`;
}

/* ---- snapshot ---- */
function applySnapshot(msg) {
  if (!msg || msg.updated === state.lastUpdated) return;
  state.lastUpdated = msg.updated;
  state.serverOffset = msg.server_time - Date.now() / 1000;
  state.provider = msg.provider;
  const mode = $("mode");
  mode.textContent = msg.provider === "yahoo" ? "LIVE" : "SIM";
  mode.className = "chip " + (msg.provider === "yahoo" ? "live" : "sim");

  if (msg.loading) { $("status").textContent = "● loading market data…"; $("status").className = ""; return; }

  state.rows = msg.rows || [];
  state.bySym = {}; state.rows.forEach((m) => (state.bySym[m.symbol] = m));
  renderTable();
  renderIdx(msg.indices);
  renderNews(msg.news);

  if (!state.focus && state.rows.length) {
    const ideas = TABS["Trade Ideas"](state.rows);
    selectFocus((ideas[0] || state.rows[0]).symbol);
  } else if (state.focus) {
    renderDetailHeader();
    loadBars();
  }
  $("lastUpdate").textContent =
    (msg.provider === "yahoo" ? "live · " : "sim · ") + "updated " + hhmmss(msg.updated);
}

/* ---- transport ---- */
async function fetchSnapshotOnce() {
  try { const r = await fetch("/api/snapshot", { cache: "no-store" }); if (r.ok) applySnapshot(await r.json()); return true; }
  catch (e) { return false; }
}
function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  let sock;
  try { sock = new WebSocket(`${proto}://${location.host}/ws`); } catch (e) { return; }
  const st = $("status");
  sock.onopen = () => { state.wsOK = true; st.textContent = "● live"; st.className = "ok"; };
  sock.onmessage = (ev) => applySnapshot(JSON.parse(ev.data));
  sock.onclose = () => { state.wsOK = false; st.textContent = "● reconnecting…"; st.className = "err"; setTimeout(connectWS, 2000); };
  sock.onerror = () => { try { sock.close(); } catch (e) {} };
}

/* ---- boot ---- */
$("tf").querySelectorAll("button").forEach((b) => b.onclick = () => {
  $("tf").querySelectorAll("button").forEach((x) => x.classList.remove("on"));
  b.classList.add("on"); state.tf = b.dataset.tf; loadBars();
});
function initTheme() {
  let t = null; try { t = localStorage.getItem("scout-theme"); } catch (e) {}
  if (t) document.documentElement.setAttribute("data-theme", t);
  $("themeBtn").onclick = () => {
    const cur = document.documentElement.getAttribute("data-theme");
    const isDark = cur ? cur === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    const next = isDark ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("scout-theme", next); } catch (e) {}
    drawChart();
  };
}
window.addEventListener("resize", drawChart);
initTheme(); renderTabs(); clock();
setInterval(clock, 1000);
$("status").textContent = "● loading…";
fetchSnapshotOnce();
connectWS();
setInterval(() => { if (!state.wsOK) fetchSnapshotOnce(); }, 5000);
const bootPoll = setInterval(async () => { if (state.lastUpdated > 0) { clearInterval(bootPoll); return; } await fetchSnapshotOnce(); }, 1500);
