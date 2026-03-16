"""
scorer.py — Hitung semua skor indikator untuk satu saham.

Data diambil dari JSON harian via indicators/loader.py.
Indikator eksternal (MGN, BRK, OWN) diambil dari cache_manager.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
import pandas as pd

from indicators.loader import build_stock_df
from indicators import (
    score_vsa, score_fsa, score_vfa,
    score_wcc, score_rsi, score_macd, score_ma,
    calculate_ip, score_ip, score_srst,
    score_tight, score_fbs,
    score_mgn, score_brk, score_own,
)
from cache_manager import get_mgn_cache, get_brk_cache, get_own_cache

# Path default — bisa di-override saat import
JSON_DIR = "/home/ec2-user/database/json"


def calculate_all_scores(ticker: str, json_dir: str = JSON_DIR) -> dict | None:
    """
    Hitung semua skor untuk satu saham.

    Args:
        ticker   : kode saham, e.g. "BBCA"
        json_dir : folder berisi file ddmmyy.json

    Returns:
        Dict berisi semua skor dan metadata.
        None jika data tidak ditemukan.
    """
    df = build_stock_df(ticker, json_dir, max_days=60)

    if df is None or df.empty:
        return None

    # ── Ambil cache eksternal ─────────────────────────────────────────────────
    mgn_cache = get_mgn_cache()
    brk_cache = get_brk_cache()
    own_cache = get_own_cache()

    # ── Hitung semua indikator ────────────────────────────────────────────────
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

    # ── Indikator eksternal ───────────────────────────────────────────────────
    mgn    = score_mgn(ticker, mgn_cache)
    brk    = score_brk(ticker, brk_cache)
    own    = score_own(ticker, own_cache)

    total = vsa + fsa + vfa + wcc + rsi + macd + ma + ip_pts + srst + tight + fbs + mgn + brk + own

    # ── Metadata harga ────────────────────────────────────────────────────────
    price  = float(df["close"].iloc[-1])
    prev   = float(df["close"].iloc[-2]) if len(df) > 1 else price
    change = ((price - prev) / prev * 100) if prev != 0 else 0.0

    return {
        "ticker":   ticker.upper(),
        "date":     df["date"].iloc[-1].strftime("%Y-%m-%d"),
        "price":    round(price,  0),
        "change":   round(change, 2),
        # skor per indikator
        "vsa":      vsa,
        "fsa":      fsa,
        "vfa":      vfa,
        "wcc":      wcc,
        "rsi":      rsi,
        "macd":     macd,
        "ma":       ma,
        "ip_raw":   round(ip_raw, 2),
        "ip_score": ip_pts,
        "srst":     srst,
        "tight":    tight,
        "fbs":      fbs,
        "mgn":      mgn,
        "brk":      brk,
        "own":      own,
        # total
        "total":    round(total, 2),
    }


def do_skor(ticker: str, json_dir: str = JSON_DIR) -> str:
    """Format hasil skor sebagai string Markdown untuk Telegram."""
    ticker = ticker.upper().strip()
    result = calculate_all_scores(ticker, json_dir=json_dir)

    if result is None:
        return (
            f"⚠️ Data untuk *{ticker}* tidak ditemukan\.\n"
            f"Minta admin reload `/4` dan pastikan kode saham benar\."
        )

    chg     = result["change"]
    chg_str = f"+{chg:.2f}%" if chg >= 0 else f"{chg:.2f}%"
    emoji   = "🟢" if chg >= 0 else "🔴"

    def fmt(val):
        return f"{val:+.1f}" if isinstance(val, float) else f"{val:+d}"

    # Label tight
    tight_val   = result["tight"]
    tight_label = {3: " VT+T", 2: " VT", 1: " T", 0: ""}.get(tight_val, "")

    # Label MGN, BRK, OWN (tampilkan 0 jika tidak ada data)
    mgn_note = "" if result["mgn"] != 0 else " (n/a)"
    brk_note = "" if result["brk"] != 0 else " (n/a)"
    own_note = "" if result["own"] != 0 else " (n/a)"

    return (
        f"📊 *{result['ticker']}*  —  {result['date']}\n"
        f"{emoji} Rp {result['price']:,.0f}  `{chg_str}`\n"
        f"\n"
        f"```\n"
        f"Indikator   Skor\n"
        f"─────────────────\n"
        f"VSA         {fmt(result['vsa'])}\n"
        f"FSA         {fmt(result['fsa'])}\n"
        f"VFA         {fmt(result['vfa'])}\n"
        f"WCC         {fmt(result['wcc'])}\n"
        f"RSI         {fmt(result['rsi'])}\n"
        f"MACD        {fmt(result['macd'])}\n"
        f"MA          {fmt(result['ma'])}\n"
        f"IP ({result['ip_raw']:+.2f})  {fmt(result['ip_score'])}\n"
        f"SRST        {fmt(result['srst'])}\n"
        f"TIGHT{tight_label:<4}  {fmt(tight_val)}\n"
        f"FBS         {fmt(result['fbs'])}\n"
        f"MGN{mgn_note:<7}  {fmt(result['mgn'])}\n"
        f"BRK{brk_note:<7}  {fmt(result['brk'])}\n"
        f"OWN{own_note:<7}  {fmt(result['own'])}\n"
        f"─────────────────\n"
        f"TOTAL       {fmt(result['total'])}\n"
        f"```"
    )


def print_score_table(result: dict):
    """Tampilkan hasil skor dalam format tabel di terminal."""
    ticker  = result["ticker"]
    date    = result["date"]
    price   = result["price"]
    chg     = result["change"]
    chg_str = f"+{chg:.2f}%" if chg >= 0 else f"{chg:.2f}%"

    tight_label = {3: "VT+T", 2: "VT  ", 1: "T   ", 0: "    "}.get(result["tight"], "    ")

    print(f"""
┌─────────────────────────────────────────┐
│  {ticker:<10}  {date}   Rp {price:>10,.0f}  {chg_str:>8}
├──────────────┬──────────────────────────┤
│ Indikator    │  Skor                    │
├──────────────┼──────────────────────────┤
│ VSA          │  {result['vsa']:>+4}                    │
│ FSA          │  {result['fsa']:>+4}                    │
│ VFA          │  {result['vfa']:>+4}                    │
│ WCC          │  {result['wcc']:>+4}                    │
│ RSI          │  {result['rsi']:>+4}                    │
│ MACD         │  {result['macd']:>+4}                    │
│ MA           │  {result['ma']:>+4}                    │
│ IP ({result['ip_raw']:>+6.2f}) │  {result['ip_score']:>+4.1f}                   │
│ SRST         │  {result['srst']:>+4}                    │
│ TIGHT {tight_label}  │  {result['tight']:>+4}                    │
│ FBS          │  {result['fbs']:>+4}                    │
│ MGN          │  {result['mgn']:>+4}                    │
│ BRK          │  {result['brk']:>+4}                    │
│ OWN          │  {result['own']:>+4}                    │
├──────────────┼──────────────────────────┤
│ TOTAL        │  {result['total']:>+6.2f}                  │
└──────────────┴──────────────────────────┘""")
