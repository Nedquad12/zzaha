"""
indicators/ma.py — Moving Average (20, 60, 120, 200)

Kolom yang dibutuhkan: 'close'
"""

import pandas as pd

MA_PERIODS = [20, 60, 120, 200]


def score_ma(df: pd.DataFrame) -> int:
    if len(df) < max(MA_PERIODS):
        return 0

    price  = float(df["close"].iloc[-1])
    closes = df["close"]

    above_count = sum(
        1 for p in MA_PERIODS
        if price > float(closes.tail(p).mean())
    )

    return {4: 2, 3: 1, 2: 0, 1: -1, 0: -2}[above_count]
