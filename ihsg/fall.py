"""
fall.py — Handler /fall

Analisis Net Asing per timeframe (1D, 1W, 1M, 1Q).
Cache dibangun otomatis saat startup dan saat admin menjalankan reload.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

CACHE_DIR = "/home/ec2-user/database/cache"

# ── Cache di RAM ───────────────────────────────────────────────────────────────
NET_ASING_CACHE: Dict[str, Dict[str, float]] = {
    '1d': {},
    '1w': {},
    '1m': {},
    '1q': {},
}

LAST_RELOAD_TIME: datetime | None = None


# ── Helpers ────────────────────────────────────────────────────────────────────

def parse_date_from_filename(filename: str) -> datetime | None:
    """Parse tanggal dari nama file format ddmmyy.txt → datetime."""
    try:
        date_str = filename.replace('.txt', '')
        day   = int(date_str[0:2])
        month = int(date_str[2:4])
        year  = int('20' + date_str[4:6])
        return datetime(year, month, day)
    except Exception as e:
        logger.warning(f"[FALL] Error parsing date from {filename}: {e}")
        return None


def get_cache_files_in_range(start_date: datetime, end_date: datetime) -> List[str]:
    """Ambil semua file .txt dalam rentang tanggal, sorted ascending."""
    if not os.path.exists(CACHE_DIR):
        logger.warning(f"[FALL] Cache directory tidak ditemukan: {CACHE_DIR}")
        return []

    files = []
    for filename in os.listdir(CACHE_DIR):
        if not filename.endswith('.txt'):
            continue
        file_date = parse_date_from_filename(filename)
        if file_date and start_date.date() <= file_date.date() <= end_date.date():
            files.append(os.path.join(CACHE_DIR, filename))

    logger.info(f"[FALL] Found {len(files)} files in range "
                f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    return sorted(files)


def load_cache_file(file_path: str) -> Dict | None:
    """Load JSON dari file cache."""
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[FALL] Error loading {file_path}: {e}")
        return None


def calculate_net_asing(data: Dict) -> Dict[str, float]:
    """Hitung net asing per kode saham: net = foreign_buy - foreign_sell."""
    net_dict: Dict[str, float] = {}
    try:
        kode_list = data.get('kode_saham', [])
        buy_list  = data.get('foreign_buy', [])
        sell_list = data.get('foreign_sell', [])

        for i in range(1, len(kode_list)):   # skip header index 0
            kode = kode_list[i]
            if not kode or not isinstance(kode, str):
                continue
            try:
                buy  = float(buy_list[i])  if i < len(buy_list)  else 0.0
                sell = float(sell_list[i]) if i < len(sell_list) else 0.0
                net_dict[kode] = buy - sell
            except (ValueError, TypeError):
                continue
    except Exception as e:
        logger.warning(f"[FALL] Error calculating net: {e}")
    return net_dict


def aggregate_net_asing(file_paths: List[str]) -> Dict[str, float]:
    """Akumulasi net asing dari beberapa file."""
    total_net: Dict[str, float] = {}
    for fp in file_paths:
        data = load_cache_file(fp)
        if not data:
            continue
        for kode, net in calculate_net_asing(data).items():
            total_net[kode] = total_net.get(kode, 0.0) + net
    return total_net


def format_number(num: float) -> str:
    """Format angka ke singkatan B/M/K."""
    abs_num = abs(num)
    if abs_num >= 1_000_000_000:
        return f"{num/1_000_000_000:.2f}B"
    if abs_num >= 1_000_000:
        return f"{num/1_000_000:.2f}M"
    if abs_num >= 1_000:
        return f"{num/1_000:.2f}K"
    return f"{num:.0f}"


def get_top_bottom_net(timeframe: str) -> Tuple[List[Tuple], List[Tuple]]:
    """Return (top_20_akumulasi, top_20_dibuang) untuk timeframe tertentu."""
    net_dict = NET_ASING_CACHE.get(timeframe, {})
    if not net_dict:
        return [], []
    sorted_desc = sorted(net_dict.items(), key=lambda x: x[1], reverse=True)
    sorted_asc  = sorted(net_dict.items(), key=lambda x: x[1])
    return sorted_desc[:20], sorted_asc[:20]


# ── Build cache (dipanggil dari main.py) ──────────────────────────────────────

def build_fall_cache() -> str:
    """
    Bangun NET_ASING_CACHE untuk semua timeframe.
    Dipanggil saat startup dan saat admin menjalankan reload.
    Return string ringkasan untuk log.
    """
    global LAST_RELOAD_TIME

    today       = datetime.now()
    week_ago    = today - timedelta(days=7)
    month_ago   = today - timedelta(days=30)
    quarter_ago = today - timedelta(days=90)

    NET_ASING_CACHE['1d'] = aggregate_net_asing(get_cache_files_in_range(today,       today))
    NET_ASING_CACHE['1w'] = aggregate_net_asing(get_cache_files_in_range(week_ago,    today))
    NET_ASING_CACHE['1m'] = aggregate_net_asing(get_cache_files_in_range(month_ago,   today))
    NET_ASING_CACHE['1q'] = aggregate_net_asing(get_cache_files_in_range(quarter_ago, today))

    LAST_RELOAD_TIME = datetime.now()

    summary = (
        f"📡 Fall cache: "
        f"1D={len(NET_ASING_CACHE['1d'])} "
        f"1W={len(NET_ASING_CACHE['1w'])} "
        f"1M={len(NET_ASING_CACHE['1m'])} "
        f"1Q={len(NET_ASING_CACHE['1q'])} saham"
    )
    logger.info(summary)
    return summary


# ── Telegram Handlers ──────────────────────────────────────────────────────────

async def cmd_fall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/fall — Tampilkan pilihan timeframe net asing."""
    from admin.auth import is_authorized_user, is_vip_user
    uid = update.effective_user.id
    if not (is_authorized_user(uid) or is_vip_user(uid)):
        await update.message.reply_text("⛔ Kamu tidak punya akses ke bot ini.")
        return

    keyboard = [
        [
            InlineKeyboardButton("1D (Hari Ini)", callback_data="fall_1d"),
            InlineKeyboardButton("1W (Minggu)",   callback_data="fall_1w"),
        ],
        [
            InlineKeyboardButton("1M (Bulan)",    callback_data="fall_1m"),
            InlineKeyboardButton("1Q (Quarter)",  callback_data="fall_1q"),
        ],
    ]

    reload_info = (
        f"\n⏰ Cache: {LAST_RELOAD_TIME.strftime('%d/%m/%Y %H:%M')}"
        if LAST_RELOAD_TIME
        else "\n⚠️ Cache belum tersedia."
    )

    await update.message.reply_text(
        f"📊 *Analisis Net Asing*\n\n"
        f"Pilih timeframe:\n"
        f"• Top 20 Akumulasi (Terbesar)\n"
        f"• Top 20 Dibuang (Terkecil){reload_info}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
    )


