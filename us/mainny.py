"""
main.py — Telegram Bot entry point
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncio
import logging
from datetime import datetime
from telegram.constants import ParseMode

import pandas as pd
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from config import (
    TELEGRAM_BOT_TOKEN, GROUP_ID, TOPIC_ID,
    STOCK_FILE, OUTPUT_DIR,
    DELAY_BETWEEN_STOCKS, ALERT_SCORE_THRESHOLD,
    SR_METHOD_DONCHIAN, SR_SENSITIVITY,
    ALLOWED_IDS,
    OHLCV_500_DIR, TRAIN_DIR, 
)
from api          import fetch_ohlcv, check_data_freshness
from cache        import reset_cache, save as cache_save, load as cache_load, list_cached
from scorer       import calculate_all_scores
from storage      import save_to_xlsx, update_xlsx_weights
from backtest     import run_backtest, run_ml
from formatter    import fmt_alert, fmt_detail, fmt_top_bottom, fmt_ip_table, fmt_vfa_table, fmt_wcc_table
from chart        import generate_chart
from chart_html   import generate_html_chart
from chart_ts     import generate_ts_chart
from chart_ts_html import generate_ts_html_chart
from tight        import scan_tight, score_tight, format_vt, format_t
from indicators   import get_vfa_detail, get_wcc_detail
from score_history import process_and_store
from train_db     import init_db, get_ticker_count, get_total_rows
from ai_analyst  import run_ai_analysis
from forex_main         import process_all_forex
from forex_cache        import reset_forex_cache, load as forex_cache_load, list_cached as forex_list_cached
from forex_tight        import scan_forex_tight, score_forex_tight, format_forex_vt, format_forex_t
from forex_scorer       import calculate_forex_scores, get_forex_weights_info
from forex_formatter    import fmt_forex_detail
from config             import (
    FOREX_FILE, FOREX_CACHE_DIR, FOREX_500_DIR, FOREX_TRAIN_DIR, FOREX_WEIGHTS_DIR
)
from forex_train_db     import init_forex_db

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

# ── Reset semua data lama saat /9 ────────────────────────────────────────────

def _reset_all_data() -> dict:

    summary = {}

    # 1. Cache OHLCV harian
    reset_cache()   # sudah handle shutil.rmtree + recreate
    summary["cache"] = "✅"

    # 2. JSON 500-bar score history
    deleted_500 = 0
    if os.path.exists(OHLCV_500_DIR):
        for f in os.listdir(OHLCV_500_DIR):
            if f.endswith(".json"):
                os.remove(os.path.join(OHLCV_500_DIR, f))
                deleted_500 += 1
    summary["500_json"] = f"✅ ({deleted_500} file)"

    # 3. train.db
    DB_PATH = os.path.join(TRAIN_DIR, "train.db")
    deleted_db = False
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        deleted_db = True
    # Re-init agar tabel langsung tersedia
    init_db()
    summary["train_db"] = "✅" if deleted_db else "✅ (sudah kosong)"

    # 4. Semua xlsx score di OUTPUT_DIR
    deleted_xlsx = 0
    if os.path.exists(OUTPUT_DIR):
        for f in os.listdir(OUTPUT_DIR):
            if f.startswith("score_") and f.endswith(".xlsx"):
                os.remove(os.path.join(OUTPUT_DIR, f))
                deleted_xlsx += 1
    summary["xlsx"] = f"✅ ({deleted_xlsx} file)"

    # 5. Forex cache
    reset_forex_cache()
    summary["forex_cache"] = "✅"

    # 6. Forex 500-bar JSON
    deleted_forex_500 = 0
    if os.path.exists(FOREX_500_DIR):
        for f in os.listdir(FOREX_500_DIR):
            if f.endswith(".json"):
                os.remove(os.path.join(FOREX_500_DIR, f))
                deleted_forex_500 += 1
    summary["forex_500_json"] = f"✅ ({deleted_forex_500} file)"

    # 7. Forex train.db
    from forex_train_db import reset_forex_db
    reset_forex_db()
    summary["forex_train_db"] = "✅"

    # 8. Forex xlsx
    deleted_forex_xlsx = 0
    if os.path.exists(OUTPUT_DIR):
        for f in os.listdir(OUTPUT_DIR):
            if f.startswith("forex_score_") and f.endswith(".xlsx"):
                os.remove(os.path.join(OUTPUT_DIR, f))
                deleted_forex_xlsx += 1
    summary["forex_xlsx"] = f"✅ ({deleted_forex_xlsx} file)"
    logger.info(f"Reset selesai: {summary}")
    return summary

# ── Pending chart requests (for inline keyboard callbacks) ────────────────────
# key: callback_data prefix  →  dict with chart params
_pending_charts: dict[str, dict] = {}

# ── Whitelist helper ──────────────────────────────────────────────────────────

def _load_whitelist() -> set[str]:
    """Baca daftar ticker dari stock.txt, return sebagai set uppercase."""
    try:
        with open(STOCK_FILE, "r") as f:
            content = f.read()
        return {t.strip().upper() for t in content.replace("\n", ",").split(",") if t.strip()}
    except FileNotFoundError:
        return set()


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

    # ── Baca daftar ticker ────────────────────────────────────────────────────
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

    # ── FASE 1 — Reset semua data lama & Fetch ───────────────────────────────
    summary = _reset_all_data()
    await bot.send_message(
        chat_id,
        (
            f"🗑 <b>Reset selesai:</b>\n"
            f"  • Cache OHLCV  : {summary['cache']}\n"
            f"  • 500-bar JSON : {summary['500_json']}\n"
            f"  • train.db     : {summary['train_db']}\n"
            f"  • Score xlsx   : {summary['xlsx']}\n"
            f"  • Forex cache  : {summary['forex_cache']}\n"
            f"  • Forex JSON   : {summary['forex_500_json']}\n"
            f"  • Forex DB     : {summary['forex_train_db']}\n"
            f"  • Forex xlsx   : {summary['forex_xlsx']}\n\n"
            f"⚙️ Mulai memproses <b>{len(tickers)}</b> saham..."
        ),
        parse_mode=ParseMode.HTML,
    )

    raw_data: dict[str, pd.DataFrame] = {}
    data_freshness_checked = False

    for i, ticker in enumerate(tickers, 1):
        logger.info(f"[{i}/{len(tickers)}] Fetch {ticker}")
        df = fetch_ohlcv(ticker)

        if df is None or len(df) < 35:
            logger.warning(f"  {ticker}: data tidak cukup, skip")
        else:
            # Cek freshness sekali saja pakai ticker pertama yang berhasil
            if not data_freshness_checked:
                is_fresh, warn_msg = check_data_freshness(df)
                if not is_fresh:
                    await bot.send_message(chat_id, warn_msg, parse_mode=ParseMode.HTML)
                data_freshness_checked = True

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

    # ── FASE 2 — Scan Tight ───────────────────────────────────────────────────
    vt_list, t_list = scan_tight()
    vt_set = {s["ticker"] for s in vt_list}
    t_set  = {s["ticker"] for s in t_list}

    # ── FASE 3 — Hitung Skor ─────────────────────────────────────────────────
    all_results   = []
    alert_count   = 0
    history_count = 0

    for ticker, df in raw_data.items():
        ts     = score_tight(ticker, vt_set, t_set)
        result = calculate_all_scores(ticker, df, tight_score=ts)
        all_results.append(result)

        if len(df) >= 201:
            try:
                process_and_store(ticker, df, tight_score=ts)
                history_count += 1
            except Exception as e:
                logger.error(f"  Gagal simpan history {ticker}: {e}")

        if result["total"] > ALERT_SCORE_THRESHOLD:
            try:
                await send_group(bot, fmt_alert(result))
                alert_count += 1
                await asyncio.sleep(10)
            except Exception as e:
                logger.error(f"  Gagal kirim alert {ticker}: {e}")

    # ── Simpan xlsx ───────────────────────────────────────────────────────────
    filepath = None
    if all_results:
        try:
            filepath = save_to_xlsx(all_results)
        except Exception as e:
            logger.error(f"Gagal simpan xlsx: {e}")

    # ── Summary ───────────────────────────────────────────────────────────────
    db_rows    = get_total_rows()
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

    # ── Kirim top/bottom list ke grup ─────────────────────────────────────────
    if all_results:
        for msg in fmt_top_bottom(all_results):
            try:
                await send_group(bot, msg)
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Gagal kirim top list: {e}")
                
    # ── FOREX — Proses setelah saham ─────────────────────────────────────────
    try:
        await process_all_forex(bot, chat_id)
    except Exception as e:
        logger.error(f"Gagal proses forex: {e}")
        await bot.send_message(
            chat_id,
            f"❌ Error saat proses forex: <code>{e}</code>",
            parse_mode=ParseMode.HTML,
        )

# ── Chart helpers ─────────────────────────────────────────────────────────────

async def _send_chart_format_picker(
    update: Update,
    ticker: str,
    method: str,
    sens: float,
    is_ts: bool = False,
):
    """Kirim pesan dengan inline keyboard pilihan PNG / HTML."""
    key = f"chart_{ticker}_{method}_{sens}_{is_ts}_{int(datetime.now().timestamp())}"
    _pending_charts[key] = {
        "ticker": ticker,
        "method": method,
        "sens":   sens,
        "is_ts":  is_ts,
    }
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🖼 PNG  (gambar)", callback_data=f"{key}|png"),
            InlineKeyboardButton("🌐 HTML (interaktif)", callback_data=f"{key}|html"),
        ]
    ])
    label = "Total Score" if is_ts else f"{ticker} — {method} S&R"
    await update.message.reply_text(
        f"📊 <b>{label}</b>\nPilih format chart:",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )

async def _deliver_chart(
    query,
    params: dict,
    fmt: str,
):
    """Eksekusi pembuatan chart sesuai format yang dipilih."""
    ticker = params["ticker"]
    method = params["method"]
    sens   = params["sens"]
    is_ts  = params["is_ts"]

    await query.edit_message_text(
        f"⏳ Membuat chart <b>{ticker}</b> format <b>{fmt.upper()}</b>...",
        parse_mode=ParseMode.HTML,
    )

    try:
        if is_ts:
            if fmt == "html":
                buf   = generate_ts_html_chart(ticker)
                fname = f"{ticker}_score_chart.html"
                await query.message.reply_document(
                    document=buf,
                    filename=fname,
                    caption=(
                        f"🌐 <b>{ticker}</b> — Total Score Chart (Interaktif)\n"
                        f"<i>Buka file HTML di browser</i>"
                    ),
                    parse_mode=ParseMode.HTML,
                )
            else:
                buf = generate_ts_chart(ticker)
                await query.message.reply_photo(photo=buf, caption=f"📊 {ticker} — Total Score History")
        elif fmt == "html":
            df = cache_load(ticker)
            if df is None:
               df = fetch_ohlcv(ticker)
            if df is None or len(df) < 35:
               await query.edit_message_text(f"❌ Data tidak tersedia untuk <b>{ticker}</b>.", parse_mode=ParseMode.HTML)
               return
            buf = generate_html_chart(ticker, df, method=method, sens=sens)
            fname = f"{ticker}_{method}_chart.html"
            await query.message.reply_document(
                document=buf,
                filename=fname,
                caption=(
                    f"🌐 <b>{ticker}</b> — Interactive Chart\n"
                    f"Method: {method} | Sensitivity: {sens}\n"
                    f"<i>Buka file HTML di browser untuk chart interaktif TradingView-style</i>"
                ),
                parse_mode=ParseMode.HTML,
            )
        else:  # PNG
            df = cache_load(ticker)
            if df is None:
               df = fetch_ohlcv(ticker)
            if df is None or len(df) < 35:
              await query.edit_message_text(f"❌ Data tidak tersedia untuk <b>{ticker}</b>.", parse_mode=ParseMode.HTML)
              return
            buf = generate_chart(ticker, df, method=method, sens=sens)
            await query.message.reply_photo(photo=buf, caption=f"📈 {ticker} — {method} S&R Chart")

        await query.delete_message()

    except ValueError as e:
        await query.edit_message_text(f"❌ {e}")
    except Exception as e:
        logger.error(f"Gagal generate chart {ticker}: {e}")
        await query.edit_message_text(f"❌ Gagal membuat chart: {e}")


# ── Callback handler for inline keyboard ─────────────────────────────────────

async def callback_chart_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pilihan format PNG / HTML dari inline keyboard."""
    query = update.callback_query
    await query.answer()

    data = query.data  # e.g. "chart_AAPL_Donchian_10.0_False_1234567890|png"
    if "|" not in data:
        return

    key, fmt = data.rsplit("|", 1)
    params = _pending_charts.get(key)
    if not params:
        await query.edit_message_text("❌ Request sudah kadaluarsa. Jalankan /ch lagi.")
        return

    # Cleanup
    _pending_charts.pop(key, None)
    if params.get("is_forex"):
        await _deliver_forex_chart(query, params, fmt)
    else:
        await _deliver_chart(query, params, fmt)


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/9 — hanya allowed IDs."""
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Anda tidak memiliki akses.")
        return
    await update.message.reply_text("🚀 <b>Kalkulasi dimulai...</b>", parse_mode=ParseMode.HTML)
    asyncio.create_task(process_all_stocks(context.bot, update.effective_chat.id))


async def cmd_scor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/scor [TICKER] — hanya allowed IDs."""
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Anda tidak memiliki akses.")
        return

    args = context.args
    if args:
        ticker = args[0].upper()
        await update.message.reply_text(f"⏳ Mengambil data <b>{ticker}</b>...", parse_mode=ParseMode.HTML)
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
            await update.message.reply_text("❌ Belum ada data hari ini. Jalankan /9 terlebih dahulu.")
            return
        try:
            df_xlsx   = pd.read_excel(filepath)
            df_sorted = df_xlsx.sort_values("Total Score", ascending=False)
            rows = df_sorted.rename(columns={
                "Ticker": "ticker", "Total Score": "total",
                "IP Score": "ip_score", "VSA": "vsa", "FSA": "fsa",
                "VFA": "vfa", "WCC": "wcc", "RSI": "rsi",
                "MACD": "macd", "MA": "ma", "Tight": "tight", "SRST": "srst",
            }).to_dict("records")
            for msg in fmt_ip_table(rows):
                await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
                await asyncio.sleep(0.3)
        except Exception as e:
            await update.message.reply_text(f"❌ Error membaca xlsx: {e}")


