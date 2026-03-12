"""
api.py — Fetch data OHLCV dari Massive.com
1 call per saham, return DataFrame siap pakai
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests

from config import MASSIVE_API_KEY, MASSIVE_BASE_URL, HISTORY_DAYS

logger = logging.getLogger(__name__)


def fetch_ohlcv(ticker: str, days: int = HISTORY_DAYS) -> Optional[pd.DataFrame]:
    """
    Ambil data OHLCV historis dari Massive.com.

    Endpoint: GET /v2/aggs/ticker/{ticker}/range/1/day/{from}/{to}

    Returns:
        DataFrame dengan kolom: date, open, high, low, close, volume, transactions
        None jika gagal atau data kosong
    """
    end_date   = datetime.today()
    # Buffer kalender agar dapat tepat `days` hari bursa
    start_date = end_date - timedelta(days=int(days * 1.5))

    url = (
        f"{MASSIVE_BASE_URL}/aggs/ticker/{ticker}/range/1/day"
        f"/{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"
    )
    params = {
        "adjusted": "true",
        "sort":     "asc",
        "limit":    50000,
        "apiKey":   MASSIVE_API_KEY,
    }

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        if not results:
            logger.warning(f"[{ticker}] Tidak ada data dari API")
            return None

        df = pd.DataFrame(results).rename(columns={
            "t": "timestamp",
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume",
            "n": "transactions",   # ← jumlah transaksi per hari
        })
        df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df.sort_values("date").reset_index(drop=True)

        # Pastikan kolom transactions ada (tidak semua ticker mungkin punya)
        if "transactions" not in df.columns:
            df["transactions"] = 0

        # Ambil tepat `days` hari bursa terakhir
        df = df.tail(days).reset_index(drop=True)

        logger.info(f"[{ticker}] {len(df)} hari data berhasil diambil")
        return df

    except requests.exceptions.HTTPError as e:
        logger.error(f"[{ticker}] HTTP error: {e}")
    except requests.exceptions.Timeout:
        logger.error(f"[{ticker}] Request timeout")
    except Exception as e:
        logger.error(f"[{ticker}] Error tidak terduga: {e}")

    return None
