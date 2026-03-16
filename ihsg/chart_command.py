"""
chart_command.py — Handler Telegram untuk /chart TICKER

Tampilkan chart 2 panel:
  Panel atas  : candlestick harga
  Panel bawah : line total score (merah)

Data diambil langsung dari JSON harian (sliding window, sama seperti backtest.py).
Tidak butuh score_history eksternal — history dihitung on-the-fly.

Penggunaan:
    /chart BBCA
    /chart TLKM

Integrasi ke main.py:
    from chart_command import register_chart_handler
    register_chart_handler(app)
"""

import asyncio
import glob
import io
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
from matplotlib.patches import Rectangle

import numpy as np
import pandas as pd

from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from telegram.constants import ParseMode

from admin.auth import is_authorized_user, is_vip_user, check_public_group_access
from admin.admin_command import active_admins

logger = logging.getLogger(__name__)

# ── Path ───────────────────────────────────────────────────────────────────────
JSON_DIR  = "/home/ec2-user/database/json"
MAX_BARS  = 300   # maksimal bar yang ditampilkan di chart

# ── Warna tema gelap ───────────────────────────────────────────────────────────
BG_COLOR    = "#161616"
PANEL_COLOR = "#1e1e1e"
GRID_COLOR  = "#2e2e2e"
TEXT_COLOR  = "#DBDBDB"
BULL_COLOR  = "#089981"
BEAR_COLOR  = "#f23645"
SCORE_COLOR = "#f23645"
ZERO_COLOR  = "#555555"


# ══════════════════════════════════════════════════════════════════════════════
#  Auth guard
# ══════════════════════════════════════════════════════════════════════════════

def _is_allowed(user_id: int) -> bool:
    return is_authorized_user(user_id) or is_vip_user(user_id)


# ══════════════════════════════════════════════════════════════════════════════
#  Build history dari JSON harian (sama seperti backtest._build_history_df)
# ══════════════════════════════════════════════════════════════════════════════

def _build_history(ticker: str, json_dir: str = JSON_DIR) -> list[dict]:
    """
    Hitung skor per hari untuk satu ticker dari semua file JSON harian.

    Returns:
        list of dict: [{date, open, high, low, price, total}, ...]
        Diurutkan ascending by date.
        List kosong jika tidak ada data.
    """
    from indicators.loader import build_stock_df, _parse_date_from_filename
    from indicators import (
        score_vsa, score_fsa, score_vfa,
        score_wcc, score_rsi, score_macd, score_ma,
        calculate_ip, score_ip, score_srst,
        score_tight, score_fbs,
        score_mgn, score_brk, score_own,
    )
    from cache_manager import get_mgn_cache, get_brk_cache, get_own_cache

    ticker = ticker.upper().strip()

    all_files = sorted(glob.glob(os.path.join(json_dir, "*.json")))
    if not all_files:
        logger.warning(f"[CHART] Tidak ada file JSON di {json_dir}")
        return []

    # Batasi ke MAX_BARS hari terakhir
    all_files = all_files[-MAX_BARS:]

    # Cache eksternal (baca sekali)
    mgn_cache = get_mgn_cache()
    brk_cache = get_brk_cache()
    own_cache = get_own_cache()

    rows = []

    for i, fpath in enumerate(all_files):
        window_files = all_files[: i + 1]
        window_files = window_files[-60:]   # konsisten dengan scorer.py

        try:
            df = _build_df_from_files(ticker, window_files)
            if df is None or df.empty:
                continue

            row_date = _parse_date_from_filename(window_files[-1])
            if row_date is None:
                continue

            price = float(df["close"].iloc[-1])
            if price == 0:
                continue

            # Hitung semua skor
            vsa    = score_vsa(df)
            fsa    = score_fsa(df)
            vfa    = score_vfa(df)
            wcc    = score_wcc(df)
            rsi    = score_rsi(df)
            macd   = score_macd(df)
            ma     = score_ma(df)
            ip_raw = calculate_ip(df)
            ip_pts = score_ip(ip_raw)
            srst   = score_srst(df)
            tight  = score_tight(df)
            fbs    = score_fbs(df)
            mgn    = score_mgn(ticker, mgn_cache)
            brk    = score_brk(ticker, brk_cache)
            own    = score_own(ticker, own_cache)

            total = (vsa + fsa + vfa + wcc + rsi + macd + ma + ip_pts
                     + srst + tight + fbs + mgn + brk + own)

            rows.append({
                "date":  pd.Timestamp(row_date),
                "open":  float(df["open"].iloc[-1]),
                "high":  float(df["high"].iloc[-1]),
                "low":   float(df["low"].iloc[-1]),
                "price": price,
                "total": round(total, 2),
            })

        except Exception as e:
            logger.debug(f"[CHART] Skip {fpath}: {e}")
            continue

    return rows


