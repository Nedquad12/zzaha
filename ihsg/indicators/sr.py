"""
indicators/sr.py — Support & Resistance detector (Donchian default)

Kolom yang dibutuhkan: 'open', 'high', 'low', 'close', 'volume'

Konstanta default (sebelumnya dari config.py):
"""

import math
from dataclasses import dataclass
import numpy as np
import pandas as pd

# ── Konstanta default (ganti via argumen fungsi jika perlu) ───────────────────
SR_METHOD_DONCHIAN = "Donchian"
SR_METHOD_PIVOTS   = "Pivots"
SR_METHOD_CSID     = "CSID"
SR_METHOD_ZIGZAG   = "ZigZag"
SR_SENSITIVITY     = 10
SR_ATR_MULT        = 0.5
SR_ATR_PERIOD      = 200
SR_MAX_LEVELS      = 5


@dataclass
class SRLevel:
    top:            float
    btm:            float
    base_price:     float
    start_bar:      int
    mitigation_bar: int  = -1
    is_support:     bool = True
    is_mitigated:   bool = False
    entries:        int  = 0
    strength:       int  = 0
    sweeps:         int  = 0
    traded_volume:  float = 0.0


def _calc_atr(high, low, close, period):
    n    = len(close)
    atr  = np.zeros(n)
    tr   = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i],
                    abs(high[i] - close[i-1]),
                    abs(low[i]  - close[i-1]))
    atr[period-1] = np.mean(tr[:period])
    for i in range(period, n):
        atr[i] = (atr[i-1] * (period-1) + tr[i]) / period
    cum = np.cumsum(np.abs(high - low))
    for i in range(period-1):
        atr[i] = cum[i] / (i + 1)
    return atr


def _detect_donchian(high, low, sens):
    swings = []
    os_dir = 0
    val    = math.nan
    val_loc = 0
    for i in range(len(high)):
        dh = max(high[max(0, i-sens+1):i+1])
        dl = min(low[max(0, i-sens+1):i+1])
        prev_dh = max(high[max(0, i-sens):i]) if i > 0 else dh
        prev_dl = min(low[max(0, i-sens):i])  if i > 0 else dl
        new_os = 1 if dh > prev_dh else (-1 if dl < prev_dl else os_dir)
        if new_os != os_dir:
            if new_os == 1:
                if not math.isnan(val):
                    swings.append((val_loc, float(val), False))
                val = high[i]; val_loc = i
            else:
                if not math.isnan(val):
                    swings.append((val_loc, float(val), True))
                val = low[i]; val_loc = i
            os_dir = new_os
        else:
            if os_dir == 1 and high[i] >= val:
                val = high[i]; val_loc = i
            elif os_dir == -1 and low[i] <= val:
                val = low[i]; val_loc = i
    return swings


def _handle_overlap(levels, top, btm, base, start, is_sup):
    for lv in levels:
        if not lv.is_mitigated and lv.is_support == is_sup:
            if max(btm, lv.btm) < min(top, lv.top):
                return False
    levels.insert(0, SRLevel(top=top, btm=btm, base_price=base,
                              start_bar=start, is_support=is_sup))
    return True


def _update_mitigation(levels, high, low, close, volume, open_):
    n = len(close)
    for i in range(n):
        for lv in levels:
            if lv.is_mitigated:
                continue
            if lv.is_support and close[i] < lv.btm:
                lv.is_mitigated   = True
                lv.mitigation_bar = i
                continue
            if not lv.is_support and close[i] > lv.top:
                lv.is_mitigated   = True
                lv.mitigation_bar = i
                continue
            if i < lv.start_bar:
                continue
            if high[i] >= lv.btm and low[i] <= lv.top:
                lv.traded_volume += float(volume[i])
            if lv.is_support:
                if low[i] <= lv.top and close[i] >= lv.btm:
                    lv.entries += 1
                if low[i] < lv.btm and min(close[i], open_[i]) > lv.btm:
                    lv.sweeps += 1
            else:
                if high[i] >= lv.btm and close[i] <= lv.top:
                    lv.entries += 1
                if high[i] > lv.top and max(close[i], open_[i]) < lv.top:
                    lv.sweeps += 1


def detect_sr(
    df:         pd.DataFrame,
    method:     str   = SR_METHOD_DONCHIAN,
    sens:       float = SR_SENSITIVITY,
    atr_mult:   float = SR_ATR_MULT,
    max_levels: int   = SR_MAX_LEVELS,
) -> tuple[list[SRLevel], list[SRLevel]]:
    high   = df["high"].values
    low    = df["low"].values
    close  = df["close"].values
    open_  = df["open"].values
    volume = df["volume"].values
    sens_i = max(1, int(sens))

    atr    = _calc_atr(high, low, close, SR_ATR_PERIOD)
    swings = _detect_donchian(high, low, sens_i)

    levels: list[SRLevel] = []
    for bar_i, price, is_high in swings:
        cur_atr = float(atr[min(bar_i, len(atr)-1)])
        if is_high:
            _handle_overlap(levels, price, price - cur_atr * atr_mult,
                            price, bar_i, is_sup=False)
        else:
            _handle_overlap(levels, price + cur_atr * atr_mult, price,
                            price, bar_i, is_sup=True)

    if len(levels) > 200:
        levels = levels[:200]

    _update_mitigation(levels, high, low, close, volume, open_)

    active_sup = [l for l in levels if not l.is_mitigated and     l.is_support][:max_levels]
    active_res = [l for l in levels if not l.is_mitigated and not l.is_support][:max_levels]
    broken     = [l for l in levels if     l.is_mitigated]

    return active_sup + active_res, broken