async def cmd_vtus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Scanning Very Tight stock...")
    try:
        vt_list, _ = scan_tight()
        await update.message.reply_text(format_vt(vt_list), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_tus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Scanning Tight stocks...")
    try:
        _, t_list = scan_tight()
        await update.message.reply_text(format_t(t_list), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_vfa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Mengambil data VFA...")
    tickers = list_cached()
    if not tickers:
        await update.message.reply_text("❌ Cache kosong. Jalankan /9 terlebih dahulu.")
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
            "ticker": ticker, "price": round(price, 2), "change": round(change, 2),
            "vfa": detail["score"], "avg_vol": detail["avg_vol"],
            "avg_freq": detail["avg_freq"], "total": 0.0,
        })
    if not rows:
        await update.message.reply_text("❌ Tidak ada data VFA yang cukup.")
        return
    rows.sort(key=lambda x: (x["vfa"], x["avg_freq"]), reverse=True)
    for msg in fmt_vfa_table(rows):
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        await asyncio.sleep(0.3)


async def cmd_wcc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Mengambil data WCC...")
    tickers = list_cached()
    if not tickers:
        await update.message.reply_text("❌ Cache kosong. Jalankan /9 terlebih dahulu.")
        return
    rows = []
    for ticker in tickers:
        df = cache_load(ticker)
        if df is None or len(df) < 2:
            continue
        detail = get_wcc_detail(df)
        price  = float(df["close"].iloc[-1])
        rows.append({
            "ticker": ticker, "price": round(price, 2),
            "wcc": detail["score"], "direction": detail["direction"],
            "open_to_close": detail["open_to_close"],
            "wick_to_body": detail["wick_to_body"], "ratio": detail["ratio"],
        })
    if not rows:
        await update.message.reply_text("❌ Tidak ada data WCC yang cukup.")
        return
    rows.sort(key=lambda x: x["wcc"], reverse=True)
    for msg in fmt_wcc_table(rows):
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        await asyncio.sleep(0.3)
        
