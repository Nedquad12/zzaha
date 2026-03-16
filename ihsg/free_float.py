"""
free_float.py — Handler /ff TICKER
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import glob
import logging

import pandas as pd
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from stock_holdings import holdings
from admin.auth import is_authorized_user, is_vip_user

logger = logging.getLogger(__name__)

FOLDER_PATH = "/home/ec2-user/database/foreign"
KURS        = 16300

def _fmt_rupiah(val: float) -> str:
    if val >= 1e12:
        return f"Rp {val/1e12:.2f}T"
    if val >= 1e9:
        return f"Rp {val/1e9:.1f}B"
    if val >= 1e6:
        return f"Rp {val/1e6:.1f}M"
    return f"Rp {val:,.0f}"

def _fmt_shares(val: float) -> str:
    return f"{int(val):,}".replace(",", ".")

def _fmt_usd(val_idr: float) -> str:
    usd = val_idr / KURS
    if usd >= 1e9:
        return f"USD {usd/1e9:.2f}B"
    if usd >= 1e6:
        return f"USD {usd/1e6:.1f}M"
    return f"USD {usd:,.0f}"


async def cmd_ff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ── Auth guard ──
    uid = update.effective_user.id
    if not (is_authorized_user(uid) or is_vip_user(uid)):
        await update.message.reply_text("⛔ Kamu tidak punya akses ke bot ini.")
        return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text(
            "⚠️ Gunakan: /ff KODE\nContoh: /ff BBCA"
        )
        return

    code = parts[1].upper()

    excel_files = sorted(glob.glob(os.path.join(FOLDER_PATH, "*.xlsx")), reverse=True)
    if not excel_files:
        await update.message.reply_text(f"❌ Tidak ada file di folder foreign.")
        return

    try:
        df = pd.read_excel(excel_files[0])
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal baca file: {e}")
        return

    required = ['Kode Saham', 'Weight For Index', 'Penutupan', 'Listed Shares']
    if not all(c in df.columns for c in required):
        await update.message.reply_text(f"❌ Kolom tidak lengkap di file sumber.")
        return

    stock = df[df['Kode Saham'].str.upper() == code]
    if stock.empty:
        await update.message.reply_text(f"❌ Saham {code} tidak ditemukan.")
        return

    row           = stock.iloc[0]
    weight_index  = float(row['Weight For Index'])
    penutupan     = float(row['Penutupan'])
    listed_shares = float(row['Listed Shares'])

    ff_value = weight_index * penutupan
    ff_pct   = (weight_index / listed_shares) * 100

    sh_df = holdings.df[holdings.df['SHARE_CODE'] == code].copy()

    small_holders = sh_df[sh_df['PERCENTAGE'] < 5.0]
    small_shares  = float(small_holders['TOTAL_HOLDING_SHARES'].sum())
    small_pct     = float(small_holders['PERCENTAGE'].sum())

    ff_adj_shares = max(weight_index - small_shares, 0)
    ff_adj_value  = ff_adj_shares * penutupan
    ff_adj_pct    = (ff_adj_shares / listed_shares) * 100

    if not small_holders.empty:
        sh_sorted = small_holders.sort_values('PERCENTAGE', ascending=False)
        exclude_lines = []
        for _, r in sh_sorted.head(10).iterrows():
            name = str(r['INVESTOR_NAME'])[:28]
            exclude_lines.append(f"  {name:<28} {r['PERCENTAGE']:.2f}%")
        if len(sh_sorted) > 10:
            exclude_lines.append(f"  ... dan {len(sh_sorted)-10} investor lainnya")
        exclude_block = "\n".join(exclude_lines)
    else:
        exclude_block = "  (tidak ada)"

    response = (
        f"📊 *Free Float Summary — {code}*\n"
        f"Harga penutupan: Rp {penutupan:,.0f}\n"
        f"Listed shares  : {_fmt_shares(listed_shares)} lembar\n"
        f"\n"
        f"```\n"
        f"{'─'*38}\n"
        f" FREE FLOAT (data bursa)\n"
        f"{'─'*38}\n"
        f" Lembar    : {_fmt_shares(weight_index)}\n"
        f" FF %      : {ff_pct:.2f}%\n"
        f" FFMC      : {_fmt_rupiah(ff_value)}\n"
        f"           : {_fmt_usd(ff_value)}\n"
        f"{'─'*38}\n"
        f" FREE FLOAT ADJ (exclude <5%)\n"
        f"{'─'*38}\n"
        f" Dikurangi : {_fmt_shares(small_shares)} lembar ({small_pct:.2f}%)\n"
        f" Lembar    : {_fmt_shares(ff_adj_shares)}\n"
        f" FF Adj %  : {ff_adj_pct:.2f}%\n"
        f" FFMC Adj  : {_fmt_rupiah(ff_adj_value)}\n"
        f"           : {_fmt_usd(ff_adj_value)}\n"
        f"{'─'*38}\n"
        f"```\n"
        f"\n"
        f"*Investor <5% yang di-exclude:*\n"
        f"```\n"
        f"{exclude_block}\n"
        f"```"
    )

    await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
