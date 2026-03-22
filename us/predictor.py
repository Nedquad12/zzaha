import json
import logging
import os
from typing import Optional

import numpy as np
import pandas as pd

from score_history import load_score_history
from weight_manager import FEATURES, load_weights
from backtest import LABEL_UP_PCT, LABEL_DOWN_PCT, LOOKAHEAD, _build_df
from wti import (
    _load_history, _calc_atr14, _ticker_json_path,
    SPY_JSON_PATH, LOOKBACK_DAYS, ATR_DIVISOR, SPY_THRESHOLD,
)

logger = logging.getLogger(__name__)

# ── Konstanta ─────────────────────────────────────────────────────────────────
WTI_LOOKAHEAD     = 3      # bar ke depan untuk cek apakah saham ikut SPY
MIN_BARS_SCORE    = 30     # minimum bar untuk score model
MIN_BARS_WTI      = 20     # minimum window untuk WTI model
WTI_FEATURES      = [      # fitur yang dipakai model WTI
    "spy_chg",             # % perubahan SPY hari ini
    "tkr_chg",             # % perubahan saham hari ini
    "roll_corr_10",        # rolling correlation 10 hari SPY vs saham
    "roll_corr_20",        # rolling correlation 20 hari
    "spy_ma5",             # SPY close vs MA5 (apakah SPY trending)
    "tkr_ma5",             # saham close vs MA5
    "spy_vol_ratio",       # rasio SPY volatility 5 vs 20 hari
    "tkr_vol_ratio",       # rasio saham volatility 5 vs 20 hari
    "followed_prev1",      # apakah saham ikut SPY 1 bar lalu
    "followed_prev2",      # apakah saham ikut SPY 2 bar lalu
    "followed_prev3",      # apakah saham ikut SPY 3 bar lalu
]


# ── Helper: build fitur WTI ───────────────────────────────────────────────────

