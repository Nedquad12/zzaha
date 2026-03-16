"""
backtest.py — Backtest model scoring + XGBoost ML weight adjustment per ticker

Diintegrasikan langsung dengan scorer.py & indicators/ dari proyek IHSG.

Command Telegram:
  /bt TICKER        → backtest dengan weight saat ini
  /bt ml TICKER     → train XGBoost, update weight, kirim perbandingan

Label (close +3 hari ke depan):
  ret >= +0.5%  → label  1 (naik)
  ret <= -0.5%  → label -1 (turun)
  else          → label  0 (netral)

Prediksi model:
  weighted_total >= +5  → prediksi naik
  weighted_total <= -5  → prediksi turun
  else                  → tidak ada sinyal

Cara kerja:
  - _build_history_df() membaca SEMUA file JSON harian, menghitung skor per hari
    menggunakan calculate_all_scores() dari scorer.py, lalu membentuk DataFrame
    time-series lengkap. Tidak perlu score_history atau weight_manager eksternal.
  - Weight disimpan per-ticker di WEIGHT_DIR sebagai JSON.
    Default weight = 1.0 untuk semua fitur (total tidak berubah dari skor asli).

Integrasi ke main.py:
  from backtest import register_bt_handler
  register_bt_handler(app)
"""

import json
import logging
import os
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Path ───────────────────────────────────────────────────────────────────────
JSON_DIR   = "/home/ec2-user/database/json"
WEIGHT_DIR = "/home/ec2-user/database/weights"   # folder simpan weight per ticker

# ── Daftar fitur (harus cocok dengan key dict calculate_all_scores) ────────────
FEATURES = [
    "vsa", "fsa", "vfa", "wcc",
    "rsi", "macd", "ma", "ip_score",
    "srst", "tight", "fbs",
    "mgn", "brk", "own",
]

DEFAULT_WEIGHTS: dict = {f: 1.0 for f in FEATURES}

# ── Konstanta backtest ─────────────────────────────────────────────────────────
LABEL_UP_PCT   =  0.005   # +0.5% → label naik
LABEL_DOWN_PCT = -0.005   # -0.5% → label turun
SIGNAL_UP      =  5.0     # threshold prediksi naik  (skala total score asli)
SIGNAL_DOWN    = -5.0     # threshold prediksi turun
LOOKAHEAD      =  3       # bar ke depan untuk cek outcome
MAX_DAYS       =  120     # maksimal hari history yang diambil


# ══════════════════════════════════════════════════════════════════════════════
#  Weight helpers
# ══════════════════════════════════════════════════════════════════════════════

def _weight_path(ticker: str) -> str:
    os.makedirs(WEIGHT_DIR, exist_ok=True)
    return os.path.join(WEIGHT_DIR, f"{ticker.upper()}.json")


def load_weights(ticker: str) -> dict:
    path = _weight_path(ticker)
    if os.path.exists(path):
        try:
            with open(path) as f:
                data = json.load(f)
            # Pastikan semua fitur ada; isi default jika kurang
            return {feat: data.get(feat, 1.0) for feat in FEATURES}
        except Exception as e:
            logger.warning(f"[{ticker}] Gagal baca weight: {e}")
    return dict(DEFAULT_WEIGHTS)


def save_weights(ticker: str, weights: dict) -> None:
    path = _weight_path(ticker)
    try:
        with open(path, "w") as f:
            json.dump(weights, f, indent=2)
        logger.info(f"[{ticker}] Weight disimpan → {path}")
    except Exception as e:
        logger.error(f"[{ticker}] Gagal simpan weight: {e}")


def _is_default_weight(weights: dict) -> bool:
    return all(abs(weights.get(f, 1.0) - 1.0) < 0.001 for f in FEATURES)


# ══════════════════════════════════════════════════════════════════════════════
#  Build history DataFrame
# ══════════════════════════════════════════════════════════════════════════════