def _build_df_from_files(ticker: str, file_list: list):
    """Bangun DataFrame satu ticker dari list file JSON. (dicomot dari backtest.py)"""
    import json as _json
    from indicators.loader import COL_MAP, NUMERIC_COLS

    dfs = []
    for fpath in file_list:
        try:
            with open(fpath, encoding="utf-8") as f:
                records = _json.load(f)
            df_day = pd.DataFrame(records)
            if df_day.empty:
                continue
            # Rename kolom
            df_day.rename(columns=COL_MAP, inplace=True)
            if "ticker" not in df_day.columns:
                continue
            df_day["ticker"] = df_day["ticker"].astype(str).str.strip().str.upper()
            sub = df_day[df_day["ticker"] == ticker]
            if sub.empty:
                continue
            # Ambil nama file sebagai tanggal
            from indicators.loader import _parse_date_from_filename
            row_date = _parse_date_from_filename(fpath)
            sub = sub.copy()
            sub["date"] = pd.Timestamp(row_date) if row_date else pd.NaT
            dfs.append(sub)
        except Exception:
            continue

    if not dfs:
        return None

    combined = pd.concat(dfs, ignore_index=True)
    combined.sort_values("date", inplace=True)
    combined.reset_index(drop=True, inplace=True)

    for col in NUMERIC_COLS:
        if col in combined.columns:
            combined[col] = pd.to_numeric(combined[col], errors="coerce").fillna(0)

    return combined if not combined.empty else None


# ══════════════════════════════════════════════════════════════════════════════
#  Chart generator
# ══════════════════════════════════════════════════════════════════════════════

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


def _generate_chart(ticker: str) -> io.BytesIO:
    """Generate chart 2 panel dan return sebagai BytesIO PNG."""
    history = _build_history(ticker)
    if not history:
        raise ValueError(
            f"Tidak ada data untuk {ticker}. "
            "Pastikan ticker benar dan data sudah di-reload."
        )

    dates  = [h["date"].to_pydatetime() for h in history]
    opens  = [h["open"]  for h in history]
    highs  = [h["high"]  for h in history]
    lows   = [h["low"]   for h in history]
    closes = [h["price"] for h in history]
    scores = [h["total"] for h in history]

    dates_num  = mdates.date2num(dates)
    scores_arr = np.array(scores)

    # ── Figure setup ───────────────────────────────────────────────────────
    fig, (ax_price, ax_score) = plt.subplots(
        2, 1,
        figsize=(16, 9),
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.08},
        facecolor=BG_COLOR,
    )

    # ── Panel atas: Candlestick harga ──────────────────────────────────────
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
    last_close = closes[-1]
    prev_close = closes[-2] if len(closes) > 1 else last_close
    chg_pct    = (last_close - prev_close) / prev_close * 100 if prev_close else 0
    chg_sign   = "+" if chg_pct >= 0 else ""
    last_date  = dates[-1].strftime("%Y-%m-%d")
    last_score = scores[-1]

    ax_price.set_title(
        f"{ticker}   Rp {last_close:,.0f}  ({chg_sign}{chg_pct:.2f}%)   "
        f"Score: {last_score:+.1f}   |   {last_date}   [{len(dates)} bars]",
        color=TEXT_COLOR, fontsize=11, loc="left", pad=8,
    )

    # Legend
    bull_p = mpatches.Patch(color=BULL_COLOR, alpha=0.8, label="Bullish")
    bear_p = mpatches.Patch(color=BEAR_COLOR, alpha=0.8, label="Bearish")
    ax_price.legend(handles=[bull_p, bear_p],
                    facecolor=PANEL_COLOR, edgecolor=GRID_COLOR,
                    labelcolor=TEXT_COLOR, fontsize=7, loc="upper left")

    # ── Panel bawah: Total score ───────────────────────────────────────────
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

    # Area fill
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

    # Label max & min score
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

    score_range = max_score - min_score or 1
    ax_score.set_ylim(min_score - score_range * 0.1,
                      max_score + score_range * 0.1)

    plt.tight_layout(pad=0.5)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor=BG_COLOR)
    plt.close(fig)
    buf.seek(0)
    return buf


# ══════════════════════════════════════════════════════════════════════════════
#  Telegram handler
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_chart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler untuk command /chart TICKER

    Contoh:
        /chart BBCA
        /chart TLKM
    """
    if not await check_public_group_access(update, active_admins):
       return
    uid = update.effective_user.id
    if not _is_allowed(uid):
        await update.message.reply_text("⛔ Kamu tidak punya akses ke fitur ini.")
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "⚠️ Gunakan: <code>/chart KODE</code>\n"
            "Contoh: <code>/chart BBCA</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    ticker = args[0].upper().strip()
    msg = await update.message.reply_text(
        f"⏳ Membuat chart <b>{ticker}</b>…",
        parse_mode=ParseMode.HTML,
    )

    try:
        buf = await asyncio.get_event_loop().run_in_executor(
            None, _generate_chart, ticker
        )
        await msg.delete()
        await update.message.reply_photo(
            photo=buf,
            caption=f"📊 <b>{ticker}</b> — Harga & Total Score",
            parse_mode=ParseMode.HTML,
        )

    except ValueError as e:
        await msg.edit_text(f"⚠️ {e}")
    except Exception as e:
        logger.error(f"[CHART] Error {ticker}: {e}", exc_info=True)
        await msg.edit_text(
            f"❌ Gagal membuat chart untuk <b>{ticker}</b>.\n"
            f"<code>{e}</code>",
            parse_mode=ParseMode.HTML,
        )


def register_chart_handler(app) -> None:
    """Daftarkan handler /chart ke Application. Panggil dari main.py."""
    app.add_handler(CommandHandler("chart", cmd_chart))