def _build_wti_df(ticker: str) -> Optional[pd.DataFrame]:
    """
    Bangun DataFrame fitur untuk model WTI.

    Setiap baris = 1 hari bursa
    Label = 1 jika saham mengikuti arah SPY dalam 3 hari ke depan, else 0
    'Mengikuti' = saham naik saat SPY naik ATAU saham turun saat SPY turun
    """
    spy_all = _load_history(SPY_JSON_PATH)
    tkr_all = _load_history(_ticker_json_path(ticker))

    if not spy_all or not tkr_all:
        return None

    # Hitung threshold saham dari ATR14
    atr14 = _calc_atr14(tkr_all)
    if atr14 is None:
        return None
    last_close    = tkr_all[-1]["close"]
    atr_pct       = (atr14 / last_close) * 100
    tkr_threshold = atr_pct / ATR_DIVISOR

    # Bangun dict date → close
    spy_map = {b["date"]: b["close"] for b in spy_all}
    tkr_map = {b["date"]: b["close"] for b in tkr_all}
    common  = sorted(set(spy_map.keys()) & set(tkr_map.keys()))

    if len(common) < MIN_BARS_WTI + WTI_LOOKAHEAD + 1:
        return None

    # Hitung % change harian
    spy_closes = [spy_map[d] for d in common]
    tkr_closes = [tkr_map[d] for d in common]

    spy_chgs = [0.0]
    tkr_chgs = [0.0]
    for i in range(1, len(common)):
        sc = (spy_closes[i] - spy_closes[i-1]) / spy_closes[i-1] * 100 if spy_closes[i-1] else 0.0
        tc = (tkr_closes[i] - tkr_closes[i-1]) / tkr_closes[i-1] * 100 if tkr_closes[i-1] else 0.0
        spy_chgs.append(sc)
        tkr_chgs.append(tc)

    spy_chgs = np.array(spy_chgs)
    tkr_chgs = np.array(tkr_chgs)
    n        = len(common)

    # Helper: rolling corr
    def rolling_corr(a, b, w):
        out = np.full(n, 0.0)
        for i in range(w - 1, n):
            sa = a[i - w + 1: i + 1]
            sb = b[i - w + 1: i + 1]
            if np.std(sa) > 0 and np.std(sb) > 0:
                out[i] = float(np.corrcoef(sa, sb)[0, 1])
        return out

    # Helper: rolling std (volatility proxy)
    def rolling_std(a, w):
        out = np.full(n, 0.0)
        for i in range(w - 1, n):
            out[i] = float(np.std(a[i - w + 1: i + 1]))
        return out

    # Helper: rolling MA
    def rolling_ma(arr, w):
        out = np.full(n, 0.0)
        for i in range(w - 1, n):
            out[i] = float(np.mean(arr[i - w + 1: i + 1]))
        return out

    rc10  = rolling_corr(spy_chgs, tkr_chgs, 10)
    rc20  = rolling_corr(spy_chgs, tkr_chgs, 20)
    spy_ma5 = rolling_ma(spy_closes, 5)
    tkr_ma5 = rolling_ma(tkr_closes, 5)
    spy_std5  = rolling_std(spy_chgs, 5)
    spy_std20 = rolling_std(spy_chgs, 20)
    tkr_std5  = rolling_std(tkr_chgs, 5)
    tkr_std20 = rolling_std(tkr_chgs, 20)

    # "Followed" flag per bar
    def followed(spy_c, tkr_c):
        """1 jika saham ikut SPY (both up atau both down), 0 jika divergen / netral."""
        spy_up   = spy_c >  SPY_THRESHOLD
        spy_down = spy_c < -SPY_THRESHOLD
        tkr_up   = tkr_c >  tkr_threshold
        tkr_down = tkr_c < -tkr_threshold
        if spy_up and tkr_up:
            return 1
        if spy_down and tkr_down:
            return 1
        if not spy_up and not spy_down:
            return -1   # SPY netral → tidak dihitung, tandai khusus
        return 0

    followed_arr = np.array([followed(spy_chgs[i], tkr_chgs[i]) for i in range(n)])

    # Build rows
    rows = []
    for i in range(20, n - WTI_LOOKAHEAD):   # mulai dari 20 untuk rolling features
        # Label: dalam 3 hari ke depan, apakah saham ikut SPY setidaknya 2 dari 3 hari?
        future_follow = 0
        counted       = 0
        for k in range(1, WTI_LOOKAHEAD + 1):
            fi = followed_arr[i + k]
            if fi != -1:   # SPY tidak netral
                counted += 1
                future_follow += fi

        # Label: 1 jika mayoritas hari mengikuti SPY (> 50% dari hari yang count)
        if counted == 0:
            continue
        label = 1 if (future_follow / counted) > 0.5 else 0

        spy_vol_ratio = (spy_std5[i] / spy_std20[i]) if spy_std20[i] > 0 else 1.0
        tkr_vol_ratio = (tkr_std5[i] / tkr_std20[i]) if tkr_std20[i] > 0 else 1.0
        spy_ma5_rel   = (spy_closes[i] / spy_ma5[i] - 1) * 100 if spy_ma5[i] > 0 else 0.0
        tkr_ma5_rel   = (tkr_closes[i] / tkr_ma5[i] - 1) * 100 if tkr_ma5[i] > 0 else 0.0

        # followed 1, 2, 3 bar lalu (ganti -1 dengan 0 untuk netral)
        fp1 = max(0, followed_arr[i])
        fp2 = max(0, followed_arr[i - 1]) if i >= 1 else 0
        fp3 = max(0, followed_arr[i - 2]) if i >= 2 else 0

        rows.append({
            "date":           common[i],
            "spy_chg":        spy_chgs[i],
            "tkr_chg":        tkr_chgs[i],
            "roll_corr_10":   rc10[i],
            "roll_corr_20":   rc20[i],
            "spy_ma5":        spy_ma5_rel,
            "tkr_ma5":        tkr_ma5_rel,
            "spy_vol_ratio":  spy_vol_ratio,
            "tkr_vol_ratio":  tkr_vol_ratio,
            "followed_prev1": fp1,
            "followed_prev2": fp2,
            "followed_prev3": fp3,
            "tkr_threshold":  tkr_threshold,
            "label":          label,
        })

    if len(rows) < MIN_BARS_WTI:
        return None

    return pd.DataFrame(rows)


