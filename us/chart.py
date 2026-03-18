"""
chart.py — Generate candlestick chart + S&R zones sebagai PNG
Dikirim ke Telegram via send_photo()
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import io
import logging
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Rectangle
import matplotlib.dates as mdates
import pandas as pd
import numpy as np

from config import (
    CHART_CANDLES,
    SR_METHOD_DONCHIAN, SR_METHOD_PIVOTS, SR_METHOD_CSID, SR_METHOD_ZIGZAG,
    SR_SENSITIVITY, SR_MAX_LEVELS,
)
from indicators.sr import detect_sr, SRLevel

logger = logging.getLogger(__name__)

# ── Warna tema gelap (mirip LuxAlgo) ─────────────────────────────────────────
BG_COLOR       = "#161616"
PANEL_COLOR    = "#1e1e1e"
GRID_COLOR     = "#2e2e2e"
TEXT_COLOR     = "#DBDBDB"
BULL_COLOR     = "#089981"
BEAR_COLOR     = "#f23645"
SUP_COLOR      = "#089981"
RES_COLOR      = "#f23645"
BROKEN_ALPHA   = 0.25
ZONE_ALPHA     = 0.15
LINE_ALPHA     = 0.9


# ── Candlestick renderer ──────────────────────────────────────────────────────

def _draw_candles(ax, df: pd.DataFrame):
    for _, row in df.iterrows():
        x     = mdates.date2num(row["date"])
        o, h, l, c = row["open"], row["high"], row["low"], row["close"]
        color = BULL_COLOR if c >= o else BEAR_COLOR
        # body
        body_h = abs(c - o) or (h - l) * 0.01
        body_y = min(o, c)
        ax.add_patch(Rectangle((x - 0.3, body_y), 0.6, body_h,
                                color=color, zorder=3))
        # wick
        ax.plot([x, x], [l, h], color=color, linewidth=0.8, zorder=2)


# ── S&R zone / line renderer ──────────────────────────────────────────────────

def _draw_sr(ax, levels: list[SRLevel], broken: list[SRLevel],
             df: pd.DataFrame, display_zones: bool = True):

    if df.empty:
        return

    x_min = mdates.date2num(df["date"].iloc[0])
    x_max = mdates.date2num(df["date"].iloc[-1]) + 5   # sedikit extend ke kanan

    # Active levels
    for lv in levels:
        color = SUP_COLOR if lv.is_support else RES_COLOR

        # zone box
        if display_zones:
            ax.fill_betweenx(
                [lv.btm, lv.top],
                x_min, x_max,
                color=color, alpha=ZONE_ALPHA, zorder=1
            )

        # base line
        ax.hlines(lv.base_price, x_min, x_max,
                  colors=color, linewidths=0.9,
                  linestyles="solid", alpha=LINE_ALPHA, zorder=4)

        # label kecil di kanan
        label_parts = []
        if lv.entries:
            label_parts.append(f"E:{lv.entries}")
        if lv.sweeps:
            label_parts.append(f"SW:{lv.sweeps}")
        if label_parts:
            ax.text(x_max + 0.3, lv.base_price, "  ".join(label_parts),
                    color=color, fontsize=5.5, va="center", zorder=5)

    # Broken levels (redup)
    for lv in broken[-10:]:   # cukup 10 broken terakhir
        color = SUP_COLOR if lv.is_support else RES_COLOR
        ax.hlines(lv.base_price, x_min, x_max,
                  colors=color, linewidths=0.6,
                  linestyles="dashed", alpha=BROKEN_ALPHA, zorder=1)


# ── Volume bar renderer ───────────────────────────────────────────────────────

def _draw_volume(ax, df: pd.DataFrame):
    for _, row in df.iterrows():
        x = mdates.date2num(row["date"])
        color = BULL_COLOR if row["close"] >= row["open"] else BEAR_COLOR
        ax.bar(x, row["volume"], width=0.6, color=color, alpha=0.5, zorder=2)
    ax.set_facecolor(PANEL_COLOR)
    ax.tick_params(colors=TEXT_COLOR, labelsize=6)
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: f"{v/1e6:.1f}M" if v >= 1e6 else f"{v/1e3:.0f}K")
    )
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID_COLOR)


# ── Main chart function ───────────────────────────────────────────────────────

def generate_chart(
    ticker: str,
    df: pd.DataFrame,
    method: str = SR_METHOD_DONCHIAN,
    sens: float = SR_SENSITIVITY,
    candles: int = CHART_CANDLES,
) -> io.BytesIO:
    """
    Generate chart PNG dan return sebagai BytesIO.

    Args:
        ticker  : nama saham
        df      : full OHLCV DataFrame (dipakai untuk hitung S&R)
        method  : S&R detection method
        sens    : sensitivity
        candles : jumlah candle yang ditampilkan

    Returns:
        BytesIO berisi PNG
    """
    # Hitung S&R dari data penuh, tampilkan N candle terakhir
    active, broken = detect_sr(df, method=method, sens=sens)
    df_plot = df.tail(candles).copy().reset_index(drop=True)

    fig, (ax_main, ax_vol) = plt.subplots(
        2, 1, figsize=(14, 8),
        gridspec_kw={"height_ratios": [4, 1], "hspace": 0.04},
        facecolor=BG_COLOR
    )

    # ── Main panel ───────────────────────────────────────────────────────
    ax_main.set_facecolor(PANEL_COLOR)
    ax_main.xaxis_date()
    ax_main.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax_main.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
    ax_main.tick_params(colors=TEXT_COLOR, labelsize=7)
    ax_main.yaxis.tick_right()
    for spine in ax_main.spines.values():
        spine.set_edgecolor(GRID_COLOR)
    ax_main.grid(True, color=GRID_COLOR, linewidth=0.4, zorder=0)

    # S&R
    _draw_sr(ax_main, active, broken, df_plot, display_zones=True)

    # Candles
    _draw_candles(ax_main, df_plot)

    # Price range padding
    price_min = df_plot["low"].min()
    price_max = df_plot["high"].max()
    pad = (price_max - price_min) * 0.05
    ax_main.set_ylim(price_min - pad, price_max + pad)
    ax_main.set_xlim(
        mdates.date2num(df_plot["date"].iloc[0]) - 1,
        mdates.date2num(df_plot["date"].iloc[-1]) + 8
    )

    # Title & info
    last_close  = df_plot["close"].iloc[-1]
    prev_close  = df_plot["close"].iloc[-2] if len(df_plot) > 1 else last_close
    chg_pct     = (last_close - prev_close) / prev_close * 100 if prev_close else 0
    chg_color   = BULL_COLOR if chg_pct >= 0 else BEAR_COLOR
    chg_sign    = "+" if chg_pct >= 0 else ""
    last_date   = df_plot["date"].iloc[-1].strftime("%Y-%m-%d")

    ax_main.set_title(
        f"{ticker}   ${last_close:.2f}  ({chg_sign}{chg_pct:.2f}%)   "
        f"{method} S&R  |  {last_date}",
        color=TEXT_COLOR, fontsize=11, loc="left", pad=8
    )

    # Legend
    sup_patch = mpatches.Patch(color=SUP_COLOR, alpha=0.7, label="Support")
    res_patch = mpatches.Patch(color=RES_COLOR, alpha=0.7, label="Resistance")
    ax_main.legend(handles=[sup_patch, res_patch],
                   facecolor=PANEL_COLOR, edgecolor=GRID_COLOR,
                   labelcolor=TEXT_COLOR, fontsize=7, loc="upper left")

    # ── Volume panel ─────────────────────────────────────────────────────
    _draw_volume(ax_vol, df_plot)
    ax_vol.set_xlim(ax_main.get_xlim())
    ax_vol.xaxis_date()
    ax_vol.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax_vol.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
    ax_vol.tick_params(colors=TEXT_COLOR, labelsize=6)
    ax_vol.set_ylabel("Vol", color=TEXT_COLOR, fontsize=7)
    ax_vol.yaxis.tick_right()
    ax_vol.grid(True, color=GRID_COLOR, linewidth=0.3)

    plt.tight_layout(pad=0.5)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor=BG_COLOR)
    plt.close(fig)
    buf.seek(0)
    return buf
