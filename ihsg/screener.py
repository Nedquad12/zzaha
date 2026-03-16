"""
screener.py — Screener otomatis: scan semua ticker, kirim top/bottom 50 ke grup Telegram.

Dipanggil setelah reload atau startup selesai:
    from screener import run_screener
    await run_screener(bot)

Output dikirim ke:
    GROUP_ID = -1002738891883
    TOPIC_ID = 27537  (None jika tidak pakai topic/thread)

Mengirim 2 pesan:
    1. 🏆 Top 50 — skor tertinggi
    2. 💀 Bottom 50 — skor terendah
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

from indicators.loader import build_stock_df, list_available_tickers
from scorer import calculate_all_scores

logger = logging.getLogger(__name__)

# ── Konfigurasi target grup ────────────────────────────────────────────────────
GROUP_ID = -1002738891883
TOPIC_ID = 27537          # set None jika grup biasa (bukan forum/topic)

JSON_DIR = "/home/ec2-user/database/json"

# ── Konstanta tampilan ─────────────────────────────────────────────────────────
TOP_N    = 50
BOTTOM_N = 50


# ══════════════════════════════════════════════════════════════════════════════
#  Scanner
# ══════════════════════════════════════════════════════════════════════════════

def _scan_all(json_dir: str = JSON_DIR) -> list[dict]:
    """
    Scan semua ticker dari JSON terbaru, hitung skor masing-masing.

    Returns:
        list of dict, sudah diurutkan descending by total score.
        Setiap dict: {ticker, total, price, change, date}
    """
    tickers = list_available_tickers(json_dir)
    if not tickers:
        logger.warning("[SCREENER] Tidak ada ticker ditemukan di JSON dir.")
        return []

    results = []
    for ticker in tickers:
        try:
            result = calculate_all_scores(ticker, json_dir=json_dir)
            if result is None:
                continue
            results.append({
                "ticker": result["ticker"],
                "total":  result["total"],
                "price":  result["price"],
                "change": result["change"],
                "date":   result["date"],
            })
        except Exception as e:
            logger.debug(f"[SCREENER] Skip {ticker}: {e}")
            continue

    results.sort(key=lambda x: x["total"], reverse=True)
    logger.info(f"[SCREENER] Scan selesai: {len(results)} ticker berhasil.")
    return results


# ══════════════════════════════════════════════════════════════════════════════
#  Formatter
# ══════════════════════════════════════════════════════════════════════════════

def _fmt_table(title: str, rows: list[dict], built: str) -> str:
    """
    Format list skor menjadi tabel monospace Telegram HTML.
    Satu pesan, maks 4096 karakter (Telegram limit).
    """
    header_line = f"{'No':<4}{'Ticker':<7}{'Total':>6}  {'Harga':>9}  {'Chg%':>6}"
    sep         = "─" * 38

    lines = [
        f"<b>{title}</b>",
        f"<i>{built}  |  {len(rows)} saham</i>",
        "",
        f"<pre>{header_line}",
        sep,
    ]

    for i, r in enumerate(rows, start=1):
        chg    = r["change"]
        chg_s  = f"{chg:+.1f}%" if chg is not None else "  n/a"
        total  = r["total"]
        tot_s  = f"{total:+.1f}"
        price  = r["price"]
        lines.append(
            f"{i:<4}{r['ticker']:<7}{tot_s:>6}  {price:>9,.0f}  {chg_s:>6}"
        )

    lines.append(sep)
    lines.append("</pre>")
    return "\n".join(lines)


def _build_messages(results: list[dict]) -> tuple[str, str]:
    """Return (msg_top, msg_bottom) siap kirim ke Telegram."""
    now   = datetime.now().strftime("%d %b %Y %H:%M WIB")
    top   = results[:TOP_N]
    bot_  = list(reversed(results[-BOTTOM_N:])) if len(results) >= BOTTOM_N else list(reversed(results))

    msg_top    = _fmt_table(f"🏆 Top {len(top)} Skor Tertinggi",  top,  now)
    msg_bottom = _fmt_table(f"💀 Bottom {len(bot_)} Skor Terendah", bot_, now)
    return msg_top, msg_bottom


# ══════════════════════════════════════════════════════════════════════════════
#  Sender
# ══════════════════════════════════════════════════════════════════════════════

async def _send(bot: Bot, text: str) -> None:
    """Kirim satu pesan ke GROUP_ID / TOPIC_ID."""
    kwargs = dict(
        chat_id    = GROUP_ID,
        text       = text,
        parse_mode = ParseMode.HTML,
    )
    if TOPIC_ID is not None:
        kwargs["message_thread_id"] = TOPIC_ID

    try:
        await bot.send_message(**kwargs)
    except TelegramError as e:
        logger.error(f"[SCREENER] Gagal kirim ke grup: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  Public API
# ══════════════════════════════════════════════════════════════════════════════

async def run_screener(bot: Bot, json_dir: str = JSON_DIR) -> None:
    """
    Scan semua ticker dan kirim hasil ke grup Telegram.

    Dipanggil setelah reload/startup:
        from screener import run_screener
        await run_screener(context.bot)

    Args:
        bot      : instance Bot dari telegram.ext
        json_dir : folder JSON harian (default pakai JSON_DIR di atas)
    """
    logger.info("[SCREENER] Mulai scan semua ticker…")

    # Scan di executor agar tidak block event loop
    loop    = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, _scan_all, json_dir)

    if not results:
        logger.warning("[SCREENER] Tidak ada hasil scan, screener dibatalkan.")
        return

    msg_top, msg_bottom = _build_messages(results)

    await _send(bot, msg_top)
    await asyncio.sleep(0.5)   # jeda kecil antar pesan
    await _send(bot, msg_bottom)

    logger.info(
        f"[SCREENER] Selesai — {len(results)} ticker, "
        f"top {TOP_N} & bottom {BOTTOM_N} dikirim ke grup."
    )