# ── Model 1: Score Prediction ─────────────────────────────────────────────────

def _predict_score(ticker: str) -> Optional[dict]:
    """
    Train XGBoost dari score history → prediksi arah 3 hari ke depan.

    Returns dict:
      label       : "NAIK" | "TURUN" | "NETRAL"
      confidence  : 0–100 (%)
      proba_up    : float
      proba_down  : float
      proba_flat  : float
      n_train     : int
      win_rate    : float (backtest win rate pada test set)
      features    : dict fitur terbaru yang dipakai prediksi
    """
    try:
        from xgboost import XGBClassifier
    except ImportError:
        return {"error": "XGBoost belum terinstall"}

    df = _build_df(ticker)
    if df is None or len(df) < MIN_BARS_SCORE + 5:
        return {"error": f"Data tidak cukup (minimal {MIN_BARS_SCORE} bar)"}

    weights = load_weights(ticker)

    # Feature matrix: raw indicator scores + weighted total
    X_cols = FEATURES + ["total"]

    # Tambah kolom weighted total
    df["total"] = sum(
        df[f].astype(float) * float(weights.get(f, 1.0))
        for f in FEATURES
    )

    # Pastikan semua kolom ada
    for col in X_cols:
        if col not in df.columns:
            df[col] = 0.0

    X = df[X_cols].astype(float).values
    y_raw = df["label"].values   # -1, 0, 1

    # Map ke 0, 1, 2
    y = y_raw + 1

    # Split waktu (70/30)
    split = int(len(X) * 0.7)
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]

    model = XGBClassifier(
        n_estimators=300,
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
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

    # Backtest win rate pada test set
    y_pred_test = model.predict(X_test)
    correct = (y_pred_test == y_test).sum()
    win_rate = correct / len(y_test) if len(y_test) > 0 else 0.0

    # Prediksi untuk bar terakhir (data terbaru)
    X_latest = X[-1].reshape(1, -1)
    proba    = model.predict_proba(X_latest)[0]   # [p_down, p_flat, p_up]

    label_map  = {0: "TURUN", 1: "NETRAL", 2: "NAIK"}
    pred_class = int(np.argmax(proba))
    label      = label_map[pred_class]
    confidence = float(proba[pred_class]) * 100

    # Feature importance
    importances = {X_cols[i]: float(model.feature_importances_[i]) for i in range(len(X_cols))}
    top3 = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:3]

    # Nilai fitur terbaru
    latest_features = {X_cols[i]: float(X[-1][i]) for i in range(len(X_cols))}

    return {
        "label":      label,
        "confidence": round(confidence, 1),
        "proba_up":   round(float(proba[2]) * 100, 1),
        "proba_down": round(float(proba[0]) * 100, 1),
        "proba_flat": round(float(proba[1]) * 100, 1),
        "n_train":    len(X_train),
        "n_test":     len(X_test),
        "win_rate":   round(win_rate * 100, 1),
        "top3_feat":  top3,
        "features":   latest_features,
    }


# ── Model 2: WTI Prediction ───────────────────────────────────────────────────