def _build_history_df(ticker: str, json_dir: str = JSON_DIR) -> Optional[pd.DataFrame]:
    """
    Hitung skor per hari untuk ticker menggunakan scorer.py.

    Cara kerja:
      Untuk setiap file JSON (hari bursa), kita panggil calculate_all_scores()
      dengan data hingga hari itu saja (sliding window max_days=60).
      Hasilnya dikumpulkan menjadi DataFrame time-series.

    Returns:
      DataFrame dengan kolom: date, price, + semua FEATURES + label
      None jika data tidak cukup.
    """
    # Import di sini agar tidak circular jika backtest.py dipakai standalone
    import glob
    from datetime import date as date_type
    from indicators.loader import build_stock_df
    from indicators import (
        score_vsa, score_fsa, score_vfa,
        score_wcc, score_rsi, score_macd, score_ma,
        calculate_ip, score_ip, score_srst,
        score_tight, score_fbs,
        score_mgn, score_brk, score_own,
    )
    from cache_manager import get_mgn_cache, get_brk_cache, get_own_cache

    ticker = ticker.upper()

    # Ambil semua file JSON, urutkan ascending
    all_files = sorted(glob.glob(os.path.join(json_dir, "*.json")))
    if not all_files:
        logger.warning(f"[{ticker}] Tidak ada file JSON di {json_dir}")
        return None

    # Ambil N hari terakhir saja
    all_files = all_files[-MAX_DAYS:]

    # Cache eksternal (baca sekali)
    mgn_cache = get_mgn_cache()
    brk_cache = get_brk_cache()
    own_cache = get_own_cache()

    rows = []

    # Untuk setiap hari, build DataFrame s/d hari itu lalu hitung skor
    for i, fpath in enumerate(all_files):
        # Gunakan semua file s/d hari ini sebagai window
        window_files = all_files[: i + 1]
        # Batasi window ke 60 hari supaya konsisten dengan scorer.py
        window_files = window_files[-60:]

        try:
            df = build_stock_df(ticker, json_dir=None, max_days=60)
            # build_stock_df butuh json_dir sebagai folder, bukan list file.
            # Kita pakai pendekatan langsung: baca hanya file-file dalam window.
            df = _build_df_from_files(ticker, window_files)
        except Exception:
            df = _build_df_from_files(ticker, window_files)

        if df is None or df.empty:
            continue

        try:
            # Tanggal baris ini = tanggal file terakhir dalam window
            from indicators.loader import _parse_date_from_filename
            row_date = _parse_date_from_filename(window_files[-1])
            if row_date is None:
                continue

            # Cek apakah ticker ada di file hari ini
            price = float(df["close"].iloc[-1])
            if price == 0:
                continue

            # ── Hitung semua skor ────────────────────────────────────────────
            vsa    = score_vsa(df)
            fsa    = score_fsa(df)
            vfa    = score_vfa(df)
            wcc    = score_wcc(df)
            rsi    = score_rsi(df)
            macd   = score_macd(df)
            ma     = score_ma(df)
            ip_raw = calculate_ip(df)
            ip_pts = score_ip(ip_raw)
            srst   = score_srst(df)
            tight  = score_tight(df)
            fbs    = score_fbs(df)
            mgn    = score_mgn(ticker, mgn_cache)
            brk    = score_brk(ticker, brk_cache)
            own    = score_own(ticker, own_cache)

            rows.append({
                "date":     row_date,
                "price":    price,
                "vsa":      vsa,
                "fsa":      fsa,
                "vfa":      vfa,
                "wcc":      wcc,
                "rsi":      rsi,
                "macd":     macd,
                "ma":       ma,
                "ip_score": ip_pts,
                "srst":     srst,
                "tight":    tight,
                "fbs":      fbs,
                "mgn":      mgn,
                "brk":      brk,
                "own":      own,
            })

        except Exception as e:
            logger.debug(f"[{ticker}] Skip hari {fpath}: {e}")
            continue

    if len(rows) < LOOKAHEAD + 5:
        logger.warning(f"[{ticker}] Data terlalu sedikit: {len(rows)} baris")
        return None

    df_hist = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)

    # ── Tambahkan label (close +LOOKAHEAD bar) ─────────────────────────────
    prices = df_hist["price"].values
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
            labels.append(None)

    df_hist["label"] = labels
    df_hist = df_hist[df_hist["label"].notna()].copy()
    df_hist["label"] = df_hist["label"].astype(int)

    return df_hist


