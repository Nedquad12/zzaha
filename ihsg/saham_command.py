"""
saham_command.py — Handler /saham TICKER

Analisis lengkap saham dalam satu perintah:
  1. Volume Analysis
  2. Foreign Flow Analysis
  3. Moving Average Analysis
  4. Foreign Flow Summary (1H/5H/1B/3B)
  5. Margin Trading Status
  6. Margin Chart
  7. Holdings (Top Shareholders)
  8. Sector Information
  9. Ringkasan akhir

Hanya bisa diakses oleh user VIP atau whitelist.
"""

import os
import sys
import glob
import json
import time
import logging
import asyncio
import gc
from datetime import datetime

import pandas as pd
import pytz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from telegram.constants import ParseMode

from admin.auth import is_authorized_user, is_vip_user
from excel_reader import get_excel_files, get_stock_sector_data
from indicators.loader import build_stock_df
from indicators import (
    score_vsa, score_fsa, score_vfa,
    score_wcc, score_rsi, score_macd, score_ma,
    calculate_ip, score_ip, score_srst,
    score_tight, score_fbs,
)
from stock_holdings import holdings
from margin import viewer as margin_viewer

# ── Konstanta ──────────────────────────────────────────────────────────────────
WIB         = pytz.timezone('Asia/Jakarta')
CACHE_DIR   = "/home/ec2-user/database/cache"
WL_DIR      = "/home/ec2-user/database/wl"
MARGIN_DIR  = "/home/ec2-user/database/margin"
JSON_DIR    = "/home/ec2-user/database/json"

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Auth guard
# ══════════════════════════════════════════════════════════════════════════════

def _is_allowed(user_id: int) -> bool:
    return is_authorized_user(user_id) or is_vip_user(user_id)


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _fmt_rupiah(value: float) -> str:
    if value >= 1e12:
        return f"{value / 1e12:.2f}T"
    if value >= 1e9:
        return f"{value / 1e9:.2f}B"
    if value >= 1e6:
        return f"{value / 1e6:.2f}M"
    return f"{value:,.0f}"


def _load_cache_files(limit: int = 60) -> list[tuple[str, datetime]]:
    """Return sorted (path, date) list from CACHE_DIR, newest first."""
    result = []
    for fname in os.listdir(CACHE_DIR):
        if not fname.endswith('.txt'):
            continue
        date_str = fname.replace('.txt', '')
        try:
            d = datetime.strptime(date_str, '%d%m%y')
            result.append((os.path.join(CACHE_DIR, fname), d))
        except ValueError:
            continue
    result.sort(key=lambda x: x[1], reverse=True)
    return result[:limit]


# ══════════════════════════════════════════════════════════════════════════════
#  1. Volume Analysis
# ══════════════════════════════════════════════════════════════════════════════

def analyze_stock_volume(stock_code: str) -> tuple[dict | None, str | None]:
    try:
        files = _load_cache_files(60)
        if len(files) < 7:
            return None, "Tidak cukup data (minimal 7 file)"

        volume_data = []
        for fpath, date_obj in files:
            try:
                with open(fpath, 'r') as f:
                    data = json.load(f)
                codes  = data.get('kode_saham', [])[1:]
                vols   = data.get('volume',     [])[1:]
                prices = data.get('penutupan',  [])[1:]
                if not codes:
                    continue
                idx = codes.index(stock_code)
                vol   = vols[idx]   if isinstance(vols[idx],   (int, float)) else 0
                price = prices[idx] if isinstance(prices[idx], (int, float)) else 0
                volume_data.append({'date': date_obj, 'volume': vol, 'price': price})
            except (ValueError, KeyError, IndexError):
                continue
            except Exception as e:
                logger.warning(f"[Volume] {fpath}: {e}")

        if len(volume_data) < 7:
            return None, f"Tidak cukup data untuk {stock_code} ({len(volume_data)} hari)"

        vols = [d['volume'] for d in volume_data]
        v0   = vols[0]
        a7   = sum(vols[:7])  / 7
        a30  = sum(vols[:min(30, len(vols))]) / min(30, len(vols))
        a60  = sum(vols[:min(60, len(vols))]) / min(60, len(vols))

        s_today  = v0  / a7  if a7  > 0 else 0
        s_7v30   = a7  / a30 if a30 > 0 else 0
        s_7v60   = a7  / a60 if a60 > 0 else 0
        score    = (s_today + s_7v30 + s_7v60) / 3

        return {
            'stock_code':    stock_code,
            'vol_today':     v0,
            'avg_7_days':    a7,
            'avg_30_days':   a30,
            'avg_60_days':   a60,
            'spike_today':   s_today,
            'spike_7vs30':   s_7v30,
            'spike_7vs60':   s_7v60,
            'vol_spike':     score,
            'current_price': volume_data[0]['price'],
            'data_points':   len(volume_data),
            'is_trending':   a7 > a60 and a7 > a30 and v0 > a7,
        }, None

    except Exception as e:
        logger.error(f"analyze_stock_volume: {e}")
        return None, "Error saat menganalisis volume"


