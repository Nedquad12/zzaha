"""
forex_score_history.py — Hitung score history 300 bar untuk forex

Sama dengan score_history.py saham, tapi:
  - Simpan ke forex_train.db (bukan train.db)
  - Simpan JSON ke FOREX_500_DIR (bukan OHLCV_500_DIR)
  - Field 'ticker' diisi dengan nama pair (tanpa C:)
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

import pandas as pd

from config import FOREX_500_DIR, SCORE_WARMUP, SCORE_BARS
from indicators import (
    score_vsa, score_rsi, score_macd, score_ma,
    calculate_ip, score_ip, score_fsa, score_vfa, score_wcc,
    score_srst,
)
from forex_train_db import upsert_score_rows, init_forex_db

logger = logging.getLogger(__name__)


def _ensure_dirs():
    os.makedirs(FOREX_500_DIR, exist_ok=True)


def _json_path(pair: str) -> str:
    clean = pair.upper().strip().removeprefix("C:")
    return os.path.join(FOREX_500_DIR, f"{clean}.json")


def _score_single_bar(window_df: pd.DataFrame, tight_score: int = 0) -> dict:
    """Hitung semua skor dari window DataFrame."""
    vsa    = score_vsa(window_df)
    rsi    = score_rsi(window_df)
    macd   = score_macd(window_df)
    ma     = score_ma(window_df)
    ip_raw = calculate_ip(window_df)
    ip_pts = score_ip(ip_raw)
    fsa    = score_fsa(window_df)
    vfa    = score_vfa(window_df)
    wcc    = score_wcc(window_df)
    srst   = score_srst(window_df)

    total = vsa + rsi + macd + ma + ip_pts + tight_score + fsa + vfa + wcc + srst

    return {
        "vsa":      vsa,
        "fsa":      fsa,
        "vfa":      vfa,
        "wcc":      wcc,
        "srst":     srst,
        "rsi":      rsi,
        "macd":     macd,
        "ma":       ma,
        "ip_raw":   round(ip_raw, 6),
        "ip_score": ip_pts,
        "tight":    tight_score,
        "total":    round(total, 2),
    }


def build_forex_score_history(
    pair: str,
    df: pd.DataFrame,
    tight_score: int = 0,
) -> list[dict]:
    """
    Hitung score untuk setiap bar dari SCORE_WARMUP hingga bar terakhir.

    Args:
        pair        : nama pair forex (e.g. "AUDUSD")
        df          : DataFrame OHLCV, diurutkan ascending
        tight_score : tight score statis dari scan_forex_tight()

    Returns:
        list of dict
    """
    clean = pair.upper().strip().removeprefix("C:")
    n = len(df)
    results = []

    start_idx = SCORE_WARMUP

    for i in range(start_idx, n):
        window = df.iloc[: i + 1]
        row    = df.iloc[i]

        date_val = row["date"]
        date_str = date_val.strftime("%Y-%m-%d") if hasattr(date_val, "strftime") else str(date_val)[:10]

        prev_close = float(df.iloc[i - 1]["close"]) if i > 0 else float(row["close"])
        close      = float(row["close"])
        change_pct = ((close - prev_close) / prev_close * 100) if prev_close != 0 else 0.0

        scores = _score_single_bar(window, tight_score)

        entry = {
            "date":         date_str,
            "bar_idx":      i,
            "price":        round(close, 6),
            "open":         round(float(row["open"]),  6),
            "high":         round(float(row["high"]),  6),
            "low":          round(float(row["low"]),   6),
            "volume":       float(row["volume"]),
            "transactions": int(row.get("transactions", 0)),
            "change_pct":   round(change_pct, 6),
            **scores,
        }
        results.append(entry)

    logger.info(f"[{clean}] Forex score history: {len(results)} bar dihitung")
    return results


def save_forex_score_history(pair: str, history: list[dict]):
    """Simpan score history ke JSON di FOREX_500_DIR."""
    _ensure_dirs()
    clean = pair.upper().strip().removeprefix("C:")
    payload = {
        "pair":         clean,
        "generated_at": datetime.utcnow().isoformat(),
        "total_bars":   len(history),
        "data":         history,
    }
    path = _json_path(pair)
    with open(path, "w") as f:
        json.dump(payload, f)
    logger.info(f"[{clean}] Forex JSON disimpan: {path}")


def load_forex_score_history(pair: str) -> Optional[list[dict]]:
    """Baca score history forex dari JSON."""
    path = _json_path(pair)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            payload = json.load(f)
        return payload.get("data", [])
    except Exception as e:
        logger.error(f"[{pair}] Gagal baca forex JSON: {e}")
        return None


def process_and_store_forex(
    pair: str,
    df: pd.DataFrame,
    tight_score: int = 0,
):
    """
    Entry point utama: hitung score history forex, simpan JSON + forex_train.db.

    Args:
        pair        : nama pair (e.g. "AUDUSD")
        df          : DataFrame OHLCV 500 bar
        tight_score : dari scan_forex_tight()
    """
    clean = pair.upper().strip().removeprefix("C:")

    if len(df) < SCORE_WARMUP + 1:
        logger.warning(f"[{clean}] Data tidak cukup untuk score history ({len(df)} bar)")
        return

    history = build_forex_score_history(clean, df, tight_score)
    if not history:
        return

    save_forex_score_history(clean, history)

    # Siapkan rows untuk DB (field 'ticker' = pair)
    db_rows = []
    for h in history:
        db_rows.append({
            "ticker":       clean,
            "date":         h["date"],
            "price":        h["price"],
            "change_pct":   h["change_pct"],
            "open":         h["open"],
            "high":         h["high"],
            "low":          h["low"],
            "volume":       h["volume"],
            "transactions": h["transactions"],
            "vsa":          h["vsa"],
            "fsa":          h["fsa"],
            "vfa":          h["vfa"],
            "wcc":          h["wcc"],
            "srst":         h["srst"],
            "rsi":          h["rsi"],
            "macd":         h["macd"],
            "ma":           h["ma"],
            "ip_raw":       h["ip_raw"],
            "ip_score":     h["ip_score"],
            "tight":        h["tight"],
            "total":        h["total"],
        })

    upsert_score_rows(db_rows)
    logger.info(f"[{clean}] Forex score history tersimpan ke DB: {len(db_rows)} rows")