def _build_df_from_files(ticker: str, file_list: list) -> Optional[pd.DataFrame]:
    """
    Bangun DataFrame satu ticker dari list file JSON tertentu.
    Versi internal agar bisa pakai sliding window.
    """
    import json as _json
    from datetime import date as date_type

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
        "value", "prev_close", "change", "foreign_buy", "foreign_sell",
    ]

    def _parse_date(fname):
        base = os.path.basename(fname).replace(".json", "")
        try:
            if len(base) == 6:
                d = int(base[:2]); m = int(base[2:4]); y = 2000 + int(base[4:6])
                from datetime import date as _d
                return _d(y, m, d)
        except Exception:
            pass
        return None

    rows = []
    for fpath in file_list:
        file_date = _parse_date(fpath)
        if file_date is None:
            continue
        try:
            with open(fpath, encoding="utf-8") as f:
                records = _json.load(f)
        except Exception:
            continue
        for rec in records:
            kode = str(rec.get("Kode Saham", "")).strip().upper()
            if kode != ticker:
                continue
            row = {"date": file_date}
            for xlsx_col, std_col in COL_MAP.items():
                row[std_col] = rec.get(xlsx_col, 0)
            rows.append(row)
            break

    if not rows:
        return None

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return df


# ══════════════════════════════════════════════════════════════════════════════
#  Evaluasi / metrik
# ══════════════════════════════════════════════════════════════════════════════

def _compute_weighted_totals(df: pd.DataFrame, weights: dict) -> np.ndarray:
    totals = np.zeros(len(df))
    for feat in FEATURES:
        w = float(weights.get(feat, 1.0))
        totals += df[feat].astype(float).values * w
    return totals


def _evaluate(df: pd.DataFrame, weights: dict) -> dict:
    totals = _compute_weighted_totals(df, weights)
    labels = df["label"].values

    pred_up   = totals >= SIGNAL_UP
    pred_down = totals <= SIGNAL_DOWN
    pred_none = ~pred_up & ~pred_down

    n_total     = len(df)
    n_signal_up = int(pred_up.sum())
    n_signal_dn = int(pred_down.sum())
    n_no_signal = int(pred_none.sum())

    if n_signal_up > 0:
        tp_up      = int(((pred_up) & (labels == 1)).sum())
        prec_up    = tp_up / n_signal_up
        winrate_up = prec_up
    else:
        tp_up = 0; prec_up = winrate_up = 0.0

    if n_signal_dn > 0:
        tp_dn      = int(((pred_down) & (labels == -1)).sum())
        prec_dn    = tp_dn / n_signal_dn
        winrate_dn = prec_dn
    else:
        tp_dn = 0; prec_dn = winrate_dn = 0.0

    n_signal_total = n_signal_up + n_signal_dn
    accuracy = (tp_up + tp_dn) / n_signal_total if n_signal_total > 0 else 0.0

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
        "score_mean":   float(np.mean(totals)),
        "score_std":    float(np.std(totals)),
        "score_max":    float(np.max(totals)),
        "score_min":    float(np.min(totals)),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Formatter output Telegram
# ══════════════════════════════════════════════════════════════════════════════

