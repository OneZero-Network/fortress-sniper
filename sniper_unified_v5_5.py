#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   PROJECT FORTRESS — SNIPER v6.0 EOD QUANTUM SCREENER                      ║
║   Bismillah — In the name of Allah, the Most Gracious, the Most Merciful   ║
║                                                                              ║
║   v6.0 ARCHITECTURE — ZERO-INFRASTRUCTURE QUANTUM UPGRADE                  ║
║   ─────────────────────────────────────────────────────────────             ║
║   PHASE-2  DYNAMIC REGIME ENGINE                                            ║
║            fetch_macro_regime() → VIX + NIFTY breadth → TREND/CHOP/BUNKER ║
║            ATR-14 dynamic stops: Stop = Price − (ATR × regime_mult)        ║
║            Regime-keyed multipliers: TREND=1.5, CHOP=2.0, BUNKER=2.5      ║
║            Position size: Shares = (Equity × Risk%) / (Entry − Stop)      ║
║                                                                              ║
║   PHASE-3  EOD ORDER FLOW PROXY                                             ║
║            Delivery % as aggressive-buying proxy (no L2 WebSocket needed)  ║
║            WHALE_ACCUMULATION flag: delivery_pct > 65 AND vol > 1.5×avg    ║
║            VPOC support zone computed from 20-day tick-aggregated closes   ║
║                                                                              ║
║   PHASE-4  ALT-DATA + OPENAI SEMANTIC PIPELINE                             ║
║            CPP tender portal scraper (BeautifulSoup, free)                 ║
║            Zauba Corp shipping manifest scraper (free)                     ║
║            OpenAI text-embedding-3-small for semantic similarity           ║
║            Vector store in Google Sheets (zero Pinecone cost)              ║
║            Catalyst match: cosine similarity vs historical 50%+ breakouts  ║
║                                                                              ║
║   INFRA    ZERO-COST STACK                                                  ║
║            DB: Google Sheets (persistent, human-readable, free)            ║
║            Scheduler: GitHub Actions (free tier, EOD 3:00 AM UTC)         ║
║            LLM: OpenAI gpt-4o-mini (~$0.002/run)                          ║
║            Embeddings: text-embedding-3-small (~$0.0001/run)              ║
║            Data: NSE Bhavcopy + yfinance (both free)                      ║
║                                                                              ║
║   PRESERVED FROM v5.5                                                       ║
║            Fortress scoring (200-pt), APEX 7-engine composite              ║
║            Three-lane architecture (FORTRESS/APEX/FUSED)                   ║
║            4-layer Halal AI Screen (L1 keyword → L4 LLM)                  ║
║            Permutations Confluence Engine (PCE)                            ║
║            CONVICTION_RERANK with Option-C RS catalyst fallback            ║
║            FII/DII streak scoring                                          ║
║            Bayesian network priors (14-node)                               ║
║            Monte Carlo survival (Student-t df=5, regime-keyed)             ║
║            Google Sheets DB (DB_BACKUP / DB_DECISIONS / SCREENER)         ║
║            Direct-to-Sheets TAKEN write (Bug-1 race condition fix)        ║
║                                                                              ║
║   REMOVED (Phase 1 / Phase 5 — requires dedicated infra + track record)   ║
║            PostgreSQL / TimescaleDB / Redis (Phase 1 infra)               ║
║            Autonomous bracket order execution (Phase 5)                   ║
║            SQLite ephemeral cache (replaced by Sheets as primary DB)      ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os, io, sys, re, json, math, time, random, logging, hashlib
import threading, warnings, asyncio, queue, itertools, collections
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

import requests
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fortress_v6")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — CONFIGURATION & SECRETS
# ══════════════════════════════════════════════════════════════════════════════

VERSION = "FORTRESS v6.0 EOD QUANTUM"

# LLM
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")
OPENAI_MINI_MODEL = os.getenv("OPENAI_MINI_MODEL", "gpt-4o-mini")
OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
_OPENAI_OK        = bool(OPENAI_API_KEY)
LLM_ENABLED       = _OPENAI_OK

# Telegram
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Google Sheets
GOOGLE_SHEET_ID   = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON", "")

# Account
ACCOUNT_EQUITY   = float(os.getenv("ACCOUNT_EQUITY", "500000"))
ACCOUNT_RISK_PCT = float(os.getenv("ACCOUNT_RISK_PCT", "0.015"))

# Screening gates
MIN_TURNOVER_LAKHS = float(os.getenv("MIN_TURNOVER_LAKHS", "50"))
MIN_PRICE          = float(os.getenv("MIN_PRICE", "20"))
MAX_PRICE          = float(os.getenv("MAX_PRICE", "10000"))
MAX_CANDIDATES     = int(os.getenv("MAX_CANDIDATES", "400"))
APEX_MIN_SCORE     = int(os.getenv("APEX_MIN_SCORE", "48"))
APEX_TOP_N         = int(os.getenv("APEX_TOP_N", "5"))

# Phase-2 Regime engine
ATR_PERIOD        = int(os.getenv("ATR_PERIOD", "14"))
ATR_MULT_TREND    = float(os.getenv("ATR_MULT_TREND", "1.5"))
ATR_MULT_CHOP     = float(os.getenv("ATR_MULT_CHOP", "2.0"))
ATR_MULT_BUNKER   = float(os.getenv("ATR_MULT_BUNKER", "2.5"))
VIX_TREND_MAX     = float(os.getenv("VIX_TREND_MAX", "15"))
VIX_CHOP_MAX      = float(os.getenv("VIX_CHOP_MAX", "22"))
# VIX > VIX_CHOP_MAX → BUNKER

# Phase-3 EOD order flow
WHALE_DELIVERY_PCT  = float(os.getenv("WHALE_DELIVERY_PCT", "65"))   # delivery% threshold
WHALE_VOL_MULT      = float(os.getenv("WHALE_VOL_MULT", "1.5"))       # vol vs 20d avg

# Phase-4 alt-data
ALT_DATA_ENABLED    = os.getenv("ALT_DATA_ENABLED", "true").lower() in ("1","true","yes")
ALT_DATA_MATCH_SIM  = float(os.getenv("ALT_DATA_MATCH_SIM", "0.72"))  # cosine floor

# Conviction rerank (preserved from v5.5.2 Option-C)
CONVICTION_RERANK       = os.getenv("CONVICTION_RERANK", "true").lower() in ("1","true","yes")
CONV_REQUIRE_CATALYST   = os.getenv("CONV_REQUIRE_CATALYST", "true").lower() in ("1","true","yes")
CONV_RS_CATALYST_FLOOR  = float(os.getenv("CONV_RS_CATALYST_FLOOR", "85"))
CONV_RS_MIN_PCT         = float(os.getenv("CONV_RS_MIN_PCT", "70"))
CONV_LANE_FORTRESS_MIN  = int(os.getenv("CONV_LANE_FORTRESS_MIN", "120"))
CONV_LANE_APEX_MIN      = int(os.getenv("CONV_LANE_APEX_MIN", "60"))
CONV_LANE_FUSED_MIN     = int(os.getenv("CONV_LANE_FUSED_MIN", "70"))

LANE_FORTRESS_MIN = int(os.getenv("LANE_FORTRESS_MIN", "100"))
LANE_APEX_MIN     = int(os.getenv("LANE_APEX_MIN", "55"))
LANE_FUSED_MIN    = int(os.getenv("LANE_FUSED_MIN", "60"))

CAPACITY_MAX_OPEN  = int(os.getenv("CAPACITY_MAX_OPEN", "4"))
CAPACITY_MAX_WEEK  = int(os.getenv("CAPACITY_MAX_WEEK", "6"))

# Sector ATR multipliers (calibrated from v5.5)
SECTOR_ATR_MULT = {
    "METAL":   1.35, "ENERGY":  1.20, "PHARMA":  1.10,
    "FMCG":    0.85, "IT":      0.80, "BANK":    0.95,
    "FINANCE": 0.90, "REALTY":  1.15, "AUTO":    1.05,
    "INFRA":   1.10, "CHEMICALS": 1.15, "TEXTILE": 1.20,
}

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — GOOGLE SHEETS DB (primary persistent store, replaces SQLite)
# ══════════════════════════════════════════════════════════════════════════════
# Zero infrastructure: Sheets = cold storage + hot decisions + vector store.
# All tabs auto-created on first run.
# Tabs used:
#   SCREENER        — daily picks (read by reply handler)
#   DB_DECISIONS    — TAKEN/SKIP decisions (written real-time by reply handler)
#   DB_BACKUP       — pick_outcomes history (written EOD by outcome engine)
#   ALT_VECTORS     — alt-data embeddings for semantic search
#   PERFORMANCE     — closed trade P&L history
#   MACRO_CACHE     — latest regime state (fallback when VIX unavailable)

_GS_WORKBOOK    = None
_GS_LOCK        = threading.Lock()
_GS_CONN_CACHE: Dict[str, Any] = {}

def _gs_ok() -> bool:
    return bool(GOOGLE_SHEET_ID and GOOGLE_CREDS_JSON)

def _get_workbook():
    global _GS_WORKBOOK
    if _GS_WORKBOOK is not None:
        return _GS_WORKBOOK
    with _GS_LOCK:
        if _GS_WORKBOOK is not None:
            return _GS_WORKBOOK
        if not _gs_ok():
            return None
        try:
            import gspread
            from google.oauth2.service_account import Credentials
            creds_dict = json.loads(GOOGLE_CREDS_JSON)
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            gc = gspread.authorize(creds)
            _GS_WORKBOOK = gc.open_by_key(GOOGLE_SHEET_ID)
            log.info("Google Sheets connected ✅")
            return _GS_WORKBOOK
        except Exception as e:
            log.warning(f"Sheets connect failed (non-fatal): {e}")
            return None

def _get_ws(tab: str):
    wb = _get_workbook()
    if wb is None:
        return None
    try:
        return wb.worksheet(tab)
    except Exception:
        try:
            ws = wb.add_worksheet(title=tab, rows=2000, cols=50)
            return ws
        except Exception as e:
            log.warning(f"_get_ws create {tab}: {e}")
            return None

def _push_sheet(tab: str, rows: list) -> bool:
    """Write rows to a Sheets tab (header + data). Resizes as needed. Returns True on success."""
    if not rows:
        return True
    ws = _get_ws(tab)
    if ws is None:
        log.warning(f"_push_sheet: cannot get tab {tab}")
        return False
    try:
        # Resize if needed
        needed_rows = max(len(rows) + 5, 100)
        needed_cols = max(len(rows[0]) if rows else 1, 10)
        if ws.row_count < needed_rows or ws.col_count < needed_cols:
            ws.resize(rows=needed_rows, cols=needed_cols)
        ws.clear()
        ws.update("A1", rows, value_input_option="USER_ENTERED")
        log.info(f"Sheets {tab}: {len(rows)-1} data rows written ✅")
        return True
    except Exception as e:
        log.warning(f"_push_sheet {tab}: {e}")
        return False

def _read_sheet(tab: str) -> list:
    """Read all values from a tab. Returns list of lists (row 0 = header)."""
    ws = _get_ws(tab)
    if ws is None:
        return []
    try:
        return ws.get_all_values()
    except Exception as e:
        log.warning(f"_read_sheet {tab}: {e}")
        return []

def _append_sheet_row(tab: str, row: list) -> bool:
    """Append a single row to a tab (used for real-time decision writes)."""
    ws = _get_ws(tab)
    if ws is None:
        return False
    try:
        ws.append_row(row, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        log.warning(f"_append_sheet_row {tab}: {e}")
        return False

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — SQLITE (local ephemeral cache only — SCORE CACHE + LLM CACHE)
# Primary DB = Sheets. SQLite only used for:
#   - score_cache (avoid re-scoring same symbol same day on reruns)
#   - llm_cache   (avoid duplicate OpenAI calls, saves cost)
#   - macro_cache (fallback when VIX feed unavailable)
# Both are fully disposable — wiped on fresh runner, reconstructed within minutes.
# ══════════════════════════════════════════════════════════════════════════════

DB_PATH = Path(os.getenv("CACHE_PATH", "outputs/sniper_cache.db"))
_SQLITE_WRITE_LOCK = threading.Lock()

@contextmanager
def _db_conn(write: bool = False, timeout: int = 10):
    ctx = _SQLITE_WRITE_LOCK if write else None
    if ctx:
        ctx.acquire()
    con = None
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(DB_PATH), timeout=timeout,
                              check_same_thread=False)  # FIX-1: allow concurrent thread access
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=5000")
        yield con
        con.commit()
    except Exception:
        if con:
            try: con.rollback()
            except Exception: pass
        raise
    finally:
        if con:
            try: con.close()
            except Exception: pass
        if ctx:
            try: ctx.release()
            except Exception: pass

