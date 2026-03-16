"""
indicators/fsa.py — Frekuensi Super Analysis

Kolom yang dibutuhkan: 'transactions'  (= Frekuensi di XLSX, dinormalise loader.py)

Logika:
  avg7 >= 2x avg30  →  +2
  avg7 > avg30       →  +1
  avg7 == avg30      →   0
  avg7 < avg30       →  -1
"""

import numpy as np
import pandas as pd


def score_fsa(df: pd.DataFrame) -> int:
    if "transactions" not in df.columns or len(df) < 30:
        return 0

    txn   = pd.to_numeric(df["transactions"], errors="coerce").fillna(0).values
    avg7  = float(np.mean(txn[-7:]))
    avg30 = float(np.mean(txn[-30:]))

    if avg30 == 0:
        return 0

    ratio = avg7 / avg30

    if ratio >= 2.0:
        return 2
    elif ratio > 1.0:
        return 1
    elif ratio == 1.0:
        return 0
    else:
        return -1