def _fmt_metrics(ticker: str, m: dict, weights: dict) -> str:
    is_default = _is_default_weight(weights)
    weight_tag = "default (1.0 semua)" if is_default else "ML (custom)"

    lines = [
        f"📊 <b>Backtest {ticker}</b>",
        f"─────────────────────────",
        f"⚙️ Weight  : <code>{weight_tag}</code>",
        f"📅 Data    : <b>{m['n_bars']}</b> bar  |  Lookahead: {LOOKAHEAD} hari",
        f"",
        f"<b>Label Aktual (close +{LOOKAHEAD} hari):</b>",
        f"  ▲ Naik   : {m['n_label_up']} bar ({m['n_label_up']/m['n_bars']*100:.1f}%)",
        f"  ▼ Turun  : {m['n_label_dn']} bar ({m['n_label_dn']/m['n_bars']*100:.1f}%)",
        f"  ─ Netral : {m['n_label_nt']} bar ({m['n_label_nt']/m['n_bars']*100:.1f}%)",
        f"",
        f"<b>Sinyal Model (threshold ≥{SIGNAL_UP:.0f} / ≤{SIGNAL_DOWN:.0f}):</b>",
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
        f"<b>Distribusi Score (weighted total):</b>",
        f"  Mean: {m['score_mean']:+.2f} | Std: {m['score_std']:.2f}",
        f"  Max : {m['score_max']:+.2f} | Min: {m['score_min']:+.2f}",
    ]
    return "\n".join(lines)


def _fmt_comparison(ticker: str, m_before: dict, m_after: dict,
                    w_before: dict, w_after: dict,
                    importances: dict) -> list[str]:

    def arrow(d): return "▲" if d > 0 else ("▼" if d < 0 else "─")

    delta_acc = (m_after["accuracy"]   - m_before["accuracy"])   * 100
    delta_wu  = (m_after["winrate_up"] - m_before["winrate_up"]) * 100
    delta_wd  = (m_after["winrate_dn"] - m_before["winrate_dn"]) * 100

    msg1_lines = [
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
        f"<b>Delta:</b>",
        f"  {arrow(delta_acc)} Accuracy : {delta_acc:+.1f}%",
        f"  {arrow(delta_wu)} Win ▲    : {delta_wu:+.1f}%",
        f"  {arrow(delta_wd)} Win ▼    : {delta_wd:+.1f}%",
        f"",
        f"✅ Weight baru disimpan ke <code>{_weight_path(ticker)}</code>",
        f"✅ Berlaku untuk semua scoring {ticker} berikutnya",
    ]

    sorted_feats = sorted(importances.items(), key=lambda x: x[1], reverse=True)
    msg2_lines = [
        f"📐 <b>Feature Importance → Weight Baru ({ticker})</b>",
        f"─────────────────────────",
    ]
    for feat, imp in sorted_feats:
        w_old = w_before.get(feat, 1.0)
        w_new = w_after.get(feat, 1.0)
        delta = w_new - w_old
        aw    = "▲" if delta > 0.001 else ("▼" if delta < -0.001 else "─")
        bar   = "█" * min(int(imp * 20), 10) + "░" * (10 - min(int(imp * 20), 10))
        msg2_lines.append(
            f"  {feat:<10} imp={imp:.3f}  [{bar}]  "
            f"w: {w_old:+.3f} → <b>{w_new:+.3f}</b> {aw}"
        )

    return ["\n".join(msg1_lines), "\n".join(msg2_lines)]


# ══════════════════════════════════════════════════════════════════════════════
#  Public API
# ══════════════════════════════════════════════════════════════════════════════

def run_backtest(ticker: str, json_dir: str = JSON_DIR) -> str:
    """
    Backtest model dengan weight saat ini untuk ticker.

    Returns:
        str pesan Telegram HTML
    """
    ticker = ticker.upper()

    df = _build_history_df(ticker, json_dir)
    if df is None:
        return (
            f"❌ <b>{ticker}</b>: Data tidak cukup untuk backtest.\n"
            f"Pastikan JSON harian sudah di-reload dan ticker valid."
        )

    weights = load_weights(ticker)
    metrics = _evaluate(df, weights)
    return _fmt_metrics(ticker, metrics, weights)