async def cmd_chart(update, context):
    args = context.args

    if not args:
        await update.message.reply_text(
            "⚠️ Format:\n"
            "<code>/ch TICKER [method] [sensitivity]</code>\n"
            "<code>/ch ts TICKER</code>       — Chart Total Score vs Price\n"
            "<code>/ch ts bt TICKER</code>    — Backtest model untuk ticker\n"
            "<code>/ch ts bt ml TICKER</code> — ML adjust weight + backtest\n"
            "<code>/ch ts bt ai TICKER</code> — AI evaluasi model (DeepSeek R1)\n\n"
            "Method S&R: donchian(d) | pivots(p) | csid(c) | zigzag(z)\n\n"
            "Format output: <b>PNG</b> (gambar) atau <b>HTML</b> (interaktif)",
            parse_mode=ParseMode.HTML,
        )
        return

    # ── /ch ts ... ───────────────────────────────────────────────────────────
    if args[0].lower() == "ts":

        # /ch ts bt ai TICKER
        if len(args) >= 4 and args[1].lower() == "bt" and args[2].lower() == "ai":
            ticker = args[3].upper()
            await update.message.reply_text(
                f"🤖 <b>Meminta analisis AI untuk {ticker}...</b>\n"
                f"⏳ DeepSeek R1 sedang berpikir, mohon tunggu (bisa 30-60 detik)...",
                parse_mode=ParseMode.HTML,
            )
            try:
                msgs = run_ai_analysis(ticker)
                for msg in msgs:
                    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
                    import asyncio; await asyncio.sleep(0.5)
            except Exception as e:
                await update.message.reply_text(f"❌ Error AI: {e}", parse_mode=ParseMode.HTML)
            return

        # /ch ts bt ml TICKER
        if len(args) >= 4 and args[1].lower() == "bt" and args[2].lower() == "ml":
            ticker = args[3].upper()
            await update.message.reply_text(
                f"🤖 <b>Menjalankan ML untuk {ticker}...</b>\n"
                f"⏳ Training XGBoost, mohon tunggu...",
                parse_mode=ParseMode.HTML,
            )
            try:
                msgs = run_ml(ticker)
                for msg in msgs:
                    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
                    import asyncio; await asyncio.sleep(0.5)

                # Update xlsx dengan weight baru
                import os, asyncio
                from datetime import datetime
                from config import OUTPUT_DIR
                import pandas as pd

                today    = datetime.today().strftime("%Y-%m-%d")
                filepath = os.path.join(OUTPUT_DIR, f"score_{today}.xlsx")

                if os.path.exists(filepath):
                    try:
                        df_xlsx = pd.read_excel(filepath)
                        results = df_xlsx.rename(columns={
                            "Ticker": "ticker", "Date": "date",
                            "Price": "price", "Change%": "change",
                            "VSA": "vsa", "FSA": "fsa", "VFA": "vfa",
                            "WCC": "wcc", "SRST": "srst", "RSI": "rsi",
                            "MACD": "macd", "MA": "ma",
                            "IP Raw": "ip_raw", "IP Score": "ip_score",
                            "Tight": "tight", "Total Score": "total",
                        }).to_dict("records")
                        update_xlsx_weights(results)
                        await update.message.reply_text(
                            f"✅ <b>xlsx hari ini sudah di-update</b> dengan weight baru.\n"
                            f"<code>{filepath}</code>",
                            parse_mode=ParseMode.HTML,
                        )
                    except Exception as e:
                        await update.message.reply_text(
                            f"⚠️ Weight disimpan, tapi gagal update xlsx: {e}",
                            parse_mode=ParseMode.HTML,
                        )
                else:
                    await update.message.reply_text(
                        "ℹ️ Tidak ada xlsx hari ini. Weight tersimpan dan berlaku di /9 berikutnya.",
                        parse_mode=ParseMode.HTML,
                    )
            except Exception as e:
                await update.message.reply_text(f"❌ Error ML: {e}", parse_mode=ParseMode.HTML)
            return

        # /ch ts bt TICKER
        if len(args) >= 3 and args[1].lower() == "bt":
            ticker = args[2].upper()
            await update.message.reply_text(
                f"⏳ <b>Menjalankan backtest untuk {ticker}...</b>",
                parse_mode=ParseMode.HTML,
            )
            try:
                msg = run_backtest(ticker)
                await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
            except Exception as e:
                await update.message.reply_text(f"❌ Error backtest: {e}", parse_mode=ParseMode.HTML)
            return

        # /ch ts TICKER (chart biasa)
        if len(args) < 2:
            await update.message.reply_text(
                "⚠️ Format: <code>/ch ts TICKER</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        ticker = args[1].upper()
        if ticker not in _load_whitelist():
            await update.message.reply_text(
                f"⚠️ <b>{ticker}</b> tidak tersedia.\n"
                f"Hanya saham S&P 500 yang didukung.",
                parse_mode=ParseMode.HTML,
            )
            return
        await _send_chart_format_picker(update, ticker, SR_METHOD_DONCHIAN, float(SR_SENSITIVITY), is_ts=True)
        return

    # ── Default: /ch TICKER [method] [sens] ──────────────────────────────────
    ticker = args[0].upper()
    method = SR_METHOD_DONCHIAN
    sens   = float(SR_SENSITIVITY)

    if ticker not in _load_whitelist():
        await update.message.reply_text(
            f"⚠️ <b>{ticker}</b> tidak tersedia.\n"
            f"Hanya saham S&P 500 yang didukung.",
            parse_mode=ParseMode.HTML,
        )
        return

    if len(args) >= 2:
        mk = args[1].lower()
        if mk not in VALID_METHODS:
            await update.message.reply_text(
                f"⚠️ Method tidak dikenal: <b>{args[1]}</b>\n"
                f"Pilihan: donchian(d) | pivots(p) | csid(c) | zigzag(z)",
                parse_mode=ParseMode.HTML,
            )
            return
        method = VALID_METHODS[mk]

    if len(args) >= 3:
        try:
            sens = float(args[2])
        except ValueError:
            await update.message.reply_text("⚠️ Sensitivity harus berupa angka.")
            return

    await _send_chart_format_picker(update, ticker, method, sens)
    
async def cmd_forex_chart(update, context):
    args = context.args

    if not args:
        await update.message.reply_text(
            "⚠️ Format:\n"
            "<code>/cf PAIR [method] [sensitivity]</code>\n"
            "<code>/cf ts PAIR</code>       — Chart Total Score vs Price\n"
            "<code>/cf ts bt PAIR</code>    — Backtest model untuk pair\n"
            "<code>/cf ts bt ml PAIR</code> — ML adjust weight + backtest\n\n"
            "Method S&R: donchian(d) | pivots(p) | csid(c) | zigzag(z)\n\n"
            "Format output: <b>PNG</b> (gambar) atau <b>HTML</b> (interaktif)",
            parse_mode=ParseMode.HTML,
        )
        return

    # ── /cf ts ... ────────────────────────────────────────────────────────────
    if args[0].lower() == "ts":

        # /cf ts bt ml PAIR
        if len(args) >= 4 and args[1].lower() == "bt" and args[2].lower() == "ml":
            pair = args[3].upper().removeprefix("C:")
            await update.message.reply_text(
                f"🤖 <b>Menjalankan ML untuk {pair}...</b>\n"
                f"⏳ Training XGBoost, mohon tunggu...",
                parse_mode=ParseMode.HTML,
            )
            try:
                from forex_backtest import run_forex_ml
                msgs = run_forex_ml(pair)
                for msg in msgs:
                    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
                    await asyncio.sleep(0.5)
            except Exception as e:
                await update.message.reply_text(f"❌ Error ML forex: {e}", parse_mode=ParseMode.HTML)
            return

        # /cf ts bt PAIR
        if len(args) >= 3 and args[1].lower() == "bt":
            pair = args[2].upper().removeprefix("C:")
            await update.message.reply_text(
                f"⏳ <b>Menjalankan backtest untuk {pair}...</b>",
                parse_mode=ParseMode.HTML,
            )
            try:
                from forex_backtest import run_forex_backtest
                msg = run_forex_backtest(pair)
                await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
            except Exception as e:
                await update.message.reply_text(f"❌ Error backtest forex: {e}", parse_mode=ParseMode.HTML)
            return

        # /cf ts PAIR (chart score history)
        if len(args) < 2:
            await update.message.reply_text(
                "⚠️ Format: <code>/cf ts PAIR</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        pair = args[1].upper().removeprefix("C:")
        await _send_forex_chart_picker(update, pair, SR_METHOD_DONCHIAN, float(SR_SENSITIVITY), is_ts=True)
        return

    # ── Default: /cf PAIR [method] [sens] ────────────────────────────────────
    pair   = args[0].upper().removeprefix("C:")
    method = SR_METHOD_DONCHIAN
    sens   = float(SR_SENSITIVITY)

    if len(args) >= 2:
        mk = args[1].lower()
        if mk not in VALID_METHODS:
            await update.message.reply_text(
                f"⚠️ Method tidak dikenal: <b>{args[1]}</b>\n"
                f"Pilihan: donchian(d) | pivots(p) | csid(c) | zigzag(z)",
                parse_mode=ParseMode.HTML,
            )
            return
        method = VALID_METHODS[mk]

    if len(args) >= 3:
        try:
            sens = float(args[2])
        except ValueError:
            await update.message.reply_text("⚠️ Sensitivity harus berupa angka.")
            return

    await _send_forex_chart_picker(update, pair, method, sens)
    
async def _send_forex_chart_picker(
    update,
    pair: str,
    method: str,
    sens: float,
    is_ts: bool = False,
):
    key = f"cfchart_{pair}_{method}_{sens}_{is_ts}_{int(datetime.now().timestamp())}"
    _pending_charts[key] = {
        "ticker": pair,   # pakai key "ticker" agar _deliver_forex_chart seragam
        "method": method,
        "sens":   sens,
        "is_ts":  is_ts,
        "is_forex": True,
    }
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🖼 PNG  (gambar)",     callback_data=f"{key}|png"),
            InlineKeyboardButton("🌐 HTML (interaktif)", callback_data=f"{key}|html"),
        ]
    ])
    label = f"{pair} — Total Score" if is_ts else f"{pair} — {method} S&R"
    await update.message.reply_text(
        f"📊 <b>{label}</b>\nPilih format chart:",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )

