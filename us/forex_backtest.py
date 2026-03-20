"""
forex_backtest.py — Backtest model scoring + XGBoost ML untuk forex

Sama dengan backtest.py saham, tapi:
  - Baca dari forex_train.db (via forex_train_db)
  - Load/save weight dari forex_weights/ (via forex_scorer)
  - Label target: close[+3] / close[0] - 1 >= +0.5%  → 1 (naik)
                  close[+3] / close[0] - 1 <= -0.5%  → -1 (turun)
                  else                                → 0

Dipanggil via:
  /cf ts bt PAIR       → run_forex_backtest(pair)
  /cf ts bt ml PAIR    → run_forex_ml(pair)
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

from forex_score_history import load_forex_score_history
from forex_scorer import (
    FEATURES, DEFAULT_WEIGHTS,
    load_forex_weights, save_forex_weights, apply_forex_weights,
    get_forex_weights_info,
)

logger = logging.getLogger(__name__)

LABEL_UP_PCT   =  0.005
LABEL_DOWN_PCT = -0.005
SIGNAL_UP      =  1.0
SIGNAL_DOWN    = -1.0
LOOKAHEAD      =  3


def _build_df(pair: str) -> Optional[pd.DataFrame]:
    """
    Baca forex score history, tambah kolom label berdasarkan price[+3].
    3 bar terakhir tidak punya label → di-drop.
    """
    clean   = pair.upper().strip().removeprefix("C:")
    history = load_forex_score_history(clean)
    if not history:
        return None

    df = pd.DataFrame(history)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    # Hitung label dari future return
    labels = []
    for i in range(len(df)):
        if i + LOOKAHEAD >= len(df):
            labels.append(None)
            continue
        ret = (df.loc[i + LOOKAHEAD, "price"] - df.loc[i, "price"]) / df.loc[i, "price"]
        if ret >= LABEL_UP_PCT:
            labels.append(1)
        elif ret <= LABEL_DOWN_PCT:
            labels.append(-1)
        else:
            labels.append(0)

    df["label"] = labels
    df = df.dropna(subset=["label"]).reset_index(drop=True)
    df["label"] = df["label"].astype(int)

    # Pastikan semua fitur ada
    for f in FEATURES:
        if f not in df.columns:
            df[f] = 0

    return df


def _evaluate(df: pd.DataFrame, weights: dict) -> dict:
    """Evaluasi model dengan weight tertentu, return metrics dict."""
    df = df.copy()
    df["weighted_total"] = df[FEATURES].apply(
        lambda row: apply_forex_weights(row.to_dict(), weights), axis=1
    )

    n = len(df)
    labels = df["label"].values
    signals = df["weighted_total"].values

    n_up = int((labels == 1).sum())
    n_dn = int((labels == -1).sum())
    n_nt = int((labels == 0).sum())

    sig_up = df["weighted_total"] >= SIGNAL_UP
    sig_dn = df["weighted_total"] <= SIGNAL_DOWN

    n_sig_up = int(sig_up.sum())
    n_sig_dn = int(sig_dn.sum())
    n_no_sig = n - n_sig_up - n_sig_dn

    tp_up = int((sig_up & (df["label"] == 1)).sum())
    tp_dn = int((sig_dn & (df["label"] == -1)).sum())

    prec_up = tp_up / n_sig_up if n_sig_up > 0 else 0.0
    prec_dn = tp_dn / n_sig_dn if n_sig_dn > 0 else 0.0

    correct = int(((sig_up & (df["label"] == 1)) | (sig_dn & (df["label"] == -1))).sum())
    accuracy = correct / (n_sig_up + n_sig_dn) if (n_sig_up + n_sig_dn) > 0 else 0.0

    wu = tp_up / n_sig_up if n_sig_up > 0 else 0.0
    wd = tp_dn / n_sig_dn if n_sig_dn > 0 else 0.0

    return {
        "n_bars":      n,
        "n_label_up":  n_up,
        "n_label_dn":  n_dn,
        "n_label_nt":  n_nt,
        "n_signal_up": n_sig_up,
        "n_signal_dn": n_sig_dn,
        "n_no_signal": n_no_sig,
        "tp_up":       tp_up,
        "tp_dn":       tp_dn,
        "prec_up":     prec_up,
        "prec_dn":     prec_dn,
        "accuracy":    accuracy,
        "winrate_up":  wu,
        "winrate_dn":  wd,
        "score_mean":  float(np.mean(signals)),
        "score_std":   float(np.std(signals)),
        "score_max":   float(np.max(signals)),
        "score_min":   float(np.min(signals)),
    }


def _fmt_metrics(pair: str, m: dict, weights: dict, label: str = "Current Weight") -> str:
    wi = get_forex_weights_info(pair)
    updated  = wi.get("updated_at", "—") or "—"
    is_def   = all(abs(weights.get(f, 1.0) - 1.0) < 0.001 for f in FEATURES)
    w_tag    = "default (1.0 semua)" if is_def else f"ML ({updated[:10]})"

    lines = [
        f"📊 <b>Backtest {pair}</b> — {label}",
        f"─────────────────────────",
        f"⚙️ Weight  : <code>{w_tag}</code>",
        f"📅 Data    : <b>{m['n_bars']}</b> bar",
        f"",
        f"<b>Label Aktual (price +3 hari):</b>",
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


def run_forex_backtest(pair: str) -> str:
    """Backtest model forex dengan weight saat ini."""
    clean = pair.upper().strip().removeprefix("C:")
    df = _build_df(clean)
    if df is None:
        return (
            f"❌ <b>{clean}</b>: Tidak ada score history.\n"
            f"Jalankan /9 terlebih dahulu."
        )
    weights = load_forex_weights(clean)
    metrics = _evaluate(df, weights)
    return _fmt_metrics(clean, metrics, weights, label="Current Weight")


def run_forex_ml(pair: str) -> list[str]:
    """Train XGBoost pada data forex pair, update weight, return perbandingan."""
    clean = pair.upper().strip().removeprefix("C:")

    try:
        from xgboost import XGBClassifier
    except ImportError:
        return ["❌ XGBoost belum terinstall. Jalankan: <code>pip install xgboost</code>"]

    df = _build_df(clean)
    if df is None:
        return [f"❌ <b>{clean}</b>: Tidak ada score history. Jalankan /9 terlebih dahulu."]
    if len(df) < 30:
        return [f"❌ <b>{clean}</b>: Data terlalu sedikit ({len(df)} bar). Minimal 30 bar."]

    w_before = load_forex_weights(clean)
    m_before = _evaluate(df, w_before)

    X = df[FEATURES].astype(float).values
    y = df["label"].values + 1   # shift: -1→0, 0→1, 1→2

    split_idx = int(len(X) * 0.7)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    model = XGBClassifier(
        n_estimators=200, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        use_label_encoder=False, eval_metric="mlogloss",
        random_state=42, verbosity=0,
        num_class=3, objective="multi:softmax",
    )
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

    raw_imp = model.feature_importances_
    importances = {FEATURES[i]: float(raw_imp[i]) for i in range(len(FEATURES))}
    mean_imp = float(np.mean(raw_imp))
    if mean_imp > 0:
        w_new = {f: round(float(imp) / mean_imp, 6) for f, imp in importances.items()}
    else:
        w_new = dict(DEFAULT_WEIGHTS)

    save_forex_weights(clean, w_new)
    m_after = _evaluate(df, w_new)

    # ── Format output ─────────────────────────────────────────────────────────
    delta_acc = (m_after["accuracy"]   - m_before["accuracy"])   * 100
    delta_wu  = (m_after["winrate_up"] - m_before["winrate_up"]) * 100
    delta_wd  = (m_after["winrate_dn"] - m_before["winrate_dn"]) * 100
    arrow = lambda d: "▲" if d > 0 else ("▼" if d < 0 else "─")

    msg1 = "\n".join([
        f"🤖 <b>ML Weight Adjustment — {clean}</b>",
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
        f"<b>Delta:</b>",
        f"  {arrow(delta_acc)} Accuracy : {delta_acc:+.1f}%",
        f"  {arrow(delta_wu)} Win ▲    : {delta_wu:+.1f}%",
        f"  {arrow(delta_wd)} Win ▼    : {delta_wd:+.1f}%",
        f"",
        f"✅ Weight baru disimpan ke <code>forex_weights/{clean}.json</code>",
    ])

    sorted_feats = sorted(importances.items(), key=lambda x: x[1], reverse=True)
    feat_lines = [f"📐 <b>Feature Importance → Weight Baru ({clean})</b>", "─────────────────────────"]
    for feat, imp in sorted_feats:
        w_old  = w_before.get(feat, 1.0)
        w_n    = w_new.get(feat, 1.0)
        delta  = w_n - w_old
        aw     = "▲" if delta > 0.001 else ("▼" if delta < -0.001 else "─")
        bar    = "█" * min(int(imp * 20), 10) + "░" * max(0, 10 - min(int(imp * 20), 10))
        feat_lines.append(
            f"  {feat:<10} imp={imp:.3f}  [{bar}]  "
            f"w: {w_old:+.3f} → <b>{w_n:+.3f}</b> {aw}"
        )

    return [msg1, "\n".join(feat_lines)]
