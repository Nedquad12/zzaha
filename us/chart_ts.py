"""
chart_ts.py — Chart Total Score vs Price (2 panel)
Panel atas : candlestick price (300 bar terakhir yang ada score)
Panel bawah: line merah total score

Dipanggil via command /ch ts TICKER
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import io
import logging

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
from matplotlib.patches import Rectangle
import pandas as pd
import numpy as np
from datetime import datetime

from score_history import load_score_history

logger = logging.getLogger(__name__)

# ── Warna tema gelap (sama dengan chart.py) ───────────────────────────────────
BG_COLOR    = "#161616"
PANEL_COLOR = "#1e1e1e"
GRID_COLOR  = "#2e2e2e"
TEXT_COLOR  = "#DBDBDB"
BULL_COLOR  = "#089981"
BEAR_COLOR  = "#f23645"
SCORE_COLOR = "#f23645"   # line merah untuk total score
ZERO_COLOR  = "#555555"   # garis nol


def _draw_candles(ax, dates, opens, highs, lows, closes):
    """Render candlestick dari array."""
    x_nums = mdates.date2num(dates)
    for x, o, h, l, c in zip(x_nums, opens, highs, lows, closes):
        color  = BULL_COLOR if c >= o else BEAR_COLOR
        body_h = abs(c - o) or (h - l) * 0.01
        body_y = min(o, c)
        ax.add_patch(Rectangle((x - 0.3, body_y), 0.6, body_h,
                                color=color, zorder=3))
        ax.plot([x, x], [l, h], color=color, linewidth=0.8, zorder=2)


def generate_ts_chart(ticker: str) -> io.BytesIO:
    """
    Generate chart Total Score vs Price dan return sebagai BytesIO PNG.

    Args:
        ticker: kode saham (e.g. "AAPL")

    Returns:
        BytesIO berisi PNG

    Raises:
        ValueError jika data tidak tersedia
    """
    history = load_score_history(ticker)
    if not history:
        raise ValueError(f"Tidak ada score history untuk {ticker}. Jalankan /9 terlebih dahulu.")

    # ── Parse data ─────────────────────────────────────────────────────────
    dates  = []
    opens  = []
    highs  = []
    lows   = []
    closes = []
    scores = []

    for h in history:
        try:
            dates.append(pd.to_datetime(h["date"]).to_pydatetime())
            opens.append(float(h["open"]))
            highs.append(float(h["high"]))
            lows.append(float(h["low"]))
            closes.append(float(h["price"]))
            scores.append(float(h["total"]))
        except Exception:
            continue

    if not dates:
        raise ValueError(f"Data kosong untuk {ticker}")

    dates_num = mdates.date2num(dates)

    # ── Figure setup ───────────────────────────────────────────────────────
    fig, (ax_price, ax_score) = plt.subplots(
        2, 1,
        figsize=(16, 9),
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.08},
        facecolor=BG_COLOR,
    )

    # ── Panel atas: Price candlestick ──────────────────────────────────────
    ax_price.set_facecolor(PANEL_COLOR)
    ax_price.xaxis_date()
    ax_price.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax_price.xaxis.set_major_locator(mdates.MonthLocator())
    ax_price.tick_params(colors=TEXT_COLOR, labelsize=7, labelbottom=False)
    ax_price.yaxis.tick_right()
    ax_price.yaxis.set_tick_params(labelcolor=TEXT_COLOR, labelsize=7)
    for spine in ax_price.spines.values():
        spine.set_edgecolor(GRID_COLOR)
    ax_price.grid(True, color=GRID_COLOR, linewidth=0.4, zorder=0)

    _draw_candles(ax_price, dates, opens, highs, lows, closes)

    price_min = min(lows)
    price_max = max(highs)
    pad       = (price_max - price_min) * 0.05
    ax_price.set_ylim(price_min - pad, price_max + pad)
    ax_price.set_xlim(dates_num[0] - 1, dates_num[-1] + 3)

    # Title
    last_close  = closes[-1]
    prev_close  = closes[-2] if len(closes) > 1 else last_close
    chg_pct     = (last_close - prev_close) / prev_close * 100 if prev_close else 0
    chg_sign    = "+" if chg_pct >= 0 else ""
    chg_color   = BULL_COLOR if chg_pct >= 0 else BEAR_COLOR
    last_date   = dates[-1].strftime("%Y-%m-%d")
    last_score  = scores[-1]

    ax_price.set_title(
        f"{ticker}   ${last_close:.2f}  ({chg_sign}{chg_pct:.2f}%)   "
        f"Score: {last_score:+.1f}   |   {last_date}   [{len(dates)} bars]",
        color=TEXT_COLOR, fontsize=11, loc="left", pad=8,
    )

    # ── Panel bawah: Total score line merah ────────────────────────────────
    ax_score.set_facecolor(PANEL_COLOR)
    ax_score.xaxis_date()
    ax_score.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    ax_score.xaxis.set_major_locator(mdates.MonthLocator())
    ax_score.tick_params(colors=TEXT_COLOR, labelsize=7)
    ax_score.yaxis.tick_right()
    ax_score.yaxis.set_tick_params(labelcolor=TEXT_COLOR, labelsize=7)
    for spine in ax_score.spines.values():
        spine.set_edgecolor(GRID_COLOR)
    ax_score.grid(True, color=GRID_COLOR, linewidth=0.4, zorder=0)

    # Garis nol
    ax_score.axhline(0, color=ZERO_COLOR, linewidth=0.8, linestyle="--", zorder=2)

    # Area fill: hijau di atas nol, merah di bawah
    scores_arr = np.array(scores)
    ax_score.fill_between(dates_num, scores_arr, 0,
                          where=(scores_arr >= 0),
                          color=BULL_COLOR, alpha=0.15, zorder=1)
    ax_score.fill_between(dates_num, scores_arr, 0,
                          where=(scores_arr < 0),
                          color=BEAR_COLOR, alpha=0.15, zorder=1)

    # Line merah
    ax_score.plot(dates_num, scores_arr,
                  color=SCORE_COLOR, linewidth=1.2, zorder=3)

    # Titik terakhir
    ax_score.scatter([dates_num[-1]], [scores_arr[-1]],
                     color=SCORE_COLOR, s=30, zorder=4)

    # Label score tertinggi & terendah
    max_score = scores_arr.max()
    min_score = scores_arr.min()
    max_idx   = scores_arr.argmax()
    min_idx   = scores_arr.argmin()
    ax_score.annotate(f"{max_score:+.0f}",
                      xy=(dates_num[max_idx], max_score),
                      color=BULL_COLOR, fontsize=7, ha="center", va="bottom")
    ax_score.annotate(f"{min_score:+.0f}",
                      xy=(dates_num[min_idx], min_score),
                      color=BEAR_COLOR, fontsize=7, ha="center", va="top")

    ax_score.set_ylabel("Total Score", color=TEXT_COLOR, fontsize=8)
    ax_score.set_xlim(ax_price.get_xlim())

    # Padding y score
    score_range = max_score - min_score or 1
    ax_score.set_ylim(min_score - score_range * 0.1,
                      max_score + score_range * 0.1)

    # ── Legend sederhana ───────────────────────────────────────────────────
    bull_p = mpatches.Patch(color=BULL_COLOR, alpha=0.8, label="Bullish")
    bear_p = mpatches.Patch(color=BEAR_COLOR, alpha=0.8, label="Bearish")
    ax_price.legend(handles=[bull_p, bear_p],
                    facecolor=PANEL_COLOR, edgecolor=GRID_COLOR,
                    labelcolor=TEXT_COLOR, fontsize=7, loc="upper left")

    plt.tight_layout(pad=0.5)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor=BG_COLOR)
    plt.close(fig)
    buf.seek(0)
    return buf