async def _deliver_forex_chart(query, params: dict, fmt: str):
    pair   = params["ticker"]
    method = params["method"]
    sens   = params["sens"]
    is_ts  = params["is_ts"]

    await query.edit_message_text(
        f"⏳ Membuat chart <b>{pair}</b> format <b>{fmt.upper()}</b>...",
        parse_mode=ParseMode.HTML,
    )

    try:
        if is_ts:
            # Gunakan forex score history
            from forex_score_history import load_forex_score_history
            from chart_ts import generate_ts_chart
            from chart_ts_html import generate_ts_html_chart

            # Patch: chart_ts dan chart_ts_html baca dari load_score_history,
            # tapi untuk forex kita override dengan data dari forex DB.
            # Solusi: buat wrapper yang inject history forex ke fungsi chart.
            history = load_forex_score_history(pair)
            if not history:
                await query.edit_message_text(
                    f"❌ Tidak ada score history untuk <b>{pair}</b>. Jalankan /9 terlebih dahulu.",
                    parse_mode=ParseMode.HTML,
                )
                return

            if fmt == "html":
                buf   = _generate_forex_ts_html(pair, history)
                fname = f"{pair}_score_chart.html"
                await query.message.reply_document(
                    document=buf,
                    filename=fname,
                    caption=(
                        f"🌐 <b>{pair}</b> — Total Score Chart (Interaktif)\n"
                        f"<i>Buka file HTML di browser</i>"
                    ),
                    parse_mode=ParseMode.HTML,
                )
            else:
                buf = _generate_forex_ts_png(pair, history)
                await query.message.reply_photo(photo=buf, caption=f"📊 {pair} — Total Score History")

        else:
            # S&R chart biasa — load df dari cache forex
            df = forex_cache_load(pair)
            if df is None:
                from forex_api import fetch_forex_ohlcv
                df = fetch_forex_ohlcv(pair)
            if df is None or len(df) < 35:
                await query.edit_message_text(
                    f"❌ Data tidak tersedia untuk <b>{pair}</b>.",
                    parse_mode=ParseMode.HTML,
                )
                return

            if fmt == "html":
                buf   = generate_html_chart(pair, df, method=method, sens=sens)
                fname = f"{pair}_{method}_chart.html"
                await query.message.reply_document(
                    document=buf,
                    filename=fname,
                    caption=(
                        f"🌐 <b>{pair}</b> — Interactive Chart\n"
                        f"Method: {method} | Sensitivity: {sens}\n"
                        f"<i>Buka file HTML di browser</i>"
                    ),
                    parse_mode=ParseMode.HTML,
                )
            else:
                buf = generate_chart(pair, df, method=method, sens=sens)
                await query.message.reply_photo(photo=buf, caption=f"📈 {pair} — {method} S&R Chart")

        await query.delete_message()

    except ValueError as e:
        await query.edit_message_text(f"❌ {e}")
    except Exception as e:
        logger.error(f"Gagal generate forex chart {pair}: {e}")
        await query.edit_message_text(f"❌ Gagal membuat chart: {e}")

