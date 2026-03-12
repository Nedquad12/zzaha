"""
main.py — Telegram Bot entry point
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncio
import logging
from datetime import datetime

import pandas as pd
from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from config import (
    TELEGRAM_BOT_TOKEN, GROUP_ID, TOPIC_ID,
    STOCK_FILE, OUTPUT_DIR,
    DELAY_BETWEEN_STOCKS, ALERT_SCORE_THRESHOLD,
    SR_METHOD_DONCHIAN, SR_SENSITIVITY,
    ALLOWED_IDS,
)
from api          import fetch_ohlcv
from cache        import reset_cache, save as cache_save, load as cache_load, list_cached
from scorer       import calculate_all_scores
from storage      import save_to_xlsx
from formatter    import fmt_alert, fmt_detail, fmt_top_bottom, fmt_ip_table, fmt_vfa_table, fmt_wcc_table
from chart        import generate_chart
from chart_ts     import generate_ts_chart
from tight        import scan_tight, score_tight, format_vt, format_t
from indicators   import get_vfa_detail, get_wcc_detail
from score_history import process_and_store
from train_db     import init_db, get_ticker_count, get_total_rows

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

VALID_METHODS = {
    "d": SR_METHOD_DONCHIAN, "donchian": SR_METHOD_DONCHIAN,
    "p": "Pivots",           "pivots":   "Pivots",
    "c": "CSID",             "csid":     "CSID",
    "z": "ZigZag",           "zigzag":   "ZigZag",
}


# ── Access helper ─────────────────────────────────────────────────────────────

def is_allowed(user_id: int) -> bool:
    return user_id in ALLOWED_IDS


# ── Telegram helpers ──────────────────────────────────────────────────────────

async def send_group(bot: Bot, text: str):
    await bot.send_message(
        chat_id                  = GROUP_ID,
        text                     = text,
        parse_mode               = ParseMode.HTML,
        message_thread_id        = TOPIC_ID,
        disable_web_page_preview = True,
    )


# ── Core processing ───────────────────────────────────────────────────────────

async def process_all_stocks(bot: Bot, chat_id: int):
    """Proses semua saham: reset cache → fetch → hitung → simpan xlsx → alert."""

    # 1. Baca ticker
    try:
        with open(STOCK_FILE, "r") as f:
            content = f.read()
        tickers = [t.strip().upper() for t in content.replace("\n", ",").split(",") if t.strip()]
    except FileNotFoundError:
        await bot.send_message(chat_id,
            f"❌ File tidak ditemukan: <code>{STOCK_FILE}</code>",
            parse_mode=ParseMode.HTML)
        return

    if not tickers:
        await bot.send_message(chat_id, "❌ Tidak ada ticker di stock.txt")
        return

    # 2. Reset cache
    reset_cache()
    await bot.send_message(
        chat_id,
        f"🗑 Cache direset.\n⚙️ Mulai memproses <b>{len(tickers)}</b> saham...",
        parse_mode=ParseMode.HTML,
    )

    # 3. Fase 1 — Fetch semua data & simpan ke cache
    raw_data: dict[str, pd.DataFrame] = {}
    for i, ticker in enumerate(tickers, 1):
        logger.info(f"[{i}/{len(tickers)}] Fetch {ticker}")
        df = fetch_ohlcv(ticker)
        if df is None or len(df) < 35:
            logger.warning(f"  {ticker}: data tidak cukup, skip")
        else:
            cache_save(ticker, df)
            raw_data[ticker] = df
        if i < len(tickers):
            await asyncio.sleep(DELAY_BETWEEN_STOCKS)

    await bot.send_message(
        chat_id,
        f"✅ Fetch selesai: {len(raw_data)}/{len(tickers)} saham.\n"
        f"⚙️ Menghitung tight scan...",
        parse_mode=ParseMode.HTML,
    )

    # 4. Fase 2 — Scan VT/T dari cache (semua ticker sekaligus)
    vt_list, t_list = scan_tight()
    vt_set = {s["ticker"] for s in vt_list}
    t_set  = {s["ticker"] for s in t_list}
    logger.info(f"VT: {len(vt_set)} saham, T: {len(t_set)} saham")

    # 5. Fase 3 — Hitung semua skor + simpan score history
    all_results = []
    alert_count = 0
    history_count = 0

    for ticker, df in raw_data.items():
        ts     = score_tight(ticker, vt_set, t_set)
        result = calculate_all_scores(ticker, df, tight_score=ts)
        all_results.append(result)
        logger.info(
           f"  {ticker} → total: {result['total']:+.2f}  "
           f"tight: {int(ts):+d}  vfa: {int(result['vfa']):+d}  wcc: {int(result['wcc']):+d}"
        )

        # Simpan score history (300 bar) ke JSON + SQLite
        if len(df) >= 201:   # minimal warmup + 1 bar
            try:
                process_and_store(ticker, df, tight_score=ts)
                history_count += 1
            except Exception as e:
                logger.error(f"  Gagal simpan history {ticker}: {e}")

        if result["total"] > ALERT_SCORE_THRESHOLD:
            try:
                await send_group(bot, fmt_alert(result))
                alert_count += 1
                await asyncio.sleep(1.5) 
            except Exception as e:
                logger.error(f"  Gagal kirim alert {ticker}: {e}")

    # 6. Simpan xlsx
    filepath = None
    if all_results:
        try:
            filepath = save_to_xlsx(all_results)
        except Exception as e:
            logger.error(f"Gagal simpan xlsx: {e}")

    # 7. Summary ke admin
    db_rows = get_total_rows()
    db_tickers = get_ticker_count()
    await bot.send_message(
        chat_id,
        (
            f"✅ <b>Selesai!</b>\n"
            f"📊 Diproses   : {len(all_results)}/{len(tickers)} saham\n"
            f"✨ VT         : {len(vt_set)} saham\n"
            f"📌 T          : {len(t_set)} saham\n"
            f"🔔 Alert      : {alert_count} saham\n"
            f"📈 History    : {history_count} saham tersimpan\n"
            f"🗄 DB         : {db_rows:,} rows | {db_tickers} ticker\n"
            f"📁 File       : <code>{filepath or 'gagal simpan'}</code>"
        ),
        parse_mode=ParseMode.HTML,
    )

    # 8. Top & Bottom 50 ke grup
    if all_results:
        for msg in fmt_top_bottom(all_results):
            try:
                await send_group(bot, msg)
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Gagal kirim top list: {e}")


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/9 — hanya allowed IDs."""
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Anda tidak memiliki akses.")
        return
    await update.message.reply_text("🚀 <b>Kalkulasi dimulai...</b>",
                                    parse_mode=ParseMode.HTML)
    asyncio.create_task(process_all_stocks(context.bot, update.effective_chat.id))


