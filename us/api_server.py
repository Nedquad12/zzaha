"""
api_server.py — FastAPI backend untuk Stock Scoring Web Dashboard

RAM cache: semua data dari 500/*.json di-load ke memory saat startup / reload.
Auth: JWT hardcode dari config (WEB_USER / WEB_PASS).

Run:
    uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

# ── Config (ganti sesuai .env atau config.py) ─────────────────────────────────
OHLCV_500_DIR = "/home/ec2-user/us/500"
TRAIN_DIR     = "/home/ec2-user/us/train"

WEB_USER      = "admin"
WEB_PASS      = "supersecret123"
JWT_SECRET    = "ganti-ini-dengan-random-string-panjang"
JWT_ALGO      = "HS256"
JWT_EXP_HOURS = 24

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── RAM Cache ─────────────────────────────────────────────────────────────────
_ram: dict[str, dict] = {}         # ticker → full JSON payload
_last_reload: float   = 0.0


def load_all_to_ram() -> int:
    global _last_reload
    loaded = 0
    base = Path(OHLCV_500_DIR)
    if not base.exists():
        logger.warning(f"500 dir tidak ditemukan: {OHLCV_500_DIR}")
        return 0
    for f in base.glob("*.json"):
        ticker = f.stem.upper()
        try:
            with open(f, "r") as fp:
                _ram[ticker] = json.load(fp)
            loaded += 1
        except Exception as e:
            logger.error(f"[{ticker}] Gagal load: {e}")
    _last_reload = time.time()
    logger.info(f"RAM cache: {loaded} tickers loaded")
    return loaded


def get_summary_row(ticker: str) -> Optional[dict]:
    """Ambil 1 baris summary (bar terakhir) dari RAM cache."""
    payload = _ram.get(ticker)
    if not payload or not payload.get("data"):
        return None
    last = payload["data"][-1]
    return {
        "ticker":   ticker,
        "date":     last.get("date"),
        "price":    last.get("price"),
        "change":   last.get("change_pct"),
        "vsa":      last.get("vsa", 0),
        "fsa":      last.get("fsa", 0),
        "vfa":      last.get("vfa", 0),
        "wcc":      last.get("wcc", 0),
        "srst":     last.get("srst", 0),
        "rsi":      last.get("rsi", 0),
        "macd":     last.get("macd", 0),
        "ma":       last.get("ma", 0),
        "ip_score": last.get("ip_score", 0),
        "tight":    last.get("tight", 0),
        "total":    last.get("total", 0),
    }


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="Stock Scoring API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # restrict ke domain lo di production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    n = load_all_to_ram()
    logger.info(f"Startup: {n} tickers in RAM")


# ── Auth ──────────────────────────────────────────────────────────────────────
security = HTTPBearer()


class LoginRequest(BaseModel):
    username: str
    password: str


def create_token(username: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=JWT_EXP_HOURS)
    return jwt.encode({"sub": username, "exp": exp}, JWT_SECRET, algorithm=JWT_ALGO)


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGO])
        return payload["sub"]
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalid")


@app.post("/auth/login")
async def login(req: LoginRequest):
    if req.username != WEB_USER or req.password != WEB_PASS:
        raise HTTPException(status_code=401, detail="Username atau password salah")
    token = create_token(req.username)
    return {"access_token": token, "token_type": "bearer", "expires_in": JWT_EXP_HOURS * 3600}


# ── Internal (dipanggil bot Telegram) ────────────────────────────────────────
@app.post("/internal/reload")
async def internal_reload():
    n = load_all_to_ram()
    return {
        "ok":          True,
        "tickers":     n,
        "reloaded_at": datetime.now(timezone.utc).isoformat(),
    }


# ── API Endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/status")
async def api_status(_: str = Depends(verify_token)):
    """RAM cache status + market hours."""
    now_et = datetime.now(timezone.utc) - timedelta(hours=5)  # ET approximation
    market_open = (
        now_et.weekday() < 5 and
        9 * 60 + 30 <= now_et.hour * 60 + now_et.minute <= 16 * 60
    )
    return {
        "tickers_loaded": len(_ram),
        "last_reload":    datetime.fromtimestamp(_last_reload).isoformat() if _last_reload else None,
        "market_open":    market_open,
        "server_time":    datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/leaderboard")
async def leaderboard(
    sort_by:   str = "total",
    direction: str = "desc",
    limit:     int = 50,
    _: str = Depends(verify_token),
):
    """Leaderboard semua ticker berdasarkan score terakhir."""
    valid_fields = {"total", "vsa", "fsa", "vfa", "wcc", "srst", "rsi", "macd", "ma", "ip_score", "tight", "change", "price"}
    if sort_by not in valid_fields:
        sort_by = "total"

    rows = []
    for ticker in _ram:
        row = get_summary_row(ticker)
        if row:
            rows.append(row)

    reverse = direction == "desc"
    rows.sort(key=lambda x: (x.get(sort_by) or 0), reverse=reverse)

    return {
        "data":       rows[:limit],
        "total":      len(rows),
        "sort_by":    sort_by,
        "direction":  direction,
        "updated_at": datetime.fromtimestamp(_last_reload).isoformat() if _last_reload else None,
    }


@app.get("/api/ticker/{ticker}")
async def ticker_detail(ticker: str, _: str = Depends(verify_token)):
    """Detail lengkap 1 ticker: summary + score history 300 bar."""
    ticker = ticker.upper()
    payload = _ram.get(ticker)
    if not payload:
        raise HTTPException(status_code=404, detail=f"{ticker} tidak ditemukan di cache")

    summary = get_summary_row(ticker)
    return {
        "ticker":  ticker,
        "summary": summary,
        "history": payload.get("data", []),
        "total_bars": payload.get("total_bars", 0),
        "generated_at": payload.get("generated_at"),
    }


@app.get("/api/tickers")
async def list_tickers(_: str = Depends(verify_token)):
    """List semua ticker yang tersedia di RAM."""
    return {"tickers": sorted(_ram.keys()), "count": len(_ram)}
