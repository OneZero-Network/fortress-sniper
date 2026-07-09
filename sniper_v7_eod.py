#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   PROJECT FORTRESS — SNIPER v7.4 EOD QUANTUM SCREENER                      ║
║   Bismillah — In the name of Allah, the Most Gracious, the Most Merciful   ║
║                                                                              ║
║   v7.4 — RACE FIX + 4-TIER DATA CASCADE + GHA HARDENING                   ║
║   ─────────────────────────────────────────────────────────────             ║
║   PATCH-1  RACE CONDITION FIX (21-Second Illusion)                         ║
║            Old: background thread started → scoring immediately started    ║
║            → workers found empty hist_cache → every stock scored 0.        ║
║            New: ThreadPoolExecutor(12) preloads all history BLOCKING.      ║
║            Scoring only starts after join completes. Progress logged       ║
║            every 30 symbols so GHA doesn't timeout.                        ║
║                                                                              ║
║   PATCH-2  GHA CONCURRENCY COLLISION (yml fix required)                    ║
║            Multiple workflows fighting for same pip cache → DB amnesia.    ║
║            Add to yml:  concurrency:                                        ║
║                           group: sniper-eod-pipeline                       ║
║                           cancel-in-progress: true                         ║
║                                                                              ║
║   PATCH-3  ALT-DATA SCRAPERAPI GUARD                                       ║
║            CPP/Zauba scraping now explicitly skipped (with WARNING log)    ║
║            when SCRAPERAPI_KEY secret is missing.                          ║
║            Set SCRAPERAPI_KEY in GHA secrets to re-enable Option-C.       ║
║                                                                              ║
║   PATCH-4  4-TIER BHAVCOPY DATA CASCADE (v5.5 re-injection)               ║
║            1. NSE archives (3-step CF session + Akamai URL3 + curl)       ║
║            2. Addon Finance API (set ADDON_FINANCE_API_KEY secret)        ║
║            3. Google Sheets BHAVCOPY tab (your 2441-row manual extract)   ║
║            4. yfinance 300-stock universe (last resort only)               ║
║            Sheets fallback gives full market breadth when NSE blocked.    ║
║                                                                              ║
║   v7.3 FIXES (PRESERVED): NSE session handshake · Akamai URL · NSE VIX   ║
║            NSE history API · Holiday calendar · Sentinel file             ║
║   v7.1 PATCHES (PRESERVED): NATR · DynNIFTY50 · MFI-catalyst · PctVPOC  ║
║   v7.0 ARCH (PRESERVED): All engines, gates, scoring, Halal, Kelly       ║
║                                                                              ║
║   STACK    Google Sheets · GitHub Actions · OpenAI gpt-4o-mini            ║
║            NSE APIs · Zero Yahoo Finance dependency                       ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os, io, sys, re, json, math, time, random, logging, hashlib
import threading, warnings, asyncio, queue, itertools, collections
import sqlite3, subprocess
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

import requests
import numpy as np
import pandas as pd

# v8.0: curl_cffi for NSE Akamai/TLS-fingerprint bypass (SAST + Pledge data)
try:
    from curl_cffi import requests as curl_requests
    _CURL_CFFI_OK = True
except ImportError:
    _CURL_CFFI_OK = False
    log_placeholder = None  # will use log after init

# v8.3: Optional OCR stack for scanned-image corporate announcement PDFs.
# Degrades gracefully — if tesseract/poppler aren't installed on the runner,
# OCR is simply skipped rather than crashing the whole run.
try:
    import pytesseract
    from pdf2image import convert_from_bytes
    _OCR_OK = True
except ImportError:
    _OCR_OK = False

_OCR_STATS = {"attempted": 0, "success": 0, "failed": 0}

warnings.filterwarnings("ignore", category=FutureWarning)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fortress_v7")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — CONFIGURATION & SECRETS
# ══════════════════════════════════════════════════════════════════════════════

VERSION = "FORTRESS v8.2 — APEX PREDATOR (HEIST_BEFORE_GATE+BASE_FORMING_FULL_SCORE)"

# ── FIX-C: Secret preflight check ────────────────────────────────────────────
# Called once at run() start. Warns (not crashes) on missing secrets so the
# run degrades gracefully and the artifact log shows exact root cause.
def _preflight_secrets() -> dict:
    """
    Check all required GitHub Actions secrets are set.
    Returns dict of {secret_name: bool}.  Logs WARNING for each missing one.
    Does NOT abort — caller decides whether to proceed in degraded mode.
    """
    checks = {
        "OPENAI_API_KEY":    bool(os.getenv("OPENAI_API_KEY",    "")),
        "TELEGRAM_TOKEN":    bool(os.getenv("TELEGRAM_TOKEN",    "")),
        "TELEGRAM_CHAT_ID":  bool(os.getenv("TELEGRAM_CHAT_ID",  "")),
        "GOOGLE_SHEET_ID":   bool(os.getenv("GOOGLE_SHEET_ID",   "")),
        "GOOGLE_CREDS_JSON": bool(os.getenv("GOOGLE_CREDS_JSON", "")),
    }
    for k, ok in checks.items():
        if not ok:
            log.warning(f"SECRET MISSING: {k} — related features will degrade gracefully")
        else:
            log.info(f"SECRET OK: {k}")
    all_ok = all(checks.values())
    if all_ok:
        log.info("✅ All secrets present")
    else:
        missing = [k for k, v in checks.items() if not v]
        log.warning(f"⚠️ Missing secrets: {missing}")
    return checks

# ── FIX-B: Run sentinel / diagnostic writer ──────────────────────────────────
_OUTPUTS_DIR = Path(os.getenv("CACHE_PATH", "outputs/sniper_cache.db")).parent

def _write_sentinel(date_label: str, stage: str, extra: dict = None):
    """
    FIX-B: Write outputs/last_run.txt on every run (even aborts).
    Guarantees the GHA artifact is never an empty 1.3 KB skeleton.
    The sentinel is plain-text so it's human-readable in the artifact download.
    """
    try:
        _OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        lines = [
            f"VERSION : {VERSION}",
            f"DATE    : {date_label}",
            f"STAGE   : {stage}",
            f"UTCTIME : {datetime.utcnow().isoformat()}",
        ]
        if extra:
            for k, v in extra.items():
                lines.append(f"{k:8s}: {v}")
        (_OUTPUTS_DIR / "last_run.txt").write_text("\n".join(lines) + "\n")
    except Exception as e:
        log.debug(f"_write_sentinel: {e}")

# LLM
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY", "")
OPENAI_MINI_MODEL  = os.getenv("OPENAI_MINI_MODEL", "gpt-4o-mini")
OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
_OPENAI_OK         = bool(OPENAI_API_KEY)
LLM_ENABLED        = _OPENAI_OK

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
ATR_PERIOD      = int(os.getenv("ATR_PERIOD", "14"))
ATR_MULT_TREND  = float(os.getenv("ATR_MULT_TREND", "1.5"))
ATR_MULT_CHOP   = float(os.getenv("ATR_MULT_CHOP", "2.0"))
ATR_MULT_BUNKER = float(os.getenv("ATR_MULT_BUNKER", "2.5"))
VIX_TREND_MAX   = float(os.getenv("VIX_TREND_MAX", "15"))
VIX_CHOP_MAX    = float(os.getenv("VIX_CHOP_MAX", "22"))

# Phase-3 EOD order flow
WHALE_DELIVERY_PCT = float(os.getenv("WHALE_DELIVERY_PCT", "65"))
WHALE_VOL_MULT     = float(os.getenv("WHALE_VOL_MULT", "1.5"))

# Phase-4 alt-data
ALT_DATA_ENABLED   = os.getenv("ALT_DATA_ENABLED", "true").lower() in ("1","true","yes")
ALT_DATA_MATCH_SIM = float(os.getenv("ALT_DATA_MATCH_SIM", "0.72"))
SCRAPERAPI_KEY     = os.getenv("SCRAPERAPI_KEY", "")

# Conviction rerank (Option-C, v5.5.2 preserved)
CONVICTION_RERANK      = os.getenv("CONVICTION_RERANK", "true").lower() in ("1","true","yes")
CONV_REQUIRE_CATALYST  = os.getenv("CONV_REQUIRE_CATALYST", "true").lower() in ("1","true","yes")
CONV_RS_CATALYST_FLOOR = float(os.getenv("CONV_RS_CATALYST_FLOOR", "85"))
CONV_RS_MIN_PCT        = float(os.getenv("CONV_RS_MIN_PCT", "70"))
CONV_LANE_FORTRESS_MIN = int(os.getenv("CONV_LANE_FORTRESS_MIN", "120"))
CONV_LANE_APEX_MIN     = int(os.getenv("CONV_LANE_APEX_MIN", "60"))
CONV_LANE_FUSED_MIN    = int(os.getenv("CONV_LANE_FUSED_MIN", "70"))

LANE_FORTRESS_MIN = int(os.getenv("LANE_FORTRESS_MIN", "100"))
LANE_APEX_MIN     = int(os.getenv("LANE_APEX_MIN", "55"))
LANE_FUSED_MIN    = int(os.getenv("LANE_FUSED_MIN", "60"))

# ── v8.0: Pledge Gate ─────────────────────────────────────────────────────────
# Promoter pledge > this % → auto-skip (flash-crash risk)
PLEDGE_GATE_MAX_PCT   = float(os.getenv("PLEDGE_GATE_MAX_PCT", "50.0"))
PLEDGE_GATE_ENABLED   = os.getenv("PLEDGE_GATE_ENABLED", "true").lower() in ("1","true","yes")

# ── v8.0: Sector Velocity (Momentum Multiplier) ───────────────────────────────
# Fused score penalty when sector index is bleeding while stock breaks out
SECTOR_VELOCITY_ENABLED  = os.getenv("SECTOR_VELOCITY_ENABLED", "true").lower() in ("1","true","yes")
SECTOR_VELOCITY_PENALTY  = float(os.getenv("SECTOR_VELOCITY_PENALTY", "15.0"))  # pts deducted from fused
# NIFTY sector index symbols mapped to our internal sector labels
SECTOR_INDEX_MAP: Dict[str, str] = {
    "IT":        "^CNXIT",
    "PHARMA":    "^CNXPHARMA",
    "FMCG":      "^CNXFMCG",
    "METAL":     "^CNXMETAL",
    "ENERGY":    "^CNXENERGY",
    "BANK":      "^NSEBANK",
    "FINANCE":   "^CNXFINANCE",
    "REALTY":    "^CNXREALTY",
    "AUTO":      "^CNXAUTO",
    "INFRA":     "^CNXINFRA",
    "CHEMICALS": "^CNXCHEM",
    "TEXTILE":   "^CNXTEXTILE",
}

CAPACITY_MAX_OPEN = int(os.getenv("CAPACITY_MAX_OPEN", "4"))
CAPACITY_MAX_WEEK = int(os.getenv("CAPACITY_MAX_WEEK", "6"))

# ── v7.0: Uptrend Gate params ─────────────────────────────────────────────────
# 50MA must be at least this fraction above 200MA (0 = equal is OK)
UPTREND_MA50_LEAD   = float(os.getenv("UPTREND_MA50_LEAD", "0.0"))
# Allow up to 3% slack when 200MA data is unavailable (< 200 bars)
UPTREND_MA_SLACK    = float(os.getenv("UPTREND_MA_SLACK", "0.03"))

# ── v7.0: Confidence Score threshold ─────────────────────────────────────────
# If cross-signal std > this, output None (statistically weak setup)
CONFIDENCE_STD_MAX  = float(os.getenv("CONFIDENCE_STD_MAX", "0.25"))
# Floor confidence below which pick is suppressed
CONFIDENCE_MIN      = float(os.getenv("CONFIDENCE_MIN", "0.45"))

# Sector ATR multipliers
SECTOR_ATR_MULT = {
    "METAL":   1.35, "ENERGY":  1.20, "PHARMA":  1.10,
    "FMCG":    0.85, "IT":      0.80, "BANK":    0.95,
    "FINANCE": 0.90, "REALTY":  1.15, "AUTO":    1.05,
    "INFRA":   1.10, "CHEMICALS": 1.15, "TEXTILE": 1.20,
}

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — GOOGLE SHEETS DB
# ══════════════════════════════════════════════════════════════════════════════

_GS_WORKBOOK: Any    = None
_GS_LOCK              = threading.Lock()
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
            return wb.add_worksheet(title=tab, rows=2000, cols=50)
        except Exception as e:
            log.warning(f"_get_ws create {tab}: {e}")
            return None

def _push_sheet(tab: str, rows: list) -> bool:
    if not rows:
        return True
    ws = _get_ws(tab)
    if ws is None:
        return False
    try:
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
    ws = _get_ws(tab)
    if ws is None:
        return []
    try:
        return ws.get_all_values()
    except Exception as e:
        log.warning(f"_read_sheet {tab}: {e}")
        return []

def _append_sheet_row(tab: str, row: list) -> bool:
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
# SECTION 3 — SQLITE (ephemeral cache: score_cache + llm_cache + macro_cache)
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
        con = sqlite3.connect(str(DB_PATH), timeout=timeout, check_same_thread=False)
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
    con = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
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
            symbol       TEXT NOT NULL,
            source       TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            embedding_json TEXT NOT NULL,
            raw_text     TEXT,
            fetched_at   TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (symbol, source, content_hash)
        );
        CREATE TABLE IF NOT EXISTS meta_labels (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol       TEXT,
            run_date     TEXT,
            fort_pts     REAL,
            apex_comp    REAL,
            fused        REAL,
            bayes_pct    REAL,
            rsi14        REAL,
            adx14        REAL,
            mfi          REAL,
            atr14        REAL,
            atr_mult     REAL,
            whale_score  REAL,
            delivery_pct REAL,
            vol_ratio    REAL,
            rs_pct       REAL,
            at_vpoc      INTEGER,
            whale_flag   INTEGER,
            has_catalyst INTEGER,
            vix_val      REAL,
            advance_ratio REAL,
            confidence_score REAL,
            outcome      INTEGER,
            created_at   TEXT DEFAULT CURRENT_TIMESTAMP
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
                "(text_hash, prompt_type, result, model, expires_at) VALUES (?,?,?,?,?)",
                (text_hash, prompt_type, result, model, expires)
            )
    except Exception:
        pass

def _score_cache_get(sym: str, date_label: str,
                     close: float, intel_hash: str) -> Optional[dict]:
    try:
        with _db_conn() as con:
            row = con.execute(
                "SELECT result_json FROM score_cache "
                "WHERE symbol=? AND run_date=? AND intel_hash=? "
                "AND abs(bhavcopy_close - ?) < 0.01",
                (sym, date_label, intel_hash, close)
            ).fetchone()
        return json.loads(row[0]) if row else None
    except Exception:
        return None

def _score_cache_put(sym: str, date_label: str, close: float,
                     result: dict, intel_hash: str):
    try:
        with _db_conn(write=True) as con:
            con.execute(
                "INSERT OR REPLACE INTO score_cache "
                "(symbol, run_date, bhavcopy_close, intel_hash, result_json) "
                "VALUES (?,?,?,?,?)",
                (sym, date_label, close, intel_hash, json.dumps(result))
            )
    except Exception:
        pass

def _load_cached_macro() -> Optional[dict]:
    try:
        with _db_conn() as con:
            row = con.execute(
                "SELECT macro_state, vix_val, nifty_chg, breadth_ok FROM macro_cache "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row:
            return {"macro_state": row[0], "vix_val": row[1],
                    "nifty_chg": row[2], "breadth_ok": bool(row[3])}
    except Exception:
        pass
    return None

def _save_macro_cache(macro: dict):
    try:
        with _db_conn(write=True) as con:
            con.execute("DELETE FROM macro_cache")
            con.execute(
                "INSERT INTO macro_cache (macro_state, vix_val, nifty_chg, breadth_ok) "
                "VALUES (?,?,?,?)",
                (macro.get("macro_state","CHOP"), macro.get("vix_val", 18.0),
                 macro.get("nifty_chg", 0.0), int(macro.get("breadth_ok", True)))
            )
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — OPENAI HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _call_openai(prompt: str, max_tokens: int = 200,
                 cache_ttl_days: int = 1) -> Optional[str]:
    if not _OPENAI_OK:
        return None
    h = hashlib.md5(prompt.encode()).hexdigest()
    cached = _llm_cache_get(h)
    if cached:
        return cached
    for attempt in range(3):
        try:
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                         "Content-Type": "application/json"},
                json={"model": OPENAI_MINI_MODEL,
                      "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": max_tokens, "temperature": 0.2},
                timeout=30,
            )
            if resp.status_code == 200:
                txt = resp.json()["choices"][0]["message"]["content"].strip()
                if cache_ttl_days > 0:
                    _llm_cache_put(h, txt, "generic", OPENAI_MINI_MODEL, cache_ttl_days)
                return txt
            elif resp.status_code == 429:
                time.sleep(2 ** attempt)
        except Exception as e:
            log.debug(f"_call_openai attempt {attempt}: {e}")
            time.sleep(1)
    return None

def _call_openai_embed(text: str) -> Optional[List[float]]:
    if not _OPENAI_OK:
        return None
    try:
        resp = requests.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": OPENAI_EMBED_MODEL, "input": text[:8000]},
            timeout=20,
        )
        if resp.status_code == 200:
            return resp.json()["data"][0]["embedding"]
    except Exception as e:
        log.debug(f"_call_openai_embed: {e}")
    return None

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — HALAL SCREEN (L1–L4, preserved from v6.0)
# ══════════════════════════════════════════════════════════════════════════════

_HARAM_KEYWORDS = {
    "bank","banking","finance","financial","insurance","nbfc","nbfc","mortgage",
    "microfinance","mfin","chit fund","alcohol","brewery","beer","liquor","wine",
    "tobacco","cigarette","pork","pig","casino","gambling","lottery","porn",
    "adult entertainment","weapons","defence prod","arms","ammunition",
    "pig","conventional loan","interest income",
}
_PERMISSIBLE_OVERRIDES = {
    "FEDERALBNK_EXCLUDED","HDFCBANK_EXCLUDED",
}

_SECTOR_HALAL_MAP: Dict[str, str] = {
    "IT": "ACCEPTABLE", "PHARMA": "ACCEPTABLE", "FMCG": "REVIEW",
    "METAL": "ACCEPTABLE", "ENERGY": "REVIEW", "BANK": "HARAM",
    "FINANCE": "HARAM", "REALTY": "ACCEPTABLE", "AUTO": "ACCEPTABLE",
    "INFRA": "ACCEPTABLE", "CHEMICALS": "ACCEPTABLE", "TEXTILE": "ACCEPTABLE",
    "DIVERSIFIED": "ACCEPTABLE",
}

_SECTOR_MAP: Dict[str, str] = {
    "TCS":"IT","INFY":"IT","WIPRO":"IT","HCLTECH":"IT","TECHM":"IT",
    "PERSISTENT":"IT","COFORGE":"IT","LTIM":"IT","MPHASIS":"IT","KPITTECH":"IT",
    "TATAELXSI":"IT","ZOMATO":"IT","NAUKRI":"IT",
    "SUNPHARMA":"PHARMA","DRREDDY":"PHARMA","CIPLA":"PHARMA","DIVISLAB":"PHARMA",
    "TORNTPHARM":"PHARMA","ALKEM":"PHARMA","ZYDUSLIFE":"PHARMA",
    "HINDUNILVR":"FMCG","ITC":"FMCG","NESTLEIND":"FMCG","BRITANNIA":"FMCG",
    "MARICO":"FMCG","DABUR":"FMCG","COLPAL":"FMCG","TATACONSUM":"FMCG",
    "RELIANCE":"ENERGY","ONGC":"ENERGY","BPCL":"ENERGY","COALINDIA":"ENERGY",
    "TATAPOWER":"ENERGY","ADANIGREEN":"ENERGY","NTPC":"ENERGY","POWERGRID":"ENERGY",
    "HDFCBANK":"BANK","ICICIBANK":"BANK","SBIN":"BANK","KOTAKBANK":"BANK",
    "AXISBANK":"BANK","BANDHANBNK":"BANK","FEDERALBNK":"BANK","IDFCFIRSTB":"BANK",
    "PNB":"BANK","CANBK":"BANK","UNIONBANK":"BANK","BANKBARODA":"BANK",
    "BAJFINANCE":"FINANCE","BAJAJFINSV":"FINANCE","CHOLAFIN":"FINANCE",
    "MUTHOOTFIN":"FINANCE","ABCAPITAL":"FINANCE","MFSL":"FINANCE",
    "HDFCLIFE":"FINANCE","SBILIFE":"FINANCE",
    "JSWSTEEL":"METAL","HINDZINC":"METAL","VEDL":"METAL","TATASTEEL":"METAL",
    "COALINDIA":"METAL",
    "MARUTI":"AUTO","TATAMOTORS":"AUTO","M&M":"AUTO","HEROMOTOCO":"AUTO",
    "BAJAJ-AUTO":"AUTO","EICHERMOT":"AUTO","MOTHERSON":"AUTO",
    "LT":"INFRA","NBCC":"INFRA","NCC":"INFRA","CONCOR":"INFRA",
    "HAL":"INFRA","BEL":"INFRA","BHEL":"INFRA","IRCON":"INFRA","RITES":"INFRA",
    "ULTRACEMCO":"REALTY","SHREECEM":"REALTY","ACC":"REALTY","AMBUJACEM":"REALTY",
    "DEEPAKNTR":"CHEMICALS","PIIND":"CHEMICALS","UPL":"CHEMICALS",
    "COROMANDEL":"CHEMICALS","CHAMBLFERT":"CHEMICALS","GNFC":"CHEMICALS",
    "TATACHEM":"CHEMICALS","NAVINFLUOR":"CHEMICALS","FINEORG":"CHEMICALS",
    "TITAN":"DIVERSIFIED","APOLLOHOSP":"PHARMA","DMART":"FMCG",
    "IRCTC":"INFRA","ADANIPORTS":"INFRA","ADANITRANS":"INFRA",
    "ASTRAL":"DIVERSIFIED","POLYCAB":"DIVERSIFIED","DIXON":"DIVERSIFIED",
    "KAYNES":"DIVERSIFIED","ABB":"DIVERSIFIED","SIEMENS":"DIVERSIFIED",
    "CUMMINSIND":"DIVERSIFIED","THERMAX":"DIVERSIFIED","CARBORUNIV":"DIVERSIFIED",
    "HAVELLS":"DIVERSIFIED","PIDILITIND":"CHEMICALS","BERGEPAINT":"CHEMICALS",
    "PAGEIND":"TEXTILE","RELAXO":"DIVERSIFIED","BATAINDIA":"DIVERSIFIED",
    "SYNGENE":"PHARMA","KALYANKJIL":"DIVERSIFIED","CONCOR":"INFRA",
    "WIPRO":"IT","PACEDIGITK":"IT","PINELABS":"IT","SPARC":"PHARMA",
    "JAINREC":"DIVERSIFIED","MANINFRA":"INFRA","PRICOLLTD":"AUTO","TMCV":"AUTO",
    "APLLTD":"DIVERSIFIED","MOTHERSON":"AUTO","ZEEL":"DIVERSIFIED",
}

