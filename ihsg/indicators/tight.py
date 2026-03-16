"""
indicators/tight.py — Tight / Very Tight Detector

Definisi:
  VT (Very Tight) : close > MA3/5/10/20 DAN jarak ke semua MA < 5%
  T  (Tight)      : close > MA3/5/10/20 DAN jarak ke semua MA antara 5%–15%

Scoring per ticker:
  VT + T  → +3   (sangat rapat, masuk kedua bucket)
  VT saja → +2
  T saja  → +1
  tidak masuk keduanya → 0

Kolom yang dibutuhkan: 'close', 'volume'
"""

import numpy as np
import pandas as pd

# ── Konstanta ──────────────────────────────────────────────────────────────────
MA_PERIODS   = [3, 5, 10, 20]
VT_THRESHOLD = 5.0   # jarak maksimal untuk VT (%)
T_MIN        = 5.0   # jarak minimal untuk T (%)
T_MAX        = 15.0  # jarak maksimal untuk T (%)


# ── Helper ─────────────────────────────────────────────────────────────────────

def _calc_mas(df: pd.DataFrame) -> dict | None:
    """Hitung MA 3/5/10/20 dari kolom close. Return None jika data tidak cukup."""
    closes = df["close"].values
    if len(closes) < max(MA_PERIODS):
        return None
    return {p: float(np.mean(closes[-p:])) for p in MA_PERIODS}


def _pct_distance(price: float, ma: float) -> float:
    if ma == 0 or np.isnan(ma):
        return float("inf")
    return (price - ma) / ma * 100


def _get_tight_bucket(df: pd.DataFrame) -> str | None:
    """
    Return 'VT', 'T', atau None.
    Harga harus di atas semua MA, baru dicek jaraknya.
    """
    if len(df) < max(MA_PERIODS):
        return None

    close = float(df["close"].iloc[-1])
    mas   = _calc_mas(df)
    if mas is None:
        return None

    if any(np.isnan(v) or v == 0 for v in mas.values()):
        return None

    if not all(close > mas[p] for p in MA_PERIODS):
        return None

    max_dist = max(_pct_distance(close, mas[p]) for p in MA_PERIODS)

    if max_dist < VT_THRESHOLD:
        return "VT"
    if T_MIN <= max_dist < T_MAX:
        return "T"
    return None


# ── Public: skor per ticker ────────────────────────────────────────────────────

def score_tight(df: pd.DataFrame) -> int:
    """
    Hitung tight score dari DataFrame satu saham.

    Returns:
        +3  masuk VT dan T  (sangat rapat)
        +2  masuk VT saja
        +1  masuk T saja
         0  tidak masuk keduanya
    """
    bucket = _get_tight_bucket(df)

    if bucket == "VT":
        # VT juga dianggap memenuhi T (subset lebih ketat), skor +3
        return 3
    if bucket == "T":
        return 1
    return 0


def get_tight_detail(df: pd.DataFrame) -> dict:
    """
    Return detail untuk debugging / laporan.
    """
    if len(df) < max(MA_PERIODS):
        return {"bucket": None, "max_dist": None, "mas": {}, "score": 0}

    close = float(df["close"].iloc[-1])
    mas   = _calc_mas(df) or {}

    if not mas or any(np.isnan(v) or v == 0 for v in mas.values()):
        return {"bucket": None, "max_dist": None, "mas": mas, "score": 0}

    above_all = all(close > mas[p] for p in MA_PERIODS)
    distances = {p: round(_pct_distance(close, mas[p]), 2) for p in MA_PERIODS}
    max_dist  = max(distances.values()) if above_all else None
    bucket    = _get_tight_bucket(df)

    return {
        "bucket":    bucket,
        "above_all": above_all,
        "max_dist":  round(max_dist, 2) if max_dist is not None else None,
        "distances": distances,
        "mas":       {p: round(v, 2) for p, v in mas.items()},
        "score":     score_tight(df),
    }
