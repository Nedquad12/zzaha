"""
indicators/fbs.py — Foreign Buy-Sell Flow

Bandingkan rata-rata Foreign Net 5 hari vs 22 hari bursa.
Foreign Net dihitung di sini: Foreign Buy - Foreign Sell

Logika skor:
  avg5 > avg22 dan delta/base >= 2.0  →  +2  (inflow akselerasi kuat)
  avg5 > avg22                         →  +1  (inflow meningkat / outflow melambat)
  avg5 == avg22                        →   0
  avg5 < avg22 dan delta/base >= 2.0  →  -2  (outflow akselerasi kuat)
  avg5 < avg22                         →  -1  (inflow melambat / outflow meningkat)

Edge cases:
  - avg22=-200k, avg5=-50k  →  avg5 > avg22  →  +1  (magnitude mengecil = membaik)
  - Keduanya 0 atau data < 22 hari  →  0

Kolom yang dibutuhkan: 'foreign_buy', 'foreign_sell'  (dinormalise loader.py)
"""

import numpy as np
import pandas as pd


def score_fbs(df: pd.DataFrame) -> int:
    """
    Hitung skor Foreign Buy-Sell flow.

    Args:
        df: DataFrame dengan kolom 'foreign_buy' dan 'foreign_sell',
            diurutkan ascending

    Returns:
        Skor integer antara -2 dan +2
    """
    if "foreign_buy" not in df.columns or "foreign_sell" not in df.columns:
        return 0
    if len(df) < 22:
        return 0

    buy  = pd.to_numeric(df["foreign_buy"],  errors="coerce").fillna(0).values
    sell = pd.to_numeric(df["foreign_sell"], errors="coerce").fillna(0).values
    net  = buy - sell

    avg5  = float(np.mean(net[-5:]))
    avg22 = float(np.mean(net[-22:]))

    if avg5 == 0 and avg22 == 0:
        return 0

    if avg5 > avg22:
        base  = abs(avg22) if avg22 != 0 else abs(avg5)
        if base == 0:
            return 1
        delta = avg5 - avg22
        ratio = delta / base
        return 2 if ratio >= 2.0 else 1

    elif avg5 < avg22:
        base  = abs(avg22) if avg22 != 0 else abs(avg5)
        if base == 0:
            return -1
        delta = avg22 - avg5  # selalu positif
        ratio = delta / base
        return -2 if ratio >= 2.0 else -1

    return 0


def get_fbs_detail(df: pd.DataFrame) -> dict:
    """Return detail untuk debugging / laporan."""
    empty = {
        "avg5": 0.0, "avg22": 0.0,
        "delta": 0.0, "ratio": 0.0,
        "score": 0,
    }

    if "foreign_buy" not in df.columns or "foreign_sell" not in df.columns:
        return empty
    if len(df) < 22:
        return empty

    buy  = pd.to_numeric(df["foreign_buy"],  errors="coerce").fillna(0).values
    sell = pd.to_numeric(df["foreign_sell"], errors="coerce").fillna(0).values
    net  = buy - sell

    avg5  = float(np.mean(net[-5:]))
    avg22 = float(np.mean(net[-22:]))
    delta = avg5 - avg22
    base  = abs(avg22) if avg22 != 0 else (abs(avg5) if avg5 != 0 else 1.0)
    ratio = delta / base

    return {
        "avg5":  round(avg5,  0),
        "avg22": round(avg22, 0),
        "delta": round(delta, 0),
        "ratio": round(ratio, 2),
        "score": score_fbs(df),
    }
