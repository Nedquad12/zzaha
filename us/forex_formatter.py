"""
forex_formatter.py — Format pesan Telegram untuk hasil scoring forex

Dipisah dari formatter.py saham agar pesan forex punya label yang berbeda
(e.g. pakai harga desimal lebih banyak, tidak ada "$" sign, dll).
"""

from datetime import datetime

from config import TOP_N


def fmt_forex_alert(r: dict) -> str:
    """Pesan alert untuk satu pair forex yang lolos threshold."""
    arrow = "🟢" if r["total"] > 0 else "🔴"
    tight_lbl = ""
    t = r.get("tight", 0)
    if t == 2:
        tight_lbl = " 🔥VT+T"
    elif t == 1:
        tight_lbl = " ✨VT"
    pair = r.get("pair", r.get("ticker", ""))
    return (
        f"{arrow} <b>{pair}/USD</b>{tight_lbl}  |  Score: <b>{r['total']:+.1f}</b>\n"
        f"Price: <b>{r['price']:.5f}</b>  ({r['change']:+.4f}%)\n"
        f"VSA:{r['vsa']:+d}  FSA:{r.get('fsa', 0):+d}  VFA:{r.get('vfa', 0):+d}  "
        f"WCC:{r.get('wcc', 0):+d}  SRST:{r.get('srst', 0):+d}  "
        f"RSI:{r['rsi']:+d}  MACD:{r['macd']:+d}  "
        f"MA:{r['ma']:+d}  IP:{r['ip_score']:+.1f}  T:{t:+d}"
    )


def fmt_forex_detail(r: dict) -> str:
    """Detail skor satu pair forex untuk command /scorf atau /ch."""
    t = r.get("tight", 0)
    tight_label = {2: "VT + T ✨", 1: "VT ✨", 0: "T", -1: "None"}.get(t, str(t))
    pair = r.get("pair", r.get("ticker", ""))
    wi   = r.get("_weight_info", {})
    weight_tag = "default (1.0)" if wi.get("is_default", True) else f"ML ({(wi.get('updated_at') or '')[:10]})"
    return (
        f"<b>{pair} — Forex Detail Score</b>\n\n"
        f"<pre>"
        f"Price    : {r['price']:.5f} ({r['change']:+.4f}%)\n"
        f"Weight   : {weight_tag}\n"
        f"\n"
        f"VSA      : {r['vsa']:+d}\n"
        f"FSA      : {r.get('fsa', 0):+d}\n"
        f"VFA      : {r.get('vfa', 0):+d}\n"
        f"WCC      : {r.get('wcc', 0):+d}\n"
        f"SRST     : {r.get('srst', 0):+d}\n"
        f"RSI      : {r['rsi']:+d}\n"
        f"MACD     : {r['macd']:+d}\n"
        f"MA       : {r['ma']:+d}\n"
        f"IP Raw   : {r['ip_raw']:.4f}\n"
        f"IP Score : {r['ip_score']:+.1f}\n"
        f"Tight    : {t:+d}  ({tight_label})\n"
        f"{'─'*22}\n"
        f"TOTAL    : {r['total']:+.2f}"
        f"</pre>"
    )


def _build_forex_table(title: str, pairs: list[dict]) -> str:
    lines = [
        f"<b>{title}</b>",
        "<pre>",
        f"{'#':<3} {'Pair':<10} {'Score':>6}  {'Price':>10}  {'Chg%':>8}  {'T':>3}",
        "─" * 48,
    ]
    for i, r in enumerate(pairs, 1):
        t    = r.get("tight", 0)
        pair = r.get("pair", r.get("ticker", ""))
        lines.append(
            f"{i:<3} {pair:<10} {r['total']:>+6.1f}  "
            f"{r['price']:>10.5f}  {r['change']:>+7.4f}%  {t:>+3d}"
        )
    lines.append("</pre>")
    return "\n".join(lines)


def fmt_forex_top_bottom(results: list[dict], top_n: int = TOP_N) -> list[str]:
    today   = datetime.today().strftime("%Y-%m-%d")
    top_n   = min(top_n, len(results))
    top50   = sorted(results, key=lambda x: x["total"], reverse=True)[:top_n]
    bot50   = sorted(results, key=lambda x: x["total"])[:top_n]

    raw_msgs = [
        _build_forex_table(f"🏆 TOP {top_n} FOREX — {today}", top50),
        _build_forex_table(f"📉 BOTTOM {top_n} FOREX — {today}", bot50),
    ]

    messages = []
    for msg in raw_msgs:
        if len(msg) <= 4000:
            messages.append(msg)
        else:
            lines = msg.split("\n")
            for i in range(0, len(lines), 30):
                messages.append("\n".join(lines[i:i+30]))
    return messages
