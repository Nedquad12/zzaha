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
from wti import calculate_wti, fmt_wti, fmt_wti_error

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

async def cmd_wti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "📊 <b>Weight To Index (WTI)</b>\n\n"
            "Penggunaan: <code>/wti TICKER</code>\n\n"
            "Contoh: <code>/wti NVDA</code>\n\n"
            "WTI mengukur seberapa sering saham bergerak searah SPY (90 hari):\n"
            "  🟢 <b>SPY Up</b>   — SPY naik >0.1%, apakah saham naik >ATR14÷3?\n"
            "  🔴 <b>SPY Down</b> — SPY turun >0.1%, apakah saham turun >ATR14÷3?\n"
            "  ⚪ <b>Netral</b>   — di luar kedua kondisi di atas\n\n"
            "<i>Data diambil dari /us/500/ (hasil /9 terakhir)</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    ticker = args[0].upper().strip()
    await update.message.reply_text(
        f"⏳ Menghitung WTI untuk <b>{ticker}</b> vs SPY...",
        parse_mode=ParseMode.HTML,
    )

    result = calculate_wti(ticker)

    if result is None:
        spy_exists = os.path.exists("/home/ec2-user/us/500/SPY.json")
        tkr_exists = os.path.exists(f"/home/ec2-user/us/500/{ticker}.json")

        if not spy_exists:
            reason = "❗ Data SPY tidak ditemukan di <code>/us/500/SPY.json</code>"
        elif not tkr_exists:
            reason = f"❗ Data <b>{ticker}</b> tidak ditemukan di <code>/us/500/{ticker}.json</code>"
        else:
            reason = "❗ Data tidak cukup untuk perhitungan (kurang dari 2 bar bersama)"

        await update.message.reply_text(
            fmt_wti_error(ticker, reason),
            parse_mode=ParseMode.HTML,
        )
        return

    await update.message.reply_text(
        fmt_wti(result),
        parse_mode=ParseMode.HTML,
    )

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
    app.add_handler(CommandHandler("wcc",   cmd_wcc))
    app.add_handler(CommandHandler("ch",    cmd_chart))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("wti", cmd_wti))
    # Callback untuk pilihan format chart
    app.add_handler(CallbackQueryHandler(callback_chart_format, pattern=r"^(?:chart_|cfchart_).*\|(?:png|html)$"))


    logger.info("Bot started. Listening...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
