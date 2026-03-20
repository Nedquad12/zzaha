"""
ai_analyst.py — Evaluasi model scoring oleh DeepSeek R1

Dipanggil via: /ch ts bt ai TICKER
"""

import logging
import os
from typing import Optional

import requests

from config import DEEPSEEK_API_KEY
from score_history import load_score_history
from weight_manager import load_weights, FEATURES, get_weights_info
from backtest import _build_df, _evaluate, SIGNAL_UP, SIGNAL_DOWN

logger = logging.getLogger(__name__)

DEEPSEEK_URL   = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-reasoner"
MAX_TOKENS     = 1024
BARS_TO_SEND   = 30


SYSTEM_PROMPT = """You are a quantitative analyst evaluating a stock scoring model for short-term US equity trading.

The model scores each trading day using 10 indicators. Each score is multiplied by a per-indicator weight (default 1.0) and summed into a total weighted score.
- Signal BUY  : total >= +{up}
- Signal SELL : total <= {down}
- Target       : will stock close >= +0.5% in 3 trading days?

INDICATORS (name: score range, what it measures):
- VSA  : [-2, +2]  Avg 7-day vs 30-day volume ratio
- FSA  : [-2, +2]  Transaction frequency trend vs volume trend
- VFA  : [-3, +3]  Daily % change of volume vs transaction count over 7 days
- WCC  : [-2, +2]  Candle body direction vs wick ratio
- SRST : [-4, +3]  Proximity and strength of nearest Support/Resistance zone
- RSI  : [-1, +2]  RSI-14: >70=-1, 50-70=0, 30-50=+1, <30=+2
- MACD : [-2, +2]  MACD(12,26,9): line vs signal + line vs zero
- MA   : [-2, +2]  How many of MA3/5/10/20/50/200 price is above
- IP   : [-4, +4]  Avg of (MACD+Stoch) across daily/weekly/monthly timeframes
- Tight: [-1, +2]  Price proximity to MA3/5/10/20: VT+T=+2, VT=+1, T=0, none=-1

Your task:
1. Is this model reliable for this stock? (based on win rate, accuracy, signal count)
2. Which indicators appear noisy or contradictory in the recent 30 bars?
3. Specific actionable recommendation: which to upweight/downweight, or threshold change?

OUTPUT RULES:
- Use abbreviations only: VSA, FSA, VFA, WCC, SRST, RSI, MACD, MA, IP, Tight
- Be concise. Max 3-4 short paragraphs. No bullet-point walls.
- Do NOT explain what indicators mean
- Write in Indonesian
""".format(up=int(SIGNAL_UP), down=int(SIGNAL_DOWN))


def _build_bar_table(history: list[dict], n: int = BARS_TO_SEND) -> str:
    recent = history[-n:]
    lines  = ["Date        Price   Chg%  VSA FSA VFA WCC SRST RSI MACD MA   IP Tght Total"]
    lines += ["─" * 80]
    for h in recent:
        lines.append(
            f"{h['date']:<12}"
            f"{h.get('price', 0):>7.2f} "
            f"{h.get('change_pct', 0):>+5.2f} "
            f"{int(h.get('vsa',      0)):>+3d} "
            f"{int(h.get('fsa',      0)):>+3d} "
            f"{int(h.get('vfa',      0)):>+3d} "
            f"{int(h.get('wcc',      0)):>+3d} "
            f"{int(h.get('srst',     0)):>+4d} "
            f"{int(h.get('rsi',      0)):>+3d} "
            f"{int(h.get('macd',     0)):>+4d} "
            f"{int(h.get('ma',       0)):>+3d} "
            f"{float(h.get('ip_score', 0)):>+4.1f} "
            f"{int(h.get('tight',    0)):>+4d} "
            f"{float(h.get('total',  0)):>+6.2f}"
        )
    return "\n".join(lines)


def _build_weight_table(weights: dict) -> str:
    lines = ["Indicator | Weight"]
    lines += ["─" * 22]
    for feat in FEATURES:
        lines.append(f"{feat:<10}| {weights.get(feat, 1.0):+.4f}")
    return "\n".join(lines)


