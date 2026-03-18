"""
forex_tight.py — Scan Very Tight (VT) dan Tight (T) untuk pasangan forex

Perbedaan dengan tight.py (saham):
  - TIDAK ada filter nilai transaksi (close × volume >= 0.5 miliar)
    karena volume forex tidak representatif seperti saham
  - Baca dari forex_cache, bukan cache saham
  - Nama pair pakai format bersih (tanpa C:)

Logika:
  scan_forex_tight()
    └── per pair:
          1. hitung MA 3/5/10/20 dari close
          2. syarat: close > semua MA (harga di atas semua MA)
          3. hitung jarak close ke semua MA:
               semua < 5%      → masuk vt_list
               semua 5% – 7%  → masuk t_list

  score_forex_tight(pair, vt_set, t_set)
    masuk VT+T → +2
    masuk VT   → +1
    masuk T    → 0
    tidak masuk→ -1
"""

import logging
from typing import Tuple

import numpy as np

import forex_cache

logger = logging.getLogger(__name__)

# ── Threshold ─────────────────────────────────────────────────────────────────
VT_MAX_DIST = 0.05   # < 5%  dari MA
T_MIN_DIST  = 0.05   # 5%
T_MAX_DIST  = 0.07   # 7%
MA_PERIODS  = [3, 5, 10, 20]


def _calc_distances(close: float, closes: list) -> dict:
    """
    Hitung jarak relatif close ke setiap MA.
    Return dict {period: jarak_pct} atau None jika data tidak cukup.
    """
    distances = {}
    for p in MA_PERIODS:
        if len(closes) < p:
            return None
        ma = float(np.mean(closes[-p:]))
        if ma == 0:
            return None
        distances[p] = abs(close - ma) / ma
    return distances


def scan_forex_tight() -> Tuple[list, list]:
    """
    Scan semua pair dari forex cache, pisahkan ke vt_list dan t_list.

    Returns:
        (vt_list, t_list)
        masing-masing list of dict:
          {"pair": str, "close": float, "distances": dict, "ma": dict}
    """
    pairs = forex_cache.list_cached()
    vt_list = []
    t_list  = []

    for pair in pairs:
        df = forex_cache.load(pair)
        if df is None or len(df) < max(MA_PERIODS):
            continue

        closes = df["close"].tolist()
        close  = float(df["close"].iloc[-1])

        # Hitung semua MA
        ma_vals = {}
        for p in MA_PERIODS:
            ma_vals[p] = float(np.mean(closes[-p:]))

        # Syarat: harga di atas semua MA
        if not all(close > ma_vals[p] for p in MA_PERIODS):
            continue

        distances = _calc_distances(close, closes)
        if distances is None:
            continue

        entry = {
            "pair":      pair,
            "close":     round(close, 6),
            "distances": {p: round(d * 100, 3) for p, d in distances.items()},  # dalam %
            "ma":        {p: round(v, 6) for p, v in ma_vals.items()},
        }

        max_dist = max(distances.values())

        if max_dist < VT_MAX_DIST:
            vt_list.append(entry)
        elif T_MIN_DIST <= max_dist <= T_MAX_DIST:
            t_list.append(entry)

    # Urutkan dari yang paling ketat (jarak terkecil)
    vt_list.sort(key=lambda x: max(x["distances"].values()))
    t_list.sort(key=lambda x: max(x["distances"].values()))

    logger.info(f"Forex tight scan: VT={len(vt_list)}, T={len(t_list)}")
    return vt_list, t_list


def score_forex_tight(pair: str, vt_set: set, t_set: set) -> int:
    """
    Hitung tight score untuk satu pair berdasarkan hasil scan_forex_tight().

    Args:
        pair   : nama pair (tanpa C:, uppercase)
        vt_set : set pair yang masuk Very Tight
        t_set  : set pair yang masuk Tight

    Returns:
        +2 jika masuk VT dan juga T (terdekat dari semua MA)
        +1 jika masuk VT saja
         0 jika masuk T saja
        -1 jika tidak masuk keduanya
    """
    clean = pair.upper().strip().removeprefix("C:")
    in_vt = clean in vt_set
    in_t  = clean in t_set

    if in_vt and in_t:
        return 2
    elif in_vt:
        return 1
    elif in_t:
        return 0
    else:
        return -1


# ── Formatter ─────────────────────────────────────────────────────────────────

def format_forex_vt(vt_list: list) -> str:
    """Format tabel VT forex untuk dikirim ke Telegram."""
    if not vt_list:
        return "📭 <b>Tidak ada pasangan forex Very Tight saat ini.</b>"

    lines = [
        "🔥 <b>Forex Very Tight (VT) — Jarak ke semua MA &lt; 5%</b>",
        "<pre>",
        f"{'Pair':<10} {'Close':>10}  {'MA3%':>6} {'MA5%':>6} {'MA10%':>6} {'MA20%':>6}",
        "─" * 52,
    ]
    for e in vt_list:
        d = e["distances"]
        lines.append(
            f"{e['pair']:<10} {e['close']:>10.5f}  "
            f"{d[3]:>5.2f}% {d[5]:>5.2f}% {d[10]:>5.2f}% {d[20]:>5.2f}%"
        )
    lines.append("</pre>")
    return "\n".join(lines)


def format_forex_t(t_list: list) -> str:
    """Format tabel T forex untuk dikirim ke Telegram."""
    if not t_list:
        return "📭 <b>Tidak ada pasangan forex Tight saat ini.</b>"

    lines = [
        "📌 <b>Forex Tight (T) — Jarak ke semua MA 5–7%</b>",
        "<pre>",
        f"{'Pair':<10} {'Close':>10}  {'MA3%':>6} {'MA5%':>6} {'MA10%':>6} {'MA20%':>6}",
        "─" * 52,
    ]
    for e in t_list:
        d = e["distances"]
        lines.append(
            f"{e['pair']:<10} {e['close']:>10.5f}  "
            f"{d[3]:>5.2f}% {d[5]:>5.2f}% {d[10]:>5.2f}% {d[20]:>5.2f}%"
        )
    lines.append("</pre>")
    return "\n".join(lines)
