"""
forex_api.py — Fetch data OHLCV End-of-Day untuk forex dari Massive.com

Perbedaan dengan api.py (saham):
  - Ticker prefix  : "C:AUDUSD" bukan "AUDUSD"
  - Endpoint       : sama (/aggs/ticker/{symbol}/range/1/day/...)
  - Tidak ada field transactions → default 0
  - Tidak ada adjusted=true (tidak relevan untuk forex)
  - Data EOD (paket gratis)
"""

import logging
from datetime import datetime, timedelta, date
from typing import Optional

import pandas as pd
import requests

from config import MASSIVE_API_KEY, MASSIVE_BASE_URL, FOREX_HISTORY_DAYS

logger = logging.getLogger(__name__)


def _forex_symbol(pair: str) -> str:
    """
    Konversi nama pair ke format Massive.com.
    "AUDUSD" → "C:AUDUSD"
    "C:AUDUSD" → "C:AUDUSD"  (idempoten)
    """
    pair = pair.upper().strip()
    if not pair.startswith("C:"):
        return f"C:{pair}"
    return pair


def _latest_forex_day() -> date:
    """
    Kembalikan tanggal EOD forex terbaru yang aman dipakai.
    Forex tutup akhir pekan (Sabtu-Minggu), mundur ke Jumat kalau perlu.
    Data EOD biasanya tersedia H+1 pagi.
    """
    today = datetime.utcnow().date()
    # Pakai kemarin sebagai target aman
    target = today - timedelta(days=1)
    # Mundur kalau weekend
    while target.weekday() >= 5:  # 5=Sabtu, 6=Minggu
        target -= timedelta(days=1)
    return target


def fetch_forex_ohlcv(pair: str, days: int = FOREX_HISTORY_DAYS) -> Optional[pd.DataFrame]:
    """
    Ambil data OHLCV historis EOD untuk satu pasangan forex dari Massive.com.

    Args:
        pair : nama pair, e.g. "AUDUSD" atau "C:AUDUSD"
        days : jumlah hari historis yang diminta (default dari config)

    Returns:
        DataFrame dengan kolom: date, open, high, low, close, volume, transactions
        None jika gagal atau data tidak cukup
    """
    symbol   = _forex_symbol(pair)
    end_date = _latest_forex_day()
    # Minta lebih banyak untuk kompensasi weekend/holiday
    start_date = end_date - timedelta(days=int(days * 1.6))

    url = (
        f"{MASSIVE_BASE_URL}/aggs/ticker/{symbol}/range/1/day/"
        f"{start_date.isoformat()}/{end_date.isoformat()}"
    )
    params = {
        "sort":   "asc",
        "limit":  50000,
        "apiKey": MASSIVE_API_KEY,
    }

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.error(f"[{symbol}] Request error: {e}")
        return None
    except Exception as e:
        logger.error(f"[{symbol}] Parse error: {e}")
        return None

    results = data.get("results") or data.get("results", [])
    if not results:
        logger.warning(f"[{symbol}] Tidak ada hasil dari API. Status: {data.get('status')}")
        return None

    records = []
    for bar in results:
        try:
            records.append({
                "date":         pd.to_datetime(bar["t"], unit="ms"),
                "open":         float(bar.get("o", 0)),
                "high":         float(bar.get("h", 0)),
                "low":          float(bar.get("l", 0)),
                "close":        float(bar.get("c", 0)),
                "volume":       float(bar.get("v", 0)),
                "transactions": int(bar.get("n", 0)),
            })
        except (KeyError, ValueError) as e:
            logger.warning(f"[{symbol}] Skip bar karena error: {e}")
            continue

    if not records:
        logger.warning(f"[{symbol}] Tidak ada bar valid setelah parsing.")
        return None

    df = pd.DataFrame(records)
    df = df.sort_values("date").reset_index(drop=True)

    # Ambil N bar terakhir sesuai days
    if len(df) > days:
        df = df.iloc[-days:].reset_index(drop=True)

    logger.info(f"[{symbol}] Fetch selesai: {len(df)} bar, terakhir {df['date'].iloc[-1].date()}")
    return df