def _predict_wti(ticker: str) -> Optional[dict]:
    """
    Train XGBoost dari data WTI → prediksi apakah saham akan mengikuti SPY
    dalam 3 hari ke depan.

    Returns dict:
      label       : "IKUT SPY" | "DIVERGEN"
      confidence  : 0–100 (%)
      proba_follow: float
      proba_div   : float
      n_train     : int
      win_rate    : float
      roll_corr_10: float (korelasi terbaru 10 hari)
      roll_corr_20: float (korelasi terbaru 20 hari)
    """
    try:
        from xgboost import XGBClassifier
    except ImportError:
        return {"error": "XGBoost belum terinstall"}

    df = _build_wti_df(ticker)
    if df is None or len(df) < MIN_BARS_WTI + 5:
        err_reason = "Data WTI tidak cukup"
        if df is None:
            spy_ok = os.path.exists(SPY_JSON_PATH)
            tkr_ok = os.path.exists(_ticker_json_path(ticker))
            if not spy_ok:
                err_reason = "Data SPY tidak tersedia di /us/500/SPY.json"
            elif not tkr_ok:
                err_reason = f"Data {ticker} tidak tersedia di /us/500/{ticker}.json"
            else:
                err_reason = "Data tidak cukup untuk WTI (jalankan /9 terlebih dahulu)"
        return {"error": err_reason}

    X = df[WTI_FEATURES].astype(float).values
    y = df["label"].values   # 0 atau 1

    split = int(len(X) * 0.7)
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]

    model = XGBClassifier(
        n_estimators=200,
        max_depth=3,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        use_label_encoder=False,
        eval_metric="logloss",
        random_state=42,
        verbosity=0,
        objective="binary:logistic",
    )
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

    # Win rate test
    y_pred = model.predict(X_test)
    win_rate = float((y_pred == y_test).sum() / len(y_test)) if len(y_test) > 0 else 0.0

    # Prediksi bar terakhir
    X_latest = X[-1].reshape(1, -1)
    proba    = model.predict_proba(X_latest)[0]   # [p_divergen, p_follow]

    follow_prob = float(proba[1]) * 100
    div_prob    = float(proba[0]) * 100

    if follow_prob >= div_prob:
        label      = "IKUT SPY"
        confidence = follow_prob
    else:
        label      = "DIVERGEN"
        confidence = div_prob

    # Ambil nilai korelasi terbaru untuk context
    last_row = df.iloc[-1]
    rc10     = float(last_row["roll_corr_10"])
    rc20     = float(last_row["roll_corr_20"])
    fp1      = int(last_row["followed_prev1"])
    fp2      = int(last_row["followed_prev2"])
    fp3      = int(last_row["followed_prev3"])
    recent_follow = fp1 + fp2 + fp3

    return {
        "label":        label,
        "confidence":   round(confidence, 1),
        "proba_follow": round(follow_prob, 1),
        "proba_div":    round(div_prob, 1),
        "n_train":      len(X_train),
        "n_test":       len(X_test),
        "win_rate":     round(win_rate * 100, 1),
        "roll_corr_10": round(rc10, 3),
        "roll_corr_20": round(rc20, 3),
        "recent_follow":recent_follow,   # berapa hari dari 3 hari lalu saham ikut SPY
    }


# ── Formatter ─────────────────────────────────────────────────────────────────

def _emoji_label_score(label: str) -> str:
    return {"NAIK": "🟢", "TURUN": "🔴", "NETRAL": "⚪"}.get(label, "❓")


def _emoji_label_wti(label: str) -> str:
    return {"IKUT SPY": "🔗", "DIVERGEN": "🔀"}.get(label, "❓")


def _conf_bar(pct: float, width: int = 10) -> str:
    """Visual bar konfidence."""
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _corr_desc(corr: float) -> str:
    if corr >= 0.7:
        return "sangat kuat"
    elif corr >= 0.4:
        return "kuat"
    elif corr >= 0.2:
        return "moderat"
    elif corr >= 0:
        return "lemah"
    else:
        return "negatif"


