"""
wti.py — Weight To Index (WTI)

Mengukur korelasi arah gerak saham terhadap SPY selama 90 hari terakhir.

Logic:
  Threshold saham = (ATR14 / harga_close_terakhir) * 100 / 3  (dalam %)
  Threshold SPY   = 0.1% (fix)

  SPY Up   = SPY change% > +0.1%  DAN  saham change% > +threshold_saham
  SPY Down = SPY change% < -0.1%  DAN  saham change% < -threshold_saham
  Netral   = semua kondisi di luar dua di atas

Data SPY   : /home/ec2-user/us/500/SPY.json
Data saham : /home/ec2-user/us/500/{TICKER}.json
"""

import json
import os
import numpy as np
from typing import Optional

SPY_JSON_PATH  = "/home/ec2-user/us/500/SPY.json"
SCORE_500_DIR  = "/home/ec2-user/us/500"

LOOKBACK_DAYS  = 90      # window perbandingan (hari)
ATR_PERIOD     = 14      # periode ATR Wilder
ATR_DIVISOR    = 3.0     # ATR% dibagi 3 → threshold saham
SPY_THRESHOLD  = 0.1     # SPY threshold fix (%)


# ── Data loader ───────────────────────────────────────────────────────────────

def _load_history(json_path: str) -> Optional[list[dict]]:
    """
    Baca list bar dari file score history JSON.
    Return list of dict: date, close (=price), high, low
    Return None jika file tidak ada atau kosong.
    """
    if not os.path.exists(json_path):
        return None
    try:
        with open(json_path, "r") as f:
            payload = json.load(f)
        data = payload.get("data", [])
        result = []
        for row in data:
            date  = str(row.get("date", ""))[:10]
            price = float(row.get("price", 0))
            high  = float(row.get("high",  price))
            low   = float(row.get("low",   price))
            if date and price > 0:
                result.append({
                    "date":  date,
                    "close": price,
                    "high":  high,
                    "low":   low,
                })
        return result if result else None
    except Exception:
        return None


def _ticker_json_path(ticker: str) -> str:
    return os.path.join(SCORE_500_DIR, f"{ticker.upper()}.json")


# ── ATR 14 (Wilder) ───────────────────────────────────────────────────────────

def _calc_atr14(bars: list[dict]) -> Optional[float]:
    """
    Hitung ATR 14 Wilder dari seluruh bar yang tersedia.
    Return nilai ATR terakhir (float), atau None jika data kurang.
    """
    n = len(bars)
    if n < ATR_PERIOD + 1:
        return None

    highs  = [b["high"]  for b in bars]
    lows   = [b["low"]   for b in bars]
    closes = [b["close"] for b in bars]

    # True Range
    tr = [highs[0] - lows[0]]
    for i in range(1, n):
        tr.append(max(
            highs[i]  - lows[i],
            abs(highs[i]  - closes[i - 1]),
            abs(lows[i]   - closes[i - 1]),
        ))

    # Seed dengan simple average periode pertama
    atr = float(np.mean(tr[:ATR_PERIOD]))

    # Wilder smoothing
    for i in range(ATR_PERIOD, n):
        atr = (atr * (ATR_PERIOD - 1) + tr[i]) / ATR_PERIOD

    return atr


# ── Core calculation ──────────────────────────────────────────────────────────