# ══════════════════════════════════════════════════════════════════════════════
#  2. Foreign Flow Analysis
# ══════════════════════════════════════════════════════════════════════════════

def analyze_stock_foreign(stock_code: str) -> tuple[dict | None, str | None]:
    try:
        files = _load_cache_files(60)
        if len(files) < 2:
            return None, "Tidak cukup data foreign"

        foreign_data = []
        for fpath, date_obj in files:
            try:
                with open(fpath, 'r') as f:
                    data = json.load(f)
                codes = data.get('kode_saham',   [])[1:]
                buys  = data.get('foreign_buy',  [])[1:]
                sells = data.get('foreign_sell', [])[1:]
                if not codes:
                    continue
                idx  = codes.index(stock_code)
                buy  = buys[idx]  if isinstance(buys[idx],  (int, float)) else 0
                sell = sells[idx] if isinstance(sells[idx], (int, float)) else 0
                foreign_data.append({'date': date_obj, 'foreign_buy': buy,
                                     'foreign_sell': sell, 'foreign_net': buy - sell})
            except (ValueError, KeyError, IndexError):
                continue
            except Exception as e:
                logger.warning(f"[Foreign] {fpath}: {e}")

        if len(foreign_data) < 2:
            return None, f"Tidak cukup data foreign untuk {stock_code}"

        nets        = [d['foreign_net'] for d in foreign_data]
        latest_net  = nets[0]
        avg_net     = sum(nets) / len(nets)
        avg7        = sum(nets[:min(7,  len(nets))]) / min(7,  len(nets))
        avg30       = sum(nets[:min(30, len(nets))]) / min(30, len(nets))

        if avg_net != 0:
            spike = latest_net / avg_net
        elif latest_net > 0:
            spike = float('inf')
        elif latest_net < 0:
            spike = float('-inf')
        else:
            spike = 0.0

        return {
            'stock_code':      stock_code,
            'latest_net':      latest_net,
            'latest_buy':      foreign_data[0]['foreign_buy'],
            'latest_sell':     foreign_data[0]['foreign_sell'],
            'avg_net':         avg_net,
            'avg_7_days':      avg7,
            'avg_30_days':     avg30,
            'spike_ratio':     spike,
            'data_points':     len(foreign_data),
            'is_net_positive': latest_net > 0,
            'trend_7vs30':     avg7 > avg30,
        }, None

    except Exception as e:
        logger.error(f"analyze_stock_foreign: {e}")
        return None, "Error saat menganalisis foreign flow"


# ══════════════════════════════════════════════════════════════════════════════
#  3. Moving Average Analysis  (pakai indicators/loader + indicators/ma)
# ══════════════════════════════════════════════════════════════════════════════

