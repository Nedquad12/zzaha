"""
forex_cache.py — Simpan dan baca data OHLCV forex ke /home/ec2-user/cache_forex/

Struktur file  : {PAIR}.json   (e.g. AUDUSD.json)
Pair disimpan  : tanpa prefix C: agar nama file bersih
Cache di-reset : setiap kali /9 dijalankan (sama dengan cache saham)
"""

import json
import logging
import os
import shutil
from datetime import datetime
from typing import Optional

import pandas as pd

from config import FOREX_CACHE_DIR

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean_pair(pair: str) -> str:
    """Hapus prefix C: dan uppercase. 'C:AUDUSD' → 'AUDUSD'"""
    return pair.upper().strip().removeprefix("C:")


def _path(pair: str) -> str:
    return os.path.join(FOREX_CACHE_DIR, f"{_clean_pair(pair)}.json")


def _ensure_dir():
    os.makedirs(FOREX_CACHE_DIR, exist_ok=True)


# ── Public API ────────────────────────────────────────────────────────────────

def reset_forex_cache():
    """Hapus semua file cache forex (dipanggil saat /9 dijalankan)."""
    if os.path.exists(FOREX_CACHE_DIR):
        shutil.rmtree(FOREX_CACHE_DIR)
    _ensure_dir()
    logger.info("Forex cache direset.")


def save(pair: str, df: pd.DataFrame):
    """
    Simpan DataFrame OHLCV forex ke cache.
    Kolom yang disimpan: date (ISO string), open, high, low, close, volume, transactions
    """
    _ensure_dir()
    clean = _clean_pair(pair)
    records = []
    for _, row in df.iterrows():
        records.append({
            "date":         row["date"].isoformat() if hasattr(row["date"], "isoformat") else str(row["date"]),
            "open":         float(row["open"]),
            "high":         float(row["high"]),
            "low":          float(row["low"]),
            "close":        float(row["close"]),
            "volume":       float(row["volume"]),
            "transactions": int(row["transactions"]) if "transactions" in row.index else 0,
        })

    payload = {
        "pair":      clean,
        "cached_at": datetime.utcnow().isoformat(),
        "rows":      len(records),
        "data":      records,
    }

    with open(_path(pair), "w") as f:
        json.dump(payload, f)

    logger.info(f"[{clean}] Forex cache disimpan ({len(records)} baris)")


def load(pair: str) -> Optional[pd.DataFrame]:
    """
    Baca DataFrame OHLCV forex dari cache.
    Return None jika cache tidak ada.
    """
    path = _path(pair)
    if not os.path.exists(path):
        return None

    try:
        with open(path, "r") as f:
            payload = json.load(f)

        df = pd.DataFrame(payload["data"])
        df["date"] = pd.to_datetime(df["date"])

        if "transactions" not in df.columns:
            df["transactions"] = 0

        df = df.sort_values("date").reset_index(drop=True)
        logger.info(f"[{_clean_pair(pair)}] Forex cache dimuat ({len(df)} baris)")
        return df

    except Exception as e:
        logger.error(f"[{_clean_pair(pair)}] Gagal baca forex cache: {e}")
        return None


def exists(pair: str) -> bool:
    """Cek apakah cache untuk pair tersedia."""
    return os.path.exists(_path(pair))


def list_cached() -> list[str]:
    """Daftar pair yang sudah ada di cache forex (tanpa prefix C:)."""
    if not os.path.exists(FOREX_CACHE_DIR):
        return []
    return [
        f.replace(".json", "").upper()
        for f in os.listdir(FOREX_CACHE_DIR)
        if f.endswith(".json")
    ]
