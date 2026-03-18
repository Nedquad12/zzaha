"""
backtest.py — Backtest model scoring + XGBoost ML weight adjustment per ticker

Dipanggil via:
  /ch ts bt TICKER       → run_backtest(ticker) → kirim hasil ke Telegram
  /ch ts bt ml TICKER    → run_ml(ticker)       → train XGBoost, update weight, kirim perbandingan

Label:
  close[+3] / close[0] - 1 >= +0.5%  → label  1 (naik)
  close[+3] / close[0] - 1 <= -0.5%  → label -1 (turun)
  else                                → label  0 (netral)

Prediksi model:
  weighted_total >= +5  → prediksi naik
  weighted_total <= -5  → prediksi turun
  else                  → tidak ada sinyal

Threshold ini berlaku untuk backtest current weights maupun setelah ML.
"""

import logging
import os
from typing import Optional

import numpy as np
import pandas as pd

from score_history import load_score_history
from weight_manager import (
    FEATURES, DEFAULT_WEIGHTS,
    load_weights, save_weights, apply_weights, get_weights_info,
)

logger = logging.getLogger(__name__)

# ── Konstanta ─────────────────────────────────────────────────────────────────
LABEL_UP_PCT   =  0.005   # +0.5% → label naik
LABEL_DOWN_PCT = -0.005   # -0.5% → label turun
SIGNAL_UP      =  1.0     # threshold prediksi naik
SIGNAL_DOWN    = -1.0     # threshold prediksi turun
LOOKAHEAD      =  3       # bar ke depan untuk cek outcome


# ── Helper: build DataFrame dari score history ────────────────────────────────

def _build_df(ticker: str) -> Optional[pd.DataFrame]:
    """
    Baca score history, tambahkan kolom label berdasarkan close[+3].
    Bar 3 terakhir tidak punya label (future tidak tersedia) → di-drop.
    """
    history = load_score_history(ticker)
    if not history or len(history) < LOOKAHEAD + 5:
        return None

    df = pd.DataFrame(history)

    # Pastikan kolom fitur ada
    for feat in FEATURES:
        if feat not in df.columns:
            df[feat] = 0.0

    # Hitung label dari future close
    prices = df["price"].values
    labels = []
    for i in range(len(prices)):
        if i + LOOKAHEAD < len(prices):
            ret = (prices[i + LOOKAHEAD] - prices[i]) / prices[i]
            if ret >= LABEL_UP_PCT:
                labels.append(1)
            elif ret <= LABEL_DOWN_PCT:
                labels.append(-1)
            else:
                labels.append(0)
        else:
            labels.append(None)   # 3 bar terakhir tidak ada label

    df["label"] = labels
    df = df[df["label"].notna()].copy()
    df["label"] = df["label"].astype(int)

    return df


# ── Hitung weighted total per baris ──────────────────────────────────────────

def _compute_weighted_totals(df: pd.DataFrame, weights: dict) -> np.ndarray:
    totals = np.zeros(len(df))
    for feat in FEATURES:
        w = float(weights.get(feat, 1.0))
        totals += df[feat].astype(float).values * w
    return totals


# ── Backtest logic ────────────────────────────────────────────────────────────

