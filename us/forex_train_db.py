"""
forex_train_db.py — SQLite database untuk training data ML forex

Terpisah dari train.db saham.
DB path: /home/ec2-user/us/train/forex_train.db

Schema identik dengan train.db saham agar bisa pakai
kode backtest/ML yang sama (dengan modifikasi db path).
"""

import logging
import os
import sqlite3
from datetime import datetime

from config import FOREX_TRAIN_DIR

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(FOREX_TRAIN_DIR, "forex_train.db")

DDL = """
CREATE TABLE IF NOT EXISTS scores (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker        TEXT    NOT NULL,
    date          TEXT    NOT NULL,
    price         REAL,
    change_pct    REAL,
    open          REAL,
    high          REAL,
    low           REAL,
    volume        REAL,
    transactions  INTEGER,
    vsa           INTEGER,
    fsa           INTEGER,
    vfa           INTEGER,
    wcc           INTEGER,
    srst          INTEGER,
    rsi           INTEGER,
    macd          INTEGER,
    ma            INTEGER,
    ip_raw        REAL,
    ip_score      REAL,
    tight         INTEGER,
    total         REAL,
    created_at    TEXT,
    UNIQUE(ticker, date)
);

CREATE INDEX IF NOT EXISTS idx_ticker      ON scores(ticker);
CREATE INDEX IF NOT EXISTS idx_date        ON scores(date);
CREATE INDEX IF NOT EXISTS idx_ticker_date ON scores(ticker, date);
CREATE INDEX IF NOT EXISTS idx_total       ON scores(total);
"""


def _ensure_dir():
    os.makedirs(FOREX_TRAIN_DIR, exist_ok=True)


def _connect() -> sqlite3.Connection:
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_forex_db():
    """Buat tabel dan index jika belum ada."""
    conn = _connect()
    try:
        conn.executescript(DDL)
        conn.commit()
        logger.info(f"Forex DB diinisialisasi: {DB_PATH}")
    finally:
        conn.close()


def reset_forex_db():
    """Hapus dan buat ulang DB forex (dipanggil saat /9)."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        logger.info("Forex DB dihapus.")
    init_forex_db()


def upsert_score_rows(rows: list[dict]):
    """
    Insert atau update banyak row sekaligus (upsert by ticker+date).
    Field 'ticker' di sini dipakai untuk nama pair forex.
    """
    if not rows:
        return

    sql = """
    INSERT INTO scores
        (ticker, date, price, change_pct, open, high, low, volume, transactions,
         vsa, fsa, vfa, wcc, srst, rsi, macd, ma,
         ip_raw, ip_score, tight, total, created_at)
    VALUES
        (:ticker, :date, :price, :change_pct, :open, :high, :low, :volume, :transactions,
         :vsa, :fsa, :vfa, :wcc, :srst, :rsi, :macd, :ma,
         :ip_raw, :ip_score, :tight, :total, :created_at)
    ON CONFLICT(ticker, date) DO UPDATE SET
        price        = excluded.price,
        change_pct   = excluded.change_pct,
        open         = excluded.open,
        high         = excluded.high,
        low          = excluded.low,
        volume       = excluded.volume,
        transactions = excluded.transactions,
        vsa          = excluded.vsa,
        fsa          = excluded.fsa,
        vfa          = excluded.vfa,
        wcc          = excluded.wcc,
        srst         = excluded.srst,
        rsi          = excluded.rsi,
        macd         = excluded.macd,
        ma           = excluded.ma,
        ip_raw       = excluded.ip_raw,
        ip_score     = excluded.ip_score,
        tight        = excluded.tight,
        total        = excluded.total,
        created_at   = excluded.created_at
    """

    now = datetime.utcnow().isoformat()
    prepared = []
    for r in rows:
        prepared.append({
            "ticker":       r.get("ticker", ""),
            "date":         r.get("date", ""),
            "price":        r.get("price", 0.0),
            "change_pct":   r.get("change_pct", r.get("change", 0.0)),
            "open":         r.get("open", 0.0),
            "high":         r.get("high", 0.0),
            "low":          r.get("low", 0.0),
            "volume":       r.get("volume", 0.0),
            "transactions": r.get("transactions", 0),
            "vsa":          r.get("vsa", 0),
            "fsa":          r.get("fsa", 0),
            "vfa":          r.get("vfa", 0),
            "wcc":          r.get("wcc", 0),
            "srst":         r.get("srst", 0),
            "rsi":          r.get("rsi", 0),
            "macd":         r.get("macd", 0),
            "ma":           r.get("ma", 0),
            "ip_raw":       r.get("ip_raw", 0.0),
            "ip_score":     r.get("ip_score", 0.0),
            "tight":        r.get("tight", 0),
            "total":        r.get("total", 0.0),
            "created_at":   now,
        })

    conn = _connect()
    try:
        conn.executemany(sql, prepared)
        conn.commit()
        logger.info(f"[Forex DB] Upsert {len(prepared)} rows")
    except Exception as e:
        logger.error(f"[Forex DB] Gagal upsert: {e}")
        conn.rollback()
    finally:
        conn.close()


def get_score_history(pair: str, limit: int = 300) -> list[dict]:
    """Ambil history score untuk satu pair forex, diurutkan ascending by date."""
    conn = _connect()
    try:
        cursor = conn.execute(
            "SELECT * FROM scores WHERE ticker = ? ORDER BY date ASC LIMIT ?",
            (pair.upper().strip().removeprefix("C:"), limit),
        )
        rows = [dict(r) for r in cursor.fetchall()]
        return rows
    except Exception as e:
        logger.error(f"[Forex DB] Gagal baca history {pair}: {e}")
        return []
    finally:
        conn.close()


def get_ticker_count() -> int:
    """Jumlah pair unik di DB."""
    conn = _connect()
    try:
        row = conn.execute("SELECT COUNT(DISTINCT ticker) FROM scores").fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def get_total_rows() -> int:
    """Total baris di DB."""
    conn = _connect()
    try:
        row = conn.execute("SELECT COUNT(*) FROM scores").fetchone()
        return row[0] if row else 0
    finally:
        conn.close()
