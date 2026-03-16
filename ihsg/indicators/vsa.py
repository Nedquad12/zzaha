"""
indicators/vsa.py — Volume Super Analysis

Logika:
  avg7 / avg30 >= 2.0  →  +2
  avg7 > avg30          →  +1
  avg7 == avg30         →   0
  avg7 < avg30          →  -1
  avg30 / avg7 >= 2.0  →  -2

Kolom yang dibutuhkan: 'volume'  (sudah dinormalise oleh loader.py)
"""

import numpy as np
import pandas as pd


def score_vsa(df: pd.DataFrame) -> int:
    """
    Bandingkan rata-rata volume 7 hari bursa vs 30 hari bursa.

    Args:
        df: DataFrame dengan kolom 'volume', diurutkan ascending

    Returns:
        Skor integer antara -2 dan +2
    """
    if "volume" not in df.columns or len(df) < 30:
        return 0

    vol   = pd.to_numeric(df["volume"], errors="coerce").fillna(0).values
    avg7  = float(np.mean(vol[-7:]))
    avg30 = float(np.mean(vol[-30:]))

    if avg30 == 0:
        return 0

    ratio = avg7 / avg30

    if ratio >= 2.0:
        return 2
    elif ratio > 1.0:
        return 1
    elif ratio == 1.0:
        return 0
    elif (1.0 / ratio) >= 2.0:
        return -2
    else:
        return -1