async def cmd_scor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/scor [TICKER] — hanya allowed IDs."""
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Anda tidak memiliki akses.")
        return

    args = context.args

    if args:
        ticker = args[0].upper()
        await update.message.reply_text(f"⏳ Mengambil data <b>{ticker}</b>...",
                                        parse_mode=ParseMode.HTML)
        df = cache_load(ticker)
        if df is None:
            df = fetch_ohlcv(ticker)
        if df is None or len(df) < 35:
            await update.message.reply_text(f"❌ Data tidak cukup untuk {ticker}")
            return

        vt_list, t_list = scan_tight()
        vt_set = {s["ticker"] for s in vt_list}
        t_set  = {s["ticker"] for s in t_list}
        ts     = score_tight(ticker, vt_set, t_set)

        result = calculate_all_scores(ticker, df, tight_score=ts)
        await update.message.reply_text(fmt_detail(result), parse_mode=ParseMode.HTML)

    else:
        today    = datetime.today().strftime("%Y-%m-%d")
        filepath = os.path.join(OUTPUT_DIR, f"score_{today}.xlsx")
        if not os.path.exists(filepath):
            await update.message.reply_text(
                "❌ Belum ada data hari ini. Jalankan /9 terlebih dahulu.")
            return
        try:
            df_xlsx   = pd.read_excel(filepath)
            df_sorted = df_xlsx.sort_values("Total Score", ascending=False)
            rows = df_sorted.rename(columns={
                "Ticker": "ticker", "Total Score": "total",
                "IP Score": "ip_score", "VSA": "vsa", "FSA": "fsa",
                "VFA": "vfa", "WCC": "wcc", "RSI": "rsi",
                "MACD": "macd", "MA": "ma", "Tight": "tight",
                "SRST": "srst",
            }).to_dict("records")
            for msg in fmt_ip_table(rows):
                await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
                await asyncio.sleep(0.3)
        except Exception as e:
            await update.message.reply_text(f"❌ Error membaca xlsx: {e}")


async def cmd_vtus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/vtus — daftar Very Tight, semua member bisa akses."""
    await update.message.reply_text("⏳ Scanning Very Tight stocks dari cache...")
    try:
        vt_list, _ = scan_tight()
        await update.message.reply_text(format_vt(vt_list), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error cmd_vtus: {e}")
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_tus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/tus — daftar Tight, semua member bisa akses."""
    await update.message.reply_text("⏳ Scanning Tight stocks dari cache...")
    try:
        _, t_list = scan_tight()
        await update.message.reply_text(format_t(t_list), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error cmd_tus: {e}")
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_vfa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/vfa — tabel VFA semua saham dari cache, semua member bisa akses."""
    await update.message.reply_text("⏳ Mengambil data VFA dari cache...")

    tickers = list_cached()
    if not tickers:
        await update.message.reply_text(
            "❌ Cache kosong. Jalankan /9 terlebih dahulu.")
        return

    rows = []
    for ticker in tickers:
        df = cache_load(ticker)
        if df is None or len(df) < 8:
            continue
        detail = get_vfa_detail(df)
        price  = float(df["close"].iloc[-1])
        prev   = float(df["close"].iloc[-2]) if len(df) > 1 else price
        change = ((price - prev) / prev * 100) if prev != 0 else 0.0
        rows.append({
            "ticker":   ticker,
            "price":    round(price, 2),
            "change":   round(change, 2),
            "vfa":      detail["score"],
            "avg_vol":  detail["avg_vol"],
            "avg_freq": detail["avg_freq"],
            "total":    0.0,
        })

    if not rows:
        await update.message.reply_text("❌ Tidak ada data VFA yang cukup.")
        return

    rows.sort(key=lambda x: (x["vfa"], x["avg_freq"]), reverse=True)

    try:
        for msg in fmt_vfa_table(rows):
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
            await asyncio.sleep(0.3)
    except Exception as e:
        logger.error(f"Error cmd_vfa: {e}")
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_wcc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/wcc — tabel WCC semua saham dari cache, semua member bisa akses."""
    await update.message.reply_text("⏳ Mengambil data WCC dari cache...")

    tickers = list_cached()
    if not tickers:
        await update.message.reply_text(
            "❌ Cache kosong. Jalankan /9 terlebih dahulu.")
        return

    rows = []
    for ticker in tickers:
        df = cache_load(ticker)
        if df is None or len(df) < 2:
            continue
        detail = get_wcc_detail(df)
        price  = float(df["close"].iloc[-1])
        rows.append({
            "ticker":         ticker,
            "price":          round(price, 2),
            "wcc":            detail["score"],
            "direction":      detail["direction"],
            "open_to_close":  detail["open_to_close"],
            "wick_to_body":   detail["wick_to_body"],
            "ratio":          detail["ratio"],
        })

    if not rows:
        await update.message.reply_text("❌ Tidak ada data WCC yang cukup.")
        return

    rows.sort(key=lambda x: x["wcc"], reverse=True)

    try:
        for msg in fmt_wcc_table(rows):
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
            await asyncio.sleep(0.3)
    except Exception as e:
        logger.error(f"Error cmd_wcc: {e}")
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ch TICKER [METHOD] [SENSITIVITY] atau /ch ts TICKER"""
    args = context.args

    if not args:
        await update.message.reply_text(
            "⚠️ Format:\n"
            "<code>/ch TICKER [method] [sensitivity]</code>\n"
            "<code>/ch ts TICKER</code> — Chart Total Score vs Price\n\n"
            "Method S&R: donchian(d) | pivots(p) | csid(c) | zigzag(z)",
            parse_mode=ParseMode.HTML)
        return

    # ── Sub-command: /ch ts TICKER ─────────────────────────────────────────
    if args[0].lower() == "ts":
        if len(args) < 2:
            await update.message.reply_text(
                "⚠️ Format: <code>/ch ts TICKER</code>",
                parse_mode=ParseMode.HTML)
            return

        ticker = args[1].upper()
        status = await update.message.reply_text(
            f"📊 Membuat chart Total Score <b>{ticker}</b>...",
            parse_mode=ParseMode.HTML)
        try:
            buf = generate_ts_chart(ticker)
            await update.message.reply_photo(photo=buf)
            await status.delete()
        except ValueError as e:
            await status.edit_text(f"❌ {e}")
        except Exception as e:
            logger.error(f"Gagal generate TS chart {ticker}: {e}")
            await status.edit_text(f"❌ Gagal membuat chart: {e}")
        return

    # ── Default: /ch TICKER [method] [sens] ────────────────────────────────
    ticker = args[0].upper()
    method = SR_METHOD_DONCHIAN
    sens   = float(SR_SENSITIVITY)

    if len(args) >= 2:
        mk = args[1].lower()
        if mk not in VALID_METHODS:
            await update.message.reply_text(
                f"⚠️ Method tidak dikenal: <b>{args[1]}</b>\n"
                f"Pilihan: donchian(d) | pivots(p) | csid(c) | zigzag(z)",
                parse_mode=ParseMode.HTML)
            return
        method = VALID_METHODS[mk]

    if len(args) >= 3:
        try:
            sens = float(args[2])
        except ValueError:
            await update.message.reply_text("⚠️ Sensitivity harus berupa angka.")
            return

    status = await update.message.reply_text(
        f"📊 Membuat chart <b>{ticker}</b>...", parse_mode=ParseMode.HTML)

    df = cache_load(ticker)
    if df is None:
        df = fetch_ohlcv(ticker)
    if df is None or len(df) < 35:
        await status.edit_text(f"❌ Data tidak tersedia untuk <b>{ticker}</b>.",
                               parse_mode=ParseMode.HTML)
        return

    try:
        buf = generate_chart(ticker, df, method=method, sens=sens)
        await update.message.reply_photo(photo=buf)
        await status.delete()
    except Exception as e:
        logger.error(f"Gagal generate chart {ticker}: {e}")
        await status.edit_text(f"❌ Gagal membuat chart: {e}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    # Inisialisasi DB ML saat bot start
    init_db()
    logger.info("Train DB siap.")

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .build()
     )
    app.add_handler(CommandHandler("9",     cmd_trigger))
    app.add_handler(CommandHandler("scor",  cmd_scor))
    app.add_handler(CommandHandler("vtus",  cmd_vtus))
    app.add_handler(CommandHandler("tus",   cmd_tus))
    app.add_handler(CommandHandler("vfa",   cmd_vfa))
    app.add_handler(CommandHandler("wcc",   cmd_wcc))
    app.add_handler(CommandHandler("ch",    cmd_chart))

    logger.info("Bot started. Listening...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