def _evaluate(df: pd.DataFrame, weights: dict) -> dict:
    """
    Evaluasi model dengan weight tertentu.
    Return dict berisi metrik performa.
    """
    totals = _compute_weighted_totals(df, weights)
    labels = df["label"].values

    # Prediksi
    pred_up   = totals >= SIGNAL_UP
    pred_down = totals <= SIGNAL_DOWN
    pred_none = ~pred_up & ~pred_down

    n_total     = len(df)
    n_signal_up = int(pred_up.sum())
    n_signal_dn = int(pred_down.sum())
    n_no_signal = int(pred_none.sum())

    # Evaluasi prediksi naik
    if n_signal_up > 0:
        tp_up    = int(((pred_up) & (labels == 1)).sum())
        fp_up    = int(((pred_up) & (labels != 1)).sum())
        prec_up  = tp_up / n_signal_up
        winrate_up = tp_up / n_signal_up
    else:
        tp_up = fp_up = 0
        prec_up = winrate_up = 0.0

    # Evaluasi prediksi turun
    if n_signal_dn > 0:
        tp_dn    = int(((pred_down) & (labels == -1)).sum())
        fp_dn    = int(((pred_down) & (labels != -1)).sum())
        prec_dn  = tp_dn / n_signal_dn
        winrate_dn = tp_dn / n_signal_dn
    else:
        tp_dn = fp_dn = 0
        prec_dn = winrate_dn = 0.0

    # Overall accuracy (hanya bar yang ada sinyal)
    n_signal_total = n_signal_up + n_signal_dn
    if n_signal_total > 0:
        tp_total = tp_up + tp_dn
        accuracy = tp_total / n_signal_total
    else:
        accuracy = 0.0

    # Distribusi total score
    score_mean = float(np.mean(totals))
    score_std  = float(np.std(totals))
    score_max  = float(np.max(totals))
    score_min  = float(np.min(totals))

    # Distribusi label
    n_label_up = int((labels == 1).sum())
    n_label_dn = int((labels == -1).sum())
    n_label_nt = int((labels == 0).sum())

    return {
        "n_bars":       n_total,
        "n_label_up":   n_label_up,
        "n_label_dn":   n_label_dn,
        "n_label_nt":   n_label_nt,
        "n_signal_up":  n_signal_up,
        "n_signal_dn":  n_signal_dn,
        "n_no_signal":  n_no_signal,
        "tp_up":        tp_up,
        "tp_dn":        tp_dn,
        "prec_up":      prec_up,
        "prec_dn":      prec_dn,
        "winrate_up":   winrate_up,
        "winrate_dn":   winrate_dn,
        "accuracy":     accuracy,
        "score_mean":   score_mean,
        "score_std":    score_std,
        "score_max":    score_max,
        "score_min":    score_min,
    }


# ── Format hasil backtest ─────────────────────────────────────────────────────

def _fmt_metrics(ticker: str, m: dict, weights: dict, label: str = "Current") -> str:
    """Format metrik backtest jadi teks Telegram HTML."""
    wi = get_weights_info(ticker)
    updated = wi.get("updated_at", "—") or "—"
    is_default = all(abs(weights.get(f, 1.0) - 1.0) < 0.001 for f in FEATURES)
    weight_tag = "default (1.0 semua)" if is_default else f"ML ({updated[:10]})"

    lines = [
        f"📊 <b>Backtest {ticker}</b> — {label}",
        f"─────────────────────────",
        f"⚙️ Weight  : <code>{weight_tag}</code>",
        f"📅 Data    : <b>{m['n_bars']}</b> bar",
        f"",
        f"<b>Label Aktual (close +3 hari):</b>",
        f"  ▲ Naik   : {m['n_label_up']} bar ({m['n_label_up']/m['n_bars']*100:.1f}%)",
        f"  ▼ Turun  : {m['n_label_dn']} bar ({m['n_label_dn']/m['n_bars']*100:.1f}%)",
        f"  ─ Netral : {m['n_label_nt']} bar ({m['n_label_nt']/m['n_bars']*100:.1f}%)",
        f"",
        f"<b>Sinyal Model (threshold ±{SIGNAL_UP:.0f}):</b>",
        f"  🟢 Sinyal Naik  : {m['n_signal_up']} bar",
        f"     ✅ Benar      : {m['tp_up']} | Presisi: <b>{m['prec_up']*100:.1f}%</b>",
        f"  🔴 Sinyal Turun : {m['n_signal_dn']} bar",
        f"     ✅ Benar      : {m['tp_dn']} | Presisi: <b>{m['prec_dn']*100:.1f}%</b>",
        f"  ⚪ Tidak Sinyal : {m['n_no_signal']} bar",
        f"",
        f"<b>Ringkasan:</b>",
        f"  🎯 Accuracy     : <b>{m['accuracy']*100:.1f}%</b>",
        f"  💹 Win Rate ▲   : <b>{m['winrate_up']*100:.1f}%</b>",
        f"  💹 Win Rate ▼   : <b>{m['winrate_dn']*100:.1f}%</b>",
        f"",
        f"<b>Distribusi Score:</b>",
        f"  Mean: {m['score_mean']:+.2f} | Std: {m['score_std']:.2f}",
        f"  Max: {m['score_max']:+.2f} | Min: {m['score_min']:+.2f}",
    ]
    return "\n".join(lines)