def _generate_forex_ts_png(pair: str, history: list) -> "io.BytesIO":
    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import matplotlib.patches as mpatches
    from matplotlib.patches import Rectangle
    import pandas as pd, numpy as np

    BG     = "#161616"; PANEL = "#1e1e1e"; GRID = "#2e2e2e"
    TEXT   = "#DBDBDB"; BULL  = "#089981"; BEAR = "#f23645"
    SC     = "#f23645"; ZC   = "#555555"

    df = pd.DataFrame(history)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True,
                                    gridspec_kw={"height_ratios": [3, 1.5]},
                                    facecolor=BG)
    for ax in [ax1, ax2]:
        ax.set_facecolor(PANEL)
        ax.tick_params(colors=TEXT, labelsize=8)
        ax.grid(True, color=GRID, linewidth=0.4, alpha=0.6)
        for spine in ax.spines.values():
            spine.set_color(GRID)

    # Panel atas — candlestick price
    x = mdates.date2num(df["date"].dt.to_pydatetime())
    for xi, o, h, l, c in zip(x, df["open"], df["high"], df["low"], df["price"]):
        col  = BULL if c >= o else BEAR
        bh   = abs(c - o) or (h - l) * 0.01
        ax1.add_patch(Rectangle((xi - 0.3, min(o, c)), 0.6, bh, color=col, zorder=3))
        ax1.plot([xi, xi], [l, h], color=col, linewidth=0.8, zorder=2)
    ax1.set_xlim(x[0] - 1, x[-1] + 1)
    ax1.set_ylim(df["low"].min() * 0.998, df["high"].max() * 1.002)
    ax1.set_ylabel("Price", color=TEXT, fontsize=9)
    ax1.set_title(f"{pair} — Total Score History", color=TEXT, fontsize=11, pad=8)

    # Panel bawah — total score line
    scores = df["total"].values
    colors = [BULL if s >= 0 else BEAR for s in scores]
    for i in range(len(x) - 1):
        ax2.plot([x[i], x[i+1]], [scores[i], scores[i+1]], color=colors[i], linewidth=1.2)
    ax2.axhline(0, color=ZC, linewidth=0.8, linestyle="--")
    ax2.fill_between(x, scores, 0,
                     where=[s >= 0 for s in scores], alpha=0.15, color=BULL)
    ax2.fill_between(x, scores, 0,
                     where=[s < 0 for s in scores], alpha=0.15, color=BEAR)
    ax2.set_ylabel("Total Score", color=TEXT, fontsize=9)

    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    ax2.xaxis.set_major_locator(mdates.MonthLocator())
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=30, ha="right")

    plt.tight_layout(pad=1.2)
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    buf.seek(0)
    return buf