def fmt_prediction(ticker: str, score_pred: Optional[dict], wti_pred: Optional[dict]) -> list[str]:
    """
    Format hasil prediksi menjadi pesan Telegram HTML.

    Returns list[str] (bisa 1 atau 2 pesan jika panjang).
    """
    ticker = ticker.upper()
    lines  = [f"🔮 <b>Prediksi 3 Hari — {ticker}</b>", "─────────────────────────", ""]

    # ── Blok 1: Score Prediction ──────────────────────────────────────────
    lines.append("📊 <b>Score Model (Arah Harga)</b>")

    if score_pred is None or "error" in score_pred:
        err = score_pred.get("error", "Unknown") if score_pred else "Data tidak tersedia"
        lines.append(f"   ❌ {err}")
    else:
        sp    = score_pred
        emoji = _emoji_label_score(sp["label"])
        bar   = _conf_bar(sp["confidence"])

        lines += [
            f"   {emoji} <b>{sp['label']}</b>  —  Confidence: <b>{sp['confidence']:.1f}%</b>",
            f"   [{bar}]",
            f"",
            f"   Probabilitas:",
            f"   🟢 Naik    : <b>{sp['proba_up']:.1f}%</b>",
            f"   ⚪ Netral  : <b>{sp['proba_flat']:.1f}%</b>",
            f"   🔴 Turun   : <b>{sp['proba_down']:.1f}%</b>",
            f"",
            f"   Model: {sp['n_train']} bar train | {sp['n_test']} bar test",
            f"   Akurasi backtest: <b>{sp['win_rate']:.1f}%</b>",
        ]

        if sp.get("top3_feat"):
            top3_str = " · ".join(f"{k}({v:.2f})" for k, v in sp["top3_feat"])
            lines.append(f"   Top fitur: <code>{top3_str}</code>")

    lines.append("")
    lines.append("─────────────────────────")
    lines.append("")

    # ── Blok 2: WTI Prediction ────────────────────────────────────────────
    lines.append("📡 <b>WTI Model (Korelasi SPY)</b>")
    lines.append(f"   Prediksi apakah <b>{ticker}</b> ikut arah SPY dalam 3 hari:")

    if wti_pred is None or "error" in wti_pred:
        err = wti_pred.get("error", "Unknown") if wti_pred else "Data tidak tersedia"
        lines.append(f"   ❌ {err}")
    else:
        wp    = wti_pred
        emoji = _emoji_label_wti(wp["label"])
        bar   = _conf_bar(wp["confidence"])

        lines += [
            f"",
            f"   {emoji} <b>{wp['label']}</b>  —  Confidence: <b>{wp['confidence']:.1f}%</b>",
            f"   [{bar}]",
            f"",
            f"   Probabilitas:",
            f"   🔗 Ikut SPY : <b>{wp['proba_follow']:.1f}%</b>",
            f"   🔀 Divergen  : <b>{wp['proba_div']:.1f}%</b>",
            f"",
            f"   Korelasi historis:",
            f"   10 hari : <b>{wp['roll_corr_10']:+.3f}</b>  ({_corr_desc(wp['roll_corr_10'])})",
            f"   20 hari : <b>{wp['roll_corr_20']:+.3f}</b>  ({_corr_desc(wp['roll_corr_20'])})",
            f"",
            f"   3 hari lalu ikut SPY: <b>{wp['recent_follow']}/3</b>",
            f"   Model: {wp['n_train']} bar train | {wp['n_test']} bar test",
            f"   Akurasi backtest: <b>{wp['win_rate']:.1f}%</b>",
        ]

    lines += [
        "",
        "─────────────────────────",
        "<i>⚠️ Prediksi model ML, bukan saran investasi.</i>",
        f"<i>Data berdasarkan hari bursa terakhir ({LOOKAHEAD} hari lookahead).</i>",
    ]

    # Gabung dan split jika terlalu panjang
    full = "\n".join(lines)
    if len(full) <= 4000:
        return [full]

    # Split di separator
    parts  = full.split("─────────────────────────")
    msgs   = []
    chunk  = ""
    for part in parts:
        if len(chunk) + len(part) > 3800:
            if chunk.strip():
                msgs.append(chunk.strip())
            chunk = part
        else:
            chunk += "─────────────────────────" + part
    if chunk.strip():
        msgs.append(chunk.strip())
    return msgs if msgs else [full[:4000]]


# ── Public entry point ────────────────────────────────────────────────────────

def run_prediction(ticker: str) -> list[str]:
    """
    Entry point utama untuk /pred TICKER.

    Returns:
        list[str] pesan Telegram HTML
    """
    ticker = ticker.upper()

    score_pred = None
    wti_pred   = None

    # Run score prediction
    try:
        score_pred = _predict_score(ticker)
    except Exception as e:
        logger.error(f"[{ticker}] Score prediction error: {e}")
        score_pred = {"error": str(e)}

    # Run WTI prediction
    try:
        wti_pred = _predict_wti(ticker)
    except Exception as e:
        logger.error(f"[{ticker}] WTI prediction error: {e}")
        wti_pred = {"error": str(e)}

    return fmt_prediction(ticker, score_pred, wti_pred)