def run_ml(ticker: str, json_dir: str = JSON_DIR) -> list[str]:
    """
    Train XGBoost pada data ticker, update weight, kirim perbandingan.

    Returns:
        list[str] pesan Telegram HTML (2 pesan: summary + feature table)
    """
    ticker = ticker.upper()

    try:
        from xgboost import XGBClassifier
    except ImportError:
        return ["❌ XGBoost belum terinstall.\nJalankan: <code>pip install xgboost</code>"]

    df = _build_history_df(ticker, json_dir)
    if df is None:
        return [
            f"❌ <b>{ticker}</b>: Data tidak cukup untuk training.\n"
            f"Pastikan JSON harian sudah di-reload dan ticker valid."
        ]

    if len(df) < 30:
        return [
            f"❌ <b>{ticker}</b>: Data terlalu sedikit ({len(df)} bar).\n"
            f"Minimal 30 bar diperlukan untuk training."
        ]

    # Backtest SEBELUM ML
    w_before = load_weights(ticker)
    m_before = _evaluate(df, w_before)

    # ── Persiapan data training ────────────────────────────────────────────
    X     = df[FEATURES].astype(float).values
    y_raw = df["label"].values   # -1, 0, 1
    y     = y_raw + 1            # shift → 0, 1, 2 untuk XGBoost multi-class

    # Split 70/30 berdasarkan urutan waktu (tidak di-shuffle)
    split = int(len(X) * 0.7)
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]

    # ── Train XGBoost ──────────────────────────────────────────────────────
    model = XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric="mlogloss",
        random_state=42,
        verbosity=0,
        num_class=3,
        objective="multi:softmax",
        use_label_encoder=False,
    )
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

    # ── Feature importances → weight baru ──────────────────────────────────
    raw_imp    = model.feature_importances_
    importances = {FEATURES[i]: float(raw_imp[i]) for i in range(len(FEATURES))}
    mean_imp   = float(np.mean(raw_imp))

    if mean_imp > 0:
        w_new = {feat: round(float(imp) / mean_imp, 6)
                 for feat, imp in importances.items()}
    else:
        w_new = dict(DEFAULT_WEIGHTS)

    save_weights(ticker, w_new)

    # Backtest SESUDAH ML
    m_after = _evaluate(df, w_new)

    return _fmt_comparison(ticker, m_before, m_after, w_before, w_new, importances)


# ══════════════════════════════════════════════════════════════════════════════
#  Telegram handler
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_bt(update, context) -> None:
    """
    /bt TICKER        → backtest dengan weight saat ini
    /bt ml TICKER     → train XGBoost + update weight
    """
    from telegram.constants import ParseMode
    from admin.auth import is_authorized_user, is_vip_user
    import asyncio

    uid = update.effective_user.id
    if not (is_authorized_user(uid) or is_vip_user(uid)):
        await update.message.reply_text("⛔ Kamu tidak punya akses ke fitur ini.")
        return

    args = context.args  # list kata setelah /bt

    # ── /bt ml TICKER ──────────────────────────────────────────────────────
    if args and args[0].lower() == "ml":
        if len(args) < 2:
            await update.message.reply_text(
                "⚠️ Gunakan: <code>/bt ml KODE</code>\nContoh: <code>/bt ml BBCA</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        ticker = args[1].upper()
        msg = await update.message.reply_text(
            f"⏳ Training XGBoost untuk <b>{ticker}</b>…",
            parse_mode=ParseMode.HTML,
        )

        results = await asyncio.get_event_loop().run_in_executor(
            None, run_ml, ticker
        )

        await msg.delete()
        for text in results:
            await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return

    # ── /bt TICKER ─────────────────────────────────────────────────────────
    if not args:
        await update.message.reply_text(
            "⚠️ Gunakan: <code>/bt KODE</code> atau <code>/bt ml KODE</code>\n"
            "Contoh: <code>/bt BBCA</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    ticker = args[0].upper()
    msg = await update.message.reply_text(
        f"⏳ Menghitung backtest <b>{ticker}</b>…",
        parse_mode=ParseMode.HTML,
    )

    result = await asyncio.get_event_loop().run_in_executor(
        None, run_backtest, ticker
    )

    await msg.edit_text(result, parse_mode=ParseMode.HTML)


def register_bt_handler(app) -> None:
    """Daftarkan handler /bt ke Application. Panggil dari main.py."""
    from telegram.ext import CommandHandler
    app.add_handler(CommandHandler("bt", cmd_bt))