def _generate_forex_ts_html(pair: str, history: list) -> "io.BytesIO":
    import io, json
    import pandas as pd

    df = pd.DataFrame(history)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    labels  = df["date"].dt.strftime("%Y-%m-%d").tolist()
    prices  = df["price"].round(6).tolist()
    scores  = df["total"].round(2).tolist()
    bg_col  = ["rgba(8,153,129,0.6)" if s >= 0 else "rgba(242,54,69,0.6)" for s in scores]

    labels_j  = json.dumps(labels)
    prices_j  = json.dumps(prices)
    scores_j  = json.dumps(scores)
    bg_col_j  = json.dumps(bg_col)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{pair} Score Chart</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  body {{ background:#161616; color:#dbdbdb; font-family:sans-serif; margin:0; padding:16px; }}
  h2   {{ text-align:center; letter-spacing:2px; }}
  .wrap {{ max-width:1100px; margin:auto; }}
  canvas {{ background:#1e1e1e; border-radius:6px; margin-bottom:20px; }}
</style>
</head>
<body>
<div class="wrap">
  <h2>💱 {pair} — Total Score History</h2>
  <canvas id="price"  height="80"></canvas>
  <canvas id="score"  height="50"></canvas>
</div>
<script>
const labels = {labels_j};
const prices = {prices_j};
const scores = {scores_j};
const bgcol  = {bg_col_j};

new Chart(document.getElementById("price"), {{
  type: "line",
  data: {{
    labels,
    datasets: [{{ label:"Price", data:prices,
      borderColor:"#089981", borderWidth:1.5, pointRadius:0,
      fill:false, tension:0.1 }}]
  }},
  options: {{
    plugins:{{ legend:{{ labels:{{ color:"#dbdbdb" }} }} }},
    scales:{{
      x:{{ ticks:{{ color:"#aaa", maxTicksLimit:12 }}, grid:{{ color:"#2e2e2e" }} }},
      y:{{ ticks:{{ color:"#aaa" }},              grid:{{ color:"#2e2e2e" }} }}
    }}
  }}
}});

new Chart(document.getElementById("score"), {{
  type: "bar",
  data: {{
    labels,
    datasets: [{{ label:"Total Score", data:scores,
      backgroundColor:bgcol, borderRadius:2 }}]
  }},
  options: {{
    plugins:{{ legend:{{ labels:{{ color:"#dbdbdb" }} }} }},
    scales:{{
      x:{{ ticks:{{ color:"#aaa", maxTicksLimit:12 }}, grid:{{ color:"#2e2e2e" }} }},
      y:{{ ticks:{{ color:"#aaa" }},              grid:{{ color:"#2e2e2e" }} }}
    }}
  }}
}});
</script>
</body>
</html>"""

    buf = io.BytesIO(html.encode())
    buf.seek(0)
    return buf

  
async def cmd_vtf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Scanning Very Tight forex...", parse_mode=ParseMode.HTML)
    try:
        vt_list, _ = scan_forex_tight()
        await update.message.reply_text(format_forex_vt(vt_list), parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_tf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Scanning Tight forex...", parse_mode=ParseMode.HTML)
    try:
        _, t_list = scan_forex_tight()
        await update.message.reply_text(format_forex_t(t_list), parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_wccf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Mengambil data WCC forex...", parse_mode=ParseMode.HTML)
    pairs = forex_list_cached()
    if not pairs:
        await update.message.reply_text(
            "❌ Cache forex kosong. Jalankan /9 terlebih dahulu."
        )
        return
    rows = []
    for pair in pairs:
        df = forex_cache_load(pair)
        if df is None or len(df) < 8:
            continue
        detail = get_wcc_detail(df)
        price  = float(df["close"].iloc[-1])
        prev   = float(df["close"].iloc[-2]) if len(df) > 1 else price
        change = ((price - prev) / prev * 100) if prev != 0 else 0.0
        rows.append({
            "ticker":        pair,
            "price":         round(price, 6),
            "change":        round(change, 4),
            "wcc":           detail["score"],
            "direction":     detail["direction"],
            "open_to_close": detail["open_to_close"],
            "wick_to_body":  detail["wick_to_body"],
            "ratio":         detail["ratio"],
            "total":         0.0,
        })
    if not rows:
        await update.message.reply_text("❌ Tidak ada data WCC forex yang cukup.")
        return
    rows.sort(key=lambda x: x["wcc"], reverse=True)
    for msg in fmt_wcc_table(rows):
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        await asyncio.sleep(0.3)


async def cmd_scorf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Anda tidak memiliki akses.")
        return
    args = context.args
    if not args:
        await update.message.reply_text(
            "Penggunaan: <code>/scorf AUDUSD</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    pair = args[0].upper().removeprefix("C:")
    await update.message.reply_text(
        f"⏳ Mengambil data <b>{pair}</b>...", parse_mode=ParseMode.HTML
    )
    df = forex_cache_load(pair)
    if df is None:
        from forex_api import fetch_forex_ohlcv
        df = fetch_forex_ohlcv(pair)
    if df is None or len(df) < 35:
        await update.message.reply_text(f"❌ Data tidak cukup untuk {pair}")
        return
    vt_list, t_list = scan_forex_tight()
    vt_set = {e["pair"] for e in vt_list}
    t_set  = {e["pair"] for e in t_list}
    ts     = score_forex_tight(pair, vt_set, t_set)
    result = calculate_forex_scores(pair, df, tight_score=ts)
    wi     = get_forex_weights_info(pair)
    result["_weight_info"] = wi
    await update.message.reply_text(fmt_forex_detail(result), parse_mode=ParseMode.HTML)

async def cmd_help(update, context):

    text = (
        "📖 <b>Daftar Command</b>\n"
        "─────────────────────────\n\n"

        "⚙️ <b>Scoring & Data</b>\n"
        "<code>/scor</code>  — Lihat skor semua saham hari ini\n"
        "<code>/scor TICKER</code>  — Hitung skor end of day 1 saham\n\n"

        "📊 <b>Chart</b>\n"
        "<code>/ch TICKER</code>  — Chart S&R (Donchian default)\n"
        "<code>/ch TICKER [method] [sens]</code>  — S&R dengan method & sensitivity\n"
        "   Method: <code>d</code>=Donchian  <code>p</code>=Pivots  <code>c</code>=CSID  <code>z</code>=ZigZag\n\n"

        "📈 <b>Total Score Chart & Analisis</b>\n"
        "<code>/ch ts TICKER</code>  — Chart Total Score vs Price\n"
        "<code>/ch ts bt TICKER</code>  — Backtest model (weight saat ini)\n"

        "🔍 <b>Scan</b>\n"
        "<code>/vtus</code>  — List saham Very Tight\n"
        "<code>/tus</code>  — List saham Tight \n"
        "<code>/vfa</code>  — Tabel Volume Frequency Analysis semua saham\n"
        "<code>/wcc</code>  — Tabel Wick Candle Change semua saham\n\n"

    )

    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# ── Entry point ───────────────────────────────────────────────────────────────

def main():
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
    app.add_handler(CommandHandler("cf", cmd_forex_chart))
    app.add_handler(CommandHandler("wcc",   cmd_wcc))
    app.add_handler(CommandHandler("ch",    cmd_chart))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("vtf",   cmd_vtf))
    app.add_handler(CommandHandler("tf",    cmd_tf))
    app.add_handler(CommandHandler("wccf",  cmd_wccf))
    app.add_handler(CommandHandler("scorf", cmd_scorf))
    # Callback untuk pilihan format chart
    app.add_handler(CallbackQueryHandler(callback_chart_format, pattern=r"^(?:chart_|cfchart_).*\|(?:png|html)$"))


    logger.info("Bot started. Listening...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
