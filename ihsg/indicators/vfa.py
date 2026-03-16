"""
indicators/vfa.py — Volume Frequency Analysis

Kolom yang dibutuhkan: 'volume', 'transactions'  (dinormalise loader.py)
"""

import numpy as np
import pandas as pd


def _avg_pct_change(arr: np.ndarray, n: int = 7) -> float:
    tail = arr[-(n + 1):]
    if len(tail) < 2:
        return 0.0
    changes = []
    for i in range(1, len(tail)):
        prev = tail[i - 1]
        if prev == 0:
            continue
        changes.append((tail[i] - prev) / prev * 100.0)
    return float(np.mean(changes)) if changes else 0.0


def score_vfa(df: pd.DataFrame) -> int:
    if "transactions" not in df.columns or len(df) < 8:
        return 0

    vol_arr  = pd.to_numeric(df["volume"],       errors="coerce").fillna(0).values
    freq_arr = pd.to_numeric(df["transactions"],  errors="coerce").fillna(0).values

    avg_vol  = _avg_pct_change(vol_arr)
    avg_freq = _avg_pct_change(freq_arr)

    if avg_vol < 0 and avg_freq < 0:
        return -3
    if avg_vol < 0:
        return 2
    if avg_freq < 0:
        return 1
    if avg_vol == 0 and avg_freq == 0:
        return 0
    if avg_freq == 0:
        return -1
    if avg_vol == 0:
        return 2

    vol_to_freq = avg_vol / avg_freq
    freq_to_vol = avg_freq / avg_vol

    if vol_to_freq >= 2.0:
        return -1
    elif avg_vol > avg_freq:
        return 1
    elif freq_to_vol >= 2.0:
        return 3
    else:
        return 2


def get_vfa_detail(df: pd.DataFrame) -> dict:
    if "transactions" not in df.columns or len(df) < 8:
        return {"avg_vol": 0.0, "avg_freq": 0.0, "score": 0}
    vol_arr  = pd.to_numeric(df["volume"],      errors="coerce").fillna(0).values
    freq_arr = pd.to_numeric(df["transactions"], errors="coerce").fillna(0).values
    return {
        "avg_vol":  round(_avg_pct_change(vol_arr),  2),
        "avg_freq": round(_avg_pct_change(freq_arr), 2),
        "score":    score_vfa(df),
    }
