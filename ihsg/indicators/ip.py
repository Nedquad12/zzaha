"""
indicators/ip.py — Indikator Poin (IP)

Kolom yang dibutuhkan: 'close', 'high', 'low'
"""

import numpy as np
import pandas as pd


def _ema(series: list, span: int) -> list:
    k   = 2 / (span + 1)
    out = [series[0]]
    for v in series[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _macd_score(closes: list) -> int:
    if len(closes) < 35:
        return 0
    ema12  = _ema(closes, 12)
    ema26  = _ema(closes, 26)
    macd   = [a - b for a, b in zip(ema12, ema26)]
    signal = _ema(macd, 9)
    m, s   = macd[-1], signal[-1]
    score  = 0
    score += 1 if m > s else (-1 if m < s else 0)
    score += 1 if m > 0 else (-1 if m < 0 else 0)
    return score


def _stoch_score(highs, lows, closes, k_period=14, d_period=3) -> int:
    if len(closes) < k_period + d_period:
        return 0
    k_vals = []
    for i in range(len(closes) - k_period + 1):
        lo = min(lows[i:i + k_period])
        hi = max(highs[i:i + k_period])
        k_vals.append((closes[i + k_period - 1] - lo) / (hi - lo) * 100 if hi != lo else 50.0)
    if len(k_vals) < d_period:
        return 0
    k = k_vals[-1]
    d = float(np.mean(k_vals[-d_period:]))
    score = 0
    if k < 25:
        score += 1
    elif k > 85:
        score -= 1
    score += 1 if k > d else (-1 if k < d else 0)
    return score


def _aggregate(closes, highs, lows, period):
    wc, wh, wl = [], [], []
    for i in range(0, len(closes), period):
        c = closes[i:i + period]
        if c:
            wc.append(c[-1])
            wh.append(max(highs[i:i + period]))
            wl.append(min(lows[i:i + period]))
    return wc, wh, wl


def calculate_ip(df: pd.DataFrame) -> float:
    closes = df["close"].tolist()
    highs  = df["high"].tolist()
    lows   = df["low"].tolist()

    ipd = _macd_score(closes) + _stoch_score(highs, lows, closes)

    wc, wh, wl = _aggregate(closes, highs, lows, 5)
    ipw = _macd_score(wc) + _stoch_score(wh, wl, wc)

    mc, mh, ml = _aggregate(closes, highs, lows, 25)
    ipm = _macd_score(mc) + _stoch_score(mh, ml, mc)

    return (ipd + ipw + ipm) / 3.0


def score_ip(ip_value: float) -> float:
    if ip_value >= 3:
        return 4.0
    elif ip_value >= 1.3:
        return 2.0
    elif ip_value >= 0.3:
        return 1.0
    elif ip_value >= 0:
        return 0.0
    elif ip_value <= -3:
        return -4.0
    elif ip_value <= -1.3:
        return -2.0
    elif ip_value <= -0.3:
        return -1.0
    else:
        return 0.0