def run_ai_analysis(ticker: str) -> list[str]:
    ticker = ticker.upper()

    # ── Load data ─────────────────────────────────────────────────────────
    history = load_score_history(ticker)
    if not history or len(history) < 10:
        return [f"❌ <b>{ticker}</b>: Tidak ada score history. Jalankan /9 terlebih dahulu."]

    # ── Backtest metrics ──────────────────────────────────────────────────
    df      = _build_df(ticker)
    weights = load_weights(ticker)
    wi      = get_weights_info(ticker)

    if df is not None and len(df) >= 10:
        m            = _evaluate(df, weights)
        has_metrics  = True
        metrics_text = (
            f"Total bars   : {m['n_bars']}\n"
            f"Label up     : {m['n_label_up']} ({m['n_label_up']/m['n_bars']*100:.1f}%)\n"
            f"Label down   : {m['n_label_dn']} ({m['n_label_dn']/m['n_bars']*100:.1f}%)\n"
            f"Label neutral: {m['n_label_nt']} ({m['n_label_nt']/m['n_bars']*100:.1f}%)\n"
            f"Signal up    : {m['n_signal_up']} | Precision: {m['prec_up']*100:.1f}%\n"
            f"Signal down  : {m['n_signal_dn']} | Precision: {m['prec_dn']*100:.1f}%\n"
            f"No signal    : {m['n_no_signal']}\n"
            f"Accuracy     : {m['accuracy']*100:.1f}%\n"
            f"Win rate ▲   : {m['winrate_up']*100:.1f}%\n"
            f"Win rate ▼   : {m['winrate_dn']*100:.1f}%\n"
            f"Score mean   : {m['score_mean']:+.2f} | std: {m['score_std']:.2f}\n"
            f"Score range  : {m['score_min']:+.2f} to {m['score_max']:+.2f}"
        )
    else:
        has_metrics  = False
        m            = {}
        metrics_text = "Backtest tidak tersedia (data terlalu sedikit)."

    is_default   = wi.get("is_default", True)
    weight_label = "default (all 1.0)" if is_default else f"ML-adjusted ({(wi.get('updated_at') or '')[:10]})"

    # ── Susun user prompt ─────────────────────────────────────────────────
    user_prompt = (
        f"Stock: {ticker}\n\n"
        f"=== WEIGHTS ({weight_label}) ===\n"
        f"{_build_weight_table(weights)}\n\n"
        f"=== BACKTEST METRICS (signal threshold ±{int(SIGNAL_UP)}) ===\n"
        f"{metrics_text}\n\n"
        f"=== LAST {BARS_TO_SEND} BARS ===\n"
        f"{_build_bar_table(history)}\n\n"
        f"Evaluate reliability, identify noisy indicators, and give adjustment recommendation."
    )

    # ── Panggil DeepSeek ──────────────────────────────────────────────────
    try:
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type":  "application/json",
        }
        payload = {
            "model":      DEEPSEEK_MODEL,
            "max_tokens": MAX_TOKENS,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
        }

        resp = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()

        # DeepSeek reasoner bisa punya reasoning_content + content
        # Yang dikirim ke user hanya content (final answer)
        choice  = data["choices"][0]["message"]
        ai_text = (choice.get("content") or "").strip()

        # Fallback: kalau content kosong coba reasoning_content
        if not ai_text:
            ai_text = (choice.get("reasoning_content") or "").strip()

        if not ai_text:
            logger.error(f"[{ticker}] DeepSeek response kosong: {data}")
            return [f"❌ DeepSeek tidak memberikan respons. Coba lagi."]

    except requests.exceptions.Timeout:
        return ["❌ DeepSeek timeout (>120 detik). Coba lagi."]
    except requests.exceptions.HTTPError as e:
        return [f"❌ DeepSeek API error: {e}"]
    except Exception as e:
        logger.error(f"[{ticker}] DeepSeek error: {e}")
        return [f"❌ Error memanggil DeepSeek: {e}"]

    # ── Format header ─────────────────────────────────────────────────────
    if has_metrics:
        header = (
            f"🤖 <b>AI Analysis — {ticker}</b>\n"
            f"─────────────────────────\n"
            f"Model  : DeepSeek R1 | {BARS_TO_SEND} bar terakhir\n"
            f"Weight : <code>{weight_label}</code>\n"
            f"Acc    : <b>{m['accuracy']*100:.1f}%</b>  "
            f"Win▲: <b>{m['winrate_up']*100:.1f}%</b>  "
            f"Win▼: <b>{m['winrate_dn']*100:.1f}%</b>\n"
            f"─────────────────────────\n\n"
        )
    else:
        header = (
            f"🤖 <b>AI Analysis — {ticker}</b>\n"
            f"─────────────────────────\n"
            f"Model  : DeepSeek R1 | {BARS_TO_SEND} bar terakhir\n"
            f"─────────────────────────\n\n"
        )

    # ── Split pesan jika terlalu panjang ──────────────────────────────────
    messages = []

    # Kirim header + ai_text dalam 1 pesan kalau muat
    full = header + ai_text
    if len(full) <= 4000:
        messages.append(full)
    else:
        # Header dulu
        messages.append(header)
        # AI text dipecah per 3800 char di batas baris
        chunk = ""
        for line in ai_text.split("\n"):
            if len(chunk) + len(line) + 1 > 3800:
                if chunk.strip():
                    messages.append(chunk.strip())
                chunk = line + "\n"
            else:
                chunk += line + "\n"
        if chunk.strip():
            messages.append(chunk.strip())

    return messages
