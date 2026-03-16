"""
indicators/srst.py — Support & Resistance Smart Tool

Kolom yang dibutuhkan: 'open', 'high', 'low', 'close', 'volume'
"""

import pandas as pd
from .sr import detect_sr, SRLevel


def _score_support(close: float, active_levels: list) -> int:
    sup_levels = [l for l in active_levels if l.is_support and l.top <= close]
    if not sup_levels:
        return 0
    nearest   = min(sup_levels, key=lambda l: close - l.top)
    dist_pct  = (close - nearest.top) / close * 100
    if dist_pct > 5.0:
        return 0
    score = 1
    if nearest.entries > 2:
        score += 1
    if nearest.entries > 4:
        score += 1
    return score


def _score_resistance(close: float, active_levels: list) -> int:
    res_levels = [l for l in active_levels if not l.is_support and l.base_price >= close]
    if not res_levels:
        return 0
    nearest  = min(res_levels, key=lambda l: l.base_price - close)
    dist_pct = (nearest.base_price - close) / close * 100
    if dist_pct > 5.0:
        return 0
    score = -1
    if nearest.entries > 2:
        score -= 1
    if nearest.entries > 4:
        score -= 2
    return score


def score_srst(df: pd.DataFrame) -> int:
    if len(df) < 30:
        return 0
    try:
        active_levels, _ = detect_sr(df)
    except Exception:
        return 0
    if not active_levels:
        return 0
    close = float(df["close"].iloc[-1])
    return _score_support(close, active_levels) + _score_resistance(close, active_levels)


def get_srst_detail(df: pd.DataFrame) -> dict:
    empty = {
        "nearest_sup": None, "sup_dist_pct": None, "sup_entries": None,
        "nearest_res": None, "res_dist_pct": None, "res_entries": None,
        "score": 0,
    }
    if len(df) < 30:
        return empty
    try:
        active_levels, _ = detect_sr(df)
    except Exception:
        return empty
    if not active_levels:
        return empty
    close = float(df["close"].iloc[-1])
    sup_levels  = [l for l in active_levels if l.is_support and l.top <= close]
    res_levels  = [l for l in active_levels if not l.is_support and l.base_price >= close]
    nearest_sup = min(sup_levels, key=lambda l: close - l.top)       if sup_levels else None
    nearest_res = min(res_levels, key=lambda l: l.base_price - close) if res_levels else None
    return {
        "nearest_sup":  round(nearest_sup.top, 4)                         if nearest_sup else None,
        "sup_dist_pct": round((close - nearest_sup.top) / close * 100, 2) if nearest_sup else None,
        "sup_entries":  nearest_sup.entries                                if nearest_sup else None,
        "nearest_res":  round(nearest_res.base_price, 4)                  if nearest_res else None,
        "res_dist_pct": round((nearest_res.base_price - close) / close * 100, 2) if nearest_res else None,
        "res_entries":  nearest_res.entries                                if nearest_res else None,
        "score":        score_srst(df),
    }
