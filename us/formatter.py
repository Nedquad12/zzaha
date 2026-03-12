"""
formatter.py — Format pesan Telegram dari data skor saham
"""

from datetime import datetime

from config import TOP_N


def fmt_alert(r: dict) -> str:
    """Pesan alert untuk satu saham yang lolos threshold."""
    arrow = "🟢" if r["total"] > 0 else "🔴"
    tight_lbl = ""
    t = r.get("tight", 0)
    if t == 2:
        tight_lbl = " 🔥VT+T"
    elif t == 1:
        tight_lbl = " ✨VT"
    return (
        f"{arrow} <b>{r['ticker']}</b>{tight_lbl}  |  Score: <b>{r['total']:+.1f}</b>\n"
        f"Price: <b>${r['price']:.2f}</b>  ({r['change']:+.2f}%)\n"
        f"VSA:{r['vsa']:+d}  RSI:{r['rsi']:+d}  MACD:{r['macd']:+d}  "
        f"MA:{r['ma']:+d}  IP:{r['ip_score']:+.1f}  T:{t:+d}"
    )


def fmt_detail(r: dict) -> str:
    """Detail skor satu saham untuk command /ip TICKER."""
    t = r.get("tight", 0)
    tight_label = {2: "VT + T ✨", 1: "VT ✨", 0: "T", -1: "None"}.get(t, str(t))
    return (
        f"<b>{r['ticker']} — Detail Score</b>\n\n"
        f"<pre>"
        f"Price    : ${r['price']:.2f} ({r['change']:+.2f}%)\n"
        f"\n"
        f"VSA      : {r['vsa']:+d}\n"
        f"RSI      : {r['rsi']:+d}\n"
        f"MACD     : {r['macd']:+d}\n"
        f"MA       : {r['ma']:+d}\n"
        f"IP Raw   : {r['ip_raw']:.2f}\n"
        f"IP Score : {r['ip_score']:+.1f}\n"
        f"Tight    : {t:+d}  ({tight_label})\n"
        f"{'─'*22}\n"
        f"TOTAL    : {r['total']:+.2f}"
        f"</pre>"
    )


def _build_table(title: str, stocks: list[dict]) -> str:
    lines = [
        f"<b>{title}</b>",
        "<pre>",
        f"{'#':<3} {'Ticker':<7} {'Score':>6}  {'Price':>8}  {'Chg%':>7}  {'T':>3}",
        "─" * 44,
    ]
    for i, r in enumerate(stocks, 1):
        t = r.get("tight", 0)
        lines.append(
            f"{i:<3} {r['ticker']:<7} {r['total']:>+6.1f}  "
            f"${r['price']:>7.2f}  {r['change']:>+6.2f}%  {t:>+3d}"
        )
    lines.append("</pre>")
    return "\n".join(lines)


def fmt_top_bottom(results: list[dict], top_n: int = TOP_N) -> list[str]:
    today    = datetime.today().strftime("%Y-%m-%d")
    top50    = sorted(results, key=lambda x: x["total"], reverse=True)[:top_n]
    bottom50 = sorted(results, key=lambda x: x["total"])[:top_n]

    raw_msgs = [
        _build_table(f"🏆 TOP {top_n} SAHAM — {today}",    top50),
        _build_table(f"📉 BOTTOM {top_n} SAHAM — {today}", bottom50),
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


def fmt_ip_table(rows: list[dict]) -> list[str]:
    today  = datetime.today().strftime("%Y-%m-%d")
    header = [
        f"<b>📊 IP Scores — {today}</b>",
        "<pre>",
        f"{'Ticker':<7} {'Total':>6}  {'IP':>5}  {'VSA':>4}  {'RSI':>4}  {'MACD':>5}  {'MA':>4}  {'T':>3}",
        "─" * 52,
    ]

    data_lines = []
    for r in rows:
        t = r.get("tight", 0)
        data_lines.append(
            f"{r['ticker']:<7} {r['total']:>+6.1f}  {r['ip_score']:>+5.1f}  "
            f"{r['vsa']:>+4d}  {r['rsi']:>+4d}  {r['macd']:>+5d}  {r['ma']:>+4d}  {t:>+3d}"
        )

    messages   = []
    batch_size = 40

    for i in range(0, len(data_lines), batch_size):
        batch = data_lines[i:i+batch_size]
        if i == 0:
            msg = "\n".join(header + batch + ["</pre>"])
        else:
            msg = "<pre>\n" + "\n".join(batch) + "\n</pre>"
        messages.append(msg)

    return messages if messages else ["<i>Belum ada data.</i>"]