def _fmt_weights_table(weights: dict) -> str:
    """Format tabel weight jadi teks."""
    lines = ["<b>Weight per Fitur:</b>"]
    for feat in FEATURES:
        w = weights.get(feat, 1.0)
        bar = "█" * int(abs(w) * 5) if abs(w) <= 3 else "██████████"
        lines.append(f"  {feat:<10}: <code>{w:+.4f}</code>  {bar}")
    return "\n".join(lines)


def _fmt_comparison(ticker: str, m_before: dict, m_after: dict,
                     w_before: dict, w_after: dict, importances: dict) -> list[str]:
    """Format perbandingan before vs after ML → list pesan (bisa > 1 jika panjang)."""
    msg1 = [
        f"🤖 <b>ML Weight Adjustment — {ticker}</b>",
        f"─────────────────────────",
        f"",
        f"<b>SEBELUM (weight default):</b>",
        f"  🎯 Accuracy  : {m_before['accuracy']*100:.1f}%",
        f"  💹 Win ▲     : {m_before['winrate_up']*100:.1f}%  ({m_before['n_signal_up']} sinyal)",
        f"  💹 Win ▼     : {m_before['winrate_dn']*100:.1f}%  ({m_before['n_signal_dn']} sinyal)",
        f"",
        f"<b>SESUDAH (weight ML):</b>",
        f"  🎯 Accuracy  : {m_after['accuracy']*100:.1f}%",
        f"  💹 Win ▲     : {m_after['winrate_up']*100:.1f}%  ({m_after['n_signal_up']} sinyal)",
        f"  💹 Win ▼     : {m_after['winrate_dn']*100:.1f}%  ({m_after['n_signal_dn']} sinyal)",
        f"",
    ]

    # Delta
    delta_acc = (m_after['accuracy'] - m_before['accuracy']) * 100
    delta_wu  = (m_after['winrate_up'] - m_before['winrate_up']) * 100
    delta_wd  = (m_after['winrate_dn'] - m_before['winrate_dn']) * 100
    arrow = lambda d: "▲" if d > 0 else ("▼" if d < 0 else "─")

    msg1 += [
        f"<b>Delta:</b>",
        f"  {arrow(delta_acc)} Accuracy : {delta_acc:+.1f}%",
        f"  {arrow(delta_wu)} Win ▲    : {delta_wu:+.1f}%",
        f"  {arrow(delta_wd)} Win ▼    : {delta_wd:+.1f}%",
        f"",
        f"✅ Weight baru disimpan ke <code>/us/weights/{ticker}.json</code>",
        f"✅ Berlaku global untuk semua scoring {ticker}",
    ]

    msg2 = [
        f"📐 <b>Feature Importance → Weight Baru ({ticker})</b>",
        f"─────────────────────────",
    ]
    # Sort by importance descending
    sorted_feats = sorted(importances.items(), key=lambda x: x[1], reverse=True)
    for feat, imp in sorted_feats:
        w_old = w_before.get(feat, 1.0)
        w_new = w_after.get(feat, 1.0)
        delta = w_new - w_old
        arrow_w = "▲" if delta > 0.001 else ("▼" if delta < -0.001 else "─")
        bar_len = min(int(imp * 20), 10)
        bar = "█" * bar_len + "░" * (10 - bar_len)
        msg2.append(
            f"  {feat:<10} imp={imp:.3f}  [{bar}]  "
            f"w: {w_old:+.3f} → <b>{w_new:+.3f}</b> {arrow_w}"
        )

    return ["\n".join(msg1), "\n".join(msg2)]


