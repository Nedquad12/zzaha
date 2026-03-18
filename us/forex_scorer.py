"""
forex_scorer.py — Hitung semua skor untuk satu pasangan forex

Sama dengan scorer.py saham, tapi:
  - Load weight dari folder khusus forex: /home/ec2-user/us/forex_weights/
  - Scorer tetap pakai semua indikator yang sama
  - ML weight otomatis dipakai kalau sudah ada (hasil /ch bt ml di forex)
"""

import os
import json
import logging
from datetime import datetime

import pandas as pd

from indicators import (
    score_vsa, score_rsi, score_macd, score_ma,
    calculate_ip, score_ip, score_fsa, score_vfa, score_wcc,
    score_srst,
)
from config import FOREX_WEIGHTS_DIR

logger = logging.getLogger(__name__)

# Fitur yang dipakai ML (sama dengan saham)
FEATURES = ["vsa", "fsa", "vfa", "wcc", "srst", "rsi", "macd", "ma", "ip_score", "tight"]
DEFAULT_WEIGHTS = {f: 1.0 for f in FEATURES}


# ── Weight helpers ────────────────────────────────────────────────────────────

def _weights_path(pair: str) -> str:
    clean = pair.upper().strip().removeprefix("C:")
    return os.path.join(FOREX_WEIGHTS_DIR, f"{clean}.json")


def load_forex_weights(pair: str) -> dict:
    """
    Load weight untuk pair forex.
    Kalau belum ada file weight → pakai default (semua 1.0).
    """
    path = _weights_path(pair)
    if not os.path.exists(path):
        return dict(DEFAULT_WEIGHTS)
    try:
        with open(path, "r") as f:
            data = json.load(f)
        weights = data.get("weights", DEFAULT_WEIGHTS)
        # Pastikan semua fitur ada
        return {f: float(weights.get(f, 1.0)) for f in FEATURES}
    except Exception as e:
        logger.warning(f"[{pair}] Gagal baca forex weight: {e}, pakai default")
        return dict(DEFAULT_WEIGHTS)


def save_forex_weights(pair: str, weights: dict):
    """Simpan weight hasil ML untuk pair forex."""
    os.makedirs(FOREX_WEIGHTS_DIR, exist_ok=True)
    clean = pair.upper().strip().removeprefix("C:")
    payload = {
        "pair":       clean,
        "updated_at": datetime.utcnow().isoformat(),
        "weights":    weights,
    }
    with open(_weights_path(pair), "w") as f:
        json.dump(payload, f, indent=2)
    logger.info(f"[{clean}] Forex weight disimpan.")


def apply_forex_weights(scores: dict, weights: dict) -> float:
    """Hitung weighted total score."""
    total = 0.0
    for feat in FEATURES:
        score  = scores.get(feat, 0)
        weight = weights.get(feat, 1.0)
        total += score * weight
    return total


def get_forex_weights_info(pair: str) -> dict:
    """Info weight: apakah sudah di-ML atau masih default."""
    path = _weights_path(pair)
    if not os.path.exists(path):
        return {"is_default": True, "updated_at": None}
    try:
        with open(path, "r") as f:
            data = json.load(f)
        weights = data.get("weights", {})
        is_default = all(abs(weights.get(f, 1.0) - 1.0) < 0.001 for f in FEATURES)
        return {
            "is_default": is_default,
            "updated_at": data.get("updated_at"),
            "weights":    weights,
        }
    except Exception:
        return {"is_default": True, "updated_at": None}


# ── Main scorer ───────────────────────────────────────────────────────────────

def calculate_forex_scores(pair: str, df: pd.DataFrame, tight_score: int = 0) -> dict:
    """
    Hitung semua skor untuk satu pasangan forex dari DataFrame OHLCV.

    Args:
        pair        : nama pair (e.g. "AUDUSD" atau "C:AUDUSD")
        df          : DataFrame dengan kolom date/open/high/low/close/volume/transactions
        tight_score : skor VT/T dari forex_tight.py, default 0

    Returns:
        Dict berisi semua skor dan metadata
    """
    clean = pair.upper().strip().removeprefix("C:")

    vsa    = score_vsa(df)
    rsi    = score_rsi(df)
    macd   = score_macd(df)
    ma     = score_ma(df)
    ip_raw = calculate_ip(df)
    ip_pts = score_ip(ip_raw)
    fsa    = score_fsa(df)
    vfa    = score_vfa(df)
    wcc    = score_wcc(df)
    srst   = score_srst(df)

    scores = {
        "vsa":      vsa,
        "fsa":      fsa,
        "vfa":      vfa,
        "wcc":      wcc,
        "srst":     srst,
        "rsi":      rsi,
        "macd":     macd,
        "ma":       ma,
        "ip_score": ip_pts,
        "tight":    tight_score,
    }

    weights = load_forex_weights(clean)
    total   = apply_forex_weights(scores, weights)

    price  = float(df["close"].iloc[-1])
    prev   = float(df["close"].iloc[-2]) if len(df) > 1 else price
    change = ((price - prev) / prev * 100) if prev != 0 else 0.0

    return {
        "ticker":   clean,       # nama pair, untuk kompatibilitas dengan formatter saham
        "pair":     clean,
        "date":     datetime.today().strftime("%Y-%m-%d"),
        "price":    round(price,  6),
        "change":   round(change, 4),
        # skor per indikator
        "vsa":      vsa,
        "fsa":      fsa,
        "vfa":      vfa,
        "wcc":      wcc,
        "srst":     srst,
        "rsi":      rsi,
        "macd":     macd,
        "ma":       ma,
        "ip_raw":   round(ip_raw, 4),
        "ip_score": ip_pts,
        "tight":    tight_score,
        # total weighted
        "total":    round(total, 4),
    }