def get_stock_ma_data(stock_code: str) -> tuple[dict | None, str | None]:
    try:
        df = build_stock_df(stock_code, JSON_DIR, max_days=220)
        if df is None or df.empty:
            return None, f"Data MA untuk {stock_code} tidak tersedia"

        price   = float(df['close'].iloc[-1])
        closes  = df['close']
        periods = [20, 60, 120, 200]
        mas: dict = {}

        for p in periods:
            if len(closes) >= p:
                ma_val  = float(closes.tail(p).mean())
                diff    = (price - ma_val) / ma_val * 100 if ma_val else 0
                mas[p]  = {
                    'value':    round(ma_val, 0),
                    'diff_pct': round(diff, 2),
                    'position': 'ABOVE' if diff > 0 else ('BELOW' if diff < 0 else 'AT'),
                }
            else:
                mas[p] = None

        return {'stock_code': stock_code, 'current_price': price, 'mas': mas}, None

    except Exception as e:
        logger.error(f"get_stock_ma_data: {e}")
        return None, "Error saat menganalisis MA"


# ══════════════════════════════════════════════════════════════════════════════
#  4. Foreign Flow Summary by period
# ══════════════════════════════════════════════════════════════════════════════

def get_foreign_summary_by_days(stock_code: str) -> list | None:
    try:
        files = _load_cache_files(60)
        if len(files) < 2:
            return None

        foreign_data = []
        for fpath, date_obj in files:
            try:
                with open(fpath, 'r') as f:
                    data = json.load(f)
                codes = data.get('kode_saham',   [])[1:]
                buys  = data.get('foreign_buy',  [])[1:]
                sells = data.get('foreign_sell', [])[1:]
                if not codes:
                    continue
                idx  = codes.index(stock_code)
                buy  = buys[idx]  if isinstance(buys[idx],  (int, float)) else 0
                sell = sells[idx] if isinstance(sells[idx], (int, float)) else 0
                foreign_data.append({'date': date_obj, 'buy': buy, 'sell': sell,
                                     'net': buy - sell})
            except (ValueError, KeyError, IndexError):
                continue
            except Exception as e:
                logger.warning(f"[ForeignSummary] {fpath}: {e}")

        if len(foreign_data) < 2:
            return None

        periods = [
            ('1H',  1),
            ('5H',  5),
            ('1B',  22),
            ('3B',  min(60, len(foreign_data))),
        ]

        summary = []
        for label, days in periods:
            n    = min(days, len(foreign_data))
            rows = foreign_data[:n]
            summary.append((
                label,
                sum(r['buy']  for r in rows),
                sum(r['sell'] for r in rows),
                sum(r['net']  for r in rows),
            ))
        return summary

    except Exception as e:
        logger.error(f"get_foreign_summary_by_days: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  5. Margin Data
# ══════════════════════════════════════════════════════════════════════════════

def get_stock_margin_data(stock_code: str) -> tuple[dict | None, str | None]:
    try:
        margin_viewer.load_margin_files()
        if margin_viewer.margin_df is None:
            return None, "Data margin tidak tersedia"

        col = 'Kode Saham' if 'Kode Saham' in margin_viewer.margin_df.columns else None
        if col is None:
            return None, "Format data margin tidak dikenali"

        sub = margin_viewer.margin_df[
            margin_viewer.margin_df[col].str.upper() == stock_code.upper()
        ]
        if sub.empty:
            return None, f"Saham {stock_code} tidak terdaftar dalam margin trading"

        return {'stock_code': stock_code, 'is_marginable': True,
                'margin_data': sub.iloc[0].to_dict()}, None

    except Exception as e:
        logger.error(f"get_stock_margin_data: {e}")
        return None, "Error saat menganalisis data margin"


# ══════════════════════════════════════════════════════════════════════════════
#  7. Holdings (pakai HoldingsManager yang sudah ada)
# ══════════════════════════════════════════════════════════════════════════════

def get_holdings_text(stock_code: str) -> str | None:
    """Return ringkasan top holders sebagai teks Markdown (tanpa gambar)."""
    try:
        df = holdings.df[holdings.df['SHARE_CODE'] == stock_code.upper()].copy()
        if df.empty:
            return None
        df = df.sort_values('PERCENTAGE', ascending=False).head(10)
        lines = [f"```\n🏦 TOP SHAREHOLDERS — {stock_code}\n" + "="*42]
        lines.append(f"{'Investor':<30} {'%':>6}")
        lines.append("-"*42)
        for _, row in df.iterrows():
            name = str(row['INVESTOR_NAME'])[:30]
            lines.append(f"{name:<30} {row['PERCENTAGE']:>6.2f}%")
        lines.append("```")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"get_holdings_text: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  Main command handler
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_saham(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /saham TICKER
    Analisis lengkap: volume, foreign flow, MA, margin, holdings, sector.
    Hanya VIP / whitelist.
    """
    uid = update.effective_user.id
    if not _is_allowed(uid):
        await update.message.reply_text("⛔ Kamu tidak punya akses ke fitur ini.")
        return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text(
            "⚠️ Masukkan kode saham.\nContoh: `/saham BBCA`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    stock_code    = parts[1].upper()
    start_time    = time.time()
    processing_msg = await update.message.reply_text(
        f"🔄 Menganalisis *{stock_code}*… Mohon tunggu…",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        now_wib = datetime.now(WIB)

        # ── Header ────────────────────────────────────────────────────────────
        await update.message.reply_text(
            f"📊 *ANALISIS LENGKAP: {stock_code}*\n"
            f"🕐 {now_wib.strftime('%d/%m/%Y %H:%M')} WIB\n"
            f"{'='*35}",
            parse_mode=ParseMode.MARKDOWN,
        )
        await asyncio.sleep(0.3)

        # ── 1. Volume ─────────────────────────────────────────────────────────
        volume_analysis, vol_error = await asyncio.get_event_loop().run_in_executor(
            None, analyze_stock_volume, stock_code
        )
        if volume_analysis:
            va = volume_analysis
            msg = (
                f"```\n📈 VOLUME ANALYSIS — {stock_code}\n"
                f"{'='*40}\n"
                f"{'Harga Saat Ini':<22}: {va['current_price']:>12,.0f}\n"
                f"{'Volume Hari Ini':<22}: {va['vol_today']:>12,.0f}\n"
                f"{'Rata-rata 7 Hari':<22}: {va['avg_7_days']:>12,.0f}\n"
                f"{'Rata-rata 30 Hari':<22}: {va['avg_30_days']:>12,.0f}\n"
                f"{'Rata-rata 60 Hari':<22}: {va['avg_60_days']:>12,.0f}\n"
                f"{'='*40}\n"
                f"{'Spike Hari Ini':<22}: {va['spike_today']:>12.2f}x\n"
                f"{'Spike 7 vs 30':<22}: {va['spike_7vs30']:>12.2f}x\n"
                f"{'Spike 7 vs 60':<22}: {va['spike_7vs60']:>12.2f}x\n"
                f"{'VSA Score':<22}: {va['vol_spike']:>12.2f}\n"
                f"{'='*40}\n"
                f"{'Data Points':<22}: {va['data_points']:>11} hari\n"
                f"{'Status Trending':<22}: {'✅ YA' if va['is_trending'] else '❌ TIDAK':>12}\n"
                f"```"
            )
            if va['vol_spike'] >= 2.2:
                msg += "\n🚀 *Volume spike tinggi!*"
            elif va['is_trending']:
                msg += "\n📈 *Volume dalam tren naik*"
            else:
                msg += "\n😐 *Volume dalam kondisi normal*"
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(f"❌ Volume: {vol_error}")
        await asyncio.sleep(0.3)

        # ── 2. Foreign Flow ───────────────────────────────────────────────────
        foreign_analysis, foreign_error = await asyncio.get_event_loop().run_in_executor(
            None, analyze_stock_foreign, stock_code
        )
        if foreign_analysis:
            fa = foreign_analysis
            if fa['spike_ratio'] == float('inf'):
                spike_str = "∞+"
            elif fa['spike_ratio'] == float('-inf'):
                spike_str = "∞-"
            else:
                spike_str = f"{fa['spike_ratio']:+.2f}x"

            msg = (
                f"```\n🌍 FOREIGN FLOW ANALYSIS — {stock_code}\n"
                f"{'='*45}\n"
                f"{'Foreign Buy Hari Ini':<24}: {fa['latest_buy']:>+15,.0f}\n"
                f"{'Foreign Sell Hari Ini':<24}: {fa['latest_sell']:>+15,.0f}\n"
                f"{'Net Foreign Hari Ini':<24}: {fa['latest_net']:>+15,.0f}\n"
                f"{'='*45}\n"
                f"{'Rata-rata Net 7 Hari':<24}: {fa['avg_7_days']:>+15,.0f}\n"
                f"{'Rata-rata Net 30 Hari':<24}: {fa['avg_30_days']:>+15,.0f}\n"
                f"{'Rata-rata Net Total':<24}: {fa['avg_net']:>+15,.0f}\n"
                f"{'='*45}\n"
                f"{'Spike Ratio':<24}: {spike_str:>15}\n"
                f"{'Data Points':<24}: {fa['data_points']:>14} hari\n"
                f"{'Tren 7 vs 30 Hari':<24}: {'📈 UP' if fa['trend_7vs30'] else '📉 DOWN':>15}\n"
                f"```"
            )
            if fa['is_net_positive']:
                if abs(fa['spike_ratio']) >= 2.5:
                    msg += "\n🚀 *Foreign buy spike tinggi!*"
                else:
                    msg += "\n💚 *Net foreign buying positif*"
            else:
                msg += "\n🔴 *Net foreign selling*"
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(f"❌ Foreign Flow: {foreign_error}")
        await asyncio.sleep(0.3)

        # ── 3. Moving Average ─────────────────────────────────────────────────
        ma_analysis, ma_error = await asyncio.get_event_loop().run_in_executor(
            None, get_stock_ma_data, stock_code
        )
        if ma_analysis:
            msg = (
                f"```\n📊 MOVING AVERAGE — {stock_code}\n"
                f"{'='*50}\n"
                f"Harga Saat Ini: {ma_analysis['current_price']:,.0f}\n"
                f"{'='*50}\n"
                f"{'MA':<6} {'Value':<10} {'Diff %':<10} {'Position'}\n"
                f"{'-'*50}\n"
            )
            for p in [20, 60, 120, 200]:
                d = ma_analysis['mas'].get(p)
                if d is None:
                    msg += f"MA{p:<4} {'NaN':<10} {'NaN':<10} N/A\n"
                else:
                    msg += f"MA{p:<4} {d['value']:>9,.0f}  {d['diff_pct']:>+8.2f}%  {d['position']}\n"
            msg += "```"

            above = sum(
                1 for p in [20, 60, 120, 200]
                if ma_analysis['mas'].get(p) and ma_analysis['mas'][p]['position'] == 'ABOVE'
            )
            if above == 4:
                msg += "\n💚 *Harga di atas semua MA — Strong uptrend!*"
            elif ma_analysis['mas'].get(20) and ma_analysis['mas'][20]['position'] == 'ABOVE':
                msg += "\n🟢 *Harga di atas MA20 — Short term bullish*"
            else:
                msg += "\n📊 *Monitor pergerakan MA untuk konfirmasi trend*"
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(f"❌ MA: {ma_error}")
        await asyncio.sleep(0.3)

        # ── 4. Foreign Summary ────────────────────────────────────────────────
        foreign_summary = await asyncio.get_event_loop().run_in_executor(
            None, get_foreign_summary_by_days, stock_code
        )
        if foreign_summary:
            msg = (
                f"```\n📊 FOREIGN FLOW SUMMARY — {stock_code}\n"
                f"{'='*50}\n"
                f"{'Period':>6} | {'Buy':>12} | {'Sell':>12} | {'Net':>13}\n"
                f"{'='*50}\n"
            )
            for label, buy, sell, net in foreign_summary:
                msg += f"{label:>6} | {buy:>12,.0f} | {sell:>12,.0f} | {net:>+13,.0f}\n"
            msg += "```"
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        await asyncio.sleep(0.3)

        # ── 5. Margin Status ──────────────────────────────────────────────────
        margin_analysis, margin_error = await asyncio.get_event_loop().run_in_executor(
            None, get_stock_margin_data, stock_code
        )
        if margin_analysis:
            await update.message.reply_text(
                f"```\n💰 MARGIN TRADING — {stock_code}\n"
                f"{'='*30}\n"
                f"Status: Marginable ✅\n"
                f"```",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text(f"ℹ️ Margin: {margin_error}")
        await asyncio.sleep(0.3)

        # ── 6. Margin Chart ───────────────────────────────────────────────────
        try:
            chart_buf = await asyncio.get_event_loop().run_in_executor(
                None, margin_viewer.create_margin_charts, stock_code
            )
            if chart_buf:
                await update.message.reply_photo(
                    photo=chart_buf,
                    caption=f"📊 Margin Trading Chart — {stock_code}",
                )
                await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(f"Margin chart error: {e}")

        # ── 7. Holdings ───────────────────────────────────────────────────────
        holdings_text = await asyncio.get_event_loop().run_in_executor(
            None, get_holdings_text, stock_code
        )
        if holdings_text:
            await update.message.reply_text(holdings_text, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(f"ℹ️ Holdings: Data tidak tersedia untuk {stock_code}")
        await asyncio.sleep(0.3)

        # ── 8. Sector ─────────────────────────────────────────────────────────
        sector_analysis, sector_error = await asyncio.get_event_loop().run_in_executor(
            None, get_stock_sector_data, stock_code
        )
        if sector_analysis:
            tanggal = sector_analysis.get('tanggal_pencatatan', '')
            try:
                tanggal = pd.to_datetime(tanggal).strftime('%d/%m/%Y')
            except Exception:
                tanggal = str(tanggal)
            papan = sector_analysis.get('papan_pencatatan', '-')
            await update.message.reply_text(
                f"```\n🏢 SECTOR INFORMATION — {stock_code}\n"
                f"{'='*40}\n"
                f"{'Sektor':<22}: {sector_analysis['sector']}\n"
                f"{'Tanggal Pencatatan':<22}: {tanggal}\n"
                f"{'Papan Pencatatan':<22}: {papan}\n"
                f"```",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text(f"ℹ️ Sektor: {sector_error}")
        await asyncio.sleep(0.3)

        # ── Ringkasan Akhir ───────────────────────────────────────────────────
        elapsed = time.time() - start_time
        summary = f"✅ *RINGKASAN ANALISIS {stock_code}*\n\n"

        if sector_analysis:
            summary += f"🏢 Sektor: {sector_analysis['sector']}\n"
        if volume_analysis:
            label = '🚀 HIGH' if volume_analysis['vol_spike'] >= 2.2 else '😐 NORMAL'
            summary += f"📈 VSA Score: {volume_analysis['vol_spike']:.2f} ({label})\n"
        if foreign_analysis:
            label = '💚 BUY' if foreign_analysis['is_net_positive'] else '🔴 SELL'
            summary += f"🌍 Net Foreign: {foreign_analysis['latest_net']:+,.0f} ({label})\n"
        if ma_analysis:
            above = sum(
                1 for p in [20, 60, 120, 200]
                if ma_analysis['mas'].get(p) and ma_analysis['mas'][p]['position'] == 'ABOVE'
            )
            summary += f"📊 MA Position: {above}/4 Above\n"
        summary += f"💰 Margin: {'✅ Available' if margin_analysis else '❌ Not Available'}\n"
        summary += f"\n⏱️ Selesai dalam {elapsed:.2f} detik"

        await update.message.reply_text(summary, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"cmd_saham error: {e}", exc_info=True)
        await processing_msg.edit_text(f"❌ Terjadi error: {e}")
    finally:
        await processing_msg.delete()
        margin_viewer.margin_df  = None
        margin_viewer.combined_df = None
        gc.collect()


# ══════════════════════════════════════════════════════════════════════════════
#  Registration
# ══════════════════════════════════════════════════════════════════════════════

def register_saham_handler(app):
    """Daftarkan /saham ke Application."""
    app.add_handler(CommandHandler("saham", cmd_saham))
