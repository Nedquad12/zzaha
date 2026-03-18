"""
forex_main.py — Orchestrator proses forex

Dipanggil dari main.py setelah proses saham selesai.

Alur:
  FASE 1 — Fetch EOD OHLCV untuk semua pair dari forex.txt
  FASE 2 — Scan Tight (VT/T) dari cache forex
  FASE 3 — Hitung skor + simpan history + alert + xlsx

Commands yang terkait (didaftarkan di main.py):
  /vtf    → tampilkan Very Tight forex
  /tf     → tampilkan Tight forex
  /wccf   → tampilkan WCC forex (pakai cache forex)
  /scorf  → detail score satu pair
  /ch     → chart (dipakai bersama saham, auto detect C: prefix)
"""

import asyncio
import logging
import os
from datetime import datetime

import pandas as pd
from telegram import Bot
from telegram.constants import ParseMode

from config import (
    GROUP_ID, TOPIC_ID,
    FOREX_FILE, OUTPUT_DIR,
    DELAY_BETWEEN_STOCKS, ALERT_SCORE_THRESHOLD,
    FOREX_500_DIR, FOREX_TRAIN_DIR,
)
from forex_api          import fetch_forex_ohlcv
from forex_cache        import save as forex_cache_save, load as forex_cache_load
from forex_tight        import scan_forex_tight, score_forex_tight
from forex_scorer       import calculate_forex_scores, get_forex_weights_info
from forex_storage      import save_forex_to_xlsx
from forex_score_history import process_and_store_forex
from forex_train_db     import init_forex_db, get_ticker_count, get_total_rows
from forex_formatter    import fmt_forex_alert, fmt_forex_top_bottom

logger = logging.getLogger(__name__)


def load_forex_pairs() -> list[str]:
    """
    Baca daftar pair dari forex.txt.
    Format file: satu pair per baris atau dipisah koma, e.g. "AUDUSD" atau "C:AUDUSD"
    Return list uppercase tanpa prefix C:.
    """
    try:
        with open(FOREX_FILE, "r") as f:
            content = f.read()
        pairs = [
            p.strip().upper().removeprefix("C:")
            for p in content.replace("\n", ",").split(",")
            if p.strip()
        ]
        return pairs
    except FileNotFoundError:
        logger.error(f"forex.txt tidak ditemukan: {FOREX_FILE}")
        return []


async def _send_group(bot: Bot, text: str):
    """Kirim pesan ke grup/topik yang sama dengan saham."""
    await bot.send_message(
        chat_id                  = GROUP_ID,
        text                     = text,
        parse_mode               = ParseMode.HTML,
        message_thread_id        = TOPIC_ID,
        disable_web_page_preview = True,
    )


async def process_all_forex(bot: Bot, chat_id: int):
    """
    Entry point utama. Dipanggil dari main.py setelah process_all_stocks() selesai.

    Fase:
      1. Fetch & cache EOD forex
      2. Scan tight (VT/T)
      3. Hitung skor + alert + simpan
    """
    pairs = load_forex_pairs()
    if not pairs:
        await bot.send_message(
            chat_id,
            f"⚠️ Tidak ada pair di <code>{FOREX_FILE}</code>. Skip forex.",
            parse_mode=ParseMode.HTML,
        )
        return

    await bot.send_message(
        chat_id,
        f"💱 <b>Mulai proses forex — {len(pairs)} pair...</b>",
        parse_mode=ParseMode.HTML,
    )

    # ── FASE 1 — Fetch ────────────────────────────────────────────────────────
    raw_data: dict[str, pd.DataFrame] = {}

    for i, pair in enumerate(pairs, 1):
        logger.info(f"[Forex {i}/{len(pairs)}] Fetch {pair}")
        df = fetch_forex_ohlcv(pair)

        if df is None or len(df) < 35:
            logger.warning(f"  {pair}: data tidak cukup, skip")
        else:
            forex_cache_save(pair, df)
            raw_data[pair] = df

        if i < len(pairs):
            await asyncio.sleep(DELAY_BETWEEN_STOCKS)

    await bot.send_message(
        chat_id,
        f"✅ Forex fetch selesai: {len(raw_data)}/{len(pairs)} pair.\n"
        f"⚙️ Menghitung forex tight scan...",
        parse_mode=ParseMode.HTML,
    )

    # ── FASE 2 — Scan Tight ───────────────────────────────────────────────────
    vt_list, t_list = scan_forex_tight()
    vt_set = {e["pair"] for e in vt_list}
    t_set  = {e["pair"] for e in t_list}

    # ── FASE 3 — Hitung Skor ─────────────────────────────────────────────────
    all_results   = []
    alert_count   = 0
    history_count = 0

    for pair, df in raw_data.items():
        ts     = score_forex_tight(pair, vt_set, t_set)
        result = calculate_forex_scores(pair, df, tight_score=ts)

        # Tambahkan info weight untuk /scorf
        wi = get_forex_weights_info(pair)
        result["_weight_info"] = wi

        all_results.append(result)

        # Simpan score history ke forex_train.db
        if len(df) >= 201:
            try:
                process_and_store_forex(pair, df, tight_score=ts)
                history_count += 1
            except Exception as e:
                logger.error(f"  Gagal simpan forex history {pair}: {e}")

        # Alert ke grup kalau skor lolos threshold
        if result["total"] > ALERT_SCORE_THRESHOLD:
            try:
                await _send_group(bot, fmt_forex_alert(result))
                alert_count += 1
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"  Gagal kirim alert forex {pair}: {e}")

    # ── Simpan xlsx ───────────────────────────────────────────────────────────
    filepath = None
    if all_results:
        try:
            filepath = save_forex_to_xlsx(all_results)
        except Exception as e:
            logger.error(f"Gagal simpan forex xlsx: {e}")

    # ── Summary ke chat ───────────────────────────────────────────────────────
    db_rows    = get_total_rows()
    db_pairs   = get_ticker_count()

    await bot.send_message(
        chat_id,
        (
            f"✅ <b>Forex selesai!</b>\n"
            f"💱 Diproses   : {len(all_results)}/{len(pairs)} pair\n"
            f"✨ VT         : {len(vt_set)} pair\n"
            f"📌 T          : {len(t_set)} pair\n"
            f"🔔 Alert      : {alert_count} pair\n"
            f"📈 History    : {history_count} pair tersimpan\n"
            f"🗄 DB Forex   : {db_rows:,} rows | {db_pairs} pair\n"
            f"📁 File       : <code>{filepath or 'gagal simpan'}</code>"
        ),
        parse_mode=ParseMode.HTML,
    )

    # ── Kirim top/bottom forex ke grup ────────────────────────────────────────
    if all_results:
        for msg in fmt_forex_top_bottom(all_results):
            try:
                await _send_group(bot, msg)
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Gagal kirim forex top list: {e}")
