"""
tight_command.py — Handler Telegram untuk /vt dan /t
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging

from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from telegram.constants import ParseMode

from indicators.loader import build_stock_df, list_available_tickers
from indicators.tight import _get_tight_bucket, _calc_mas, _pct_distance, MA_PERIODS
from admin.auth import is_authorized_user, is_vip_user

logger = logging.getLogger(__name__)

JSON_DIR = "/home/ec2-user/database/json"

# ── In-memory cache ────────────────────────────────────────────────────────────
_cache: dict = {
    "vt":    [],
    "t":     [],
    "built": None,
}


# ── Scanner ────────────────────────────────────────────────────────────────────

def build_tight_cache(json_dir: str = JSON_DIR) -> tuple[int, int]:
    from datetime import datetime

    tickers = list_available_tickers(json_dir)
    vt_list = []
    t_list  = []

    for ticker in tickers:
        try:
            df = build_stock_df(ticker, json_dir, max_days=30)
            if df is None or len(df) < max(MA_PERIODS):
                continue

            bucket = _get_tight_bucket(df)
            if bucket is None:
                continue

            close  = float(df["close"].iloc[-1])
            volume = float(df["volume"].iloc[-1])
            value  = (close * volume) / 1_000_000_000

            mas      = _calc_mas(df)
            max_dist = max(_pct_distance(close, mas[p]) for p in MA_PERIODS)

            entry = {
                "ticker":   ticker,
                "close":    close,
                "ma20":     mas[20],
                "volume":   volume,
                "value":    value,
                "max_dist": round(max_dist, 2),
            }

            if bucket == "VT":
                vt_list.append(entry)
            else:
                t_list.append(entry)

        except Exception as e:
            logger.error(f"[{ticker}] tight scan error: {e}")

    vt_list.sort(key=lambda x: x["value"], reverse=True)
    t_list.sort(key=lambda x: x["value"], reverse=True)

    _cache["vt"]    = vt_list
    _cache["t"]     = t_list
    _cache["built"] = datetime.now().strftime("%d %b %Y %H:%M")

    logger.info(f"Tight cache built: {len(vt_list)} VT, {len(t_list)} T")
    return len(vt_list), len(t_list)


# ── Formatter ──────────────────────────────────────────────────────────────────

def _format_table(title: str, results: list[dict], built: str) -> list[str]:
    if not results:
        return [f"```\n{title}\n\nTidak ada saham yang memenuhi kriteria.\n```"]

    header = (
        f"{title}\n"
        f"Data: {built}\n\n"
        f"{'Ticker':<6}  {'Close':>8}  {'MA20':>8}  {'Dist':>6}  {'Val(B)':>7}\n"
        f"{'─' * 44}\n"
    )

    chunks      = []
    chunk_lines = []
    total       = len(results)

    for i, s in enumerate(results):
        line = (
            f"{s['ticker']:<6}  {s['close']:>8,.0f}  {s['ma20']:>8,.0f}"
            f"  {s['max_dist']:>5.2f}%  {s['value']:>6.1f}B\n"
        )
        chunk_lines.append(line)

        if len(chunk_lines) == 30 or i == total - 1:
            is_last = (i == total - 1)
            footer  = (
                f"{'─' * 44}\n"
                f"Total: {total}  |  Dist=jarak close ke MA terjauh  |  Val=miliar Rp"
            ) if is_last else "..."

            chunks.append("```\n" + header + "".join(chunk_lines) + footer + "\n```")
            chunk_lines = []
            header = f"(lanjutan {title})\n{'─' * 44}\n"

    return chunks


# ── Handlers ───────────────────────────────────────────────────────────────────

async def cmd_vt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ── Auth guard ──
    uid = update.effective_user.id
    if not (is_authorized_user(uid) or is_vip_user(uid)):
        await update.message.reply_text("⛔ Kamu tidak punya akses ke bot ini.")
        return

    if not _cache["built"]:
        await update.message.reply_text(
            "⚠️ Cache belum tersedia. Minta admin jalankan `reload` terlebih dahulu.",
        )
        return

    for chunk in _format_table("🔥 Very Tight Stocks", _cache["vt"], _cache["built"]):
        await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_t(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ── Auth guard ──
    uid = update.effective_user.id
    if not (is_authorized_user(uid) or is_vip_user(uid)):
        await update.message.reply_text("⛔ Kamu tidak punya akses ke bot ini.")
        return

    if not _cache["built"]:
        await update.message.reply_text(
            "⚠️ Cache belum tersedia. Minta admin jalankan `reload` terlebih dahulu.",
        )
        return

    for chunk in _format_table("✨ Tight Stocks", _cache["t"], _cache["built"]):
        await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN_V2)


# ── Registration ───────────────────────────────────────────────────────────────

def register_tight_handlers(app, json_dir: str = JSON_DIR):
    global JSON_DIR
    JSON_DIR = json_dir
    app.add_handler(CommandHandler("vt", cmd_vt))
    app.add_handler(CommandHandler("t",  cmd_t))
