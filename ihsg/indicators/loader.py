"""
indicators/loader.py — Bangun DataFrame time-series per saham dari JSON harian.

Setiap file JSON = 1 hari bursa, berisi semua saham.
Loader ini mengumpulkan data satu saham dari banyak file,
lalu me-rename kolom XLSX → nama standar yang dipakai semua indikator.

Mapping kolom XLSX → standar:
  Kode Saham  → ticker
  Open Price  → open
  Tertinggi   → high
  Terendah    → low
  Penutupan   → close
  Volume      → volume
  Frekuensi   → transactions
  Nilai       → value
  Foreign Buy → foreign_buy
  Foreign Sell→ foreign_sell
"""

import json
import glob
import os
from datetime import date
import pandas as pd

# ── Mapping nama kolom XLSX → nama standar indikator ─────────────────────────
COL_MAP = {
    "Kode Saham":  "ticker",
    "Open Price":  "open",
    "Tertinggi":   "high",
    "Terendah":    "low",
    "Penutupan":   "close",
    "Volume":      "volume",
    "Frekuensi":   "transactions",
    "Nilai":       "value",
    "Sebelumnya":  "prev_close",
    "Selisih":     "change",
    "Foreign Buy": "foreign_buy",
    "Foreign Sell":"foreign_sell",
}

NUMERIC_COLS = [
    "open", "high", "low", "close", "volume", "transactions",
    "value", "prev_close", "change",
    "foreign_buy", "foreign_sell",
]


def _parse_date_from_filename(fname: str):
    """ddmmyy.json → date object. None jika gagal."""
    date_str = os.path.basename(fname).replace(".json", "")
    try:
        if len(date_str) == 6:
            d = int(date_str[:2])
            m = int(date_str[2:4])
            y = 2000 + int(date_str[4:6])
            return date(y, m, d)
    except ValueError:
        pass
    return None


def build_stock_df(stock_code: str, json_dir: str, max_days: int = 60) -> pd.DataFrame | None:
    """
    Kumpulkan history satu saham dari banyak file JSON harian.

    Args:
        stock_code : kode saham, e.g. "BBCA"
        json_dir   : folder berisi file ddmmyy.json
        max_days   : maksimal hari yang diambil (ambil N file terbaru)

    Returns:
        DataFrame dengan kolom standar (open/high/low/close/volume/transactions...),
        diurutkan ascending (hari terlama di baris 0).
        None jika tidak ada data sama sekali.
    """
    pattern = os.path.join(json_dir, "*.json")
    all_files = glob.glob(pattern)

    dated = []
    for f in all_files:
        d = _parse_date_from_filename(f)
        if d:
           dated.append((d, f))
    dated.sort(key=lambda x: x[0])
    files = [f for _, f in dated]
    files = files[-max_days:]

    rows = []
    for fpath in files:
        file_date = _parse_date_from_filename(fpath)
        if file_date is None:
            continue

        try:
            with open(fpath, encoding="utf-8") as f:
                records = json.load(f)
        except Exception:
            continue

        for rec in records:
            kode = str(rec.get("Kode Saham", "")).strip().upper()
            if kode != stock_code.upper():
                continue

            row = {"date": file_date}
            for xlsx_col, std_col in COL_MAP.items():
                row[std_col] = rec.get(xlsx_col, 0)
            rows.append(row)
            break   # satu baris per file

    if not rows:
        return None

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)

    # Pastikan kolom numerik bertipe float
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    return df


def list_available_tickers(json_dir: str) -> list[str]:
    """
    Baca file JSON terbaru dan kembalikan daftar semua kode saham.
    Berguna untuk validasi input.
    """
    pattern = os.path.join(json_dir, "*.json")
    files   = sorted(glob.glob(pattern))
    if not files:
        return []

    latest = files[-1]
    try:
        with open(latest, encoding="utf-8") as f:
            records = json.load(f)
        return sorted(
            str(r.get("Kode Saham", "")).strip().upper()
            for r in records
            if r.get("Kode Saham")
        )
    except Exception:
        return []
