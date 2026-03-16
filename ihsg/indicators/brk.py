"""
indicators/brk.py — BlackRock Holdings Trend

Bandingkan Quantity Total terbaru vs sebelumnya untuk satu ticker.

Logika:
  latest > previous  →  +1  (BlackRock beli / tambah)
  latest < previous  →  -1  (BlackRock jual / kurangi)
  sama / tidak ada   →   0

Data di-cache saat startup / reload.
"""

import logging
import os
import glob
import pandas as pd
from datetime import datetime

logger = logging.getLogger(__name__)


# ── Public: skor dari cache ────────────────────────────────────────────────────

def score_brk(ticker: str, brk_cache: dict) -> int:
    """
    Hitung skor BlackRock berdasarkan cache.

    Args:
        ticker    : kode saham, e.g. "BBCA"
        brk_cache : dict {ticker: {"latest_qty": float, "prev_qty": float}}

    Returns:
        +1  BlackRock beli / tambah
        -1  BlackRock jual / kurangi
         0  tidak ada data / tidak berubah
    """
    entry = brk_cache.get(ticker.upper())
    if entry is None:
        return 0

    latest = entry.get("latest_qty", 0.0)
    prev   = entry.get("prev_qty",   0.0)

    if latest == prev:
        return 0
    return 1 if latest > prev else -1


def get_brk_detail(ticker: str, brk_cache: dict) -> dict:
    """Return detail untuk debugging / laporan."""
    entry = brk_cache.get(ticker.upper(), {})
    latest = entry.get("latest_qty", 0.0)
    prev   = entry.get("prev_qty",   0.0)
    return {
        "latest_qty":  latest,
        "prev_qty":    prev,
        "latest_date": entry.get("latest_date", "-"),
        "prev_date":   entry.get("prev_date",   "-"),
        "score":       score_brk(ticker, brk_cache),
    }


# ── Builder: dipanggil saat startup / reload ───────────────────────────────────

def build_brk_cache(blackrock_folder: str) -> dict:
    """
    Baca semua file Excel BlackRock Indonesia, bangun cache per ticker.

    Struktur cache:
        {
          "BBCA": {
              "latest_qty":  1_000_000.0,
              "prev_qty":      900_000.0,
              "latest_date": "2025-03-10",
              "prev_date":   "2025-02-10",
          },
          ...
        }

    Args:
        blackrock_folder : path ke folder berisi ddmmyy.xlsx BlackRock

    Returns:
        dict cache (kosong jika folder / file tidak ditemukan)
    """
    cache: dict = {}

    if not os.path.exists(blackrock_folder):
        logger.warning(f"[BRK] Folder tidak ditemukan: {blackrock_folder}")
        return cache

    excel_files = sorted(
        glob.glob(os.path.join(blackrock_folder, "*.xlsx")) +
        glob.glob(os.path.join(blackrock_folder, "*.xls"))
    )

    if not excel_files:
        logger.warning("[BRK] Tidak ada file Excel di BlackRock folder.")
        return cache

    dataframes = []
    for fp in excel_files:
        try:
            filename = os.path.basename(fp)
            date_str = filename.split(".")[0]
            if len(date_str) != 6:
                continue
            day   = int(date_str[0:2])
            month = int(date_str[2:4])
            year  = 2000 + int(date_str[4:6])
            file_date = datetime(year, month, day)

            df = pd.read_excel(fp)
            df["Date"] = file_date
            dataframes.append(df)
        except Exception as e:
            logger.warning(f"[BRK] Gagal baca {fp}: {e}")
            continue

    if not dataframes:
        logger.warning("[BRK] Semua file gagal dibaca.")
        return cache

    combined = pd.concat(dataframes, ignore_index=True)

    # Pastikan kolom Ticker ada
    if "Ticker" not in combined.columns:
        logger.error("[BRK] Kolom 'Ticker' tidak ditemukan.")
        return cache

    combined["Ticker"] = combined["Ticker"].astype(str).str.strip().str.upper()
    combined = combined[~combined["Ticker"].isin(["", "NAN", "NONE"])]

    if "Quantity Total" not in combined.columns:
        logger.error("[BRK] Kolom 'Quantity Total' tidak ditemukan.")
        return cache

    combined["Quantity Total"] = pd.to_numeric(
        combined["Quantity Total"], errors="coerce"
    ).fillna(0)

    for ticker, grp in combined.groupby("Ticker"):
        daily = (
            grp.groupby("Date")["Quantity Total"]
            .sum()
            .sort_index()
        )

        if len(daily) < 2:
            continue

        latest_date = daily.index[-1]
        prev_date   = daily.index[-2]

        cache[ticker] = {
            "latest_qty":  float(daily.iloc[-1]),
            "prev_qty":    float(daily.iloc[-2]),
            "latest_date": latest_date.strftime("%Y-%m-%d"),
            "prev_date":   prev_date.strftime("%Y-%m-%d"),
        }

    logger.info(f"[BRK] Cache dibangun: {len(cache)} ticker")
    return cache