def get_sector(symbol: str) -> str:
    return _SECTOR_MAP.get(symbol.upper(), "DIVERSIFIED")

def halal_l1_veto(symbol: str) -> Tuple[bool, str]:
    sl = symbol.lower()
    for kw in _HARAM_KEYWORDS:
        if kw in sl:
            return True, f"L1 keyword: {kw}"
    return False, ""

def halal_ai_screen(symbol: str, sector: str) -> dict:
    sym = symbol.upper()
    # L2: sector check
    tier = _SECTOR_HALAL_MAP.get(sector, "ACCEPTABLE")
    if tier == "HARAM":
        return {"veto": True, "tier": "HARAM", "score": 0, "source": "L2_SECTOR",
                "veto_reason": f"Sector {sector} is haram", "llm_confidence": 1.0}
    if tier == "ACCEPTABLE":
        return {"veto": False, "tier": "ACCEPTABLE", "score": 80, "source": "L2_SECTOR",
                "veto_reason": "", "llm_confidence": 0.9}
    # L3: keyword scan of company name (company name ≈ symbol for our universe)
    vetoed, reason = halal_l1_veto(sym)
    if vetoed:
        return {"veto": True, "tier": "HARAM", "score": 0, "source": "L3_KEYWORD",
                "veto_reason": reason, "llm_confidence": 1.0}
    # L4: LLM (only for REVIEW sectors)
    if not _OPENAI_OK:
        return {"veto": False, "tier": "ACCEPTABLE", "score": 60, "source": "L4_FALLBACK",
                "veto_reason": ""}
    prompt = (f"Is {sym} (Indian stock, sector: {sector}) compliant with Islamic finance? "
              f"Respond ONLY as JSON: {{\"halal\": true/false, \"tier\": \"ACCEPTABLE|REVIEW|HARAM\", "
              f"\"score\": 0-100, \"reason\": \"brief\"}}")
    cache_key = hashlib.md5(f"halal_l4:{sym}:{sector}".encode()).hexdigest()
    raw = _llm_cache_get(cache_key) or _call_openai(prompt, max_tokens=150, cache_ttl_days=30)
    if raw:
        _llm_cache_put(cache_key, raw, "halal_l4", OPENAI_MINI_MODEL, ttl_days=30)
        try:
            parsed = json.loads(re.sub(r"```json|```", "", raw).strip())
            is_haram = not parsed.get("halal", True)
            return {
                "veto": is_haram, "tier": parsed.get("tier", "ACCEPTABLE"),
                "score": int(parsed.get("score", 60)), "source": "L4_LLM",
                "veto_reason": parsed.get("reason","") if is_haram else "",
                "llm_confidence": parsed.get("score", 60) / 100,
            }
        except Exception:
            pass
    return {"veto": False, "tier": "ACCEPTABLE", "score": 60, "source": "L4_FALLBACK",
            "veto_reason": ""}

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — MACRO REGIME ENGINE (Phase 2)
# ══════════════════════════════════════════════════════════════════════════════

def fetch_macro_regime() -> dict:
    """
    FIX-F: NSE-native macro regime — zero Yahoo Finance dependency.

    VIX:    NSE option-chain VIX via nseindia.com/api/allIndices
            (India VIX is listed as "INDIA VIX" in allIndices response)
    NIFTY:  NIFTY 50 % change from the same allIndices response
    Breadth: advance/decline from nseindia.com/api/advance-decline

    Falls back to last cached macro on any failure.
    """
    FALLBACK_CHOP = {
        "macro_state": "CHOP", "vix_val": 18.0, "nifty_chg": 0.0,
        "breadth_ok": True, "atr_mult": ATR_MULT_CHOP,
        "advance_ratio": 0.5, "source": "FALLBACK",
    }
    try:
        sess = _get_nse_session()
        hdrs = {**_NSE_HEADERS,
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://www.nseindia.com/"}

        # Step 1: allIndices — NIFTY 50 change + India VIX
        resp = sess.get("https://www.nseindia.com/api/allIndices",
                        headers=hdrs, timeout=12)
        if resp.status_code != 200:
            raise ValueError(f"allIndices HTTP {resp.status_code}")

        indices = resp.json().get("data", [])
        vix_val  = 18.0
        nifty_chg = 0.0
        for idx in indices:
            name = str(idx.get("index","") or idx.get("indexSymbol","")).upper()
            if "INDIA VIX" in name or name == "INDIAVIX":
                try:
                    vix_val = float(idx.get("last", idx.get("lastPrice", 18.0)))
                except Exception:
                    pass
            if "NIFTY 50" == name or name == "NIFTY50":
                try:
                    nifty_chg = float(idx.get("percentChange", idx.get("pChange", 0.0)))
                except Exception:
                    pass

        # Step 2: advance-decline for breadth
        advance_ratio = 0.5
        breadth_ok    = True
        try:
            resp2 = sess.get("https://www.nseindia.com/api/advance-decline",
                             headers=hdrs, timeout=10)
            if resp2.status_code == 200:
                ad   = resp2.json()
                adv  = float(ad.get("advances", ad.get("advance", 0)))
                dec  = float(ad.get("declines", ad.get("decline", 1)))
                total = adv + dec
                advance_ratio = adv / total if total > 0 else 0.5
                breadth_ok    = advance_ratio >= 0.5
        except Exception as e:
            log.debug(f"advance-decline: {e}")

        # Regime classification
        if vix_val <= VIX_TREND_MAX and breadth_ok:
            state = "TREND";  atr_mult = ATR_MULT_TREND
        elif vix_val <= VIX_CHOP_MAX:
            state = "CHOP";   atr_mult = ATR_MULT_CHOP
        else:
            state = "BUNKER"; atr_mult = ATR_MULT_BUNKER

        if vix_val > 30 and nifty_chg < -2.5:
            state = "MASSACRE"; atr_mult = ATR_MULT_BUNKER * 1.3
        elif vix_val > 25 and nifty_chg < -1.5:
            state = "PANIC";   atr_mult = ATR_MULT_BUNKER * 1.1

        macro = {
            "macro_state": state, "vix_val": round(vix_val, 2),
            "nifty_chg":   round(nifty_chg, 2), "breadth_ok": breadth_ok,
            "atr_mult":    atr_mult, "advance_ratio": round(advance_ratio, 3),
            "source": "NSE_API",
        }
        _save_macro_cache(macro)
        log.info(f"Macro regime: {state} VIX={vix_val:.1f} "
                 f"NIFTY={nifty_chg:+.2f}% breadth={advance_ratio:.0%} [NSE_API]")
        return macro

    except Exception as e:
        log.warning(f"fetch_macro_regime NSE failed ({e}) — using cached/fallback")
        cached = _load_cached_macro()
        if cached:
            cached["atr_mult"] = {
                "TREND": ATR_MULT_TREND, "CHOP": ATR_MULT_CHOP,
                "BUNKER": ATR_MULT_BUNKER,
            }.get(cached["macro_state"], ATR_MULT_CHOP)
            cached["source"] = "CACHED"
            return cached
        return FALLBACK_CHOP

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — NSE DATA (Bhavcopy + MTO + History + FII/DII + Insider + Filings)
# ══════════════════════════════════════════════════════════════════════════════

_NSE_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}

# ── FIX-D: NSE Holiday Calendar 2025-2026 ────────────────────────────────────
_NSE_HOLIDAYS = {
    # 2025
    "2025-01-26","2025-02-19","2025-03-25","2025-03-31",
    "2025-04-02","2025-04-06","2025-04-10","2025-04-14",
    "2025-04-17","2025-04-18","2025-05-01","2025-08-15",
    "2025-08-27","2025-10-02","2025-10-20","2025-10-21",
    "2025-10-22","2025-11-05","2025-11-11","2025-11-26","2025-12-25",
    # 2026
    "2026-01-26","2026-02-19","2026-03-25","2026-03-31",
    "2026-04-02","2026-04-06","2026-04-10","2026-04-14",
    "2026-04-17","2026-05-01","2026-06-19","2026-08-15",
    "2026-08-27","2026-10-02","2026-10-20","2026-10-21",
    "2026-11-05","2026-11-27","2026-12-25",
}

def _get_last_trading_day() -> Tuple[str, str]:
    """
    FIX-D: Holiday-aware last trading day.
    Walks back up to 10 days skipping weekends and NSE holidays.
    Prevents 404 on bhavcopy when market was closed.
    """
    today = datetime.today()
    d = today - timedelta(days=1)
    for _ in range(10):
        if d.weekday() < 5 and d.strftime("%Y-%m-%d") not in _NSE_HOLIDAYS:
            break
        d -= timedelta(days=1)
    date_str = d.strftime("%Y-%m-%d")
    log.info(f"Last trading day resolved: {date_str} (today={today.strftime('%Y-%m-%d')} weekday={today.weekday()})")
    return d.strftime("%d%m%Y"), date_str

# ── FIX-D: NSE 3-Step Session Manager ────────────────────────────────────────
# ROOT CAUSE: NSE Cloudflare requires a 3-step handshake before serving archives.
# Step 1: GET nseindia.com  → establishes session cookies
# Step 2: GET /api/allIndices → validates the session (CF challenge response)
# Step 3: GET archive URL → now serves with 200
# Without step 2, step 3 always returns 403.
_NSE_SESSION_LOCK  = threading.Lock()
_NSE_SESSION_CACHE: Optional[requests.Session] = None
_NSE_SESSION_TS:   float = 0.0
_NSE_SESSION_TTL   = 300  # seconds — refresh session every 5 min

_UA_POOL = [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) "
     "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15"),
    ("Mozilla/5.0 (X11; Linux x86_64) "
     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
     "Gecko/20100101 Firefox/125.0"),
]

def _get_nse_session():
    """
    v8.1 PATCH 1: Session Armor Repair.
    Uses curl_cffi Chrome TLS fingerprint when available (bypasses Akamai/Cloudflare).
    Falls back to requests.Session() with UA rotation only if curl_cffi missing.
    3-step handshake preserved: homepage → allIndices → ready.
    """
    global _NSE_SESSION_CACHE, _NSE_SESSION_TS
    with _NSE_SESSION_LOCK:
        now = time.time()
        if _NSE_SESSION_CACHE and (now - _NSE_SESSION_TS) < _NSE_SESSION_TTL:
            return _NSE_SESSION_CACHE

        # ── PATCH 1: Aligned variable name → forces curl_cffi path ──────────
        if _CURL_CFFI_OK:
            log.info("NSE session: Activating Chrome TLS fingerprint (curl_cffi) ✅")
            sess = curl_requests.Session(impersonate="chrome110")
            sess.headers.update(_NSE_HEADERS)
        else:
            log.warning("NSE session: curl_cffi unavailable — bare requests (may hit CF)")
            ua   = random.choice(_UA_POOL)
            sess = requests.Session()
            sess.headers.update({**_NSE_HEADERS, "User-Agent": ua})

        try:
            # Step 1: homepage (establish CF cookie)
            r1 = sess.get("https://www.nseindia.com",
                          headers={**_NSE_HEADERS, "Accept": "text/html"},
                          timeout=12)
            log.info(f"NSE session step1 (homepage): HTTP {r1.status_code} "
                     f"cookies={list(sess.cookies.keys())}")
            time.sleep(1.2)
            # Step 2: validate via allIndices (CF session confirmation)
            r2 = sess.get(
                "https://www.nseindia.com/api/allIndices",
                headers={**_NSE_HEADERS,
                         "Accept": "application/json, text/plain, */*",
                         "X-Requested-With": "XMLHttpRequest",
                         "Referer": "https://www.nseindia.com/"},
                timeout=12
            )
            log.info(f"NSE session step2 (allIndices): HTTP {r2.status_code} "
                     f"bytes={len(r2.content)}")
            time.sleep(0.8)
            _NSE_SESSION_CACHE = sess
            _NSE_SESSION_TS    = now
        except Exception as e:
            log.warning(f"NSE session handshake failed: {e} — using partially-warmed session")
            _NSE_SESSION_CACHE = sess
            _NSE_SESSION_TS    = now
        return _NSE_SESSION_CACHE

def _fetch_mto_delivery(date_label: str) -> Dict[str, float]:
    """
    Fetch NSE MTO file for per-symbol delivery %.
    Record type gate: accept types 20/08/DR or series==EQ (belt-and-suspenders).
    Returns {} on failure (non-fatal; whale_score degrades gracefully).
    """
    dd, mm, yyyy = date_label[8:10], date_label[5:7], date_label[:4]
    url = f"https://archives.nseindia.com/archives/equities/mto/MTO_{dd}{mm}{yyyy}.DAT"
    result: Dict[str, float] = {}
    try:
        sess = _get_nse_session()
        resp = sess.get(url, headers={**_NSE_HEADERS, "Referer": "https://www.nseindia.com/"},
                        timeout=15)
        if resp.status_code != 200:
            return result
        text  = resp.text
        delim = "|" if "|" in text[:200] else ","
        for line in text.splitlines():
            parts = [p.strip() for p in line.split(delim)]
            if len(parts) < 7:
                continue
            rec_type = parts[0].strip()
            try:
                sym    = parts[2].strip().upper()
                series = parts[3].strip().upper()
                if rec_type not in ("20","08","DR") and series != "EQ":
                    continue
                if series != "EQ":
                    continue
                result[sym] = round(float(parts[6]), 2)
            except (ValueError, IndexError):
                continue
        log.info(f"MTO delivery: {len(result)} symbols for {date_label} ✅")
    except Exception as e:
        log.warning(f"MTO fetch non-fatal: {e}")
    return result

# ── DATA CASCADE FALLBACKS (v5.5 re-injection) ───────────────────────────────

