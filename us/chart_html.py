"""
chart_html.py — Generate TradingView-style interactive HTML chart
Dikirim ke Telegram via document (file .html)
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import io
import json
import logging
from typing import Optional

import pandas as pd
import numpy as np

from config import (
    CHART_CANDLES,
    SR_METHOD_DONCHIAN, SR_SENSITIVITY, SR_MAX_LEVELS,
)
from indicators.sr import detect_sr, SRLevel

logger = logging.getLogger(__name__)


def _sr_to_dict(levels: list, broken: list) -> dict:
    active = []
    for lv in levels:
        active.append({
            "top": lv.top,
            "btm": lv.btm,
            "base": lv.base_price,
            "is_support": lv.is_support,
            "entries": lv.entries,
            "sweeps": lv.sweeps,
        })
    brok = []
    for lv in broken[-10:]:
        brok.append({
            "base": lv.base_price,
            "is_support": lv.is_support,
        })
    return {"active": active, "broken": brok}


def generate_html_chart(
    ticker: str,
    df: pd.DataFrame,
    method: str = SR_METHOD_DONCHIAN,
    sens: float = SR_SENSITIVITY,
    candles: int = CHART_CANDLES,
) -> io.BytesIO:
    """
    Generate TradingView-style interactive HTML chart.

    Returns:
        BytesIO berisi file HTML
    """
    active, broken = detect_sr(df, method=method, sens=sens)
    df_plot = df.tail(candles).copy().reset_index(drop=True)

    # Serialize OHLCV data
    ohlcv = []
    for _, row in df_plot.iterrows():
        ohlcv.append({
            "t": row["date"].strftime("%Y-%m-%d"),
            "o": round(float(row["open"]), 4),
            "h": round(float(row["high"]), 4),
            "l": round(float(row["low"]), 4),
            "c": round(float(row["close"]), 4),
            "v": int(row["volume"]),
        })

    sr_data = _sr_to_dict(active, broken)

    last_close = float(df_plot["close"].iloc[-1])
    prev_close = float(df_plot["close"].iloc[-2]) if len(df_plot) > 1 else last_close
    chg_pct = (last_close - prev_close) / prev_close * 100 if prev_close else 0
    last_date = df_plot["date"].iloc[-1].strftime("%Y-%m-%d")

    ohlcv_json = json.dumps(ohlcv)
    sr_json = json.dumps(sr_data)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{ticker} — Interactive Chart</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #0d0d0d; color: #d1d4dc; font-family: 'Trebuchet MS', sans-serif; overflow: hidden; height: 100vh; display: flex; flex-direction: column; }}
  #header {{ background: #161616; border-bottom: 1px solid #2a2a2a; padding: 10px 16px; display: flex; align-items: center; gap: 20px; flex-shrink: 0; }}
  #ticker-info {{ display: flex; align-items: baseline; gap: 10px; }}
  #ticker-name {{ font-size: 20px; font-weight: 700; color: #ffffff; letter-spacing: 1px; }}
  #price {{ font-size: 22px; font-weight: 600; }}
  #change {{ font-size: 14px; font-weight: 500; }}
  #date-info {{ font-size: 12px; color: #666; margin-left: auto; }}
  #method-badge {{ background: #1e2d3d; color: #4a9eff; font-size: 11px; padding: 3px 10px; border-radius: 4px; border: 1px solid #2a4a6a; }}
  #ohlcv-bar {{ background: #161616; padding: 6px 16px; display: flex; gap: 20px; font-size: 12px; flex-shrink: 0; border-bottom: 1px solid #1e1e1e; }}
  .ohlcv-item {{ display: flex; gap: 5px; }}
  .ohlcv-label {{ color: #555; }}
  .ohlcv-val {{ color: #d1d4dc; }}
  #toolbar {{ background: #161616; border-bottom: 1px solid #1e1e1e; padding: 6px 16px; display: flex; gap: 8px; align-items: center; flex-shrink: 0; }}
  .tb-btn {{ background: transparent; border: 1px solid #2a2a2a; color: #888; font-size: 11px; padding: 4px 10px; border-radius: 4px; cursor: pointer; transition: all 0.15s; }}
  .tb-btn:hover {{ background: #222; color: #ccc; border-color: #444; }}
  .tb-btn.active {{ background: #1e2d3d; color: #4a9eff; border-color: #2a4a6a; }}
  .tb-sep {{ width: 1px; height: 18px; background: #2a2a2a; }}
  #chart-wrap {{ flex: 1; display: flex; flex-direction: column; overflow: hidden; position: relative; }}
  #main-canvas {{ flex: 1; display: block; width: 100%; cursor: crosshair; }}
  #vol-canvas {{ height: 100px; display: block; width: 100%; cursor: crosshair; flex-shrink: 0; border-top: 1px solid #1e1e1e; }}
  #crosshair-label {{ position: absolute; background: rgba(0,0,0,0.85); border: 1px solid #333; padding: 8px 12px; font-size: 11px; pointer-events: none; display: none; border-radius: 4px; line-height: 1.7; z-index: 100; white-space: nowrap; }}
  #legend {{ position: absolute; top: 8px; left: 12px; background: rgba(0,0,0,0.7); padding: 6px 10px; border-radius: 4px; font-size: 11px; display: flex; gap: 14px; pointer-events: none; }}
  .leg-item {{ display: flex; align-items: center; gap: 5px; }}
  .leg-dot {{ width: 10px; height: 3px; border-radius: 2px; }}
  #scrollbar-wrap {{ height: 14px; background: #111; border-top: 1px solid #1e1e1e; flex-shrink: 0; position: relative; cursor: pointer; }}
  #scrollbar-thumb {{ position: absolute; height: 100%; background: #2a2a2a; border-radius: 2px; cursor: grab; transition: background 0.1s; }}
  #scrollbar-thumb:hover {{ background: #3a3a3a; }}
</style>
</head>
<body>

<div id="header">
  <div id="ticker-info">
    <span id="ticker-name">{ticker}</span>
    <span id="price" style="color:{'#089981' if chg_pct >= 0 else '#f23645'}">${last_close:.2f}</span>
    <span id="change" style="color:{'#089981' if chg_pct >= 0 else '#f23645'}">({'+'if chg_pct>=0 else ''}{chg_pct:.2f}%)</span>
  </div>
  <span id="method-badge">{method} S&R</span>
  <div id="date-info">{last_date}</div>
</div>

<div id="ohlcv-bar">
  <div class="ohlcv-item"><span class="ohlcv-label">O</span><span class="ohlcv-val" id="hb-o">—</span></div>
  <div class="ohlcv-item"><span class="ohlcv-label">H</span><span class="ohlcv-val" id="hb-h">—</span></div>
  <div class="ohlcv-item"><span class="ohlcv-label">L</span><span class="ohlcv-val" id="hb-l">—</span></div>
  <div class="ohlcv-item"><span class="ohlcv-label">C</span><span class="ohlcv-val" id="hb-c">—</span></div>
  <div class="ohlcv-item"><span class="ohlcv-label">V</span><span class="ohlcv-val" id="hb-v">—</span></div>
</div>

<div id="toolbar">
  <button class="tb-btn active" id="btn-sr">S&R Zones</button>
  <button class="tb-btn active" id="btn-broken">Broken Levels</button>
  <div class="tb-sep"></div>
  <button class="tb-btn active" id="btn-vol">Volume</button>
  <div class="tb-sep"></div>
  <button class="tb-btn" id="btn-fit">Fit All</button>
  <button class="tb-btn" id="btn-zoom-in">Zoom +</button>
  <button class="tb-btn" id="btn-zoom-out">Zoom −</button>
</div>

<div id="chart-wrap">
  <canvas id="main-canvas"></canvas>
  <canvas id="vol-canvas"></canvas>
  <div id="crosshair-label"></div>
  <div id="legend">
    <div class="leg-item"><div class="leg-dot" style="background:#089981"></div><span style="color:#aaa;font-size:10px">Support</span></div>
    <div class="leg-item"><div class="leg-dot" style="background:#f23645"></div><span style="color:#aaa;font-size:10px">Resistance</span></div>
    <div class="leg-item"><div class="leg-dot" style="background:#555;width:14px"></div><span style="color:#aaa;font-size:10px">Broken</span></div>
  </div>
</div>

<div id="scrollbar-wrap">
  <div id="scrollbar-thumb"></div>
</div>

<script>
const RAW = {ohlcv_json};
const SR  = {sr_json};

const BULL = '#089981', BEAR = '#f23645';
const BG = '#0d0d0d', PANEL = '#111111', GRID = '#1e1e1e';
const TEXT = '#666', TEXT2 = '#aaa';
const SUP_C = '#089981', RES_C = '#f23645';

const mainCanvas = document.getElementById('main-canvas');
const volCanvas  = document.getElementById('vol-canvas');
const mc = mainCanvas.getContext('2d');
const vc = volCanvas.getContext('2d');

let data = RAW;
let viewStart = 0, viewEnd = data.length;
let showSR = true, showBroken = true, showVol = true;
let dragging = false, dragX = 0, dragStart = 0;
let sbDragging = false, sbDragX = 0;
const PRICE_AXIS_W = 80, DATE_AXIS_H = 24;

function resize() {{
  const wrap = document.getElementById('chart-wrap');
  mainCanvas.width  = wrap.clientWidth;
  mainCanvas.height = wrap.clientHeight - (showVol ? volCanvas.clientHeight : 0);
  volCanvas.width   = wrap.clientWidth;
  draw();
}}

function getView() {{
  const n = viewEnd - viewStart;
  return {{ start: viewStart, end: viewEnd, n }};
}}

function priceRange() {{
  const {{ start, end }} = getView();
  let mn = Infinity, mx = -Infinity;
  for (let i = start; i < end; i++) {{
    if (i < 0 || i >= data.length) continue;
    mn = Math.min(mn, data[i].l); mx = Math.max(mx, data[i].h);
  }}
  if (showSR) {{
    SR.active.forEach(lv => {{ mn = Math.min(mn, lv.btm); mx = Math.max(mx, lv.top); }});
    SR.broken.forEach(lv => {{ mn = Math.min(mn, lv.base * 0.995); mx = Math.max(mx, lv.base * 1.005); }});
  }}
  const pad = (mx - mn) * 0.06;
  return {{ min: mn - pad, max: mx + pad }};
}}

function toX(i) {{
  const {{ start, end }} = getView();
  const chartW = mainCanvas.width - PRICE_AXIS_W;
  const barW = chartW / (end - start);
  return (i - start + 0.5) * barW;
}}

function toY(price, canvas, range) {{
  const h = canvas.height - DATE_AXIS_H;
  return h - ((price - range.min) / (range.max - range.min)) * h;
}}

function barWidth() {{
  const {{ n }} = getView();
  return Math.max(1, (mainCanvas.width - PRICE_AXIS_W) / n);
}}

function draw() {{
  const W = mainCanvas.width, H = mainCanvas.height;
  const VW = volCanvas.width, VH = volCanvas.height;
  const bw = barWidth();
  const range = priceRange();
  const {{ start, end }} = getView();

  mc.fillStyle = PANEL; mc.fillRect(0, 0, W, H);
  vc.fillStyle = '#0a0a0a'; vc.fillRect(0, 0, VW, VH);

  // Grid lines
  const nGridY = 6;
  mc.strokeStyle = GRID; mc.lineWidth = 0.5;
  for (let i = 0; i <= nGridY; i++) {{
    const y = (H - DATE_AXIS_H) * i / nGridY;
    mc.beginPath(); mc.moveTo(0, y); mc.lineTo(W - PRICE_AXIS_W, y); mc.stroke();
    const price = range.max - (range.max - range.min) * i / nGridY;
    mc.fillStyle = TEXT; mc.font = '10px monospace'; mc.textAlign = 'left';
    mc.fillText('$' + price.toFixed(2), W - PRICE_AXIS_W + 6, y + 4);
  }}

  // Date axis
  const step = Math.max(1, Math.floor((end - start) / 8));
  mc.fillStyle = TEXT; mc.font = '10px monospace'; mc.textAlign = 'center';
  for (let i = start; i < end; i += step) {{
    if (i < 0 || i >= data.length) continue;
    const x = toX(i);
    mc.fillText(data[i].t.slice(5), x, H - 6);
  }}

  // S&R zones and lines
  if (showSR) {{
    SR.active.forEach(lv => {{
      const color = lv.is_support ? SUP_C : RES_C;
      const y1 = toY(lv.top, mainCanvas, range);
      const y2 = toY(lv.btm, mainCanvas, range);
      mc.fillStyle = color + '22';
      mc.fillRect(0, Math.min(y1, y2), W - PRICE_AXIS_W, Math.abs(y2 - y1));
      const yBase = toY(lv.base, mainCanvas, range);
      mc.strokeStyle = color; mc.lineWidth = 1; mc.setLineDash([]);
      mc.beginPath(); mc.moveTo(0, yBase); mc.lineTo(W - PRICE_AXIS_W, yBase); mc.stroke();
      if (lv.entries > 0) {{
        mc.fillStyle = color; mc.font = 'bold 10px monospace'; mc.textAlign = 'right';
        mc.fillText('E:' + lv.entries + (lv.sweeps > 0 ? '  SW:' + lv.sweeps : ''), W - PRICE_AXIS_W - 4, yBase - 3);
      }}
    }});
  }}

  if (showBroken) {{
    SR.broken.forEach(lv => {{
      const color = lv.is_support ? SUP_C : RES_C;
      const yBase = toY(lv.base, mainCanvas, range);
      mc.strokeStyle = color + '44'; mc.lineWidth = 0.8; mc.setLineDash([4, 4]);
      mc.beginPath(); mc.moveTo(0, yBase); mc.lineTo(W - PRICE_AXIS_W, yBase); mc.stroke();
    }});
    mc.setLineDash([]);
  }}

  // Candles
  for (let i = start; i < end; i++) {{
    if (i < 0 || i >= data.length) continue;
    const d = data[i];
    const x = toX(i);
    const color = d.c >= d.o ? BULL : BEAR;
    mc.fillStyle = color; mc.strokeStyle = color; mc.lineWidth = Math.max(1, bw * 0.1);
    const bodyH = Math.max(1, Math.abs(toY(d.c, mainCanvas, range) - toY(d.o, mainCanvas, range)));
    const bodyY = Math.min(toY(d.o, mainCanvas, range), toY(d.c, mainCanvas, range));
    mc.fillRect(x - bw * 0.4, bodyY, bw * 0.8, bodyH);
    mc.beginPath();
    mc.moveTo(x, toY(d.h, mainCanvas, range));
    mc.lineTo(x, toY(d.l, mainCanvas, range));
    mc.stroke();
  }}

  // Volume
  if (showVol) {{
    let maxVol = 0;
    for (let i = start; i < end; i++) {{ if (i >= 0 && i < data.length) maxVol = Math.max(maxVol, data[i].v); }}
    const vBw = VW / (end - start);
    for (let i = start; i < end; i++) {{
      if (i < 0 || i >= data.length) continue;
      const d = data[i];
      const vx = (i - start + 0.5) * vBw;
      const barH = ((d.v / maxVol) * (VH - 14)) || 0;
      vc.fillStyle = (d.c >= d.o ? BULL : BEAR) + '88';
      vc.fillRect(vx - vBw * 0.4, VH - 14 - barH, vBw * 0.8, barH);
    }}
    // Vol axis label
    const volLabel = maxVol > 1e6 ? (maxVol/1e6).toFixed(1)+'M' : maxVol > 1e3 ? (maxVol/1e3).toFixed(0)+'K' : maxVol;
    vc.fillStyle = TEXT; vc.font = '9px monospace'; vc.textAlign = 'right';
    vc.fillText(volLabel, VW - 4, 12);
    // Vol date axis
    vc.fillStyle = TEXT; vc.font = '9px monospace'; vc.textAlign = 'center';
    for (let i = start; i < end; i += step) {{
      if (i < 0 || i >= data.length) continue;
      const vx = (i - start + 0.5) * vBw;
      vc.fillText(data[i].t.slice(5), vx, VH - 4);
    }}
  }}

  updateScrollbar();
}}

function updateScrollbar() {{
  const total = data.length;
  const shown = viewEnd - viewStart;
  const thumb = document.getElementById('scrollbar-thumb');
  const wrap  = document.getElementById('scrollbar-wrap');
  const ww = wrap.clientWidth;
  const tw = Math.max(30, (shown / total) * ww);
  const tx = (viewStart / total) * ww;
  thumb.style.width = tw + 'px';
  thumb.style.left  = tx + 'px';
}}

// Interactions
mainCanvas.addEventListener('wheel', e => {{
  e.preventDefault();
  const n = viewEnd - viewStart;
  const delta = e.deltaY > 0 ? 1 : -1;
  const newN = Math.min(data.length, Math.max(10, n + delta * Math.max(1, Math.floor(n * 0.05))));
  const mid = (viewStart + viewEnd) / 2;
  viewStart = Math.max(0, Math.round(mid - newN / 2));
  viewEnd   = Math.min(data.length, viewStart + newN);
  draw();
}}, {{ passive: false }});

mainCanvas.addEventListener('mousedown', e => {{
  dragging = true; dragX = e.clientX; dragStart = viewStart;
}});
document.addEventListener('mousemove', e => {{
  if (dragging) {{
    const dx = e.clientX - dragX;
    const n  = viewEnd - viewStart;
    const bw = (mainCanvas.width - PRICE_AXIS_W) / n;
    const shift = -Math.round(dx / bw);
    viewStart = Math.max(0, Math.min(data.length - n, dragStart + shift));
    viewEnd   = viewStart + n;
    draw();
  }}
  updateCrosshair(e, mainCanvas.getBoundingClientRect());
}});
document.addEventListener('mouseup', () => {{ dragging = false; }});
mainCanvas.addEventListener('mouseleave', () => {{
  document.getElementById('crosshair-label').style.display = 'none';
}});

function updateCrosshair(e, rect) {{
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  if (x < 0 || x > mainCanvas.width - PRICE_AXIS_W || y < 0 || y > mainCanvas.height - DATE_AXIS_H) {{
    document.getElementById('crosshair-label').style.display = 'none';
    return;
  }}
  const {{ start, end }} = getView();
  const bw = (mainCanvas.width - PRICE_AXIS_W) / (end - start);
  const idx = Math.round(start + x / bw - 0.5);
  if (idx < 0 || idx >= data.length) return;
  const d = data[idx];
  const range = priceRange();
  const price = range.max - (y / (mainCanvas.height - DATE_AXIS_H)) * (range.max - range.min);
  const lbl = document.getElementById('crosshair-label');
  const color = d.c >= d.o ? BULL : BEAR;
  const chg = ((d.c - d.o) / d.o * 100).toFixed(2);
  const chgSign = d.c >= d.o ? '+' : '';
  const vol = d.v > 1e6 ? (d.v/1e6).toFixed(2)+'M' : d.v > 1e3 ? (d.v/1e3).toFixed(0)+'K' : d.v;
  lbl.innerHTML = `<span style="color:#888;font-size:10px">${{d.t}}</span><br>` +
    `<span style="color:#aaa">O</span> <b style="color:${{color}}">${{d.o.toFixed(2)}}</b>&nbsp;` +
    `<span style="color:#aaa">H</span> <b style="color:${{color}}">${{d.h.toFixed(2)}}</b>&nbsp;` +
    `<span style="color:#aaa">L</span> <b style="color:${{color}}">${{d.l.toFixed(2)}}</b>&nbsp;` +
    `<span style="color:#aaa">C</span> <b style="color:${{color}}">${{d.c.toFixed(2)}}</b><br>` +
    `<span style="color:${{color}}">${{chgSign}}${{chg}}%</span>&nbsp;&nbsp;Vol: ${{vol}}`;
  lbl.style.display = 'block';
  // Position tooltip
  const tx = Math.min(e.clientX - rect.left + 12, mainCanvas.width - 200);
  const ty = Math.max(0, e.clientY - rect.top - 60);
  lbl.style.left = tx + 'px'; lbl.style.top = ty + 'px';
  // Update OHLCV bar
  document.getElementById('hb-o').textContent = '$' + d.o.toFixed(2);
  document.getElementById('hb-h').textContent = '$' + d.h.toFixed(2);
  document.getElementById('hb-l').textContent = '$' + d.l.toFixed(2);
  document.getElementById('hb-c').textContent = '$' + d.c.toFixed(2);
  document.getElementById('hb-v').textContent = vol;
  document.getElementById('hb-c').style.color = color;
}}

// Scrollbar drag
const thumb = document.getElementById('scrollbar-thumb');
const sbWrap = document.getElementById('scrollbar-wrap');
thumb.addEventListener('mousedown', e => {{
  sbDragging = true; sbDragX = e.clientX - thumb.offsetLeft; e.preventDefault();
}});
document.addEventListener('mousemove', e => {{
  if (!sbDragging) return;
  const ww = sbWrap.clientWidth;
  const tw = thumb.clientWidth;
  const tx = Math.max(0, Math.min(ww - tw, e.clientX - sbDragX));
  const ratio = tx / (ww - tw);
  const n = viewEnd - viewStart;
  viewStart = Math.round(ratio * (data.length - n));
  viewEnd   = viewStart + n;
  draw();
}});
document.addEventListener('mouseup', () => {{ sbDragging = false; }});
sbWrap.addEventListener('click', e => {{
  if (e.target === thumb) return;
  const ww = sbWrap.clientWidth;
  const n  = viewEnd - viewStart;
  const ratio = e.offsetX / ww;
  viewStart = Math.max(0, Math.min(data.length - n, Math.round(ratio * data.length - n/2)));
  viewEnd   = viewStart + n;
  draw();
}});

// Toolbar buttons
document.getElementById('btn-sr').addEventListener('click', function() {{
  showSR = !showSR; this.classList.toggle('active', showSR); draw();
}});
document.getElementById('btn-broken').addEventListener('click', function() {{
  showBroken = !showBroken; this.classList.toggle('active', showBroken); draw();
}});
document.getElementById('btn-vol').addEventListener('click', function() {{
  showVol = !showVol; this.classList.toggle('active', showVol);
  volCanvas.style.display = showVol ? 'block' : 'none';
  resize(); draw();
}});
document.getElementById('btn-fit').addEventListener('click', () => {{
  viewStart = 0; viewEnd = data.length; draw();
}});
document.getElementById('btn-zoom-in').addEventListener('click', () => {{
  const n   = viewEnd - viewStart;
  const mid = (viewStart + viewEnd) / 2;
  const newN = Math.max(10, Math.round(n * 0.7));
  viewStart = Math.max(0, Math.round(mid - newN/2));
  viewEnd   = Math.min(data.length, viewStart + newN);
  draw();
}});
document.getElementById('btn-zoom-out').addEventListener('click', () => {{
  const n   = viewEnd - viewStart;
  const mid = (viewStart + viewEnd) / 2;
  const newN = Math.min(data.length, Math.round(n * 1.4));
  viewStart = Math.max(0, Math.round(mid - newN/2));
  viewEnd   = Math.min(data.length, viewStart + newN);
  draw();
}});

// Init
viewStart = Math.max(0, data.length - {candles});
viewEnd   = data.length;
window.addEventListener('resize', resize);
resize();
</script>
</body>
</html>"""

    buf = io.BytesIO(html.encode("utf-8"))
    buf.seek(0)
    return buf
