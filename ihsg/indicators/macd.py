"""
indicators/macd.py — MACD (12, 26, 9)

Kolom yang dibutuhkan: 'close'
"""

import pandas as pd


def _compute_macd(closes: pd.Series, fast=12, slow=26, signal=9):
    ema_fast    = closes.ewm(span=fast,   adjust=False).mean()
    ema_slow    = closes.ewm(span=slow,   adjust=False).mean()
    macd_line   = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return float(macd_line.iloc[-1]), float(signal_line.iloc[-1])


def score_macd(df: pd.DataFrame) -> int:
    if len(df) < 35:
        return 0

    macd_val, signal_val = _compute_macd(df["close"])
    score = 0

    if macd_val > signal_val:
        score += 1
    elif macd_val < signal_val:
        score -= 1

    if macd_val > 0:
        score += 1
    elif macd_val < 0:
        score -= 1

    return score