def _init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH), timeout=10,
                          check_same_thread=False)  # FIX-1
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS score_cache (
            symbol        TEXT NOT NULL,
            run_date      TEXT NOT NULL,
            bhavcopy_close REAL NOT NULL,
            intel_hash    TEXT NOT NULL DEFAULT '',
            result_json   TEXT NOT NULL,
            created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (symbol, run_date, intel_hash)
        );
        CREATE TABLE IF NOT EXISTS llm_cache (
            text_hash   TEXT PRIMARY KEY,
            prompt_type TEXT,
            result      TEXT,
            model       TEXT,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at  TEXT
        );
        CREATE TABLE IF NOT EXISTS macro_cache (
            id          INTEGER PRIMARY KEY,
            macro_state TEXT,
            vix_val     REAL,
            nifty_chg   REAL,
            breadth_ok  INTEGER,
            fetched_at  TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS alt_vector_cache (
            symbol      TEXT NOT NULL,
            source      TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            embedding_json TEXT NOT NULL,
            raw_text    TEXT,
            fetched_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (symbol, source, content_hash)
        );
    """)
    con.commit()
    con.close()

def _llm_cache_get(text_hash: str) -> Optional[str]:
    try:
        with _db_conn() as con:
            row = con.execute(
                "SELECT result FROM llm_cache WHERE text_hash=? "
                "AND (expires_at IS NULL OR expires_at > datetime('now'))",
                (text_hash,)
            ).fetchone()
        return row[0] if row else None
    except Exception:
        return None

def _llm_cache_put(text_hash: str, result: str, prompt_type: str,
                   model: str, ttl_days: int = 7):
    expires = (datetime.utcnow() + timedelta(days=ttl_days)).isoformat()
    try:
        with _db_conn(write=True) as con:
            con.execute(
                "INSERT OR REPLACE INTO llm_cache "
                "(text_hash,prompt_type,result,model,expires_at) VALUES (?,?,?,?,?)",
                (text_hash, prompt_type, result, model, expires)
            )
    except Exception:
        pass

def _score_cache_get(symbol: str, run_date: str, close: float,
                     intel_hash: str) -> Optional[dict]:
    try:
        with _db_conn() as con:
            row = con.execute(
                "SELECT result_json, bhavcopy_close FROM score_cache "
                "WHERE symbol=? AND run_date=? AND intel_hash=?",
                (symbol.upper(), run_date, intel_hash)
            ).fetchone()
        if row and abs(float(row[1]) - close) < 0.01:
            return json.loads(row[0])
    except Exception:
        pass
    return None

def _score_cache_put(symbol: str, run_date: str, close: float,
                     result: dict, intel_hash: str):
    try:
        with _db_conn(write=True) as con:
            con.execute(
                "INSERT OR REPLACE INTO score_cache "
                "(symbol,run_date,bhavcopy_close,intel_hash,result_json) VALUES (?,?,?,?,?)",
                (symbol.upper(), run_date, close, intel_hash, json.dumps(result, default=str))
            )
    except Exception:
        pass

def _score_cache_purge(keep_days: int = 5):
    cutoff = (datetime.today() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    try:
        with _db_conn(write=True) as con:
            n = con.execute("DELETE FROM score_cache WHERE run_date < ?", (cutoff,)).rowcount
        if n:
            log.info(f"score_cache: purged {n} stale rows")
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — OPENAI LLM + EMBEDDING WRAPPERS
# All calls are cached (llm_cache). Circuit breaker: 3 failures → open for run.
# ══════════════════════════════════════════════════════════════════════════════

_OAI_FAIL_COUNT   = 0
_OAI_CB_OPEN      = False
_OAI_CB_LOCK      = threading.Lock()

def _call_openai(prompt: str, model: str = None, max_tokens: int = 600,
                 system: str = "You are a quant analyst. Be concise and precise.",
                 cache_ttl_days: int = 7) -> Optional[str]:
    global _OAI_FAIL_COUNT, _OAI_CB_OPEN
    if not _OPENAI_OK:
        return None
    with _OAI_CB_LOCK:
        if _OAI_CB_OPEN:
            log.debug("OpenAI circuit OPEN — skipping LLM call")
            return None
    _model = model or OPENAI_MINI_MODEL
    # Cache check
    cache_key = hashlib.md5(f"{_model}:{system}:{prompt}".encode()).hexdigest()
    cached = _llm_cache_get(cache_key)
    if cached is not None:
        return cached
    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": _model, "max_tokens": max_tokens,
                  "messages": [{"role":"system","content":system},
                                {"role":"user","content":prompt}]},
            timeout=25,
        )
        if resp.status_code == 200:
            result = resp.json()["choices"][0]["message"]["content"].strip()
            with _OAI_CB_LOCK:
                _OAI_FAIL_COUNT = 0
            _llm_cache_put(cache_key, result, "gpt", _model, cache_ttl_days)
            return result
        log.warning(f"OpenAI HTTP {resp.status_code}: {resp.text[:120]}")
        with _OAI_CB_LOCK:
            _OAI_FAIL_COUNT += 1
            if _OAI_FAIL_COUNT >= 3:
                _OAI_CB_OPEN = True
                log.warning("OpenAI circuit breaker OPEN (3 failures)")
    except Exception as e:
        log.warning(f"_call_openai: {e}")
        with _OAI_CB_LOCK:
            _OAI_FAIL_COUNT += 1
    return None

def _embed_openai(text: str) -> Optional[List[float]]:
    """Generate embedding via OpenAI text-embedding-3-small. Cached in SQLite."""
    if not _OPENAI_OK:
        return None
    cache_key = "emb:" + hashlib.md5(text.encode()).hexdigest()
    cached = _llm_cache_get(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass
    try:
        resp = requests.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": OPENAI_EMBED_MODEL, "input": text[:8000]},
            timeout=20,
        )
        if resp.status_code == 200:
            vec = resp.json()["data"][0]["embedding"]
            _llm_cache_put(cache_key, json.dumps(vec), "embedding",
                           OPENAI_EMBED_MODEL, ttl_days=30)
            return vec
    except Exception as e:
        log.debug(f"_embed_openai: {e}")
    return None

def _cosine_sim(v1: list, v2: list) -> float:
    try:
        a, b = np.array(v1, dtype=np.float32), np.array(v2, dtype=np.float32)
        d = np.linalg.norm(a) * np.linalg.norm(b)
        return float(np.dot(a, b) / d) if d > 0 else 0.0
    except Exception:
        return 0.0

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — PHASE 2: DYNAMIC REGIME ENGINE
# VIX + NIFTY breadth → TREND / CHOP / BUNKER / PANIC / MASSACRE
# ATR-14 replaces all static % stops. Position size = equity-risk / dollar-risk.
# ══════════════════════════════════════════════════════════════════════════════

def compute_internal_breadth(bhavcopy: pd.DataFrame) -> Tuple[float, bool]:
    """
    FIX-4: True market breadth from bhavcopy advance/decline count.

    The original code used CNX500 close > 50DMA, which is INDEX MOMENTUM,
    not breadth. 5 mega-cap stocks can push the index above its 50DMA while
    495 mid-caps crash — the engine would read "positive breadth" and lock into
    TREND mode, buying breakouts into a mid-cap slaughter.

    This function counts stocks where close > open (advancing) from the same
    bhavcopy dataframe the engine already holds — zero extra API calls.
    Threshold: advancers / total < 0.40 → breadth is negative (bearish internals).

    Returns (advance_ratio, breadth_ok)
    """
    if bhavcopy is None or bhavcopy.empty:
        return 0.5, True  # neutral fallback if bhavcopy unavailable
    try:
        df = bhavcopy.copy()
        # Filter to liquid stocks only (same gate as main pipeline)
        df = df[(df["turnover_lakhs"] >= MIN_TURNOVER_LAKHS) &
                (df["close"] > 0) & (df["open"] > 0)]
        if len(df) < 20:
            return 0.5, True
        # FIX-1: close > open only measures green intraday candle, NOT that the
        # stock advanced vs yesterday. On a gap-down Black Monday, stocks that
        # chop sideways close > open while being down -4% — the old code would
        # register 90% "advancing" and trigger TREND mode during a crash.
        # Fix: true advance = close > prevclose (prior session's close).
        if "prevclose" in df.columns and df["prevclose"].gt(0).any():
            advancers = int((df["close"] > df["prevclose"]).sum())
        else:
            # FIX-1: shift(1) on a cross-company DataFrame compares INFY price
            # against HDFCBANK price — pure alphabetical noise, not breadth.
            # yfinance fallback now stores per-symbol prevclose in load_bhavcopy.
            # If still absent, default to neutral (0.5) — safer than garbage.
            log.warning("compute_internal_breadth: prevclose absent — defaulting neutral")
            return 0.5, True
        total     = len(df)
        ratio     = advancers / total
        breadth_ok = ratio >= 0.40
        log.info(f"Internal breadth (close>prevclose): {advancers}/{total} = {ratio:.0%} "
                 f"→ {'✅ positive' if breadth_ok else '❌ negative'}")
        return round(ratio, 3), breadth_ok
    except Exception as e:
        log.warning(f"compute_internal_breadth: {e} — defaulting neutral")
        return 0.5, True


def fetch_macro_regime(bhavcopy: pd.DataFrame = None) -> dict:
    """
    Phase 2.1: Regime classification microservice.
    TREND   : VIX < 15  AND internal breadth > 40%  → VCP breakouts active
    CHOP    : VIX 15-22 OR breadth negative         → mean-reversion only
    BUNKER  : VIX > 22  AND breadth negative        → tightest gates
    PANIC   : VIX > 28                              → no new positions
    MASSACRE: NIFTY50 day change < -3%              → halt pipeline

    FIX-4: breadth now computed from bhavcopy advance/decline ratio (true internals),
    not CNX500 vs 50DMA (index momentum). Pass bhavcopy when available; falls back
    to neutral (True) when called before bhavcopy is loaded (e.g. startup tests).
    """
    FALLBACK = {"macro_state": "CHOP", "vix_val": 18.0,
                "nifty_chg": 0.0, "breadth_ok": True, "advance_ratio": 0.5,
                "atr_mult": ATR_MULT_CHOP, "regime_note": "fallback"}
    try:
        import yfinance as yf
        vix_df   = yf.download("^INDIAVIX", period="5d",  progress=False,
                               auto_adjust=True, timeout=15)
        nifty_df = yf.download("^NSEI",     period="10d", progress=False,
                               auto_adjust=True, timeout=15)
        # FIX-4: CNX500 download removed — no longer used for breadth
    except Exception as e:
        log.warning(f"fetch_macro_regime yfinance: {e} — FALLBACK")
        return _load_cached_macro() or FALLBACK

    vix = 18.0
    if not vix_df.empty:
        try:
            vix = float(vix_df["Close"].squeeze().iloc[-1])
        except Exception:
            pass

    nifty_chg = 0.0
    if not nifty_df.empty and len(nifty_df) >= 2:
        try:
            nc = nifty_df["Close"].squeeze().values
            nifty_chg = float((nc[-1] - nc[-2]) / nc[-2] * 100)
        except Exception:
            pass

    # FIX-4: True internal breadth from bhavcopy advance/decline ratio
    advance_ratio, breadth_ok = compute_internal_breadth(bhavcopy)

    # Regime classification (auditor spec Phase 2.1)
    if nifty_chg <= -3.0:
        state = "MASSACRE"
    elif vix >= 28:
        state = "PANIC"
    elif vix > VIX_CHOP_MAX and not breadth_ok:
        state = "BUNKER"
    elif vix > VIX_CHOP_MAX:
        state = "CHOP"
    elif vix <= VIX_TREND_MAX and breadth_ok:
        state = "TREND"
    else:
        state = "CHOP"

    # Regime → ATR multiplier (Phase 2.2)
    atr_mult = {
        "TREND":    ATR_MULT_TREND,
        "CHOP":     ATR_MULT_CHOP,
        "BUNKER":   ATR_MULT_BUNKER,
        "PANIC":    ATR_MULT_BUNKER,
        "MASSACRE": ATR_MULT_BUNKER,
    }.get(state, ATR_MULT_CHOP)

    result = {
        "macro_state": state, "vix_val": round(vix, 2),
        "nifty_chg": round(nifty_chg, 2), "breadth_ok": bool(breadth_ok),
        "advance_ratio": advance_ratio,
        "atr_mult": atr_mult,
        "regime_note": (f"VIX={vix:.1f} breadth={advance_ratio:.0%} "
                        f"({'✅' if breadth_ok else '❌'}) FIX-4:internal"),
    }
    log.info(f"Regime: {state} | VIX={vix:.1f} | NIFTY {nifty_chg:+.2f}% | "
             f"Breadth={advance_ratio:.0%} | ATR_mult={atr_mult}×")
    _save_macro_cache(result)
    _push_macro_to_sheets(result)
    return result

def _save_macro_cache(macro: dict):
    try:
        with _db_conn(write=True) as con:
            con.execute("CREATE TABLE IF NOT EXISTS macro_cache ("
                        "id INTEGER PRIMARY KEY, macro_state TEXT, vix_val REAL, "
                        "nifty_chg REAL, breadth_ok INTEGER, atr_mult REAL, "
                        "fetched_at TEXT DEFAULT CURRENT_TIMESTAMP)")
            con.execute("INSERT INTO macro_cache "
                        "(macro_state,vix_val,nifty_chg,breadth_ok,atr_mult) VALUES (?,?,?,?,?)",
                        (macro["macro_state"], macro["vix_val"], macro["nifty_chg"],
                         int(macro["breadth_ok"]), macro["atr_mult"]))
            con.execute("DELETE FROM macro_cache WHERE id NOT IN "
                        "(SELECT id FROM macro_cache ORDER BY id DESC LIMIT 10)")
    except Exception as e:
        log.debug(f"_save_macro_cache: {e}")

def _load_cached_macro() -> Optional[dict]:
    try:
        with _db_conn() as con:
            row = con.execute(
                "SELECT macro_state,vix_val,nifty_chg,breadth_ok,atr_mult,fetched_at "
                "FROM macro_cache ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row:
            age = (datetime.utcnow() -
                   datetime.fromisoformat(row[5])).total_seconds() / 3600
            if age < 12:
                log.info(f"Using cached macro: {row[0]} VIX={row[1]:.1f} ({age:.1f}h old)")
                return {"macro_state": row[0], "vix_val": row[1],
                        "nifty_chg": row[2], "breadth_ok": bool(row[3]),
                        "atr_mult": row[4] or ATR_MULT_CHOP,
                        "regime_note": f"cached {age:.1f}h ago"}
    except Exception:
        pass
    return None

def _push_macro_to_sheets(macro: dict):
    """Write latest macro state to MACRO_CACHE tab for cross-runner fallback."""
    try:
        header = ["fetched_at","macro_state","vix_val","nifty_chg","breadth_ok","atr_mult","regime_note"]
        row = [datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
               macro["macro_state"], str(macro["vix_val"]),
               str(macro["nifty_chg"]), str(macro["breadth_ok"]),
               str(macro["atr_mult"]), macro.get("regime_note","")]
        _push_sheet("MACRO_CACHE", [header, row])
    except Exception as e:
        log.debug(f"_push_macro_to_sheets: {e}")

def atr_dynamic_stop(close: float, atr14: float, sector: str,
                     macro_state: str, atr_mult: float) -> float:
    """
    Phase 2.2: ATR-based dynamic stop-loss.
    Stop = Current_Price − (ATR_14 × regime_multiplier × sector_multiplier)
    Prevents static % stops being too tight in volatile sectors / BUNKER regime.
    Minimum stop: 5% below close (hard floor).
    """
    sect_mult = SECTOR_ATR_MULT.get(sector, 1.0)
    # Calibrate for penny stocks (< ₹100)
    if close < 100:
        sect_mult *= 0.75
    elif close > 1000:
        sect_mult *= 1.2
    effective_mult = atr_mult * sect_mult
    stop = close - (atr14 * effective_mult)
    # Hard floor: never more than 15% below close regardless of ATR
    floor = close * 0.85
    return round(max(stop, floor), 2)

def atr_position_size(equity: float, risk_pct: float,
                      entry: float, stop: float,
                      max_position_pct: float = 0.25) -> int:
    """
    Phase 2.2: Volatility-adjusted position sizing with buy-power cap.
    FIX-1: pure risk math (Shares = dollar_risk / per_share_risk) ignores buying
    power. A very tight ATR stop (e.g. ₹1 on a ₹100 stock) at 1.5% risk on
    ₹5L equity → 7,500 shares → ₹7.5L required → broker INSUFFICIENT_FUNDS reject.
    Fix: hard-cap at max_position_pct (default 25%) of total equity.
    Returns the LOWER of risk-sized shares and max-affordable shares.
    """
    if stop >= entry or entry <= 0:
        return 0
    dollar_risk     = equity * risk_pct
    per_share_risk  = entry - stop
    risk_sized      = int(dollar_risk / per_share_risk)
    max_affordable  = int((equity * max_position_pct) / entry)  # FIX-1: buy-power cap
    return max(1, min(risk_sized, max_affordable))

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — DATA FETCHING
# Bhavcopy (NSE free), yfinance histories, FII/DII, insider, filings
# ══════════════════════════════════════════════════════════════════════════════

def _get_last_trading_day() -> Tuple[str, str]:
    """Return (ddmmyyyy, yyyy-mm-dd) of the last trading day."""
    today = datetime.today()
    if today.weekday() == 0:
        d = today - timedelta(days=3)
    elif today.weekday() == 6:
        d = today - timedelta(days=2)
    else:
        d = today - timedelta(days=1)
    return d.strftime("%d%m%Y"), d.strftime("%Y-%m-%d")

_NSE_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/",
}


def _fetch_mto_delivery(date_label: str) -> Dict[str, float]:
    """
    FIX-2: Fetch Security-wise Delivery Position (MTO) from NSE archives.
    Standard NSE Bhavcopy (cmDDMMYYYYbhav.csv) does NOT contain delivery data.
    Without MTO, delivery_pct = 0.0 for every stock → whale_flag mathematically
    impossible → 30-pt whale score permanently dead → true pearls downgraded.

    NSE MTO file: https://archives.nseindia.com/archives/equities/mto/MTO_DDMMYYYY.DAT
    Format (pipe-delimited): Record Type | Sr No | Symbol | Series | Traded Qty |
                             Deliverable Qty | % Dly Qt to Traded Qty

    Returns {SYMBOL: delivery_pct} dict, empty dict on failure (non-fatal).
    """
    dd = date_label[8:10]
    mm = date_label[5:7]
    yyyy = date_label[:4]
    url  = f"https://archives.nseindia.com/archives/equities/mto/MTO_{dd}{mm}{yyyy}.DAT"
    result: Dict[str, float] = {}
    try:
        sess = requests.Session()
        sess.get("https://www.nseindia.com", headers=_NSE_HEADERS, timeout=8)
        resp = sess.get(url, headers=_NSE_HEADERS, timeout=15)
        if resp.status_code != 200:
            log.warning(f"MTO fetch HTTP {resp.status_code} for {date_label} — delivery_pct=0")
            return result
        # Format: "90,1,SYMBOL,EQ,TradedQty,DelivQty,DelivPct"
        # or older: "90|1|SYMBOL|EQ|..."
        text = resp.text
        delim = "|" if "|" in text[:200] else ","
        for line in text.splitlines():
            parts = [p.strip() for p in line.split(delim)]
            if len(parts) < 7:
                continue
            rec_type = parts[0].strip()
            # FIX-3: NSE MTO record types — "90" does NOT exist for equities.
            # Type 20 = normal CM equities, Type 08 = additional series.
            # Filtering on "90" silently rejects every row → delivery_pct=0.
            # Fix: accept types 20/08/DR OR fall through to series=="EQ" check.
            # series=="EQ" is the reliable gate; record type is belt-and-suspenders.
            try:
                sym      = parts[2].strip().upper()
                series   = parts[3].strip().upper()
                if rec_type not in ("20", "08", "DR") and series != "EQ":
                    continue
                if series != "EQ":
                    continue
                deliv_pct = float(parts[6])
                result[sym] = round(deliv_pct, 2)
            except (ValueError, IndexError):
                continue
        log.info(f"MTO delivery loaded: {len(result)} symbols for {date_label} ✅")
    except Exception as e:
        log.warning(f"MTO fetch failed (non-fatal, delivery_pct=0): {e}")
    return result

def load_bhavcopy() -> Tuple[pd.DataFrame, str]:
    """
    Load NSE bhavcopy (EQ segment only). Returns (df, source_name).
    Tries NSE direct download first, falls back to yfinance universe.
    Columns: symbol, open, high, low, close, volume, turnover_lakhs, delivery_pct
    """
    _, date_label = _get_last_trading_day()
    dd, mm, yyyy = date_label[8:10], date_label[5:7], date_label[:4]

    # Try NSE bhav copy direct
    urls = [
        f"https://archives.nseindia.com/content/historical/EQUITIES/{yyyy}/{mm.upper()[:3]}/cm{dd}{mm.upper()[:3]}{yyyy}bhav.csv.zip",
        f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_{dd}{mm}{yyyy}_F_0000.csv.zip",
    ]
    for url in urls:
        try:
            sess = requests.Session()
            sess.get("https://www.nseindia.com", headers=_NSE_HEADERS, timeout=8)
            resp = sess.get(url, headers=_NSE_HEADERS, timeout=20)
            if resp.status_code == 200 and len(resp.content) > 5000:
                from zipfile import ZipFile
                zf = ZipFile(io.BytesIO(resp.content))
                csv_name = [n for n in zf.namelist() if n.endswith(".csv")][0]
                df_raw = pd.read_csv(io.BytesIO(zf.read(csv_name)))
                df_raw.columns = [c.strip().upper() for c in df_raw.columns]
                # Normalise column names across both NSE formats
                col_map = {}
                for c in df_raw.columns:
                    cl = c.lower()
                    if cl in ("symbol","series","open","high","low","close","volume",
                              "tottrdqty","tottrdval","traddte","isin"):
                        col_map[c] = cl
                    elif "symbol" in cl: col_map[c] = "symbol"
                    elif "series" in cl: col_map[c] = "series"
                    elif "open" in cl:   col_map[c] = "open"
                    elif "high" in cl:   col_map[c] = "high"
                    elif "low" in cl:    col_map[c] = "low"
                    elif "prevclose" in cl:  col_map[c] = "prevclose"  # FIX-1: preserve yesterday close for true breadth
                    elif cl in ("close","ltp"): col_map[c] = "close"
                    elif "qty" in cl or "volume" in cl: col_map[c] = "volume"
                    elif "val" in cl or "turnover" in cl: col_map[c] = "turnover_lakhs"
                    elif "deliv" in cl:  col_map[c] = "delivery_pct"
                    elif "isin" in cl:   col_map[c] = "isin"
                df_raw = df_raw.rename(columns=col_map)
                if "series" in df_raw.columns:
                    df_raw = df_raw[df_raw["series"] == "EQ"]
                needed = ["symbol","open","high","low","close","volume"]
                if all(c in df_raw.columns for c in needed):
                    df = df_raw[needed].copy()
                    if "turnover_lakhs" in df_raw.columns:
                        df["turnover_lakhs"] = pd.to_numeric(df_raw["turnover_lakhs"], errors="coerce").fillna(0) / 100000
                    else:
                        df["turnover_lakhs"] = (pd.to_numeric(df_raw.get("volume", 0), errors="coerce") *
                                                 pd.to_numeric(df_raw.get("close", 0), errors="coerce") / 100000)
                    if "delivery_pct" in df_raw.columns:
                        df["delivery_pct"] = pd.to_numeric(df_raw["delivery_pct"], errors="coerce").fillna(0)
                    else:
                        df["delivery_pct"] = 0.0
                    for col in ["open","high","low","close","volume","turnover_lakhs"]:
                        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
                    df["symbol"] = df["symbol"].str.strip().str.upper()
                    # FIX-2: merge MTO delivery data (separate NSE file)
                    _mto = _fetch_mto_delivery(date_label)
                    if _mto:
                        df["delivery_pct"] = df["symbol"].map(_mto).fillna(0.0)
                        log.info(f"MTO merged: {df['delivery_pct'].gt(0).sum()} symbols have delivery data")
                    log.info(f"Bhavcopy loaded from NSE: {len(df)} rows | source={url}")
                    return df.dropna(subset=["close"]), "NSE_DIRECT"
        except Exception as e:
            log.debug(f"Bhavcopy NSE attempt failed: {e}")

    # Fallback: yfinance Nifty500 + Nifty Midcap150
    log.warning("Bhavcopy: NSE failed — falling back to yfinance universe")
    try:
        import yfinance as yf
        # Core halal-friendly universe from known liquid NSE symbols
        symbols_500 = _load_nifty500_symbols()
        if not symbols_500:
            log.error("No symbols loaded for yfinance fallback")
            return pd.DataFrame(), "EMPTY"
        tickers = [f"{s}.NS" for s in symbols_500[:300]]
        raw = yf.download(" ".join(tickers), period="2d", progress=False,
                          auto_adjust=True, timeout=30, group_by="ticker")
        rows = []
        for sym in symbols_500[:300]:
            tk = f"{sym}.NS"
            try:
                if hasattr(raw.columns, "levels"):
                    sub = raw[tk] if tk in raw.columns.get_level_values(0) else None
                else:
                    sub = raw if len(symbols_500) == 1 else None
                if sub is None or sub.empty or len(sub) < 1:
                    continue
                last = sub.iloc[-1]
                # FIX-1: capture actual previous close from prior row.
                # breadth fallback needs per-symbol prevclose, not cross-symbol .shift(1).
                prevclose = float(sub.iloc[-2].get("Close", last.get("Close", 0))) if len(sub) > 1 else float(last.get("Close", 0))
                rows.append({
                    "symbol": sym, "open": float(last.get("Open", 0)),
                    "high": float(last.get("High", 0)), "low": float(last.get("Low", 0)),
                    "close": float(last.get("Close", 0)),
                    "prevclose": prevclose,
                    "volume": float(last.get("Volume", 0)),
                    "turnover_lakhs": float(last.get("Volume", 0)) * float(last.get("Close", 0)) / 100000,
                    "delivery_pct": 0.0,
                })
            except Exception:
                continue
        df = pd.DataFrame(rows)
        log.info(f"Bhavcopy loaded from yfinance: {len(df)} symbols")
        return df, "YFINANCE"
    except Exception as e:
        log.error(f"Bhavcopy yfinance fallback: {e}")
        return pd.DataFrame(), "EMPTY"

def _load_nifty500_symbols() -> List[str]:
    """Load Nifty500 symbol list from NSE or return curated fallback."""
    try:
        sess = requests.Session()
        sess.get("https://www.nseindia.com", headers=_NSE_HEADERS, timeout=8)
        resp = sess.get(
            "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
            headers=_NSE_HEADERS, timeout=15
        )
        if resp.status_code == 200:
            df = pd.read_csv(io.StringIO(resp.text))
            syms = df["Symbol"].str.strip().str.upper().tolist()
            log.info(f"Nifty500 list: {len(syms)} symbols")
            return syms
    except Exception as e:
        log.debug(f"_load_nifty500_symbols: {e}")
    # Curated fallback universe (top 200 liquid NSE stocks)
    return [
        "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR","SBIN","BHARTIARTL",
        "ITC","KOTAKBANK","LT","HCLTECH","AXISBANK","BAJFINANCE","WIPRO","ADANIENT",
        "MARUTI","SUNPHARMA","TITAN","NTPC","ULTRACEMCO","POWERGRID","TECHM","NESTLEIND",
        "M&M","INDUSINDBK","TATAMOTORS","COALINDIA","ONGC","BAJAJFINSV","DIVISLAB",
        "HDFCLIFE","JSWSTEEL","GRASIM","TATACONSUM","CIPLA","DRREDDY","HEROMOTOCO",
        "APOLLOHOSP","BAJAJ-AUTO","ADANIPORTS","BPCL","EICHERMOT","SBILIFE","TRENT",
        "SHREECEM","BRITANNIA","HINDZINC","VEDL","HAVELLS","PIDILITIND","BERGEPAINT",
        "MARICO","DABUR","COLPAL","AMBUJACEM","ACC","MOTHERSON","MUTHOOTFIN","CHOLAFIN",
        "BANDHANBNK","FEDERALBNK","IDFCFIRSTB","PNB","CANBK","UNIONBANK","BANKBARODA",
        "NAUKRI","ZOMATO","PAYTM","IRCTC","DMART","ASTRAL","POLYCAB","DIXON","KAYNES",
        "TATAPOWER","ADANIGREEN","ADANITRANS","TORNTPOWER","TATAELXSI","PERSISTENT",
        "COFORGE","LTIM","MPHASIS","KPITTECH","ZYDUSLIFE","TORNTPHARM","ALKEM","AAVAS",
        "ABCAPITAL","CHOLAFIN","MFSL","PAGEIND","WHIRLPOOL","VOLTAS","BLUESTAR","SYMPHONY",
        "RELAXO","BATAINDIA","VMART","PATANJALI","HONAUT","3MINDIA","ABB","SIEMENS",
        "CUMMINSIND","THERMAX","BHEL","HAL","BEL","COCHINSHIP","MAZDA","GRINDWELL",
        "CARBORUNIV","FINEORG","NAVINFLUOR","ATUL","DEEPAKNTR","PIIND","UPL","COROMANDEL",
        "CHAMBLFERT","GNFC","TATACHEM","GHCL","NOCIL","VINDHYATEL","RAILTEL","IRCON",
        "RITES","NBCC","NCC","KNR","KNRCON","AHLUCONT","PNC","HGINFRA","GPPL","CONCOR",
        "BLUEDART","MAHINDCIE","ENDURANCE","SUNDRMFAST","GABRIEL","SUPRAJIT","RAMKRISHNA",
    ]

def fetch_history(symbol: str, days: int = 300) -> pd.DataFrame:
    """Fetch OHLCV history for a symbol. Returns empty DataFrame on failure."""
    import yfinance as yf
    end   = datetime.today()
    start = end - timedelta(days=days + 30)  # buffer for weekends
    for attempt in range(2):
        try:
            raw = yf.download(f"{symbol}.NS", start=start, end=end,
                              progress=False, auto_adjust=True, timeout=20)
            # FIX-1: auto_adjust=True — all OHLC are split/dividend adjusted
            # and mathematically synchronized. auto_adjust=False returns
            # unadjusted O/H/L but adjusted Close, corrupting ATR calculation
            # (e.g. post-split TR = ₹100 unadj_high − ₹45 adj_close = 55pts fake spike).
            if raw.empty:
                return pd.DataFrame()
            df = raw.reset_index()
            df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                          for c in df.columns]
            dt_col = next((c for c in df.columns if c != "date" and
                           pd.api.types.is_datetime64_any_dtype(df[c])), None)
            if dt_col:
                df = df.rename(columns={dt_col: "date"})
            df["date"] = pd.to_datetime(df["date"])
            df = df[["date","open","high","low","close","volume"]].dropna()
            df = df.tail(days)
            return df.reset_index(drop=True)
        except Exception as e:
            if attempt == 0:
                time.sleep(1)
            else:
                log.debug(f"fetch_history {symbol}: {e}")
    return pd.DataFrame()

def fetch_fii_dii() -> dict:
    """Fetch FII/DII net activity from NSE. Returns structured dict."""
    FALLBACK = {"label": "MIXED", "fii_net": 0.0, "dii_net": 0.0,
                "fii_pts": 0, "dii_pts": 0, "score": 15}
    try:
        sess = requests.Session()
        sess.get("https://www.nseindia.com", headers=_NSE_HEADERS, timeout=8)
        resp = sess.get(
            "https://www.nseindia.com/api/fiidiiTradeReact",
            headers={**_NSE_HEADERS, "X-Requested-With": "XMLHttpRequest"},
            timeout=12
        )
        if resp.status_code != 200:
            return FALLBACK
        data = resp.json()
        rows = data if isinstance(data, list) else data.get("data", [])
        if not rows:
            return FALLBACK
        # Most recent trading day
        row = rows[0]
        fii_net = float(row.get("buyValue", 0)) - float(row.get("sellValue", 0))
        dii_net_val = float(row.get("clientBuyValue", 0)) - float(row.get("clientSellValue", 0))
        score = 15
        if fii_net > 500:   score += 10
        elif fii_net > 0:   score += 5
        elif fii_net < -500: score -= 10
        if dii_net_val > 0: score += 5
        label = "BULL" if score > 25 else "BEAR" if score < 10 else "MIXED"
        return {"label": label, "fii_net": round(fii_net, 2),
                "dii_net": round(dii_net_val, 2), "fii_pts": score,
                "dii_pts": 5 if dii_net_val > 0 else 0, "score": score}
    except Exception as e:
        log.debug(f"fetch_fii_dii: {e}")
        return FALLBACK

def fetch_insider_trades(days_back: int = 30) -> dict:
    """Fetch SAST/insider BULK deals from NSE. Returns {SYMBOL: {count, total_cr, person}}."""
    result = {}
    try:
        sess = requests.Session()
        sess.get("https://www.nseindia.com", headers=_NSE_HEADERS, timeout=8)
        resp = sess.get(
            "https://www.nseindia.com/api/bulk-deals",
            headers={**_NSE_HEADERS, "X-Requested-With": "XMLHttpRequest"},
            timeout=12
        )
        if resp.status_code != 200:
            return result
        deals = resp.json().get("data", [])
        cutoff = (datetime.today() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        for d in deals:
            sym = str(d.get("symbol","")).strip().upper()
            dt  = str(d.get("bdDt",""))[:10]
            if dt < cutoff or not sym:
                continue
            qty   = float(d.get("bdQty", 0) or 0)
            price = float(d.get("bdAvePrice", 0) or 0)
            val_cr = qty * price / 1e7
            side   = str(d.get("buySell","")).upper()
            if side != "BUY":
                continue
            if sym not in result:
                result[sym] = {"count": 0, "total_cr": 0.0, "person": d.get("clientName","")}
            result[sym]["count"] += 1
            result[sym]["total_cr"] += val_cr
    except Exception as e:
        log.debug(f"fetch_insider_trades: {e}")
    return result

def fetch_filings(days_back: int = 14) -> dict:
    """Fetch NSE corporate action filings. Returns {SYMBOL: {subject, detail, score}}."""
    result = {}
    try:
        sess = requests.Session()
        sess.get("https://www.nseindia.com", headers=_NSE_HEADERS, timeout=8)
        resp = sess.get(
            "https://www.nseindia.com/api/home-most-active-securities?index=equities",
            headers={**_NSE_HEADERS, "X-Requested-With": "XMLHttpRequest"},
            timeout=12
        )
        # Separate filings endpoint
        resp2 = sess.get(
            "https://www.nseindia.com/api/corporates-annualReports?index=equities",
            headers={**_NSE_HEADERS, "X-Requested-With": "XMLHttpRequest"},
            timeout=12
        )
        if resp2.status_code == 200:
            data = resp2.json()
            for item in (data if isinstance(data, list) else data.get("data", [])):
                sym = str(item.get("symbol","")).strip().upper()
                subject = str(item.get("subject","") or item.get("desc",""))
                if not sym:
                    continue
                # Simple sentiment score
                pos_words = ["profit","order","win","contract","growth","capex","expansion","buyback"]
                neg_words = ["loss","downgrade","fraud","strike","penalty","default"]
                score = 15
                sl = subject.lower()
                for w in pos_words:
                    if w in sl: score += 5
                for w in neg_words:
                    if w in sl: score -= 8
                result[sym] = {"subject": subject[:100], "detail": subject[:100], "score": score}
    except Exception as e:
        log.debug(f"fetch_filings: {e}")
    return result

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — PHASE 3: EOD ORDER FLOW PROXY
# True L2 WebSocket (Phase 5 infra) replaced by:
#   delivery_pct  — % of traded volume that resulted in actual delivery
#   vol vs 20d avg — volume spike confirmation
#   VPOC zone     — value area from 20-day price distribution
# ══════════════════════════════════════════════════════════════════════════════

def compute_eod_order_flow(symbol: str, today_row: dict,
                           hist: pd.DataFrame) -> dict:
    """
    Phase 3.2 EOD proxy for Order Flow Imbalance.
    Returns:
      whale_flag       — True if delivery_pct > threshold AND volume spike
      whale_score      — 0-30 contribution to fused score
      vpoc             — Volume Point of Control price (20-day)
      at_vpoc_support  — True if close within 2% of VPOC
      delivery_pct     — raw delivery percentage from bhavcopy
      vol_ratio        — today's volume vs 20-day average
    """
    result = {
        "whale_flag": False, "whale_score": 0.0, "vpoc": 0.0,
        "at_vpoc_support": False, "delivery_pct": 0.0, "vol_ratio": 1.0,
    }
    try:
        close   = float(today_row.get("close", 0))
        volume  = float(today_row.get("volume", 0))
        deliv_pct = float(today_row.get("delivery_pct", 0))
        result["delivery_pct"] = deliv_pct

        if hist.empty or len(hist) < 20:
            return result

        # Volume ratio vs 20-day avg
        # FIX-2: exclude today from avg — .tail(20) includes today, inflating
        # the baseline and shrinking the spike ratio. iloc[-21:-1] = prior 20 sessions.
        avg_vol = float(hist["volume"].iloc[-21:-1].mean())
        vol_ratio = volume / avg_vol if avg_vol > 0 else 1.0
        result["vol_ratio"] = round(vol_ratio, 2)

        # VPOC: price level with maximum traded volume (20-day)
        # FIX-3: Typical Price = (H+L+C)/3 — NOT close price.
        # Assigning all daily volume to the close creates fake support zones.
        # Typical price distributes volume across the intraday range, producing
        # a mathematically valid VPOC that reflects where price actually traded.
        # FIX-2: exclude today from VPOC computation.
        # .tail(20) includes today — if today has a 5x volume spike, today's
        # bucket dominates all 19 prior days, making today's price the VPOC.
        # Then at_vpoc_support=True trivially (close ≈ today's price = VPOC).
        # Fix: use prior 20 sessions (iloc[-21:-1]) to find genuine historical
        # support, then test whether today's close is bouncing off that floor.
        prices = ((hist["high"] + hist["low"] + hist["close"]) / 3).iloc[-21:-1].values
        vols   = hist["volume"].iloc[-21:-1].values
        if len(prices) == len(vols) and len(prices) > 0:
            # 10-bucket histogram of price range
            p_min, p_max = prices.min(), prices.max()
            if p_max > p_min:
                bucket_size = (p_max - p_min) / 10
                buckets = np.floor((prices - p_min) / bucket_size).astype(int)
                buckets = np.clip(buckets, 0, 9)
                vol_by_bucket = np.zeros(10)
                for i, b in enumerate(buckets):
                    vol_by_bucket[b] += vols[i]
                vpoc_bucket = int(np.argmax(vol_by_bucket))
                vpoc = p_min + (vpoc_bucket + 0.5) * bucket_size
                result["vpoc"] = round(vpoc, 2)
                at_vpoc = close > 0 and abs(close - vpoc) / close < 0.02
                result["at_vpoc_support"] = at_vpoc

        # WHALE_ACCUMULATION flag (Phase 3.2)
        # High delivery + volume spike at VPOC = institutional accumulation
        whale = (deliv_pct >= WHALE_DELIVERY_PCT and vol_ratio >= WHALE_VOL_MULT)
        result["whale_flag"] = whale

        # Score contribution: 0-30 pts
        score = 0.0
        if deliv_pct >= 70:   score += 15
        elif deliv_pct >= 55: score += 8
        if vol_ratio >= 2.0:  score += 10
        elif vol_ratio >= 1.5: score += 6
        if result["at_vpoc_support"]: score += 5
        result["whale_score"] = min(score, 30.0)

    except Exception as e:
        log.debug(f"compute_eod_order_flow {symbol}: {e}")
    return result

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — PHASE 4: ALT-DATA PIPELINE
# CPP tender portal + Zauba shipping manifests → OpenAI embeddings → cosine search
# Vectors stored in Google Sheets ALT_VECTORS tab (zero Pinecone cost)
# ══════════════════════════════════════════════════════════════════════════════

# ── Alt-data scraper config ───────────────────────────────────────────────────
# FIX-2: CPP / Zauba block on datacenter IPs (GitHub Actions = known blacklisted).
# Both sites sit behind Cloudflare / Akamai bot-protection. A plain requests.get()
# from a GHA runner IP returns 403 or a CAPTCHA page — the LLM would then embed
# a CAPTCHA, poisoning the vector store.
# Solution hierarchy (in order of cost):
#   1. SCRAPERAPI_KEY set → route through ScraperAPI rotating residential proxy
#   2. Playwright + stealth → headless browser (slower, no extra cost)
#   3. No proxy available → skip gracefully (non-fatal, alt-data disabled for run)
# Set SCRAPERAPI_KEY in GitHub Actions secrets for reliable production use.
SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY", "")

def _scrape_via_proxy(url: str, params: dict = None) -> Optional[str]:
    """
    FIX-2: Route scrape through residential proxy or Playwright to bypass
    Cloudflare/Akamai bot-protection on CPP/Zauba from GHA datacenter IPs.
    Returns page HTML string or None if blocked/unavailable.
    """
    # Path 1: ScraperAPI residential proxy (set SCRAPERAPI_KEY secret)
    if SCRAPERAPI_KEY:
        try:
            api_url = "https://api.scraperapi.com/"
            target  = requests.Request("GET", url, params=params).prepare().url
            resp = requests.get(
                api_url,
                params={"api_key": SCRAPERAPI_KEY, "url": target,
                        "country_code": "in", "render": "false"},
                timeout=25,
            )
            if resp.status_code == 200:
                html = resp.text
                # FIX-2: validate we got real HTML, not a CAPTCHA/block page
                if _is_captcha_page(html):
                    log.warning(f"ScraperAPI returned CAPTCHA for {url} — skipping")
                    return None
                return html
            log.debug(f"ScraperAPI {resp.status_code} for {url}")
        except Exception as e:
            log.debug(f"ScraperAPI request: {e}")

    # Path 2: Playwright stealth (fallback, no extra cost)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"),
                locale="en-IN",
            )
            page = ctx.new_page()
            full_url = requests.Request("GET", url, params=params).prepare().url
            page.goto(full_url, timeout=20000, wait_until="domcontentloaded")
            html = page.content()
            browser.close()
            if _is_captcha_page(html):
                log.warning(f"Playwright returned CAPTCHA for {url} — skipping")
                return None
            return html
    except ImportError:
        pass  # Playwright not installed — skip gracefully
    except Exception as e:
        log.debug(f"Playwright scrape: {e}")

    # Path 3: No proxy available — skip this data source entirely
    log.debug(f"FIX-2: No proxy/browser available for {url} — alt-data skipped")
    return None

def _is_captcha_page(html: str) -> bool:
    """
    FIX-2: Detect CAPTCHA / block pages before embedding HTML.
    Poisoning the vector store with CAPTCHA text would create fake catalyst signals.
    """
    if not html or len(html) < 200:
        return True
    low = html.lower()
    captcha_signals = [
        "captcha", "cf-challenge", "ddos-guard", "ray id",
        "please enable javascript", "access denied",
        "bot protection", "verify you are human",
        "challenge-form", "turnstile",
    ]
    hits = sum(1 for s in captcha_signals if s in low)
    # Also flag if suspiciously short (block page) or missing <body>
    if len(html) < 1000 and "<body" not in low:
        return True
    return hits >= 2

def _scrape_cpp_tenders(symbol: str, company_name: str = "") -> List[str]:
    """
    Phase 4.1: CPP Portal government tender scraper.
    FIX-2: Routes via _scrape_via_proxy() to bypass Cloudflare/Akamai blocking
    on GitHub Actions datacenter IPs. Returns [] (non-fatal) if no proxy available.
    """
    results = []
    if not company_name and not symbol:
        return results
    search_term = company_name.lower() if company_name else symbol.lower()
    search_term = re.sub(r"\s*(ltd|limited|corp|pvt|india|industries?)\s*$", "",
                         search_term, flags=re.I).strip()
    html = _scrape_via_proxy(
        "https://eprocure.gov.in/eprocure/app",
        params={"page": "FrontEndTendersByOrganisation",
                "service": "page", "searchOrganisationName": search_term},
    )
    if not html:
        return results
    try:
        from html.parser import HTMLParser
        class TenderParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.in_td = False; self.texts = []
            def handle_starttag(self, tag, attrs):
                if tag == "td": self.in_td = True
            def handle_endtag(self, tag):
                if tag == "td": self.in_td = False
            def handle_data(self, data):
                if self.in_td:
                    d = data.strip()
                    if len(d) > 20: self.texts.append(d)
        parser = TenderParser()
        parser.feed(html)
        results = [t for t in parser.texts if any(
            w in t.lower() for w in ["tender","supply","work","award","contract"]
        )][:5]
    except Exception as e:
        log.debug(f"CPP parse {symbol}: {e}")
    return results

def _scrape_zauba_exports(symbol: str, company_name: str = "") -> List[str]:
    """
    Phase 4.1: Zauba Corp import/export shipping manifests.
    FIX-2: Routes via _scrape_via_proxy() — Zauba sits behind Akamai bot-protection
    and blacklists GHA datacenter IPs. Returns [] gracefully if no proxy available.
    """
    results = []
    search_term = (company_name or symbol).lower()
    search_term = re.sub(r"\s*(ltd|limited|corp|pvt|india)\s*$", "", search_term).strip()
    html = _scrape_via_proxy(
        "https://www.zauba.com/export-COMPANY-hs-code.html",
        params={"q": search_term, "detailed": "1"},
    )
    if not html:
        return results
    try:
        items = re.findall(r'<td[^>]*class="[^"]*item[^"]*"[^>]*>([^<]{20,200})<', html)
        if not items:
            items = re.findall(r'"itemName"\s*:\s*"([^"]{20,200})"', html)
        results = items[:5]
    except Exception as e:
        log.debug(f"Zauba parse {symbol}: {e}")
    return results

def _build_alt_data_text(symbol: str, tenders: List[str],
                          exports: List[str], filings_text: str = "") -> str:
    """Concatenate alt-data sources into a single embedding-ready text."""
    parts = [f"NSE symbol: {symbol}"]
    if tenders:
        parts.append("Government tenders: " + " | ".join(tenders[:3]))
    if exports:
        parts.append("Export shipments: " + " | ".join(exports[:3]))
    if filings_text:
        parts.append(f"Filing: {filings_text[:200]}")
    return " ".join(parts)

def _load_vector_store() -> List[dict]:
    """
    Load alt-data vectors from Sheets ALT_VECTORS tab.
    Each row: [symbol, source, embedding_json, raw_text, outcome_label]
    outcome_label = "WIN_50PCT" if the stock broke out 50%+ after this signal.
    """
    rows = _read_sheet("ALT_VECTORS")
    if not rows or len(rows) < 2:
        return []
    header = [h.lower() for h in rows[0]]
    vectors = []
    for row in rows[1:]:
        if not row:
            continue
        d = dict(zip(header, row))
        try:
            emb = json.loads(d.get("embedding_json", "null"))
            if emb and isinstance(emb, list):
                vectors.append({
                    "symbol": d.get("symbol",""),
                    "source": d.get("source",""),
                    "raw_text": d.get("raw_text",""),
                    "outcome": d.get("outcome_label",""),
                    "embedding": emb,
                })
        except Exception:
            continue
    return vectors

def _semantic_catalyst_match(symbol: str, alt_text: str,
                              vector_store: List[dict]) -> dict:
    """
    Phase 4.2: Cosine similarity search.
    Compares current alt-data text embedding against historical WIN_50PCT patterns.
    Returns {matched: bool, best_sim: float, match_label: str, catalyst_sub: bool}
    """
    result = {"matched": False, "best_sim": 0.0,
              "match_label": "", "catalyst_sub": False}
    if not alt_text or not _OPENAI_OK:
        return result
    # Only match against historical breakout signals
    win_vectors = [v for v in vector_store
                   if "WIN" in v.get("outcome","").upper() or "50" in v.get("outcome","")]
    if not win_vectors:
        return result
    try:
        current_emb = _embed_openai(alt_text)
        if current_emb is None:
            return result
        best_sim = 0.0
        best_label = ""
        for v in win_vectors:
            sim = _cosine_sim(current_emb, v["embedding"])
            if sim > best_sim:
                best_sim = sim
                best_label = v.get("raw_text","")[:60]
        result["best_sim"] = round(best_sim, 4)
        result["matched"] = best_sim >= ALT_DATA_MATCH_SIM
        result["match_label"] = best_label
        result["catalyst_sub"] = result["matched"]  # valid catalyst substitute
        if result["matched"]:
            log.info(f"ALT-DATA MATCH {symbol}: sim={best_sim:.3f} ≥ {ALT_DATA_MATCH_SIM} "
                     f"→ semantic catalyst confirmed ✅")
    except Exception as e:
        log.debug(f"_semantic_catalyst_match {symbol}: {e}")
    return result

def store_alt_vector(symbol: str, source: str, raw_text: str,
                     outcome_label: str = "") -> bool:
    """
    Store an alt-data embedding in the Sheets vector store.
    Called by the outcome engine when a trade closes at +50% or more.
    outcome_label = "WIN_50PCT", "WIN_R3", etc.
    """
    if not _OPENAI_OK or not raw_text:
        return False
    try:
        emb = _embed_openai(raw_text)
        if emb is None:
            return False
        ws = _get_ws("ALT_VECTORS")
        if ws is None:
            return False
        # Ensure header exists
        existing = ws.get_all_values()
        if not existing:
            ws.append_row(["symbol","source","embedding_json","raw_text","outcome_label","stored_at"])
        ws.append_row([
            symbol, source, json.dumps(emb), raw_text[:500],
            outcome_label, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        ], value_input_option="USER_ENTERED")
        log.info(f"ALT_VECTORS: stored embedding for {symbol} ({outcome_label}) ✅")
        return True
    except Exception as e:
        log.warning(f"store_alt_vector {symbol}: {e}")
        return False

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — HALAL SCREENING (4-Layer, preserved from v5.5)
# L1: keyword veto (instant, no LLM)
# L2: financial ratio screen (debt/equity, interest coverage)
# L3: sector ethical overlay
# L4: OpenAI gpt-4o-mini business model analysis (cached 7d)
# ══════════════════════════════════════════════════════════════════════════════

_HARAM_KEYWORDS = {
    "BANK", "BANKING", "FINANCE", "INSURANCE", "NBFC", "LENDER", "MICROFINANCE",
    "ALCOHOL", "BEER", "WINE", "SPIRITS", "TOBACCO", "CIGARETTE", "CASINO",
    "GAMBLING", "LOTTERY", "PORK", "HOTEL", "RESORT",
    "DEFENCE", "WEAPON", "AMMUNITION", "ARMS",
}
_HALAL_SECTORS = {
    "IT", "PHARMA", "FMCG", "AUTO", "CHEMICALS", "TEXTILE",
    "INFRA", "REALTY", "METAL", "ENERGY", "DIVERSIFIED",
}

def halal_l1_veto(symbol: str) -> Tuple[bool, str]:
    """L1: keyword veto on symbol name. Returns (vetoed, reason)."""
    sym = symbol.upper()
    for kw in _HARAM_KEYWORDS:
        if kw in sym:
            return True, f"L1 keyword veto: {kw} in {sym}"
    return False, ""

def get_sector(sym: str) -> str:
    """Map symbol to sector using NSE industry classification proxy."""
    sym = sym.upper()
    sector_map = {
        "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "HCLTECH": "IT", "TECHM": "IT",
        "LTIM": "IT", "MPHASIS": "IT", "COFORGE": "IT", "PERSISTENT": "IT",
        "SUNPHARMA": "PHARMA", "DRREDDY": "PHARMA", "CIPLA": "PHARMA",
        "DIVISLAB": "PHARMA", "TORNTPHARM": "PHARMA", "ALKEM": "PHARMA",
        "HINDUNILVR": "FMCG", "ITC": "FMCG", "NESTLEIND": "FMCG",
        "BRITANNIA": "FMCG", "DABUR": "FMCG", "MARICO": "FMCG", "COLPAL": "FMCG",
        "MARUTI": "AUTO", "TATAMOTORS": "AUTO", "M&M": "AUTO",
        "BAJAJ-AUTO": "AUTO", "HEROMOTOCO": "AUTO", "EICHERMOT": "AUTO",
        "DEEPAKNTR": "CHEMICALS", "PIIND": "CHEMICALS", "ATUL": "CHEMICALS",
        "NAVINFLUOR": "CHEMICALS", "FINEORG": "CHEMICALS", "NOCIL": "CHEMICALS",
        "JSWSTEEL": "METAL", "TATASTEEL": "METAL", "HINDZINC": "METAL",
        "VEDL": "METAL", "NATIONALUM": "METAL", "NMDC": "METAL",
        "RELIANCE": "ENERGY", "ONGC": "ENERGY", "BPCL": "ENERGY",
        "TATAPOWER": "ENERGY", "ADANIGREEN": "ENERGY", "ADANITRANS": "ENERGY",
        "LT": "INFRA", "NCC": "INFRA", "KNR": "INFRA", "AHLUCONT": "INFRA",
        "HGINFRA": "INFRA", "IRCON": "INFRA", "NBCC": "INFRA",
        "TITAN": "FMCG", "TRENT": "FMCG", "PAGEIND": "TEXTILE",
        "ASTRAL": "CHEMICALS", "POLYCAB": "INFRA", "HAVELLS": "INFRA",
        "DIXON": "IT", "KAYNES": "IT",
    }
    return sector_map.get(sym, "DIVERSIFIED")

def halal_ai_screen(symbol: str, sector: str = "DIVERSIFIED") -> dict:
    """
    4-layer Halal AI Screen.
    Returns {veto: bool, tier: str, score: int, source: str, veto_reason: str}
    """
    # L1: Keyword veto (instant)
    vetoed, reason = halal_l1_veto(symbol)
    if vetoed:
        return {"veto": True, "tier": "HARAM", "score": 0,
                "source": "L1_KEYWORD", "veto_reason": reason}

    # L2: Sector screen
    if sector in ("BANK", "FINANCE", "INSURANCE", "NBFC"):
        return {"veto": True, "tier": "HARAM", "score": 0,
                "source": "L2_SECTOR", "veto_reason": f"Sector {sector} is non-halal"}

    # L3: Ethical overlay (known FMCG with haram products)
    haram_l3 = {"UNITEDSPIRITS", "TILAKNAGAR", "RADICO", "GLOBUSSPR",
                 "PICCADILY", "DHARAMPAL", "VSTIND", "GODFRYPHLP"}
    if symbol.upper() in haram_l3:
        return {"veto": True, "tier": "HARAM", "score": 0,
                "source": "L3_ETHICAL", "veto_reason": "Known haram product manufacturer"}

    # L4: OpenAI LLM business model analysis
    if not _OPENAI_OK:
        return {"veto": False, "tier": "ACCEPTABLE", "score": 60,
                "source": "L4_SKIPPED", "veto_reason": ""}

    prompt = f"""Analyse if NSE-listed company {symbol} (sector: {sector}) is Shariah-compliant.
Consider: core business activity, revenue sources, debt structure.
Respond ONLY with JSON: {{"halal": true/false, "tier": "PURE|ACCEPTABLE|DOUBTFUL|HARAM",
"score": 0-100, "reason": "one sentence"}}
Do not explain — JSON only."""
    cache_key = hashlib.md5(f"halal_l4:{symbol}:{sector}".encode()).hexdigest()
    cached = _llm_cache_get(cache_key)
    raw = cached
    if raw is None:
        raw = _call_openai(prompt, max_tokens=150, cache_ttl_days=30)
        if raw:
            _llm_cache_put(cache_key, raw, "halal_l4", OPENAI_MINI_MODEL, ttl_days=30)
    if raw:
        try:
            clean = re.sub(r"```json|```", "", raw).strip()
            parsed = json.loads(clean)
            is_haram = not parsed.get("halal", True)
            return {
                "veto": is_haram,
                "tier": parsed.get("tier", "ACCEPTABLE"),
                "score": int(parsed.get("score", 60)),
                "source": "L4_LLM",
                "veto_reason": parsed.get("reason","") if is_haram else "",
                "llm_confidence": parsed.get("score", 60) / 100,
            }
        except Exception:
            pass
    return {"veto": False, "tier": "ACCEPTABLE", "score": 60,
            "source": "L4_FALLBACK", "veto_reason": ""}

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 10 — TECHNICAL INDICATORS
# Preserved from v5.5: ATR, RSI, ADX, MFI, VPOC, VCP in one shared pass.
# ══════════════════════════════════════════════════════════════════════════════

def compute_indicators(df: pd.DataFrame) -> dict:
    """
    Single fused indicator pass — 4x faster than separate calls.
    Returns dict with atr14, atr7, atr20, atr50, atr100,
    rsi14, adx14, mfi, pdi, ndi.
    """
    empty = {k: 0.0 for k in ["atr14","atr7","atr20","atr50","atr100",
                                "rsi14","adx14","mfi","pdi","ndi","atr_s"]}
    if df.empty or len(df) < 7:
        return empty
    try:
        h = df["high"].astype(float)
        l = df["low"].astype(float)
        c = df["close"].astype(float)
        v = df["volume"].astype(float) if "volume" in df.columns else pd.Series(np.ones(len(df)))

        # True range
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)

        # ATR family
        atr14_s  = tr.ewm(span=14,  adjust=False).mean()
        atr7_s   = tr.ewm(span=7,   adjust=False).mean()
        atr20_s  = tr.ewm(span=20,  adjust=False).mean()
        atr50_s  = tr.ewm(span=50,  adjust=False).mean()
        atr100_s = tr.ewm(span=100, adjust=False).mean()
        atr14  = float(atr14_s.iloc[-1])  if len(df) >= 14  else 0.0
        atr7   = float(atr7_s.iloc[-1])   if len(df) >= 7   else atr14
        atr20  = float(atr20_s.iloc[-1])  if len(df) >= 20  else atr14
        atr50  = float(atr50_s.iloc[-1])  if len(df) >= 50  else atr14
        atr100 = float(atr100_s.iloc[-1]) if len(df) >= 100 else atr14

        # RSI-14
        delta = c.diff()
        gain  = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
        loss  = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
        rs    = gain / loss.replace(0, np.nan)
        rsi14 = float((100 - 100 / (1 + rs)).iloc[-1]) if not rs.isna().all() else 50.0

        # ADX/PDI/NDI
        period = 14
        pdm = (h.diff()).clip(lower=0)
        ndm = (-l.diff()).clip(lower=0)
        pdm[pdm < 0] = 0; ndm[ndm < 0] = 0
        atr_adx = tr.ewm(span=period, adjust=False).mean()
        pdi = 100 * pdm.ewm(span=period, adjust=False).mean() / atr_adx.replace(0, np.nan)
        ndi = 100 * ndm.ewm(span=period, adjust=False).mean() / atr_adx.replace(0, np.nan)
        dx  = (100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan))
        adx14 = float(dx.ewm(span=period, adjust=False).mean().iloc[-1]) if len(df) >= period else 0.0

        # MFI-14
        tp   = (h + l + c) / 3
        mf   = tp * v
        pos  = mf.where(tp > tp.shift(), 0).rolling(14).sum()
        neg  = mf.where(tp <= tp.shift(), 0).rolling(14).sum()
        mfi_v = float((100 - 100 / (1 + pos / neg.replace(0, np.nan))).iloc[-1]) if len(df) >= 14 else 50.0

        return {
            "atr14": atr14, "atr7": atr7, "atr20": atr20,
            "atr50": atr50, "atr100": atr100,
            "rsi14": round(rsi14, 1), "adx14": round(adx14, 1),
            "mfi": round(mfi_v, 1), "pdi": round(float(pdi.iloc[-1]), 1),
            "ndi": round(float(ndi.iloc[-1]), 1), "atr_s": atr14_s,
        }
    except Exception as e:
        log.debug(f"compute_indicators: {e}")
        return empty

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 11 — FORTRESS SCORING ENGINE (preserved from v5.5, Phase-2 ATR wired)
# 200-point system:
#   VPOC support (25), 52W compression (20), VCP coil (20),
#   ATR velocity (15), volume dry-up (15), FII/DII (20), insider (15),
#   filing sentiment (15), whale score (25) [Phase-3 new], div_score (10)
# ══════════════════════════════════════════════════════════════════════════════

def fortress_score(symbol: str, today_row: dict, hist: pd.DataFrame,
                   fii_data: dict, insider_map: dict, filings: dict,
                   macro: dict, order_flow: dict) -> dict:
    """
    Fortress scoring with ATR-dynamic stops (Phase 2.2) and whale score (Phase 3).
    Returns dict with fort_pts, stop_loss, buy_lo, buy_hi, r1, r2, r3, story, etc.
    """
    sym = symbol.upper()
    ind = compute_indicators(hist)
    atr14   = ind["atr14"]
    atr100  = ind["atr100"]
    rsi14   = ind["rsi14"]
    adx14   = ind["adx14"]
    mfi     = ind["mfi"]

    close   = float(today_row.get("close", 0))
    volume  = float(today_row.get("volume", 0))
    high    = float(today_row.get("high", close))
    low     = float(today_row.get("low", close))
    sector  = get_sector(sym)
    atr_mult = macro.get("atr_mult", ATR_MULT_CHOP)
    macro_state = macro.get("macro_state", "CHOP")

    if close <= 0:
        return {}

    fort_pts = 0
    story_parts = []

    # 1. 52-Week compression + proximity
    if not hist.empty and len(hist) >= 52:
        hi52 = float(hist["high"].tail(252).max()) if len(hist) >= 252 else float(hist["high"].max())
        lo52 = float(hist["low"].tail(252).min())  if len(hist) >= 252 else float(hist["low"].min())
        pct_from_h = (hi52 - close) / hi52 * 100 if hi52 > 0 else 100
        range_ratio = (hi52 - lo52) / lo52 * 100 if lo52 > 0 else 100
        atr_tight   = atr14 > 0 and atr100 > 0 and (atr14 / atr100) < 0.70
        if pct_from_h <= 5:    w52_bonus = 20 if atr_tight else 15
        elif pct_from_h <= 10: w52_bonus = 12 if atr_tight else 8
        elif pct_from_h <= 20: w52_bonus = 6
        else:                  w52_bonus = 0
        fort_pts += w52_bonus
        if w52_bonus >= 12:
            story_parts.append(f"52W compression: {pct_from_h:.1f}% from high")

    # 2. VCP coil (ATR14 / ATR100 contraction)
    # FIX-3: TREND GATE required before awarding VCP points.
    # A dead-cat bounce / downtrending stock also shows low ATR14/ATR100
    # (abandoned, no volatility) AND low volume — it scores perfect VCP/VDU
    # without Minervini's prerequisite uptrend context.
    # Gate: close must be above 50-MA AND 50-MA above 200-MA (price structure).
    _ma50  = float(hist["close"].rolling(50).mean().iloc[-1])  if len(hist) >= 50  else 0.0
    _ma200 = float(hist["close"].rolling(200).mean().iloc[-1]) if len(hist) >= 200 else 0.0
    _in_uptrend = (
        close > _ma50 > 0 and                    # price above 50-MA
        (_ma200 == 0.0 or _ma50 > _ma200 * 0.97) # 50-MA above (or within 3% of) 200-MA
    )
    vcp_score = 0
    if _in_uptrend and atr14 > 0 and atr100 > 0:
        ratio = atr14 / atr100
        if ratio < 0.60:   vcp_score = 20
        elif ratio < 0.70: vcp_score = 14
        elif ratio < 0.80: vcp_score = 8
        else:              vcp_score = 0
    elif not _in_uptrend:
        log.debug(f"VCP gate FAIL {sym}: close={close:.0f} ma50={_ma50:.0f} ma200={_ma200:.0f}")
    fort_pts += vcp_score
    if vcp_score >= 14:
        story_parts.append(f"VCP coil ATR={atr14/atr100:.2f} (uptrend ✅)")

    # 3. ATR velocity (short vs long ATR)
    atrv_bonus = 0
    if ind["atr7"] > 0 and ind["atr50"] > 0:
        rate = (ind["atr7"] - ind["atr50"]) / ind["atr50"]
        if rate > 0.50:   atrv_bonus = 15
        elif rate > 0.30: atrv_bonus = 10
        elif rate > 0.10: atrv_bonus = 5
        elif ind["atr50"] > 0 and ind["atr7"] < ind["atr50"]:
            atrv_bonus = 2
    fort_pts += atrv_bonus

    # 4. Volume dry-up (VDU) — volume contracting while price stable
    # FIX-3: same trend gate — low VDU on a dead downtrend = abandonment, not coil.
    vdu_score = 0
    if _in_uptrend and not hist.empty and len(hist) >= 20:
        recent_vol = float(hist["volume"].tail(5).mean())
        # FIX-2: exclude today from base_vol (same look-ahead dilution fix)
        base_vol   = float(hist["volume"].iloc[-21:-1].mean())
        if base_vol > 0:
            vdu_ratio = recent_vol / base_vol
            if vdu_ratio < 0.40:   vdu_score = 15
            elif vdu_ratio < 0.60: vdu_score = 10
            elif vdu_ratio < 0.80: vdu_score = 5
    fort_pts += vdu_score

    # 5. FII/DII contribution
    fii_score = int(fii_data.get("score", 15))
    fii_bonus = min(20, max(0, (fii_score - 10) // 2))
    fort_pts += fii_bonus
    if fii_bonus >= 10:
        story_parts.append(f"FII {fii_data.get('label','MIXED')}")

    # 6. Insider accumulation
    ins = insider_map.get(sym, {})
    ins_bonus = 0
    if ins.get("count", 0) > 0:
        ins_bonus = min(15, int(ins.get("total_cr", 0) * 2 + ins.get("count", 0) * 3))
        story_parts.append(f"Insider ₹{ins.get('total_cr',0):.0f}Cr ({ins['count']} txn)")
    fort_pts += ins_bonus

    # 7. Filing sentiment
    fil = filings.get(sym, {})
    fil_bonus = 0
    if fil.get("score", 15) >= 20:
        fil_bonus = 15
        story_parts.append("Positive filing")
    elif fil.get("score", 15) <= 8:
        fil_bonus = -10
    fort_pts += fil_bonus

    # 8. Phase-3 whale score (order flow proxy)
    whale_score = float(order_flow.get("whale_score", 0))
    fort_pts += int(whale_score)
    if order_flow.get("whale_flag"):
        story_parts.append(f"🐳 WHALE_ACCUM del={order_flow.get('delivery_pct',0):.0f}% "
                           f"vol={order_flow.get('vol_ratio',1):.1f}x")

    # 9. RSI momentum confirmation
    if 50 <= rsi14 <= 70:
        fort_pts += 8
    elif rsi14 > 70:
        fort_pts += 4  # slightly extended

    # 10. ADX trend strength
    if adx14 >= 25:
        fort_pts += 8
    elif adx14 >= 20:
        fort_pts += 4

    # Phase-2.2: ATR-dynamic stop loss (replaces static %)
    stop_loss = atr_dynamic_stop(close, atr14, sector, macro_state, atr_mult)

    # Entry zone (tight ATR-based spread)
    lo_pct = max(0.005, min(0.04, (atr14 / close) * 0.8)) if close > 0 and atr14 > 0 else 0.015
    hi_pct = max(0.003, min(0.025, (atr14 / close) * 0.5)) + 0.01 if close > 0 and atr14 > 0 else 0.01
    buy_lo = round(close * (1 - lo_pct), 2)
    buy_hi = round(close * (1 + hi_pct), 2)

    # Targets: R1=1.5R, R2=3R, R3=5R (R = entry - stop)
    risk   = max(close - stop_loss, close * 0.03)
    r1     = round(close + risk * 1.5, 2)
    r2     = round(close + risk * 3.0, 2)
    r3     = round(close + risk * 5.0, 2)

    # Phase-2.2: ATR position size
    shares = atr_position_size(ACCOUNT_EQUITY, ACCOUNT_RISK_PCT, close, stop_loss)

    # Grade
    fp = fort_pts
    if fp >= 160:   grade = "APEX"
    elif fp >= 140: grade = "PRISTINE"
    elif fp >= 120: grade = "GOOD"
    elif fp >= 100: grade = "PROBE"
    else:           grade = "WATCHLIST"

    story = " | ".join(story_parts) if story_parts else f"Fortress {fort_pts}pts {macro_state}"

    return {
        "symbol": sym, "sector": sector, "fort_pts": fort_pts, "grade": grade,
        "close": close, "stop_loss": stop_loss, "buy_lo": buy_lo, "buy_hi": buy_hi,
        "r1": r1, "r2": r2, "r3": r3, "shares": shares,
        "rsi14": rsi14, "adx14": adx14, "mfi": mfi, "atr14": round(atr14, 2),
        "whale_score": whale_score, "delivery_pct": order_flow.get("delivery_pct", 0),
        "vol_ratio": order_flow.get("vol_ratio", 1.0),
        "whale_flag": order_flow.get("whale_flag", False),
        "vpoc": order_flow.get("vpoc", 0), "at_vpoc": order_flow.get("at_vpoc_support", False),
        "story": story, "macro_state": macro_state, "atr_mult": atr_mult,
    }

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 12 — APEX COMPOSITE ENGINE (7-factor, preserved from v5.5)
# ══════════════════════════════════════════════════════════════════════════════

def apex_composite(symbol: str, fortress: dict, hist: pd.DataFrame,
                   macro: dict, fii_data: dict) -> dict:
    """
    7-factor APEX composite score (0-100):
    1. Momentum (RSI + ADX)
    2. Volume structure (MFI + whale)
    3. Regime alignment (macro_state)
    4. 52W positioning
    5. VCP coil quality
    6. FII flow
    7. Phase-3 order flow
    """
    if not fortress or fortress.get("close", 0) <= 0:
        return {"apex_comp": 0.0}

    scores = []

    # 1. Momentum
    rsi = fortress.get("rsi14", 50)
    adx = fortress.get("adx14", 0)
    mom = 0
    if 45 <= rsi <= 65: mom = 20
    elif 35 <= rsi < 45 or 65 < rsi <= 72: mom = 12
    elif rsi > 72: mom = 6
    if adx >= 25: mom = min(20, mom + 8)
    elif adx >= 18: mom = min(20, mom + 4)
    scores.append(("momentum", mom, 20))

    # 2. Volume structure (MFI + whale)
    mfi = fortress.get("mfi", 50)
    ws  = fortress.get("whale_score", 0)
    vol_s = 0
    if 40 <= mfi <= 65: vol_s = 15
    elif mfi < 40:      vol_s = 10  # oversold accumulation
    if ws >= 20: vol_s = min(20, vol_s + 5)
    scores.append(("volume", vol_s, 20))

    # 3. Regime alignment
    state = macro.get("macro_state", "CHOP")
    fp    = fortress.get("fort_pts", 0)
    reg_s = {"TREND": 20, "CHOP": 12, "BUNKER": 6, "PANIC": 0, "MASSACRE": 0}.get(state, 10)
    # Downgrade if setup is weak in TREND (shouldn't fire APEX on mediocre TREND setups)
    if state == "TREND" and fp < 120: reg_s = 12
    scores.append(("regime", reg_s, 20))

    # 4. FII alignment
    fii_score = int(fii_data.get("score", 15))
    fii_s = min(15, max(0, (fii_score - 10)))
    scores.append(("fii", fii_s, 15))

    # 5. VCP + ATR contraction quality
    atr14  = fortress.get("atr14", 0)
    close  = fortress.get("close", 1)
    vcp_pct = (atr14 / close) * 100 if close > 0 and atr14 > 0 else 5
    vcp_s = 15 if vcp_pct < 1.5 else (10 if vcp_pct < 2.5 else (5 if vcp_pct < 4 else 0))
    scores.append(("vcp", vcp_s, 15))

    # 6. VPOC support (Phase-3)
    vpoc_s = 10 if fortress.get("at_vpoc") else 0
    scores.append(("vpoc_support", vpoc_s, 10))

    # 7. Whale flag bonus
    whale_bonus = 5 if fortress.get("whale_flag") else 0
    # Normalise to 0-100
    raw = sum(s for _, s, _ in scores) + whale_bonus
    max_pts = sum(m for _, _, m in scores) + 5
    apex = round(min(100, raw / max_pts * 100), 1)

    # Regime scale: CLEAR+trending gets 1.08× uplift (v5.5 ACC-4 preserved)
    if state in ("TREND",) and adx >= 20:
        apex = round(min(100, apex * 1.08), 1)

    return {"apex_comp": apex, "apex_breakdown": {n: s for n, s, _ in scores}}

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 13 — BAYESIAN WIN PROBABILITY (14-node, preserved from v5.5)
# ══════════════════════════════════════════════════════════════════════════════

# Prior win rates by condition (populated from historical data; cold-start defaults)
_BAYES_PRIORS = {
    "vcp_tight":        0.62,
    "whale_accum":      0.68,
    "insider_bought":   0.64,
    "fii_bull":         0.57,
    "vpoc_support":     0.60,
    "rsi_45_65":        0.56,
    "adx_25_plus":      0.58,
    "delivery_high":    0.63,
    "regime_trend":     0.65,
    "regime_chop":      0.48,
    "filing_positive":  0.59,
    "atr_contracting":  0.61,
    "52w_near_high":    0.64,
    "mfi_accumulation": 0.57,
}

def bayes_win_probability(fortress: dict, apex: dict,
                           macro: dict, order_flow: dict) -> float:
    """
    14-node Bayesian network: multiply conditional probabilities.
    Returns win_pct ∈ [0, 100].
    """
    if not fortress:
        return 50.0
    prior = 0.50
    factors = []

    def _apply(node: str, cond: bool, strength: float = 1.0):
        p = _BAYES_PRIORS.get(node, 0.55)
        factors.append(p if cond else (1 - p * 0.5))

    fp    = fortress.get("fort_pts", 0)
    rsi   = fortress.get("rsi14", 50)
    adx   = fortress.get("adx14", 0)
    mfi   = fortress.get("mfi", 50)
    atr14 = fortress.get("atr14", 1)
    a100  = fortress.get("atr14", 1)  # use atr14 as proxy when atr100 unavailable
    state = macro.get("macro_state", "CHOP")

    _apply("vcp_tight",       atr14 < a100 * 0.80)
    _apply("whale_accum",     fortress.get("whale_flag", False))
    _apply("insider_bought",  fortress.get("ins_count", 0) > 0)
    _apply("fii_bull",        macro.get("breadth_ok", True) and state == "TREND")
    _apply("vpoc_support",    fortress.get("at_vpoc", False))
    _apply("rsi_45_65",       45 <= rsi <= 65)
    _apply("adx_25_plus",     adx >= 25)
    _apply("delivery_high",   fortress.get("delivery_pct", 0) >= 55)
    _apply("regime_trend",    state == "TREND")
    _apply("regime_chop",     state == "CHOP")
    _apply("filing_positive", fortress.get("fil_score", 15) >= 20)
    _apply("atr_contracting", atr14 < a100 * 0.70 if a100 > 0 else False)
    _apply("52w_near_high",   fp >= 140)
    _apply("mfi_accumulation", mfi < 50)

    # Naive Bayes: product of factors
    result = prior
    for f in factors:
        result = result * f / (result * f + (1 - result) * (1 - f))
    return round(result * 100, 1)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 14 — LLM STORY ENRICHMENT (OpenAI gpt-4o-mini, Phase 4)
# ══════════════════════════════════════════════════════════════════════════════

def llm_enrich_pick(symbol: str, fortress: dict, apex: dict,
                     bayes_pct: float, macro: dict, fii_data: dict,
                     insider_map: dict, filings: dict,
                     alt_match: dict) -> dict:
    """
    OpenAI gpt-4o-mini enrichment.
    Returns {llm_why, llm_verdict, llm_confidence, llm_catalyst, llm_narrative}
    Cached 24h. Falls back to rule-based story on failure.
    """
    default = {
        "llm_why": fortress.get("story","Technical setup"),
        "llm_verdict": "QUALIFIED",
        "llm_confidence": 0.60,
        "llm_catalyst": "",
        "llm_narrative": "",
    }
    if not _OPENAI_OK:
        return default

    sym     = symbol.upper()
    sector  = fortress.get("sector", "DIVERSIFIED")
    grade   = fortress.get("grade", "GOOD")
    fp      = fortress.get("fort_pts", 0)
    ac      = apex.get("apex_comp", 0)
    stop    = fortress.get("stop_loss", 0)
    close   = fortress.get("close", 0)
    risk_r  = round((fortress.get("r1",close) - close) / max(close - stop, 1), 2) if close > stop else 1.5
    state   = macro.get("macro_state","CHOP")
    fii_lbl = fii_data.get("label","MIXED")
    ins     = insider_map.get(sym, {})
    fil     = filings.get(sym, {})
    whale   = fortress.get("whale_flag", False)
    alt_txt = alt_match.get("match_label","")

    prompt = f"""You are a concise quant analyst for NSE India mid/small-cap stocks.

SETUP: {sym} | Sector: {sector} | Grade: {grade}
Scores: Fortress={fp}/200 APEX={ac}/100 Bayes={bayes_pct:.0f}%
Regime: {state} | FII: {fii_lbl} | RSI={fortress.get('rsi14',50):.0f} ADX={fortress.get('adx14',0):.0f}
ATR stop: ₹{stop:.0f} (dynamic) | R1:R = {risk_r:.1f}:1 | Whale_accum={whale}
Insider: {f"₹{ins.get('total_cr',0):.0f}Cr bought" if ins.get('count') else "None"}
Filing: {fil.get('subject','None')[:60]}
Alt-data match: {alt_txt or "None"}
Delivery%: {fortress.get('delivery_pct',0):.0f}% | Vol ratio: {fortress.get('vol_ratio',1):.1f}x

Respond ONLY as JSON (no markdown):
{{
  "verdict": "STRONG_BUY|BUY|HOLD|SKIP",
  "confidence": 0.0-1.0,
  "why": "≤15 words: key edge",
  "catalyst": "primary catalyst or empty string",
  "risk_note": "≤10 words: main risk"
}}"""

    raw = _call_openai(prompt, max_tokens=200, cache_ttl_days=1)
    if raw:
        try:
            clean = re.sub(r"```json|```", "", raw).strip()
            parsed = json.loads(clean)
            return {
                "llm_why":        str(parsed.get("why",""))[:120],
                "llm_verdict":    str(parsed.get("verdict","QUALIFIED")),
                "llm_confidence": float(parsed.get("confidence", 0.60)),
                "llm_catalyst":   str(parsed.get("catalyst",""))[:80],
                "llm_narrative":  str(parsed.get("risk_note",""))[:80],
            }
        except Exception:
            pass
    return default

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 15 — CONVICTION RE-RANK (Option-C preserved from v5.5.2 patch)
# ══════════════════════════════════════════════════════════════════════════════

def _compute_rs_pct(symbol: str, hist: pd.DataFrame,
                    hist_cache: Dict[str, pd.DataFrame],
                    hist_lock: threading.Lock = None) -> float:
    """
    Relative strength percentile vs universe (0-100).
    FIX-3: hist_cache is actively mutated by _bg_preload() on a background
    thread. Calling .items() without a lock raises
    RuntimeError: dictionary changed size during iteration.
    Because the except clause returned 50.0, every rs_pct silently defaulted
    to 50 — below CONV_RS_CATALYST_FLOOR (85) — killing Option-C for all picks.
    Fix: acquire hist_lock before snapshotting the dict into a local list.
    """
    if hist.empty or len(hist) < 63:
        return 50.0
    try:
        sym_ret = float(hist["close"].iloc[-1] / hist["close"].iloc[-63] - 1)
        # FIX-3: snapshot under lock before iterating
        if hist_lock is not None:
            with hist_lock:
                cache_items = list(hist_cache.items())[:50]
        else:
            cache_items = list(hist_cache.items())[:50]
        returns = [sym_ret]
        for s, h in cache_items:
            if s == symbol or h.empty or len(h) < 63:
                continue
            try:
                returns.append(float(h["close"].iloc[-1] / h["close"].iloc[-63] - 1))
            except Exception:
                pass
        if len(returns) < 3:
            return 50.0
        arr = np.array(returns)
        pct = float(np.searchsorted(np.sort(arr), sym_ret) / len(arr) * 100)
        return round(pct, 1)
    except Exception:
        return 50.0

def apply_conviction_rerank(pick: dict, rs_pct: float,
                             has_catalyst: bool,
                             alt_match: dict) -> dict:
    """
    Option-C catalyst fallback (v5.5.2 patch preserved).
    If grade is APEX/PRISTINE and has_catalyst=False:
      - If rs_pct >= CONV_RS_CATALYST_FLOOR OR alt_match.catalyst_sub → retain grade
      - Else → downgrade to GOOD
    """
    if not CONVICTION_RERANK:
        return pick
    grade = pick.get("grade","GOOD")
    if not CONV_REQUIRE_CATALYST:
        return pick
    if grade not in ("APEX","PRISTINE"):
        return pick
    if has_catalyst:
        return pick

    # Option-C: RS momentum substitutes for news catalyst
    if rs_pct >= CONV_RS_CATALYST_FLOOR:
        pick["story"] = (pick.get("story","") +
                         f" | ✅ RS{rs_pct:.0f}pct catalyst-sub (≥{CONV_RS_CATALYST_FLOOR:.0f})")
        log.info(f"  Option-C: {pick.get('symbol')} rs_pct={rs_pct:.0f} ≥ "
                 f"{CONV_RS_CATALYST_FLOOR:.0f} — grade {grade} retained")
        return pick

    # Phase-4 alt-data semantic match also substitutes
    if alt_match.get("catalyst_sub"):
        pick["story"] = (pick.get("story","") +
                         f" | ✅ ALT-DATA catalyst-sub sim={alt_match.get('best_sim',0):.3f}")
        log.info(f"  Option-C: {pick.get('symbol')} alt-data match — grade {grade} retained")
        return pick

    # Downgrade
    pick["grade"] = "GOOD"
    pick["story"] = (pick.get("story","") +
                     f" | ⚠️ capped GOOD: no catalyst, RS{rs_pct:.0f}pct<{CONV_RS_CATALYST_FLOOR:.0f}")
    return pick

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 16 — FUSED SCORING
# Combines fort_pts (normalised) + apex_comp + bayes + whale + conviction
# ══════════════════════════════════════════════════════════════════════════════

def fused_score(fortress: dict, apex: dict, bayes_pct: float) -> float:
    """
    Fused score = weighted combination of all engines.
    0-100 scale.
    """
    fp_norm = fortress.get("fort_pts", 0) / 200 * 100   # 200 max → 0-100
    ac      = apex.get("apex_comp", 0)
    bp      = bayes_pct
    ws      = fortress.get("whale_score", 0) / 30 * 100  # 30 max → 0-100
    # Weights: fortress 40%, apex 30%, bayes 20%, whale 10%
    fused = fp_norm * 0.40 + ac * 0.30 + bp * 0.20 + ws * 0.10
    return round(min(fused, 100), 1)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 17 — SCORE ONE SYMBOL (worker function for parallel scoring)
# ══════════════════════════════════════════════════════════════════════════════

def _intelligence_hash(fii_data: dict, insider_map: dict, filings: dict) -> str:
    data = f"{fii_data.get('label')}{len(insider_map)}{len(filings)}"
    return hashlib.md5(data.encode()).hexdigest()[:8]

def score_one_symbol(args: tuple) -> Optional[dict]:
    """
    Full scoring pipeline for one symbol.
    Args: (sym, row_dict, hist_cache, fii_data, insider_map, filings,
           macro, date_label, vector_store, fast_rerun, hist_lock)
    FIX-3: hist_lock passed in so _compute_rs_pct can snapshot hist_cache
    safely without triggering RuntimeError on concurrent dict mutation.
    """
    (sym, row, hist_cache, fii_data, insider_map,
     filings, macro, date_label, vector_store, fast_rerun, hist_lock) = args

    try:
        close = float(row.get("close", 0))
        if close <= 0:
            return None

        # L1 halal veto (instant, no LLM)
        vetoed, reason = halal_l1_veto(sym)
        if vetoed:
            log.debug(f"L1 veto {sym}: {reason}")
            return None

        intel_hash = _intelligence_hash(fii_data, insider_map, filings)

        # Score cache check (fast rerun)
        if fast_rerun:
            cached = _score_cache_get(sym, date_label, close, intel_hash)
            if cached:
                return cached

        # Fetch history (from cache or live)
        hist = hist_cache.get(sym.upper())
        if hist is None:
            hist = fetch_history(sym, days=300)
            if not hist.empty:
                hist_cache[sym.upper()] = hist

        if hist.empty or len(hist) < 20:
            return None

        # Phase 3: EOD order flow
        order_flow = compute_eod_order_flow(sym, row, hist)

        # Fortress scoring (Phase 2 ATR wired)
        fort = fortress_score(sym, row, hist, fii_data, insider_map,
                              filings, macro, order_flow)
        if not fort or fort.get("fort_pts", 0) < 80:
            return None

        # Halal check (L2/L3 fast, L4 LLM only for candidates above fort gate)
        sector = get_sector(sym)
        halal  = halal_ai_screen(sym, sector)
        if halal.get("veto"):
            log.debug(f"Halal veto {sym}: {halal.get('veto_reason','')}")
            return None
        if halal.get("score", 0) < 50:
            log.debug(f"{sym} halal score {halal.get('score')} < 50 — skip")
            return None

        # APEX composite
        apex_d  = apex_composite(sym, fort, hist, macro, fii_data)
        bayes_p = bayes_win_probability(fort, apex_d, macro, order_flow)
        fused   = fused_score(fort, apex_d, bayes_p)

        if fused < APEX_MIN_SCORE:
            return None

        # FIX-2: Alt-data scraping moved BELOW fused gate.
        # Playwright/ScraperAPI only fires for the ~3-5 symbols that clear
        # all math gates. Firing for all 300 symbols caused 8 concurrent
        # Chromium instances in the ThreadPoolExecutor → OOM kill on GHA
        # (7GB RAM). Playwright sync_api is also not thread-safe.
        alt_match = {"matched": False, "best_sim": 0.0,
                     "match_label": "", "catalyst_sub": False}
        has_catalyst = False
        if ALT_DATA_ENABLED and _OPENAI_OK:
            try:
                fil  = filings.get(sym, {})
                ins  = insider_map.get(sym, {})
                tenders = _scrape_cpp_tenders(sym)
                exports = _scrape_zauba_exports(sym)
                alt_text = _build_alt_data_text(sym, tenders, exports,
                                                fil.get("subject",""))
                if alt_text and len(alt_text) > 30:
                    alt_match = _semantic_catalyst_match(sym, alt_text, vector_store)
                    has_catalyst = (alt_match.get("matched") or
                                    ins.get("count", 0) > 0 or
                                    fil.get("score", 15) >= 20)
            except Exception as e:
                log.debug(f"Alt-data {sym}: {e}")

        # RS percentile for conviction rerank
        rs_pct = _compute_rs_pct(sym, hist, hist_cache, hist_lock)  # FIX-3

        # LLM story enrichment
        llm = llm_enrich_pick(sym, fort, apex_d, bayes_p, macro,
                               fii_data, insider_map, filings, alt_match)

        # Grade from fused
        if fused >= 80:      grade = "APEX"
        elif fused >= 70:    grade = "PRISTINE"
        elif fused >= 60:    grade = "GOOD"
        elif fused >= 48:    grade = "PROBE"
        else:                grade = "WATCHLIST"
        fort["grade"] = grade

        # Conviction re-rank with Option-C
        fort = apply_conviction_rerank(fort, rs_pct, has_catalyst, alt_match)
        grade = fort["grade"]

        # Final grade gate
        if grade == "WATCHLIST":
            return None

        # Meta-labeler veto (silent ML overlay — Sec 25)
        _ml_vetoed, _p_win = meta_labeler_veto(
            {"fort_pts": fort.get("fort_pts",0), "apex_comp": apex_d.get("apex_comp",0),
             "fused": fused, "bayes_pct": bayes_p, "rsi14": fort.get("rsi14",50),
             "adx14": fort.get("adx14",0), "mfi": fort.get("mfi",50),
             "atr14": fort.get("atr14",0), "atr_mult": fort.get("atr_mult",2.0),
             "whale_score": fort.get("whale_score",0),
             "delivery_pct": fort.get("delivery_pct",0),
             "vol_ratio": fort.get("vol_ratio",1.0), "rs_pct": rs_pct,
             "at_vpoc": fort.get("at_vpoc",False), "whale_flag": fort.get("whale_flag",False),
             "has_catalyst": has_catalyst, "symbol": sym},
            macro
        )
        if _ml_vetoed:
            return None

        result = {
            "symbol":       sym,
            "sector":       sector,
            "grade":        grade,
            "fort_pts":     fort.get("fort_pts", 0),
            "apex_comp":    apex_d.get("apex_comp", 0),
            "fused":        fused,
            "bayes_pct":    bayes_p,
            "close":        close,
            "stop_loss":    fort.get("stop_loss", 0),
            "buy_lo":       fort.get("buy_lo", 0),
            "buy_hi":       fort.get("buy_hi", 0),
            "r1":           fort.get("r1", 0),
            "r2":           fort.get("r2", 0),
            "r3":           fort.get("r3", 0),
            "shares":       fort.get("shares", 0),
            "atr14":        fort.get("atr14", 0),
            "atr_mult":     fort.get("atr_mult", ATR_MULT_CHOP),
            "rsi14":        fort.get("rsi14", 50),
            "adx14":        fort.get("adx14", 0),
            "mfi":          fort.get("mfi", 50),
            "whale_flag":   fort.get("whale_flag", False),
            "whale_score":  fort.get("whale_score", 0),
            "delivery_pct": fort.get("delivery_pct", 0),
            "vol_ratio":    fort.get("vol_ratio", 1.0),
            "vpoc":         fort.get("vpoc", 0),
            "at_vpoc":      fort.get("at_vpoc", False),
            "rs_pct":       rs_pct,
            "has_catalyst": has_catalyst,
            "alt_matched":  alt_match.get("matched", False),
            "alt_sim":      alt_match.get("best_sim", 0),
            "halal_tier":   halal.get("tier","ACCEPTABLE"),
            "halal_score":  halal.get("score", 60),
            "llm_why":      llm.get("llm_why",""),
            "llm_verdict":  llm.get("llm_verdict","QUALIFIED"),
            "llm_conf":     llm.get("llm_confidence", 0.60),
            "llm_catalyst": llm.get("llm_catalyst",""),
            "story":        fort.get("story",""),
            "macro_state":  macro.get("macro_state","CHOP"),
            "meta_p_win":   _p_win,      # meta-labeler win probability
        }

        # Cache for fast rerun
        _score_cache_put(sym, date_label, close, result, intel_hash)
        return result

    except Exception as e:
        log.debug(f"score_one_symbol {sym}: {e}")
        return None

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 18 — THREE-LANE SELECTION (FORTRESS / APEX / FUSED)
# Each lane picks its best halal-vetted pearl. Returns up to 3 picks.
# ══════════════════════════════════════════════════════════════════════════════

def select_lane_winners(results: List[dict], macro: dict) -> dict:
    """
    Three-lane architecture (preserved from v5.5).
    FORTRESS lane: highest fort_pts ≥ LANE_FORTRESS_MIN
    APEX lane:     highest apex_comp ≥ LANE_APEX_MIN
    FUSED lane:    highest fused ≥ LANE_FUSED_MIN
    Under CONVICTION_RERANK: gates rise to CONV_* values.
    Returns {"fortress": pick_or_None, "apex": ..., "fused": ...}
    """
    g_fort  = CONV_LANE_FORTRESS_MIN if CONVICTION_RERANK else LANE_FORTRESS_MIN
    g_apex  = CONV_LANE_APEX_MIN     if CONVICTION_RERANK else LANE_APEX_MIN
    g_fused = CONV_LANE_FUSED_MIN    if CONVICTION_RERANK else LANE_FUSED_MIN

    def _pick(key: str, gate: float) -> Optional[dict]:
        candidates = [r for r in results if r.get(key, 0) >= gate
                      and r.get("grade","") not in ("WATCHLIST",)]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r.get(key, 0))

    fortress_w = _pick("fort_pts", g_fort)
    apex_w     = _pick("apex_comp", g_apex)
    fused_w    = _pick("fused", g_fused)

    # Deduplicate: each symbol can only win one lane
    seen = set()
    winners = {}
    for lane, w in [("fortress", fortress_w), ("apex", apex_w), ("fused", fused_w)]:
        if w and w["symbol"] not in seen:
            winners[lane] = w
            seen.add(w["symbol"])
        else:
            winners[lane] = None

    log.info("THREE-LANE WINNERS: " + " | ".join(
        f"{k.upper()}:{v['symbol']}" if v else f"{k.upper()}:NO_PICK"
        for k, v in winners.items()
    ))
    return winners

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 19 — GOOGLE SHEETS OUTPUT
# Writes SCREENER tab (read by reply handler) + PERFORMANCE tab.
# ══════════════════════════════════════════════════════════════════════════════

_SCREENER_HEADER = [
    "Date","Symbol","Sector","Grade","Fused/100","Fort/200","APEX/100",
    "Bayes%","BuyLo","BuyHi","StopLoss","R1","R2","R3","Shares",
    "ATR14","ATR_Mult","RSI","ADX","MFI","Delivery%","VolRatio",
    "Whale","VPOC","RS_Pct","HasCatalyst","AltData","HalalTier",
    "LLM_Verdict","LLM_Why","LLM_Catalyst","Story","MacroState","Lane",
    "MetaP_Win","KellyMult"  # Sec 25/27
]

def _pick_to_row(p: dict, date_label: str, lane: str = "") -> list:
    return [
        date_label, p.get("symbol",""), p.get("sector",""),
        p.get("grade",""), round(p.get("fused",0),1),
        round(p.get("fort_pts",0),0), round(p.get("apex_comp",0),1),
        round(p.get("bayes_pct",0),1),
        round(p.get("buy_lo",0),2), round(p.get("buy_hi",0),2),
        round(p.get("stop_loss",0),2),
        round(p.get("r1",0),2), round(p.get("r2",0),2), round(p.get("r3",0),2),
        p.get("shares",0),
        round(p.get("atr14",0),2), round(p.get("atr_mult",2.0),2),
        round(p.get("rsi14",50),1), round(p.get("adx14",0),1),
        round(p.get("mfi",50),1),
        round(p.get("delivery_pct",0),1), round(p.get("vol_ratio",1),2),
        "✅" if p.get("whale_flag") else "", round(p.get("vpoc",0),2),
        round(p.get("rs_pct",50),1),
        "✅" if p.get("has_catalyst") else "",
        f"sim={p.get('alt_sim',0):.3f}" if p.get("alt_matched") else "",
        p.get("halal_tier","ACCEPTABLE"),
        p.get("llm_verdict",""), p.get("llm_why","")[:80],
        p.get("llm_catalyst","")[:60],
        p.get("story","")[:120], p.get("macro_state",""),
        lane.upper(),
        round(p.get("meta_p_win", 0.5), 3),
        round(p.get("kelly_mult", 1.0), 3),
    ]

def push_screener_to_sheets(winners: dict, date_label: str) -> bool:
    """Write the three-lane picks to SCREENER tab. Appends to existing rows."""
    picks = [(lane, w) for lane, w in winners.items() if w]
    if not picks:
        log.warning("No picks to push to SCREENER")
        return False
    # Read existing rows to append (not overwrite history)
    existing = _read_sheet("SCREENER")
    if not existing:
        rows = [_SCREENER_HEADER]
    else:
        rows = existing
        # Remove today's rows if rerun
        rows = [r for r in rows if not (len(r) > 0 and str(r[0]) == date_label)]
        if not rows:
            rows = [_SCREENER_HEADER]
    for lane, w in picks:
        rows.append(_pick_to_row(w, date_label, lane))
    return _push_sheet("SCREENER", rows)

def push_performance_to_sheets(date_label: str):
    """
    Read DB_DECISIONS (TAKEN picks) and DB_BACKUP (outcomes) and write
    a joined PERFORMANCE tab. Called by outcome engine.
    """
    decisions = _read_sheet("DB_DECISIONS")
    backup    = _read_sheet("DB_BACKUP")
    if not decisions or len(decisions) < 2:
        return
    dec_header = [h.lower() for h in decisions[0]]
    taken_rows = [
        dict(zip(dec_header, r)) for r in decisions[1:]
        if len(r) > 2 and r[dec_header.index("decision") if "decision" in dec_header else 2] == "TAKEN"
    ]
    if not taken_rows:
        return
    perf_header = ["Date","Symbol","Decision","EntryPrice","Shares",
                   "StopLoss","R1","ExitPrice","ExitDate","PnL_Pct","Status"]
    perf_rows   = [perf_header]

    # Build outcome lookup from DB_BACKUP
    outcome_map = {}
    if backup and len(backup) > 1:
        bk_header = [h.lower() for h in backup[0]]
        for r in backup[1:]:
            if not r:
                continue
            d = dict(zip(bk_header, r))
            key = (d.get("run_date",""), d.get("symbol","").upper())
            outcome_map[key] = d

    for row in taken_rows:
        sym  = row.get("symbol","").upper()
        rd   = row.get("run_date","")
        out  = outcome_map.get((rd, sym), {})
        perf_rows.append([
            rd, sym, "TAKEN",
            row.get("entry_price",""), row.get("shares_taken",""),
            out.get("stop_loss",""), out.get("r1",""),
            out.get("exit_price",""), out.get("exit_date",""),
            out.get("pnl_pct",""), out.get("status","open"),
        ])
    _push_sheet("PERFORMANCE", perf_rows)
    log.info(f"PERFORMANCE tab: {len(perf_rows)-1} rows written")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 20 — TELEGRAM OUTPUT (preserved from v5.5, Phase 5 execution REMOVED)
# Telegram = alerting only. No autonomous order execution.
# ══════════════════════════════════════════════════════════════════════════════

def _send_tg(text: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    for attempt in range(3):
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": text,
                      "parse_mode": "HTML"},
                timeout=15,
            )
            if resp.status_code == 200:
                return True
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
            log.debug(f"Telegram attempt {attempt+1}: {e}")
    return False

def _format_pick_card(p: dict, lane: str, idx: int,
                       macro: dict, fii_data: dict) -> str:
    """Format a single pick as a rich Telegram HTML card."""
    grade_emoji = {"APEX":"🏆","PRISTINE":"💎","GOOD":"✅","PROBE":"🔍"}.get(p.get("grade",""),"📋")
    whale_line  = f"\n🐳 <b>WHALE ACCUM</b> Del={p.get('delivery_pct',0):.0f}% Vol={p.get('vol_ratio',1):.1f}x" if p.get("whale_flag") else ""
    alt_line    = f"\n🔍 Alt-data match: {p.get('alt_sim',0):.3f} ✅" if p.get("alt_matched") else ""
    catalyst    = f"\n⚡ Catalyst: {p.get('llm_catalyst','')}" if p.get("llm_catalyst") else ""
    regime_mult = p.get("atr_mult", 2.0)
    stop_type   = f"ATR×{regime_mult} ({macro.get('macro_state','CHOP')})"
    return (
        f"{grade_emoji} <b>#{idx} {p['symbol']}</b> | {lane.upper()} lane\n"
        f"Grade: <b>{p.get('grade','?')}</b> | "
        f"Fused: <b>{p.get('fused',0):.0f}</b>/100 | "
        f"Bayes: {p.get('bayes_pct',0):.0f}%\n"
        f"Fort: {p.get('fort_pts',0):.0f}/200 | "
        f"APEX: {p.get('apex_comp',0):.0f}/100 | "
        f"RS: {p.get('rs_pct',50):.0f}pct\n"
        f"Entry: ₹{p.get('buy_lo',0):.0f}–{p.get('buy_hi',0):.0f} | "
        f"Close: ₹{p.get('close',0):.0f}\n"
        f"Stop: ₹{p.get('stop_loss',0):.0f} ({stop_type})\n"
        f"R1: ₹{p.get('r1',0):.0f} | R2: ₹{p.get('r2',0):.0f} | R3: ₹{p.get('r3',0):.0f}\n"
        f"Shares: {p.get('shares',0):,} (₹{ACCOUNT_EQUITY*ACCOUNT_RISK_PCT:,.0f} risk)\n"
        f"Halal: {p.get('halal_tier','?')} | Sector: {p.get('sector','?')}\n"
        f"{whale_line}{alt_line}{catalyst}\n"
        f"📊 {p.get('llm_why',p.get('story',''))[:100]}"
    )

def send_telegram_picks(winners: dict, macro: dict, fii_data: dict,
                         date_label: str,
                         options: dict = None,
                         kelly_stats: dict = None) -> bool:
    """Send all lane picks in one Telegram message block."""
    picks = [(lane, w) for lane, w in winners.items() if w]
    if not picks:
        msg = (
            f"📋 <b>FORTRESS v6.0 — {date_label}</b>\n"
            f"Regime: {macro.get('macro_state','?')} VIX={macro.get('vix_val',0):.1f}\n"
            f"No picks cleared the pearls gate today. 🚫"
        )
        _send_tg(msg)
        return False

    state   = macro.get("macro_state","CHOP")
    vix     = macro.get("vix_val", 0)
    fii_lbl = fii_data.get("label","MIXED")
    opt_line = ""
    if options and options.get("options_regime") != "NEUTRAL":
        ow = options.get("call_oi_wall",0)
        opt_line = f"\n⚡ Options: {options['options_regime']} | CallWall={ow:.0f} MaxPain={options.get('max_pain_strike',0):.0f}"
    kelly_line = ""
    if kelly_stats and kelly_stats.get("status") == "active":
        km = kelly_stats.get("multiplier",1.0)
        wr = kelly_stats.get("win_rate",0)
        rr = kelly_stats.get("avg_rr",0)
        kelly_line = f"\n📐 Kelly ×{km:.2f} | WR={wr:.0%} RR={rr:.2f} [{kelly_stats.get('trades',0)}T]"
    header  = (
        f"⚔️ <b>FORTRESS v6.0 — {date_label}</b>\n"
        f"Regime: <b>{state}</b> | VIX={vix:.1f} | FII={fii_lbl}\n"
        f"ATR mult={macro.get('atr_mult',2.0)}× | {len(picks)} pearl(s) today"
        f"{opt_line}{kelly_line}\n"
        f"{'━'*30}\n"
    )
    cards = []
    for i, (lane, w) in enumerate(picks, 1):
        cards.append(_format_pick_card(w, lane, i, macro, fii_data))
    footer = (
        f"\n{'━'*30}\n"
        f"Reply: <code>TAKEN SYM [@price]</code> | <code>/confirm #N</code>\n"
        f"<code>SKIP SYM</code> | <code>SKIP ALL</code> | <code>HELP</code>\n"
        f"ℹ️ Phase 5 execution disabled — manual via broker. No slippage."
    )
    full_msg = header + "\n\n".join(cards) + footer
    # Telegram 4096-char limit — split if needed
    if len(full_msg) > 4000:
        _send_tg(header)
        for lane, w in picks:
            _send_tg(_format_pick_card(w, lane, 1, macro, fii_data))
        _send_tg(footer)
    else:
        _send_tg(full_msg)
    return True

def send_telegram_massacre(macro: dict, date_label: str):
    _send_tg(
        f"🚨 <b>MASSACRE HALT — {date_label}</b>\n"
        f"NIFTY50 {macro.get('nifty_chg',0):+.2f}% | VIX={macro.get('vix_val',0):.1f}\n"
        f"Pipeline halted. No new positions. Capital preservation mode."
    )

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 21 — OUTCOME ENGINE
# Reads TAKEN decisions from Sheets DB_DECISIONS, resolves against today's prices,
# writes closed outcomes to DB_BACKUP. Stores alt-data vectors for wins ≥50%.
# ══════════════════════════════════════════════════════════════════════════════

def run_outcome_engine(date_label: str):
    """
    EOD outcome resolution:
    1. Read open positions from DB_BACKUP
    2. Fetch today's close from bhavcopy / yfinance
    3. Check if stop/R1/R2/R3 hit
    4. Write closed outcomes to DB_BACKUP
    5. Store alt-data vector for wins ≥50% (Phase 4 feedback loop)
    """
    log.info("=== Outcome Engine ===")
    # Read open positions
    rows = _read_sheet("DB_BACKUP")
    if not rows or len(rows) < 2:
        log.info("DB_BACKUP empty — no open positions to resolve")
        return

    header = [h.lower() for h in rows[0]]
    open_positions = [dict(zip(header, r)) for r in rows[1:]
                      if len(r) > 0 and str(r[header.index("status") if "status" in header else -1]).lower() == "open"]
    if not open_positions:
        log.info("No open positions in DB_BACKUP")
        return

    log.info(f"Resolving {len(open_positions)} open positions")

    # Fetch today's bhavcopy
    bhav, _ = load_bhavcopy()
    price_map = {}
    high_map  = {}  # FIX-3: needed for target resolution (high hits R1/R2/R3)
    low_map   = {}  # FIX-3: needed for stop resolution (low hits stop_loss)
    if not bhav.empty:
        price_map = dict(zip(bhav["symbol"].str.upper(), bhav["close"]))
        high_map  = dict(zip(bhav["symbol"].str.upper(), bhav["high"]))
        low_map   = dict(zip(bhav["symbol"].str.upper(), bhav["low"]))

    updated = []
    for pos in open_positions:
        sym        = str(pos.get("symbol","")).upper()
        entry      = float(pos.get("entry_price", 0) or 0)
        stop_loss  = float(pos.get("stop_loss", 0) or 0)
        r1         = float(pos.get("r1", 0) or 0)
        r2         = float(pos.get("r2", 0) or 0)
        r3         = float(pos.get("r3", 0) or 0)
        run_date   = str(pos.get("run_date",""))

        if entry <= 0:
            continue

        # Get today's price, high, low
        today_close = price_map.get(sym)
        today_high  = high_map.get(sym)
        today_low   = low_map.get(sym)
        if today_close is None:
            # Fallback to yfinance
            try:
                import yfinance as yf
                tk  = yf.Ticker(f"{sym}.NS")
                inf = tk.fast_info
                today_close = float(inf.last_price)     if hasattr(inf, "last_price")     else 0
                today_high  = float(inf.day_high)       if hasattr(inf, "day_high")        else today_close
                today_low   = float(inf.day_low)        if hasattr(inf, "day_low")         else today_close
            except Exception:
                pass
        if not today_close or today_close <= 0:
            updated.append(pos)
            continue
        today_high = today_high or today_close
        today_low  = today_low  or today_close

        # FIX-3: evaluate stops against daily LOW, targets against daily HIGH.
        # Using only close price ignores intraday wicks: a stock that crashes to
        # ₹85 (stop at ₹90) then recovers to close at ₹105 was stopped out in
        # reality — the broker filled the stop. Close-only resolution reports
        # "still open", producing fake win-rates while the account bleeds.
        status    = "open"
        exit_price = 0.0
        if today_low > 0 and today_low <= stop_loss:
            status     = "stopped"
            exit_price = stop_loss          # filled at stop price, not the low
        elif r3 > 0 and today_high >= r3:
            status     = "r3_hit"
            exit_price = r3
        elif r2 > 0 and today_high >= r2:
            status     = "r2_hit"
            exit_price = r2
        elif r1 > 0 and today_high >= r1:
            status     = "r1_hit"
            exit_price = r1

        if status != "open" and entry > 0:
            pnl_pct = round((exit_price - entry) / entry * 100, 2)
            pos["status"]     = status
            pos["exit_price"] = exit_price
            pos["exit_date"]  = date_label
            pos["pnl_pct"]    = pnl_pct
            log.info(f"Outcome: {sym} {status} entry={entry:.0f} exit={exit_price:.0f} "
                     f"pnl={pnl_pct:+.1f}%")
            # Sec 25: store meta-labeler training label
            try:
                outcome_label = 1 if status in ("r1_hit","r2_hit","r3_hit") else 0
                macro_snap = _load_cached_macro() or {"vix_val":18,"advance_ratio":0.5}
                store_meta_label(pos, macro_snap, outcome_label, run_date)
            except Exception as _ml_e:
                log.debug(f"store_meta_label non-fatal: {_ml_e}")
            # Phase 4 feedback: store alt-data vector for big wins
            if pnl_pct >= 50 and ALT_DATA_ENABLED and _OPENAI_OK:
                try:
                    tenders = _scrape_cpp_tenders(sym)
                    exports = _scrape_zauba_exports(sym)
                    alt_text = _build_alt_data_text(sym, tenders, exports,
                                                     pos.get("story",""))
                    if alt_text:
                        store_alt_vector(sym, "outcome_win", alt_text, "WIN_50PCT")
                except Exception as e:
                    log.debug(f"Alt-data store {sym}: {e}")
        updated.append(pos)

    # Rewrite DB_BACKUP with updated statuses
    if not updated:
        return
    all_keys = list(header) if header else list(updated[0].keys())
    out_rows  = [all_keys]
    for p in updated:
        out_rows.append([str(p.get(k,"")) for k in all_keys])
    _push_sheet("DB_BACKUP", out_rows)
    log.info(f"DB_BACKUP updated: {len(updated)} positions")

def auto_log_skipped_picks(date_label: str):
    """
    EOD: mark any picks not replied to as SKIPPED (no_response).
    Only adds SKIPPED rows for symbols missing from DB_DECISIONS.
    """
    screener = _read_sheet("SCREENER")
    decisions_rows = _read_sheet("DB_DECISIONS")
    if not screener or len(screener) < 2:
        return

    sc_header   = [h.lower() for h in screener[0]]
    today_picks = [
        row[sc_header.index("symbol")].upper()
        for row in screener[1:]
        if len(row) > 0 and str(row[sc_header.index("date") if "date" in sc_header else 0]) == date_label
    ]
    if not today_picks:
        return

    dec_syms = set()
    if decisions_rows and len(decisions_rows) > 1:
        dec_header = [h.lower() for h in decisions_rows[0]]
        dec_date_col   = dec_header.index("run_date") if "run_date" in dec_header else 0
        dec_sym_col    = dec_header.index("symbol") if "symbol" in dec_header else 1
        for row in decisions_rows[1:]:
            if len(row) > max(dec_date_col, dec_sym_col):
                if str(row[dec_date_col]) == date_label:
                    dec_syms.add(str(row[dec_sym_col]).upper())

    for sym in today_picks:
        if sym not in dec_syms:
            _append_sheet_row("DB_DECISIONS", [
                date_label, sym, "SKIPPED", "", "0",
                "no_response", "", "",
                datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            ])
            log.info(f"Auto-SKIPPED {sym} (no reply)")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 22 — WEEKLY REVIEW (OpenAI gpt-4o-mini narrative)
# ══════════════════════════════════════════════════════════════════════════════

def run_weekly_review(force: bool = False):
    """
    Monday weekly review via OpenAI.
    Reads PERFORMANCE tab, computes stats, generates narrative, sends to Telegram.
    """
    if not force and datetime.today().weekday() != 0:
        log.info("Weekly review: not Monday — skip (use FORCE_WEEKLY=true to override)")
        return

    log.info("=== Weekly Review ===")
    perf_rows = _read_sheet("PERFORMANCE")
    if not perf_rows or len(perf_rows) < 2:
        _send_tg("📈 <b>Weekly Review</b>\nNo closed trades yet — build the track record! 💪")
        return

    header = [h.lower() for h in perf_rows[0]]
    trades = [dict(zip(header, r)) for r in perf_rows[1:] if len(r) > 3]
    closed = [t for t in trades if t.get("status","open") != "open"]
    wins   = [t for t in closed if "hit" in t.get("status","")]
    losses = [t for t in closed if t.get("status","") == "stopped"]

    total  = len(closed)
    wr     = len(wins) / total * 100 if total > 0 else 0
    avg_pnl = (sum(float(t.get("pnl_pct",0) or 0) for t in closed) /
               total) if total > 0 else 0

    summary = (
        f"Closed: {total} | Wins: {len(wins)} | Losses: {len(losses)}\n"
        f"Win rate: {wr:.0f}% | Avg P&L: {avg_pnl:+.1f}%\n"
        f"Recent: {[t.get('symbol','') for t in closed[-5:]]}"
    )

    if _OPENAI_OK and total > 0:
        prompt = f"""NSE quant screener weekly performance review.
{summary}
Top 3 wins: {[(t.get('symbol',''), t.get('pnl_pct','0')) for t in wins[:3]]}
Top 3 losses: {[(t.get('symbol',''), t.get('pnl_pct','0')) for t in losses[:3]]}

Write a concise 3-paragraph quant review: (1) performance highlights,
(2) regime context and what worked, (3) one concrete adjustment for next week.
Max 200 words. Professional, data-driven tone."""
        narrative = _call_openai(prompt, max_tokens=400, cache_ttl_days=0)
    else:
        narrative = "Run more trades to generate AI narrative."

    msg = (
        f"📈 <b>FORTRESS v6.0 — Weekly Review</b>\n"
        f"{'━'*30}\n"
        f"Trades: {total} | WR: {wr:.0f}% | Avg: {avg_pnl:+.1f}%\n"
        f"{'━'*30}\n"
        f"{narrative or summary}"
    )
    _send_tg(msg)
    log.info(f"Weekly review sent: {total} trades, WR={wr:.0f}%")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 25 — META-LABELER (XGBoost/RandomForest ML Overlay)
# Watches the rules engine and vetoes false positives.
# Features: all 15 indicator values + regime + grade.
# Label: 1 = Win (r1/r2/r3 hit), 0 = Loss (stopped/expired).
# Cold-start: needs ≥ 30 closed trades. Returns None when untrained.
# Sheets tab: META_MODEL_DATA (feature matrix, accumulates across runners).
# ══════════════════════════════════════════════════════════════════════════════

_META_MODEL       = None          # singleton — trained once per run
_META_MODEL_LOCK  = threading.Lock()
# FIX-2: Curse of Dimensionality — 18 features needs ~180-250 samples min.
# At 30 samples the RF memorises noise. Two-phase feature set:
#   CORE (4 features, active from trade 50) — statistically valid at low N.
#   FULL (12 features, active from trade 150) — requires year of data.
# n_estimators reduced to 100 (200 overfits at low N, slower too).
# max_depth reduced to 4 (tighter regularisation at early stages).
META_MIN_SAMPLES  = int(os.getenv("META_MIN_SAMPLES", "50"))    # was 30 — FIX-2
META_FULL_SAMPLES = int(os.getenv("META_FULL_SAMPLES", "150"))  # unlock full features
META_VETO_THRESH  = float(os.getenv("META_VETO_THRESH", "0.35"))

# CORE: 4 highest-signal features — valid at N≥50 (10-15 samples/feature rule)
_META_FEATURE_COLS_CORE = ["fused","vix_val","whale_score","advance_ratio"]
# FULL: 12 features — valid at N≥150
_META_FEATURE_COLS_FULL = [
    "fused","vix_val","whale_score","advance_ratio",
    "fort_pts","apex_comp","bayes_pct","rsi14",
    "adx14","rs_pct","delivery_pct","atr_mult",
]

def _get_meta_feature_cols(n_samples: int) -> list:
    """Return active feature list based on training corpus size."""
    if n_samples >= META_FULL_SAMPLES:
        return _META_FEATURE_COLS_FULL
    return _META_FEATURE_COLS_CORE

# Legacy alias for store_meta_label (always stores full feature set for future use)
_META_FEATURE_COLS = _META_FEATURE_COLS_FULL

def _pick_to_features(pick: dict, macro: dict) -> dict:
    """Extract feature dict from a scored pick + macro context."""
    return {
        "fort_pts":      float(pick.get("fort_pts", 0)),
        "apex_comp":     float(pick.get("apex_comp", 0)),
        "fused":         float(pick.get("fused", 0)),
        "bayes_pct":     float(pick.get("bayes_pct", 50)),
        "rsi14":         float(pick.get("rsi14", 50)),
        "adx14":         float(pick.get("adx14", 0)),
        "mfi":           float(pick.get("mfi", 50)),
        "atr14":         float(pick.get("atr14", 0)),
        "atr_mult":      float(pick.get("atr_mult", 2.0)),
        "whale_score":   float(pick.get("whale_score", 0)),
        "delivery_pct":  float(pick.get("delivery_pct", 0)),
        "vol_ratio":     float(pick.get("vol_ratio", 1.0)),
        "rs_pct":        float(pick.get("rs_pct", 50)),
        "vix_val":       float(macro.get("vix_val", 18)),
        "advance_ratio": float(macro.get("advance_ratio", 0.5)),
        "at_vpoc":       int(bool(pick.get("at_vpoc", False))),
        "whale_flag":    int(bool(pick.get("whale_flag", False))),
        "has_catalyst":  int(bool(pick.get("has_catalyst", False))),
    }

def _load_meta_training_data() -> Tuple[Optional[Any], Optional[Any]]:
    """
    Read META_MODEL_DATA from Sheets.
    Returns (X, y) numpy arrays or (None, None) if insufficient data.
    Each row: feature cols + "label" (1=win, 0=loss).
    """
    rows = _read_sheet("META_MODEL_DATA")
    if not rows or len(rows) < META_MIN_SAMPLES + 1:
        log.info(f"Meta-labeler: {max(0,len(rows)-1)} samples < {META_MIN_SAMPLES} min — cold start")
        return None, None
    header = [h.lower() for h in rows[0]]
    records = []
    for row in rows[1:]:
        if not row or len(row) < len(header):
            continue
        d = dict(zip(header, row))
        if d.get("label","") not in ("1","0","1.0","0.0"):
            continue
        try:
            feat = [float(d.get(c, 0) or 0) for c in _META_FEATURE_COLS]
            label = int(float(d["label"]))
            records.append((feat, label))
        except Exception:
            continue
    if len(records) < META_MIN_SAMPLES:
        log.info(f"Meta-labeler: {len(records)} labelled samples < {META_MIN_SAMPLES} — cold start")
        return None, None
    X = np.array([r[0] for r in records], dtype=np.float32)
    y = np.array([r[1] for r in records], dtype=np.int32)
    log.info(f"Meta-labeler training data: {len(records)} samples "
             f"({int(y.sum())} wins / {int((1-y).sum())} losses)")
    return X, y

def _train_meta_model():
    """Train RandomForest on historical outcomes. Feature set scales with corpus size.
    FIX-2: hyperparams tightened to prevent overfitting at low sample counts.
    """
    X, y = _load_meta_training_data()
    if X is None:
        return None
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import cross_val_score
        n = len(y)
        # FIX-2: regularise proportionally to sample count
        n_est  = 100 if n < META_FULL_SAMPLES else 200   # 200 overfits at low N
        depth  = 4   if n < META_FULL_SAMPLES else 6     # shallower = less overfit
        min_leaf = max(5, n // 20)                        # at least 5% of data per leaf
        clf = RandomForestClassifier(
            n_estimators=n_est, max_depth=depth,
            min_samples_leaf=min_leaf,
            class_weight="balanced", random_state=42, n_jobs=-1,
        )
        # Use only the phase-appropriate feature set
        active_cols = _get_meta_feature_cols(n)
        col_idx = [_META_FEATURE_COLS.index(c) for c in active_cols
                   if c in _META_FEATURE_COLS]
        X_active = X[:, col_idx]
        log.info(f"Meta-labeler: {n} samples | {len(active_cols)} features | "
                 f"depth={depth} n_est={n_est} min_leaf={min_leaf}")
        clf.fit(X_active, y)
        clf._active_cols = active_cols  # store for predict path
        # Quick CV estimate
        try:
            cv_scores = cross_val_score(clf, X, y, cv=min(5, len(y)//6), scoring="roc_auc")
            log.info(f"Meta-labeler trained: ROC-AUC={cv_scores.mean():.3f}±{cv_scores.std():.3f} "
                     f"on {len(y)} samples")
        except Exception:
            log.info(f"Meta-labeler trained on {len(y)} samples")
        return clf
    except ImportError:
        log.warning("sklearn not installed — meta-labeler disabled. pip install scikit-learn")
        return None
    except Exception as e:
        log.warning(f"Meta-labeler training failed (non-fatal): {e}")
        return None

def get_meta_model():
    """Singleton — train once per run, reuse across all picks."""
    global _META_MODEL
    if _META_MODEL is not None:
        return _META_MODEL
    with _META_MODEL_LOCK:
        if _META_MODEL is None:
            _META_MODEL = _train_meta_model()
    return _META_MODEL

def meta_labeler_veto(pick: dict, macro: dict) -> Tuple[bool, float]:
    """
    Run the meta-labeler on a pick.
    Returns (vetoed: bool, p_win: float).
    vetoed=True when P(win) < META_VETO_THRESH.
    vetoed=False (pass-through) when model untrained.
    """
    model = get_meta_model()
    if model is None:
        return False, 0.5  # cold start — pass everything through
    try:
        feat = _pick_to_features(pick, macro)
        # FIX-2: use only the columns the model was trained on
        active_cols = getattr(model, "_active_cols", _META_FEATURE_COLS_CORE)
        X    = np.array([[feat.get(c, 0.0) for c in active_cols]], dtype=np.float32)
        p_win = float(model.predict_proba(X)[0][1])
        vetoed = p_win < META_VETO_THRESH
        if vetoed:
            log.info(f"  🤖 META-LABELER VETO {pick.get('symbol')}: "
                     f"P(win)={p_win:.2f} < {META_VETO_THRESH:.2f}")
        else:
            log.info(f"  🤖 Meta-labeler PASS {pick.get('symbol')}: P(win)={p_win:.2f}")
        return vetoed, p_win
    except Exception as e:
        log.debug(f"meta_labeler_veto: {e}")
        return False, 0.5

def store_meta_label(pick: dict, macro: dict, outcome_label: int, run_date: str):
    """
    Append one labelled row to META_MODEL_DATA Sheets tab.
    Called by outcome engine when a trade closes (outcome_label: 1=win, 0=loss).
    Accumulates the training corpus across all runs.
    """
    feat = _pick_to_features(pick, macro)
    ws   = _get_ws("META_MODEL_DATA")
    if ws is None:
        return
    try:
        existing = ws.get_all_values()
        if not existing:
            header = ["run_date","symbol"] + _META_FEATURE_COLS + ["label"]
            ws.append_row(header)
        row = ([run_date, pick.get("symbol","")] +
               [str(feat[c]) for c in _META_FEATURE_COLS] +
               [str(outcome_label)])
        ws.append_row(row, value_input_option="USER_ENTERED")
        log.debug(f"Meta-labeler: stored label={outcome_label} for {pick.get('symbol')}")
    except Exception as e:
        log.debug(f"store_meta_label: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 26 — MAX PAIN / OPTIONS GRAVITY ENGINE
# NSE option chain → max pain strike → OI wall detection.
# Overlays on regime: if TREND but price at Call OI wall → pause breakouts.
# Zero cost — NSE option chain API is public.
# ══════════════════════════════════════════════════════════════════════════════

MAX_PAIN_CALL_OI_BLOCK_PCT = float(os.getenv("MAX_PAIN_CALL_OI_BLOCK_PCT", "0.005"))  # within 0.5% of max call OI strike
MAX_PAIN_ENABLED           = os.getenv("MAX_PAIN_ENABLED", "true").lower() in ("1","true","yes")

def fetch_options_gravity(index: str = "NIFTY") -> dict:
    """
    Fetch NSE option chain for NIFTY or BANKNIFTY.
    Returns:
      max_pain_strike  — price where option sellers lose least
      call_oi_wall     — strike with highest call OI (resistance)
      put_oi_wall      — strike with highest put OI (support)
      spot             — current index spot price
      breakout_blocked — True if spot within 0.5% of call OI wall
      options_regime   — "BLOCKED", "SUPPORTED", "NEUTRAL"
    """
    FALLBACK = {
        "max_pain_strike": 0, "call_oi_wall": 0, "put_oi_wall": 0,
        "spot": 0, "breakout_blocked": False, "options_regime": "NEUTRAL",
        "source": "FALLBACK",
    }
    if not MAX_PAIN_ENABLED:
        return FALLBACK
    try:
        sess = requests.Session()
        sess.get("https://www.nseindia.com", headers=_NSE_HEADERS, timeout=8)
        symbol = "NIFTY" if index.upper() == "NIFTY" else "BANKNIFTY"
        resp = sess.get(
            f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}",
            headers={**_NSE_HEADERS, "X-Requested-With": "XMLHttpRequest"},
            timeout=15,
        )
        if resp.status_code != 200:
            log.debug(f"Options chain HTTP {resp.status_code}")
            return FALLBACK
        data    = resp.json()
        records = data.get("records", {})
        spot    = float(records.get("underlyingValue", 0))
        chain   = records.get("data", [])
        if not chain or spot <= 0:
            return FALLBACK

        # Aggregate OI by strike
        call_oi: Dict[float, float] = {}
        put_oi:  Dict[float, float] = {}
        for row in chain:
            strike = float(row.get("strikePrice", 0))
            if strike <= 0:
                continue
            ce = row.get("CE", {})
            pe = row.get("PE", {})
            call_oi[strike] = call_oi.get(strike, 0) + float(ce.get("openInterest", 0))
            put_oi[strike]  = put_oi.get(strike, 0)  + float(pe.get("openInterest", 0))

        if not call_oi:
            return FALLBACK

        # Max Pain: strike minimising total value of all expiring options
        strikes = sorted(set(call_oi) | set(put_oi))
        pain_values = {}
        for s in strikes:
            call_pain = sum(max(0, s - k) * v for k, v in call_oi.items())
            put_pain  = sum(max(0, k - s) * v for k, v in put_oi.items())
            pain_values[s] = call_pain + put_pain
        max_pain_strike = float(min(pain_values, key=pain_values.get))

        # FIX-1: filter strikes relative to spot before finding walls.
        # Global max OI is almost always a deep OTM lottery-ticket strike
        # (e.g. 25000 CE when spot=22000) — 3000pts away, breakout_blocked
        # never fires. True resistance = nearest overhead Call OI concentration.
        valid_calls = {k: v for k, v in call_oi.items() if k >= spot}   # overhead only
        valid_puts  = {k: v for k, v in put_oi.items()  if k <= spot}   # below only
        call_oi_wall = float(max(valid_calls, key=valid_calls.get)) if valid_calls else 0
        put_oi_wall  = float(max(valid_puts,  key=valid_puts.get))  if valid_puts  else 0

        # Breakout blocked: spot within MAX_PAIN_CALL_OI_BLOCK_PCT of call wall
        near_call_wall = spot > 0 and abs(spot - call_oi_wall) / spot <= MAX_PAIN_CALL_OI_BLOCK_PCT
        near_put_wall  = spot > 0 and abs(spot - put_oi_wall)  / spot <= 0.005

        if near_call_wall:
            options_regime = "BLOCKED"   # strong call OI above = ceiling, pause breakouts
        elif near_put_wall:
            options_regime = "SUPPORTED"  # strong put OI below = floor, confirms longs
        else:
            options_regime = "NEUTRAL"

        result = {
            "max_pain_strike":  max_pain_strike,
            "call_oi_wall":     call_oi_wall,
            "put_oi_wall":      put_oi_wall,
            "spot":             spot,
            "breakout_blocked": near_call_wall,
            "options_regime":   options_regime,
            "source":           f"NSE_{symbol}",
        }
        log.info(f"Options gravity [{symbol}]: spot={spot:.0f} "
                 f"MaxPain={max_pain_strike:.0f} "
                 f"CallWall={call_oi_wall:.0f} PutWall={put_oi_wall:.0f} "
                 f"→ {options_regime}")
        return result
    except Exception as e:
        log.warning(f"fetch_options_gravity: {e} — FALLBACK")
        return FALLBACK

def apply_options_gravity_gate(winners: dict, options: dict, macro: dict) -> dict:
    """
    Options gravity overlay on three-lane winners.
    If TREND regime AND options_regime=BLOCKED → suppress APEX/FUSED breakout lanes.
    FORTRESS lane (mean-reversion) unaffected by call walls.
    Returns filtered winners dict with explanation in story fields.
    """
    if not options or options.get("options_regime") != "BLOCKED":
        return winners
    if macro.get("macro_state") not in ("TREND", "CHOP"):
        return winners  # already BUNKER/PANIC — no extra gate needed
    call_wall = options.get("call_oi_wall", 0)
    spot      = options.get("spot", 0)
    filtered  = dict(winners)
    for lane in ("apex", "fused"):
        w = filtered.get(lane)
        if w:
            filtered[lane] = None
            log.info(f"OPTIONS GATE: {lane.upper()} lane {w['symbol']} suppressed — "
                     f"spot {spot:.0f} at Call OI wall {call_wall:.0f} "
                     f"(TREND breakout into ceiling = low edge)")
    # FORTRESS lane preserved — mean-reversion can still work near resistance
    return filtered

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 27 — KELLY CRITERION DYNAMIC SIZING
# Rolling Kelly f* over last N closed trades.
# Kelly fraction adjusts atr_position_size multiplier:
#   hot streak  → size up (Kelly > 1.0 → fractional Kelly cap at 0.5 of Kelly)
#   cold streak → choke down (Kelly < 0 → minimum size floor)
# Uses half-Kelly for safety (Kelly overcalculates in live markets).
# ══════════════════════════════════════════════════════════════════════════════

KELLY_LOOKBACK  = int(os.getenv("KELLY_LOOKBACK", "20"))   # rolling window of closed trades
KELLY_FRACTION  = float(os.getenv("KELLY_FRACTION", "0.5")) # half-Kelly
KELLY_MIN_MULT  = float(os.getenv("KELLY_MIN_MULT", "0.25")) # floor: never below 25% of base size
KELLY_MAX_MULT  = float(os.getenv("KELLY_MAX_MULT", "2.0"))  # cap: never more than 2× base size
KELLY_MIN_TRADES = int(os.getenv("KELLY_MIN_TRADES", "10")) # need at least this many to activate

def compute_kelly_multiplier() -> Tuple[float, dict]:
    """
    Compute Kelly multiplier from last KELLY_LOOKBACK closed trades in PERFORMANCE tab.

    Kelly formula: f* = p − (q / b)
      p = win probability  (wins / total)
      q = loss probability (1 − p)
      b = average win / average loss (risk-reward ratio)

    Returns (multiplier, stats_dict).
    multiplier = 1.0 when insufficient data (neutral — no change to sizing).
    """
    NEUTRAL = (1.0, {"kelly_f": 1.0, "win_rate": 0.5, "avg_rr": 1.5,
                     "trades": 0, "status": "cold_start"})
    try:
        rows = _read_sheet("PERFORMANCE")
        if not rows or len(rows) < 2:
            return NEUTRAL
        header = [h.lower() for h in rows[0]]
        closed = []
        for row in rows[1:]:
            if len(row) < len(header):
                continue
            d = dict(zip(header, row))
            if d.get("status","") in ("stopped","r1_hit","r2_hit","r3_hit"):
                try:
                    closed.append({
                        "pnl_pct": float(d.get("pnl_pct", 0) or 0),
                        "status":  d.get("status",""),
                    })
                except Exception:
                    pass

        # Use last KELLY_LOOKBACK trades
        recent = closed[-KELLY_LOOKBACK:] if len(closed) > KELLY_LOOKBACK else closed
        n = len(recent)
        if n < KELLY_MIN_TRADES:
            log.info(f"Kelly: {n}/{KELLY_MIN_TRADES} min trades — neutral sizing")
            return NEUTRAL

        wins   = [t for t in recent if t["status"] in ("r1_hit","r2_hit","r3_hit")]
        losses = [t for t in recent if t["status"] == "stopped"]
        p = len(wins) / n
        q = 1.0 - p

        avg_win  = float(np.mean([t["pnl_pct"] for t in wins]))   if wins   else 1.5
        avg_loss = abs(float(np.mean([t["pnl_pct"] for t in losses]))) if losses else 1.0
        b = avg_win / avg_loss if avg_loss > 0 else avg_win

        # Kelly fraction
        kelly_f = p - (q / b) if b > 0 else 0.0
        # Half-Kelly for safety (full Kelly is too aggressive in live markets)
        half_kelly = kelly_f * KELLY_FRACTION
        # FIX-3: correct Kelly multiplier formula.
        # Old: 1.0 + half_kelly = only a tiny nudge around base risk.
        # E.g. base_risk=1.5%, kelly_f=0.10 → half=0.05 → mult=1.05 → risk=1.57%.
        # Correct: multiplier = half_kelly / base_risk, so the trade IS sized to
        # the Kelly optimum fraction of equity.
        # E.g. base_risk=1.5%, half_kelly=0.045 → mult=3.0 → risk=4.5% of equity.
        # Kelly ≤ 0 (losing streak) → multiplier floors at KELLY_MIN_MULT.
        base_risk = max(ACCOUNT_RISK_PCT, 1e-6)  # avoid div/0
        multiplier = float(np.clip(half_kelly / base_risk, KELLY_MIN_MULT, KELLY_MAX_MULT))

        stats = {
            "kelly_f":    round(kelly_f, 4),
            "half_kelly": round(half_kelly, 4),
            "multiplier": round(multiplier, 3),
            "win_rate":   round(p, 3),
            "avg_win":    round(avg_win, 2),
            "avg_loss":   round(avg_loss, 2),
            "avg_rr":     round(b, 2),
            "trades":     n,
            "status":     "active",
        }
        log.info(f"Kelly [{n} trades]: WR={p:.0%} RR={b:.2f} "
                 f"f*={kelly_f:.3f} → ×{multiplier:.2f} sizing")
        return multiplier, stats
    except Exception as e:
        log.warning(f"compute_kelly_multiplier: {e} — neutral")
        return NEUTRAL

def kelly_adjusted_size(base_shares: int, kelly_mult: float) -> int:
    """Apply Kelly multiplier to base ATR-sized shares. Rounds to whole shares."""
    return max(1, int(base_shares * kelly_mult))

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 23 — MAIN RUN PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

def run():
    """
    v6.0 EOD pipeline:
    1. Init DB + Sheets
    2. Phase 2: Macro regime → MASSACRE halt or continue
    3. Bhavcopy → liquidity filter
    4. Intelligence: FII/DII, insider, filings (async)
    5. Phase 4: Alt-data vector store load
    6. Phase 3: EOD order flow compute per candidate
    7. Parallel scoring: Fortress + APEX + Bayes + LLM enrichment
    8. Three-lane winner selection (FORTRESS / APEX / FUSED)
    9. Conviction re-rank (Option-C catalyst fallback)
    10. Outputs: Sheets SCREENER + Telegram (alerting only — no autonomous execution)
    11. Outcome engine: resolve yesterday's picks
    12. Auto-log skipped picks EOD
    """
    _init_db()
    _score_cache_purge()
    _, date_label = _get_last_trading_day()

    log.info("=" * 70)
    log.info(f"⚔️  {VERSION} | {date_label} | Bismillah")
    log.info(f"   OpenAI: {'✅' if _OPENAI_OK else '❌'} | "
             f"Sheets: {'✅' if _gs_ok() else '❌'} | "
             f"Telegram: {'✅' if TELEGRAM_TOKEN else '❌'}")
    log.info("=" * 70)

    # 1. Phase 2: VIX + NIFTY (breadth computed after bhavcopy — see below)
    # Partial macro fetch first: MASSACRE/PANIC halt before bhavcopy load (saves time)
    _early_macro = fetch_macro_regime(bhavcopy=None)
    if _early_macro["macro_state"] == "MASSACRE":
        log.error("🚨 MASSACRE — pipeline halted")
        send_telegram_massacre(_early_macro, date_label)
        return []
    if _early_macro["macro_state"] == "PANIC":
        _send_tg(f"⚠️ <b>PANIC REGIME</b> VIX={_early_macro['vix_val']:.1f}\n"
                 f"No new positions. Existing positions on tight trailing stops.")
        return []

    # 2. Bhavcopy
    bhavcopy, data_source = load_bhavcopy()
    if bhavcopy.empty:
        log.error("❌ Bhavcopy failed — abort")
        _send_tg(f"❌ Bhavcopy fetch failed {date_label} — no run")
        return []
    log.info(f"Bhavcopy: {len(bhavcopy)} rows | source={data_source}")

    # FIX-4: Recompute regime with TRUE internal breadth from bhavcopy A/D ratio.
    # _early_macro used CNX500 fallback (bhavcopy=None). Now we have the full
    # universe — recompute so TREND/CHOP/BUNKER reflects actual stock internals.
    macro = fetch_macro_regime(bhavcopy=bhavcopy)
    log.info(f"Final regime (with true breadth): {macro['macro_state']} "
             f"A/D={macro.get('advance_ratio',0.5):.0%}")

    # 3. Liquidity filter (no halal pre-filter — engines run on all EQ)
    cands = bhavcopy[
        (bhavcopy["turnover_lakhs"] >= MIN_TURNOVER_LAKHS) &
        (bhavcopy["close"] >= MIN_PRICE) &
        (bhavcopy["close"] <= MAX_PRICE)
    ].copy()
    if len(cands) > MAX_CANDIDATES:
        cands = cands.nlargest(MAX_CANDIDATES, "turnover_lakhs")
    log.info(f"After liquidity filter: {len(cands)} candidates")

    # 4. Intelligence (concurrent)
    log.info("Fetching intelligence data...")
    fii_data, insider_map, filings = {}, {}, {}
    try:
        import asyncio as _aio

        async def _fetch_all():
            fd, ins, fil = await _aio.gather(
                _aio.to_thread(fetch_fii_dii),
                _aio.to_thread(fetch_insider_trades),
                _aio.to_thread(fetch_filings),
            )
            return fd, ins, fil

        try:
            loop = _aio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None:
            fii_data, insider_map, filings = _aio.run(_fetch_all())
        else:
            _res: list = []
            def _run_loop():
                nl = _aio.new_event_loop()
                _aio.set_event_loop(nl)
                try:
                    _res.append(nl.run_until_complete(_fetch_all()))
                finally:
                    nl.close()
            t = threading.Thread(target=_run_loop, daemon=True)
            t.start(); t.join(timeout=60)
            if _res:
                fii_data, insider_map, filings = _res[0]
    except Exception as e:
        log.warning(f"Intelligence fetch error (non-fatal): {e}")
        fii_data = {"label":"MIXED","fii_net":0,"dii_net":0,"score":15}

    log.info(f"FII: {fii_data.get('label','?')} | "
             f"Insider: {len(insider_map)} | Filings: {len(filings)}")

    # 5. Phase 4: Load alt-data vector store from Sheets
    vector_store = []
    if ALT_DATA_ENABLED and _OPENAI_OK:
        try:
            vector_store = _load_vector_store()
            log.info(f"Alt-data vector store: {len(vector_store)} vectors loaded")
        except Exception as e:
            log.debug(f"Vector store load: {e}")

    # 6. Preload histories in background
    hist_cache: Dict[str, pd.DataFrame] = {}
    hist_lock   = threading.Lock()

    def _bg_preload():
        import yfinance as yf
        syms  = cands["symbol"].tolist()
        end   = datetime.today()
        start = end - timedelta(days=350)
        for i in range(0, len(syms), 50):
            chunk   = syms[i:i+50]
            tickers = " ".join(f"{s}.NS" for s in chunk)
            try:
                raw = yf.download(tickers, start=start, end=end,
                                  progress=False, auto_adjust=True,  # FIX-1
                                  group_by="ticker", timeout=30)
                if raw.empty:
                    continue
                for sym in chunk:
                    tk = f"{sym}.NS"
                    try:
                        if hasattr(raw.columns, "levels"):
                            sub = (raw.xs(tk, axis=1, level=0)
                                   if tk in raw.columns.get_level_values(0)
                                   else None)
                        else:
                            sub = raw if len(chunk) == 1 else None
                        if sub is None or sub.empty:
                            continue
                        sub = sub.reset_index()
                        sub.columns = [c[0].lower() if isinstance(c,tuple) else c.lower()
                                        for c in sub.columns]
                        # FIX-1: auto_adjust=True — Close already adjusted;
                        # 'Adj Close' column absent. Rename guard removed.
                        dt_c = next((c for c in sub.columns if c != "date" and
                                     pd.api.types.is_datetime64_any_dtype(sub[c])), None)
                        if dt_c:
                            sub = sub.rename(columns={dt_c: "date"})
                        sub["date"] = pd.to_datetime(sub["date"])
                        df = sub[["date","open","high","low","close","volume"]].dropna()
                        if len(df) >= 20:
                            with hist_lock:
                                hist_cache[sym.upper()] = df.tail(300).reset_index(drop=True)
                    except Exception:
                        continue
            except Exception as e:
                log.debug(f"BG preload chunk {i}: {e}")

    preload_t = threading.Thread(target=_bg_preload, daemon=True)
    preload_t.start()
    log.info(f"Background history preload started for {len(cands)} symbols")

    # 7. Parallel scoring
    fast_rerun = os.getenv("FAST_RERUN","false").lower() in ("1","true","yes")
    n_workers  = min(8, max(2, len(cands) // 10))
    results    = []
    results_lock = threading.Lock()

    scoring_args = [
        (row["symbol"], row.to_dict(), hist_cache,
         fii_data, insider_map, filings,
         macro, date_label, vector_store, fast_rerun,
         hist_lock)  # FIX-3: pass lock for safe RS pct computation
        for _, row in cands.iterrows()
    ]
    log.info(f"Scoring {len(cands)} candidates with {n_workers} workers...")

    completed = 0
    with ThreadPoolExecutor(max_workers=n_workers, thread_name_prefix="v6_score") as executor:
        from concurrent.futures import as_completed
        future_map = {executor.submit(score_one_symbol, args): args[0]
                      for args in scoring_args}
        for future in as_completed(future_map):
            sym = future_map[future]
            completed += 1
            if completed % 50 == 0:
                log.info(f"Progress: {completed}/{len(scoring_args)} | picks: {len(results)}")
            try:
                r = future.result(timeout=60)
                if r:
                    with results_lock:
                        results.append(r)
                    log.info(f"  ✅ {sym:12s} | fused={r['fused']}/100 | "
                             f"{r['grade'][:8]} | {r['story'][:50]}")
            except Exception as e:
                log.debug(f"{sym}: {e}")

    log.info(f"Scored {len(cands)} | Passed: {len(results)}")

    if not results:
        msg = (
            f"📋 <b>FORTRESS v6.0 — {date_label}</b>\n"
            f"Regime: {macro['macro_state']} VIX={macro['vix_val']:.1f}\n"
            f"No candidates cleared all gates today.\n"
            f"Fused min={APEX_MIN_SCORE}, CONVICTION_RERANK={'on' if CONVICTION_RERANK else 'off'}"
        )
        _send_tg(msg)
        return []

    # 8. Three-lane winner selection
    winners = select_lane_winners(results, macro)

    # 8a. Sec 26: Options gravity overlay — suppress breakout lanes at Call OI walls
    options = {}
    try:
        options = fetch_options_gravity("NIFTY")
        winners = apply_options_gravity_gate(winners, options, macro)
    except Exception as _og_e:
        log.warning(f"Options gravity non-fatal: {_og_e}")

    # 8b. Sec 27: Kelly criterion multiplier for position sizing
    kelly_mult, kelly_stats = (1.0, {})
    try:
        kelly_mult, kelly_stats = compute_kelly_multiplier()
        # Apply Kelly multiplier to shares in all lane winners
        for lane, w in winners.items():
            if w and w.get("shares", 0) > 0:
                w["shares"]      = kelly_adjusted_size(w["shares"], kelly_mult)
                w["kelly_mult"]  = kelly_mult
                w["kelly_stats"] = kelly_stats
    except Exception as _k_e:
        log.warning(f"Kelly sizing non-fatal: {_k_e}")

    final_picks = [w for w in winners.values() if w]
    if not final_picks:
        _send_tg(f"📋 <b>FORTRESS v6.0 — {date_label}</b>\n"
                 f"Regime: {macro['macro_state']} | {len(results)} scored\n"
                 f"No picks passed lane gates today (pearls-or-nothing).")
        return []

    # 9. Persist to SCREENER tab
    push_screener_to_sheets(winners, date_label)

    # 10. Telegram alert (Phase 5 execution disabled)
    send_telegram_picks(winners, macro, fii_data, date_label,
                        options=options, kelly_stats=kelly_stats)

    # 11. Outcome engine (resolve yesterday's picks)
    try:
        run_outcome_engine(date_label)
    except Exception as e:
        log.warning(f"Outcome engine non-fatal: {e}")

    # 12. Performance tab
    try:
        push_performance_to_sheets(date_label)
    except Exception as e:
        log.warning(f"Performance tab non-fatal: {e}")

    log.info(f"✅ Run complete | {len(final_picks)} pick(s) | "
             f"{[p['symbol'] for p in final_picks]}")
    return final_picks


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 24 — CLI ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fortress Sniper v6.0 EOD Quantum Screener")
    parser.add_argument("--weekly-review", action="store_true",
                        help="Run weekly performance review")
    parser.add_argument("--outcome-only", action="store_true",
                        help="Run outcome engine only (no new scoring)")
    parser.add_argument("--store-vector", metavar="SYMBOL",
                        help="Manually store alt-data vector for a symbol")
    args = parser.parse_args()

    if args.weekly_review:
        force = os.getenv("FORCE_WEEKLY","false").lower() in ("1","true","yes")
        run_weekly_review(force=force)
    elif args.outcome_only:
        _init_db()
        _, date_label = _get_last_trading_day()
        run_outcome_engine(date_label)
        auto_log_skipped_picks(date_label)
    elif args.store_vector:
        sym = args.store_vector.upper()
        _init_db()
        tenders = _scrape_cpp_tenders(sym)
        exports = _scrape_zauba_exports(sym)
        text = _build_alt_data_text(sym, tenders, exports)
        if text:
            ok = store_alt_vector(sym, "manual", text, "WIN_50PCT")
            print(f"Vector stored: {ok}")
        else:
            print("No alt-data found")
    else:
        run()