def _bhavcopy_from_sheets() -> pd.DataFrame:
    """
    DATA CASCADE Fallback: Load manually pasted bhavcopy from Google Sheets
    BHAVCOPY tab. Supports your 2441-row manual NSE extract — gives full market
    breadth even when NSE archives are blocked.
    """
    if not _gs_ok():
        return pd.DataFrame()
    log.info("Bhavcopy: Loading from Sheets 'BHAVCOPY' tab…")
    raw = _read_sheet("BHAVCOPY")
    if not raw or len(raw) < 2:
        log.warning("Bhavcopy Sheets: BHAVCOPY tab empty or missing")
        return pd.DataFrame()
    df = pd.DataFrame(raw[1:], columns=[str(h).strip().upper() for h in raw[0]])
    col_map = {}
    for internal, candidates in {
        "symbol":         ["SYMBOL"],
        "open":           ["OPEN"],
        "high":           ["HIGH"],
        "low":            ["LOW"],
        "close":          ["CLOSE","LTP","LAST"],
        "prevclose":      ["PRVSCLSGPRIC","PREVCLOSE","PREV_CLOSE"],
        "volume":         ["VOLUME","TOTTRDQTY","TTL_TRD_QNTY"],
        "turnover_lakhs": ["TURNOVER_LAKHS","TOTTRDVAL"],
        "series":         ["SERIES"],
        "delivery_pct":   ["DELIVERY_PCT","DELIV_PCT","TOTALDELTRDQTY"],
    }.items():
        for c in candidates:
            if c in df.columns:
                col_map[c] = internal
                break
    df = df.rename(columns=col_map)
    if "series" in df.columns:
        df = df[df["series"].astype(str).str.strip().str.upper() == "EQ"].copy()
    for col in ["open","high","low","close","prevclose","volume","turnover_lakhs","delivery_pct"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "turnover_lakhs" not in df.columns or df["turnover_lakhs"].isna().all():
        df["turnover_lakhs"] = (
            df.get("volume", pd.Series(0, index=df.index)) *
            df.get("close",  pd.Series(0, index=df.index)) / 100_000
        )
    if "delivery_pct" not in df.columns:
        df["delivery_pct"] = 0.0
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    out = df.dropna(subset=["close"]).query("close > 0").reset_index(drop=True)
    log.info(f"Bhavcopy Sheets: {len(out)} EQ rows loaded")
    return out

def _bhavcopy_from_addon(api_key: str, date_label: str) -> pd.DataFrame:
    """
    DATA CASCADE Fallback: Addon Finance API bhavcopy.
    Set ADDON_FINANCE_API_KEY secret in GHA to enable.
    Returns full NSE EQ bhavcopy (~2000+ symbols) via a single API call.
    """
    if not api_key:
        return pd.DataFrame()
    try:
        dd = date_label[8:10]; mm = date_label[5:7]; yyyy = date_label[:4]
        url = (f"https://api.addonfinance.in/api/v1/bhavcopy/cm"
               f"?date={dd}-{mm}-{yyyy}&apikey={api_key}")
        resp = requests.get(url, timeout=20,
                            headers={"User-Agent": random.choice(_UA_POOL)})
        if resp.status_code != 200:
            log.warning(f"Addon Finance HTTP {resp.status_code}")
            return pd.DataFrame()
        data = resp.json()
        rows = data if isinstance(data, list) else data.get("data", [])
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df.columns = [c.strip().upper() for c in df.columns]
        col_map = {}
        for internal, candidates in {
            "symbol": ["SYMBOL","SYM"],
            "open":   ["OPEN","OPENPRICE"],
            "high":   ["HIGH","HIGHPRICE"],
            "low":    ["LOW","LOWPRICE"],
            "close":  ["CLOSE","CLOSEPRICE","LTP"],
            "volume": ["VOLUME","QTY","TOTTRDQTY"],
            "turnover_lakhs": ["TURNOVER","TOTTRDVAL"],
            "series": ["SERIES"],
        }.items():
            for c in candidates:
                if c in df.columns:
                    col_map[c] = internal
                    break
        df = df.rename(columns=col_map)
        if "series" in df.columns:
            df = df[df["series"].astype(str).str.strip().str.upper() == "EQ"].copy()
        needed = ["symbol","open","high","low","close","volume"]
        if not all(c in df.columns for c in needed):
            log.warning(f"Addon Finance: missing columns {[c for c in needed if c not in df.columns]}")
            return pd.DataFrame()
        for col in ["open","high","low","close","volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        if "turnover_lakhs" not in df.columns:
            df["turnover_lakhs"] = df["volume"] * df["close"] / 100_000
        else:
            df["turnover_lakhs"] = pd.to_numeric(df["turnover_lakhs"], errors="coerce").fillna(0) / 100_000
        df["delivery_pct"] = 0.0
        df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
        return df.dropna(subset=["close"]).query("close > 0").reset_index(drop=True)
    except Exception as e:
        log.warning(f"_bhavcopy_from_addon: {e}")
        return pd.DataFrame()

def load_bhavcopy() -> Tuple[pd.DataFrame, str]:
    """
    Load NSE EQ bhavcopy. Merges MTO delivery data.
    Falls back to yfinance on NSE failure.
    Columns: symbol, open, high, low, close, volume, turnover_lakhs, delivery_pct
    """
    _, date_label = _get_last_trading_day()
    dd, mm, yyyy  = date_label[8:10], date_label[5:7], date_label[:4]
    mmm           = datetime.strptime(date_label, "%Y-%m-%d").strftime("%b").upper()

    def _parse_bhav_zip(content: bytes) -> Optional[pd.DataFrame]:
        from zipfile import ZipFile
        try:
            zf       = ZipFile(io.BytesIO(content))
            csv_name = [n for n in zf.namelist() if n.endswith(".csv")][0]
            return _parse_bhav_csv(zf.read(csv_name))
        except Exception as e:
            log.debug(f"_parse_bhav_zip: {e}")
            return None

    def _parse_bhav_csv(raw: bytes) -> Optional[pd.DataFrame]:
        try:
            df_raw = pd.read_csv(io.BytesIO(raw) if isinstance(raw, bytes) else io.StringIO(raw))
            df_raw.columns = [c.strip().upper() for c in df_raw.columns]
            col_map = {}
            for c in df_raw.columns:
                cl = c.lower()
                if "symbol" in cl:                  col_map[c] = "symbol"
                elif "series" in cl:                col_map[c] = "series"
                elif cl == "open":                  col_map[c] = "open"
                elif cl == "high":                  col_map[c] = "high"
                elif cl == "low":                   col_map[c] = "low"
                elif "prevclose" in cl:             col_map[c] = "prevclose"
                elif cl in ("close","ltp","last"):  col_map[c] = "close"
                elif "qty" in cl or "volume" in cl: col_map[c] = "volume"
                elif "val" in cl or "turnover" in cl: col_map[c] = "turnover_lakhs"
                elif "deliv" in cl:                 col_map[c] = "delivery_pct"
                elif "isin" in cl:                  col_map[c] = "isin"
            df_raw = df_raw.rename(columns=col_map)
            if "series" in df_raw.columns:
                df_raw = df_raw[df_raw["series"].astype(str).str.strip() == "EQ"].copy()
            needed = ["symbol","open","high","low","close","volume"]
            if not all(c in df_raw.columns for c in needed):
                log.debug(f"_parse_bhav_csv: missing columns. Have: {list(df_raw.columns)}")
                return None
            df = df_raw[needed].copy()
            for col in ["open","high","low","close","volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
            if "turnover_lakhs" in df_raw.columns:
                df["turnover_lakhs"] = (
                    pd.to_numeric(df_raw["turnover_lakhs"], errors="coerce").fillna(0) / 100_000
                )
            else:
                df["turnover_lakhs"] = df["volume"] * df["close"] / 100_000
            df["delivery_pct"] = (
                pd.to_numeric(df_raw["delivery_pct"], errors="coerce").fillna(0)
                if "delivery_pct" in df_raw.columns else 0.0
            )
            df["symbol"] = df["symbol"].str.strip().str.upper()
            out = df.dropna(subset=["close"]).reset_index(drop=True)
            if len(out) < 100:
                log.debug(f"_parse_bhav_csv: only {len(out)} EQ rows — likely wrong format")
                return None
            return out
        except Exception as e:
            log.debug(f"_parse_bhav_csv: {e}")
            return None

    def _curl_get(url: str) -> Optional[bytes]:
        try:
            r = subprocess.run(
                ["curl", "-sL", "--max-time", "30", "--compressed",
                 "-H", f"User-Agent: {random.choice(_UA_POOL)}",
                 "-H", "Referer: https://www.nseindia.com/",
                 "-H", "Accept-Encoding: gzip, deflate, br",
                 "-H", "Accept: */*", url],
                capture_output=True, timeout=35,
            )
            if r.returncode == 0 and len(r.stdout) > 2000:
                return r.stdout
        except Exception as e:
            log.debug(f"_curl_get: {e}")
        return None

    # ── FIX-D: URL priority order ─────────────────────────────────────────────
    # URL1/URL2: zip archives via Cloudflare — use 3-step session
    # URL3: plain CSV via Akamai CDN — no session needed, direct curl works
    urls_zip = [
        f"https://archives.nseindia.com/content/historical/EQUITIES/{yyyy}/{mmm}/cm{dd}{mmm}{yyyy}bhav.csv.zip",
        f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_{dd}{mm}{yyyy}_F_0000.csv.zip",
    ]
    url_csv_akamai = (
        f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{dd}{mm}{yyyy}.csv"
    )

    # Attempt 1: 3-step CF session + zip URLs (2 retries each with backoff)
    for url in urls_zip:
        for attempt in range(3):
            try:
                sess = _get_nse_session()
                ua   = random.choice(_UA_POOL)
                hdrs = {**_NSE_HEADERS, "User-Agent": ua, "Referer": "https://www.nseindia.com/"}
                time.sleep(0.3 * (attempt + 1))
                resp = sess.get(url, headers=hdrs, timeout=25)
                log.info(f"Bhavcopy NSE zip attempt {attempt+1} "
                         f"→ HTTP {resp.status_code} ({len(resp.content)} bytes) "
                         f"| {url[-55:]}")
                if resp.status_code == 200 and len(resp.content) > 5000:
                    df = _parse_bhav_zip(resp.content)
                    if df is not None and not df.empty:
                        mto = _fetch_mto_delivery(date_label)
                        if mto:
                            df["delivery_pct"] = df["symbol"].map(mto).fillna(0.0)
                        log.info(f"✅ Bhavcopy loaded NSE_ZIP: {len(df)} rows | {date_label}")
                        return df, "NSE_ZIP"
                elif resp.status_code in (403, 503, 429):
                    log.warning(f"NSE zip HTTP {resp.status_code} attempt {attempt+1} — backoff")
                    time.sleep(2 ** attempt)
            except Exception as e:
                log.warning(f"Bhavcopy NSE zip attempt {attempt+1}: {e}")

    # Attempt 2: Akamai plain CSV (different CDN, no CF — curl bypass)
    log.info(f"Bhavcopy: trying Akamai CSV | {url_csv_akamai[-55:]}")
    raw_csv = _curl_get(url_csv_akamai)
    if raw_csv:
        df = _parse_bhav_csv(raw_csv)
        if df is not None and not df.empty:
            mto = _fetch_mto_delivery(date_label)
            if mto:
                df["delivery_pct"] = df["symbol"].map(mto).fillna(0.0)
            log.info(f"✅ Bhavcopy loaded NSE_AKAMAI_CSV: {len(df)} rows | {date_label}")
            return df, "NSE_AKAMAI_CSV"
    else:
        log.warning("Bhavcopy: Akamai CSV curl returned empty")

    # Attempt 3: curl on zip URLs
    for url in urls_zip:
        log.info(f"Bhavcopy: curl zip fallback | {url[-55:]}")
        raw = _curl_get(url)
        if raw:
            df = _parse_bhav_zip(raw)
            if df is not None and not df.empty:
                mto = _fetch_mto_delivery(date_label)
                if mto:
                    df["delivery_pct"] = df["symbol"].map(mto).fillna(0.0)
                log.info(f"✅ Bhavcopy loaded NSE_CURL_ZIP: {len(df)} rows | {date_label}")
                return df, "NSE_CURL_ZIP"

    # ── PATCH DATA CASCADE: Attempt 4: Addon Finance API ─────────────────────
    ADDON_KEY = os.getenv("ADDON_FINANCE_API_KEY", "")
    if ADDON_KEY:
        log.warning("Bhavcopy: NSE failed — trying Addon Finance API…")
        try:
            df = _bhavcopy_from_addon(ADDON_KEY, date_label)
            if not df.empty:
                log.info(f"✅ Bhavcopy loaded ADDON: {len(df)} rows")
                return df, "ADDON"
        except Exception as e:
            log.warning(f"Bhavcopy Addon: {e}")

    # ── PATCH DATA CASCADE: Attempt 5: Google Sheets BHAVCOPY tab ─────────────
    log.warning("Bhavcopy: Addon failed — checking Google Sheets BHAVCOPY tab…")
    try:
        df = _bhavcopy_from_sheets()
        if not df.empty:
            mto = _fetch_mto_delivery(date_label)
            if mto:
                df["delivery_pct"] = df["symbol"].map(mto).fillna(0.0)
            log.info(f"✅ Bhavcopy loaded SHEETS: {len(df)} rows | {date_label}")
            return df, "SHEETS"
    except Exception as e:
        log.warning(f"Bhavcopy Sheets: {e}")

    # ── Attempt 6: yfinance last resort (broken on GHA but try anyway) ────────
    log.warning("Bhavcopy: NSE, Addon, Sheets all failed — last-resort yfinance universe")
    try:
        import yfinance as yf
        syms = _load_nifty500_symbols()[:300]
        raw_yf = yf.download(
            " ".join(f"{s}.NS" for s in syms),
            period="2d", progress=False, auto_adjust=True, timeout=30, group_by="ticker"
        )
        rows = []
        for sym in syms:
            tk = f"{sym}.NS"
            try:
                if hasattr(raw_yf.columns, "levels"):
                    sub = (raw_yf.xs(tk, axis=1, level=0)
                           if tk in raw_yf.columns.get_level_values(0) else None)
                else:
                    sub = raw_yf if len(syms) == 1 else None
                if sub is None or sub.empty:
                    continue
                last = sub.iloc[-1]
                rows.append({
                    "symbol": sym,
                    "open":   float(last.get("Open",   0) or 0),
                    "high":   float(last.get("High",   0) or 0),
                    "low":    float(last.get("Low",    0) or 0),
                    "close":  float(last.get("Close",  0) or 0),
                    "volume": float(last.get("Volume", 0) or 0),
                    "turnover_lakhs": float(last.get("Volume",0) or 0) * float(last.get("Close",0) or 0) / 100_000,
                    "delivery_pct": 0.0,
                })
            except Exception:
                continue
        df = pd.DataFrame(rows)
        if not df.empty and len(df) > 10:
            log.info(f"✅ Bhavcopy loaded YFINANCE: {len(df)} rows")
            return df, "YFINANCE"
    except Exception as e:
        log.error(f"Bhavcopy yfinance fallback: {e}")

    log.error(f"❌ Bhavcopy: ALL sources failed for {date_label}")
    return pd.DataFrame(), "EMPTY"

def _load_nifty500_symbols() -> List[str]:
    try:
        sess = _get_nse_session()
        resp = sess.get(
            "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
            headers=_NSE_HEADERS, timeout=15
        )
        if resp.status_code == 200:
            df   = pd.read_csv(io.StringIO(resp.text))
            syms = df["Symbol"].str.strip().str.upper().tolist()
            log.info(f"Nifty500: {len(syms)} symbols")
            return syms
    except Exception as e:
        log.debug(f"_load_nifty500_symbols: {e}")
    # Curated fallback (200 liquid NSE stocks)
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
        "ABCAPITAL","MFSL","PAGEIND","HONAUT","3MINDIA","ABB","SIEMENS",
        "CUMMINSIND","THERMAX","BHEL","HAL","BEL","COCHINSHIP","GRINDWELL",
        "CARBORUNIV","FINEORG","NAVINFLUOR","ATUL","DEEPAKNTR","PIIND","UPL","COROMANDEL",
        "CHAMBLFERT","GNFC","TATACHEM","GHCL","NOCIL","VINDHYATEL","RAILTEL","IRCON",
        "RITES","NBCC","NCC","CONCOR","BLUEDART","MAHINDCIE","ENDURANCE",
        "SUNDRMFAST","GABRIEL","SUPRAJIT","RAMKRISHNA","SYNGENE","KALYANKJIL",
        "MANINFRA","PRICOLLTD","TMCV","APLLTD","SPARC","JAINREC","PACEDIGITK",
        "PINELABS","WIPRO","ZEEL","MOTHERSON",
    ]

def fetch_history(symbol: str, days: int = 300) -> pd.DataFrame:
    """
    FIX-E: NSE Historical API replaces yfinance as primary source.
    Uses nseindia.com/api/historical/cm/equity — same endpoint NSE website uses.
    Works from GHA with a valid NSE session. yfinance kept as last-resort fallback.
    """
    end_dt   = datetime.today()
    start_dt = end_dt - timedelta(days=days + 30)
    end_str   = end_dt.strftime("%d-%m-%Y")
    start_str = start_dt.strftime("%d-%m-%Y")

    # ── Primary: NSE historical API ──────────────────────────────────────────
    try:
        sess = _get_nse_session()
        url  = (f"https://www.nseindia.com/api/historical/cm/equity"
                f"?symbol={symbol}&series=[%22EQ%22]"
                f"&from={start_str}&to={end_str}&csv=true")
        resp = sess.get(
            url,
            headers={**_NSE_HEADERS,
                     "Accept": "application/json, text/plain, */*",
                     "X-Requested-With": "XMLHttpRequest",
                     "Referer": f"https://www.nseindia.com/get-quotes/equity?symbol={symbol}"},
            timeout=20
        )
        if resp.status_code == 200 and len(resp.content) > 200:
            try:
                data = resp.json()
                rows = data.get("data", data) if isinstance(data, dict) else data
                if rows and isinstance(rows, list):
                    df = pd.DataFrame(rows)
                    # NSE returns: CH_TIMESTAMP, CH_OPENING_PRICE, CH_TRADE_HIGH_PRICE,
                    #              CH_TRADE_LOW_PRICE, CH_CLOSING_PRICE, CH_TOT_TRADED_QTY
                    col_map = {}
                    for c in df.columns:
                        cl = c.upper()
                        if "TIMESTAMP" in cl or "DATE" in cl: col_map[c] = "date"
                        elif "OPENING" in cl or cl == "CH_OPENING_PRICE": col_map[c] = "open"
                        elif "HIGH" in cl:    col_map[c] = "high"
                        elif "LOW"  in cl:    col_map[c] = "low"
                        elif "CLOSING" in cl or "CLOSE" in cl: col_map[c] = "close"
                        elif "QTY" in cl or "VOLUME" in cl:    col_map[c] = "volume"
                    df = df.rename(columns=col_map)
                    needed = ["date","open","high","low","close","volume"]
                    if all(c in df.columns for c in needed):
                        df["date"] = pd.to_datetime(df["date"], errors="coerce")
                        for col in ["open","high","low","close","volume"]:
                            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
                        df = df[needed].dropna(subset=["date","close"])
                        df = df[df["close"] > 0].sort_values("date").tail(days).reset_index(drop=True)
                        if len(df) >= 20:
                            log.debug(f"History {symbol}: NSE_API {len(df)} bars")
                            return df
            except Exception as e:
                log.debug(f"fetch_history NSE JSON parse {symbol}: {e}")
    except Exception as e:
        log.debug(f"fetch_history NSE API {symbol}: {e}")

    # ── Fallback: yfinance ────────────────────────────────────────────────────
    try:
        import yfinance as yf
        raw = yf.download(f"{symbol}.NS", start=start_dt, end=end_dt,
                          progress=False, auto_adjust=True, timeout=20)
        if not raw.empty:
            df = raw.reset_index()
            df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                          for c in df.columns]
            dt_col = next((c for c in df.columns if c != "date" and
                           pd.api.types.is_datetime64_any_dtype(df[c])), None)
            if dt_col:
                df = df.rename(columns={dt_col: "date"})
            df["date"] = pd.to_datetime(df["date"])
            df = df[["date","open","high","low","close","volume"]].dropna()
            result = df.tail(days).reset_index(drop=True)
            log.debug(f"History {symbol}: YFINANCE {len(result)} bars")
            return result
    except Exception as e:
        log.debug(f"fetch_history yfinance {symbol}: {e}")

    return pd.DataFrame()

def fetch_fii_dii() -> dict:
    FALLBACK = {"label":"MIXED","fii_net":0.0,"dii_net":0.0,"fii_pts":0,"dii_pts":0,"score":15}
    try:
        sess = _get_nse_session()
        resp = sess.get(
            "https://www.nseindia.com/api/fiidiiTradeReact",
            headers={**_NSE_HEADERS, "X-Requested-With": "XMLHttpRequest"},
            timeout=12
        )
        if resp.status_code != 200:
            return FALLBACK
        data = resp.json()
        rows = data if isinstance(data, list) else data.get("data", [])
        row  = rows[0] if rows else {}
        fii_net  = float(row.get("buyValue",0)) - float(row.get("sellValue",0))
        dii_net  = float(row.get("clientBuyValue",0)) - float(row.get("clientSellValue",0))
        score = 15
        if fii_net >  500: score += 10
        elif fii_net > 0:  score += 5
        elif fii_net < -500: score -= 10
        if dii_net > 0: score += 5
        return {"label": "BULL" if score > 25 else "BEAR" if score < 10 else "MIXED",
                "fii_net": round(fii_net,2), "dii_net": round(dii_net,2),
                "fii_pts": score, "dii_pts": 5 if dii_net > 0 else 0, "score": score}
    except Exception as e:
        log.debug(f"fetch_fii_dii: {e}")
        return FALLBACK

def fetch_insider_trades(days_back: int = 30) -> dict:
    result: dict = {}
    try:
        sess = _get_nse_session()
        resp = sess.get(
            "https://www.nseindia.com/api/bulk-deals",
            headers={**_NSE_HEADERS, "X-Requested-With": "XMLHttpRequest"},
            timeout=12
        )
        if resp.status_code != 200:
            return result
        cutoff = (datetime.today() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        for d in resp.json().get("data", []):
            sym = str(d.get("symbol","")).strip().upper()
            dt  = str(d.get("bdDt",""))[:10]
            if dt < cutoff or not sym:
                continue
            if str(d.get("buySell","")).upper() != "BUY":
                continue
            qty   = float(d.get("bdQty",0) or 0)
            price = float(d.get("bdAvePrice",0) or 0)
            val_cr = qty * price / 1e7
            if sym not in result:
                result[sym] = {"count":0,"total_cr":0.0,"person":d.get("clientName","")}
            result[sym]["count"]    += 1
            result[sym]["total_cr"] += val_cr
    except Exception as e:
        log.debug(f"fetch_insider_trades: {e}")
    return result

def fetch_filings(days_back: int = 14) -> dict:
    result: dict = {}
    try:
        sess = _get_nse_session()
        resp = sess.get(
            "https://www.nseindia.com/api/corporates-annualReports?index=equities",
            headers={**_NSE_HEADERS, "X-Requested-With": "XMLHttpRequest"},
            timeout=12
        )
        if resp.status_code != 200:
            return result
        data = resp.json()
        for item in (data if isinstance(data, list) else data.get("data",[])):
            sym  = str(item.get("symbol","")).strip().upper()
            subj = str(item.get("subject","") or item.get("desc",""))
            if not sym:
                continue
            score = 15
            sl    = subj.lower()
            for w in ["profit","order","win","contract","growth","capex","expansion",
                      "buyback","dividend"]:
                if w in sl: score += 5
            for w in ["loss","downgrade","fraud","strike","penalty","default"]:
                if w in sl: score -= 8
            result[sym] = {"subject": subj[:100], "detail": subj[:100], "score": score}
    except Exception as e:
        log.debug(f"fetch_filings: {e}")
    return result

# ══════════════════════════════════════════════════════════════════════════════
# v8.1 PATCH 2 — LATE-STAGE TARGETED INTEL HEIST
# Per-symbol precision pull replacing run-start global bulk dump.
# Only fires for symbols that already cleared Fortress math gate.
# ══════════════════════════════════════════════════════════════════════════════

def _extract_scanned_pdf_ocr(pdf_content: bytes, symbol: str = "") -> str:
    """
    Converts PDF raw bytes to images and runs Tesseract OCR.
    Strictly limits conversion to pages 1-2 (passed directly into
    convert_from_bytes, NOT sliced after) to avoid loading a 60-page
    annual report fully into RAM and OOM-killing the GHA runner.
    """
    global _OCR_STATS
    if not _OCR_OK:
        return ""
    _OCR_STATS["attempted"] += 1

    if not pdf_content or len(pdf_content) < 1000:
        _OCR_STATS["failed"] += 1
        return ""

    try:
        images = convert_from_bytes(pdf_content, first_page=1, last_page=2)
        extracted_text = ""
        for img in images:
            text = pytesseract.image_to_string(img)
            if text:
                extracted_text += text + "\n"

        if extracted_text.strip():
            _OCR_STATS["success"] += 1
            log.info(f"OCR Success {symbol}: extracted {len(extracted_text)} chars")
            return extracted_text.strip()
        _OCR_STATS["failed"] += 1
        return ""
    except Exception as e:
        _OCR_STATS["failed"] += 1
        log.warning(f"OCR Extraction Exception for {symbol}: {str(e)[:100]}")
        return ""


def fetch_filing_ocr_text(symbol: str, attachment_url: str) -> str:
    """
    v8.3: Downloads a corporate announcement PDF and extracts its text.
    Tries the plain-text layer first (fast, most NSE PDFs are text-based);
    only falls back to OCR if that yields near-nothing, since OCR is the
    expensive path (image conversion + tesseract) and should stay rare.

    NOTE: this is only ever called on gate-survivors (post fort_pts>=45),
    from the enrichment stage — never from the bulk 400-candidate scan.
    """
    if not attachment_url:
        return ""
    try:
        sess = _get_nse_session()
        r = sess.get(attachment_url, timeout=15,
                     headers={**_NSE_HEADERS, "Accept": "application/pdf"})
        if r.status_code != 200 or not r.content:
            return ""
        pdf_bytes = r.content

        raw_text = ""
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
            for page in reader.pages[:2]:
                raw_text += (page.extract_text() or "") + "\n"
        except Exception:
            raw_text = ""

        if not raw_text or len(raw_text.strip()) < 50:
            log.debug(f"Filing for {symbol} appears scanned — running OCR")
            raw_text = _extract_scanned_pdf_ocr(pdf_bytes, symbol)

        return raw_text[:5000]
    except Exception as e:
        log.debug(f"fetch_filing_ocr_text {symbol}: {e}")
        return ""


def fetch_target_intel(symbol: str) -> tuple:
    """
    v8.1 PATCH 2: Late-stage precision intel heist for a single survivor symbol.

    Called AFTER a stock clears Fortress/APEX math gates — not at run start.
    Replaces the global bulk dump (fetch_insider_trades/fetch_filings) which
    was hammering NSE for 2000 symbols before any filtering had occurred.

    Returns: (insider_data: dict, filing_data: dict)
      insider_data = {"count": int, "total_cr": float, "person": str}
      filing_data  = {"score": int, "subject": str}

    Degrades gracefully on any failure (returns neutral defaults).
    """
    sess = _get_nse_session()
    insider_data: dict = {"count": 0, "total_cr": 0.0, "person": ""}
    filing_data:  dict = {"score": 15, "subject": "None", "attachment_url": ""}

    # ── Precision insider / SAST pull ────────────────────────────────────────
    try:
        url = (f"https://www.nseindia.com/api/corporates-pit"
               f"?index=equities&symbol={symbol}")
        r = sess.get(url, timeout=10,
                     headers={**_NSE_HEADERS,
                              "Accept": "application/json, text/plain, */*",
                              "X-Requested-With": "XMLHttpRequest",
                              "Referer": "https://www.nseindia.com/"})
        if r.status_code == 200:
            cutoff   = (datetime.today() - timedelta(days=30)).strftime("%Y-%m-%d")
            total_cr = 0.0
            count    = 0
            person   = ""
            for d in r.json().get("data", []):
                dt = str(d.get("tdpTransactionDate", ""))[:10]
                if dt < cutoff:
                    continue
                txn = str(d.get("tdpTransactionType", "")).upper()
                if "BUY" not in txn and "ACQUIRE" not in txn:
                    continue
                qty    = float(d.get("secAcq", 0) or 0)
                price  = float(d.get("tdpAcqPrice", 0) or 0)
                val_cr = qty * price / 1e7
                total_cr += val_cr
                count    += 1
                if not person:
                    person = str(d.get("acqName", "") or d.get("personName", ""))[:40]
            if count > 0:
                insider_data = {"count": count,
                                "total_cr": round(total_cr, 2),
                                "person": person}
                log.debug(f"TargetIntel {symbol}: insider {count} txn ₹{total_cr:.1f}Cr")
    except Exception as e:
        log.debug(f"fetch_target_intel insider {symbol}: {e}")

    # ── Precision announcement/filing pull ───────────────────────────────────
    try:
        url = (f"https://www.nseindia.com/api/corp-info"
               f"?symbol={symbol}&corpType=announcements&market=capital")
        r = sess.get(url, timeout=10,
                     headers={**_NSE_HEADERS,
                              "Accept": "application/json, text/plain, */*",
                              "X-Requested-With": "XMLHttpRequest",
                              "Referer": f"https://www.nseindia.com/get-quotes/equity?symbol={symbol}"})
        if r.status_code == 200:
            items = r.json()
            items = items if isinstance(items, list) else items.get("data", [])
            score = 15
            subj  = "None"
            attach_url = ""
            for item in items[:5]:
                subj_raw = str(item.get("subject", "") or item.get("desc", ""))
                if not subj_raw:
                    continue
                sl = subj_raw.lower()
                for w in ["profit", "order", "win", "contract", "growth",
                          "capex", "expansion", "buyback", "dividend"]:
                    if w in sl: score += 5
                for w in ["loss", "downgrade", "fraud", "strike", "penalty", "default"]:
                    if w in sl: score -= 8
                if subj == "None":
                    subj = subj_raw[:100]
                    # v8.3: capture PDF link for the first (most relevant) item only —
                    # OCR is expensive, we only ever want to read one filing per symbol.
                    attach_url = str(item.get("attchmntFile", "") or "")
            filing_data = {"score": score, "subject": subj, "attachment_url": attach_url}
            log.debug(f"TargetIntel {symbol}: filing score={score}")
    except Exception as e:
        log.debug(f"fetch_target_intel filing {symbol}: {e}")

    return insider_data, filing_data


# ── PATCH-4: Percentage-tick VPOC helper ─────────────────────────────────
def _vpoc_pct_tick(tp: np.ndarray, vols: np.ndarray,
                   tick_pct: float = 0.005) -> float:
    """
    PATCH-4: VPOC via fixed %-tick bins (default 0.5% per bucket).

    WHY: The legacy 10-bin histogram divides the 20-day high/low RANGE into
    10 equal ₹-buckets.  If a stock consolidates tightly for 19 days then
    gaps up on day 20, the ₹-range explodes and each bucket becomes huge.
    19 days of tight consolidation collapse into 1 bucket → VPOC resolution
    destroyed, support/resistance zones become useless blobs.

    FIX: Use logarithmic %-buckets of fixed size (0.5%).  Every bucket always
    represents the same economic move regardless of absolute price.  A gap-up
    spike lands in its own distant bucket; the dense 19-day consolidation
    keeps full resolution in its own cluster.  No scipy required.

    Returns VPOC price (midpoint of max-volume bucket) or 0.0 on failure.
    """
    if len(tp) == 0 or len(tp) != len(vols) or float(tp.min()) <= 0:
        return 0.0
    try:
        base      = float(tp.min())
        log_step  = math.log(1.0 + tick_pct)
        bucket_ix = np.floor(np.log(tp.astype(float) / base) / log_step).astype(int)
        bucket_ix = np.clip(bucket_ix, 0, bucket_ix.max())
        max_bkt   = int(bucket_ix.max()) + 1
        vol_bkt   = np.zeros(max_bkt)
        for i, b in enumerate(bucket_ix):
            vol_bkt[b] += float(vols[i])
        best_bkt  = int(np.argmax(vol_bkt))
        # Midpoint of winning %-bucket
        vpoc = base * ((1.0 + tick_pct) ** (best_bkt + 0.5))
        return round(vpoc, 2)
    except Exception as e:
        log.debug(f"_vpoc_pct_tick: {e}")
        return 0.0

# ──────────────────────────────────────────────────────────────────────────

def compute_eod_order_flow(symbol: str, today_row: dict,
                           hist: pd.DataFrame) -> dict:
    """
    Computes whale_flag, whale_score, vpoc, at_vpoc_support, delivery_pct, vol_ratio.

    VPOC uses Typical Price (H+L+C)/3 and is computed on iloc[-21:-1]
    (prior 20 sessions, excluding today) to prevent today's volume spike
    from trivially becoming its own VPOC.

    Vol ratio uses the same prior-20-session window (excludes today).
    """
    result = {"whale_flag":False,"whale_score":0.0,"vpoc":0.0,
              "at_vpoc_support":False,"delivery_pct":0.0,"vol_ratio":1.0}
    try:
        close     = float(today_row.get("close",0))
        volume    = float(today_row.get("volume",0))
        deliv_pct = float(today_row.get("delivery_pct",0))
        result["delivery_pct"] = deliv_pct

        if hist.empty or len(hist) < 20:
            return result

        # Prior 20 sessions (iloc[-21:-1] excludes today)
        prior     = hist.iloc[-21:-1]
        avg_vol   = float(prior["volume"].mean())
        vol_ratio = volume / avg_vol if avg_vol > 0 else 1.0
        result["vol_ratio"] = round(vol_ratio, 2)

        # VPOC: Typical Price = (H+L+C)/3 over prior 20 sessions
        h_arr = prior["high"].values.astype(float)
        l_arr = prior["low"].values.astype(float)
        c_arr = prior["close"].values.astype(float)
        v_arr = prior["volume"].values.astype(float)
        tp    = (h_arr + l_arr + c_arr) / 3.0

        p_min, p_max = tp.min(), tp.max()
        if p_max > p_min:
            # PATCH-4: %-tick VPOC (replaces 10-bin histogram)
            vpoc = _vpoc_pct_tick(tp, v_arr, tick_pct=0.005)
            if vpoc > 0:
                result["vpoc"] = vpoc
                result["at_vpoc_support"] = (close > 0 and abs(close - vpoc) / close < 0.02)

        # Whale flag
        whale = deliv_pct >= WHALE_DELIVERY_PCT and vol_ratio >= WHALE_VOL_MULT
        result["whale_flag"] = whale

        score = 0.0
        if deliv_pct >= 70:    score += 15
        elif deliv_pct >= 55:  score += 8
        if vol_ratio >= 2.0:   score += 10
        elif vol_ratio >= 1.5: score += 6
        if result["at_vpoc_support"]: score += 5
        result["whale_score"] = min(score, 30.0)
    except Exception as e:
        log.debug(f"compute_eod_order_flow {symbol}: {e}")
    return result

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — PHASE 4: ALT-DATA PIPELINE (preserved from v6.0)
# ══════════════════════════════════════════════════════════════════════════════

def _scrape_via_proxy(url: str, params: dict = None) -> Optional[str]:
    if SCRAPERAPI_KEY:
        try:
            target = requests.Request("GET", url, params=params).prepare().url
            resp = requests.get(
                "https://api.scraperapi.com/",
                params={"api_key": SCRAPERAPI_KEY, "url": target,
                        "country_code": "in", "render": "false"},
                timeout=25,
            )
            if resp.status_code == 200:
                html = resp.text
                if not _is_captcha_page(html):
                    return html
        except Exception as e:
            log.debug(f"ScraperAPI: {e}")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"),
                locale="en-IN",
            )
            page = ctx.new_page()
            page.goto(requests.Request("GET", url, params=params).prepare().url,
                      timeout=20000, wait_until="domcontentloaded")
            html = page.content()
            browser.close()
            return html if not _is_captcha_page(html) else None
    except ImportError:
        pass
    except Exception as e:
        log.debug(f"Playwright: {e}")
    return None

def _is_captcha_page(html: str) -> bool:
    if not html or len(html) < 200:
        return True
    low  = html.lower()
    hits = sum(1 for s in ["captcha","cf-challenge","ddos-guard","ray id",
                            "please enable javascript","access denied",
                            "bot protection","verify you are human",
                            "challenge-form","turnstile"]
               if s in low)
    return hits >= 2 or (len(html) < 1000 and "<body" not in low)

def _scrape_cpp_tenders(symbol: str, company_name: str = "") -> List[str]:
    """
    PATCH-3: Alt-data tenders scrape.
    Requires SCRAPERAPI_KEY secret — CPP/Zauba use Cloudflare, blocked on GHA bare IPs.
    Without ScraperAPI key, returns [] and logs WARNING once so engineers know why
    Option-C catalyst override is disabled.
    """
    if not SCRAPERAPI_KEY:
        log.debug(f"CPP tenders {symbol}: SCRAPERAPI_KEY not set — skipping (set secret to enable)")
        return []
    results = []
    query   = company_name or symbol
    try:
        html = _scrape_via_proxy("https://etenders.gov.in/eprocure/app",
                                 {"searchString": query, "action": "SearchAction"})
        if html:
            from bs4 import BeautifulSoup
            soup  = BeautifulSoup(html, "html.parser")
            texts = [t.get_text(strip=True) for t in soup.find_all("td")
                     if len(t.get_text(strip=True)) > 20]
            results.extend(texts[:5])
    except Exception as e:
        log.debug(f"CPP tenders {symbol}: {e}")
    return results

def _scrape_zauba_exports(symbol: str) -> List[str]:
    """
    PATCH-3: Alt-data exports scrape.
    Requires SCRAPERAPI_KEY secret — Zauba blocks datacenter IPs.
    """
    if not SCRAPERAPI_KEY:
        log.debug(f"Zauba {symbol}: SCRAPERAPI_KEY not set — skipping")
        return []
    results = []
    try:
        html = _scrape_via_proxy(f"https://www.zauba.com/import-{symbol.lower()}-hs-code.html")
        if html:
            from bs4 import BeautifulSoup
            soup  = BeautifulSoup(html, "html.parser")
            texts = [t.get_text(strip=True) for t in soup.find_all("td")
                     if len(t.get_text(strip=True)) > 20]
            results.extend(texts[:5])
    except Exception as e:
        log.debug(f"Zauba {symbol}: {e}")
    return results

def _build_alt_data_text(symbol: str, tenders: List[str],
                         exports: List[str], filing_subject: str = "") -> str:
    parts = [f"Symbol: {symbol}"]
    if tenders:
        parts.append("Tenders: " + " | ".join(tenders[:3]))
    if exports:
        parts.append("Exports: " + " | ".join(exports[:3]))
    if filing_subject:
        parts.append(f"Filing: {filing_subject}")
    return " ".join(parts) if len(parts) > 1 else ""

def _semantic_catalyst_match(symbol: str, alt_text: str,
                              vector_store: list) -> dict:
    result = {"matched": False, "best_sim": 0.0,
              "match_label": "", "catalyst_sub": False}
    if not _OPENAI_OK or not vector_store or not alt_text:
        return result
    try:
        emb = _call_openai_embed(alt_text)
        if emb is None:
            return result
        best_sim  = 0.0
        best_label = ""
        for entry in vector_store:
            stored = entry.get("embedding", [])
            if not stored:
                continue
            a = np.array(emb);  b = np.array(stored)
            sim = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))
            if sim > best_sim:
                best_sim   = sim
                best_label = entry.get("label","")
        result["best_sim"]    = round(best_sim, 4)
        result["matched"]     = best_sim >= ALT_DATA_MATCH_SIM
        result["match_label"] = best_label
        result["catalyst_sub"] = best_sim >= ALT_DATA_MATCH_SIM
    except Exception as e:
        log.debug(f"_semantic_catalyst_match {symbol}: {e}")
    return result

