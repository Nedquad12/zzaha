"""
indicators/mgn.py — Margin Volume Trend

Bandingkan rata-rata Volume margin 5 hari terbaru vs 5 hari sebelumnya.

Logika:
  avg_recent > avg_prev  →  -1  (margin meningkat, tekanan jual / spekulatif)
  avg_recent < avg_prev  →  +1  (margin menurun, tekanan berkurang)
  sama / data kurang     →   0

Kolom yang dibutuhkan: DataFrame dari margin_df dengan kolom 'Volume' dan 'Date'
Data di-cache saat startup / reload oleh cache_manager.py
"""

import logging
import numpy as np

logger = logging.getLogger(__name__)

# ── Public: skor dari cache ────────────────────────────────────────────────────

def score_mgn(ticker: str, mgn_cache: dict) -> int:
    """
    Hitung skor margin berdasarkan cache yang sudah dibangun.

    Args:
        ticker    : kode saham, e.g. "BBCA"
        mgn_cache : dict {ticker: {"avg_recent": float, "avg_prev": float}}

    Returns:
        +1  jika margin volume turun (positif)
        -1  jika margin volume naik (negatif)
         0  jika sama / tidak ada data
    """
    entry = mgn_cache.get(ticker.upper())
    if entry is None:
        return 0

    avg_recent = entry.get("avg_recent", 0.0)
    avg_prev   = entry.get("avg_prev",   0.0)

    if avg_recent == 0 and avg_prev == 0:
        return 0
    if avg_recent > avg_prev:
        return -1
    if avg_recent < avg_prev:
        return 1
    return 0


def get_mgn_detail(ticker: str, mgn_cache: dict) -> dict:
    """Return detail untuk debugging / laporan."""
    entry = mgn_cache.get(ticker.upper(), {})
    avg_recent = entry.get("avg_recent", 0.0)
    avg_prev   = entry.get("avg_prev",   0.0)
    return {
        "avg_recent": round(avg_recent, 0),
        "avg_prev":   round(avg_prev,   0),
        "score":      score_mgn(ticker, mgn_cache),
    }


# ── Builder: dipanggil saat startup / reload ───────────────────────────────────

def build_mgn_cache(margin_folder: str) -> dict:
    """
    Baca semua file Excel margin, bangun cache per ticker.

    Struktur cache:
        {
          "BBCA": {"avg_recent": 1200000.0, "avg_prev": 900000.0},
          ...
        }

    Args:
        margin_folder : path ke folder berisi ddmmyy.xlsx margin

    Returns:
        dict cache (kosong jika folder / file tidak ditemukan)
    """
    import os
    import glob
    import pandas as pd
    from datetime import datetime

    cache: dict = {}

    if not os.path.exists(margin_folder):
        logger.warning(f"[MGN] Folder tidak ditemukan: {margin_folder}")
        return cache

    excel_files = sorted(
        glob.glob(os.path.join(margin_folder, "*.xlsx")) +
        glob.glob(os.path.join(margin_folder, "*.xls"))
    )

    if not excel_files:
        logger.warning("[MGN] Tidak ada file Excel di margin folder.")
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
            logger.warning(f"[MGN] Gagal baca {fp}: {e}")
            continue

    if not dataframes:
        logger.warning("[MGN] Semua file gagal dibaca.")
        return cache

    combined = pd.concat(dataframes, ignore_index=True)
    combined  = combined.sort_values("Date", ascending=True)

    if "Kode Saham" not in combined.columns or "Volume" not in combined.columns:
        logger.error("[MGN] Kolom 'Kode Saham' atau 'Volume' tidak ditemukan.")
        return cache

    combined["Kode Saham"] = combined["Kode Saham"].astype(str).str.strip().str.upper()
    combined["Volume"]     = pd.to_numeric(combined["Volume"], errors="coerce").fillna(0)

    # Ambil 10 hari terakhir per ticker
    for ticker, grp in combined.groupby("Kode Saham"):
        daily = (
            grp.groupby("Date")["Volume"]
            .sum()
            .sort_index()
        )

        if len(daily) < 10:
            # Data kurang dari 10 hari → skip
            continue

        recent_5 = daily.iloc[-5:].values    # 5 hari terbaru
        prev_5   = daily.iloc[-10:-5].values # 5 hari sebelumnya

        avg_recent = float(np.mean(recent_5))
        avg_prev   = float(np.mean(prev_5))

        cache[ticker] = {
            "avg_recent": avg_recent,
            "avg_prev":   avg_prev,
        }

    logger.info(f"[MGN] Cache dibangun: {len(cache)} ticker")
    return cache
