"""
storage.py — Simpan hasil ke file xlsx harian
"""

import os
import logging
from datetime import datetime

import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment

from config import OUTPUT_DIR

logger = logging.getLogger(__name__)

HEADERS = [
    "Ticker", "Date", "Price", "Change%",
    "VSA", "FSA", "VFA", "WCC", "SRST", "RSI", "MACD", "MA",
    "IP Raw", "IP Score", "Tight", "Total Score",
]

COLOR_HEADER = "1F4E79"
COLOR_GREEN  = "C6EFCE"
COLOR_RED    = "FFC7CE"
COLOR_WHITE  = "FFFFFF"


def _row_from_result(r: dict) -> list:
    return [
        r["ticker"], r["date"], r["price"], r["change"],
        r["vsa"], r.get("fsa", 0), r.get("vfa", 0), r.get("wcc", 0), r.get("srst", 0),
        r["rsi"], r["macd"], r["ma"],
        r["ip_raw"], r["ip_score"], r.get("tight", 0), r["total"],
    ]


def save_to_xlsx(results: list[dict]) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    today    = datetime.today().strftime("%Y-%m-%d")
    filepath = os.path.join(OUTPUT_DIR, f"score_{today}.xlsx")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Stock Scores"

    hdr_fill = PatternFill(start_color=COLOR_HEADER, end_color=COLOR_HEADER, fill_type="solid")
    hdr_font = Font(color=COLOR_WHITE, bold=True)
    center   = Alignment(horizontal="center")

    for col, h in enumerate(HEADERS, 1):
        cell           = ws.cell(row=1, column=col, value=h)
        cell.fill      = hdr_fill
        cell.font      = hdr_font
        cell.alignment = center

    green_fill = PatternFill(start_color=COLOR_GREEN, end_color=COLOR_GREEN, fill_type="solid")
    red_fill   = PatternFill(start_color=COLOR_RED,   end_color=COLOR_RED,   fill_type="solid")

    for row_idx, r in enumerate(results, 2):
        for col, val in enumerate(_row_from_result(r), 1):
            cell           = ws.cell(row=row_idx, column=col, value=val)
            cell.alignment = center

        if r["total"] > 4:
            fill = green_fill
        elif r["total"] < -4:
            fill = red_fill
        else:
            fill = None

        if fill:
            for col in range(1, len(HEADERS) + 1):
                ws.cell(row=row_idx, column=col).fill = fill

    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = max_len + 4

    wb.save(filepath)
    logger.info(f"Hasil disimpan: {filepath}")
    return filepath