def calculate_wti(ticker: str) -> Optional[dict]:
    """
    Hitung WTI untuk satu ticker vs SPY.

    Returns:
        dict hasil WTI, atau None jika data tidak tersedia / tidak cukup
    """
    # Load full history (untuk ATR pakai semua bar yang ada)
    spy_all = _load_history(SPY_JSON_PATH)
    tkr_all = _load_history(_ticker_json_path(ticker))

    if not spy_all or not tkr_all:
        return None

    # Hitung ATR14 dari full history saham
    atr14 = _calc_atr14(tkr_all)
    if atr14 is None:
        return None

    last_close    = tkr_all[-1]["close"]
    atr_pct       = (atr14 / last_close) * 100        # ATR dalam %
    tkr_threshold = atr_pct / ATR_DIVISOR              # threshold = ATR% / 3

    # Bangun dict date → close
    spy_map = {b["date"]: b["close"] for b in spy_all}
    tkr_map = {b["date"]: b["close"] for b in tkr_all}

    # Tanggal yang ada di kedua dataset, urutkan ascending
    common_dates = sorted(set(spy_map.keys()) & set(tkr_map.keys()))

    if len(common_dates) < 2:
        return None

    # Ambil LOOKBACK_DAYS bar terakhir (+1 untuk prev close bar pertama)
    window = common_dates[-(LOOKBACK_DAYS + 1):]

    spy_up_total  = 0
    spy_up_match  = 0   # SPY up DAN saham up
    spy_dn_total  = 0
    spy_dn_match  = 0   # SPY down DAN saham down
    neutral_total = 0

    for i in range(1, len(window)):
        d_today = window[i]
        d_prev  = window[i - 1]

        spy_chg = (spy_map[d_today] - spy_map[d_prev]) / spy_map[d_prev] * 100
        tkr_chg = (tkr_map[d_today] - tkr_map[d_prev]) / tkr_map[d_prev] * 100

        spy_is_up   = spy_chg >  SPY_THRESHOLD
        spy_is_down = spy_chg < -SPY_THRESHOLD
        tkr_is_up   = tkr_chg >  tkr_threshold
        tkr_is_down = tkr_chg < -tkr_threshold

        if spy_is_up:
            spy_up_total += 1
            if tkr_is_up:
                spy_up_match += 1
        elif spy_is_down:
            spy_dn_total += 1
            if tkr_is_down:
                spy_dn_match += 1
        else:
            neutral_total += 1

    total_bars = len(window) - 1

    spy_up_pct      = (spy_up_match / spy_up_total * 100) if spy_up_total > 0 else 0.0
    spy_up_miss_pct = 100.0 - spy_up_pct

    spy_dn_pct      = (spy_dn_match / spy_dn_total * 100) if spy_dn_total > 0 else 0.0
    spy_dn_miss_pct = 100.0 - spy_dn_pct

    return {
        "ticker":          ticker.upper(),
        "total_bars":      total_bars,
        "atr14":           round(atr14, 4),
        "atr_pct":         round(atr_pct, 2),
        "last_close":      round(last_close, 2),
        "tkr_threshold":   round(tkr_threshold, 2),

        "spy_up_total":    spy_up_total,
        "spy_up_match":    spy_up_match,
        "spy_up_pct":      round(spy_up_pct, 1),
        "spy_up_miss_pct": round(spy_up_miss_pct, 1),

        "spy_dn_total":    spy_dn_total,
        "spy_dn_match":    spy_dn_match,
        "spy_dn_pct":      round(spy_dn_pct, 1),
        "spy_dn_miss_pct": round(spy_dn_miss_pct, 1),

        "neutral_total":   neutral_total,
    }


# ── Formatter ─────────────────────────────────────────────────────────────────

def fmt_wti(result: dict) -> str:
    t = result["ticker"]

    spy_up_miss = result["spy_up_total"] - result["spy_up_match"]
    spy_dn_miss = result["spy_dn_total"] - result["spy_dn_match"]

    lines = [
        f"📊 <b>WTI — {t} vs SPY</b>  ({result['total_bars']} hari)\n",

        f"<code>Threshold {t:<6} : {result['tkr_threshold']:.2f}%"
        f"  (ATR14={result['atr_pct']:.2f}% ÷ 3)</code>",
        f"<code>Threshold SPY    : {SPY_THRESHOLD:.1f}% (fix)</code>\n",

        f"🟢 <b>SPY Up</b>   : <b>{result['spy_up_total']}</b> hari",
        f"   ✅ {t} ikut naik   : <b>{result['spy_up_pct']:.1f}%</b>  ({result['spy_up_match']} hari)",
        f"   ❌ {t} tidak ikut  : <b>{result['spy_up_miss_pct']:.1f}%</b>  ({spy_up_miss} hari)\n",

        f"🔴 <b>SPY Down</b> : <b>{result['spy_dn_total']}</b> hari",
        f"   ✅ {t} ikut turun  : <b>{result['spy_dn_pct']:.1f}%</b>  ({result['spy_dn_match']} hari)",
        f"   ❌ {t} tidak ikut  : <b>{result['spy_dn_miss_pct']:.1f}%</b>  ({spy_dn_miss} hari)\n",

        f"⚪ <b>Netral</b>   : <b>{result['neutral_total']}</b> hari",
    ]

    return "\n".join(lines)


def fmt_wti_error(ticker: str, reason: str) -> str:
    return (
        f"❌ <b>WTI — {ticker.upper()}</b>\n"
        f"{reason}\n\n"
        f"<i>Pastikan /9 sudah dijalankan dan data tersedia di "
        f"<code>/us/500/</code></i>"
    )
