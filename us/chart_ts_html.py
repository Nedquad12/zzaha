"""
chart_ts_html.py — Generate TradingView-style interactive HTML chart
untuk Total Score vs Price (replika chart_ts.py versi interaktif)

Panel atas : candlestick price
Panel bawah: line total score dengan area fill hijau/merah + garis nol

Dipanggil via /ch ts TICKER (pilih format HTML)
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import io
import json
import logging

from score_history import load_score_history

logger = logging.getLogger(__name__)


def generate_ts_html_chart(ticker: str) -> io.BytesIO:
    """
    Generate interactive HTML Total Score vs Price chart.

    Args:
        ticker: kode saham (e.g. "AAPL")

    Returns:
        BytesIO berisi file HTML

    Raises:
        ValueError jika data tidak tersedia
    """
    history = load_score_history(ticker)
    if not history:
        raise ValueError(
            f"Tidak ada score history untuk {ticker}. "
            f"Jalankan /9 terlebih dahulu."
        )

    # ── Parse & serialize data ─────────────────────────────────────────────
    bars = []
    for h in history:
        try:
            bars.append({
                "t":  h["date"][:10],
                "o":  round(float(h.get("open",  h["price"])), 4),
                "h":  round(float(h.get("high",  h["price"])), 4),
                "l":  round(float(h.get("low",   h["price"])), 4),
                "c":  round(float(h["price"]), 4),
                "v":  int(h.get("volume", 0)),
                "sc": round(float(h["total"]), 2),
            })
        except Exception:
            continue

    if not bars:
        raise ValueError(f"Data kosong untuk {ticker}")

    last      = bars[-1]
    prev      = bars[-2] if len(bars) > 1 else last
    chg_pct   = (last["c"] - prev["c"]) / prev["c"] * 100 if prev["c"] else 0
    last_score = last["sc"]
    last_date  = last["t"]
    chg_sign   = "+" if chg_pct >= 0 else ""
    price_color = "#089981" if chg_pct >= 0 else "#f23645"
    score_color = "#089981" if last_score >= 0 else "#f23645"

    data_json = json.dumps(bars)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{ticker} — Total Score Chart</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#0d0d0d; color:#d1d4dc; font-family:'Trebuchet MS',monospace; overflow:hidden; height:100vh; display:flex; flex-direction:column; }}

  #header {{ background:#161616; border-bottom:1px solid #2a2a2a; padding:10px 16px; display:flex; align-items:center; gap:16px; flex-shrink:0; }}
  #ticker-name {{ font-size:20px; font-weight:700; color:#fff; letter-spacing:1px; }}
  #price {{ font-size:22px; font-weight:600; color:{price_color}; }}
  #change {{ font-size:14px; color:{price_color}; }}
  #score-badge {{ font-size:14px; font-weight:600; color:{score_color}; margin-left:4px; }}
  #date-info {{ font-size:12px; color:#555; margin-left:auto; }}
  #bars-badge {{ background:#1e2d3d; color:#4a9eff; font-size:11px; padding:3px 10px; border-radius:4px; border:1px solid #2a4a6a; }}

  #ohlcv-bar {{ background:#161616; padding:5px 16px; display:flex; gap:20px; font-size:11px; flex-shrink:0; border-bottom:1px solid #1a1a1a; }}
  .ob-lbl {{ color:#555; }}
  .ob-val {{ color:#d1d4dc; }}

  #toolbar {{ background:#161616; border-bottom:1px solid #1a1a1a; padding:5px 16px; display:flex; gap:8px; align-items:center; flex-shrink:0; }}
  .tb-btn {{ background:transparent; border:1px solid #2a2a2a; color:#888; font-size:11px; padding:4px 10px; border-radius:4px; cursor:pointer; transition:all 0.15s; }}
  .tb-btn:hover {{ background:#222; color:#ccc; border-color:#444; }}
  .tb-sep {{ width:1px; height:18px; background:#2a2a2a; }}

  #chart-wrap {{ flex:1; display:flex; flex-direction:column; overflow:hidden; position:relative; }}
  #price-canvas {{ display:block; width:100%; cursor:crosshair; }}
  #score-canvas {{ display:block; width:100%; cursor:crosshair; border-top:1px solid #1a1a1a; flex-shrink:0; }}

  #xhair-lbl {{ position:absolute; background:rgba(0,0,0,0.88); border:1px solid #333; padding:7px 11px; font-size:11px; pointer-events:none; display:none; border-radius:4px; line-height:1.8; z-index:100; white-space:nowrap; }}

  #legend {{ position:absolute; top:8px; left:12px; background:rgba(0,0,0,0.65); padding:5px 10px; border-radius:4px; font-size:10px; display:flex; gap:12px; pointer-events:none; }}
  .leg-i {{ display:flex; align-items:center; gap:5px; }}
  .leg-d {{ width:12px; height:3px; border-radius:1px; }}

  #scrollbar-wrap {{ height:14px; background:#0a0a0a; border-top:1px solid #1a1a1a; flex-shrink:0; position:relative; cursor:pointer; }}
  #scrollbar-thumb {{ position:absolute; height:100%; background:#2a2a2a; border-radius:2px; cursor:grab; }}
  #scrollbar-thumb:hover {{ background:#3a3a3a; }}
</style>
</head>
<body>

<div id="header">
  <span id="ticker-name">{ticker}</span>
  <span id="price">${last["c"]:.2f}</span>
  <span id="change">({chg_sign}{chg_pct:.2f}%)</span>
  <span id="score-badge">Score: {last_score:+.1f}</span>
  <span id="bars-badge">{len(bars)} bars</span>
  <span id="date-info">{last_date}</span>
</div>

<div id="ohlcv-bar">
  <div><span class="ob-lbl">O </span><span class="ob-val" id="hb-o">—</span></div>
  <div><span class="ob-lbl">H </span><span class="ob-val" id="hb-h">—</span></div>
  <div><span class="ob-lbl">L </span><span class="ob-val" id="hb-l">—</span></div>
  <div><span class="ob-lbl">C </span><span class="ob-val" id="hb-c">—</span></div>
  <div><span class="ob-lbl">Score </span><span class="ob-val" id="hb-sc">—</span></div>
</div>

<div id="toolbar">
  <button class="tb-btn" id="btn-fit">Fit All</button>
  <button class="tb-btn" id="btn-zi">Zoom +</button>
  <button class="tb-btn" id="btn-zo">Zoom −</button>
  <div class="tb-sep"></div>
  <span style="font-size:10px;color:#555;">Scroll = zoom &nbsp;|&nbsp; Drag = pan</span>
</div>

<div id="chart-wrap">
  <canvas id="price-canvas"></canvas>
  <canvas id="score-canvas"></canvas>
  <div id="xhair-lbl"></div>
  <div id="legend">
    <div class="leg-i"><div class="leg-d" style="background:#089981"></div><span style="color:#aaa">Bullish</span></div>
    <div class="leg-i"><div class="leg-d" style="background:#f23645"></div><span style="color:#aaa">Bearish</span></div>
    <div class="leg-i"><div class="leg-d" style="background:#f23645;width:20px"></div><span style="color:#aaa">Total Score</span></div>
  </div>
</div>

<div id="scrollbar-wrap">
  <div id="scrollbar-thumb"></div>
</div>

<script>
const DATA = {data_json};

const BULL='#089981', BEAR='#f23645', SCORE_C='#f23645', ZERO_C='#444444';
const PANEL='#111111', GRID='#1e1e1e', TEXT='#555', BG='#0d0d0d';
const PAW = 80;   // price axis width (right)
const SAW = 60;   // score axis width (right)
const DAH = 22;   // date axis height (bottom)
const SCORE_PANEL_H = 130;  // fixed height for score panel

const pc = document.getElementById('price-canvas');
const sc = document.getElementById('score-canvas');
const pctx = pc.getContext('2d');
const sctx = sc.getContext('2d');
const wrap = document.getElementById('chart-wrap');
const sbWrap = document.getElementById('scrollbar-wrap');
const thumb  = document.getElementById('scrollbar-thumb');

let vStart = 0, vEnd = DATA.length;
let drag = false, dragX0 = 0, dragVS0 = 0;
let sbDrag = false, sbDX = 0;

function resize() {{
  const W = wrap.clientWidth;
  const H = wrap.clientHeight;
  const pH = H - SCORE_PANEL_H;
  pc.width = W; pc.height = pH;
  sc.width = W; sc.height = SCORE_PANEL_H;
  draw();
}}

// ── Price range for visible bars ──────────────────────────────────────────────
function priceRange() {{
  let mn = Infinity, mx = -Infinity;
  for (let i = vStart; i < vEnd; i++) {{
    if (i < 0 || i >= DATA.length) continue;
    mn = Math.min(mn, DATA[i].l);
    mx = Math.max(mx, DATA[i].h);
  }}
  const pad = (mx - mn) * 0.06;
  return {{ min: mn - pad, max: mx + pad }};
}}

// ── Score range for visible bars ──────────────────────────────────────────────
function scoreRange() {{
  let mn = Infinity, mx = -Infinity;
  for (let i = vStart; i < vEnd; i++) {{
    if (i < 0 || i >= DATA.length) continue;
    mn = Math.min(mn, DATA[i].sc);
    mx = Math.max(mx, DATA[i].sc);
  }}
  const pad = (mx - mn) * 0.12 || 1;
  return {{ min: mn - pad, max: mx + pad }};
}}

function bw() {{ return Math.max(1, (pc.width - PAW) / (vEnd - vStart)); }}

function toXp(i) {{
  const n = vEnd - vStart;
  const cw = pc.width - PAW;
  return (i - vStart + 0.5) * (cw / n);
}}

function toXs(i) {{
  const n = vEnd - vStart;
  const cw = sc.width - SAW;
  return (i - vStart + 0.5) * (cw / n);
}}

function toYp(price, range) {{
  const h = pc.height - DAH;
  return h - ((price - range.min) / (range.max - range.min)) * h;
}}

function toYs(score, range) {{
  const h = sc.height - DAH;
  return h - ((score - range.min) / (range.max - range.min)) * h;
}}

// ── Main draw ─────────────────────────────────────────────────────────────────
function draw() {{
  const pW = pc.width, pH = pc.height;
  const sW = sc.width, sH = sc.height;
  const pr = priceRange();
  const sr = scoreRange();
  const _bw = bw();
  const n = vEnd - vStart;

  // Backgrounds
  pctx.fillStyle = PANEL; pctx.fillRect(0, 0, pW, pH);
  sctx.fillStyle = '#0a0a0a'; sctx.fillRect(0, 0, sW, sH);

  // ── Price grid ──────────────────────────────────────────────────────────
  const nGP = 6;
  pctx.strokeStyle = GRID; pctx.lineWidth = 0.5;
  pctx.font = '10px monospace'; pctx.fillStyle = TEXT; pctx.textAlign = 'left';
  for (let i = 0; i <= nGP; i++) {{
    const y = (pH - DAH) * i / nGP;
    pctx.beginPath(); pctx.moveTo(0, y); pctx.lineTo(pW - PAW, y); pctx.stroke();
    const price = pr.max - (pr.max - pr.min) * i / nGP;
    pctx.fillText('$' + price.toFixed(2), pW - PAW + 6, y + 4);
  }}

  // ── Date axis (price panel) ─────────────────────────────────────────────
  const step = Math.max(1, Math.floor(n / 8));
  pctx.fillStyle = TEXT; pctx.font = '10px monospace'; pctx.textAlign = 'center';
  for (let i = vStart; i < vEnd; i += step) {{
    if (i < 0 || i >= DATA.length) continue;
    pctx.fillText(DATA[i].t.slice(5), toXp(i), pH - 6);
  }}

  // ── Candles ─────────────────────────────────────────────────────────────
  for (let i = vStart; i < vEnd; i++) {{
    if (i < 0 || i >= DATA.length) continue;
    const d = DATA[i];
    const x = toXp(i);
    const color = d.c >= d.o ? BULL : BEAR;
    const bh = Math.max(1, Math.abs(toYp(d.c, pr) - toYp(d.o, pr)));
    const by = Math.min(toYp(d.o, pr), toYp(d.c, pr));
    pctx.fillStyle = color;
    pctx.fillRect(x - _bw * 0.38, by, _bw * 0.76, bh);
    pctx.strokeStyle = color;
    pctx.lineWidth = Math.max(1, _bw * 0.1);
    pctx.beginPath();
    pctx.moveTo(x, toYp(d.h, pr));
    pctx.lineTo(x, toYp(d.l, pr));
    pctx.stroke();
  }}

  // ── Score grid ──────────────────────────────────────────────────────────
  const nGS = 4;
  sctx.strokeStyle = GRID; sctx.lineWidth = 0.5;
  sctx.font = '9px monospace'; sctx.fillStyle = TEXT; sctx.textAlign = 'left';
  for (let i = 0; i <= nGS; i++) {{
    const y = (sH - DAH) * i / nGS;
    sctx.beginPath(); sctx.moveTo(0, y); sctx.lineTo(sW - SAW, y); sctx.stroke();
    const val = sr.max - (sr.max - sr.min) * i / nGS;
    sctx.fillText((val >= 0 ? '+' : '') + val.toFixed(1), sW - SAW + 4, y + 3);
  }}

  // ── Zero line ───────────────────────────────────────────────────────────
  const yZero = toYs(0, sr);
  if (yZero >= 0 && yZero <= sH - DAH) {{
    sctx.strokeStyle = ZERO_C; sctx.lineWidth = 0.8; sctx.setLineDash([4, 4]);
    sctx.beginPath(); sctx.moveTo(0, yZero); sctx.lineTo(sW - SAW, yZero); sctx.stroke();
    sctx.setLineDash([]);
  }}

  // ── Score fill areas (green above zero, red below) ──────────────────────
  const scores = [];
  for (let i = vStart; i < vEnd; i++) {{
    if (i >= 0 && i < DATA.length) scores.push({{ i, sc: DATA[i].sc }});
  }}

  if (scores.length > 1) {{
    // Green area (above zero)
    sctx.beginPath();
    sctx.moveTo(toXs(scores[0].i), Math.min(yZero, toYs(Math.max(0, scores[0].sc), sr)));
    for (const p of scores) {{
      sctx.lineTo(toXs(p.i), toYs(Math.max(0, p.sc), sr));
    }}
    sctx.lineTo(toXs(scores[scores.length - 1].i), yZero);
    sctx.closePath();
    sctx.fillStyle = BULL + '28';
    sctx.fill();

    // Red area (below zero)
    sctx.beginPath();
    sctx.moveTo(toXs(scores[0].i), Math.max(yZero, toYs(Math.min(0, scores[0].sc), sr)));
    for (const p of scores) {{
      sctx.lineTo(toXs(p.i), toYs(Math.min(0, p.sc), sr));
    }}
    sctx.lineTo(toXs(scores[scores.length - 1].i), yZero);
    sctx.closePath();
    sctx.fillStyle = BEAR + '28';
    sctx.fill();

    // Score line
    sctx.beginPath();
    sctx.moveTo(toXs(scores[0].i), toYs(scores[0].sc, sr));
    for (const p of scores) {{
      sctx.lineTo(toXs(p.i), toYs(p.sc, sr));
    }}
    sctx.strokeStyle = SCORE_C;
    sctx.lineWidth = 1.4;
    sctx.setLineDash([]);
    sctx.stroke();

    // Last point dot
    const lastP = scores[scores.length - 1];
    sctx.beginPath();
    sctx.arc(toXs(lastP.i), toYs(lastP.sc, sr), 4, 0, Math.PI * 2);
    sctx.fillStyle = SCORE_C;
    sctx.fill();
  }}

  // ── Score min/max annotations ───────────────────────────────────────────
  let maxSc = -Infinity, minSc = Infinity, maxIdx = 0, minIdx = 0;
  for (let i = vStart; i < vEnd; i++) {{
    if (i < 0 || i >= DATA.length) continue;
    if (DATA[i].sc > maxSc) {{ maxSc = DATA[i].sc; maxIdx = i; }}
    if (DATA[i].sc < minSc) {{ minSc = DATA[i].sc; minIdx = i; }}
  }}
  sctx.font = 'bold 10px monospace';
  sctx.textAlign = 'center';
  if (maxSc > -Infinity) {{
    sctx.fillStyle = BULL;
    sctx.fillText((maxSc >= 0 ? '+' : '') + maxSc.toFixed(0), toXs(maxIdx), toYs(maxSc, sr) - 5);
  }}
  if (minSc < Infinity && minIdx !== maxIdx) {{
    sctx.fillStyle = BEAR;
    sctx.fillText((minSc >= 0 ? '+' : '') + minSc.toFixed(0), toXs(minIdx), toYs(minSc, sr) + 13);
  }}

  // ── Score date axis ─────────────────────────────────────────────────────
  sctx.fillStyle = TEXT; sctx.font = '9px monospace'; sctx.textAlign = 'center';
  for (let i = vStart; i < vEnd; i += step) {{
    if (i < 0 || i >= DATA.length) continue;
    // Format: "Jan '25"
    const d = new Date(DATA[i].t);
    const mo = d.toLocaleString('en', {{ month: 'short' }});
    const yr = ("'" + String(d.getFullYear()).slice(2));
    sctx.fillText(mo + ' ' + yr, toXs(i), sH - 6);
  }}

  updateScrollbar();
}}

function updateScrollbar() {{
  const total = DATA.length, shown = vEnd - vStart;
  const ww = sbWrap.clientWidth;
  const tw = Math.max(24, (shown / total) * ww);
  const tx = (vStart / total) * ww;
  thumb.style.width = tw + 'px';
  thumb.style.left  = tx + 'px';
}}

// ── Interactions ───────────────────────────────────────────────────────────────

// Zoom — wheel on either canvas
function onWheel(e) {{
  e.preventDefault();
  const n = vEnd - vStart;
  const delta = e.deltaY > 0 ? 1 : -1;
  const newN = Math.min(DATA.length, Math.max(10, n + delta * Math.max(1, Math.floor(n * 0.05))));
  const mid  = (vStart + vEnd) / 2;
  vStart = Math.max(0, Math.round(mid - newN / 2));
  vEnd   = Math.min(DATA.length, vStart + newN);
  draw();
}}
pc.addEventListener('wheel', onWheel, {{ passive: false }});
sc.addEventListener('wheel', onWheel, {{ passive: false }});

// Pan — drag on either canvas
function onMouseDown(e) {{ drag = true; dragX0 = e.clientX; dragVS0 = vStart; }}
pc.addEventListener('mousedown', onMouseDown);
sc.addEventListener('mousedown', onMouseDown);

document.addEventListener('mousemove', e => {{
  if (drag) {{
    const n   = vEnd - vStart;
    const _bw = (pc.width - PAW) / n;
    const shift = -Math.round((e.clientX - dragX0) / _bw);
    vStart = Math.max(0, Math.min(DATA.length - n, dragVS0 + shift));
    vEnd   = vStart + n;
    draw();
  }}
  // Crosshair: check which canvas the mouse is over
  const pr = pc.getBoundingClientRect();
  const sr = sc.getBoundingClientRect();
  if (e.clientY >= pr.top && e.clientY <= pr.bottom) {{
    updateXhair(e, pr, true);
  }} else if (e.clientY >= sr.top && e.clientY <= sr.bottom) {{
    updateXhair(e, sr, false);
  }}
}});

document.addEventListener('mouseup', () => {{ drag = false; }});

function hideXhair() {{
  document.getElementById('xhair-lbl').style.display = 'none';
}}
pc.addEventListener('mouseleave', hideXhair);
sc.addEventListener('mouseleave', hideXhair);

function updateXhair(e, rect, isPricePanel) {{
  const canvas  = isPricePanel ? pc : sc;
  const axisW   = isPricePanel ? PAW : SAW;
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  if (x < 0 || x > canvas.width - axisW || y < 0 || y > canvas.height - DAH) {{
    hideXhair(); return;
  }}
  const n = vEnd - vStart;
  const cw = canvas.width - axisW;
  const idx = Math.round(vStart + x / (cw / n) - 0.5);
  if (idx < 0 || idx >= DATA.length) return;

  const d = DATA[idx];
  const color  = d.c >= d.o ? BULL : BEAR;
  const scColor = d.sc >= 0 ? BULL : BEAR;
  const chg = ((d.c - d.o) / d.o * 100).toFixed(2);
  const vol = d.v > 1e6 ? (d.v / 1e6).toFixed(2) + 'M' : d.v > 1e3 ? (d.v / 1e3).toFixed(0) + 'K' : d.v || '—';

  const lbl = document.getElementById('xhair-lbl');
  lbl.innerHTML =
    `<span style="color:#555;font-size:9px">${{d.t}}</span><br>` +
    `<span style="color:#888">O</span> <b style="color:${{color}}">${{d.o.toFixed(2)}}</b> ` +
    `<span style="color:#888">H</span> <b style="color:${{color}}">${{d.h.toFixed(2)}}</b> ` +
    `<span style="color:#888">L</span> <b style="color:${{color}}">${{d.l.toFixed(2)}}</b> ` +
    `<span style="color:#888">C</span> <b style="color:${{color}}">${{d.c.toFixed(2)}}</b><br>` +
    `<span style="color:${{color}}">${{d.c >= d.o ? '+' : ''}}${{chg}}%</span>  ` +
    `<span style="color:#888">Score</span> <b style="color:${{scColor}}">${{d.sc >= 0 ? '+' : ''}}${{d.sc.toFixed(1)}}</b>`;

  lbl.style.display = 'block';

  // Position relative to chart-wrap
  const wrapRect = document.getElementById('chart-wrap').getBoundingClientRect();
  const tx = Math.min(e.clientX - wrapRect.left + 14, pc.width - 190);
  const ty = Math.max(0, e.clientY - wrapRect.top - 70);
  lbl.style.left = tx + 'px';
  lbl.style.top  = ty + 'px';

  // Update OHLCV bar
  document.getElementById('hb-o').textContent  = '$' + d.o.toFixed(2);
  document.getElementById('hb-h').textContent  = '$' + d.h.toFixed(2);
  document.getElementById('hb-l').textContent  = '$' + d.l.toFixed(2);
  document.getElementById('hb-c').textContent  = '$' + d.c.toFixed(2);
  document.getElementById('hb-c').style.color  = color;
  document.getElementById('hb-sc').textContent = (d.sc >= 0 ? '+' : '') + d.sc.toFixed(1);
  document.getElementById('hb-sc').style.color = scColor;
}}

// ── Scrollbar ─────────────────────────────────────────────────────────────────
thumb.addEventListener('mousedown', e => {{
  sbDrag = true; sbDX = e.clientX - thumb.offsetLeft; e.preventDefault();
}});
document.addEventListener('mousemove', e => {{
  if (!sbDrag) return;
  const ww = sbWrap.clientWidth, tw = thumb.clientWidth;
  const tx = Math.max(0, Math.min(ww - tw, e.clientX - sbDX));
  const ratio = tx / (ww - tw);
  const n = vEnd - vStart;
  vStart = Math.round(ratio * (DATA.length - n));
  vEnd   = vStart + n;
  draw();
}});
document.addEventListener('mouseup', () => {{ sbDrag = false; }});
sbWrap.addEventListener('click', e => {{
  if (e.target === thumb) return;
  const n = vEnd - vStart;
  vStart = Math.max(0, Math.min(DATA.length - n, Math.round(e.offsetX / sbWrap.clientWidth * DATA.length - n / 2)));
  vEnd   = vStart + n;
  draw();
}});

// ── Toolbar ───────────────────────────────────────────────────────────────────
document.getElementById('btn-fit').addEventListener('click', () => {{
  vStart = 0; vEnd = DATA.length; draw();
}});
document.getElementById('btn-zi').addEventListener('click', () => {{
  const n = vEnd - vStart, mid = (vStart + vEnd) / 2;
  const newN = Math.max(10, Math.round(n * 0.7));
  vStart = Math.max(0, Math.round(mid - newN / 2));
  vEnd   = Math.min(DATA.length, vStart + newN);
  draw();
}});
document.getElementById('btn-zo').addEventListener('click', () => {{
  const n = vEnd - vStart, mid = (vStart + vEnd) / 2;
  const newN = Math.min(DATA.length, Math.round(n * 1.4));
  vStart = Math.max(0, Math.round(mid - newN / 2));
  vEnd   = Math.min(DATA.length, vStart + newN);
  draw();
}});

// ── Init ──────────────────────────────────────────────────────────────────────
vStart = 0; vEnd = DATA.length;
window.addEventListener('resize', resize);
resize();
</script>
</body>
</html>"""

    buf = io.BytesIO(html.encode("utf-8"))
    buf.seek(0)
    return buf
