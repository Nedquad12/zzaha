"""
cache.py — Simpan dan baca data OHLCV per ticker ke /home/ec2-user/cache/
Format: JSON satu file per ticker  →  {ticker}.json
Cache di-reset total saat /9 dipanggil.
"""

import json
import logging
import os
import shutil
from datetime import datetime
from typing import Optional

import pandas as pd

from config import CACHE_DIR

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _path(ticker: str) -> str:
    return os.path.join(CACHE_DIR, f"{ticker.upper()}.json")


def _ensure_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


# ── Public API ────────────────────────────────────────────────────────────────

def reset_cache():
    """Hapus semua file cache (dipanggil saat /9 dijalankan)."""
    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)
    _ensure_dir()
    logger.info("Cache direset.")


def save(ticker: str, df: pd.DataFrame):
    """
    Simpan DataFrame OHLCV ke cache.
    Kolom yang disimpan: date (ISO string), open, high, low, close, volume
    """
    _ensure_dir()
    records = []
    for _, row in df.iterrows():
        records.append({
            "date":   row["date"].isoformat() if hasattr(row["date"], "isoformat") else str(row["date"]),
            "open":   float(row["open"]),
            "high":   float(row["high"]),
            "low":    float(row["low"]),
            "close":  float(row["close"]),
            "volume": float(row["volume"]),
        })

    payload = {
        "ticker":    ticker.upper(),
        "cached_at": datetime.utcnow().isoformat(),
        "rows":      len(records),
        "data":      records,
    }

    with open(_path(ticker), "w") as f:
        json.dump(payload, f)

    logger.info(f"[{ticker}] Cache disimpan ({len(records)} baris)")


def load(ticker: str) -> Optional[pd.DataFrame]:
    """
    Baca DataFrame OHLCV dari cache.
    Return None jika cache tidak ada.
    """
    path = _path(ticker)
    if not os.path.exists(path):
        return None

    try:
        with open(path, "r") as f:
            payload = json.load(f)

        df = pd.DataFrame(payload["data"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        logger.info(f"[{ticker}] Cache dimuat ({len(df)} baris)")
        return df

    except Exception as e:
        logger.error(f"[{ticker}] Gagal baca cache: {e}")
        return None


def exists(ticker: str) -> bool:
    """Cek apakah cache untuk ticker tersedia."""
    return os.path.exists(_path(ticker))


def list_cached() -> list[str]:
    """Daftar ticker yang sudah ada di cache."""
    if not os.path.exists(CACHE_DIR):
        return []
    return [f.replace(".json", "") for f in os.listdir(CACHE_DIR) if f.endswith(".json")]