async def fall_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback tombol timeframe."""
    query = update.callback_query
    await query.answer()

    timeframe = query.data.replace('fall_', '')

    if not NET_ASING_CACHE.get(timeframe):
        await query.edit_message_text("⚠️ Cache belum tersedia.")
        return

    top_20, bottom_20 = get_top_bottom_net(timeframe)

    if not top_20 and not bottom_20:
        await query.edit_message_text(
            f"❌ Tidak ada data untuk timeframe {timeframe.upper()}"
        )
        return

    tf_display = {
        '1d': '1D (Hari Ini)',
        '1w': '1W (Minggu)',
        '1m': '1M (Bulan)',
        '1q': '1Q (Quarter)',
    }

    msg = f"📊 *Net Asing — {tf_display.get(timeframe, timeframe.upper())}*\n\n"

    msg += "🟢 *TOP 20 AKUMULASI (Lembar saham)*\n"
    msg += "```\n"
    msg += f"{'No':<3} {'Kode':<6} {'Net Asing':>12}\n"
    msg += "─" * 24 + "\n"
    for idx, (kode, net) in enumerate(top_20, 1):
        msg += f"{idx:<3} {kode:<6} {format_number(net):>12}\n"
    msg += "```\n\n"

    msg += "🔴 *TOP 20 DIBUANG (Lembar Saham*\n"
    msg += "```\n"
    msg += f"{'No':<3} {'Kode':<6} {'Net Asing':>12}\n"
    msg += "─" * 24 + "\n"
    for idx, (kode, net) in enumerate(bottom_20, 1):
        msg += f"{idx:<3} {kode:<6} {format_number(net):>12}\n"
    msg += "```"

    keyboard = [[InlineKeyboardButton("« Kembali", callback_data="fall_back")]]
    await query.edit_message_text(
        msg,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
    )


async def fall_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle tombol « Kembali ke menu timeframe."""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton("1D (Hari Ini)", callback_data="fall_1d"),
            InlineKeyboardButton("1W (Minggu)",   callback_data="fall_1w"),
        ],
        [
            InlineKeyboardButton("1M (Bulan)",    callback_data="fall_1m"),
            InlineKeyboardButton("1Q (Quarter)",  callback_data="fall_1q"),
        ],
    ]

    reload_info = (
        f"\n⏰ Cache: {LAST_RELOAD_TIME.strftime('%d/%m/%Y %H:%M')}"
        if LAST_RELOAD_TIME
        else "\n⚠️ Cache belum tersedia."
    )

    await query.edit_message_text(
        f"📊 *Analisis Net Asing*\n\n"
        f"Pilih timeframe:\n"
        f"• Top 20 Akumulasi (Terbesar)\n"
        f"• Top 20 Dibuang (Terkecil){reload_info}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
    )


# ── Registration ───────────────────────────────────────────────────────────────

def register_fall_handlers(app):
    """Daftarkan handler /fall ke Application."""
    app.add_handler(CommandHandler("fall", cmd_fall))
    app.add_handler(CallbackQueryHandler(fall_callback,      pattern=r"^fall_(1d|1w|1m|1q)$"))
    app.add_handler(CallbackQueryHandler(fall_back_callback, pattern=r"^fall_back$"))