# ── Public: run_backtest ──────────────────────────────────────────────────────

def run_backtest(ticker: str) -> str:
    """
    Backtest model dengan weight saat ini untuk ticker.

    Returns:
        str pesan Telegram HTML
    """
    ticker = ticker.upper()

    df = _build_df(ticker)
    if df is None:
        return (
            f"❌ <b>{ticker}</b>: Tidak ada score history.\n"
            f"Jalankan /9 terlebih dahulu."
        )

    weights = load_weights(ticker)
    metrics = _evaluate(df, weights)

    return _fmt_metrics(ticker, metrics, weights, label="Current Weight")


# ── Public: run_ml ────────────────────────────────────────────────────────────

def run_ml(ticker: str) -> list[str]:
    """
    Train XGBoost pada data ticker, update weight, kirim perbandingan.

    Returns:
        list[str] pesan Telegram HTML (2 pesan: summary + feature table)
    """
    ticker = ticker.upper()

    try:
        from xgboost import XGBClassifier
    except ImportError:
        return ["❌ XGBoost belum terinstall. Jalankan: <code>pip install xgboost</code>"]

    df = _build_df(ticker)
    if df is None:
        return [
            f"❌ <b>{ticker}</b>: Tidak ada score history.\n"
            f"Jalankan /9 terlebih dahulu."
        ]

    if len(df) < 30:
        return [
            f"❌ <b>{ticker}</b>: Data terlalu sedikit ({len(df)} bar).\n"
            f"Minimal 30 bar diperlukan untuk training."
        ]

    # ── Backtest dengan weight saat ini (SEBELUM) ─────────────────────────
    w_before = load_weights(ticker)
    m_before = _evaluate(df, w_before)

    # ── Persiapan data training ───────────────────────────────────────────
    X = df[FEATURES].astype(float).values
    y_raw = df["label"].values   # -1, 0, 1

    # XGBoost butuh label 0, 1, 2 (multi-class)
    # Map: -1 → 0 (turun), 0 → 1 (netral), 1 → 2 (naik)
    y = y_raw + 1   # shift: 0, 1, 2

    # ── Train XGBoost ─────────────────────────────────────────────────────
    # Split 70% train / 30% test (berdasarkan urutan waktu, tidak di-shuffle)
    split_idx = int(len(X) * 0.7)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    model = XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        use_label_encoder=False,
        eval_metric="mlogloss",
        random_state=42,
        verbosity=0,
        num_class=3,
        objective="multi:softmax",
    )

    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )

    # ── Feature importances → weight baru ────────────────────────────────
    raw_importances = model.feature_importances_   # array float, sum ≈ 1.0
    importances = {FEATURES[i]: float(raw_importances[i]) for i in range(len(FEATURES))}

    # Normalize: weight = importance / mean(importance) * 1.0
    # Sehingga rata-rata weight = 1.0, tapi ada yang lebih tinggi/rendah
    mean_imp = float(np.mean(raw_importances))
    if mean_imp > 0:
        w_new = {feat: round(float(imp) / mean_imp, 6) for feat, imp in importances.items()}
    else:
        w_new = dict(DEFAULT_WEIGHTS)

    # ── Simpan weight baru ────────────────────────────────────────────────
    save_weights(ticker, w_new)

    # ── Backtest dengan weight baru (SESUDAH) ─────────────────────────────
    m_after = _evaluate(df, w_new)

    # ── Format output ─────────────────────────────────────────────────────
    return _fmt_comparison(ticker, m_before, m_after, w_before, w_new, importances)