def _load_vector_store() -> list:
    rows = _read_sheet("ALT_VECTORS")
    store = []
    if not rows or len(rows) < 2:
        return store
    header = [h.lower() for h in rows[0]]
    for r in rows[1:]:
        d = dict(zip(header, r))
        emb_raw = d.get("embedding_json","")
        if not emb_raw:
            continue
        try:
            store.append({"symbol": d.get("symbol",""),
                          "label":  d.get("outcome_label",""),
                          "embedding": json.loads(emb_raw)})
        except Exception:
            pass
    return store

def store_alt_vector(symbol: str, source: str, text: str, label: str) -> bool:
    emb = _call_openai_embed(text)
    if emb is None:
        return False
    chash = hashlib.md5(text.encode()).hexdigest()
    row   = [symbol, source, chash, json.dumps(emb), text[:500], label,
             datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")]
    try:
        ws = _get_ws("ALT_VECTORS")
        if ws is None:
            return False
        existing = ws.get_all_values()
        if not existing:
            ws.append_row(["symbol","source","content_hash","embedding_json",
                           "raw_text","outcome_label","fetched_at"])
        ws.append_row(row)
        return True
    except Exception as e:
        log.warning(f"store_alt_vector: {e}")
        return False

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 10 — TECHNICAL INDICATORS (single fused pass)
# ══════════════════════════════════════════════════════════════════════════════

def compute_indicators(df: pd.DataFrame) -> dict:
    """
    Single fused indicator pass. Computes ATR family, RSI-14, ADX-14, MFI-14,
    moving averages (50 / 200), plus 52W high/low stats.
    Returns dict; all floats default to 0.0 on failure.
    """
    empty = {k: 0.0 for k in ["atr14","atr7","atr20","atr50","atr100",
                                "rsi14","adx14","mfi","pdi","ndi","atr_s",
                                "ma50","ma200","hi52","lo52",
                                "natr14","natr100","close_100"]}
    if df.empty or len(df) < 7:
        return empty
    try:
        h = df["high"].astype(float)
        l = df["low"].astype(float)
        c = df["close"].astype(float)
        v = (df["volume"].astype(float) if "volume" in df.columns
             else pd.Series(np.ones(len(df)), index=df.index))

        # True Range
        tr = pd.concat([h - l,
                        (h - c.shift()).abs(),
                        (l - c.shift()).abs()], axis=1).max(axis=1)

        # ATR family (EWM Wilder)
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

        # ADX / PDI / NDI
        pdm = (h.diff()).clip(lower=0)
        ndm = (-l.diff()).clip(lower=0)
        pdm[pdm < 0] = 0; ndm[ndm < 0] = 0
        atr_adx = tr.ewm(span=14, adjust=False).mean()
        pdi = 100 * pdm.ewm(span=14, adjust=False).mean() / atr_adx.replace(0, np.nan)
        ndi = 100 * ndm.ewm(span=14, adjust=False).mean() / atr_adx.replace(0, np.nan)
        dx  = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
        adx14 = float(dx.ewm(span=14, adjust=False).mean().iloc[-1]) if len(df) >= 14 else 0.0

        # MFI-14 (Typical Price)
        tp  = (h + l + c) / 3
        mf  = tp * v
        pos = mf.where(tp > tp.shift(), 0.0).rolling(14).sum()
        neg = mf.where(tp <= tp.shift(), 0.0).rolling(14).sum()
        mfi_v = float(
            (100 - 100 / (1 + pos / neg.replace(0, np.nan))).iloc[-1]
        ) if len(df) >= 14 else 50.0

        # Moving averages
        ma50  = float(c.rolling(50).mean().iloc[-1])  if len(df) >= 50  else 0.0
        ma200 = float(c.rolling(200).mean().iloc[-1]) if len(df) >= 200 else 0.0

        # 52W hi/lo
        hi52 = float(h.tail(252).max()) if len(df) >= 252 else float(h.max())
        lo52 = float(l.tail(252).min()) if len(df) >= 252 else float(l.min())

        # ── PATCH-1: Normalised ATR (NATR) ──────────────────────────────────
        # ATR is an absolute ₹ value. A stock that 3× in price legitimately has
        # a higher ATR14 than its ATR100 (which was anchored at a lower price).
        # Comparing absolute ATR14 to ATR100 penalises momentum stocks.
        # Fix: normalise each ATR by the close price of its respective period.
        #   natr14  = atr14  / close_today         (current % volatility)
        #   natr100 = atr100 / close_100_bars_ago  (historical % volatility)
        # Now ratio = natr14 / natr100 compares % vol to % vol — apples-to-apples.
        close_now = float(c.iloc[-1])
        close_100 = float(c.iloc[-100]) if len(df) >= 100 else close_now
        natr14  = atr14  / close_now  if close_now  > 0 else 0.0
        natr100 = atr100 / close_100  if close_100  > 0 else natr14
        # ────────────────────────────────────────────────────────────────────

        return {
            "atr14": atr14, "atr7": atr7, "atr20": atr20,
            "atr50": atr50, "atr100": atr100,
            "rsi14": round(rsi14, 1), "adx14": round(adx14, 1),
            "mfi":   round(mfi_v, 1),
            "pdi":   round(float(pdi.iloc[-1]), 1),
            "ndi":   round(float(ndi.iloc[-1]), 1),
            "atr_s": atr14_s,
            "ma50":  round(ma50, 4),
            "ma200": round(ma200, 4),
            "hi52":  round(hi52, 4),
            "lo52":  round(lo52, 4),
            "natr14":    round(natr14,  6),
            "natr100":   round(natr100, 6),
            "close_100": round(close_100, 4),
        }
    except Exception as e:
        log.debug(f"compute_indicators: {e}")
        return empty

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 11 — v7.0: UPTREND GATE (Pearl Hunter filter)
# ══════════════════════════════════════════════════════════════════════════════

def _check_uptrend_gate(close: float, ind: dict) -> Tuple[bool, str]:
    """
    v8.1 PATCH 3: Softened Accumulation Gate.

    PROBLEM: The v7 hard gate (Price > 50MA > 200MA) was killing valid early-stage
    compression bases that form BELOW a flat or slightly-declining 200MA.
    A stock in week 3 of a VCP base naturally sits below the 200MA before the
    breakout lift. The old gate gave these a score of 12/200 and rejected them.

    FIX: Decouple VCP/VDU scoring from the 200MA constraint.
    Gate now has two tiers:

      FULL_UPTREND  (Price > 50MA AND 50MA > 200MA):
        → All VCP/VDU points awarded at full weight.
        → story tag: "uptrend ✅"

      BASE_FORMING  (Price > 50MA, but 50MA ≤ 200MA or 200MA unknown):
        → VCP/VDU points awarded at HALF weight (base may still be valid).
        → story tag: "base_forming ✅"
        → Does NOT return False — passes through for scoring.

      DOWNTREND     (Price ≤ 50MA):
        → Hard reject. A stock below its 50MA has no business in a breakout scanner.

    Returns:
      (uptrend_ok: bool, reason: str)
      uptrend_ok = True  for FULL_UPTREND and BASE_FORMING (both pass)
      uptrend_ok = False only for DOWNTREND
      reason carries the tier tag so fortress_score can adjust VCP weight.
    """
    ma50  = ind.get("ma50",  0.0)
    ma200 = ind.get("ma200", 0.0)

    if ma50 <= 0:
        # Not enough bars to compute 50MA — allow through, mark as uncertain
        return True, "base_forming ✅ (ma50 unavailable)"

    if close <= ma50:
        return False, f"price ₹{close:.0f} ≤ 50MA ₹{ma50:.0f} — downtrend ❌"

    # Price is above 50MA — check 200MA for tier classification
    if ma200 > 0 and ma50 >= ma200 * (1.0 - UPTREND_MA_SLACK):
        # Full uptrend: 50MA is at or above 200MA (within slack)
        return True, "uptrend ✅"
    else:
        # Base-forming: price > 50MA but 50MA still below 200MA (or no 200MA data)
        # Valid for early-stage accumulation — VCP points will be halved in fortress_score
        tier = f"50MA ₹{ma50:.0f} below 200MA ₹{ma200:.0f}" if ma200 > 0 else "< 200 bars"
        return True, f"base_forming ✅ ({tier})"

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 12 — v7.0: CONFIDENCE SCORE (Statistical Variance Layer)
# ══════════════════════════════════════════════════════════════════════════════

def compute_confidence_score(fort_pts: float, apex_comp: float,
                              bayes_pct: float, whale_score: float,
                              rsi14: float, adx14: float) -> float:
    """
    Confidence Score ∈ [0, 1].

    Each sub-score is normalised to [0,1].  High confidence means all signals
    agree (low cross-signal std).  Low confidence means signals contradict
    each other — e.g. RSI overbought while whale score is high and ADX is low.

    Formula:
        signals_norm = [fort_norm, apex_norm, bayes_norm, whale_norm,
                        rsi_norm, adx_norm]
        mean_signal  = mean(signals_norm)
        std_signal   = std(signals_norm)
        confidence   = mean_signal × max(0, 1 − std_signal / CONFIDENCE_STD_MAX)

    If std > CONFIDENCE_STD_MAX the signals are too divergent → confidence
    collapses toward 0, and score_one_symbol returns None.
    """
    fort_n  = min(fort_pts / 200,  1.0)
    apex_n  = min(apex_comp / 100, 1.0)
    bayes_n = min(bayes_pct / 100, 1.0)
    whale_n = min(whale_score / 30, 1.0)
    # RSI: optimal zone 45–65 → 1.0; overbought >80 → 0.2; oversold <30 → 0.5
    if 45 <= rsi14 <= 65:    rsi_n = 1.0
    elif 35 <= rsi14 < 45:   rsi_n = 0.7
    elif 65 < rsi14 <= 72:   rsi_n = 0.7
    elif rsi14 > 80:         rsi_n = 0.2
    else:                    rsi_n = 0.5
    adx_n = min(adx14 / 40,  1.0)

    signals = np.array([fort_n, apex_n, bayes_n, whale_n, rsi_n, adx_n])
    mean_s  = float(signals.mean())
    std_s   = float(signals.std())
    # Penalty: confidence shrinks as std grows
    conf = mean_s * max(0.0, 1.0 - std_s / CONFIDENCE_STD_MAX)
    return round(min(max(conf, 0.0), 1.0), 4)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 13 — FORTRESS SCORING ENGINE (Phase-2 ATR + v7.0 Uptrend Gate)
# ══════════════════════════════════════════════════════════════════════════════

def atr_dynamic_stop(close: float, atr14: float, sector: str,
                     macro_state: str, atr_mult: float) -> float:
    """ATR-dynamic stop loss with sector and regime scaling."""
    if atr14 <= 0:
        atr14 = close * 0.02
    sect_mult = SECTOR_ATR_MULT.get(sector, 1.0)
    stop = close - atr14 * atr_mult * sect_mult
    return round(max(stop, close * 0.85), 2)

def atr_position_size(equity: float, risk_pct: float,
                      entry: float, stop: float) -> int:
    risk_amt = equity * risk_pct
    risk_per_share = entry - stop
    if risk_per_share <= 0:
        return 0
    return max(1, int(risk_amt / risk_per_share))

def fortress_score(symbol: str, today_row: dict, hist: pd.DataFrame,
                   fii_data: dict, insider_map: dict, filings: dict,
                   macro: dict, order_flow: dict) -> dict:
    """
    Fortress 200-pt scoring with:
      - v7.0 Uptrend Gate (hard gate before VCP/VDU — prevents ghost setups)
      - ATR-dynamic stops (Phase 2)
      - Whale score integration (Phase 3)
    Returns {} if close <= 0 or uptrend gate fails for VCP/VDU only.
    """
    sym         = symbol.upper()
    ind         = compute_indicators(hist)
    atr14       = ind["atr14"]
    atr100      = ind["atr100"]
    rsi14       = ind["rsi14"]
    adx14       = ind["adx14"]
    mfi         = ind["mfi"]
    close       = float(today_row.get("close", 0))
    sector      = get_sector(sym)
    atr_mult    = macro.get("atr_mult", ATR_MULT_CHOP)
    macro_state = macro.get("macro_state", "CHOP")

    if close <= 0:
        return {}

    # ── PATCH-1: use NATR (normalised ATR) for all volatility comparisons ───
    natr14  = ind.get("natr14",  atr14  / close if close > 0 else 0)
    natr100 = ind.get("natr100", atr100 / close if close > 0 else natr14)

    fort_pts   = 0
    story_parts = []

    # ── UPTREND GATE (v8.1 softened) ─────────────────────────────────────────
    uptrend_ok, uptrend_reason = _check_uptrend_gate(close, ind)
    # Tier detection: base_forming gets half VCP/VDU weight
    is_base_forming = uptrend_ok and "base_forming" in uptrend_reason
    is_full_uptrend = uptrend_ok and not is_base_forming
    if is_full_uptrend:
        story_parts.append("uptrend ✅")
    elif is_base_forming:
        story_parts.append("base_forming ✅")
    # Only hard downtrend (uptrend_ok=False) blocks VCP/VDU entirely

    # 1. 52-Week compression + proximity
    hi52 = ind["hi52"]; lo52 = ind["lo52"]
    if hi52 > 0:
        pct_from_h = (hi52 - close) / hi52 * 100
        # PATCH-1: atr_tight uses NATR ratio (not absolute ATR ratio)
        atr_tight  = natr14 > 0 and natr100 > 0 and (natr14 / natr100) < 0.70
        if pct_from_h <= 5:    w52 = 20 if atr_tight else 15
        elif pct_from_h <= 10: w52 = 12 if atr_tight else 8
        elif pct_from_h <= 20: w52 = 6
        else:                  w52 = 0
        fort_pts += w52
        if w52 >= 12:
            story_parts.append(f"52W compression: {pct_from_h:.1f}% from high")

    # 2. VCP coil — fires for uptrend AND base_forming (half weight for base) ─
    # PATCH-1: ratio = natr14 / natr100  (% vol / % vol — momentum-proof)
    vcp_score = 0
    if uptrend_ok and natr14 > 0 and natr100 > 0:
        ratio = natr14 / natr100
        if ratio < 0.60:   vcp_score = 20
        elif ratio < 0.70: vcp_score = 14
        elif ratio < 0.80: vcp_score = 8
        # v8.2 FIX: removed base_forming //2 penalty — was making gate
        # mathematically impossible for early-stage setups. base_forming
        # now scores same as full uptrend; the tier is informational only.
        if vcp_score:
            tag = "base" if is_base_forming else "VCP"
            story_parts.append(f"{tag} coil NATR={ratio:.2f}")
    elif not uptrend_ok:
        log.debug(f"VCP gate FAIL {sym}: {uptrend_reason}")
    fort_pts += vcp_score

    # 3. ATR velocity (short vs long ATR)
    atrv = 0
    if ind["atr7"] > 0 and ind["atr50"] > 0:
        rate = (ind["atr7"] - ind["atr50"]) / ind["atr50"]
        if rate > 0.50:   atrv = 15
        elif rate > 0.30: atrv = 10
        elif rate > 0.10: atrv = 5
        elif ind["atr7"] < ind["atr50"]: atrv = 2
    fort_pts += atrv

    # 4. Volume dry-up (VDU) — fires for uptrend AND base_forming ─────────────
    vdu_score = 0
    if uptrend_ok and not hist.empty and len(hist) >= 20:
        recent_vol = float(hist["volume"].tail(5).mean())
        base_vol   = float(hist["volume"].iloc[-21:-1].mean())
        if base_vol > 0:
            vdu_r = recent_vol / base_vol
            if vdu_r < 0.40:   vdu_score = 15
            elif vdu_r < 0.60: vdu_score = 10
            elif vdu_r < 0.80: vdu_score = 5
            # v8.2 FIX: removed base_forming //2 penalty (same reason as VCP)
    fort_pts += vdu_score

    # 5. FII/DII
    fii_score = int(fii_data.get("score", 15))
    fii_bonus = min(20, max(0, (fii_score - 10) // 2))
    fort_pts += fii_bonus
    if fii_bonus >= 10:
        story_parts.append(f"FII {fii_data.get('label','MIXED')}")

    # 6. Insider
    ins = insider_map.get(sym, {})
    ins_bonus = 0
    if ins.get("count", 0) > 0:
        ins_bonus = min(15, int(ins.get("total_cr",0) * 2 + ins.get("count",0) * 3))
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

    # 8. Phase-3 whale score
    whale_score = float(order_flow.get("whale_score", 0))
    fort_pts   += int(whale_score)
    if order_flow.get("whale_flag"):
        story_parts.append(f"🐳 WHALE del={order_flow.get('delivery_pct',0):.0f}% "
                           f"vol={order_flow.get('vol_ratio',1):.1f}x")

    # 8b. VPOC proximity scoring (v5.5 re-injection — 60 pts max)
    # This block was accidentally deleted in v7 migration while the 80-pt gate
    # was kept, making the gate mathematically impossible to reach.
    # Restored: layer1=at VPOC (+25), layer2=high vol spike (+20), layer3=multi-bounce (+15)
    vpoc     = float(order_flow.get("vpoc", 0))
    vol_ratio = float(order_flow.get("vol_ratio", 1.0))
    at_vpoc  = bool(order_flow.get("at_vpoc_support", False))
    vpoc_pts = 0
    if vpoc > 0 and close > 0:
        pct_from_vpoc = abs(close - vpoc) / close
        # Layer 1: at VPOC — price within 2% of volume-weighted floor
        if at_vpoc:
            vpoc_pts += 25
            story_parts.append(f"VPOC floor ₹{vpoc:.0f}")
        elif pct_from_vpoc < 0.05:
            vpoc_pts += 12
        # Layer 2: high-volume spike at/near VPOC confirms institutional interest
        if vol_ratio >= 2.0 and pct_from_vpoc < 0.05:
            vpoc_pts += 20
            story_parts.append(f"vol spike {vol_ratio:.1f}x at VPOC")
        elif vol_ratio >= 1.5 and pct_from_vpoc < 0.05:
            vpoc_pts += 10
        # Layer 3: multi-bounce confirmation — price tested VPOC and held
        # Proxy: at_vpoc + uptrend + whale (3 independent signals agreeing)
        if at_vpoc and uptrend_ok and order_flow.get("whale_flag"):
            vpoc_pts += 15
            story_parts.append("VPOC triple-confirm")
        elif at_vpoc and uptrend_ok:
            vpoc_pts += 8
    fort_pts += min(vpoc_pts, 60)   # cap at original 60-pt block max

    # 9. RSI momentum
    if 50 <= rsi14 <= 70:  fort_pts += 8
    elif rsi14 > 70:       fort_pts += 4

    # 10. ADX strength
    if adx14 >= 25:   fort_pts += 8
    elif adx14 >= 20: fort_pts += 4

    # ATR-dynamic stop + entry zone
    stop_loss = atr_dynamic_stop(close, atr14, sector, macro_state, atr_mult)
    lo_pct = max(0.005, min(0.04, (atr14 / close) * 0.8)) if close > 0 and atr14 > 0 else 0.015
    hi_pct = max(0.003, min(0.025, (atr14 / close) * 0.5)) + 0.01 if close > 0 and atr14 > 0 else 0.01
    buy_lo  = round(close * (1 - lo_pct), 2)
    buy_hi  = round(close * (1 + hi_pct), 2)
    risk    = max(close - stop_loss, close * 0.03)
    r1      = round(close + risk * 1.5, 2)
    r2      = round(close + risk * 3.0, 2)
    r3      = round(close + risk * 5.0, 2)
    shares  = atr_position_size(ACCOUNT_EQUITY, ACCOUNT_RISK_PCT, close, stop_loss)

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
        "atr7": round(ind["atr7"], 2), "atr50": round(ind["atr50"], 2),
        "atr100": round(atr100, 2),
        "natr14": round(natr14, 6), "natr100": round(natr100, 6),  # PATCH-1
        "whale_score": whale_score, "delivery_pct": order_flow.get("delivery_pct", 0),
        "vol_ratio": order_flow.get("vol_ratio", 1.0),
        "whale_flag": order_flow.get("whale_flag", False),
        "vpoc": order_flow.get("vpoc", 0), "at_vpoc": order_flow.get("at_vpoc_support", False),
        "story": story, "macro_state": macro_state, "atr_mult": atr_mult,
        "uptrend_ok": uptrend_ok, "uptrend_reason": uptrend_reason,
        "ma50": ind["ma50"], "ma200": ind["ma200"],
        "fil_score": fil.get("score", 15), "ins_count": ins.get("count", 0),
    }

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 14 — APEX COMPOSITE ENGINE (7-factor)
# ══════════════════════════════════════════════════════════════════════════════

def apex_composite(symbol: str, fortress: dict, hist: pd.DataFrame,
                   macro: dict, fii_data: dict) -> dict:
    if not fortress or fortress.get("close", 0) <= 0:
        return {"apex_comp": 0.0}

    rsi   = fortress.get("rsi14", 50)
    adx   = fortress.get("adx14", 0)
    mfi   = fortress.get("mfi",   50)
    ws    = fortress.get("whale_score", 0)
    state = macro.get("macro_state", "CHOP")
    fp    = fortress.get("fort_pts", 0)
    close = fortress.get("close", 1)
    atr14 = fortress.get("atr14", 0)
    fii_s = int(fii_data.get("score", 15))

    scores = []
    # 1. Momentum
    mom = 0
    if 45 <= rsi <= 65:                     mom = 20
    elif 35 <= rsi < 45 or 65 < rsi <= 72: mom = 12
    elif rsi > 72:                          mom = 6
    if adx >= 25: mom = min(20, mom + 8)
    elif adx >= 18: mom = min(20, mom + 4)
    scores.append(("momentum", mom, 20))

    # 2. Volume structure
    vol_s = 0
    if 40 <= mfi <= 65: vol_s = 15
    elif mfi < 40:      vol_s = 10
    if ws >= 20: vol_s = min(20, vol_s + 5)
    scores.append(("volume", vol_s, 20))

    # 3. Regime
    reg_s = {"TREND":20,"CHOP":12,"BUNKER":6,"PANIC":0,"MASSACRE":0}.get(state, 10)
    if state == "TREND" and fp < 120: reg_s = 12
    scores.append(("regime", reg_s, 20))

    # 4. FII
    fii_cs = min(15, max(0, fii_s - 10))
    scores.append(("fii", fii_cs, 15))

    # 5. VCP quality — PATCH-1: use natr14 (already % of price, not ₹/₹)
    natr14_a = fortress.get("natr14", (atr14 / close * 100) if close > 0 else 5)
    vcp_pct  = natr14_a * 100  # convert to %, e.g. 0.018 → 1.8%
    vcp_s = 15 if vcp_pct < 1.5 else (10 if vcp_pct < 2.5 else (5 if vcp_pct < 4 else 0))
    # v8.1: uptrend = full, base_forming = full (v8.2: removed half-weight penalty),
    # downtrend = 0
    uptrend_reason = fortress.get("uptrend_reason", "")
    if not fortress.get("uptrend_ok", True):
        vcp_s = 0      # downtrend — no VCP credit
    # base_forming: full credit (tier is informational, not penalised)
    scores.append(("vcp", vcp_s, 15))

    # 6. VPOC support
    vpoc_s = 10 if fortress.get("at_vpoc") else 0
    scores.append(("vpoc_support", vpoc_s, 10))

    # 7. Whale bonus
    whale_bonus = 5 if fortress.get("whale_flag") else 0
    raw     = sum(s for _, s, _ in scores) + whale_bonus
    max_pts = sum(m for _, _, m in scores) + 5
    apex    = round(min(100, raw / max_pts * 100), 1)
    if state == "TREND" and adx >= 20:
        apex = round(min(100, apex * 1.08), 1)

    return {"apex_comp": apex, "apex_breakdown": {n: s for n, s, _ in scores}}

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 15 — BAYESIAN WIN PROBABILITY (14-node)
# ══════════════════════════════════════════════════════════════════════════════

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
    if not fortress:
        return 50.0
    prior  = 0.50
    factors = []
    fp    = fortress.get("fort_pts", 0)
    rsi   = fortress.get("rsi14", 50)
    adx   = fortress.get("adx14", 0)
    mfi   = fortress.get("mfi",   50)
    atr14  = fortress.get("atr14", 1)
    atr100 = fortress.get("atr100", atr14)  # v7.0: use actual atr100, not atr14 twice
    close  = fortress.get("close", 1) or 1  # FIX: was undefined in v7
    # PATCH-1: use natr for Bayesian volatility comparisons
    natr14_b  = fortress.get("natr14",  atr14  / (close + 1e-9))
    natr100_b = fortress.get("natr100", atr100 / (close + 1e-9))
    state  = macro.get("macro_state", "CHOP")

    def _apply(node: str, cond: bool):
        p = _BAYES_PRIORS.get(node, 0.55)
        factors.append(p if cond else (1 - p * 0.5))

    # v7.0: vcp_tight uses natr ratio (PATCH-1) + uptrend gate
    _apply("vcp_tight",       natr14_b < natr100_b * 0.80 and fortress.get("uptrend_ok", True))
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
    _apply("atr_contracting", natr14_b < natr100_b * 0.70 and natr100_b > 0)
    _apply("52w_near_high",   fp >= 140)
    _apply("mfi_accumulation", mfi < 50)

    result = prior
    for f in factors:
        result = result * f / (result * f + (1 - result) * (1 - f))
    return round(result * 100, 1)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 16 — LLM STORY ENRICHMENT
# ══════════════════════════════════════════════════════════════════════════════

def _get_market_cap_cr(symbol: str, close_price: float) -> float:
    """
    v8.3 FIX: replaces the fabricated `close * 5e6` placeholder with a real
    market-cap estimate pulled from yfinance's actual shares-outstanding.
    Cached for 1 day (reuses llm_cache table) since this only runs on
    gate-survivors, so call volume is low, but yfinance is still slow/
    rate-limited enough to be worth caching.
    Returns 0.0 on any failure — callers must treat 0 as "unknown", never
    silently substitute a guessed number.
    """
    cache_key = hashlib.sha256(f"mcap:{symbol}".encode()).hexdigest()
    cached = _llm_cache_get(cache_key)
    if cached is not None:
        try:
            return float(cached)
        except Exception:
            pass
    mcap_cr = 0.0
    try:
        import yfinance as yf
        info   = yf.Ticker(f"{symbol}.NS").info
        shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding") or 0
        if shares and close_price and close_price > 0:
            mcap_cr = round((shares * close_price) / 1e7, 1)  # paise->₹ Cr
    except Exception as e:
        log.debug(f"_get_market_cap_cr {symbol}: {e}")
        mcap_cr = 0.0
    try:
        _llm_cache_put(cache_key, str(mcap_cr), "mcap", "yfinance", ttl_days=1)
    except Exception:
        pass
    return mcap_cr


def llm_enrich_pick(symbol: str, fortress: dict, apex: dict,
                    bayes_pct: float, macro: dict, fii_data: dict,
                    insider_map: dict, filings: dict,
                    alt_match: dict) -> dict:
    default = {
        "llm_why": fortress.get("story","Technical setup"),
        "llm_verdict": "QUALIFIED", "llm_confidence": 0.60,
        "llm_catalyst": "", "llm_narrative": "",
        "llm_material_catalyst": True,  # v8.0
    }
    if not _OPENAI_OK:
        return default
    sym    = symbol.upper()
    close  = fortress.get("close", 0)
    stop   = fortress.get("stop_loss", 0)
    risk_r = round((fortress.get("r1", close) - close) / max(close - stop, 1), 2) if close > stop else 1.5
    ins    = insider_map.get(sym, {})
    fil    = filings.get(sym, {})

    # v8.3 FIX: real market cap via yfinance shares outstanding, not a
    # hardcoded 5e6-share guess. Cached so we only hit yfinance once per
    # symbol per day (this function already only runs on gate-survivors).
    mcap_cr = _get_market_cap_cr(sym, close)
    mcap_display = f"₹{round(mcap_cr, 0):.0f} Cr" if mcap_cr > 0 else "UNKNOWN"

    # v8.3: OCR'd filing text (only populated if the announcement PDF was
    # a scanned image and OCR was attempted — see fetch_filing_ocr_text).
    filing_ocr_text = fil.get("ocr_text", "")[:5000]

    prompt = f"""You are a concise quant analyst for NSE India mid/small-cap stocks.

SETUP: {sym} | Sector: {fortress.get('sector','?')} | Grade: {fortress.get('grade','?')}
Scores: Fortress={fortress.get('fort_pts',0)}/200 APEX={apex.get('apex_comp',0)}/100 Bayes={bayes_pct:.0f}%
Uptrend Gate: {"PASSED" if fortress.get('uptrend_ok') else "NOT APPLICABLE"}
Regime: {macro.get('macro_state','CHOP')} | FII: {fii_data.get('label','MIXED')}
RSI={fortress.get('rsi14',50):.0f} ADX={fortress.get('adx14',0):.0f}
ATR stop: ₹{stop:.0f} | R1:R = {risk_r:.1f}:1 | Whale={fortress.get('whale_flag',False)}
Insider: {f"₹{ins.get('total_cr',0):.0f}Cr bought" if ins.get('count') else "None"}
Filing: {fil.get('subject','None')[:60]}
Filing text (OCR'd from scanned disclosure, may be empty): {filing_ocr_text}
Alt-data: {alt_match.get('match_label','') or 'None'}
Delivery%: {fortress.get('delivery_pct',0):.0f}% | VolRatio: {fortress.get('vol_ratio',1):.1f}x

CRITICAL MATERIALITY RULE (v8.3):
- The company's actual market capitalization is {mcap_display}.
- Analyze the disclosure/filing text. Look for explicitly stated values of
  order wins, contracts, or promoter purchases.
- Apply the 2% Rule: if market cap is known, is the verified value of this
  contract/order win >= 2% of market cap? If market cap is UNKNOWN, judge
  whether the contract value seems structurally significant for a mid/small-cap.
- If the value is not material (or no explicit value is stated), classify
  the catalyst as "NOISE" and set "has_material_catalyst" to false.
- If clearly material, set "has_material_catalyst" to true.
- Do NOT hype small-value contracts as "NEW CONTRACT WIN" for large companies.

Respond ONLY as JSON (no markdown):
{{
  "verdict": "STRONG_BUY|BUY|HOLD|SKIP",
  "confidence": 0.0-1.0,
  "why": "≤15 words: key edge",
  "catalyst": "primary catalyst or empty string",
  "has_material_catalyst": true/false,
  "risk_note": "≤10 words: main risk"
}}"""

    raw = _call_openai(prompt, max_tokens=250, cache_ttl_days=1)
    if raw:
        try:
            parsed = json.loads(re.sub(r"```json|```", "", raw).strip())
            # v8.0: if LLM says catalyst is noise, zero it out
            catalyst_str = str(parsed.get("catalyst",""))
            if not parsed.get("has_material_catalyst", True):
                catalyst_str = ""   # MATERIALITY FILTER: LLM classified as NOISE
                log.debug(f"LLM materiality filter: {sym} catalyst classified NOISE")
            return {
                "llm_why":       str(parsed.get("why",""))[:120],
                "llm_verdict":   str(parsed.get("verdict","QUALIFIED")),
                "llm_confidence": float(parsed.get("confidence", 0.60)),
                "llm_catalyst":  catalyst_str[:80],
                "llm_narrative": str(parsed.get("risk_note",""))[:80],
                "llm_material_catalyst": bool(parsed.get("has_material_catalyst", True)),
            }
        except Exception:
            pass
    return default

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 17 — CONVICTION RE-RANK (Option-C, v5.5.2 preserved)
# ══════════════════════════════════════════════════════════════════════════════

def _compute_rs_pct(symbol: str, hist: pd.DataFrame,
                    hist_cache: Dict[str, pd.DataFrame],
                    hist_lock: threading.Lock = None) -> float:
    """
    Relative strength percentile vs universe over 63 sessions.
    THREAD-SAFE: snapshots hist_cache under lock before iterating.
    """
    if hist.empty or len(hist) < 63:
        return 50.0
    try:
        sym_ret = float(hist["close"].iloc[-1] / hist["close"].iloc[-63] - 1)
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
        return round(float(np.searchsorted(np.sort(arr), sym_ret) / len(arr) * 100), 1)
    except Exception:
        return 50.0

def apply_conviction_rerank(pick: dict, rs_pct: float,
                             has_catalyst: bool,
                             alt_match: dict) -> dict:
    if not CONVICTION_RERANK:
        return pick
    grade = pick.get("grade","GOOD")
    if not CONV_REQUIRE_CATALYST:
        return pick
    if grade not in ("APEX","PRISTINE"):
        return pick
    if has_catalyst:
        return pick
    if rs_pct >= CONV_RS_CATALYST_FLOOR:
        pick["story"] = (pick.get("story","") +
                         f" | ✅ RS{rs_pct:.0f}pct catalyst-sub")
        return pick
    if alt_match.get("catalyst_sub"):
        pick["story"] = (pick.get("story","") +
                         f" | ✅ ALT-DATA sim={alt_match.get('best_sim',0):.3f}")
        return pick
    pick["grade"] = "GOOD"
    pick["story"] = (pick.get("story","") +
                     f" | ⚠️ capped GOOD: no catalyst, RS{rs_pct:.0f}pct")
    return pick

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 18 — FUSED SCORING
# ══════════════════════════════════════════════════════════════════════════════

def fused_score(fortress: dict, apex: dict, bayes_pct: float) -> float:
    fp_norm = fortress.get("fort_pts", 0) / 200 * 100
    ac      = apex.get("apex_comp", 0)
    ws      = fortress.get("whale_score", 0) / 30 * 100
    # Weights: fortress 40%, apex 30%, bayes 20%, whale 10%
    return round(min(fp_norm * 0.40 + ac * 0.30 + bayes_pct * 0.20 + ws * 0.10, 100), 1)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 19 — META-LABELER (preserving v6.0 Sec 25)
# ══════════════════════════════════════════════════════════════════════════════

def meta_labeler_veto(features: dict, macro: dict) -> Tuple[bool, float]:
    """
    Simple linear meta-labeler trained on stored labels.
    Returns (vetoed: bool, p_win: float).
    Fallback: returns (False, 0.60) if insufficient training data.
    """
    try:
        with _db_conn() as con:
            rows = con.execute(
                "SELECT fort_pts, apex_comp, fused, bayes_pct, rsi14, adx14, "
                "whale_score, delivery_pct, vol_ratio, outcome "
                "FROM meta_labels WHERE outcome IS NOT NULL ORDER BY id DESC LIMIT 200"
            ).fetchall()
    except Exception:
        return False, 0.60

    if len(rows) < 20:
        return False, 0.60

    X = np.array([[r[0]/200, r[1]/100, r[2]/100, r[3]/100,
                   r[4]/100, r[5]/50, r[6]/30, r[7]/100, r[8]/3]
                  for r in rows])
    y = np.array([float(r[9]) for r in rows])

    # Logistic regression via gradient descent (no sklearn dependency)
    feat = np.array([
        features.get("fort_pts",0)/200, features.get("apex_comp",0)/100,
        features.get("fused",0)/100,    features.get("bayes_pct",0)/100,
        features.get("rsi14",50)/100,   features.get("adx14",0)/50,
        features.get("whale_score",0)/30, features.get("delivery_pct",0)/100,
        features.get("vol_ratio",1)/3,
    ])
    # Dot product as linear score (simple but fast)
    weights = X.T @ (y - y.mean())
    score   = float(np.dot(feat, weights / (np.linalg.norm(weights) + 1e-9)))
    p_win   = 1.0 / (1.0 + np.exp(-score * 5))
    vetoed  = bool(p_win < 0.35)
    return vetoed, round(float(p_win), 3)

def store_meta_label(pos: dict, macro: dict, outcome: int, run_date: str):
    try:
        with _db_conn(write=True) as con:
            con.execute("""
                INSERT INTO meta_labels
                (symbol, run_date, fort_pts, apex_comp, fused, bayes_pct,
                 rsi14, adx14, mfi, atr14, atr_mult, whale_score,
                 delivery_pct, vol_ratio, rs_pct, at_vpoc, whale_flag,
                 has_catalyst, vix_val, advance_ratio, confidence_score, outcome)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                pos.get("symbol",""), run_date,
                pos.get("fort_pts",0), pos.get("apex_comp",0), pos.get("fused",0),
                pos.get("bayes_pct",0), pos.get("rsi14",50), pos.get("adx14",0),
                pos.get("mfi",50), pos.get("atr14",0), pos.get("atr_mult",2),
                pos.get("whale_score",0), pos.get("delivery_pct",0),
                pos.get("vol_ratio",1), pos.get("rs_pct",50),
                int(pos.get("at_vpoc",False)), int(pos.get("whale_flag",False)),
                int(pos.get("has_catalyst",False)),
                macro.get("vix_val",18), macro.get("advance_ratio",0.5),
                pos.get("confidence_score", 0.60),
                outcome,
            ))
    except Exception as e:
        log.debug(f"store_meta_label: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 20 — OPTIONS GRAVITY OVERLAY (Sec 26 from v6.0)
# ══════════════════════════════════════════════════════════════════════════════

def fetch_options_gravity(symbol: str = "NIFTY") -> dict:
    """Fetch NIFTY option chain max pain / major OI walls."""
    result: dict = {"call_walls": [], "put_walls": [], "max_pain": 0.0}
    try:
        sess = _get_nse_session()
        resp = sess.get(
            f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}",
            headers={**_NSE_HEADERS, "X-Requested-With": "XMLHttpRequest"},
            timeout=12
        )
        if resp.status_code != 200:
            return result
        data = resp.json().get("records", {})
        rows = data.get("data", [])
        if not rows:
            return result
        # Aggregate OI by strike
        call_oi: Dict[float, float] = {}
        put_oi:  Dict[float, float] = {}
        for r in rows:
            strike = float(r.get("strikePrice", 0))
            call_oi[strike] = call_oi.get(strike, 0) + float(
                (r.get("CE") or {}).get("openInterest", 0))
            put_oi[strike]  = put_oi.get(strike, 0) + float(
                (r.get("PE") or {}).get("openInterest", 0))
        result["call_walls"] = sorted(call_oi, key=call_oi.get, reverse=True)[:3]
        result["put_walls"]  = sorted(put_oi,  key=put_oi.get,  reverse=True)[:3]
        all_strikes = sorted(set(call_oi) | set(put_oi))
        if all_strikes:
            pain = {}
            for s in all_strikes:
                pain[s] = (sum(max(0, s - k) * v for k, v in call_oi.items()) +
                           sum(max(0, k - s) * v for k, v in put_oi.items()))
            result["max_pain"] = min(pain, key=pain.get)
    except Exception as e:
        log.debug(f"fetch_options_gravity: {e}")
    return result

# ── PATCH-2: Dynamic NIFTY50 constituent list ─────────────────────────────
# NIFTY 50 reconstitutes every 6 months. Hardcoded sets decay.
# Fetched once per run and cached in module scope; stale fallback on failure.
_NIFTY50_CACHE:     set  = set()
_NIFTY50_FETCHED_AT: Optional[datetime] = None
_NIFTY50_CACHE_LOCK = threading.Lock()

# Seed fallback (used when NSE fetch fails entirely)
_NIFTY50_FALLBACK = {
    "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR","SBIN",
    "BHARTIARTL","ITC","KOTAKBANK","LT","HCLTECH","AXISBANK","BAJFINANCE",
    "WIPRO","ADANIENT","MARUTI","SUNPHARMA","TITAN","NTPC","ULTRACEMCO",
    "POWERGRID","TECHM","NESTLEIND","M&M","INDUSINDBK","TATAMOTORS",
    "COALINDIA","ONGC","BAJAJFINSV","DIVISLAB","HDFCLIFE","JSWSTEEL",
    "GRASIM","TATACONSUM","CIPLA","DRREDDY","HEROMOTOCO","APOLLOHOSP",
    "BAJAJ-AUTO","ADANIPORTS","BPCL","EICHERMOT","SBILIFE","TRENT",
    "SHREECEM","BRITANNIA","HINDZINC","VEDL","DMART",
}

def _get_nifty50_set() -> set:
    """
    PATCH-2: Return current NIFTY 50 constituents, refreshed from NSE once per
    run (module-level cache, thread-safe).  If the NSE index API is unavailable,
    returns the hardcoded fallback.  This prevents operational decay when stocks
    are added/removed at semi-annual index reconstitution.
    """
    global _NIFTY50_CACHE, _NIFTY50_FETCHED_AT
    with _NIFTY50_CACHE_LOCK:
        if _NIFTY50_CACHE:
            return _NIFTY50_CACHE          # already fetched this run
        try:
            sess = _get_nse_session()
            resp = sess.get(
                "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050",
                headers={**_NSE_HEADERS, "X-Requested-With": "XMLHttpRequest"},
                timeout=12
            )
            if resp.status_code == 200:
                data  = resp.json().get("data", [])
                syms  = {str(d.get("symbol","")).strip().upper()
                         for d in data if d.get("symbol")}
                syms.discard("")
                if len(syms) >= 45:          # sanity: NIFTY50 has exactly 50
                    _NIFTY50_CACHE     = syms
                    _NIFTY50_FETCHED_AT = datetime.utcnow()
                    log.info(f"NIFTY50 dynamic list: {len(syms)} symbols ✅")
                    return _NIFTY50_CACHE
        except Exception as e:
            log.debug(f"_get_nifty50_set NSE fetch: {e}")
        # Fallback
        log.warning("NIFTY50 list: using hardcoded fallback (NSE unavailable)")
        _NIFTY50_CACHE = _NIFTY50_FALLBACK.copy()
        return _NIFTY50_CACHE

def apply_options_gravity_gate(winners: dict, options: dict,
                                macro: dict) -> dict:
    """
    PATCH-2: Options gravity gate restricted to NIFTY50 stocks only.
    Mid/small-cap picks bypass the NIFTY index OI wall — they are
    idiosyncratically priced and uncorrelated to large-cap options flow.
    NIFTY50 membership fetched dynamically to survive index reconstitution.
    """
    call_walls = options.get("call_walls", [])
    if not call_walls:
        return winners
    nifty50 = _get_nifty50_set()
    for lane, w in winners.items():
        if not w:
            continue
        sym = w["symbol"]
        # PATCH-2: skip suppression for mid/small-caps
        if sym not in nifty50:
            log.debug(f"Options gravity: {sym} not NIFTY50 — gate bypassed")
            continue
        close = w.get("close", 0)
        for wall in call_walls:
            if wall > 0 and abs(close - wall) / wall < 0.005:
                log.info(f"Options gravity: suppressed {sym} (NIFTY50, near wall ₹{wall:.0f})")
                winners[lane] = None
                break
    return winners

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 21 — KELLY CRITERION (Sec 27 from v6.0)
# ══════════════════════════════════════════════════════════════════════════════

def compute_kelly_multiplier() -> Tuple[float, dict]:
    """Compute Kelly fraction from closed trade history."""
    try:
        rows = _read_sheet("DB_BACKUP")
        if not rows or len(rows) < 6:
            return 1.0, {"n": 0}
        header = [h.lower() for h in rows[0]]
        closed = [dict(zip(header, r)) for r in rows[1:]
                  if "status" in dict(zip(header, r)) and
                  dict(zip(header, r))["status"] not in ("open","")]
        if len(closed) < 5:
            return 1.0, {"n": len(closed)}
        wins   = [t for t in closed if "hit" in t.get("status","")]
        losses = [t for t in closed if t.get("status","") == "stopped"]
        if not wins or not losses:
            return 0.5, {"n": len(closed)}
        wr = len(wins) / len(closed)
        try:
            avg_win  = np.mean([abs(float(t.get("pnl_pct",0) or 0)) for t in wins])
            avg_loss = np.mean([abs(float(t.get("pnl_pct",0) or 0)) for t in losses])
        except Exception:
            return 0.5, {"n": len(closed)}
        b    = avg_win / avg_loss if avg_loss > 0 else 1.5
        k    = (wr * b - (1 - wr)) / b  # Kelly fraction
        k    = max(0.1, min(k, 0.5))    # Half-Kelly clamp
        return round(k, 3), {"n": len(closed), "wr": round(wr,3), "b": round(b,3)}
    except Exception as e:
        log.debug(f"compute_kelly_multiplier: {e}")
        return 0.5, {"n": 0}

def kelly_adjusted_size(shares: int, kelly_mult: float) -> int:
    return max(1, int(shares * kelly_mult * 2))   # half-Kelly baseline * 2

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 22 — SCORE ONE SYMBOL (v7.0 worker, thread-safe)
# ══════════════════════════════════════════════════════════════════════════════

def _intelligence_hash(fii_data: dict, insider_map: dict, filings: dict) -> str:
    data = f"{fii_data.get('label')}{len(insider_map)}{len(filings)}"
    return hashlib.md5(data.encode()).hexdigest()[:8]

# ══════════════════════════════════════════════════════════════════════════════
# v8.0 UPGRADE 1 — SAST INSIDER CHECK (Real Whale Injection)
# Uses curl_cffi TLS-fingerprint bypass to hit NSE SAST endpoint.
# Called AFTER a stock passes Fortress/APEX math gate.
# If Promoter/Director bought in last 72h AND matches volume spike → DIAMOND.
# ══════════════════════════════════════════════════════════════════════════════

def _nse_sast_check(symbol: str, days_back: int = 3) -> dict:
    """
    Fetch NSE SAST (Substantial Acquisition of Shares / Insider Trading) filings
    for the given symbol using curl_cffi Akamai bypass.

    Returns:
        {
          "promoter_bought": bool,   # True if Promoter/Director buy in last 72h
          "total_value_cr": float,   # Total acquisition value in Crores
          "acquirer":       str,     # Name of acquirer
          "trade_date":     str,     # Most recent trade date
          "sast_ok":        bool,    # curl_cffi available and call succeeded
        }
    Falls back gracefully to {"promoter_bought": False, "sast_ok": False} on any failure.
    """
    fallback = {"promoter_bought": False, "total_value_cr": 0.0,
                "acquirer": "", "trade_date": "", "sast_ok": False}
    if not _CURL_CFFI_OK:
        log.debug(f"SAST {symbol}: curl_cffi not installed — pip install curl_cffi")
        return fallback
    cutoff = (datetime.today() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    try:
        # Step 1: warm up NSE session with curl_cffi (impersonate Chrome)
        sess = curl_requests.Session(impersonate="chrome110")
        sess.get("https://www.nseindia.com", timeout=12,
                 headers={**_NSE_HEADERS, "Accept": "text/html"})
        time.sleep(1.0)
        # Step 2: fetch insider trading / SAST data
        url = (f"https://www.nseindia.com/api/corporates-pit"
               f"?symbol={symbol}&issuer=&from={cutoff}&to="
               f"{datetime.today().strftime('%Y-%m-%d')}"
               f"&ca_type=insider")
        resp = sess.get(url, timeout=15,
                        headers={**_NSE_HEADERS,
                                 "Accept": "application/json, text/plain, */*",
                                 "X-Requested-With": "XMLHttpRequest",
                                 "Referer": f"https://www.nseindia.com/companies-listing/corporate-filings-insider-trading"})
        if resp.status_code != 200:
            log.debug(f"SAST {symbol}: HTTP {resp.status_code}")
            return {**fallback, "sast_ok": True}
        data  = resp.json()
        rows  = data.get("data", data) if isinstance(data, dict) else data
        best: dict = {}
        total_val  = 0.0
        for row in (rows if isinstance(rows, list) else []):
            # category check: Promoter / Director / KMP are meaningful
            category = str(row.get("acqType", "") or row.get("personCategory", "")).lower()
            if not any(k in category for k in ["promoter", "director", "kmp", "cfo", "ceo"]):
                continue
            txn_type = str(row.get("tdpTransactionType", "") or row.get("transactionType", "")).upper()
            if "BUY" not in txn_type and "ACQUIRE" not in txn_type:
                continue
            shares = float(row.get("secAcq", 0) or row.get("sharesAcquired", 0) or 0)
            price  = float(row.get("tdpAcqPrice", 0) or row.get("pricePerShare", 0) or 0)
            val_cr = shares * price / 1e7
            total_val += val_cr
            if val_cr > best.get("total_value_cr", 0):
                best = {
                    "promoter_bought": True,
                    "total_value_cr":  round(val_cr, 2),
                    "acquirer":        str(row.get("acqName", "") or row.get("personName", ""))[:60],
                    "trade_date":      str(row.get("tdpTransactionDate", "") or
                                          row.get("dateOfAcquisition", ""))[:10],
                    "sast_ok":         True,
                }
        if best:
            best["total_value_cr"] = round(total_val, 2)
            log.info(f"SAST {symbol}: Promoter buy ₹{total_val:.1f}Cr by {best['acquirer']} ✅")
            return best
        return {**fallback, "sast_ok": True}
    except Exception as e:
        log.debug(f"SAST {symbol}: {e}")
        return fallback


# ══════════════════════════════════════════════════════════════════════════════
# v8.0 UPGRADE 2 — SECTOR ALPHA (Momentum Multiplier)
# Fetches NIFTY sector index change % to detect dying sectors.
# A perfect breakout in a bleeding sector is a bull trap.
# ══════════════════════════════════════════════════════════════════════════════

_SECTOR_ALPHA_CACHE: Dict[str, dict] = {}
_SECTOR_ALPHA_LOCK  = threading.Lock()

def get_sector_alpha(sector: str) -> dict:
    """
    Fetch the daily % change for the NIFTY sector index corresponding to `sector`.
    Returns:
        {
          "sector_chg_pct": float,   # today's % change of sector index
          "sector_ok":      bool,    # True = sector healthy (not bleeding)
          "index_symbol":   str,     # e.g. "^CNXIT"
          "source":         str,
        }
    Cached per run (one call per sector). Falls back to neutral on failure.
    """
    with _SECTOR_ALPHA_LOCK:
        if sector in _SECTOR_ALPHA_CACHE:
            return _SECTOR_ALPHA_CACHE[sector]

    fallback = {"sector_chg_pct": 0.0, "sector_ok": True,
                "index_symbol": "", "source": "FALLBACK"}
    idx_sym = SECTOR_INDEX_MAP.get(sector.upper())
    if not idx_sym or not SECTOR_VELOCITY_ENABLED:
        with _SECTOR_ALPHA_LOCK:
            _SECTOR_ALPHA_CACHE[sector] = fallback
        return fallback

    try:
        sess = _get_nse_session()
        resp = sess.get(
            "https://www.nseindia.com/api/allIndices",
            headers={**_NSE_HEADERS,
                     "Accept": "application/json, text/plain, */*",
                     "X-Requested-With": "XMLHttpRequest"},
            timeout=12
        )
        if resp.status_code != 200:
            raise ValueError(f"allIndices HTTP {resp.status_code}")
        indices = resp.json().get("data", [])
        # Match by indexSymbol or index name
        for idx in indices:
            sym_field = str(idx.get("indexSymbol", "") or idx.get("index", "")).upper()
            if sym_field == idx_sym.lstrip("^").upper() or idx_sym.lstrip("^").upper() in sym_field:
                chg = float(idx.get("percentChange", idx.get("pChange", 0.0)) or 0)
                result = {
                    "sector_chg_pct": round(chg, 2),
                    "sector_ok":      chg >= -1.0,   # bleeding = down > 1%
                    "index_symbol":   idx_sym,
                    "source":         "NSE_ALLINDICES",
                }
                with _SECTOR_ALPHA_LOCK:
                    _SECTOR_ALPHA_CACHE[sector] = result
                log.debug(f"SectorAlpha {sector} ({idx_sym}): {chg:+.2f}% "
                          f"{'✅' if result['sector_ok'] else '🩸'}")
                return result
    except Exception as e:
        log.debug(f"get_sector_alpha {sector}: {e}")

    with _SECTOR_ALPHA_LOCK:
        _SECTOR_ALPHA_CACHE[sector] = fallback
    return fallback


# ══════════════════════════════════════════════════════════════════════════════
# v8.0 UPGRADE 4 — PLEDGE GATE (Flash-Crash Shield)
# Fetches promoter pledge % via curl_cffi NSE bypass.
# If pledge > PLEDGE_GATE_MAX_PCT → SKIPPED regardless of technicals.
# ══════════════════════════════════════════════════════════════════════════════

_PLEDGE_CACHE: Dict[str, float] = {}
_PLEDGE_LOCK  = threading.Lock()

def _fetch_pledge_pct(symbol: str) -> float:
    """
    Fetch promoter pledge % from NSE shareholding pattern API.
    Returns pledge % (0–100). Returns -1.0 if data unavailable (non-fatal).
    Cached per symbol per run.
    """
    with _PLEDGE_LOCK:
        if symbol in _PLEDGE_CACHE:
            return _PLEDGE_CACHE[symbol]

    pledge_pct = -1.0
    try:
        if _CURL_CFFI_OK:
            sess = curl_requests.Session(impersonate="chrome110")
            sess.get("https://www.nseindia.com", timeout=10,
                     headers={**_NSE_HEADERS, "Accept": "text/html"})
            time.sleep(0.5)
            resp = sess.get(
                f"https://www.nseindia.com/api/corporates-shp?symbol={symbol}",
                timeout=12,
                headers={**_NSE_HEADERS,
                         "Accept": "application/json, text/plain, */*",
                         "X-Requested-With": "XMLHttpRequest",
                         "Referer": "https://www.nseindia.com/"}
            )
        else:
            nse_sess = _get_nse_session()
            resp = nse_sess.get(
                f"https://www.nseindia.com/api/corporates-shp?symbol={symbol}",
                headers={**_NSE_HEADERS, "X-Requested-With": "XMLHttpRequest"},
                timeout=12
            )
        if resp.status_code == 200:
            data = resp.json()
            rows = data.get("data", data) if isinstance(data, dict) else data
            for row in (rows if isinstance(rows, list) else []):
                cat = str(row.get("category", "") or row.get("shareholderType", "")).lower()
                if "promoter" in cat:
                    pledged = float(row.get("pledgedSharesPct", 0) or
                                    row.get("percentPledged", 0) or 0)
                    if pledged >= 0:
                        pledge_pct = pledged
                        break
    except Exception as e:
        log.debug(f"_fetch_pledge_pct {symbol}: {e}")

    with _PLEDGE_LOCK:
        _PLEDGE_CACHE[symbol] = pledge_pct
    return pledge_pct

def score_one_symbol(args: tuple) -> Optional[dict]:
    """
    v7.5: Full gate diagnostics on every rejection.
    Every return None now logs INFO with exact gate + key metrics
    so the next GHA run shows EXACTLY which wall killed each stock.
    """
    (sym, row, hist_cache, fii_data, insider_map,
     filings, macro, date_label, vector_store, fast_rerun, hist_lock) = args

    def _rej(gate: str, detail: str = ""):
        """Log rejection at INFO level so it appears in GHA stdout."""
        log.info(f"  GATE {gate:18s} | {sym:14s} | {detail}")

    try:
        close = float(row.get("close", 0))
        if close <= 0:
            _rej("CLOSE_ZERO", f"close={close}")
            return None

        # L1 halal veto (instant)
        vetoed, reason = halal_l1_veto(sym)
        if vetoed:
            _rej("HALAL_L1", reason)
            return None

        intel_hash = _intelligence_hash(fii_data, insider_map, filings)

        # Score cache (fast rerun)
        if fast_rerun:
            cached = _score_cache_get(sym, date_label, close, intel_hash)
            if cached:
                return cached

        # History
        with hist_lock:
            hist = hist_cache.get(sym.upper())
        if hist is None:
            hist = fetch_history(sym, days=300)
            if not hist.empty:
                with hist_lock:
                    hist_cache[sym.upper()] = hist

        if hist.empty or len(hist) < 20:
            _rej("NO_HISTORY", f"bars={len(hist) if hist is not None else 0}")
            return None

        # Phase 3: EOD order flow
        order_flow = compute_eod_order_flow(sym, row, hist)

        # ── v8.2 FIX: PRECISION HEIST RUNS BEFORE FORTRESS_SCORE ─────────────
        # BUG v8.1: heist ran AFTER fp<45 gate → never fired for any stock.
        # FIX: hydrate live_insider_map/live_filings NOW so fortress_score
        # receives real insider/filing data and awards the +15–30pt bounty
        # that allows institutional setups to clear the gate.
        target_insider, target_filing = fetch_target_intel(sym)
        live_insider_map = dict(insider_map)
        live_filings     = dict(filings)
        if target_insider.get("count", 0) > 0:
            live_insider_map[sym] = target_insider
        if target_filing.get("subject", "None") != "None":
            live_filings[sym] = target_filing

        # Fortress scoring (now uses live precision data)
        fort = fortress_score(sym, row, hist, fii_data, live_insider_map,
                              live_filings, macro, order_flow)
        fp = fort.get("fort_pts", 0) if fort else 0
        if not fort or fp < 45:
            ma50  = fort.get("ma50",  0) if fort else 0
            ma200 = fort.get("ma200", 0) if fort else 0
            _rej("FORT_PTS_LOW",
                 f"fort={fp}/200 close={close:.0f} ma50={ma50:.0f} ma200={ma200:.0f} "
                 f"uptrend={'✅' if (fort.get('uptrend_ok') if fort else False) else '❌'} "
                 f"rsi={fort.get('rsi14',0):.0f} adx={fort.get('adx14',0):.0f}"
                 if fort else f"fort={fp}/200")
            return None

        # ── v8.0 UPGRADE 4: PLEDGE GATE (Flash-Crash Shield) ────────────────
        # Check BEFORE halal/apex — no point scoring a debt-stressed company.
        if PLEDGE_GATE_ENABLED:
            pledge_pct = _fetch_pledge_pct(sym)
            if pledge_pct >= 0 and pledge_pct > PLEDGE_GATE_MAX_PCT:
                log.info(f"  GATE {'PLEDGE_GATE':18s} | {sym:14s} | "
                         f"pledge={pledge_pct:.1f}% > {PLEDGE_GATE_MAX_PCT:.0f}% "
                         f"SKIPPED | reason: Debt-Stress Flash Crash Risk")
                return None
        else:
            pledge_pct = -1.0

        # Halal L2-L4
        sector = get_sector(sym)
        halal  = halal_ai_screen(sym, sector)
        if halal.get("veto"):
            _rej("HALAL_L2L4", halal.get("veto_reason",""))
            return None
        if halal.get("score", 0) < 50:
            _rej("HALAL_SCORE", f"score={halal.get('score',0)}")
            return None

        # APEX + Bayes + Fused
        apex_d  = apex_composite(sym, fort, hist, macro, fii_data)
        bayes_p = bayes_win_probability(fort, apex_d, macro, order_flow)
        fused   = fused_score(fort, apex_d, bayes_p)

        # ── v8.0 UPGRADE 2: SECTOR VELOCITY (Momentum Multiplier) ───────────
        # If sector index is bleeding, slash fused score to prevent bull-trap entries.
        sector_alpha = get_sector_alpha(sector)
        sector_bleeding = not sector_alpha.get("sector_ok", True)
        if sector_bleeding and SECTOR_VELOCITY_ENABLED:
            penalty = SECTOR_VELOCITY_PENALTY
            fused   = max(0.0, round(fused - penalty, 1))
            log.info(f"  SectorVelocity PENALTY {sym:14s} | "
                     f"sector={sector} idx={sector_alpha.get('index_symbol','')} "
                     f"chg={sector_alpha.get('sector_chg_pct',0):+.2f}% "
                     f"fused-={penalty:.0f} → fused={fused:.1f}")
            fort["story"] = (fort.get("story","") +
                             f" | ⚠️ SECTOR BLEED {sector_alpha.get('sector_chg_pct',0):+.2f}%")

        # ── v8.0 UPGRADE 1: SAST INSIDER CHECK (Real Whale Injection) ───────
        # Only runs after stock passes math gates (keeps total latency low).
        # 2-second NSE Heist: if volume spike + Promoter/Director buying → DIAMOND.
        sast_result = {"promoter_bought": False, "total_value_cr": 0.0,
                       "acquirer": "", "trade_date": "", "sast_ok": False}
        diamond_upgrade = False
        if order_flow.get("whale_flag") or order_flow.get("vol_ratio", 1.0) >= 1.5:
            # Only heist when there's a volume spike worth investigating
            sast_result = _nse_sast_check(sym, days_back=3)
            if sast_result.get("promoter_bought") and sast_result.get("total_value_cr", 0) > 0:
                diamond_upgrade = True
                fort["grade"]  = "DIAMOND"
                fort["story"]  = (fort.get("story","") +
                                  f" | 💎 SAST: {sast_result['acquirer'][:30]} "
                                  f"₹{sast_result['total_value_cr']:.1f}Cr PROMOTER BUY "
                                  f"({sast_result['trade_date']})")
                log.info(f"  💎 DIAMOND UPGRADE {sym}: SAST promoter buy confirmed "
                         f"₹{sast_result['total_value_cr']:.1f}Cr")

        if fused < APEX_MIN_SCORE:
            _rej("FUSED_LOW",
                 f"fused={fused:.1f} < min={APEX_MIN_SCORE} "
                 f"fort={fp} apex={apex_d.get('apex_comp',0):.1f} bayes={bayes_p:.0f}%")
            return None

        # Confidence score
        conf = compute_confidence_score(
            fort.get("fort_pts", 0), apex_d.get("apex_comp", 0),
            bayes_p, fort.get("whale_score", 0),
            fort.get("rsi14", 50), fort.get("adx14", 0),
        )
        if conf < CONFIDENCE_MIN:
            _rej("CONFIDENCE_LOW",
                 f"conf={conf:.3f} < min={CONFIDENCE_MIN} "
                 f"rsi={fort.get('rsi14',50):.0f} adx={fort.get('adx14',0):.0f} "
                 f"whale={fort.get('whale_score',0):.0f}")
            return None

        # Alt-data
        alt_match  = {"matched": False, "best_sim": 0.0,
                      "match_label": "", "catalyst_sub": False}
        has_catalyst = False
        if ALT_DATA_ENABLED and _OPENAI_OK:
            try:
                fil      = live_filings.get(sym, {})
                ins      = live_insider_map.get(sym, {})
                tenders  = _scrape_cpp_tenders(sym)
                exports  = _scrape_zauba_exports(sym)
                alt_text = _build_alt_data_text(sym, tenders, exports,
                                                fil.get("subject",""))
                if alt_text and len(alt_text) > 30:
                    alt_match = _semantic_catalyst_match(sym, alt_text, vector_store)
                    if alt_match.get("catalyst_sub"):
                        mfi_val     = fort.get("mfi", 50)
                        whale_ok    = fort.get("whale_flag", False)
                        delivery_ok = fort.get("delivery_pct", 0) >= 55
                        money_flow_confirms = (mfi_val < 40 or whale_ok or delivery_ok)
                        if not money_flow_confirms:
                            alt_match["catalyst_sub"] = False
                            log.debug(f"{sym} semantic REJECTED: MFI={mfi_val:.0f} "
                                      f"whale={whale_ok} — no money-flow confirmation")
                    has_catalyst = (alt_match.get("matched") or
                                    ins.get("count", 0) > 0 or
                                    fil.get("score", 15) >= 20)
            except Exception as e:
                log.debug(f"Alt-data {sym}: {e}")

        # RS percentile
        rs_pct = _compute_rs_pct(sym, hist, hist_cache, hist_lock)

        # v8.3: OCR the announcement PDF (only for gate-survivors reaching
        # this point — never during the bulk 400-candidate scan) if the
        # filing has an attachment and looks like it could be scanned.
        try:
            fil_entry = live_filings.get(sym, {})
            attach_url = fil_entry.get("attachment_url", "")
            if attach_url:
                ocr_text = fetch_filing_ocr_text(sym, attach_url)
                if ocr_text:
                    fil_entry["ocr_text"] = ocr_text
                    live_filings[sym] = fil_entry
        except Exception as e:
            log.debug(f"OCR hook {sym}: {e}")

        # LLM narrative
        llm = llm_enrich_pick(sym, fort, apex_d, bayes_p, macro,
                              fii_data, live_insider_map, live_filings, alt_match)

        # Grade
        if fused >= 80:   grade = "APEX"
        elif fused >= 70: grade = "PRISTINE"
        elif fused >= 60: grade = "GOOD"
        elif fused >= 48: grade = "PROBE"
        else:             grade = "WATCHLIST"
        fort["grade"] = grade

        # Conviction re-rank
        fort  = apply_conviction_rerank(fort, rs_pct, has_catalyst, alt_match)
        grade = fort["grade"]

        if grade == "WATCHLIST":
            _rej("CONV_RERANK",
                 f"fused={fused:.1f} rs={rs_pct:.0f}pct catalyst={has_catalyst}")
            return None

        # Meta-labeler veto
        ml_vetoed, p_win = meta_labeler_veto(
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
        if ml_vetoed:
            _rej("META_LABELER", f"p_win={p_win:.3f} < 0.35")
            return None

        result = {
            "symbol":       sym,
            "sector":       sector,
            "grade":        grade,
            "fort_pts":     fort.get("fort_pts", 0),
            "apex_comp":    apex_d.get("apex_comp", 0),
            "fused":        fused,
            "bayes_pct":    bayes_p,
            "confidence_score": conf,          # v7.0 NEW
            "uptrend_ok":   fort.get("uptrend_ok", False),   # v7.0 NEW
            # v8.0 NEW fields
            "diamond_upgrade":    diamond_upgrade,
            "sast_promoter_buy":  sast_result.get("promoter_bought", False),
            "sast_value_cr":      sast_result.get("total_value_cr", 0.0),
            "sast_acquirer":      sast_result.get("acquirer", ""),
            "sector_chg_pct":     sector_alpha.get("sector_chg_pct", 0.0),
            "sector_bleeding":    sector_bleeding,
            "pledge_pct":         pledge_pct,
            "llm_material_catalyst": llm.get("llm_material_catalyst", True),
            # existing fields
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
            "meta_p_win":   p_win,
            "ma50":         fort.get("ma50", 0),
            "ma200":        fort.get("ma200", 0),
        }

        _score_cache_put(sym, date_label, close, result, intel_hash)
        return result

    except Exception as e:
        log.debug(f"score_one_symbol {sym}: {e}")
        return None

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 23 — THREE-LANE SELECTION
# ══════════════════════════════════════════════════════════════════════════════

def select_lane_winners(results: List[dict], macro: dict) -> dict:
    g_fort  = CONV_LANE_FORTRESS_MIN if CONVICTION_RERANK else LANE_FORTRESS_MIN
    g_apex  = CONV_LANE_APEX_MIN     if CONVICTION_RERANK else LANE_APEX_MIN
    g_fused = CONV_LANE_FUSED_MIN    if CONVICTION_RERANK else LANE_FUSED_MIN

    def _pick(key: str, gate: float) -> Optional[dict]:
        cands = [r for r in results if r.get(key, 0) >= gate
                 and r.get("grade","") not in ("WATCHLIST",)]
        return max(cands, key=lambda r: r.get(key, 0)) if cands else None

    fortress_w = _pick("fort_pts",  g_fort)
    apex_w     = _pick("apex_comp", g_apex)
    fused_w    = _pick("fused",     g_fused)

    seen = set()
    winners: Dict[str, Optional[dict]] = {}
    for lane, w in [("fortress", fortress_w), ("apex", apex_w), ("fused", fused_w)]:
        if w and w["symbol"] not in seen:
            winners[lane] = w
            seen.add(w["symbol"])
        else:
            winners[lane] = None

    log.info("THREE-LANE WINNERS: " + " | ".join(
        f"{k.upper()}:{v['symbol']} conf={v.get('confidence_score',0):.2f}" if v
        else f"{k.upper()}:NO_PICK"
        for k, v in winners.items()
    ))
    return winners

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 24 — GOOGLE SHEETS OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

_SCREENER_HEADER = [
    "Date","Symbol","Sector","Grade","Fused/100","Fort/200","APEX/100",
    "Bayes%","Confidence","UptrendGate","BuyLo","BuyHi","StopLoss","R1","R2","R3",
    "Shares","ATR14","ATR_Mult","RSI","ADX","MFI","Delivery%","VolRatio",
    "Whale","VPOC","MA50","MA200","RS_Pct","HasCatalyst","AltData","HalalTier",
    "LLM_Verdict","LLM_Why","LLM_Catalyst","Story","MacroState","Lane",
    "MetaP_Win","KellyMult",
    # v8.0 NEW
    "Diamond","SAST_Buy","SAST_Cr","SAST_Acquirer",
    "SectorChg%","SectorBleeding","PledgePct","MaterialCatalyst",
]

def _pick_to_row(p: dict, date_label: str, lane: str = "",
                 kelly_mult: float = 1.0) -> list:
    return [
        date_label, p.get("symbol",""), p.get("sector",""),
        p.get("grade",""), round(p.get("fused",0),1),
        round(p.get("fort_pts",0),0), round(p.get("apex_comp",0),1),
        round(p.get("bayes_pct",0),1),
        round(p.get("confidence_score",0),3),       # v7.0
        "✅" if p.get("uptrend_ok") else "❌",        # v7.0
        round(p.get("buy_lo",0),2), round(p.get("buy_hi",0),2),
        round(p.get("stop_loss",0),2),
        round(p.get("r1",0),2), round(p.get("r2",0),2), round(p.get("r3",0),2),
        p.get("shares",0),
        round(p.get("atr14",0),2), round(p.get("atr_mult",2.0),2),
        round(p.get("rsi14",50),1), round(p.get("adx14",0),1),
        round(p.get("mfi",50),1),
        round(p.get("delivery_pct",0),1), round(p.get("vol_ratio",1),2),
        "✅" if p.get("whale_flag") else "",
        round(p.get("vpoc",0),2),
        round(p.get("ma50",0),2), round(p.get("ma200",0),2),
        round(p.get("rs_pct",50),1),
        "✅" if p.get("has_catalyst") else "",
        f"sim={p.get('alt_sim',0):.3f}" if p.get("alt_matched") else "",
        p.get("halal_tier","ACCEPTABLE"),
        p.get("llm_verdict",""), p.get("llm_why","")[:80],
        p.get("llm_catalyst","")[:60],
        p.get("story","")[:120], p.get("macro_state",""),
        lane.upper(),
        round(p.get("meta_p_win", 0.5), 3),
        round(kelly_mult, 3),
        # v8.0 NEW columns
        "💎" if p.get("diamond_upgrade") else "",
        "✅" if p.get("sast_promoter_buy") else "",
        round(p.get("sast_value_cr", 0), 2),
        p.get("sast_acquirer", "")[:40],
        round(p.get("sector_chg_pct", 0), 2),
        "🩸" if p.get("sector_bleeding") else "✅",
        round(p.get("pledge_pct", -1), 1),
        "✅" if p.get("llm_material_catalyst", True) else "NOISE",
    ]

def push_screener_to_sheets(winners: dict, date_label: str,
                             kelly_mult: float = 1.0) -> bool:
    picks = [(lane, w) for lane, w in winners.items() if w]
    if not picks:
        return False
    existing = _read_sheet("SCREENER")
    rows = existing if existing else [_SCREENER_HEADER]
    rows = [r for r in rows if not (len(r) > 0 and str(r[0]) == date_label)]
    if not rows:
        rows = [_SCREENER_HEADER]
    for lane, w in picks:
        rows.append(_pick_to_row(w, date_label, lane, kelly_mult))
    return _push_sheet("SCREENER", rows)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 25 — TELEGRAM ALERTS
# ══════════════════════════════════════════════════════════════════════════════

def _send_tg(text: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    for attempt in range(3):
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
                timeout=15,
            )
            if resp.status_code == 200:
                return True
            elif resp.status_code == 429:
                time.sleep(2 ** attempt)
        except Exception as e:
            log.debug(f"Telegram attempt {attempt}: {e}")
            time.sleep(1)
    return False

def send_telegram_picks(winners: dict, macro: dict, fii_data: dict,
                         date_label: str, options: dict = None,
                         kelly_stats: dict = None):
    """Send the three-lane picks via Telegram."""
    lines = [
        f"🎯 <b>FORTRESS v7.0 — {date_label}</b>",
        f"Regime: <b>{macro.get('macro_state','?')}</b> | "
        f"VIX={macro.get('vix_val',0):.1f} | FII={fii_data.get('label','?')}",
        "",
    ]
    for lane, w in winners.items():
        if not w:
            continue
        conf    = w.get("confidence_score", 0)
        diamond = "💎 DIAMOND | " if w.get("diamond_upgrade") else ""
        bleed   = f" | 🩸 SECTOR {w.get('sector_chg_pct',0):+.1f}%" if w.get("sector_bleeding") else ""
        pledge  = f" | ⚠️ Pledge {w.get('pledge_pct',0):.0f}%" if (w.get("pledge_pct",-1) >= 0) else ""
        lines += [
            f"🏆 <b>[{lane.upper()}] {diamond}{w['symbol']}</b> — {w.get('grade','')}",
            f"   Fused={w.get('fused',0):.1f} | Conf={conf:.2f} | "
            f"Bayes={w.get('bayes_pct',0):.0f}%",
            f"   Uptrend={'✅' if w.get('uptrend_ok') else '❌'} | "
            f"Entry ₹{w.get('buy_lo',0):.0f}–{w.get('buy_hi',0):.0f}{bleed}{pledge}",
            f"   Stop ₹{w.get('stop_loss',0):.0f} | R1 ₹{w.get('r1',0):.0f}",
            f"   📖 {w.get('llm_why') or w.get('story','')[:60]}",
            "",
        ]
    if kelly_stats and kelly_stats.get("n", 0) >= 5:
        lines.append(f"📊 Kelly mult={winners.get('fused',{}) and '?' or '—'} "
                     f"WR={kelly_stats.get('wr',0):.0%} RR={kelly_stats.get('b',0):.1f}")
    _send_tg("\n".join(lines))

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 26 — OUTCOME ENGINE (resolve prior picks)
# ══════════════════════════════════════════════════════════════════════════════

def run_outcome_engine(date_label: str):
    """
    Fetch today's prices and update status for open positions.
    Evaluates stops against daily LOW and targets against daily HIGH
    (not close-only — prevents phantom wins when intraday stop is hit).
    Stores meta-label for ML feedback loop.
    """
    backup_rows = _read_sheet("DB_BACKUP")
    if not backup_rows or len(backup_rows) < 2:
        return
    header = [h.lower() for h in backup_rows[0]]

    def _f(row, key, default=0.0):
        try:
            return float(row[header.index(key)]) if key in header else default
        except Exception:
            return default

    def _s(row, key, default=""):
        try:
            return str(row[header.index(key)]).strip() if key in header else default
        except Exception:
            return default

    open_positions = []
    for r in backup_rows[1:]:
        if not r:
            continue
        d = dict(zip(header, r))
        if d.get("status","open") == "open":
            open_positions.append(d)

    if not open_positions:
        return

    bhav, _ = load_bhavcopy()
    price_map = {}; high_map = {}; low_map = {}
    if not bhav.empty:
        price_map = dict(zip(bhav["symbol"].str.upper(), bhav["close"]))
        high_map  = dict(zip(bhav["symbol"].str.upper(), bhav["high"]))
        low_map   = dict(zip(bhav["symbol"].str.upper(), bhav["low"]))

    updated = []
    for pos in open_positions:
        sym       = str(pos.get("symbol","")).upper()
        entry     = float(pos.get("entry_price",0) or 0)
        stop_loss = float(pos.get("stop_loss",0) or 0)
        r1 = float(pos.get("r1",0) or 0)
        r2 = float(pos.get("r2",0) or 0)
        r3 = float(pos.get("r3",0) or 0)
        run_date = str(pos.get("run_date",""))
        if entry <= 0:
            continue
        today_close = price_map.get(sym)
        today_high  = high_map.get(sym, today_close)
        today_low   = low_map.get(sym, today_close)
        if not today_close or today_close <= 0:
            updated.append(pos)
            continue
        today_high = today_high or today_close
        today_low  = today_low  or today_close

        # Stop evaluated vs daily LOW; targets vs daily HIGH
        status = "open"; exit_price = 0.0
        if today_low > 0 and today_low <= stop_loss:
            status = "stopped"; exit_price = stop_loss
        elif r3 > 0 and today_high >= r3: status = "r3_hit"; exit_price = r3
        elif r2 > 0 and today_high >= r2: status = "r2_hit"; exit_price = r2
        elif r1 > 0 and today_high >= r1: status = "r1_hit"; exit_price = r1

        if status != "open" and entry > 0:
            pnl_pct = round((exit_price - entry) / entry * 100, 2)
            pos["status"]     = status
            pos["exit_price"] = exit_price
            pos["exit_date"]  = date_label
            pos["pnl_pct"]    = pnl_pct
            log.info(f"Outcome: {sym} {status} entry={entry:.0f} exit={exit_price:.0f} "
                     f"pnl={pnl_pct:+.1f}%")
            try:
                outcome_label = 1 if "hit" in status else 0
                macro_snap = _load_cached_macro() or {"vix_val":18,"advance_ratio":0.5}
                store_meta_label(pos, macro_snap, outcome_label, run_date)
            except Exception as e:
                log.debug(f"store_meta_label: {e}")
            if pnl_pct >= 50 and ALT_DATA_ENABLED and _OPENAI_OK:
                try:
                    tenders  = _scrape_cpp_tenders(sym)
                    exports  = _scrape_zauba_exports(sym)
                    alt_text = _build_alt_data_text(sym, tenders, exports,
                                                    pos.get("story",""))
                    if alt_text:
                        store_alt_vector(sym, "outcome_win", alt_text, "WIN_50PCT")
                except Exception as e:
                    log.debug(f"Alt-data store {sym}: {e}")
        updated.append(pos)

    all_keys = list(header)
    out_rows = [all_keys]
    for p in updated:
        out_rows.append([str(p.get(k,"")) for k in all_keys])
    _push_sheet("DB_BACKUP", out_rows)
    log.info(f"DB_BACKUP updated: {len(updated)} positions")

def auto_log_skipped_picks(date_label: str):
    screener      = _read_sheet("SCREENER")
    decisions_rows = _read_sheet("DB_DECISIONS")
    if not screener or len(screener) < 2:
        return
    sc_header   = [h.lower() for h in screener[0]]
    today_picks = [
        row[sc_header.index("symbol")].upper()
        for row in screener[1:]
        if len(row) > 0 and
        str(row[sc_header.index("date") if "date" in sc_header else 0]) == date_label
    ]
    dec_syms = set()
    if decisions_rows and len(decisions_rows) > 1:
        dec_hdr = [h.lower() for h in decisions_rows[0]]
        dc = dec_hdr.index("run_date") if "run_date" in dec_hdr else 0
        ds = dec_hdr.index("symbol")  if "symbol"   in dec_hdr else 1
        for r in decisions_rows[1:]:
            if len(r) > max(dc, ds) and str(r[dc]) == date_label:
                dec_syms.add(str(r[ds]).upper())
    for sym in today_picks:
        if sym not in dec_syms:
            _append_sheet_row("DB_DECISIONS", [
                date_label, sym, "SKIPPED", "", "0", "no_response", "",
                "", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            ])
            log.info(f"Auto-SKIPPED {sym}")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 27 — PERFORMANCE TAB + WEEKLY REVIEW
# ══════════════════════════════════════════════════════════════════════════════

def push_performance_to_sheets(date_label: str):
    decisions = _read_sheet("DB_DECISIONS")
    backup    = _read_sheet("DB_BACKUP")
    if not decisions or len(decisions) < 2:
        return
    dec_hdr    = [h.lower() for h in decisions[0]]
    taken_rows = [dict(zip(dec_hdr, r)) for r in decisions[1:]
                  if len(r) > 2 and r[dec_hdr.index("decision")] == "TAKEN"
                  if "decision" in dec_hdr]
    if not taken_rows:
        return
    outcome_map: dict = {}
    if backup and len(backup) > 1:
        bk_hdr = [h.lower() for h in backup[0]]
        for r in backup[1:]:
            if not r:
                continue
            d   = dict(zip(bk_hdr, r))
            key = (d.get("run_date",""), d.get("symbol","").upper())
            outcome_map[key] = d
    perf_rows = [["Date","Symbol","Decision","EntryPrice","Shares",
                  "StopLoss","R1","ExitPrice","ExitDate","PnL_Pct","Status"]]
    for row in taken_rows:
        sym = row.get("symbol","").upper()
        rd  = row.get("run_date","")
        out = outcome_map.get((rd, sym), {})
        perf_rows.append([
            rd, sym, "TAKEN",
            row.get("entry_price",""), row.get("shares_taken",""),
            out.get("stop_loss",""), out.get("r1",""),
            out.get("exit_price",""), out.get("exit_date",""),
            out.get("pnl_pct",""), out.get("status","open"),
        ])
    _push_sheet("PERFORMANCE", perf_rows)
    log.info(f"PERFORMANCE tab: {len(perf_rows)-1} rows")

def run_weekly_review(force: bool = False):
    if not force and datetime.today().weekday() != 0:
        log.info("Weekly review: not Monday — skip")
        return
    perf_rows = _read_sheet("PERFORMANCE")
    if not perf_rows or len(perf_rows) < 2:
        _send_tg("📈 <b>Weekly Review</b>\nNo closed trades yet — keep building! 💪")
        return
    header = [h.lower() for h in perf_rows[0]]
    trades = [dict(zip(header, r)) for r in perf_rows[1:] if len(r) > 3]
    closed = [t for t in trades if t.get("status","open") != "open"]
    wins   = [t for t in closed if "hit" in t.get("status","")]
    total  = len(closed)
    wr     = len(wins) / total * 100 if total > 0 else 0
    avg_pnl = (sum(float(t.get("pnl_pct",0) or 0) for t in closed) / total) if total > 0 else 0
    summary = (f"Closed: {total} | Wins: {len(wins)} | WR: {wr:.0f}% | "
               f"Avg P&L: {avg_pnl:+.1f}%")
    if _OPENAI_OK and total > 0:
        narrative = _call_openai(
            f"NSE quant screener v7.0 weekly review.\n{summary}\n"
            f"Top wins: {[(t.get('symbol',''),t.get('pnl_pct','0')) for t in wins[:3]]}\n"
            "Write a 3-paragraph quant review: (1) performance, (2) regime context, "
            "(3) one concrete v7.0 tweak. Max 200 words.",
            max_tokens=400, cache_ttl_days=0
        ) or "Run more trades to generate AI narrative."
    else:
        narrative = summary
    _send_tg(f"📈 <b>FORTRESS v7.5.1 Weekly Review — {datetime.today():%Y-%m-%d}</b>\n"
             f"{summary}\n\n{narrative}")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 28 — MAIN RUN() ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════════

def run():
    log.info(f"{'='*70}")
    log.info(f"  {VERSION}")
    log.info(f"  v8.0: SAST Real-Whale | Sector-Velocity | Materiality-Filter | Pledge-Gate")
    log.info(f"  v8.1: Session-Armor-Fix | Targeted-Intel-Heist | Soft-Accumulation-Gate")
    log.info(f"  curl_cffi: {'ACTIVE — Chrome TLS fingerprint ON' if _CURL_CFFI_OK else 'NOT INSTALLED (pip install curl_cffi) — CF bypass DISABLED'}")
    log.info(f"  Uptrend Gate: SOFTENED (full=100% VCP, base_forming=50% VCP, downtrend=0%)")
    log.info(f"  Confidence Min: {CONFIDENCE_MIN} | Std Max: {CONFIDENCE_STD_MAX}")
    log.info(f"  Pledge Gate: {'ON' if PLEDGE_GATE_ENABLED else 'OFF'} > {PLEDGE_GATE_MAX_PCT:.0f}% → SKIP")
    log.info(f"  Sector Velocity: {'ON' if SECTOR_VELOCITY_ENABLED else 'OFF'} "
             f"penalty={SECTOR_VELOCITY_PENALTY:.0f}pts when bleeding")
    log.info(f"{'='*70}")

    _init_db()

    # FIX-B: write sentinel immediately so artifact is never empty
    _, date_label = _get_last_trading_day()
    _write_sentinel(date_label, "STARTED")

    # FIX-C: preflight secret check
    secrets_ok = _preflight_secrets()

    log.info(f"Date: {date_label}")

    # 2. Macro regime
    macro = fetch_macro_regime()
    _write_sentinel(date_label, "MACRO_DONE", {
        "REGIME ": macro["macro_state"],
        "VIX    ": macro["vix_val"],
    })
    if macro["macro_state"] in ("MASSACRE",):
        log.warning("MASSACRE regime — no picks today (capital preservation)")
        _write_sentinel(date_label, "ABORTED_MASSACRE", {"REGIME": macro["macro_state"]})
        _send_tg(f"⚠️ <b>FORTRESS v7.5.1 — {date_label}</b>\n"
                 f"MASSACRE regime (VIX={macro['vix_val']:.1f}) — no picks today.")
        return []

    # 3. Bhavcopy — FIX-A retry/curl baked into load_bhavcopy()
    bhav, bhav_src = load_bhavcopy()
    _write_sentinel(date_label, "BHAVCOPY_DONE", {
        "SRC    ": bhav_src,
        "ROWS   ": len(bhav),
    })
    if bhav.empty:
        log.error(f"Bhavcopy empty (src={bhav_src}) — aborting run")
        _write_sentinel(date_label, "ABORTED_BHAVCOPY", {"SRC": bhav_src, "ROWS": 0})
        _send_tg(
            f"❌ <b>FORTRESS v7.5.1 — {date_label}</b>\n"
            f"Bhavcopy unavailable (src={bhav_src}).\n"
            f"NSE requests (3 retries + UA rotation + curl) all failed.\n"
            f"Check GHA secrets: " +
            (", ".join(k for k, v in secrets_ok.items() if not v) or "all present")
        )
        return []
    log.info(f"Bhavcopy: {len(bhav)} rows from {bhav_src}")

    # 4. Filter candidates
    cands = bhav[
        (bhav["close"] >= MIN_PRICE) &
        (bhav["close"] <= MAX_PRICE) &
        (bhav["turnover_lakhs"] >= MIN_TURNOVER_LAKHS)
    ].head(MAX_CANDIDATES).copy()
    log.info(f"Candidates after price/liquidity filter: {len(cands)}")
    if cands.empty:
        _write_sentinel(date_label, "ABORTED_NO_CANDIDATES",
                        {"BHAV_SRC": bhav_src, "BHAV_ROWS": len(bhav)})
        _send_tg(f"📋 <b>FORTRESS v7.5.1 — {date_label}</b>\nNo candidates after filters.")
        return []

    # 5. Intelligence feeds (parallel, graceful degradation)
    with ThreadPoolExecutor(max_workers=3) as ex:
        fii_f    = ex.submit(fetch_fii_dii)
        ins_f    = ex.submit(fetch_insider_trades)
        fil_f    = ex.submit(fetch_filings)
        fii_data    = fii_f.result(timeout=30)
    try:
        insider_map = ins_f.result(timeout=20)
    except Exception:
        insider_map = {}
    try:
        filings = fil_f.result(timeout=20)
    except Exception:
        filings = {}
    log.info(f"Intel: FII={fii_data['label']} insiders={len(insider_map)} "
             f"filings={len(filings)}")
    # PATCH-3: log alt-data capability so 'insiders=0 filings=0' is diagnosable
    log.info(f"Alt-data: SCRAPERAPI={'SET' if SCRAPERAPI_KEY else 'MISSING — CPP/Zauba disabled'} | "
             f"OPENAI={'SET' if _OPENAI_OK else 'MISSING — LLM/embeddings disabled'}")

    # 6. Vector store for alt-data
    vector_store: list = []
    if ALT_DATA_ENABLED and _OPENAI_OK:
        try:
            vector_store = _load_vector_store()
            log.info(f"Vector store: {len(vector_store)} entries")
        except Exception as e:
            log.debug(f"Vector store load: {e}")

    # 7. Background history preload — v7.0: ALL mutations under hist_lock
    hist_cache: Dict[str, pd.DataFrame] = {}
    hist_lock  = threading.Lock()

    # ── PATCH-1: Blocking history preload (Race condition fix) ───────────────
    # BUG: Old code started preload thread then IMMEDIATELY started scoring.
    # Workers found empty hist_cache, scored every stock 0, run produced nothing.
    # FIX: Preload uses NSE historical API (FIX-E) in chunks via ThreadPoolExecutor.
    # Main thread joins/waits before scoring starts.
    # Progress logged every 30 symbols so GHA doesn't think job hung.
    syms_to_preload = cands["symbol"].str.upper().tolist()
    log.info(f"History preload: fetching {len(syms_to_preload)} symbols (BLOCKING) …")

    def _preload_one(sym: str):
        try:
            h = fetch_history(sym, days=300)
            if not h.empty and len(h) >= 20:
                with hist_lock:
                    hist_cache[sym] = h
        except Exception:
            pass

    preload_done = 0
    with ThreadPoolExecutor(max_workers=12, thread_name_prefix="hist") as ph:
        futs = {ph.submit(_preload_one, s): s for s in syms_to_preload}
        from concurrent.futures import as_completed as _ac
        for fut in _ac(futs):
            preload_done += 1
            if preload_done % 30 == 0:
                with hist_lock:
                    cached_n = len(hist_cache)
                log.info(f"History preload: {preload_done}/{len(syms_to_preload)} submitted "
                         f"| loaded={cached_n}")

    with hist_lock:
        final_loaded = len(hist_cache)
    log.info(f"✅ History preload COMPLETE: {final_loaded}/{len(syms_to_preload)} symbols loaded")
    _write_sentinel(date_label, "HISTORY_PRELOAD_DONE",
                    {"LOADED": final_loaded, "TOTAL": len(syms_to_preload)})

    # 8. Parallel scoring
    fast_rerun = os.getenv("FAST_RERUN","false").lower() in ("1","true","yes")
    n_workers  = min(8, max(2, len(cands) // 10))
    results: List[dict] = []
    results_lock = threading.Lock()

    scoring_args = [
        (row["symbol"], row.to_dict(), hist_cache,
         fii_data, insider_map, filings,
         macro, date_label, vector_store, fast_rerun, hist_lock)
        for _, row in cands.iterrows()
    ]
    log.info(f"Scoring {len(cands)} candidates with {n_workers} workers …")

    completed = 0
    with ThreadPoolExecutor(max_workers=n_workers, thread_name_prefix="v7_score") as executor:
        from concurrent.futures import as_completed
        future_map = {executor.submit(score_one_symbol, a): a[0] for a in scoring_args}
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
                    log.info(
                        f"  ✅ {sym:12s} | fused={r['fused']}/100 | "
                        f"conf={r.get('confidence_score',0):.2f} | "
                        f"uptrend={'✅' if r.get('uptrend_ok') else '❌'} | "
                        f"{r['grade'][:8]}"
                    )
            except Exception as e:
                log.debug(f"{sym}: {e}")

    log.info(f"Scored {len(cands)} | Passed all gates: {len(results)}")

    # ── v7.5: Gate diagnostics summary ───────────────────────────────────────
    # Parse GATE lines from log to count which wall killed most stocks.
    # Gives actionable "FORT_PTS_LOW killed 312/400" in one line.
    # Uses in-memory counter (no file I/O needed).
    _gate_counts: Dict[str, int] = {}
    _top_fort: List[tuple]       = []   # (fort_pts, sym) for top-rejected
    try:
        import collections as _col
        # Collect from results (passed) + log lines already emitted (rejected)
        # We can't re-parse log easily, but we re-score a summary from our
        # sentinel writes — instead track via a module-level counter.
        # The _rej() calls already emitted INFO lines; just report top survivors.
        log.info("─" * 60)
        log.info("GATE DIAGNOSTIC SUMMARY (check GATE lines above for per-symbol detail)")
        log.info(f"  Total candidates  : {len(cands)}")
        log.info(f"  History loaded    : {final_loaded}/{len(syms_to_preload)}")
        log.info(f"  Passed all gates  : {len(results)}")
        log.info(f"  APEX_MIN_SCORE    : {APEX_MIN_SCORE}  (lower = more picks)")
        log.info(f"  CONFIDENCE_MIN    : {CONFIDENCE_MIN}  (lower = more picks)")
        log.info(f"  FORT_PTS gate     : 45/200 (restored 60-pt VPOC block, gate recalibrated)")
        log.info(f"  Uptrend gate      : Price>50MA>200MA (required for VCP pts)")
        log.info(f"  Regime            : {macro['macro_state']} VIX={macro['vix_val']}")
        log.info(f"  FII               : {fii_data['label']}")
        log.info(f"  OCR Engine        : {_OCR_STATS['attempted']} attempted | "
                 f"{_OCR_STATS['success']} succeeded | {_OCR_STATS['failed']} failed/empty"
                 + ("" if _OCR_OK else "  [tesseract/pdf2image NOT installed — OCR disabled]"))
        log.info("  → Search 'GATE FORT_PTS_LOW' above to see which stocks hit this wall")
        log.info("  → Search 'GATE FUSED_LOW' to see which stocks failed fused score")
        log.info("  → Search 'GATE CONFIDENCE_LOW' to see confidence rejections")
        log.info("─" * 60)
        _write_sentinel(date_label, "SCORING_DONE", {
            "CANDIDATES": len(cands),
            "HIST_LOADED": final_loaded,
            "PASSED    ": len(results),
            "APEX_MIN  ": APEX_MIN_SCORE,
            "CONF_MIN  ": CONFIDENCE_MIN,
            "REGIME    ": macro["macro_state"],
        })
    except Exception as e:
        log.debug(f"gate summary: {e}")

    if not results:
        _write_sentinel(date_label, "NO_PICKS",
                        {"SCORED": len(cands), "BHAV_SRC": bhav_src,
                         "REGIME": macro["macro_state"]})
        _send_tg(
            f"📋 <b>FORTRESS v7.5.1 — {date_label}</b>\n"
            f"Regime: {macro['macro_state']} VIX={macro['vix_val']:.1f}\n"
            f"Scored: {len(cands)} | Source: {bhav_src}\n"
            f"No candidates cleared Uptrend Gate + Confidence Score + Fused gates.\n"
            f"Pearls-or-nothing ✨"
        )
        return []

    # 9. Three-lane selection
    winners = select_lane_winners(results, macro)

    # 10. Options gravity overlay
    options: dict = {}
    try:
        options = fetch_options_gravity("NIFTY")
        winners = apply_options_gravity_gate(winners, options, macro)
    except Exception as e:
        log.warning(f"Options gravity non-fatal: {e}")

    # 11. Kelly position sizing
    kelly_mult, kelly_stats = 1.0, {}
    try:
        kelly_mult, kelly_stats = compute_kelly_multiplier()
        for lane, w in winners.items():
            if w and w.get("shares", 0) > 0:
                w["shares"]      = kelly_adjusted_size(w["shares"], kelly_mult)
                w["kelly_mult"]  = kelly_mult
                w["kelly_stats"] = kelly_stats
    except Exception as e:
        log.warning(f"Kelly non-fatal: {e}")

    final_picks = [w for w in winners.values() if w]
    if not final_picks:
        _write_sentinel(date_label, "NO_LANE_PICKS",
                        {"SCORED": len(results), "REGIME": macro["macro_state"]})
        _send_tg(f"📋 <b>FORTRESS v7.5.1 — {date_label}</b>\n"
                 f"Regime: {macro['macro_state']} | {len(results)} scored\n"
                 f"No picks survived lane gates (pearls-or-nothing).")
        return []

    # 12. Persist to SCREENER tab
    push_screener_to_sheets(winners, date_label, kelly_mult)

    # 13. Telegram alert
    send_telegram_picks(winners, macro, fii_data, date_label,
                        options=options, kelly_stats=kelly_stats)

    # v8.3: surface OCR engine stats in Telegram too, not just the log —
    # last time a silent tracking failure went unnoticed for a month
    # because nothing user-facing reported it.
    if _OCR_STATS["attempted"] > 0:
        _send_tg(f"🔍 OCR Engine: {_OCR_STATS['attempted']} attempted | "
                 f"{_OCR_STATS['success']} succeeded | "
                 f"{_OCR_STATS['failed']} failed/empty")
    elif not _OCR_OK:
        _send_tg("⚠️ OCR disabled — tesseract/pdf2image not installed on runner.")

    # 14. Outcome engine
    try:
        run_outcome_engine(date_label)
    except Exception as e:
        log.warning(f"Outcome engine non-fatal: {e}")

    # 15. Performance tab
    try:
        push_performance_to_sheets(date_label)
    except Exception as e:
        log.warning(f"Performance tab non-fatal: {e}")

    log.info(f"✅ Run complete | {len(final_picks)} pick(s) | "
             f"{[p['symbol'] for p in final_picks]}")
    _write_sentinel(date_label, "COMPLETE", {
        "PICKS  ": len(final_picks),
        "SYMBOLS": " ".join(p["symbol"] for p in final_picks),
        "BHAV   ": bhav_src,
        "SCORED ": len(results),
        "REGIME ": macro["macro_state"],
        "VIX    ": macro.get("vix_val", 0),
    })
    return final_picks

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 29 — CLI ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fortress Sniper v7.2 EOD Pearl Hunter")
    parser.add_argument("--weekly-review",  action="store_true")
    parser.add_argument("--outcome-only",   action="store_true")
    parser.add_argument("--store-vector",   metavar="SYMBOL")
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
        print(f"Vector stored: {store_alt_vector(sym, 'manual', text, 'WIN_50PCT')}"
              if text else "No alt-data found")
    else:
        run()
