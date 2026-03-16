"""
indicators/wcc.py — Wick Candle Change

Kolom yang dibutuhkan: 'open', 'high', 'low', 'close'  (dinormalise loader.py)
"""

import pandas as pd


def score_wcc(df: pd.DataFrame) -> int:
    if len(df) < 2:
        return 0

    today  = df.iloc[-1]
    prev   = df.iloc[-2]

    o      = float(today["open"])
    h      = float(today["high"])
    l      = float(today["low"])
    c      = float(today["close"])
    c_prev = float(prev["close"])

    if o == 0 or c == c_prev:
        return 0

    open_to_close = (c - o) / o * 100
    close_up      = c > c_prev

    if close_up and open_to_close < 0:
        close_up = False
    elif not close_up and open_to_close > 0:
        close_up = True

    if open_to_close == 0:
        return 0

    if close_up:
        low_to_open = (o - l) / o * 100
        ratio = (low_to_open / open_to_close) * 100
        if ratio >= 650:
            return 3
        elif ratio >= 350:
            return 2
        elif ratio >= 50:
            return 1
        else:
            return 0
    else:
        high_to_open = (h - o) / o * 100
        ratio = (high_to_open / open_to_close) * 100
        if ratio <= -650:
            return -3
        elif ratio <= -350:
            return -2
        elif ratio <= -50:
            return -1
        else:
            return 0


def get_wcc_detail(df: pd.DataFrame) -> dict:
    empty = {"open_to_close": 0.0, "wick_to_body": 0.0, "ratio": 0.0, "score": 0, "direction": "-"}
    if len(df) < 2:
        return empty

    today  = df.iloc[-1]
    prev   = df.iloc[-2]
    o      = float(today["open"])
    h      = float(today["high"])
    l      = float(today["low"])
    c      = float(today["close"])
    c_prev = float(prev["close"])

    if o == 0 or c == c_prev:
        return empty

    open_to_close = (c - o) / o * 100
    close_up      = c > c_prev
    direction     = "UP" if close_up else "DOWN"

    if close_up and open_to_close < 0:
        close_up  = False
        direction = "DOWN"
    elif not close_up and open_to_close > 0:
        close_up  = True
        direction = "UP"

    if open_to_close == 0:
        return empty

    wick_to_body = ((o - l) / o * 100) if close_up else ((h - o) / o * 100)
    ratio        = (wick_to_body / open_to_close) * 100

    return {
        "open_to_close": round(open_to_close, 2),
        "wick_to_body":  round(wick_to_body,  2),
        "ratio":         round(ratio,          2),
        "score":         score_wcc(df),
        "direction":     direction,
    }
