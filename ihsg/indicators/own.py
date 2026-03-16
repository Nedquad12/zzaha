"""
indicators/own.py — Ownership Retail Trend (Local ID + Foreign ID)

Bandingkan total kepemilikan ritel (Local ID + Foreign ID) bulan terbaru
vs bulan sebelumnya.

Logika:
  total_new > total_old  →  -1  (ritel naik, distribusi ke ritel = negatif)
  total_new < total_old  →  +1  (ritel turun, akumulasi institusi = positif)
  sama / tidak ada       →   0

Data di-cache saat startup / reload.
"""

import logging
import os
import glob
import pandas as pd

logger = logging.getLogger(__name__)


# ── Public: skor dari cache ────────────────────────────────────────────────────

def score_own(ticker: str, own_cache: dict) -> int:
    """
    Hitung skor ownership ritel berdasarkan cache.

    Args:
        ticker    : kode saham, e.g. "BBCA"
        own_cache : dict {ticker: {"total_new": float, "total_old": float}}

    Returns:
        +1  total ritel turun (positif, institusi akumulasi)
        -1  total ritel naik  (negatif, distribusi ke ritel)
         0  tidak ada data / tidak berubah
    """
    entry = own_cache.get(ticker.upper())
    if entry is None:
        return 0

    total_new = entry.get("total_new", 0.0)
    total_old = entry.get("total_old", 0.0)

    if total_new == total_old:
        return 0
    return -1 if total_new > total_old else 1


def get_own_detail(ticker: str, own_cache: dict) -> dict:
    """Return detail untuk debugging / laporan."""
    entry = own_cache.get(ticker.upper(), {})
    total_new = entry.get("total_new", 0.0)
    total_old = entry.get("total_old", 0.0)
    return {
        "local_id_new":   entry.get("local_id_new",   0.0),
        "foreign_id_new": entry.get("foreign_id_new", 0.0),
        "local_id_old":   entry.get("local_id_old",   0.0),
        "foreign_id_old": entry.get("foreign_id_old", 0.0),
        "total_new":      total_new,
        "total_old":      total_old,
        "score":          score_own(ticker, own_cache),
    }


# ── Builder: dipanggil saat startup / reload ───────────────────────────────────

def build_own_cache(data_folder: str) -> dict:
    """
    Baca semua file Excel ownership (folder /database/data),
    bangun cache per ticker.

    Struktur cache:
        {
          "BBCA": {
              "local_id_new":   500_000_000.0,
              "foreign_id_new": 200_000_000.0,
              "local_id_old":   480_000_000.0,
              "foreign_id_old": 210_000_000.0,
              "total_new":      700_000_000.0,
              "total_old":      690_000_000.0,
          },
          ...
        }

    Args:
        data_folder : path ke folder berisi file Excel kepemilikan bulanan

    Returns:
        dict cache (kosong jika folder / file tidak ditemukan)
    """
    cache: dict = {}

    if not os.path.exists(data_folder):
        logger.warning(f"[OWN] Folder tidak ditemukan: {data_folder}")
        return cache

    excel_files = []
    for ext in ("*.xlsx", "*.xls", "*.XLSX", "*.XLS"):
        excel_files.extend(glob.glob(os.path.join(data_folder, ext)))

    if not excel_files:
        logger.warning("[OWN] Tidak ada file Excel di data folder.")
        return cache

    dfs = []
    for fp in sorted(excel_files):
        try:
            df = pd.read_excel(fp)
            dfs.append(df)
        except Exception as e:
            logger.warning(f"[OWN] Gagal baca {fp}: {e}")
            continue

    if not dfs:
        logger.warning("[OWN] Semua file gagal dibaca.")
        return cache

    combined = pd.concat(dfs, ignore_index=True)
    combined["Date"] = pd.to_datetime(combined.get("Date", None), errors="coerce")
    combined = combined.dropna(subset=["Date"])

    if "Code" not in combined.columns:
        logger.error("[OWN] Kolom 'Code' tidak ditemukan.")
        return cache

    combined["Code"] = combined["Code"].astype(str).str.strip().str.upper()

    # Pastikan kolom Local ID dan Foreign ID ada
    local_id_col   = "Local ID"
    foreign_id_col = "Foreign ID"

    if local_id_col not in combined.columns or foreign_id_col not in combined.columns:
        logger.error(f"[OWN] Kolom '{local_id_col}' atau '{foreign_id_col}' tidak ditemukan.")
        return cache

    combined[local_id_col]   = pd.to_numeric(combined[local_id_col],   errors="coerce").fillna(0)
    combined[foreign_id_col] = pd.to_numeric(combined[foreign_id_col], errors="coerce").fillna(0)

    # Ambil 2 bulan terakhir per ticker
    combined = combined.sort_values("Date", ascending=True)

    for ticker, grp in combined.groupby("Code"):
        # Deduplikasi per bulan (ambil baris terakhir per tanggal)
        grp = grp.drop_duplicates(subset=["Date"], keep="last").sort_values("Date")

        if len(grp) < 2:
            continue

        row_new = grp.iloc[-1]
        row_old = grp.iloc[-2]

        local_id_new   = float(row_new[local_id_col])
        foreign_id_new = float(row_new[foreign_id_col])
        local_id_old   = float(row_old[local_id_col])
        foreign_id_old = float(row_old[foreign_id_col])

        total_new = local_id_new + foreign_id_new
        total_old = local_id_old + foreign_id_old

        cache[ticker] = {
            "local_id_new":   local_id_new,
            "foreign_id_new": foreign_id_new,
            "local_id_old":   local_id_old,
            "foreign_id_old": foreign_id_old,
            "total_new":      total_new,
            "total_old":      total_old,
        }

    logger.info(f"[OWN] Cache dibangun: {len(cache)} ticker")
    return cache
