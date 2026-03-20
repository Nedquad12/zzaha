"""
api.py — Fetch data OHLCV dari Massive.com
1 call per saham, return DataFrame siap pakai
"""

import logging
from datetime import datetime, timedelta, date
from typing import Optional, Tuple

import pandas as pd
import pytz
import requests

from config import MASSIVE_API_KEY, MASSIVE_BASE_URL, HISTORY_DAYS

logger = logging.getLogger(__name__)

SGT = pytz.timezone("Asia/Singapore")
ET  = pytz.timezone("America/New_York")


def _latest_trading_day() -> date:
    """
    Kembalikan hari bursa terakhir yang datanya sudah tersedia di API.

    Logika:
      - NYSE tutup jam 4 PM ET = jam 5 AM SGT hari berikutnya
      - Kalau sekarang SGT sudah lewat jam 5 AM → data kemarin (ET) tersedia
      - Kalau belum jam 5 AM SGT → data 2 hari lalu yang aman dipakai
      - Kalau hari ini ET adalah Sabtu/Minggu → mundur ke Jumat
    """
    now_et  = datetime.now(ET)
    now_sgt = datetime.now(SGT)

    # Market sudah tutup dan data sudah tersedia kalau SGT sudah > 05:00
    market_settled = now_sgt.hour >= 5

    if market_settled:
        # Data EOD kemarin ET sudah tersedia
        target_et = now_et.date() - timedelta(days=1)
    else:
        # Terlalu pagi, ambil 2 hari lalu untuk aman
        target_et = now_et.date() - timedelta(days=2)

    # Mundur kalau weekend
    while target_et.weekday() >= 5:  # 5=Sabtu, 6=Minggu
        target_et -= timedelta(days=1)

    return target_et


def check_data_freshness(df: pd.DataFrame) -> Tuple[bool, str]:
    """
    Cek apakah candle terakhir di df adalah hari bursa terbaru yang diharapkan.

    Returns:
        (is_fresh, warning_msg)
        is_fresh=True  → data sudah up-to-date
        is_fresh=False → data tertinggal, sertakan warning_msg ke Telegram
    """
    expected = _latest_trading_day()
    actual   = df["date"].iloc[-1].date()

    if actual >= expected:
        return True, ""

    # Hitung selisih hari bursa (kasar)
    delta_days = (expected - actual).days
    # Kurangi weekend di rentang tersebut
    trading_days_behind = sum(
        1 for i in range(1, delta_days + 1)
        if (actual + timedelta(days=i)).weekday() < 5
    )

    msg = (
        f"⚠️ <b>Data tidak terkini!</b>\n"
        f"  Candle terakhir : <code>{actual}</code>\n"
        f"  Seharusnya      : <code>{expected}</code>\n"
        f"  Tertinggal      : <b>{trading_days_behind} hari bursa</b>\n\n"
        f"Kemungkinan penyebab:\n"
        f"  • /9 dijalankan sebelum jam 05:00 SGT\n"
        f"  • API belum publish data EOD\n"
        f"  • Subscription API bermasalah"
    )
    return False, msg


def fetch_ohlcv(ticker: str, days: int = HISTORY_DAYS) -> Optional[pd.DataFrame]:
    """
    Ambil data OHLCV historis dari Massive.com.

    Endpoint: GET /v2/aggs/ticker/{ticker}/range/1/day/{from}/{to}

    Returns:
        DataFrame dengan kolom: date, open, high, low, close, volume, transactions
        None jika gagal atau data kosong
    """
    # Pakai ET timezone supaya end_date selalu sesuai kalender US
    now_et     = datetime.now(ET)
    end_date   = now_et.date()
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
            "n": "transactions",
        })
        df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df.sort_values("date").reset_index(drop=True)

        if "transactions" not in df.columns:
            df["transactions"] = 0

        df = df.tail(days).reset_index(drop=True)

        logger.info(f"[{ticker}] {len(df)} hari data, candle terakhir: {df['date'].iloc[-1].date()}")
        return df

    except requests.exceptions.HTTPError as e:
        logger.error(f"[{ticker}] HTTP error: {e}")
    except requests.exceptions.Timeout:
        logger.error(f"[{ticker}] Request timeout")
    except Exception as e:
        logger.error(f"[{ticker}] Error tidak terduga: {e}")

    return None