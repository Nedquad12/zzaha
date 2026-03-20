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
    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)
    _ensure_dir()
    logger.info("Cache direset.")


def save(ticker: str, df: pd.DataFrame):
    _ensure_dir()
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
        "ticker":    ticker.upper(),
        "cached_at": datetime.utcnow().isoformat(),
        "rows":      len(records),
        "data":      records,
    }

    with open(_path(ticker), "w") as f:
        json.dump(payload, f)

    logger.info(f"[{ticker}] Cache disimpan ({len(records)} baris)")


def load(ticker: str) -> Optional[pd.DataFrame]:
    path = _path(ticker)
    if not os.path.exists(path):
        return None

    try:
        with open(path, "r") as f:
            payload = json.load(f)

        df = pd.DataFrame(payload["data"])
        df["date"] = pd.to_datetime(df["date"])

        # Backward-compat: cache lama mungkin belum punya kolom transactions
        if "transactions" not in df.columns:
            df["transactions"] = 0

        df = df.sort_values("date").reset_index(drop=True)
        logger.info(f"[{ticker}] Cache dimuat ({len(df)} baris)")
        return df

    except Exception as e:
        logger.error(f"[{ticker}] Gagal baca cache: {e}")
        return None


def exists(ticker: str) -> bool:
    return os.path.exists(_path(ticker))


def list_cached() -> list[str]:
    if not os.path.exists(CACHE_DIR):
        return []
    return [f.replace(".json", "") for f in os.listdir(CACHE_DIR) if f.endswith(".json")]
