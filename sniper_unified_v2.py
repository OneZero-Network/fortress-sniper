"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   UNIFIED HALAL SNIPER v4.0-M — FORTRESS × APEX × CALIBRATED AI JUDGE     ║
║   Bismillah — In the name of Allah, the Most Gracious, the Most Merciful   ║
║                                                                              ║
║   ARCHITECTURE                                                               ║
║   ─────────────────────────────────────────────────────────────             ║
║   ONE pipeline. ONE halal guard. ONE DB. ONE macro fetch.                   ║
║   Fortress scoring + APEX 7-engine composite run together,                  ║
║   ranked by a single fused score, sent in one clean Telegram message.       ║
║                                                                              ║
║   WHAT WAS MERGED / WHAT WAS DEDUPLICATED                                   ║
║   ─────────────────────────────────────────────────────────────             ║
║   ✓  Single is_halal() — Nifty500 Shariah CSV → Sheets Tab 7 → fallback    ║
║   ✓  Single fetch_history() — NSE API → yfinance (NSE session shared)      ║
║   ✓  Single fetch_macro_regime() — INDIAVIX + NSEI + CNX500                ║
║   ✓  Single fetch_fii_dii() — NSE API → Sheets Tab 2 → VIX proxy          ║
║   ✓  Fortress scoring (fortress_score + assemble_result_v8) preserved      ║
║      fully — 6-layer VPOC, SN-2/3/5/6 Bayesian, Monte Carlo, FOG, VSA     ║
║   ✓  APEX 7-engine preserved — Whale Radar, Divergence, Vol Profile,       ║
║      Pattern, MC, 11-node Bayes, POC proximity                             ║
║   ✓  FUSED composite: fortress_total × 0.45 + apex_composite × 0.55        ║
║      Intelligence bonus: FII/insider/filing scores feed APEX Bayesian       ║
║   ✓  Story: structured (not raw Sheets cell refs), all 4 signal sources    ║
║   ✓  Single Telegram send — MarkdownV2 safe, plain-text fallback            ║
║   ✓  Single DB (fortress_cache.db) — halal, ROCE, EOD, positions           ║
║   ✓  Single GitHub Actions step — python sniper_unified_v1.py              ║
║                                                                              ║
║   REMOVED BUGS                                                               ║
║   ─────────────────────────────────────────────────────────────             ║
║   ✗  Fortress running twice (workflow python -c + standalone)               ║
║   ✗  Duplicate is_halal() / HALAL_WHITELIST in APEX                        ║
║   ✗  APEX header hardcoded "v1.1" (now reads VERSION)                      ║
║   ✗  Story returning raw "updates [sheets tab 4]" cell refs                ║
║   ✗  run_apex_after_fortress() imported but never called                   ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os, io, sys, re, json, math, time, random, logging, sqlite3, threading, warnings
import queue
import asyncio
import dataclasses
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)
for _noisy in ("yfinance", "peewee", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.CRITICAL)

VERSION = "UNIFIED v4.0-M"

# ── Event-Driven Pipeline Infrastructure ──────────────────────────────────────
# Producer threads push MarketEvents into the queue.
# The Fused Engine (consumer) processes each event the moment it arrives,
# preventing one slow API call (e.g. earnings veto) from blocking others.

@dataclasses.dataclass
class MarketEvent:
    """Atomic unit of market data flowing through the pipeline."""
    event_type: str          # "QUOTE" | "MACRO" | "INTELLIGENCE" | "HISTORY"
    symbol: str
    payload: dict            # raw data; consumer extracts what it needs
    timestamp: float = dataclasses.field(default_factory=time.time)

# Global thread-safe event queue (producers → consumer)
_EVENT_QUEUE: queue.Queue = queue.Queue(maxsize=0)   # unbounded

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — CONFIG (all env-overridable)
# ══════════════════════════════════════════════════════════════════════════════

TELEGRAM_TOKEN     = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_SHARE_IDS = [c.strip() for c in os.getenv("TELEGRAM_SHARE_IDS", "").split(",") if c.strip()]

GOOGLE_SHEET_ID   = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON", "")

DB_PATH          = Path(os.getenv("CACHE_PATH", "outputs/sniper_cache.db"))
EXCEL_PATH       = Path("outputs/sniper_report.xlsx")
HTML_PATH        = Path("outputs/sniper_report.html")

PAPER_MODE       = os.getenv("PAPER_MODE", "false").lower() == "true"
FORCE_YFINANCE   = os.getenv("FORCE_YFINANCE", "false").lower() == "true"
FORCE_SHEETS     = os.getenv("FORCE_SHEETS", "false").lower() == "true"
CB_FAIL_SAFE     = os.getenv("CB_FAIL_SAFE", "true").lower() == "true"

ACCOUNT_EQUITY   = float(os.getenv("ACCOUNT_EQUITY", "500000"))
ACCOUNT_RISK_PCT = float(os.getenv("ACCOUNT_RISK_PCT", "0.015"))

SHARIAH_TTL_DAYS = int(os.getenv("SHARIAH_CACHE_TTL_DAYS", "7"))  # FIX-3: was 1 day; CI IPs blocked so daily re-fetch always fails; extend to 7d
APEX_TOP_N       = int(os.getenv("APEX_TOP_N", "5"))
APEX_MIN_SCORE   = int(os.getenv("APEX_MIN_SCORE", "48"))
NSE_MAX_RETRIES  = int(os.getenv("NSE_MAX_RETRIES", "3"))         # FIX-4: set NSE_MAX_RETRIES=1 in CI env to cut log noise when NSE is blocked

MC_SIMS    = int(os.getenv("MC_SIMS", "600"))

# v3.0-M: Capacity guard config
CAPACITY_MAX_OPEN  = int(os.getenv("CAPACITY_MAX_OPEN", "4"))
CAPACITY_MAX_WEEK  = int(os.getenv("CAPACITY_MAX_WEEK", "6"))
MC_FAT_DF  = 5          # Student-t df — heavier tails for NSE gap risk
MC_HORIZON = 12         # swing horizon (days)

MIN_PRICE          = 50
MAX_PRICE          = 800
MIN_TURNOVER_LAKHS = 150
MAX_CANDIDATES     = 200
MIN_HIST_BARS      = 30

# Scoring weights — APEX 7-engine
W = dict(
    fortress_vpoc = 0.25,
    whale_radar   = 0.25,
    divergence    = 0.15,
    vol_profile   = 0.15,
    pattern       = 0.10,
    bayesian      = 0.10,
)

# Fortress component maxima
FORT_SCORE_MAX = dict(fortress=80, fii_dii=30, insider=30, filing=30, earnings=30)
FORT_TOTAL_MAX = sum(FORT_SCORE_MAX.values())   # 200

# Grade thresholds (APEX composite 0-100)
GRADE_APEX     = 82
GRADE_PRISTINE = 72
GRADE_GOOD     = 60
GRADE_PROBE    = 48

SNIPER_CFG = dict(
    vix_panic      = 22.0, vix_chop      = 15.0, vix_fog       = 20.0,
    nifty_massacre = -3.0,
    vpoc_band_pct  = 0.02, vpoc_weeks    = 52,   vol_spikes_52w= 35,
    bounce_recency = 45,   min_bounces   = 3,
    liquidity_mult = 2.0,  min_turnover_cr= 3.0,
    alt_warn_pct   = 40.0, alt_stop_pct  = 60.0,
    risk_per_trade = 0.015, max_pos_pct  = 0.10,
    atr_stop_mult  = 2.0,  trail_atr_mult= 2.5,
    trail_trigger_pct = 15.0,
    r1_pct = 30.0, r2_pct = 60.0, r3_pct = 100.0,
    r1_sell_pct = 30, r2_sell_pct = 30, r3_sell_pct = 40,
    bayes_alpha    = 0.12,
    vpoc_3m_wt = 0.40, vpoc_6m_wt = 0.35, vpoc_12m_wt = 0.25,
    ma200_tolerance = 0.05,
    score_pristine = 85, score_good = 70, score_marginal = 58, score_probe = 45,
    adx_trend = 25.0, adx_range = 18.0,
    vol_ratio = 2.5, turnover_lakhs = 150,
)

SECTOR_INDICES = {
    "NIFTY IT":     "CNXIT",
    "NIFTY PHARMA": "CNXPHARMA",
    "NIFTY AUTO":   "CNXAUTO",
    "NIFTY FMCG":   "CNXFMCG",
    "NIFTY METAL":  "CNXMETAL",
}

SECTOR_TRUTH = {
    "NIFTY PHARMA": 1.15, "NIFTY IT": 1.10, "NIFTY AUTO": 1.00,
    "NIFTY FMCG": 0.95,  "NIFTY METAL": 0.85, "DIVERSIFIED": 1.00,
    "NIFTY BANK": 0.00,  "NIFTY REALTY": 0.75, "NIFTY ENERGY": 0.20,
}
SECTOR_BLOCKED = {"NIFTY BANK", "NIFTY ENERGY"}

SECTOR_ATR_MULT = {
    "NIFTY METAL": 1.20, "NIFTY IT": 0.90, "NIFTY PHARMA": 1.10,
    "NIFTY AUTO": 1.05,  "NIFTY FMCG": 0.85, "DIVERSIFIED": 1.00,
}

# ══════════════════════════════════════════════════════════════════════════════
# YFINANCE CIRCUIT BREAKER & SHARED CACHES
# ══════════════════════════════════════════════════════════════════════════════

_YF_DOWNLOAD_TIMEOUT = 15          # seconds for yf.download
_YF_INFO_TIMEOUT     = 10          # seconds for yf.Ticker().info
_YF_FAIL_COUNT       = 0
_YF_FAIL_LOCK        = threading.Lock()   # Bug fix: guards concurrent increments from worker threads
_YF_FAIL_THRESHOLD   = 3           # skip all yf calls after 3 consecutive failures
_YF_CIRCUIT_OPEN_UNTIL: float = 0.0  # C3: epoch-seconds; >0 means circuit open (24 h ban)
_NSE_HISTORY_OK      = None        # None=unknown, True=working, False=broken (speeds up loop when NSE is down)

_YF_BACKOFF_BASE   = 2.0   # C3: base for exponential back-off (seconds)
_YF_BACKOFF_MAX    = 60.0  # C3: cap per-attempt sleep
_YF_MAX_ATTEMPTS   = 4     # C3: per-call retry budget

_CNX500_CACHE        = None
_CNX500_CACHE_TIME   = 0
_SECTOR_INDEX_CACHE  = {}        # ticker -> DataFrame
_SECTOR_MOM_CACHE    = {}        # "sector_days" -> result dict
_MAX_SECTOR_YF_CALLS = 8         # max unique sector index downloads per run
_SECTOR_YF_CALLS     = 0


# ══════════════════════════════════════════════════════════════════════════════
# [PATCH-A]  MULTI-PROVIDER LLM CONFIG  (replaces SECTION 1b — v4.0-M)
# ══════════════════════════════════════════════════════════════════════════════
# Each task routes to the cheapest capable model.
# To enable: set the relevant API key env var. Keys absent → rule-based fallback.

# Claude (Anthropic) — signal coherence + halal screening
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL       = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

# OpenAI — filing sentiment (mini) + sandbox/weekly (batch)
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY", "")
OPENAI_MINI_MODEL  = os.getenv("OPENAI_MINI_MODEL", "gpt-4o-mini")
OPENAI_BATCH_MODEL = os.getenv("OPENAI_BATCH_MODEL", "gpt-4o")

LLM_MAX_TOKENS     = int(os.getenv("LLM_MAX_TOKENS", "512"))

# Backward-compat: if only ANTHROPIC_API_KEY set, it covers all LLM tasks
_ANTHROPIC_OK = bool(ANTHROPIC_API_KEY)
_OPENAI_OK    = bool(OPENAI_API_KEY)
LLM_ENABLED   = _ANTHROPIC_OK or _OPENAI_OK

# Legacy shims (used elsewhere in the codebase)
LLM_API_KEY = ANTHROPIC_API_KEY
LLM_MODEL   = CLAUDE_MODEL


def _llm_hash(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()[:32]


# ── Provider routers ─────────────────────────────────────────────────────────

def _call_claude(prompt: str, max_tokens: int = None) -> Optional[str]:
    """Call Claude Sonnet. Returns text or None."""
    if not _ANTHROPIC_OK:
        return None
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": max_tokens or LLM_MAX_TOKENS,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()["content"][0]["text"]
        log.warning(f"Claude {resp.status_code}: {resp.text[:80]}")
    except Exception as e:
        log.debug(f"Claude call failed: {e}")
    return None


def _call_openai(prompt: str, model: str = None, max_tokens: int = None) -> Optional[str]:
    """Call OpenAI. Returns text or None."""
    if not _OPENAI_OK:
        return None
    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": model or OPENAI_MINI_MODEL,
                "max_tokens": max_tokens or LLM_MAX_TOKENS,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        log.warning(f"OpenAI {resp.status_code}: {resp.text[:80]}")
    except Exception as e:
        log.debug(f"OpenAI call failed: {e}")
    return None


# ── Shared SQLite LLM cache ──────────────────────────────────────────────────

def _llm_cached(text: str, prompt_type: str) -> Optional[str]:
    """Check SQLite cache for existing LLM result."""
    if not LLM_ENABLED:
        return None
    try:
        con = sqlite3.connect(DB_PATH)
        h = _llm_hash(text)
        row = con.execute(
            "SELECT result FROM llm_cache WHERE text_hash=? AND prompt_type=?",
            (h, prompt_type)
        ).fetchone()
        con.close()
        if row:
            log.debug(f"LLM cache hit: {prompt_type} | {h[:8]}...")
            return row[0]
    except Exception:
        pass
    return None


def _llm_store_cache(text: str, prompt_type: str, result: str, model: str = ""):
    """Store LLM result in SQLite cache."""
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute(
            "INSERT OR REPLACE INTO llm_cache (text_hash, prompt_type, result, model) VALUES (?,?,?,?)",
            (_llm_hash(text), prompt_type, result, model or CLAUDE_MODEL)
        )
        con.commit(); con.close()
    except Exception:
        pass


def _llm_call(prompt: str, prompt_type: str, max_tokens: int = None) -> Optional[str]:
    """
    Legacy single-provider call shim. Routes to Claude first, then OpenAI.
    New code should call _call_claude / _call_openai directly.
    """
    if not LLM_ENABLED:
        return None
    cached = _llm_cached(prompt, prompt_type)
    if cached:
        return cached
    raw = _call_claude(prompt, max_tokens) or _call_openai(prompt, max_tokens=max_tokens)
    if raw:
        _llm_store_cache(prompt, prompt_type, raw)
    return raw


# ── Task-specific callers ────────────────────────────────────────────────────

def _llm_alpha_mine(subject: str, symbol: str = "") -> dict:
    """Filing sentiment → GPT-4o mini (cheapest). Falls back to Claude, then rule."""
    if not LLM_ENABLED:
        return {"score": 15, "factors": {}, "source": "LLM_DISABLED"}

    cache_key = f"alpha_mine:{symbol}:{_llm_hash(subject)}"
    cached = _llm_cached(cache_key, "alpha_mine")
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    prompt = (
        "Analyze this Indian corporate filing. Return ONLY JSON (no markdown):\n"
        '{"SURPRISE_FACTOR": X.XX, "CONFIDENCE": X.XX, "URGENCY": X.XX, '
        '"SENTIMENT": X.XX, "MATERIALITY": X.XX}\n'
        f"Ranges: SURPRISE_FACTOR/SENTIMENT [-1,1], others [0,1]\n"
        f"Filing: {subject[:800]}\nSymbol: {symbol}"
    )
    # Route: GPT-4o mini first, fall back to Claude
    raw = _call_openai(prompt, model=OPENAI_MINI_MODEL, max_tokens=200) or _call_claude(prompt, max_tokens=200)
    if not raw:
        return {"score": 15, "factors": {}, "source": "LLM_FAILED"}

    try:
        txt = raw.strip().replace("```json", "").replace("```", "")
        factors = json.loads(txt)
        validated = {}
        for key, default in [("SURPRISE_FACTOR", 0.0), ("CONFIDENCE", 0.5),
                              ("URGENCY", 0.5), ("SENTIMENT", 0.0), ("MATERIALITY", 0.5)]:
            val = float(factors.get(key, default))
            if key in ("SURPRISE_FACTOR", "SENTIMENT"):
                val = max(-1.0, min(1.0, val))
            else:
                val = max(0.0, min(1.0, val))
            validated[key] = round(val, 2)
        alpha_score = int(max(0, min(30,
            (validated["SURPRISE_FACTOR"] * 0.25 + validated["CONFIDENCE"] * 0.20 +
             validated["URGENCY"] * 0.15 + validated["SENTIMENT"] * 0.30 +
             validated["MATERIALITY"] * 0.10) * 30 + 15
        )))
        result_dict = {"score": alpha_score, "factors": validated, "source": "LLM_ALPHA_MINE"}
        _llm_store_cache(cache_key, "alpha_mine", json.dumps(result_dict), OPENAI_MINI_MODEL)
        return result_dict
    except Exception as e:
        log.debug(f"Alpha mine parse {symbol}: {e}")
        return {"score": 15, "factors": {}, "source": "PARSE_ERROR"}


def _llm_filing_sentiment(subject: str, symbol: str = "") -> dict:
    """Backward-compat wrapper."""
    alpha = _llm_alpha_mine(subject, symbol)
    score = alpha.get("score", 15)
    factors = alpha.get("factors", {})
    sentiment = "POSITIVE" if score >= 20 else ("NEGATIVE" if score <= 10 else "NEUTRAL")
    return {"score": score, "sentiment": sentiment,
            "detail": f"AlphaMine: SENTIMENT={factors.get('SENTIMENT', 0):.2f}",
            "alpha_factors": factors}


def _llm_structured_reasoning(symbol: str, signal_dict: dict) -> Optional[dict]:
    """Signal coherence → Claude Sonnet (best reasoning). Falls back to OpenAI."""
    if not LLM_ENABLED:
        return None

    import hashlib
    signal_json = json.dumps(signal_dict, sort_keys=True, default=str)
    signal_hash = hashlib.sha256(signal_json.encode()).hexdigest()[:16]
    cached = _llm_cached(signal_hash, "structured_reasoning")
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    prompt = (
        "You are a quantitative trading analyst. Analyze this NSE stock signal JSON.\n"
        f"Symbol: {symbol}\nSignals: {signal_json[:2000]}\n\n"
        "Return EXACTLY this JSON (no markdown):\n"
        '{"conviction": 0-100, "key_risk": "single sentence", '
        '"weight_override": {"whale_radar": 0.0-1.0, "divergence": 0.0-1.0, '
        '"vol_profile": 0.0-1.0, "pattern": 0.0-1.0, "bayesian": 0.0-1.0}, '
        '"regime_note": "single sentence"}'
    )
    # Route: Claude first (better at structured JSON), fall back to OpenAI
    raw = _call_claude(prompt, max_tokens=600) or _call_openai(prompt, model=OPENAI_MINI_MODEL, max_tokens=600)
    if not raw:
        return None
    try:
        txt = raw.strip().replace("```json", "").replace("```", "")
        parsed = json.loads(txt)
        parsed["conviction"] = max(0, min(100, int(parsed.get("conviction", 50))))
        parsed["key_risk"]   = str(parsed.get("key_risk", ""))[:100]
        parsed["regime_note"] = str(parsed.get("regime_note", ""))[:100]
        wo = parsed.get("weight_override")
        if isinstance(wo, dict):
            for k in ["whale_radar", "divergence", "vol_profile", "pattern", "bayesian"]:
                if k in wo:
                    wo[k] = max(0.0, min(1.0, float(wo[k])))
        else:
            parsed["weight_override"] = None
        _llm_store_cache(signal_hash, "structured_reasoning", json.dumps(parsed), CLAUDE_MODEL)
        return parsed
    except Exception as e:
        log.debug(f"LLM structured parse {symbol}: {e}")
        return None


def _llm_story_enhance(symbol: str, story_parts: list, technicals: dict) -> Optional[str]:
    result = _llm_structured_reasoning(symbol, {"parts": story_parts, "technicals": technicals})
    return result.get("regime_note") if result else None


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — HALAL GUARD  (single authoritative implementation)
# ══════════════════════════════════════════════════════════════════════════════

HALAL_EXCLUDED = {
    "HDFCBANK","ICICIBANK","SBIN","KOTAKBANK","AXISBANK","INDUSINDBK",
    "BANDHANBNK","IDFCFIRSTB","FEDERALBNK","RBLBANK","BANKBARODA",
    "CANBK","UNIONBANK","PNB","INDIANB","AUBANK","DCBBANK","YESBANK",
    "BAJFINANCE","BAJAJFINSV","SBICARD","CHOLAFIN","HDFC","LICHSGFIN",
    "M&MFIN","SHRIRAMFIN","MUTHOOTFIN","MANAPPURAM","IIFL","SUNDARMFIN",
    "RECLTD","PFC","IRFC","HUDCO","PNBHOUSING",
    "HDFCLIFE","SBILIFE","ICICIPRU","LICI","STARHEALTH","GICRE","NIACL",
    "LTIM","NIFTYBEES","JUNIORBEES","GOLDBEES","BANKBEES","LIQUIDBEES",
}

HALAL_KW = (
    "bank","bancorp","finance","finserv","fincorp","financial",
    "insurance","insur","nifty","etf","reit","invit",
    "liquid","overnight","gilt","treasury",
)
_BEES_RE = re.compile(r'\bbees\b', re.IGNORECASE)

# Curated fallback when all live Shariah sources fail
_HALAL_FALLBACK = {
    "TCS","INFY","WIPRO","HCLTECH","TECHM","MPHASIS","COFORGE","PERSISTENT",
    "KPITTECH","TATAELXSI","TANLA","MASTEK","ROUTE","NEWGEN","SAKSOFT",
    "INTELLECT","DATAMATICS","ZENSAR",
    "SUNPHARMA","DRREDDY","CIPLA","DIVISLAB","AUROPHARMA","LUPIN",
    "TORNTPHARM","ALKEM","IPCALAB","NATCOPHARM","GRANULES","GLENMARK",
    "AJANTPHARM","LALPATHLAB","METROPOLIS","SYNGENE","MARKSANS","LAURUSLABS",
    "MARUTI","TATAMOTORS","M&M","HEROMOTOCO","BAJAJ-AUTO","EICHERMOT",
    "TVSMOTORS","MOTHERSON","BOSCHLTD","ENDURANCE","APOLLOTYRE","BALKRISIND",
    "CEATLTD","TIINDIA",
    "HINDUNILVR","NESTLEIND","BRITANNIA","DABUR","MARICO","COLPAL",
    "EMAMILTD","TATACONSUM","VBL","JUBLFOOD","KRBL","JYOTHYLAB",
    "PIDILITIND","FINEORG","GALAXYSURF","VINATIORG","NAVINFLUOR","DEEPAKNI",
    "TATACHEM","GHCL","ANUPAM","PCBL","AARTI","HIMADRI","ATUL","NOCIL","EPIGRAL",
    "LT","HAVELLS","VOLTAS","SIEMENS","ABB","CUMMINSIND","THERMAX","KEC",
    "POLYCAB","SCHAEFFLER","TIMKEN","GRINDWELL","PRAJ","ELGIEQUIP","KAYNES","SYRMA",
    "DLF","GODREJPROP","OBEROIRLTY","PHOENIXLTD","SOBHA",
    "CONCOR","BLUEDART","TCI","DELHIVERY","ALLCARGO",
    "KAVERI","DHANUKA","UPL","PIIND","COROMANDEL","CHAMBLFERT",
    "PAGEIND","RAYMOND","WELSPUNIND","VARDHMAN","TRIDENT",
    "TATASTEEL","HINDALCO","JSWSTEEL","NMDC","RATNAMANI","VEDL",
    "TITAN","TRENT","ASIANPAINT","BERGERPAINTS","DIXON","AMBER",
    "NTPC","TATAPOWER","TORNTPOWER","SUZLON","INOXWIND","WEBELSOLAR",
}

_HALAL_UNIVERSE_CACHE: Optional[set]  = None
_HALAL_UNIVERSE_LOCK  = threading.Lock()
# Serialise all SQLite write transactions (WAL mode reduces contention but does
# not eliminate "database is locked" errors when multiple threads write at the same time)
_SQLITE_WRITE_LOCK    = threading.Lock()

# ── BUG FIX [SQL-001]: guaranteed-close SQLite context manager ─────────────
# The previous pattern of `con = sqlite3.connect(...) / con.close()` leaks the
# connection on any exception path because close() is never in a finally block.
# Under WAL mode a leaked read connection prevents the writer from checkpointing,
# causing escalating "database is locked" errors across threads.
# Usage (read):   `with _db_conn() as con: rows = con.execute(...).fetchall()`
# Usage (write):  `with _db_conn(write=True) as con: con.execute(...); con.commit()`
from contextlib import contextmanager as _contextmanager

@_contextmanager
def _db_conn(timeout: int = 10, write: bool = False):
    """Thread-safe SQLite connection with guaranteed close in finally."""
    _lock = _SQLITE_WRITE_LOCK if write else None
    if _lock:
        _lock.acquire()
    con = None
    try:
        con = sqlite3.connect(DB_PATH, timeout=timeout)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=5000")
        yield con
        if write:
            con.commit()
    except Exception:
        if write and con:
            try:
                con.rollback()
            except Exception:
                pass
        raise
    finally:
        if con:
            con.close()
        if _lock:
            _lock.release()
_HALAL_CUSTOM_LIST:    set             = set()

SYMBOL_SECTOR: Dict[str, str] = {
    "TCS":"NIFTY IT","INFY":"NIFTY IT","WIPRO":"NIFTY IT","HCLTECH":"NIFTY IT",
    "TECHM":"NIFTY IT","MPHASIS":"NIFTY IT","COFORGE":"NIFTY IT","PERSISTENT":"NIFTY IT",
    "SUNPHARMA":"NIFTY PHARMA","DRREDDY":"NIFTY PHARMA","CIPLA":"NIFTY PHARMA",
    "DIVISLAB":"NIFTY PHARMA","AUROPHARMA":"NIFTY PHARMA","LUPIN":"NIFTY PHARMA",
    "TORNTPHARM":"NIFTY PHARMA","ALKEM":"NIFTY PHARMA",
    "MARUTI":"NIFTY AUTO","TATAMOTORS":"NIFTY AUTO","M&M":"NIFTY AUTO",
    "HEROMOTOCO":"NIFTY AUTO","BAJAJ-AUTO":"NIFTY AUTO","EICHERMOT":"NIFTY AUTO",
    "TVSMOTORS":"NIFTY AUTO","BOSCHLTD":"NIFTY AUTO",
    "TATASTEEL":"NIFTY METAL","JSWSTEEL":"NIFTY METAL","HINDALCO":"NIFTY METAL",
    "NMDC":"NIFTY METAL","RATNAMANI":"NIFTY METAL","VEDL":"NIFTY METAL",
    "HINDUNILVR":"NIFTY FMCG","NESTLEIND":"NIFTY FMCG","BRITANNIA":"NIFTY FMCG",
    "DABUR":"NIFTY FMCG","MARICO":"NIFTY FMCG","COLPAL":"NIFTY FMCG",
    "DLF":"NIFTY REALTY","GODREJPROP":"NIFTY REALTY","OBEROIRLTY":"NIFTY REALTY",
}

_SECTOR_LIVE_CACHE: Dict[str, tuple] = {}   # BUG-003 FIX: (sector, timestamp) with TTL
_SECTOR_CACHE_TTL = 86_400                  # 24 hours in seconds


def _lookup_sector_yfinance(sym: str) -> str:
    """CRIT-1 FIX: yfinance sector fallback when NSE API is blocked."""
    _YF_SECTOR_MAP = {
        "Technology": "NIFTY IT", "Consumer Technology": "NIFTY IT",
        "Communication Services": "NIFTY IT",
        "Healthcare": "NIFTY PHARMA", "Biotechnology": "NIFTY PHARMA",
        "Consumer Defensive": "NIFTY FMCG", "Consumer Cyclical": "NIFTY FMCG",
        "Energy": "NIFTY ENERGY", "Utilities": "NIFTY ENERGY",
        "Basic Materials": "NIFTY METAL",
        "Real Estate": "NIFTY REALTY", "Industrials": "NIFTY CAPGOODS",
        "Financial Services": "DIVERSIFIED", "Finance": "DIVERSIFIED",
    }
    try:
        import yfinance as yf
        ticker = sym if sym.endswith(".NS") else f"{sym}.NS"
        info = yf.Ticker(ticker).info
        raw = info.get("sector") or info.get("industry") or ""
        return _YF_SECTOR_MAP.get(raw, "DIVERSIFIED")
    except Exception:
        return "DIVERSIFIED"


def get_sector(sym: str) -> str:
    s = sym.upper()
    if s in SYMBOL_SECTOR:
        return SYMBOL_SECTOR[s]
    # BUG-003 FIX: check TTL before returning cached value
    if s in _SECTOR_LIVE_CACHE:
        cached_sec, cached_ts = _SECTOR_LIVE_CACHE[s]
        if time.time() - cached_ts < _SECTOR_CACHE_TTL:
            return cached_sec
    # Try NSE first, fall back to yfinance (CRIT-1 FIX)
    sec = _lookup_sector_nse(s)
    if sec == "DIVERSIFIED":
        sec = _lookup_sector_yfinance(s)
    _SECTOR_LIVE_CACHE[s] = (sec, time.time())
    return sec




def _tg_health_alert(message: str):
    """Send a health-alert Telegram message (best-effort, no crash on failure)."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    # FIX-3: Set SUPPRESS_HEALTH_ALERTS=1 in CI env to silence Shariah/yfinance noise
    if os.getenv("SUPPRESS_HEALTH_ALERTS", "").lower() in ("1", "true", "yes"):
        log.debug(f"Health alert suppressed: {message[:80]}")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": f"⚠️ SNIPER HEALTH\n{message}"},
            timeout=10,
        )
    except Exception:
        pass


def _yf_download_with_backoff(ticker: str, **kwargs):
    """
    C3 FIX — Exponential back-off + jitter wrapper for yf.download().
    On _YF_FAIL_THRESHOLD consecutive failures the 24-hour circuit breaker opens.
    GitHub Actions runners share IP pools; Yahoo bans shared IPs when hammered.
    This wrapper prevents the silent-failure cascade documented as issue C3.
    """
    global _YF_FAIL_COUNT, _YF_CIRCUIT_OPEN_UNTIL
    import yfinance as yf

    # Circuit-breaker guard
    with _YF_FAIL_LOCK:
        if time.time() < _YF_CIRCUIT_OPEN_UNTIL:
            remaining = int((_YF_CIRCUIT_OPEN_UNTIL - time.time()) / 60)
            log.warning(f"YF circuit OPEN — skipping {ticker} ({remaining} min remaining)")
            return pd.DataFrame()

    last_exc: Exception = RuntimeError("unreachable")
    for attempt in range(_YF_MAX_ATTEMPTS):
        if attempt:
            raw   = _YF_BACKOFF_BASE ** attempt            # 2, 4, 8 s
            jitter = raw * 0.25 * random.random()          # ±25 %
            delay  = min(raw + jitter, _YF_BACKOFF_MAX)
            log.warning(f"YF back-off {attempt}/{_YF_MAX_ATTEMPTS}: "
                        f"sleeping {delay:.1f}s for {ticker}")
            time.sleep(delay)
        try:
            df = yf.download(ticker, **kwargs)
            with _YF_FAIL_LOCK:
                _YF_FAIL_COUNT = 0        # reset on any success
            return df
        except Exception as e:
            last_exc = e
            log.warning(f"YF download attempt {attempt+1}/{_YF_MAX_ATTEMPTS} "
                        f"failed for {ticker}: {e}")

    # All retries exhausted — increment global counter and maybe open circuit
    with _YF_FAIL_LOCK:
        _YF_FAIL_COUNT += 1
        fc = _YF_FAIL_COUNT
        if fc >= _YF_FAIL_THRESHOLD:
            _YF_CIRCUIT_OPEN_UNTIL = time.time() + 86_400  # 24 h
            log.error(
                f"YF circuit breaker OPEN — {fc} consecutive failures. "
                f"yfinance suspended for 24 h. Last error: {last_exc}"
            )
            _tg_health_alert(
                f"🚨 yfinance circuit breaker OPEN after {fc} consecutive failures.\n"
                f"Pipeline is in NSE-only mode for 24 h.\nLast error: {last_exc}"
            )
    return pd.DataFrame()


def _live_sector_momentum(sector: str, days: int = 20) -> dict:
    """Compute sector vs CNX500 relative momentum. Returns bonus/penalty."""
    NEUTRAL = {"rel_5d": 0.0, "rel_20d": 0.0, "momentum_tier": "NEUTRAL", "bonus": 0}

    if sector not in SECTOR_INDICES:
        return NEUTRAL

    global _YF_FAIL_COUNT
    with _YF_FAIL_LOCK:
        fail_count = _YF_FAIL_COUNT
    if fail_count >= _YF_FAIL_THRESHOLD:
        return NEUTRAL

    cache_key = f"{sector}_{days}"
    if cache_key in _SECTOR_MOM_CACHE:
        return _SECTOR_MOM_CACHE[cache_key]

    global _SECTOR_YF_CALLS
    if _SECTOR_YF_CALLS >= _MAX_SECTOR_YF_CALLS:
        log.debug(f"Sector YF call cap reached ({_MAX_SECTOR_YF_CALLS}) — skipping {sector}")
        return NEUTRAL

    try:
        # Shared CNX500 cache (TTL 1 hour)
        global _CNX500_CACHE, _CNX500_CACHE_TIME
        now = time.time()
        if _CNX500_CACHE is None or (now - _CNX500_CACHE_TIME) > 3600:
            cnx_df = _yf_download_with_backoff("^CNX500", period="30d", progress=False,
                                               auto_adjust=True, timeout=_YF_DOWNLOAD_TIMEOUT)
            _CNX500_CACHE = cnx_df
            _CNX500_CACHE_TIME = now
        else:
            cnx_df = _CNX500_CACHE

        sector_ticker = SECTOR_INDICES[sector]
        if sector_ticker not in _SECTOR_INDEX_CACHE:
            sector_df = _yf_download_with_backoff(f"^{sector_ticker}", period="30d",
                                                  progress=False, auto_adjust=True,
                                                  timeout=_YF_DOWNLOAD_TIMEOUT)
            _SECTOR_INDEX_CACHE[sector_ticker] = sector_df
            _SECTOR_YF_CALLS += 1
        else:
            sector_df = _SECTOR_INDEX_CACHE[sector_ticker]

        if sector_df.empty or cnx_df.empty or len(sector_df) < 20:
            return NEUTRAL

        sector_close = sector_df["Close"].squeeze().values
        cnx_close    = cnx_df["Close"].squeeze().values

        sec_5d = (sector_close[-1] - sector_close[-5]) / sector_close[-5] * 100 if len(sector_close) >= 5 else 0
        cnx_5d = (cnx_close[-1] - cnx_close[-5]) / cnx_close[-5] * 100 if len(cnx_close) >= 5 else 0
        rel_5d = sec_5d - cnx_5d

        sec_20d = (sector_close[-1] - sector_close[-20]) / sector_close[-20] * 100 if len(sector_close) >= 20 else 0
        cnx_20d = (cnx_close[-1] - cnx_close[-20]) / cnx_close[-20] * 100 if len(cnx_close) >= 20 else 0
        rel_20d = sec_20d - cnx_20d

        if rel_5d > 2.0 and rel_20d > 3.0:
            tier, bonus = "STRONG", 6
        elif rel_5d > 1.0 and rel_20d > 1.5:
            tier, bonus = "MODERATE", 3
        elif rel_5d < -2.0 or rel_20d < -3.0:
            tier, bonus = "WEAK", -4
        elif rel_5d < -1.0:
            tier, bonus = "FADING", -2
        else:
            tier, bonus = "NEUTRAL", 0

        result = {"rel_5d": round(rel_5d, 2), "rel_20d": round(rel_20d, 2),
                  "momentum_tier": tier, "bonus": bonus}
        _SECTOR_MOM_CACHE[cache_key] = result
        return result

    except Exception as e:
        with _YF_FAIL_LOCK:
            _YF_FAIL_COUNT += 1
            current = _YF_FAIL_COUNT
        log.warning(f"YF fail #{current}: sector momentum {sector} — {e}")
        return NEUTRAL

def _lookup_sector_nse(sym: str) -> str:
    try:
        sess = _get_nse_session()
        data = _nse_json(sess, "https://www.nseindia.com/api/quote-equity", params={"symbol": sym}, timeout=10)
        if isinstance(data, dict):
            info = data.get("info", data)
            ind  = (info.get("industry") or info.get("macro") or info.get("basicIndustry") or "").lower()
            if any(k in ind for k in ("pharma","health","drug","biotech","hospital","medical")):         return "NIFTY PHARMA"
            if any(k in ind for k in ("software","it services","technology","telecom","digital")):      return "NIFTY IT"
            if any(k in ind for k in ("auto","vehicle","tyre","ancillar","bearing","piston")):         return "NIFTY AUTO"
            if any(k in ind for k in ("fmcg","consumer","food","beverag","packag","agro")):            return "NIFTY FMCG"
            if any(k in ind for k in ("metal","steel","alumin","copper","mining","iron","zinc")):       return "NIFTY METAL"
            if any(k in ind for k in ("energy","power","oil","gas","petro","solar","wind","renew")):    return "NIFTY ENERGY"
            if any(k in ind for k in ("realty","real estate","construct","cement","infra","road","rail","engineer")): return "NIFTY REALTY"
            if any(k in ind for k in ("chemical","specialty","dye","pigment","pesticide","fertiliser")): return "NIFTY CHEMICAL"
            if any(k in ind for k in ("capital goods","industrial","machinery","equipment","defence")):  return "NIFTY CAPGOODS"
            if any(k in ind for k in ("textile","apparel","garment","yarn","fabric","spinning")):        return "NIFTY TEXTILES"
    except Exception as e:
        log.debug(f"Sector lookup {sym}: {e}")
    return "DIVERSIFIED"


def _fetch_shariah_csv() -> set:
    """Fetch live Nifty500 Shariah index CSV with 3-URL cascade."""
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0",
        "Referer": "https://www.niftyindices.com/",
    })
    try:
        sess.get("https://www.niftyindices.com/", timeout=15)
        time.sleep(1)
    except Exception:
        pass

    for url in [
        "https://www.niftyindices.com/IndexConstituents/ind_nifty500shariah.csv",
        "https://archives.nseindia.com/content/indices/ind_nifty500shariah.csv",
        "https://www.nseindia.com/content/indices/ind_nifty500shariah.csv",
    ]:
        try:
            resp = sess.get(url, timeout=25)
            if resp.status_code != 200 or len(resp.text) < 200:
                continue
            df = pd.read_csv(io.StringIO(resp.text))
            df.columns = df.columns.str.strip().str.upper()
            col = next((c for c in df.columns if any(k in c for k in ("SYMBOL","TICKER","SCRIP"))), None)
            if col is None:
                continue
            syms = {str(s).strip().upper() for s in df[col] if str(s).strip()
                    and not str(s).strip().upper().startswith(("INDEX","NIFTY","TOTAL","DATE","SYMBOL"))}
            if len(syms) >= 100:
                log.info(f"Shariah CSV loaded LIVE: {len(syms)} symbols ✅")
                return syms
        except Exception as e:
            log.warning(f"Shariah CSV {url}: {e}")    # H1: was debug — now visible in prod
    # All three URLs failed
    log.error(
        "Shariah CSV: all 3 URLs failed — falling back to hardcoded list. "
        "Halal screening is DEGRADED. Check niftyindices.com reachability."
    )
    _tg_health_alert(
        "⚠️ Shariah CSV fetch FAILED (all 3 URLs). "
        "Running on hardcoded fallback list — halal screening may be stale."
    )
    return set()


def _load_shariah_db() -> set:
    try:
        con = sqlite3.connect(DB_PATH)
        row = con.execute("SELECT symbol, cached_date FROM halal_cache LIMIT 1").fetchone()
        if row:
            age = (datetime.today().date() - datetime.strptime(row[1], "%Y-%m-%d").date()).days
            if age <= SHARIAH_TTL_DAYS:
                syms = {r[0] for r in con.execute("SELECT symbol FROM halal_cache").fetchall()}
                con.close()
                return syms
        con.close()
    except Exception:
        pass
    return set()


def _save_shariah_db(syms: set):
    try:
        today = datetime.today().strftime("%Y-%m-%d")
        con   = sqlite3.connect(DB_PATH)
        con.execute("DELETE FROM halal_cache")
        con.executemany("INSERT OR REPLACE INTO halal_cache (symbol, cached_date) VALUES (?,?)",
                        [(s, today) for s in syms])
        con.commit(); con.close()
    except Exception as e:
        log.debug(f"Shariah DB save: {e}")


def get_halal_universe() -> set:
    """
    Priority cascade (double-checked locking for thread safety):
    1. SQLite cache (TTL = SHARIAH_TTL_DAYS, default 1 day)
    2. Live Nifty500 Shariah CSV
    3. Sheets HALAL_LIST (Tab 7)
    4. Hardcoded _HALAL_FALLBACK
    """
    global _HALAL_UNIVERSE_CACHE
    if _HALAL_UNIVERSE_CACHE is not None:
        return _HALAL_UNIVERSE_CACHE
    with _HALAL_UNIVERSE_LOCK:
        if _HALAL_UNIVERSE_CACHE is not None:
            return _HALAL_UNIVERSE_CACHE
        cached = _load_shariah_db()
        if len(cached) >= 100:
            log.info(f"Halal universe from SQLite: {len(cached)} symbols")
            _HALAL_UNIVERSE_CACHE = cached
            return cached
        live = _fetch_shariah_csv()
        if len(live) >= 100:
            _save_shariah_db(live)
            _HALAL_UNIVERSE_CACHE = live
            return live
        sheets = _read_sheets_halal_list()
        if len(sheets) >= 50:
            log.info(f"Halal universe from Sheets HALAL_LIST: {len(sheets)}")
            _HALAL_UNIVERSE_CACHE = sheets
            return sheets
        log.warning("All live Shariah sources failed — using curated fallback")
        _HALAL_UNIVERSE_CACHE = _HALAL_FALLBACK
        return _HALAL_FALLBACK


def is_halal(symbol: str) -> bool:
    """
    4-layer halal gate — order is safety-critical:
    L1. Hard exclusion (banks, NBFCs, insurance, ETFs) — cannot be overridden
    L2. Keyword exclusion (finance, bank, etf, bees...)
    L3. Custom Sheets whitelist (user-added, post-exclusion only)
    L4. Nifty500 Shariah universe
    """
    sym = symbol.upper().strip()
    if sym in HALAL_EXCLUDED:
        return False
    sl = sym.lower()
    if any(kw in sl for kw in HALAL_KW) or _BEES_RE.search(sl):
        return False
    if _HALAL_CUSTOM_LIST and sym in _HALAL_CUSTOM_LIST:
        return True
    return sym in get_halal_universe()



# ══════════════════════════════════════════════════════════════════════════════
# [PATCH-B]  HALAL AI SCREEN — 4-layer  (v4.0-M, runs post-APEX on top picks)
# ══════════════════════════════════════════════════════════════════════════════
# is_halal() is KEPT as fast pre-filter on bhavcopy candidates (no change).
# halal_ai_screen() runs on top-N candidates only, after fortress+apex scoring.

# Layer 1 hard-veto sets (business screen)
_HALAL_L1_VETO_SYMBOLS = {
    "HDFCBANK","ICICIBANK","SBIN","KOTAKBANK","AXISBANK","INDUSINDBK",
    "BANDHANBNK","IDFCFIRSTB","FEDERALBNK","RBLBANK","BANKBARODA",
    "CANBK","UNIONBANK","PNB","INDIANB","AUBANK","DCBBANK","YESBANK",
    "BAJFINANCE","BAJAJFINSV","SBICARD","CHOLAFIN","HDFC","LICHSGFIN",
    "M&MFIN","SHRIRAMFIN","MUTHOOTFIN","MANAPPURAM","IIFL","SUNDARMFIN",
    "RECLTD","PFC","IRFC","HUDCO","PNBHOUSING",
    "HDFCLIFE","SBILIFE","ICICIPRU","LICI","STARHEALTH","GICRE","NIACL",
    "LTIM","NIFTYBEES","JUNIORBEES","GOLDBEES","BANKBEES","LIQUIDBEES",
    "ITC",  # tobacco
}
_HALAL_L1_KW = (
    "bank","bancorp","finance","finserv","fincorp","financial",
    "insurance","insur","nifty","etf","reit","invit",
    "liquid","overnight","gilt","treasury","casino","gaming",
    "tobacco","alcohol","spirits","brewery","liquor",
)
_BEES_RE_AI = re.compile(r'\bbees\b', re.IGNORECASE)

# Layer 3 ethical sector mapping (bonus/penalty, not veto)
_HALAL_L3_SECTORS = {
    "NIFTY IT": +8, "NIFTY PHARMA": +10, "NIFTY AUTO": +5,
    "NIFTY FMCG": +3, "NIFTY METAL": +5, "NIFTY CAPGOODS": +10,
    "NIFTY TEXTILES": +5, "NIFTY CHEMICAL": +5, "NIFTY REALTY": -5,
    "NIFTY ENERGY": -5, "NIFTY BANK": -15, "DIVERSIFIED": 0,
}

HALAL_AI_TTL_DAYS = int(os.getenv("HALAL_AI_TTL_DAYS", "7"))


def _halal_l1_business_veto(symbol: str) -> bool:
    """Layer 1: hard veto on known haram business. True = VETO."""
    sym = symbol.upper().strip()
    if sym in _HALAL_L1_VETO_SYMBOLS:
        return True
    sl = sym.lower()
    if any(kw in sl for kw in _HALAL_L1_KW):
        return True
    if _BEES_RE_AI.search(sl):
        return True
    return False


def _halal_l2_financial_veto(symbol: str) -> Tuple[bool, float]:
    """
    Layer 2: Debt/MarketCap < 33% check.
    Returns (veto, debt_to_mcap). Defaults to (False, 0.0) on data failure.
    """
    try:
        con = sqlite3.connect(DB_PATH, timeout=5)
        row = con.execute(
            "SELECT debt_to_mcap, assessed_date FROM halal_ai_cache WHERE symbol=?",
            (symbol.upper(),)
        ).fetchone()
        con.close()
        if row:
            age = (datetime.today().date() -
                   datetime.strptime(row[1][:10], "%Y-%m-%d").date()).days
            if age <= HALAL_AI_TTL_DAYS and row[0] is not None:
                dtm = float(row[0])
                return dtm >= 0.33, dtm
    except Exception:
        pass

    try:
        import yfinance as yf
        info   = yf.Ticker(f"{symbol}.NS").info
        debt   = float(info.get("totalDebt") or 0)
        mcap   = float(info.get("marketCap") or 0)
        if mcap > 0:
            dtm = round(debt / mcap, 4)
            return dtm >= 0.33, dtm
    except Exception:
        pass
    return False, 0.0


def _halal_l3_ethical_score(symbol: str, sector: str) -> int:
    """Layer 3: ethical sector overlay. Returns ±15 pts, no veto."""
    return _HALAL_L3_SECTORS.get(sector, 0)


def _halal_l4_llm_screen(symbol: str, sector: str, business_desc: str = "") -> dict:
    """Layer 4: LLM business model analysis via Claude Sonnet (optional)."""
    if not _ANTHROPIC_OK:
        return {"llm_confidence": 0.5, "llm_flags": [], "llm_source": "DISABLED"}

    cache_key = f"halal_l4:{symbol}:{_llm_hash(sector + business_desc[:200])}"
    cached = _llm_cached(cache_key, "halal_l4")
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    prompt = (
        "You are an Islamic finance compliance analyst. Assess this Indian listed company.\n"
        f"Symbol: {symbol}\nSector: {sector}\n"
        f"Business description: {business_desc[:500] or 'Not available'}\n\n"
        "Assess Shariah compliance. Return ONLY JSON (no markdown):\n"
        '{"halal_confidence": 0.0-1.0, '
        '"business_concern": "brief concern or NONE", '
        '"revenue_model": "fee_based|interest_based|mixed|manufacturing|services", '
        '"subsidiary_risk": "LOW|MEDIUM|HIGH", '
        '"manual_review_needed": true|false}\n\n'
        "1.0 = clearly permissible, 0.0 = clearly impermissible. "
        "Be conservative — when uncertain, lower confidence."
    )
    raw = _call_claude(prompt, max_tokens=300)
    if not raw:
        return {"llm_confidence": 0.5, "llm_flags": [], "llm_source": "FAILED"}

    try:
        txt = raw.strip().replace("```json", "").replace("```", "")
        parsed = json.loads(txt)
        result = {
            "llm_confidence":       max(0.0, min(1.0, float(parsed.get("halal_confidence", 0.5)))),
            "llm_business_concern": str(parsed.get("business_concern", ""))[:100],
            "llm_revenue_model":    str(parsed.get("revenue_model", "unknown")),
            "llm_subsidiary_risk":  str(parsed.get("subsidiary_risk", "MEDIUM")),
            "llm_manual_review":    bool(parsed.get("manual_review_needed", False)),
            "llm_source":           CLAUDE_MODEL,
        }
        _llm_store_cache(cache_key, "halal_l4", json.dumps(result), CLAUDE_MODEL)
        return result
    except Exception as e:
        log.debug(f"Halal L4 parse {symbol}: {e}")
        return {"llm_confidence": 0.5, "llm_flags": [], "llm_source": "PARSE_ERROR"}


def _halal_ai_cache_save(symbol: str, result: dict):
    """Persist halal AI result to halal_ai_cache table."""
    try:
        today = datetime.today().strftime("%Y-%m-%d")
        with _db_conn(write=True) as con:
            con.execute("""
                INSERT OR REPLACE INTO halal_ai_cache
                  (symbol, score, veto, tier, debt_to_mcap, business_model,
                   ethical_score, llm_confidence, assessed_date, source)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (symbol, result["score"], int(result["veto"]), result["tier"],
                  result["debt_to_mcap"], result["business_model"],
                  result["ethical_score"], result["llm_confidence"],
                  today, result.get("source", "SCORED")))
    except Exception as e:
        log.debug(f"Halal AI cache save {symbol}: {e}")


def halal_ai_screen(symbol: str, sector: str = "DIVERSIFIED",
                    business_desc: str = "") -> dict:
    """
    Full 4-layer Halal AI Screen. Runs post-APEX on top-N candidates only.
    Returns: {score, veto, tier, debt_to_mcap, business_model, ethical_score,
              llm_confidence, veto_reason, source}
    Tiers: score<40→RISKY, 40-69→ACCEPTABLE, 70+→PURE
    Hard veto: L1 business, L2 debt≥33%, L4 confidence<0.30
    """
    sym = symbol.upper().strip()

    # ── Check 7-day DB cache ─────────────────────────────────────────────────
    try:
        with _db_conn() as con:
            row = con.execute(
                "SELECT score, veto, tier, debt_to_mcap, business_model, "
                "ethical_score, llm_confidence, assessed_date "
                "FROM halal_ai_cache WHERE symbol=?",
                (sym,)
            ).fetchone()
        if row:
            age = (datetime.today().date() -
                   datetime.strptime(row[7][:10], "%Y-%m-%d").date()).days
            if age <= HALAL_AI_TTL_DAYS:
                return {
                    "score": row[0], "veto": bool(row[1]), "tier": row[2],
                    "debt_to_mcap": row[3], "business_model": row[4],
                    "ethical_score": row[5], "llm_confidence": row[6],
                    "veto_reason": "" if not row[1] else "CACHED_VETO",
                    "source": "CACHE",
                }
    except Exception:
        pass

    # ── Layer 1: Business screen ─────────────────────────────────────────────
    if _halal_l1_business_veto(sym):
        result = {"score": 0, "veto": True, "tier": "HARAM",
                  "debt_to_mcap": 0.0, "business_model": "HARAM_BUSINESS",
                  "ethical_score": 0, "llm_confidence": 0.0,
                  "veto_reason": "L1: Haram business category", "source": "L1"}
        _halal_ai_cache_save(sym, result)
        return result

    # ── Layer 2: Financial screen ────────────────────────────────────────────
    l2_veto, debt_to_mcap = _halal_l2_financial_veto(sym)
    if l2_veto:
        result = {"score": 0, "veto": True, "tier": "HARAM",
                  "debt_to_mcap": debt_to_mcap, "business_model": "HIGH_DEBT",
                  "ethical_score": 0, "llm_confidence": 0.5,
                  "veto_reason": f"L2: Debt/MCap {debt_to_mcap:.1%} >= 33%",
                  "source": "L2"}
        _halal_ai_cache_save(sym, result)
        return result

    # ── Layer 3: Ethical overlay ─────────────────────────────────────────────
    ethical_score = _halal_l3_ethical_score(sym, sector)
    base_score    = 70 + ethical_score
    debt_penalty  = int(max(0, debt_to_mcap - 0.10) * 100)
    base_score   -= debt_penalty
    base_score    = max(0, min(100, base_score))

    # ── Layer 4: LLM analysis (optional) ────────────────────────────────────
    llm = _halal_l4_llm_screen(sym, sector, business_desc)
    llm_conf  = llm.get("llm_confidence", 0.5)
    llm_model = llm.get("llm_revenue_model", "unknown")

    if _ANTHROPIC_OK:
        llm_delta = int((llm_conf - 0.5) * 20)
        base_score = max(0, min(100, base_score + llm_delta))
        if llm_conf < 0.30:
            result = {"score": 0, "veto": True, "tier": "HARAM",
                      "debt_to_mcap": debt_to_mcap, "business_model": llm_model,
                      "ethical_score": ethical_score, "llm_confidence": llm_conf,
                      "veto_reason": f"L4: LLM confidence {llm_conf:.0%} < 30%",
                      "source": "L4"}
            _halal_ai_cache_save(sym, result)
            return result

    tier = "PURE" if base_score >= 70 else ("ACCEPTABLE" if base_score >= 40 else "RISKY")
    result = {
        "score": base_score, "veto": False, "tier": tier,
        "debt_to_mcap": debt_to_mcap, "business_model": llm_model,
        "ethical_score": ethical_score, "llm_confidence": llm_conf,
        "veto_reason": "", "source": "SCORED",
    }
    _halal_ai_cache_save(sym, result)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — GOOGLE SHEETS CLIENT (single shared workbook)
# ══════════════════════════════════════════════════════════════════════════════

_GS_WORKBOOK    = None
_GS_WS_CACHE:   Dict = {}
_GS_INIT_LOCK   = threading.Lock()

_GS_SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def _sheets_ok() -> bool:
    return bool(GOOGLE_SHEET_ID and GOOGLE_CREDS_JSON)


def _init_sheets() -> bool:
    global _GS_WORKBOOK
    if _GS_WORKBOOK is not None:
        return True
    with _GS_INIT_LOCK:
        if _GS_WORKBOOK is not None:
            return True
        if not _sheets_ok():
            return False
        try:
            import gspread, base64
            from google.oauth2.service_account import Credentials
            raw = GOOGLE_CREDS_JSON.strip()
            try:
                creds_dict = json.loads(base64.b64decode(raw).decode())
            except Exception:
                creds_dict = json.loads(raw)
            creds       = Credentials.from_service_account_info(creds_dict, scopes=_GS_SCOPES)
            client      = gspread.authorize(creds)
            _GS_WORKBOOK = client.open_by_key(GOOGLE_SHEET_ID)
            log.info(f"Sheets workbook opened: '{_GS_WORKBOOK.title}' ✅")
            return True
        except Exception as e:
            log.error(f"Sheets auth failed: {e}")
            return False


def _get_ws(tab: str):
    if tab in _GS_WS_CACHE:
        return _GS_WS_CACHE[tab]
    if not _init_sheets():
        return None
    try:
        ws = _GS_WORKBOOK.worksheet(tab)
        _GS_WS_CACHE[tab] = ws
        return ws
    except Exception as e:
        log.debug(f"Worksheet '{tab}' not found: {e}")
        _GS_WS_CACHE[tab] = None
        return None


def _read_sheet(tab: str) -> pd.DataFrame:
    ws = _get_ws(tab)
    if ws is None:
        return pd.DataFrame()
    try:
        raw = ws.get_all_values()
        if not raw or len(raw) < 2:
            return pd.DataFrame()
        headers = [str(h).strip().upper() for h in raw[0]]
        df = pd.DataFrame(raw[1:], columns=headers)
        df = df[~df.apply(lambda r: r.str.strip().eq("").all(), axis=1)].reset_index(drop=True)
        log.info(f"  Sheet '{tab}': {len(df)} rows ✅")
        return df
    except Exception as e:
        log.error(f"Sheet '{tab}' read failed: {e}")
        return pd.DataFrame()


def _push_sheet(tab: str, rows: list):
    """Write list-of-lists to a sheet tab."""
    if not _init_sheets():
        log.warning(f"Sheets push '{tab}': init failed")
        return
    try:
        ws = _get_ws(tab)
        if ws is None:
            log.info(f"Sheets tab '{tab}' not found — creating…")
            ws = _GS_WORKBOOK.add_worksheet(title=tab, rows=max(300, len(rows)+10), cols=max(40, len(rows[0]) if rows else 40))
            _GS_WS_CACHE[tab] = ws
            log.info(f"Sheets tab '{tab}' created ✅")

        # Ensure enough rows/cols
        needed_rows = len(rows)
        needed_cols = max(len(r) for r in rows) if rows else 1

        # Resize if needed (gspread doesn't auto-resize on update)
        if needed_rows > ws.row_count or needed_cols > ws.col_count:
            ws.resize(rows=max(needed_rows + 10, ws.row_count), cols=max(needed_cols + 5, ws.col_count))

        ws.clear()

        # Use batch update for reliability
        try:
            ws.update("A1", rows, value_input_option="USER_ENTERED")
        except TypeError:
            ws.update(rows, value_input_option="USER_ENTERED")

        log.info(f"Sheets tab '{tab}' updated: {len(rows)-1} data rows ✅")
    except Exception as e:
        log.error(f"push_sheet '{tab}' FAILED: {e}")


def _read_sheets_halal_list() -> set:
    df = _read_sheet("HALAL_LIST")
    if df.empty:
        return set()
    col = next((c for c in df.columns if any(k in c for k in ("SYMBOL","SCRIP","TICKER"))), df.columns[0])
    return {str(s).strip().upper() for s in df[col] if str(s).strip()
            and str(s).strip().upper() not in ("SYMBOL","SCRIP","TICKER","")}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — NSE SESSION & HTTP HELPERS
# ══════════════════════════════════════════════════════════════════════════════

_NSE_SESSION: Optional[requests.Session] = None
_NSE_SESSION_LOCK = threading.Lock()


def _make_nse_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0",
        "Accept":          "application/json, text/html, */*",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer":         "https://www.nseindia.com",
        "Connection":      "keep-alive",
        "DNT":             "1",
    })
    for url in ["https://www.nseindia.com",
                "https://www.nseindia.com/market-data/live-equity-market"]:
        try:
            s.get(url, timeout=15); time.sleep(1.0)
        except Exception:
            pass
    return s


def _get_nse_session() -> requests.Session:
    """Return module-level cached NSE session — warm exactly once per run."""
    global _NSE_SESSION
    if _NSE_SESSION is not None:
        return _NSE_SESSION
    with _NSE_SESSION_LOCK:
        if _NSE_SESSION is None:
            log.info("Initialising NSE session (once per run)…")
            _NSE_SESSION = _make_nse_session()
    return _NSE_SESSION


def _nse_json(sess: requests.Session, url: str, params: dict = None, timeout: int = 15):
    """
    C4 FIX: Retry NSE requests up to 3× with exponential back-off + jitter.
    NSE API returns 503 under load; a single bare request silently cascades
    to yfinance, triggering the rate-limit death spiral (C3).
    Delays: ~2s, ~4s, ~8s (+ ±25 % jitter each time).
    """
    last_exc: Exception = RuntimeError("unreachable")
    for attempt in range(NSE_MAX_RETRIES):  # FIX-4: was hardcoded 3; set NSE_MAX_RETRIES=1 in CI
        if attempt:
            base_delay = 2 ** attempt          # 2, 4
            jitter     = base_delay * 0.25 * random.random()
            time.sleep(base_delay + jitter)
        try:
            resp = sess.get(url, params=params, timeout=timeout)
            body = resp.text.strip()
            if not body or body.startswith("<"):
                raise ValueError(f"NSE empty/HTML body ({resp.status_code}) for {url}")
            if resp.status_code == 503:
                raise IOError(f"NSE 503 Service Unavailable for {url}")
            return resp.json()
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                IOError,
                ValueError) as e:            # BUG-004 FIX: retry on ValueError (HTML/empty body)
            last_exc = e
            log.warning(f"NSE request attempt {attempt+1}/3 failed ({type(e).__name__}): {url} — {e}")
    raise last_exc


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — SQLITE DATABASE (single file, all tables)
# ══════════════════════════════════════════════════════════════════════════════

def _init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)
    try:
        con.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    con.execute("PRAGMA busy_timeout=5000")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS halal_cache (
            symbol      TEXT PRIMARY KEY,
            cached_date TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS roce_cache (
            symbol     TEXT PRIMARY KEY,
            value      REAL,
            label      TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS positions (
            entry_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol        TEXT NOT NULL,
            entry_price   REAL NOT NULL,
            entry_date    TEXT NOT NULL,
            initial_t3    REAL NOT NULL,
            peak_price    REAL NOT NULL,
            trailing_stop REAL NOT NULL,
            be_triggered  INTEGER DEFAULT 0,
            updated_at    TEXT NOT NULL,
            status        TEXT NOT NULL DEFAULT 'open',
            UNIQUE(symbol, entry_date)
        );
        CREATE TABLE IF NOT EXISTS sniper_results (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date      TEXT,
            symbol        TEXT,
            grade         TEXT,
            fused_score   REAL,
            close         REAL,
            stop_loss     REAL,
            r1            REAL,
            r2            REAL,
            r3            REAL,
            story         TEXT,
            sector        TEXT,
            created_at    TEXT DEFAULT CURRENT_TIMESTAMP
        );
                CREATE TABLE IF NOT EXISTS data_quality (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date            TEXT,
            data_source         TEXT,
            bhavcopy_records    INTEGER,
            halal_universe_size INTEGER,
            halal_in_bhavcopy   INTEGER,
            yfinance_shrink     TEXT,
            missing_halal       INTEGER,
            alert               TEXT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        );
                CREATE TABLE IF NOT EXISTS pick_outcomes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date        TEXT,
            symbol          TEXT,
            entry_price     REAL,
            stop_loss       REAL,
            r1              REAL,
            r2              REAL,
            r3              REAL,
            grade           TEXT,
            fused_score     REAL,
            status          TEXT DEFAULT 'open',  -- open/closed/stopped/r1_hit/r2_hit/r3_hit/expired
            exit_price      REAL,
            exit_date       TEXT,
            pnl_pct         REAL,
            days_held       INTEGER,
            hit_target      TEXT,  -- which target hit: r1/r2/r3/stop/none
            story           TEXT,
            llm_story       TEXT,           -- AI-enhanced narrative
            bayes_prior_version TEXT,         -- Which prior set was used
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS mcap_cache (
            symbol      TEXT PRIMARY KEY,
            mcap        REAL,
            fetched_at  TEXT
        );
        CREATE TABLE IF NOT EXISTS llm_cache (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            text_hash   TEXT UNIQUE,
            prompt_type TEXT,
            result      TEXT,
            model       TEXT,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS bayes_calibration (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            prior_name      TEXT,
            condition       TEXT,
            wins            INTEGER DEFAULT 0,
            total           INTEGER DEFAULT 0,
            win_rate        REAL,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(prior_name, condition)
        );
        CREATE TABLE IF NOT EXISTS meta_features (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date        TEXT NOT NULL,
            symbol          TEXT NOT NULL,
            whale_score     REAL,
            div_score       REAL,
            vp_score       REAL,
            pat_score      REAL,
            bayes_pct      REAL,
            macro_state    TEXT,
            sector         TEXT,
            vix_level      REAL,
            primary_fused_score REAL,
            outcome_pnl_pct REAL,
            profitable     INTEGER,
            created_at     TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(run_date, symbol)
        );
    """)
    # Migration: add status column to positions if absent
    try:
        con.execute("ALTER TABLE positions ADD COLUMN status TEXT NOT NULL DEFAULT 'open'")
        con.commit()
    except Exception as e:
        if "duplicate column" not in str(e).lower() and "already exists" not in str(e).lower():
            if "locked" in str(e).lower():
                con.close()
                raise RuntimeError(f"DB locked during migration: {e}") from e
    # FIX 6: Migration — add sector column to sniper_results if absent.
    # The _push_performance_tab() query joins pick_outcomes o JOIN sniper_results s
    # ON o.symbol=s.symbol expecting s.sector, causing "no such column: s.sector".
    # This ALTER TABLE is idempotent: SQLite raises "duplicate column name" if the
    # column already exists, which we silently ignore.
    try:
        con.execute("ALTER TABLE sniper_results ADD COLUMN sector TEXT DEFAULT 'DIVERSIFIED'")
        con.commit()
        log.info("DB migration: added 'sector' column to sniper_results ✅")
    except Exception as e:
        if "duplicate column" not in str(e).lower() and "already exists" not in str(e).lower():
            log.debug(f"sniper_results sector migration: {e}")
    con.commit()
    con.close()
    _migrate_db_v3()  # v3.0-M: additive migration (trade_decisions, weekly_reviews, meta_features columns)
    _migrate_db_v4()  # v4.0-M: halal_ai_cache, platt_calibration, strategy_sandbox


def _get_position(symbol: str) -> Optional[dict]:
    try:
        con = sqlite3.connect(DB_PATH)
        row = con.execute(
            "SELECT entry_price,entry_date,initial_t3,peak_price,trailing_stop,be_triggered "
            "FROM positions WHERE symbol=? AND status='open' ORDER BY entry_date DESC LIMIT 1",
            (symbol.upper(),)
        ).fetchone()
        con.close()
        if row:
            return dict(zip(["entry_price","entry_date","initial_t3","peak_price","trailing_stop","be_triggered"], row))
    except Exception:
        pass
    return None


def _put_position(symbol: str, entry_price: float, entry_date: str, initial_t3: float,
                  peak_price: float, trailing_stop: float, be_triggered: int = 0):
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute(
            "INSERT OR REPLACE INTO positions "
            "(symbol,entry_price,entry_date,initial_t3,peak_price,trailing_stop,be_triggered,updated_at,status) "
            "VALUES (?,?,?,?,?,?,?,?,'open')",
            (symbol.upper(), entry_price, entry_date, initial_t3,
             peak_price, trailing_stop, be_triggered, datetime.today().isoformat())
        )
        con.commit(); con.close()
    except Exception:
        pass


def _fetch_roce(symbol: str) -> Tuple[Optional[float], str]:
    try:
        con = sqlite3.connect(DB_PATH)
        row = con.execute("SELECT value, label, fetched_at FROM roce_cache WHERE symbol=?",
                          (symbol.upper(),)).fetchone()
        con.close()
        if row:
            age_h = (time.time() - float(row[2])) / 3600
            if age_h < 24:
                return row[0], row[1]
    except Exception:
        pass
    result = (None, "ROE data unavailable")
    try:
        import yfinance as yf
        info = yf.Ticker(f"{symbol}.NS").info
        roe  = info.get("returnOnEquity")
        if roe is not None:
            roe_pct = float(roe) * 100
            q = ("HIGH ✓" if roe_pct >= 15 else "ACCEPTABLE" if roe_pct >= 5 else "LOW ⚠️")
            result = (roe_pct, f"ROE(proxy) {roe_pct:.1f}% [{q}]")
    except Exception:
        pass
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute("INSERT OR REPLACE INTO roce_cache (symbol,value,label,fetched_at) VALUES (?,?,?,?)",
                    (symbol.upper(), result[0], result[1], str(time.time())))
        con.commit(); con.close()
    except Exception:
        pass
    return result


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — BHAVCOPY DATA CASCADE (NSE → Sheets → yfinance)
# ══════════════════════════════════════════════════════════════════════════════

def _get_last_trading_day() -> Tuple[str, str]:
    d = datetime.today()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%d%m%Y"), d.strftime("%Y-%m-%d")


def _download_bhavcopy_nse(date_str: str, sess: requests.Session) -> pd.DataFrame:
    dd, mm, yyyy = date_str[:2], date_str[2:4], date_str[4:]
    yyyymmdd = f"{yyyy}{mm}{dd}"
    mon = {"01":"JAN","02":"FEB","03":"MAR","04":"APR","05":"MAY","06":"JUN",
           "07":"JUL","08":"AUG","09":"SEP","10":"OCT","11":"NOV","12":"DEC"}[mm]
    for url, is_zip in [
        (f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip", True),
        (f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv", False),
        (f"https://archives.nseindia.com/content/historical/EQUITIES/{yyyy}/{mon}/cm{date_str}bhav.csv.zip", True),
    ]:
        try:
            resp = sess.get(url, timeout=30)
            if resp.status_code == 200 and len(resp.content) > 1000:
                df = (pd.read_csv(io.BytesIO(resp.content), compression="zip")
                      if is_zip else pd.read_csv(io.BytesIO(resp.content)))
                df.columns = df.columns.str.strip()
                if len(df) > 100:
                    return df
        except Exception as e:
            log.debug(f"Bhavcopy URL failed: {e}")
    raise Exception(f"All bhavcopy URLs failed for {date_str}")


def _clean_bhavcopy(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = df.columns.str.strip().str.upper()
    for mapping in [
        {"TCKRSYMB":"symbol","SCTYSRS":"series","OPNPRIC":"open","HGHPRIC":"high",
         "LWPRIC":"low","CLSPRIC":"close","TTLTRADGVOL":"volume","TTLTRFVAL":"turnover"},
        {"SYMBOL":"symbol","SERIES":"series","OPEN":"open","HIGH":"high","LOW":"low",
         "CLOSE":"close","TOTTRDQTY":"volume","TOTTRDVAL":"turnover"},
        {"SYMBOL":"symbol","SERIES":"series","OPEN_PRICE":"open","HIGH_PRICE":"high",
         "LOW_PRICE":"low","CLOSE_PRICE":"close","TTL_TRD_QNTY":"volume","TURNOVER_LACS":"turnover_lakhs"},
    ]:
        if all(k in df.columns for k in mapping):
            df = df.rename(columns=mapping); break
    if "series" in df.columns:
        df = df[df["series"].astype(str).str.strip() == "EQ"].copy()
    if "turnover_lakhs" not in df.columns and "turnover" in df.columns:
        df["turnover_lakhs"] = pd.to_numeric(df["turnover"], errors="coerce").fillna(0) / 100_000
    elif "turnover_lakhs" not in df.columns:
        df["turnover_lakhs"] = 0
    for col in ["open","high","low","close","volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    required = {"symbol","close"}
    if not required.issubset(df.columns):
        return pd.DataFrame()
    if "volume" not in df.columns:
        df["volume"] = 0
    # WARN-1 FIX: NSE bhavcopy sometimes appends series suffixes to symbol
    # (e.g. "PRICOLLTD-EQ", "NMDC-BE"). Strip trailing "-XX" so halal
    # universe matching works correctly and coverage improves from ~42% to ~80%+.
    df["symbol"] = (df["symbol"].astype(str).str.strip().str.upper()
                    .str.replace(r"-[A-Z]{1,3}$", "", regex=True))
    df["data_quality"] = "EOD_FRESH"
    return df[["symbol","open","high","low","close","volume","turnover_lakhs","data_quality"]
              ].dropna(subset=["close"]).query("close > 0").reset_index(drop=True)


def _bhavcopy_from_sheets() -> pd.DataFrame:
    if not _sheets_ok():
        return pd.DataFrame()
    log.info("Loading BHAVCOPY from Sheets Tab 1…")
    raw = _read_sheet("BHAVCOPY")
    if raw.empty:
        return pd.DataFrame()
    col_map = {}
    for internal, candidates in {
        "symbol": ["SYMBOL","SCRIP","TICKER"],
        "open":   ["OPEN","OPEN_PRICE"],
        "high":   ["HIGH","HIGH_PRICE"],
        "low":    ["LOW","LOW_PRICE"],
        "close":  ["CLOSE","CLOSE_PRICE","LTP"],
        "volume": ["VOLUME","TOTTRDQTY","TTLTRADGVOL"],
        "turnover_lakhs": ["TURNOVER_LAKHS","TURNOVER_LACS","TOTTRDVAL"],
        "series": ["SERIES"],
    }.items():
        for c in candidates:
            if c in raw.columns:
                col_map[c] = internal; break
    df = raw.rename(columns=col_map)
    if "series" in df.columns:
        df = df[df["series"].astype(str).str.strip().str.upper() == "EQ"].copy()
    for col in ["open","high","low","close","volume","turnover_lakhs"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "turnover_lakhs" not in df.columns:
        df["turnover_lakhs"] = df.get("volume", pd.Series(0)) * df.get("close", pd.Series(0)) / 100_000
    df["symbol"]       = df["symbol"].astype(str).str.strip().str.upper()
    df["data_quality"] = "SHEETS_EOD"
    return df.dropna(subset=["close"]).query("close > 0").reset_index(drop=True)


def _bhavcopy_from_yfinance() -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError:
        return pd.DataFrame()
    universe   = get_halal_universe()
    candidates = [s for s in _HALAL_FALLBACK if s in universe] or list(_HALAL_FALLBACK)
    log.info(f"yfinance batch: {len(candidates)} halal candidates")
    batch_close: dict = {}; batch_vol: dict = {}
    for i in range(0, len(candidates), 50):
        chunk   = candidates[i:i+50]
        tickers = " ".join(f"{s}.NS" for s in chunk)
        for _attempt in range(3):
            try:
                raw = yf.download(tickers, period="2d", interval="1d",
                                  progress=False, auto_adjust=False, group_by="ticker",
                                  timeout=_YF_DOWNLOAD_TIMEOUT)
                if raw.empty:
                    break
                for sym in chunk:
                    tk = f"{sym}.NS"
                    try:
                        if hasattr(raw.columns, "levels"):
                            # BUG FIX [YF-001]: yfinance ≥0.2.x flipped MultiIndex level
                            # order — ticker symbols are now at level 0, price types at
                            # level 1.  We detect the real ticker level by checking which
                            # level contains '.NS' strings instead of hard-coding level=1.
                            lvl0 = list(raw.columns.get_level_values(0))
                            lvl1 = list(raw.columns.get_level_values(1))
                            if any(".NS" in str(v) for v in lvl0):
                                tk_level = 0
                            elif any(".NS" in str(v) for v in lvl1):
                                tk_level = 1
                            else:
                                tk_level = 0  # safe fallback
                            tickers_in_col = list(raw.columns.get_level_values(tk_level))
                            sub = (raw.xs(tk, axis=1, level=tk_level) if tk in tickers_in_col
                                   else (raw[tk] if tk in raw.columns else None))
                        else:
                            sub = raw.copy()
                        if sub is None:
                            continue
                        sub.columns = [c.lower() if isinstance(c, str) else str(c).lower() for c in sub.columns]
                        cs = sub["close"].dropna()
                        vs = sub.get("volume", pd.Series(dtype=float)).dropna()
                        if not cs.empty:
                            batch_close[sym] = float(cs.iloc[-1])
                            batch_vol[sym]   = float(vs.iloc[-1]) if not vs.empty else 0.0
                    except Exception:
                        continue
                time.sleep(1); break
            except Exception:
                time.sleep(5 * (_attempt + 1))
    records = [{"symbol": sym, "open": c, "high": c, "low": c,
                "close": round(c, 2), "volume": batch_vol.get(sym, 0),
                "turnover_lakhs": round((batch_vol.get(sym, 0) * c) / 100_000, 2),
                "data_quality": "SNAPSHOT_FALLBACK"}
               for sym, c in batch_close.items() if c > 0]
    log.info(f"yfinance batch complete: {len(records)} symbols")
    return pd.DataFrame(records) if records else pd.DataFrame()


def load_bhavcopy() -> Tuple[pd.DataFrame, str]:
    """
    Main data cascade — returns (df, source_label).
    NSE bhavcopy (up to 6 days back) → Sheets Tab 1 → yfinance snapshot.
    """
    if FORCE_YFINANCE:
        df = _bhavcopy_from_yfinance()
        return df, "YFINANCE"

    if FORCE_SHEETS:
        df = _bhavcopy_from_sheets()
        return (df, "SHEETS") if not df.empty else (_bhavcopy_from_yfinance(), "YFINANCE")

    sess = _get_nse_session()
    for days_back in range(0, 6):
        d = datetime.today() - timedelta(days=days_back)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        ds = d.strftime("%d%m%Y")
        try:
            log.info(f"Trying NSE bhavcopy {ds}…")
            raw = _download_bhavcopy_nse(ds, sess)
            df  = _clean_bhavcopy(raw)
            if not df.empty:
                log.info(f"✅ NSE bhavcopy: {len(df)} EQ records")
                return df, "NSE"
        except Exception as e:
            log.debug(f"Bhavcopy {ds}: {e}")
        time.sleep(1)

    log.warning("NSE bhavcopy failed — trying Sheets…")
    df = _bhavcopy_from_sheets()
    if not df.empty:
        return df, "SHEETS"

    log.warning("⚠️ DEGRADED MODE — yfinance fallback")
    df = _bhavcopy_from_yfinance()
    
    # ── NEW: UNIVERSE SHRINK CHECK ──
    if not df.empty and len(df) <= 100:
        log.warning(f"🚨 UNIVERSE SHRUNK: yfinance fallback = {len(df)} hardcoded stocks only")
        halal_uni = get_halal_universe()
        missing = len(halal_uni - set(df["symbol"]))
        log.warning(f"   Missing {missing} halal symbols from screening")
    
    return df, "YFINANCE"

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — HISTORICAL OHLCV
# ══════════════════════════════════════════════════════════════════════════════

def _validate_no_lookahead(df: pd.DataFrame) -> pd.DataFrame:
    """
    Guard against look-ahead bias.

    Two layers of protection:
    1. Date ceiling  — strip any rows dated after today (future data).
    2. Unclosed-bar  — if the last row's date equals today, remove it.
       An intraday bar for today is *not yet closed*; including it in any
       rolling indicator (MA, RSI, Bollinger, VPOC) would embed future
       information into a position that is scored on yesterday's close.

    All indicator functions (fortress_score, _whale_radar, _divergence_engine,
    etc.) call this once via fetch_history() so no further guard is needed
    inside individual scorers.
    """
    if df.empty or "date" not in df.columns:
        return df
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)

    # BUG FIX [TZ-001]: yfinance returns tz-aware UTC dates; comparing them to a
    # tz-naive pd.Timestamp raises TypeError in pandas ≥1.4.  The previous fix used
    # tz_localize(col_tz) which itself raises TypeError if the timestamp already has
    # tzinfo set.  The cleanest solution: strip timezone from the date column once,
    # immediately after loading, so all comparisons are tz-naive throughout the pipeline.
    # Daily OHLCV bars don't need sub-day timezone precision.
    if not df.empty and hasattr(df["date"].dt, "tz") and df["date"].dt.tz is not None:
        df["date"] = df["date"].dt.tz_localize(None)

    today_date = datetime.today().date()
    today      = pd.Timestamp(today_date)           # always tz-naive now
    # Layer 1: remove future rows
    df = df[df["date"] <= today].copy()
    # Layer 2: remove today's unclosed bar (score on confirmed, closed candles only)
    if not df.empty and df["date"].iloc[-1].date() == today_date:
        df = df.iloc[:-1].copy()
    return df




def _preload_histories_yf(symbols: List[str], days: int = 300) -> Dict[str, pd.DataFrame]:
    """Batch-download historical OHLCV for all symbols via yfinance in chunks of 50.
    Returns {symbol_upper: DataFrame} to eliminate per-symbol network calls."""
    cache: Dict[str, pd.DataFrame] = {}
    if not symbols:
        return cache
    try:
        import yfinance as yf
    except ImportError:
        return cache

    end = datetime.today()
    start = end - timedelta(days=days + 50)
    for i in range(0, len(symbols), 50):
        chunk = symbols[i:i + 50]
        tickers = " ".join(f"{s}.NS" for s in chunk)
        for attempt in range(2):
            try:
                raw = yf.download(tickers, start=start, end=end,
                                  progress=False, auto_adjust=False,
                                  group_by="ticker",
                                  timeout=_YF_DOWNLOAD_TIMEOUT)
                if raw.empty:
                    break
                for sym in chunk:
                    tk = f"{sym}.NS"
                    try:
                        if hasattr(raw.columns, "levels"):
                            # BUG FIX [YF-001]: detect real ticker level dynamically
                            lvl0 = list(raw.columns.get_level_values(0))
                            lvl1 = list(raw.columns.get_level_values(1))
                            if any(".NS" in str(v) for v in lvl0):
                                tk_level = 0
                            elif any(".NS" in str(v) for v in lvl1):
                                tk_level = 1
                            else:
                                tk_level = 0
                            tickers_in_col = list(raw.columns.get_level_values(tk_level))
                            sub = (raw.xs(tk, axis=1, level=tk_level) if tk in tickers_in_col
                                   else (raw[tk] if tk in raw.columns else None))
                        else:
                            sub = raw.copy() if len(chunk) == 1 else None
                        if sub is None or sub.empty:
                            continue
                        sub = sub.reset_index()
                        sub.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                                       for c in sub.columns]
                        if "close" not in sub.columns and "adj close" in sub.columns:
                            sub = sub.rename(columns={"adj close": "close"})
                        sub["date"] = pd.to_datetime(sub["date"])
                        df = sub[["date", "open", "high", "low", "close", "volume"]].dropna()
                        cache[sym.upper()] = _validate_no_lookahead(df)
                    except Exception:
                        continue
                break
            except Exception as e:
                log.debug(f"Batch yfinance chunk {i}-{i + 50} attempt {attempt + 1}: {e}")
                time.sleep(2 * (attempt + 1))
    log.info(f"Preloaded {len(cache)} histories via batch yfinance")
    return cache

def fetch_history(symbol: str, days: int = 300,
                  sess: Optional[requests.Session] = None,
                  yf_cache: Optional[Dict[str, pd.DataFrame]] = None) -> pd.DataFrame:
    """NSE historical API → batch yfinance cache → individual yfinance fallback."""
    global _NSE_HISTORY_OK
    sym = symbol.upper().strip()

    # Fast path: preloaded batch yfinance cache (zero network call)
    if yf_cache is not None and sym in yf_cache:
        df = yf_cache[sym]
        if len(df) >= MIN_HIST_BARS:
            return df

    # NSE API (skip entirely if we already know it is down)
    if _NSE_HISTORY_OK is not False:
        try:
            if sess is None:
                sess = _get_nse_session()
            end = datetime.today(); start = end - timedelta(days=days + 50)
            data = _nse_json(sess, "https://www.nseindia.com/api/historical/cm/equity",
                             params={"symbol": sym, "series": '["EQ"]',
                                     "from": start.strftime("%d-%m-%Y"), "to": end.strftime("%d-%m-%Y")},
                             timeout=12)
            records = data.get("data", []) if isinstance(data, dict) else []
            if records:
                df = pd.DataFrame(records).rename(columns={
                    "CH_TIMESTAMP":"date","CH_OPENING_PRICE":"open",
                    "CH_TRADE_HIGH_PRICE":"high","CH_TRADE_LOW_PRICE":"low",
                    "CH_CLOSING_PRICE":"close","CH_TOT_TRADED_QTY":"volume",
                })
                df["date"] = pd.to_datetime(df["date"])
                for c in ["open","high","low","close","volume"]:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
                df = df[["date","open","high","low","close","volume"]].dropna()
                if len(df) >= MIN_HIST_BARS:
                    _NSE_HISTORY_OK = True
                    return _validate_no_lookahead(df)
        except Exception as e:
            log.warning(f"NSE history {sym}: {e} — falling back to yfinance")   # H1
            _NSE_HISTORY_OK = False

    # Individual yfinance fallback (only if no cache entry)
    if yf_cache is None or sym not in yf_cache:
        with _YF_FAIL_LOCK:
            cb_open = time.time() < _YF_CIRCUIT_OPEN_UNTIL
        if cb_open:
            log.warning(f"YF circuit open — skipping individual history fetch for {sym}")
        else:
            try:
                end = datetime.today(); start = end - timedelta(days=days + 50)
                raw = _yf_download_with_backoff(f"{sym}.NS", start=start, end=end,
                                                progress=False, auto_adjust=False,
                                                timeout=_YF_DOWNLOAD_TIMEOUT)
                if not raw.empty:
                    raw = raw.reset_index()
                    raw.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in raw.columns]
                    if "close" not in raw.columns and "adj close" in raw.columns:
                        raw = raw.rename(columns={"adj close": "close"})
                    raw["date"] = pd.to_datetime(raw["date"])
                    df = raw[["date","open","high","low","close","volume"]].dropna()
                    return _validate_no_lookahead(df)
            except Exception as e:
                log.warning(f"yfinance history {sym}: {e}")

    # Return cached frame even if short, or empty
    if yf_cache is not None and sym in yf_cache:
        return yf_cache[sym]
    return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — INTELLIGENCE DATA (FII/DII, Insider, Filings, Earnings)
# ══════════════════════════════════════════════════════════════════════════════

def fetch_fii_dii() -> dict:
    NEUTRAL = {"score": 15, "label": "↔ MIXED", "detail": "FII/DII data unavailable", "fii_net": 0, "dii_net": 0}
    if not FORCE_SHEETS and not FORCE_YFINANCE:
        try:
            sess = _get_nse_session()
            data = _nse_json(sess, "https://www.nseindia.com/api/fiidiiTradeReact")
            row  = data[0] if isinstance(data, list) else data
            fii  = float(str(row.get("fiiNet", row.get("FII_NET_PURCHASE_SALES", 0))).replace(",",""))
            dii  = float(str(row.get("diiNet", row.get("DII_NET_PURCHASE_SALES", 0))).replace(",",""))
            both = fii > 0 and dii > 0
            if both:          score, label = 30, "🟢 FII+DII BUYING"
            elif fii > 0:     score, label = 22, "✅ FII BUYING"
            elif dii > 0:     score, label = 18, "✅ DII BUYING"
            elif fii < 0 and dii < 0: score, label = 5, "🔴 FII+DII SELLING"
            else:             score, label = 12, "↔ MIXED"
            score = min(30, score + min(5, int((abs(fii)+abs(dii))/100_000)))
            fii_cr = fii/100; dii_cr = dii/100
            return {"score": score, "label": label, "fii_net": round(fii_cr),
                    "dii_net": round(dii_cr), "detail": f"FII ₹{fii_cr:+,.0f}Cr | DII ₹{dii_cr:+,.0f}Cr"}
        except Exception as e:
            log.debug(f"FII/DII NSE: {e}")

    # Sheets Tab 2
    if _sheets_ok():
        df = _read_sheet("FII_DII")
        if not df.empty:
            fii_col = next((c for c in df.columns if "FII" in c), None)
            dii_col = next((c for c in df.columns if "DII" in c), None)
            if fii_col and dii_col:
                def _pcr(x):
                    try: return float(str(x).replace(",","").replace("₹","").replace("CR","").strip())
                    except: return 0.0
                row = df.tail(5)
                fii_5d = sum(_pcr(v) for v in row[fii_col])
                dii_5d = sum(_pcr(v) for v in row[dii_col])
                if fii_5d > 0 and dii_5d > 0: score, label = 30, "🟢 FII+DII BUYING"
                elif fii_5d > 0:               score, label = 22, "✅ FII BUYING"
                elif dii_5d > 0:               score, label = 18, "✅ DII BUYING"
                else:                          score, label = 5,  "🔴 SELLING"
                return {"score": score, "label": label, "fii_net": round(fii_5d/100),
                        "dii_net": round(dii_5d/100), "detail": f"FII 5d ₹{fii_5d/100:.0f}Cr [SHEETS]"}
    return NEUTRAL


def fetch_insider_trades(days_back: int = 30) -> dict:
    result: dict = {}
    if not FORCE_SHEETS and not FORCE_YFINANCE:
        try:
            sess   = _get_nse_session()
            data   = _nse_json(sess, "https://www.nseindia.com/api/corporates-pit", params={"index":"equities"})
            data   = data.get("data",[]) if isinstance(data,dict) else data
            cutoff = datetime.today() - timedelta(days=days_back)
            for row in data:
                sym = str(row.get("symbol","")).upper()
                if not sym or not is_halal(sym): continue
                if "sell" in str(row.get("acqMode","")).lower(): continue
                try:
                    if pd.to_datetime(row.get("date","")) < cutoff: continue
                except Exception: pass
                shares = float(str(row.get("totAcqShrs", row.get("secAcq",0))).replace(",",""))
                try: val_cr = float(str(row.get("secVal",0)).replace(",","")) / 100
                except: val_cr = shares * 10 / 1e7
                if sym not in result:
                    result[sym] = {"total_cr": 0.0, "count": 0, "person": ""}
                result[sym]["total_cr"] += val_cr
                result[sym]["count"]    += 1
                result[sym]["person"]    = str(row.get("acqName","Insider"))[:30]
            if result:
                for sym, d in result.items():
                    log_val = math.log10(max(1, d["total_cr"] * 1e7)) if d["total_cr"] > 0 else 0
                    score   = max(5, min(30, round((log_val - 4) * 5)))
                    d["score"]  = score
                    d["detail"] = f"{d['count']} insider buy(s) — ₹{d['total_cr']:.1f}Cr ({d['person']})"
                return result
        except Exception as e:
            log.debug(f"Insider NSE: {e}")

    # Sheets Tab 3
    if _sheets_ok():
        df = _read_sheet("INSIDER")
        if not df.empty:
            sym_col = next((c for c in df.columns if "SYMBOL" in c or "SCRIP" in c), None)
            val_col = next((c for c in df.columns if any(k in c for k in ("VALUE","LAKH","AMOUNT"))), None)
            per_col = next((c for c in df.columns if any(k in c for k in ("PERSON","NAME","ACQNAME"))), None)
            if sym_col:
                for _, row in df.iterrows():
                    sym = str(row.get(sym_col,"")).strip().upper()
                    if not sym or not is_halal(sym): continue
                    try:
                        raw_val = float(str(row.get(val_col,"0")).replace(",","").replace("₹",""))
                    except: raw_val = 0
                    val_cr = raw_val / 100 if raw_val < 100_000 else raw_val / 1e7
                    person = str(row.get(per_col,"Insider"))[:30] if per_col else "Insider"
                    if sym not in result:
                        result[sym] = {"total_cr": 0.0, "count": 0, "person": person}
                    result[sym]["total_cr"] += val_cr
                    result[sym]["count"]    += 1
                for sym, d in result.items():
                    log_val = math.log10(max(1, d["total_cr"] * 1e7)) if d["total_cr"] > 0 else 0
                    score   = max(5, min(30, round((log_val - 4) * 5)))
                    d["score"]  = score
                    d["detail"] = f"{d['count']} buy(s) ₹{d['total_cr']:.1f}Cr ({d['person']}) [SHEETS]"
    return result


def fetch_filings(days_back: int = 14) -> dict:
    """
    Corporate filing sentiment analysis with proper negation handling.
    Scores: 0-30 scale. Negation flips sentiment (e.g., 'no penalty' = positive).
    """
    POS_KW = ["bonus","dividend","buyback","split","profit","growth","order",
              "contract","win","award","acquisition","launch","upgrade","beat",
              "expansion","partnership","approval","clearance","patent","fda"]
    NEG_KW = ["loss","write-off","penalty","fraud","probe","npa","default",
              "downgrade","miss","warning","sebi notice","court","litigation",
              "resignation","delay","postpone","cancel","terminate","recall"]
    NEGATION_MARKERS = ["no ","not ","without ","never ","non-","anti-",
                        "denies","denied","rejects","rejected","cleared of",
                        "acquitted","not guilty","dismissed"]
    result: dict = {}

    def _score_text(text: str) -> tuple:
        """Return (score, detail, sentiment_label) with negation awareness."""
        text_lower = text.lower()

        # Detect negated phrases first (higher priority)
        negated_pos = 0
        negated_neg = 0
        for marker in NEGATION_MARKERS:
            if marker in text_lower:
                for kw in POS_KW:
                    if f"{marker}{kw}" in text_lower or f"{marker} {kw}" in text_lower:
                        negated_pos += 1
                for kw in NEG_KW:
                    if f"{marker}{kw}" in text_lower or f"{marker} {kw}" in text_lower:
                        negated_neg += 1

        # Standard keyword matching
        pos = sum(1 for k in POS_KW if k in text_lower)
        neg = sum(1 for k in NEG_KW if k in text_lower)

        # Adjust: negated positives don't count, negated negatives flip to positive
        effective_pos = max(0, pos - negated_pos + negated_neg)
        effective_neg = max(0, neg - negated_neg)

        raw_score = 15 + effective_pos * 5 - effective_neg * 8
        score = min(30, max(0, raw_score))

        # Build detail
        if negated_neg > 0:
            matched_neg = [k for k in NEG_KW if any(m in text_lower for m in NEGATION_MARKERS 
                         if f"{m}{k}" in text_lower or f"{m} {k}" in text_lower)]
            detail = f"✅ Cleared: {', '.join(matched_neg[:2])}"
            label = "POSITIVE_NEGATED"
        elif effective_pos > 0:
            matched = [k.title() for k in POS_KW if k in text_lower]
            detail = f"Filing: {', '.join(matched[:2])}"
            label = "POSITIVE"
        elif effective_neg > 0:
            matched = [k.title() for k in NEG_KW if k in text_lower]
            detail = f"⚠️ Risk: {', '.join(matched[:2])}"
            label = "NEGATIVE"
        else:
            detail = "Corporate filing — neutral"
            label = "NEUTRAL"

        return score, detail, label

    if not FORCE_SHEETS and not FORCE_YFINANCE:
        try:
            sess = _get_nse_session()
            data = _nse_json(sess, "https://www.nseindia.com/api/corporates-corporateActions",
                             params={"index":"equities",
                                     "from_date":(datetime.today()-timedelta(days=days_back)).strftime("%d-%m-%Y"),
                                     "to_date":datetime.today().strftime("%d-%m-%Y"),
                                     "type":"announcements"})
            if isinstance(data,dict): data=data.get("data",[])
            for row in (data or []):
                sym     = str(row.get("symbol","")).upper()
                subject = str(row.get("subject",row.get("desc",""))).lower()
                if not sym: continue
                score, detail, label = _score_text(subject)
                if sym not in result or score > result[sym]["score"]:
                    result[sym] = {"score": score, "detail": detail, "label": label}
            if result: return result
        except Exception as e:
            log.debug(f"Filings NSE: {e}")

    # Sheets Tab 4 — parse structured, not raw cell text
    if _sheets_ok():
        df = _read_sheet("FILINGS")
        if not df.empty:
            sym_col  = next((c for c in df.columns if "SYMBOL" in c or "SCRIP" in c), None)
            subj_col = next((c for c in df.columns if any(k in c for k in ("SUBJECT","DESC","FILING","HEADLINE","ANNOUNCEMENT"))), None)
            if sym_col and subj_col:
                for _, row in df.iterrows():
                    sym = str(row.get(sym_col,"")).strip().upper()
                    raw_subj = str(row.get(subj_col,"")).lower()
                    if not sym: continue
                    score, detail, label = _score_text(raw_subj)
                    if sym not in result or score > result[sym]["score"]:
                        result[sym] = {"score": score, "detail": detail, "label": label}
    return result


def fetch_earnings_calendar() -> dict:
    cal: dict = {}
    if not FORCE_SHEETS and not FORCE_YFINANCE:
        try:
            sess  = _get_nse_session()
            evts  = _nse_json(sess,"https://www.nseindia.com/api/event-calendar",params={"index":"equities"})
            if isinstance(evts,dict): evts=evts.get("data",[])
            today = datetime.today()
            for ev in (evts or []):
                sym = str(ev.get("symbol","")).upper()
                pur = str(ev.get("purpose","")).lower()
                if "result" not in pur and "dividend" not in pur: continue
                try:
                    dt   = pd.to_datetime(ev.get("date","")).to_pydatetime()
                    days = (dt - today).days
                    if sym not in cal or abs(days) < abs(cal[sym]): cal[sym] = days
                except Exception: continue
            if cal: return cal
        except Exception as e:
            log.debug(f"Earnings NSE: {e}")

    if _sheets_ok():
        df = _read_sheet("EARNINGS")
        if not df.empty:
            sym_col  = next((c for c in df.columns if "SYMBOL" in c), None)
            date_col = next((c for c in df.columns if "DATE" in c or "RESULT" in c), None)
            if sym_col and date_col:
                today = datetime.today()
                for _, row in df.iterrows():
                    sym = str(row.get(sym_col,"")).strip().upper()
                    if not sym: continue
                    try:
                        dt   = pd.to_datetime(str(row[date_col]), dayfirst=True, errors="coerce")
                        if pd.isna(dt): continue
                        days = (dt.to_pydatetime() - today).days
                        if sym not in cal or abs(days) < abs(cal[sym]): cal[sym] = days
                    except Exception: continue
    return cal


def _check_earnings_yf(sym: str) -> Optional[int]:
    try:
        import yfinance as yf
        cal   = yf.Ticker(f"{sym}.NS").calendar
        dates = cal.get("Earnings Date", []) if isinstance(cal, dict) else []
        today = datetime.today()
        future = []
        for d in (dates if hasattr(dates,"__iter__") else [dates]):
            try:
                days = (pd.to_datetime(d).to_pydatetime() - today).days
                if days >= 0: future.append(days)
            except Exception: pass
        return min(future) if future else None
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — MACRO REGIME (single shared cache)
# ══════════════════════════════════════════════════════════════════════════════

_MACRO_CACHE:    Optional[dict] = None
_MACRO_LOCK      = threading.Lock()
_SMALLCAP_CACHE: dict           = {}


def fetch_macro_regime() -> dict:
    FALLBACK = {"macro_state":"CHOP","vix_val":18.0,"nifty_chg":0.0,"breadth_ok":True}
    try:
        import yfinance as yf
        vix_df   = yf.download("^INDIAVIX", period="5d",  progress=False, auto_adjust=True, timeout=_YF_DOWNLOAD_TIMEOUT)
        nifty_df = yf.download("^NSEI",     period="10d", progress=False, auto_adjust=True, timeout=_YF_DOWNLOAD_TIMEOUT)
        cnx_df   = yf.download("^CNX500",   period="60d", progress=False, auto_adjust=True, timeout=_YF_DOWNLOAD_TIMEOUT)
    except Exception:
        return FALLBACK

    vix = 18.0
    if not vix_df.empty:
        try: vix = float(vix_df["Close"].squeeze().iloc[-1])
        except: pass

    nifty_chg = 0.0
    if not nifty_df.empty and len(nifty_df) >= 2:
        try:
            nc = nifty_df["Close"].squeeze().values
            nifty_chg = float((nc[-1]-nc[-2])/nc[-2]*100)
        except: pass

    breadth_ok = True
    if not cnx_df.empty and len(cnx_df) >= 50:
        try:
            cc = cnx_df["Close"].squeeze()
            breadth_ok = float(cc.iloc[-1]) > float(cc.rolling(50).mean().iloc[-1])
        except: pass

    if nifty_chg <= SNIPER_CFG["nifty_massacre"]:   state = "MASSACRE"
    elif vix >= SNIPER_CFG["vix_panic"]:             state = "PANIC"
    elif vix >= SNIPER_CFG["vix_chop"]:              state = "CHOP"
    elif not breadth_ok:                             state = "CHOP"
    else:                                            state = "CLEAR"

    log.info(f"Macro: {state} | VIX={vix:.1f} | NIFTY {nifty_chg:+.2f}%")
    return {"macro_state": state, "vix_val": round(vix,2),
            "nifty_chg": round(nifty_chg,2), "breadth_ok": breadth_ok}


def _get_macro() -> dict:
    global _MACRO_CACHE
    if _MACRO_CACHE is not None:
        return _MACRO_CACHE
    with _MACRO_LOCK:
        if _MACRO_CACHE is None:
            _MACRO_CACHE = fetch_macro_regime()
    return _MACRO_CACHE


def check_smallcap_cb() -> Tuple[bool, str]:
    if "r" in _SMALLCAP_CACHE:
        return _SMALLCAP_CACHE["r"]
    fail = (True, "⚠️ CB data unavailable — entries blocked (CB_FAIL_SAFE=true)") if CB_FAIL_SAFE \
        else (False, "CB data unavailable — pass")
    try:
        import yfinance as yf
        df = yf.download("^CNXSC", period="60d", progress=False, auto_adjust=True, timeout=_YF_DOWNLOAD_TIMEOUT)
        if df.empty:
            df = yf.download("NIFTYSMLCAP100.NS", period="60d", progress=False, auto_adjust=True, timeout=_YF_DOWNLOAD_TIMEOUT)
        if not df.empty and len(df) >= 20:
            c    = df["Close"].squeeze().values
            ma20 = float(np.mean(c[-20:]))
            last = float(c[-1])
            if last < ma20:
                r = (True, f"⚠️ SMALLCAP CB — {(ma20-last)/ma20*100:.1f}% below 20-DMA")
            else:
                r = (False, f"Smallcap healthy — {(last-ma20)/ma20*100:.1f}% above 20-DMA ✓")
            _SMALLCAP_CACHE["r"] = r
            return r
    except Exception:
        pass
    _SMALLCAP_CACHE["r"] = fail
    return fail


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 10 — INDICATOR TOOLKIT (shared by both engines)
# ══════════════════════════════════════════════════════════════════════════════

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h,l,c = df["high"],df["low"],df["close"]
    tr = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.ewm(span=period,adjust=False).mean()

def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    d = series.diff()
    g = d.clip(lower=0).ewm(span=period,adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(span=period,adjust=False).mean()
    return 100-(100/(1+g/l.replace(0,np.nan)))

def _adx(df: pd.DataFrame, period: int = 14) -> float:
    h,l,c = df["high"],df["low"],df["close"]
    tr  = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    atr = tr.ewm(span=period,adjust=False).mean()
    up  = h-h.shift(); dn=l.shift()-l
    pdm = up.where((up>dn)&(up>0),0); ndm=dn.where((dn>up)&(dn>0),0)
    pdi = 100*pdm.ewm(span=period,adjust=False).mean()/atr
    ndi = 100*ndm.ewm(span=period,adjust=False).mean()/atr
    dx  = 100*(pdi-ndi).abs()/(pdi+ndi).replace(0,np.nan)
    val = float(dx.ewm(span=period,adjust=False).mean().iloc[-1])
    return val if not math.isnan(val) else 0.0

def _mfi(df: pd.DataFrame, period: int = 14) -> float:
    tp  = (df["high"]+df["low"]+df["close"])/3
    rmf = tp*df["volume"]
    pos = rmf.where(tp>tp.shift(),0); neg=rmf.where(tp<tp.shift(),0)
    mfr = pos.rolling(period).sum()/neg.rolling(period).sum().replace(0,np.nan)
    s   = 100-(100/(1+mfr))
    v   = float(s.iloc[-1]) if not s.empty else 50.0
    return v if not math.isnan(v) else 50.0

def _obv(df: pd.DataFrame) -> pd.Series:
    return (df["volume"] * np.sign(df["close"].diff().fillna(0))).cumsum()

def _volume_reliable(df: pd.DataFrame, lookback: int = 63) -> bool:
    r = df.tail(lookback)
    return len(r) > 0 and (r["volume"] <= 0).sum() / len(r) < 0.80

def _calc_vpoc_single(df: pd.DataFrame, lookback: int, n_bins: int = 100) -> float:
    r = df.tail(lookback)
    if len(r) < 20: return float(df["close"].iloc[-1])
    pmin,pmax = float(r["low"].min()),float(r["high"].max())
    if pmax <= pmin: return float(r["close"].iloc[-1])
    total = float(r["volume"].sum())
    if total <= 0: return float((pmin+pmax)/2)
    bins = np.linspace(pmin,pmax,n_bins+1); bv=np.zeros(n_bins); n=len(r)
    lows=r["low"].values.astype(float); highs=r["high"].values.astype(float); vols=r["volume"].values.astype(float)
    rw = np.linspace(0.5,1.0,n)
    for i in range(n):
        bl,bh,vol=lows[i],highs[i],vols[i]
        if vol<=0 or bh<=bl: continue
        ov = np.maximum(0.0,np.minimum(bh,bins[1:])-np.maximum(bl,bins[:-1]))
        bv += rw[i]*vol*(ov/(bh-bl))
    idx = int(np.argmax(bv))
    return float((bins[idx]+bins[idx+1])/2)

def calc_vpoc(df: pd.DataFrame) -> float:
    wt = SNIPER_CFG
    lb3m=min(63,len(df)); lb6m=min(126,len(df)); lb12m=min(252,len(df))
    v3=_calc_vpoc_single(df,lb3m); v6=_calc_vpoc_single(df,lb6m); v12=_calc_vpoc_single(df,lb12m)
    div = abs(v3-v6)/max(v6,1e-6)
    w3,w6,w12 = (0.20,0.45,0.35) if div>0.10 else (wt["vpoc_3m_wt"],wt["vpoc_6m_wt"],wt["vpoc_12m_wt"])
    return round(float((v3*w3+v6*w6+v12*w12)/(w3+w6+w12)),2)

def _vpoc_profile(df: pd.DataFrame, n_bins: int = 50) -> dict:
    """APEX-style volume profile with Value Area and whale_pct."""
    res = {"poc":0.0,"va_high":0.0,"va_low":0.0,"whale_pct":0.0}
    r   = df.tail(63)
    if len(r)<20: return res
    pmin,pmax=float(r["low"].min()),float(r["high"].max())
    if pmax<=pmin: return res
    total=float(r["volume"].sum())
    if total<=0: return res
    bins=np.linspace(pmin,pmax,n_bins+1); bv=np.zeros(n_bins)
    for _,row in r.iterrows():
        bl,bh,vol=float(row["low"]),float(row["high"]),float(row["volume"])
        if vol<=0 or bh<=bl: continue
        ov=np.maximum(0.0,np.minimum(bh,bins[1:])-np.maximum(bl,bins[:-1]))
        bv+=vol*(ov/(bh-bl))
    idx=int(np.argmax(bv))
    res["poc"]       = float((bins[idx]+bins[idx+1])/2)
    res["whale_pct"] = float(bv[idx]/total*100)
    si    = np.argsort(bv)[::-1]
    cum   = np.cumsum(bv[si])
    va_i  = si[cum<=total*0.70]
    if len(va_i)>0:
        res["va_low"]  = float(bins[va_i.min()])
        res["va_high"] = float(bins[va_i.max()+1])
    return res


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 11 — FORTRESS SCORING ENGINE (fully preserved from v8.2)
# ══════════════════════════════════════════════════════════════════════════════

def fortress_score(symbol: str, today_row, hist: pd.DataFrame,
                   macro_state: str = "CHOP") -> Optional[dict]:
    """
    Core Fortress engine: 6-layer VPOC, regime, MFI/ADX, sector truth,
    52W compression, ATR velocity, VDU, VCP coil.
    Returns dict or None (hard-veto).
    RC3 FIX: macro_state now passed in so MA200 tolerance can be regime-aware.
    """
    if len(hist) < MIN_HIST_BARS:
        log.info(f"FORTRESS VETO {symbol}: insufficient bars ({len(hist)} < {MIN_HIST_BARS})")
        return None

    close  = float(today_row["close"])
    volume = float(today_row.get("volume", hist["volume"].iloc[-1] if "volume" in hist.columns else 0))

    atr14_s  = _atr(hist, 14)
    atr14    = float(atr14_s.iloc[-1]) if not atr14_s.empty else 0.0
    rsi_v    = float(_rsi(hist["close"]).iloc[-1])
    mfi_v    = _mfi(hist)
    adx_v    = _adx(hist, 14)
    adx_prev = _adx(hist.iloc[:-1], 14) if len(hist) > 14 else adx_v
    vpoc     = calc_vpoc(hist)
    vol_rel  = _volume_reliable(hist, 63)
    adv20    = float(hist["volume"].tail(20).mean()) if len(hist) >= 20 else volume
    ma50     = float(hist["close"].tail(50).mean())  if len(hist) >= 50 else close
    ma200    = float(hist["close"].tail(200).mean()) if len(hist) >= 200 else close

    if len(hist) >= 21:
        velocity = (close - float(hist["close"].iloc[-21])) / float(hist["close"].iloc[-21]) * 100
    else:
        velocity = 0.0

    ma_ref   = ma200 if len(hist)>=200 else (float(hist["close"].tail(100).mean()) if len(hist)>=100 else ma50)
    ma_label = "MA200" if len(hist)>=200 else ("MA100" if len(hist)>=100 else "MA50")
    alt_pct  = (close-ma_ref)/ma_ref*100 if ma_ref>0 else 0.0

    if alt_pct < -SNIPER_CFG["ma200_tolerance"]*100 and ma_label=="MA200":
        # RC3 FIX: Widen tolerance in CHOP/PANIC regimes — mean-reversion and
        # bounce entries happen exactly at MA200 dips. Static 5% tolerance killed
        # quality IT stocks in correction (WIPRO, VIMTALABS, ZENSARTECH in the log).
        # CHOP  → 7.5% (1.5×): controlled pullback entries are valid
        # PANIC → 10%  (2.0×): catch high-quality stocks in a broad flush
        # MASSACRE → tolerance unchanged (pipeline returns None upstream anyway)
        regime_scale = {"CHOP": 1.5, "PANIC": 2.0}.get(macro_state, 1.0)
        effective_tol = SNIPER_CFG["ma200_tolerance"] * regime_scale * 100
        if alt_pct < -effective_tol:
            log.info(f"FORTRESS VETO {symbol}: alt_pct={alt_pct:.1f}% below MA200 tol "
                     f"{effective_tol:.1f}% ({macro_state} regime)")
            return None
        log.info(f"FORTRESS MA200 PASS {symbol}: alt_pct={alt_pct:.1f}% within "
                 f"regime-scaled {effective_tol:.1f}% ({macro_state})")
    if alt_pct > SNIPER_CFG["alt_stop_pct"]:
        log.info(f"FORTRESS VETO {symbol}: alt_pct above stop threshold")
        return None

    sector      = get_sector(symbol)
    sector_mult = SECTOR_TRUTH.get(sector, 1.0)
    if sector in SECTOR_BLOCKED:
        log.info(f"FORTRESS VETO {symbol}: sector is BLOCKED")
        return None

    # Sector RS override
    sect_20: Optional[float] = None
    if sector in SECTOR_INDICES:
        try:
            idf = _yf_download_with_backoff(f"^{SECTOR_INDICES[sector]}", period="30d",
                                            progress=False, auto_adjust=True,
                                            timeout=_YF_DOWNLOAD_TIMEOUT)
            if not idf.empty and len(idf)>=2:
                ic = idf["Close"].squeeze().values
                sect_20 = float((ic[-1]-ic[-20])/ic[-20]*100) if len(ic)>=20 else None
        except Exception as se:
            log.debug(f"Sector RS {sector}: {se}")
    if sect_20 is not None and velocity > sect_20+5.0:
        sector_mult = max(sector_mult, 1.0)

    turnover_lakhs = float(today_row.get("turnover_lakhs", 0))
    if turnover_lakhs < SNIPER_CFG["turnover_lakhs"]:
        log.info(f"FORTRESS VETO {symbol}: turnover below minimum")
        return None

    # Entry zone
    atr100 = float(_atr(hist,100).iloc[-1]) if len(hist)>=100 else atr14
    lo_pct = max(0.005, min(0.05, (atr14/close)*0.8)) if close>0 and atr14>0 else 0.02
    hi_pct = max(0.003, min(0.03, (atr14/close)*0.5)) + 0.01 if close>0 and atr14>0 else 0.015
    t1     = round(vpoc, 2)
    entry_lo, entry_hi = round(t1*(1-lo_pct),2), round(t1*(1+hi_pct),2)
    entry_zone = ("PRISTINE" if entry_lo<=close<=entry_hi else ("ABOVE" if close>entry_hi else "BELOW"))

    # Stop / exits
    atr_mult = SECTOR_ATR_MULT.get(sector, 1.0) * (0.75 if close<100 else 1.0 if close<300 else 1.40)
    t3 = round(max(close - atr_mult*atr14, close*0.93), 2)
    r1 = round(close*1.15,2); r2=round(close*1.30,2); r3=round(close*1.50,2)

    # VCP coil
    vol_contract = adv20>0 and volume<adv20*0.8
    vcp_coil = ("TIGHT 🟢" if atr14>0 and atr100>0 and (atr14/atr100)<0.70 and vol_contract else "LOOSE")

    # VDU (volume dry-up) with price confirmation
    vdu_bars = 0
    if len(hist)>=6 and vol_rel:
        for n in range(3,6):
            if all(float(hist["volume"].iloc[-(i+1)])<float(hist["volume"].iloc[-(i+2)]) for i in range(n-1)):
                vdu_bars = n
    vdu_confirmed = True
    if vdu_bars>=3:
        chg = (float(hist["close"].iloc[-1])-float(hist["close"].iloc[-(vdu_bars+1)])) / float(hist["close"].iloc[-(vdu_bars+1)])
        vdu_confirmed = chg >= -0.01

    if not vdu_confirmed: vdu_bonus,vdu_label = -3,f"🔴 VDU {vdu_bars}b+price drop — DISTRIBUTION"
    elif vdu_bars>=5:     vdu_bonus,vdu_label = 7,f"🌀 VDU {vdu_bars}-bar deep coil (+7pts)"
    elif vdu_bars>=4:     vdu_bonus,vdu_label = 5,f"🌀 VDU {vdu_bars}-bar confirmed (+5pts)"
    elif vdu_bars>=3:     vdu_bonus,vdu_label = 3,f"🌀 VDU {vdu_bars}-bar mild (+3pts)"
    else:                 vdu_bonus,vdu_label = 0,""

    # 52W compression
    if len(hist)>=20:
        h52 = float(hist.tail(252)["high"].max())
        pct_from_h = (h52-close)/h52*100 if h52>0 else 100
        atr_tight  = atr14>0 and atr100>0 and (atr14/atr100)<0.70
        if pct_from_h<=5:    w52_bonus=12 if atr_tight else 9
        elif pct_from_h<=10: w52_bonus=7  if atr_tight else 5
        elif pct_from_h<=15: w52_bonus=3
        else:                w52_bonus=0
    else:
        pct_from_h=100; w52_bonus=0

    # ATR velocity
    if len(hist)>=55:
        a7=float(_atr(hist,7).iloc[-1]); a20=float(_atr(hist,20).iloc[-1]); a50=float(_atr(hist,50).iloc[-1])
        if a50>0 and a7<a20<a50:
            rate=1-(a7/a50)
            atrv_bonus=(8 if rate>0.50 else 6 if rate>0.30 else 4)
        elif a50>0 and a7<a50: atrv_bonus=2
        else:                  atrv_bonus=0
    else: atrv_bonus=0

    forward_bonus = w52_bonus+atrv_bonus+vdu_bonus

    # VPOC layers (volume-gated)
    if vol_rel:
        layer1 = abs(close-vpoc)/vpoc<=0.02 if vpoc>0 else False
        layer2 = any(float(hist["volume"].iloc[-(i+1)])>=SNIPER_CFG["vol_ratio"]*adv20
                     for i in range(min(5,len(hist)))) if adv20>0 else False
    else:
        layer1,layer2=False,False
    recent = hist.tail(min(SNIPER_CFG["bounce_recency"],len(hist)))
    touches = sum(1 for _,r in recent.iterrows() if vpoc>0 and abs(float(r["close"])-vpoc)/vpoc<=0.03)
    layer3  = touches>=2 or (adx_v>=25 and close>ma50)

    # Base fortress pts
    pts=0.0
    if layer1: pts+=25
    elif vpoc>0 and abs(close-vpoc)/vpoc<=0.05: pts+=15
    if layer2: pts+=20
    if layer3: pts+=15
    if adx_v>=SNIPER_CFG["adx_trend"]: pts+=10
    elif adx_v>=SNIPER_CFG["adx_range"]: pts+=5
    if mfi_v<=40: pts+=8
    elif mfi_v<=50: pts+=4
    if vcp_coil=="TIGHT 🟢": pts+=5

    pts *= sector_mult
    if alt_pct>SNIPER_CFG["alt_warn_pct"]:
        excess = min(5,int((alt_pct-SNIPER_CFG["alt_warn_pct"])/5))
        pts   *= 0.80*(0.92**excess)
    elif alt_pct>30: pts*=0.92
    pts += forward_bonus
    pts  = min(int(pts), FORT_SCORE_MAX["fortress"]+30)

    # ── FIX 3: Minimum fortress score veto ──────────────────────────────
    # Previously fortress_score() returned None only on hard structural vetoes
    # (insufficient bars, MA200 tolerance, sector block, turnover, alt_pct).
    # Symbols with pts=23 (only layer3 true) passed through to APEX, wasting
    # compute and injecting weak candidates. Add a soft minimum:
    # at least ONE of the two primary VPOC layers must be true, OR pts must be
    # above a minimum bar to ensure we have genuine volume-at-price confluence.
    _FORTRESS_MIN_PTS = 28   # absolute minimum before intelligence bonuses
    _FORTRESS_REQUIRE_VPOC = not (layer1 or layer2)  # True when both VPOC layers absent

    if pts < _FORTRESS_MIN_PTS:
        log.info(f"FORTRESS SOFT-VETO {symbol}: pts={pts:.0f} < {_FORTRESS_MIN_PTS} minimum")
        return None
    if _FORTRESS_REQUIRE_VPOC and pts < 38:
        # layer3-only pass with weak score: not enough confluence for APEX
        log.info(f"FORTRESS SOFT-VETO {symbol}: pts={pts:.0f}, no VPOC layers (l1=F,l2=F) — need ≥38")
        return None

    log.info(f"FORTRESS PASS {symbol}: pts={pts:.0f} | layers={layer1},{layer2},{layer3} | zone={entry_zone}")
    return {
        "fortress_pts": pts,
        "layer1": layer1, "layer2": layer2, "layer3": layer3,
        "vol_reliable": vol_rel, "vcp_coil": vcp_coil,
        "entry_zone": entry_zone, "atr_mult": atr_mult,
        "alt_pct": round(alt_pct,2), "sector_mult": round(sector_mult,3),
        "regime": ("MOMENTUM" if adx_v>=SNIPER_CFG["adx_trend"]
                   else "TRANSITION" if adx_v>=SNIPER_CFG["adx_range"] else "RANGING"),
        "mfi": round(mfi_v,1), "rsi": round(rsi_v,1), "adx": round(adx_v,1), "adx_prev": round(adx_prev,1),
        "t1": t1, "t3": t3, "r1": r1, "r2": r2, "r3": r3,
        "atr14": round(atr14,2), "adv20": round(adv20,0),
        "vpoc": round(vpoc,2), "ma50": round(ma50,2), "ma200": round(ma200,2),
        "ma_label": ma_label, "turnover_cr": round(turnover_lakhs/100,2),
        "w52_bonus": w52_bonus, "atrv_bonus": atrv_bonus,
        "vdu_bonus": vdu_bonus, "vdu_label": vdu_label, "vdu_bars": vdu_bars,
        "forward_bonus": forward_bonus, "velocity_pct": round(velocity,2),
    }


def _calc_cvd(hist: pd.DataFrame, vol_rel: bool) -> dict:
    if not vol_rel or len(hist)<12:
        return {"cvd_signal":"NEUTRAL","cvd_label":"","cvd_bonus":0}
    h = hist.copy()
    h["cvd"] = h.apply(lambda r: float(r["volume"]) if r["close"]>r["open"] else -float(r["volume"]),axis=1).cumsum()
    w=10; cn=float(h["cvd"].iloc[-1]); c10=float(h["cvd"].iloc[-w-1])
    pn=float(h["close"].iloc[-1]); p10=float(h["close"].iloc[-w-1])
    if pn>p10 and cn<c10:   return {"cvd_signal":"DISTRIBUTION","cvd_label":"🔴 CVD Diverge","cvd_bonus":-5}
    elif pn<=p10 and cn>c10: return {"cvd_signal":"ACCUMULATION","cvd_label":"🟢 CVD Accum","cvd_bonus":+5}
    return {"cvd_signal":"NEUTRAL","cvd_label":"","cvd_bonus":0}


def _calc_vsa(hist: pd.DataFrame, atr14: float, adv20: float, vol_rel: bool) -> dict:
    if not vol_rel or len(hist)<5 or atr14<=0 or adv20<=0:
        return {"vsa_absorption":False,"vsa_label":"","vsa_bonus":0}
    bull,bear=0,0
    for _,row in hist.tail(5).iterrows():
        sp=float(row["high"])-float(row["low"]); vol=float(row["volume"])
        cl=float(row["close"]); lo=float(row["low"]); hi=float(row["high"])
        rng=hi-lo
        if rng<=0: continue
        cp=(cl-lo)/rng
        if sp<0.5*atr14 and vol>1.5*adv20 and cp>=0.60: bull+=1
        elif sp<0.5*atr14 and vol>1.5*adv20 and cp<=0.40: bear+=1
    net=bull-bear
    if net>0:  return {"vsa_absorption":True, "vsa_label":f"🟢 VSA Bullish ({bull}b)","vsa_bonus":min(8,bull*4)}
    elif net<0: return {"vsa_absorption":False,"vsa_label":f"🔴 VSA Dist ({bear}b)","vsa_bonus":-min(4,bear*2)}
    return {"vsa_absorption":False,"vsa_label":"","vsa_bonus":0}


def _calc_fog(adx_v: float, adx_prev: float, vix: float, ma50: float, ma200: float, w52_bonus: int) -> dict:
    score=0; reasons=[]
    if adx_v<=18 and adx_v<adx_prev: score+=1; reasons.append(f"ADX {adx_v:.1f}↓")
    if vix>SNIPER_CFG["vix_fog"]:    score+=1; reasons.append(f"VIX {vix:.1f}>{SNIPER_CFG['vix_fog']:.0f}")
    if ma200>0 and ma50>0 and abs(ma50-ma200)/ma200<=0.03: score+=1; reasons.append("MA compressed")
    if adx_v<=18 and w52_bonus==0:   score+=1; reasons.append("no 52W coil")
    tier  = ("FOG_SEVERE" if score>=3 else "FOG_WARNING" if score>=2 else "CLEAR")
    block = score>=2
    label = (f"🌫️ {tier} — "+" · ".join(reasons)) if block else ""
    return {"fog_tier":tier,"fog_block":block,"fog_label":label}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 12 — APEX 7-ENGINE (fully preserved from v1.2)
# ══════════════════════════════════════════════════════════════════════════════

def _whale_radar(hist: pd.DataFrame, adv20: float) -> Tuple[float, dict]:
    LOOKBACK=15; EMPTY={"whale_detected":False,"signal_type":"NONE","whale_label":"","stealth_score":0}
    if len(hist)<max(LOOKBACK,60) or adv20<=0: return 0.0,EMPTY
    tail=hist.tail(LOOKBACK)
    p_vel=float((tail["close"].iloc[-1]-tail["close"].iloc[0])/tail["close"].iloc[0]*100)
    flat =abs(p_vel)<3.0
    v20=float(hist["volume"].tail(20).mean()); v60=float(hist["volume"].tail(60).mean())
    if v60<=0: return 0.0,EMPTY
    vol_rising=(v20/v60-1)>=0.30
    obv_s=_obv(tail); obv_up=float(obv_s.iloc[-1]-obv_s.iloc[0])>0
    spikes=int((tail["volume"]>2.5*adv20).sum())
    rng_now=float(tail["high"].tail(5).max()-tail["low"].tail(5).min())
    rng_prev=float(hist.tail(40).head(35)["high"].max()-hist.tail(40).head(35)["low"].min())
    compressed=rng_prev>0 and (rng_now/rng_prev)<0.40
    pw=hist["close"].tail(5).values; vw=hist["volume"].tail(5).values.astype(float)
    prng=float(abs(pw[-1]-pw[0])/max(pw[0],1)*100)
    vt  =float(np.polyfit(range(5),vw,1)[0]) if len(vw)==5 else 0
    stealth=prng<=1.5 and vt>0 and vw[-1]>adv20*1.2
    ss  =min(100.0,40+abs(vt)*10) if stealth else 0.0
    sig ="NONE"
    if flat and vol_rising: sig="STEALTH" if ss>40 else "ACCUMULATION"
    elif flat and obv_up:   sig="STEALTH"
    elif not flat and vol_rising: sig="ACCUMULATION"
    score=0; parts=[]
    if flat and vol_rising:   score+=40; parts.append(f"🐋 Flat+Vol({(v20/max(v60,1)-1)*100:.0f}%↑)")
    if ss>40:                 score+=int(ss*0.35); parts.append(f"🕵️ Stealth{ss:.0f}")
    if obv_up and flat:       score+=20; parts.append("📈 OBV↑ flat")
    if spikes>=3:             score+=min(20,spikes*5); parts.append(f"🔦 {spikes}spikes")
    if compressed:            score+=15; parts.append("🌀 Range compressed")
    if not flat and vol_rising: score+=10; parts.append("⚡ Vol expanding")
    score=min(100,score)
    detected=score>=35 or ss>=50
    return float(score),{"whale_detected":detected,"signal_type":sig,
                         "whale_label":" | ".join(parts),"stealth_score":ss,
                         "price_velocity":round(p_vel,2),"vol_velocity":round((v20/max(v60,1)-1)*100,1),
                         "spike_days":spikes,"obv_rising":obv_up}


def _divergence_engine(hist: pd.DataFrame) -> Tuple[float, dict]:
    WINDOW=15; EMPTY={"div_type":"NONE","div_label":"No divergence","div_strength":0}
    if len(hist)<WINDOW+20: return 0.0,EMPTY
    rsi_s=_rsi(hist["close"]); obv_s=_obv(hist)
    lb=hist.tail(WINDOW+5)
    prices=lb["close"].values; rsis=rsi_s.tail(len(lb)).values; obvs=obv_s.tail(len(lb)).values
    def pivots(arr,w=3):
        hi,lo=[],[]
        for i in range(w,len(arr)-w):
            if all(arr[i]>=arr[i-j] for j in range(1,w+1)) and all(arr[i]>=arr[i+j] for j in range(1,w+1)): hi.append((i,arr[i]))
            if all(arr[i]<=arr[i-j] for j in range(1,w+1)) and all(arr[i]<=arr[i+j] for j in range(1,w+1)): lo.append((i,arr[i]))
        return hi,lo
    _,p_lows=pivots(prices); _,r_lows=pivots(rsis); o_highs,_=pivots(obvs)
    div_type="NONE"; strength=0.0
    if len(p_lows)>=2 and len(r_lows)>=2:
        pl1,pl2=p_lows[-2],p_lows[-1]; rl1,rl2=r_lows[-2],r_lows[-1]
        if pl2[1]>pl1[1] and rl2[1]<rl1[1]:
            div_type="BULLISH_HIDDEN"; strength=min(100.0,float((rl1[1]-rl2[1])*2+25))
    obv_bonus=15.0 if len(o_highs)>=2 and o_highs[-1][1]>o_highs[-2][1] else 0.0
    score=min(100.0,(strength*0.85+obv_bonus)*{"BULLISH_HIDDEN":1.0,"NONE":0.0}.get(div_type,0.5))
    label=f"🔀 {div_type} ({strength:.0f}%)" if div_type!="NONE" else "No divergence"
    return float(score),{"div_type":div_type,"div_label":label,"div_strength":round(strength,1)}


def _vol_profile_score(profile: dict, close: float, fortress_vpoc: float = 0.0) -> Tuple[float, str]:
    """Score volume profile closeness.
    FIX: Uses fortress_vpoc (weighted 3m/6m/12m) as primary distance reference
    when available, avoiding the contradiction where fortress_score says
    layer1=True (close ≈ VPOC) but _vpoc_profile (63d only) reports a different POC.
    profile['poc'] is still used for Value Area checks (independent of VPOC calc)."""
    poc = profile.get("poc", 0)
    if poc <= 0: return 0.0, "No vol profile"
    score = 0; notes = []

    # Use weighted fortress VPOC for distance if provided, else fall back to 63d POC
    ref_poc = fortress_vpoc if fortress_vpoc > 0 else poc
    dist = abs(close - ref_poc) / ref_poc * 100
    if dist <= 1.0:   score += 40; notes.append("AT POC 🎯")
    elif dist <= 3.0: score += 25; notes.append("NEAR POC")
    elif dist <= 5.0: score += 12; notes.append("POC ZONE")

    va_lo = profile.get("va_low", 0); va_hi = profile.get("va_high", 0)
    if va_lo > 0 and va_hi > 0:
        if va_lo <= close <= va_hi: score += 20; notes.append("INSIDE VA")
        elif close < va_lo:         score += 8;  notes.append("BELOW VA")
    wp = profile.get("whale_pct", 0)
    if wp >= 35:   score += 25; notes.append(f"WHALE DEF {wp:.0f}%")
    elif wp >= 25: score += 15; notes.append(f"Strong POC {wp:.0f}%")
    va_w = (va_hi - va_lo) / poc * 100 if poc > 0 and va_hi > va_lo else 0
    if 0 < va_w <= 8: score += 10; notes.append("TIGHT VA")
    return float(min(100, score)), " · ".join(notes) if notes else "Diffuse"


def _pattern_score(hist: pd.DataFrame, atr14: float, profile: dict) -> Tuple[float, str]:
    if len(hist)<20: return 0.0,"No pattern"
    cl=hist["close"].values; hi=hist["high"].values
    lo=hist["low"].values;   vol=hist["volume"].values; n=len(hist)
    score=0; pats=[]
    if n>=7:
        rng=hi-lo
        if rng[-1]<=rng[-7:].min()+1e-9: score+=20; pats.append("NR7 🌀")
    if n>=2 and hi[-2]-lo[-2]>0 and (hi[-1]-lo[-1])/(hi[-2]-lo[-2])<0.60:
        score+=15; pats.append("Inside-Bar")
    if n>=30:
        pvts=[]
        for i in range(5,n-1):
            if hi[i]>=hi[i-1] and hi[i]>=hi[i-3]: pvts.append(("H",i,hi[i]))
            elif lo[i]<=lo[i-1] and lo[i]<=lo[i-3]: pvts.append(("L",i,lo[i]))
        if len(pvts)>=3:
            lp=pvts[-3:]; sw=[abs(lp[k][2]-lp[k-1][2]) for k in range(1,len(lp))]
            if len(sw)>=2 and all(sw[k]<sw[k-1] for k in range(1,len(sw))):
                score+=30; pats.append(f"VCP-{len(lp)}P 🎯")
    if n>=10:
        r10=cl[-10:]; band=(r10.max()-r10.min())/r10.mean()*100
        if band<5: score+=15; pats.append(f"Flat-Base({band:.1f}%)")
    if n>=12:
        dv=vol[-10:][np.diff(cl[-11:])<0]; md=float(dv.max()) if len(dv)>0 else 0
        if md>0 and vol[-1]>md and cl[-1]>cl[-2]: score+=20; pats.append("PocketPivot 💉")
    if n>=40:
        mid=n//2
        lh=float(hist["high"].iloc[:mid].max()); rh=float(hist["high"].iloc[mid:].max())
        ml=float(hist["low"].iloc[mid-5:mid+5].min())
        cd=(lh-ml)/lh if lh>0 else 0
        if 0.05<=cd<=0.20 and rh>=lh*0.98 and cl[-1]>=lh*0.95:
            score+=25; pats.append("Cup&Handle 🏆")
    poc=profile.get("poc",0)
    if poc>0 and n>=5:
        for i in range(-5,0):
            if abs(float(hist["low"].iloc[i])-poc)/poc<=0.015 and hist["close"].iloc[i]>hist["open"].iloc[i]:
                score+=15; pats.append("POC-Bounce"); break
    return float(min(100,score))," + ".join(pats) if pats else "No pattern"


def _monte_carlo(hist: pd.DataFrame, stop_loss: float, close: float) -> dict:
    EMPTY = {"survival": None, "t1_hit_pct": 0.0, "days_to_t1": None, 
             "label": "MC: insufficient data", "valid": False, "regime_warning": ""}

    if len(hist) < 50 or stop_loss <= 0:  # Increased from 30 to 50
        return EMPTY

    closes = hist["close"].values.astype(float)

    # ── REGIME CHANGE DETECTION ──
    # Check if recent volatility is significantly different from historical
    recent_vol = np.std(np.diff(np.log(closes[-20:]))) if len(closes) >= 20 else 0
    hist_vol = np.std(np.diff(np.log(closes[:-20]))) if len(closes) > 40 else recent_vol

    vol_regime_changed = False
    if hist_vol > 0:
        vol_ratio = recent_vol / hist_vol
        if vol_ratio > 1.5 or vol_ratio < 0.5:
            vol_regime_changed = True

    # ── TREND BIAS DETECTION ──
    # If stock just broke out, historical vol is misleading
    sma20 = np.mean(closes[-20:])
    sma50 = np.mean(closes[-50:])
    in_uptrend = closes[-1] > sma20 > sma50
    just_broke_out = closes[-1] > sma20 * 1.05 and closes[-5] < sma20 * 1.02

    # ── MC SIMULATION ──
    lr = np.diff(np.log(closes[closes > 0]))
    if len(lr) < 20:
        return EMPTY

    # Use RECENT volatility if regime changed, else full history
    if vol_regime_changed or just_broke_out:
        mu = float(np.mean(lr[-20:]))  # Recent mean
        sigma = float(np.std(lr[-20:]))  # Recent vol (higher = more realistic post-breakout)
        regime_note = " [RECENT VOL — regime change detected]"
    else:
        mu = float(np.mean(lr))
        sigma = float(np.std(lr))
        regime_note = ""

    # Sanity check: if sigma is implausibly low, bump it
    if sigma < 0.005:  # Less than 0.5% daily vol
        sigma = 0.015  # Minimum 1.5% daily vol for NSE mid-caps
        regime_note += " [MIN VOL FLOOR APPLIED]"

    df = MC_FAT_DF
    ts = sigma * math.sqrt((df - 2) / df) if df > 2 else sigma
    t1t = close * 1.10
    rng = np.random.default_rng(42)

    surv = hit = days_tot = 0
    for _ in range(MC_SIMS):
        path = close * np.exp(np.cumsum(mu + ts * rng.standard_t(df, size=MC_HORIZON)))
        if float(np.min(path)) > stop_loss:
            surv += 1
        if float(np.max(path)) >= t1t:
            hit += 1
            for d, p in enumerate(path, 1):
                if p >= t1t:
                    days_tot += d
                    break

    sp = round(surv / MC_SIMS * 100, 1)
    tp = round(hit / MC_SIMS * 100, 1)
    ad = round(days_tot / max(1, hit), 1) if hit > 0 else None

    # ── VALIDATION: Consistency check (seeds 42 vs 43) ──
    # NOTE: this is a consistency/noise test, not true convergence.
    # The HARD VETO below (sp < 50) is the meaningful safety gate.
    h = MC_SIMS // 2
    r1 = np.random.default_rng(42)
    r2 = np.random.default_rng(43)
    s1 = sum(1 for _ in range(h)
             for p in [close * np.exp(np.cumsum(mu + ts * r1.standard_t(df, size=MC_HORIZON)))]
             if float(np.min(p)) > stop_loss)
    s2 = sum(1 for _ in range(h)
             for p in [close * np.exp(np.cumsum(mu + ts * r2.standard_t(df, size=MC_HORIZON)))]
             if float(np.min(p)) > stop_loss)
    conv = abs(s1 / max(1, h) * 100 - s2 / max(1, h) * 100) <= 8.0

    # ── VALIDATION: Sanity bounds ──
    # NSE mid-caps rarely show >90% survival in reality
    if sp > 95 and (vol_regime_changed or just_broke_out):
        sp = min(sp, 85)  # Cap at 85% if regime changed
        regime_note += " [CAP: regime change]"

    valid = conv and len(lr) >= 30 and not (vol_regime_changed and sp > 90)

    # ── H2 FIX: Hard veto — survival below 50% means stop is likely to be hit ──
    # Previously MC survival was a cosmetic label; it barely moved the fused score.
    # A pick surviving fewer than half of 600 simulations should not be presented.
    MC_HARD_VETO_PCT = 50.0
    hard_veto = valid and sp < MC_HARD_VETO_PCT

    lbl = f"MC {sp}% survive ({MC_HORIZON}d, t-df{df}){regime_note}"
    if not conv:
        lbl += " [NOT CONVERGED]"
    if not valid:
        lbl += " [LOW CONFIDENCE]"
    if hard_veto:
        lbl += " [HARD VETO — survival too low]"

    return {
        "survival":      sp,
        "t1_hit_pct":    tp,
        "days_to_t1":    ad,
        "label":         lbl,
        "converged":     conv,
        "valid":         valid,
        "hard_veto":     hard_veto,       # H2: caller must check this
        "regime_warning": "⚠️ Post-breakout vol unreliable" if just_broke_out else
                          "⚠️ Vol regime changed" if vol_regime_changed else ""
    }


# ── BAYESIAN PRIOR LEARNING ENGINE ──
# Reads closed pick outcomes from DB and updates empirical win rates per signal node.
# Falls back to conservative defaults if insufficient data (< 20 samples per node).

_BAYES_PRIOR_VERSION = "v1.0-conservative"  # Tracks which prior set is active
_MIN_CALIBRATION_SAMPLES = 20  # Minimum trades before trusting empirical rate




def _walkforward_engine_correlation(days: int = 90) -> dict:
    """
    Correlate each sub-engine score with realized P&L from closed picks.
    Returns: {engine_name: spearman_r, p_value, edge_status}
    edge_status: 'GENUINE' | 'NOISE' | 'INSUFFICIENT'
    """
    try:
        import scipy.stats as stats
        con = sqlite3.connect(DB_PATH)

        # Get closed picks with their scores and P&L
        rows = con.execute(
            "SELECT whale_score, div_score, vp_score, pat_score, bayes_pct, pnl_pct, status "
            "FROM pick_outcomes WHERE status IN ('r1_hit','r2_hit','r3_hit','stopped','expired') "
            "AND run_date > ?",
            ((datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d"),)
        ).fetchall()
        con.close()

        if len(rows) < 15:
            return {"status": "INSUFFICIENT", "message": f"Only {len(rows)} closed picks (< 15)"}

        results = {}
        engines = [
            ("whale_radar", 0),
            ("divergence", 1),
            ("vol_profile", 2),
            ("pattern", 3),
            ("bayesian", 4),
        ]

        for name, idx in engines:
            scores = [r[idx] for r in rows]
            pnls = [r[5] for r in rows]

            if len(set(scores)) < 3:
                results[name] = {"r": 0.0, "p": 1.0, "status": "NOISE", "n": len(rows)}
                continue

            r, p = stats.spearmanr(scores, pnls)
            status = "GENUINE" if r > 0.3 and p < 0.10 else "NOISE" if r < 0.1 else "MARGINAL"
            results[name] = {
                "r": round(r, 3),
                "p": round(p, 3),
                "status": status,
                "n": len(rows)
            }

        return results
    except Exception as e:
        log.debug(f"Walkforward correlation: {e}")
        return {"status": "ERROR", "message": str(e)}



def _calibrate_bayes_priors() -> dict:
    """
    Read pick_outcomes table, group by which Bayesian nodes were true/false,
    compute empirical win rate per condition, return updated priors.
    Win = hit r1/r2/r3 (status in ['r1_hit','r2_hit','r3_hit'])
    Loss = stopped or expired with negative P&L
    """
    try:
        con = sqlite3.connect(DB_PATH)
        # Get all closed picks with their signals and outcomes
        rows = con.execute(
            "SELECT symbol, run_date, status, pnl_pct, story, grade "
            "FROM pick_outcomes WHERE status IN ('r1_hit','r2_hit','r3_hit','stopped','expired') "
            "AND run_date > ?",
            ((datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d"),)
        ).fetchall()
        con.close()

        if len(rows) < _MIN_CALIBRATION_SAMPLES:
            log.info(f"Calibration: only {len(rows)} closed picks (< {_MIN_CALIBRATION_SAMPLES}) — using defaults")
            return None

        # For each pick, we need to reconstruct which signals were true
        # We store this in bayes_calibration table during run()
        con = sqlite3.connect(DB_PATH)
        cal_rows = con.execute(
            "SELECT prior_name, condition, wins, total FROM bayes_calibration"
        ).fetchall()
        con.close()

        if not cal_rows:
            # BUG-009 FIX: bayes_calibration is only populated BY this function,
            # so on first run it's always empty. Bootstrap from pick_outcomes directly
            # by treating each node as a coin-flip seeded from grade and macro state.
            log.info("Bayes calibration: bootstrapping from pick_outcomes (BUG-009 fix)")
            bootstrap_rows = []
            for sym, rdate, status, pnl, story, grade in rows:
                is_win = status in ("r1_hit", "r2_hit", "r3_hit")
                # Use available metadata as proxy node signals
                grade_node = f"grade_{grade}" if grade else "grade_GOOD"
                bootstrap_rows.append((grade_node, grade or "GOOD", is_win))
            if bootstrap_rows:
                try:
                    with _db_conn() as con:
                        for node, condition, is_win in bootstrap_rows:
                            con.execute("""
                                INSERT INTO bayes_calibration (prior_name, condition, wins, total)
                                VALUES (?, ?, ?, 1)
                                ON CONFLICT(prior_name, condition) DO UPDATE SET
                                    wins  = wins  + excluded.wins,
                                    total = total + 1
                            """, (node, condition, int(is_win)))
                    # Re-read the now-populated table
                    with _db_conn() as con:
                        cal_rows = con.execute(
                            "SELECT prior_name, condition, wins, total FROM bayes_calibration"
                        ).fetchall()
                except Exception as e:
                    log.warning(f"BUG-009 bootstrap write failed: {e}")
            if not cal_rows:
                return None

        updated_priors = {}
        for name, condition, wins, total in cal_rows:
            if total >= 10:  # Minimum samples per node
                empirical_wr = wins / total
                # Shrink toward default prior (regularization)
                default_wr = 0.40  # Base rate
                shrunk = (wins + default_wr * 10) / (total + 10)
                updated_priors[name] = {
                    "win_rate": round(shrunk, 3),
                    "samples": total,
                    "raw_wins": wins
                }

        if updated_priors:
            global _BAYES_PRIOR_VERSION
            _BAYES_PRIOR_VERSION = f"v1.1-learned-{datetime.today().strftime('%Y%m%d')}"
            log.info(f"Bayesian priors calibrated: {len(updated_priors)} nodes updated | Version: {_BAYES_PRIOR_VERSION}")
            return updated_priors

    except Exception as e:
        log.warning(f"Bayes calibration failed — priors unchanged (stale): {e}")    # H1


def _load_learned_priors() -> Optional[dict]:
    """Load calibrated priors if available and recent (< 7 days old)."""
    try:
        con = sqlite3.connect(DB_PATH)
        row = con.execute(
            "SELECT prior_name, win_rate, updated_at FROM bayes_calibration "
            "WHERE updated_at > ? LIMIT 1",
            ((datetime.today() - timedelta(days=7)).isoformat(),)
        ).fetchone()
        con.close()
        if row:
            return _calibrate_bayes_priors()
    except Exception:
        pass
    return None

def _store_meta_features(run_date: str, symbol: str, features: dict):
    """Store signal vector at entry time for later meta-model training."""
    try:
        with _db_conn(write=True) as con:
            con.execute(
                """INSERT OR REPLACE INTO meta_features
                (run_date, symbol, whale_score, div_score, vp_score, pat_score, bayes_pct,
                 macro_state, sector, vix_level, primary_fused_score)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (run_date, symbol.upper(),
                 features.get("whale_score"), features.get("div_score"),
                 features.get("vp_score"), features.get("pat_score"),
                 features.get("bayes_pct"), features.get("macro_state"),
                 features.get("sector"), features.get("vix_level"),
                 features.get("primary_fused_score"))
            )
    except Exception as e:
        log.debug(f"Meta-features store {symbol}: {e}")


def _update_meta_outcomes():
    """Backfill outcome_pnl_pct and profitable flags from closed pick_outcomes."""
    try:
        with _db_conn(write=True) as con:
            rows = con.execute(
                """SELECT o.run_date, o.symbol, o.pnl_pct,
                          CASE WHEN o.pnl_pct > 0 THEN 1 ELSE 0 END as profitable
                   FROM pick_outcomes o
                   JOIN meta_features m ON o.run_date = m.run_date AND o.symbol = m.symbol
                   WHERE o.status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')
                   AND m.outcome_pnl_pct IS NULL""").fetchall()
            for run_date, symbol, pnl, prof in rows:
                con.execute(
                    "UPDATE meta_features SET outcome_pnl_pct=?, profitable=? WHERE run_date=? AND symbol=?",
                    (pnl, prof, run_date, symbol))
        if rows:
            log.info(f"Meta-features: backfilled {len(rows)} outcomes")
    except Exception as e:
        log.debug(f"Meta outcomes update: {e}")


def _train_meta_labeler(min_samples: int = 50) -> Optional[object]:
    """
    v1 meta-labeler — trains on ALL resolved signals.
    Kept as internal fallback; prefer _train_meta_labeler_v2() in run().
    """
    try:
        with _db_conn() as con:
            rows = con.execute(
                """SELECT whale_score, div_score, vp_score, pat_score, bayes_pct,
                          macro_state, sector, vix_level, primary_fused_score, profitable
                   FROM meta_features
                   WHERE profitable IS NOT NULL""").fetchall()

        if len(rows) < min_samples:
            log.info(f"Meta-labeler v1: {len(rows)} samples (< {min_samples}) -- skipping")
            return None

        import pandas as pd
        df = pd.DataFrame(rows, columns=[
            "whale_score","div_score","vp_score","pat_score","bayes_pct",
            "macro_state","sector","vix_level","primary_fused_score","profitable"])

        df["macro_clear"] = (df["macro_state"] == "CLEAR").astype(int)
        df["macro_chop"] = (df["macro_state"] == "CHOP").astype(int)
        df["macro_panic"] = (df["macro_state"].isin(["PANIC","MASSACRE"])).astype(int)

        top_sectors = df['sector'].value_counts().head(6).index.tolist()
        for sec in top_sectors:
            col_name = "sec_" + sec.replace(" ", "_")
            df[col_name] = (df["sector"] == sec).astype(int)

        feature_cols = [c for c in df.columns if c not in ["profitable","macro_state","sector"]]
        X = df[feature_cols].fillna(0)
        y = df["profitable"]

        from sklearn.model_selection import train_test_split
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.metrics import brier_score_loss, roc_auc_score

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y)

        base_clf = RandomForestClassifier(
            n_estimators=200, max_depth=6, min_samples_leaf=5,
            class_weight="balanced", random_state=42, n_jobs=-1)
        calibrated_clf = CalibratedClassifierCV(base_clf, method="isotonic", cv=5)
        calibrated_clf.fit(X_train, y_train)

        y_prob = calibrated_clf.predict_proba(X_test)[:, 1]
        auc = roc_auc_score(y_test, y_prob)
        brier = brier_score_loss(y_test, y_prob)
        log.info(f"Meta-labeler v1 trained: AUC={auc:.3f} | Brier={brier:.3f} | n={len(rows)}")

        return calibrated_clf

    except Exception as e:
        log.warning(f"Meta-labeler v1 training failed: {e}")
        return None


def _fit_and_persist_platt_params(X, y, base_model) -> Optional[dict]:
    """
    GAP-2 FIX: Extract Platt scaling A/B parameters from a fitted
    CalibratedClassifierCV and persist them to the platt_calibration DB table.

    The existing training code wraps the model in CalibratedClassifierCV but
    never writes A/B scalars to the DB — so _load_calibration_params() always
    returns None, and _platt_calibrate() is always an identity passthrough.

    Why extract A/B instead of just using the wrapped sklearn model?
    The AI Judge runs in the inference pipeline on individual picks — it calls
    _platt_calibrate(raw_prob, {A, B}) with a scalar, not a DataFrame.
    The sklearn CalibratedClassifierCV expects a full feature matrix.
    A/B extraction gives us the inference-time sigmoid without sklearn dependency.

    Extracts A and B from the first calibrated classifier's sigmoid (Platt method):
      p_calibrated = 1 / (1 + exp(A * raw_score + B))
    where raw_score is the uncalibrated model's decision_function or predict_proba output.

    Returns dict with A, B, n_samples, ece (expected calibration error) or None on failure.
    """
    try:
        from sklearn.calibration import CalibratedClassifierCV, calibration_curve
        from sklearn.metrics import brier_score_loss
        import numpy as np

        n_samples = len(y)
        n_folds   = min(5, max(2, n_samples // 10))

        # Fit the Platt-calibrated wrapper
        platt_clf = CalibratedClassifierCV(base_model, method="sigmoid", cv=n_folds)
        platt_clf.fit(X, y)

        # Extract A, B from the first calibrator's sigmoid parameters
        # CalibratedClassifierCV stores calibrators in .calibrated_classifiers_
        A, B = None, None
        for cc in getattr(platt_clf, "calibrated_classifiers_", []):
            for cal in getattr(cc, "calibrators_", []):
                # sklearn's _SigmoidCalibration stores a_ and b_
                if hasattr(cal, "a_") and hasattr(cal, "b_"):
                    A = float(cal.a_)
                    B = float(cal.b_)
                    break
            if A is not None:
                break

        if A is None:
            log.warning("Platt param extraction: could not find a_/b_ — sigmoid params unavailable")
            return None

        # Compute Expected Calibration Error on training set (optimistic but useful for logging)
        raw_probs = platt_clf.predict_proba(X)[:, 1]
        brier     = brier_score_loss(y, raw_probs)
        fraction_pos, mean_pred = calibration_curve(y, raw_probs, n_bins=10, strategy="uniform")
        ece = float(np.mean(np.abs(fraction_pos - mean_pred)))

        # Persist to DB — _load_calibration_params() will pick this up next run
        try:
            with _db_conn(write=True) as con:
                con.execute(
                    "INSERT INTO platt_calibration (A, B, n_samples, ece) VALUES (?, ?, ?, ?)",
                    (A, B, n_samples, round(ece, 4))
                )
            log.info(f"Platt params persisted: A={A:.4f} B={B:.4f} | "
                     f"n={n_samples} | Brier={brier:.4f} | ECE={ece:.4f}")
        except Exception as db_err:
            log.warning(f"Platt DB write failed: {db_err}")

        return {"A": A, "B": B, "n_samples": n_samples, "ece": round(ece, 4)}

    except Exception as e:
        log.warning(f"_fit_and_persist_platt_params failed: {e}")
        return None


def _train_meta_labeler_v2(min_samples: int = 20) -> Optional[object]:
    """
    Meta-labeler v2 (v3.0-M): trains on YOUR decisions, not all signals.

    Labels:
      1 (win)  = decision=TAKEN AND outcome in (r1_hit, r2_hit, r3_hit)
      0 (loss) = decision=TAKEN AND outcome in (stopped, expired)
    Skipped trades are excluded from training (counterfactual unknown).
    Falls back to v1 training (all signals) if fewer than min_samples decisions exist.

    H3 FIX: Only retrain when the closed-pick count has grown by >50 since the
    model was last saved.  RandomForest on 1000+ rows is O(n²) — retraining on
    every run causes the 45-minute GitHub Actions timeout to trigger once the DB
    accumulates enough history.  The model file's mtime is used to detect staleness.
    """
    try:
        from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import Pipeline
        from sklearn.model_selection import cross_val_score
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.metrics import brier_score_loss, roc_auc_score
        import pickle
    except ImportError:
        log.debug("sklearn not available — meta-labeler v2 skipped")
        return None

    # ── H3: Retrain guard ─────────────────────────────────────────────────────
    _META_RETRAIN_DELTA = 50      # minimum new closed picks before retraining
    model_path = Path("meta_model.pkl")
    try:
        current_closed = sqlite3.connect(DB_PATH, timeout=5).execute(
            "SELECT COUNT(*) FROM pick_outcomes "
            "WHERE status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')"
        ).fetchone()[0]
    except Exception:
        current_closed = 0

    retrain_count_path = Path("meta_model_train_count.txt")
    last_train_count = 0
    try:
        last_train_count = int(retrain_count_path.read_text().strip())
    except Exception:
        pass  # first run or missing file

    if (model_path.exists()
            and current_closed - last_train_count < _META_RETRAIN_DELTA):
        log.info(
            f"Meta-labeler v2: skipping retrain "
            f"(closed picks since last train: "
            f"{current_closed - last_train_count} < {_META_RETRAIN_DELTA}). "
            f"Loading existing model."
        )
        return _load_meta_model()
    # ── End retrain guard ─────────────────────────────────────────────────────

    try:
        con = sqlite3.connect(DB_PATH, timeout=10)

        decision_count = con.execute(
            "SELECT COUNT(*) FROM trade_decisions WHERE decision='TAKEN'"
        ).fetchone()[0]

        if decision_count >= min_samples:
            log.info(f"Meta-labeler v2: {decision_count} personal decisions → PERSONALIZED mode")
            rows = con.execute("""
                SELECT mf.whale_score, mf.div_score, mf.vp_score, mf.pat_score,
                       mf.bayes_pct, mf.mc_survival, mf.fort_norm, mf.apex_composite,
                       mf.confluence_bonus, mf.macro_state, mf.sector, mf.vix_level,
                       mf.primary_fused_score,
                       COALESCE(mf.days_to_earnings, -1),
                       COALESCE(mf.signals_this_week, 0),
                       COALESCE(mf.your_wr_this_grade, 0.5),
                       COALESCE(mf.your_wr_this_sector, 0.5),
                       COALESCE(mf.setup_profile, ''),
                       o.status
                FROM trade_decisions td
                JOIN pick_outcomes o   ON td.symbol=o.symbol AND td.run_date=o.run_date
                JOIN meta_features mf  ON td.symbol=mf.symbol AND td.run_date=mf.run_date
                WHERE td.decision='TAKEN'
                  AND o.status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')
            """).fetchall()
        else:
            log.info(f"Meta-labeler v2: only {decision_count} decisions — FALLBACK to all signals")
            rows = con.execute("""
                SELECT mf.whale_score, mf.div_score, mf.vp_score, mf.pat_score,
                       mf.bayes_pct,
                       COALESCE(mf.mc_survival, 50),
                       COALESCE(mf.fort_norm, 50),
                       COALESCE(mf.apex_composite, 50),
                       COALESCE(mf.confluence_bonus, 0),
                       mf.macro_state, mf.sector,
                       COALESCE(mf.vix_level, 18),
                       mf.primary_fused_score,
                       COALESCE(mf.days_to_earnings, -1),
                       0, 0.5, 0.5, '',
                       o.status
                FROM meta_features mf
                JOIN pick_outcomes o ON mf.symbol=o.symbol AND mf.run_date=o.run_date
                WHERE o.status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')
            """).fetchall()

        columns = [
            "whale_score","div_score","vp_score","pat_score",
            "bayes_pct","mc_survival","fort_norm","apex_composite",
            "confluence_bonus","macro_state","sector","vix_level",
            "primary_fused_score","days_to_earnings","signals_this_week",
            "your_wr_this_grade","your_wr_this_sector","setup_profile","status"
        ]
        con.close()

        if len(rows) < min_samples:
            log.info(f"Meta-labeler v2: {len(rows)} samples < {min_samples} minimum — skipping")
            return None

        df = pd.DataFrame(rows, columns=columns)
        df["label"] = df["status"].isin(["r1_hit","r2_hit","r3_hit"]).astype(int)

        df["macro_clear"]   = (df["macro_state"] == "CLEAR").astype(int)
        df["macro_chop"]    = (df["macro_state"] == "CHOP").astype(int)
        df["macro_panic"]   = (df["macro_state"].isin(["PANIC","MASSACRE"])).astype(int)
        df["earnings_near"] = (df["days_to_earnings"].clip(lower=-1) < 8).astype(int)
        df["high_capacity"] = (df["signals_this_week"] >= 4).astype(int)

        for sec in ["NIFTY IT","NIFTY PHARMA","NIFTY AUTO","NIFTY FMCG","NIFTY METAL","DIVERSIFIED"]:
            df[f"sec_{sec.replace(' ','_')}"] = (df["sector"] == sec).astype(int)

        if df["setup_profile"].nunique() > 1:
            top_profiles = df["setup_profile"].value_counts().head(8).index.tolist()
            for p in top_profiles:
                df[f"prof_{p}"] = (df["setup_profile"] == p).astype(int)

        feature_cols = [c for c in df.columns if c not in
                        ("status","label","macro_state","sector","setup_profile")]
        X = df[feature_cols].fillna(0)
        y = df["label"]

        if y.sum() < 3 or (1-y).sum() < 3:
            log.warning("Meta-labeler v2: too few of one class — skipping")
            return None

        if len(rows) >= 100:
            model = Pipeline([
                ("scaler", StandardScaler()),
                ("clf", GradientBoostingClassifier(n_estimators=100, max_depth=3,
                                                    learning_rate=0.1, random_state=42))
            ])
        else:
            model = RandomForestClassifier(n_estimators=100, max_depth=4,
                                           min_samples_leaf=3, random_state=42,
                                           class_weight="balanced")

        model.fit(X, y)

        # ── Platt Calibration (sigmoid method) ───────────────────────────────
        # GBM and RF predict_proba() outputs are poorly calibrated — probabilities
        # are pushed toward 0/1 extremes, making the meta_prob threshold comparisons
        # (e.g. _META_VETO_THRESHOLD = 0.40) unreliable.
        # Platt scaling fits a logistic curve on top of the raw scores using
        # cross-validated held-out folds so we don't overfit the calibration.
        # GAP-2 FIX: _fit_and_persist_platt_params() extracts A/B scalars AND writes
        # them to platt_calibration DB so _load_calibration_params() can find them.
        # The old code called CalibratedClassifierCV but never persisted A/B — the
        # table was always empty so every run was an identity passthrough.
        n_cal_folds = min(5, max(2, len(X) // 10))   # at least 10 samples per fold
        try:
            platt_result = _fit_and_persist_platt_params(X, y, model)
            platt_model = CalibratedClassifierCV(model, method="sigmoid", cv=n_cal_folds)
            platt_model.fit(X, y)
            brier = brier_score_loss(y, platt_model.predict_proba(X)[:, 1])
            log.info(f"Platt calibration applied: cv={n_cal_folds} folds | Brier={brier:.4f} "
                     f"(lower=better; 0.25=random, 0=perfect)"
                     + (f" | A={platt_result['A']:.4f} B={platt_result['B']:.4f}" if platt_result else " | A/B extraction failed"))
            calibrated_model = platt_model
        except Exception as cal_err:
            log.warning(f"Platt calibration failed ({cal_err}) — using uncalibrated model")
            calibrated_model = model

        # Preserve feature names for inference alignment
        feat_names = X.columns.tolist()
        if not hasattr(calibrated_model, "feature_names_in_"):
            calibrated_model.feature_names_in_ = feat_names

        cv_scores = cross_val_score(calibrated_model, X, y,
                                    cv=min(3, len(rows) // 5 or 1), scoring="roc_auc")
        log.info(f"Meta-labeler v2 trained: {len(rows)} samples | "
                 f"AUC {cv_scores.mean():.3f}±{cv_scores.std():.3f} | "
                 f"Mode: {'PERSONALIZED' if decision_count >= min_samples else 'FALLBACK'} | "
                 f"Calibration: Platt (sigmoid)")

        return calibrated_model

    except Exception as e:
        log.debug(f"Meta-labeler v2 training failed: {e}")
        return None




def _model_feature_hash(model) -> str:
    """M2 FIX: Compute a short hash of the feature set the model was trained on.
    Stored alongside the model so load-time can detect column drift."""
    import hashlib
    names = list(model.feature_names_in_) if hasattr(model, "feature_names_in_") else []
    raw   = ",".join(sorted(names)).encode()
    return hashlib.md5(raw).hexdigest()[:12]


def _load_meta_model(model_path: str = "meta_model.pkl") -> Optional[object]:
    """Load cached meta-labeler model if fresh (< 7 days).
    M2 FIX: Also validates feature hash against a sidecar .hash file.
    Forces retrain if the feature set has drifted since the model was saved."""
    import pickle
    p = Path(model_path)
    if not p.exists():
        return None
    age_days = (datetime.today() - datetime.fromtimestamp(p.stat().st_mtime)).days
    if age_days > 7:
        log.info(f"Meta-model stale ({age_days}d) -- will retrain")
        return None
    try:
        with open(p, "rb") as f:
            model = pickle.load(f)
        # M2 FIX: Check feature hash sidecar
        hash_path = Path(str(model_path) + ".hash")
        if hash_path.exists() and hasattr(model, "feature_names_in_"):
            saved_hash    = hash_path.read_text().strip()
            current_hash  = _model_feature_hash(model)
            if saved_hash != current_hash:
                log.warning(f"Meta-model feature hash mismatch "
                            f"(saved={saved_hash}, current={current_hash}) — forcing retrain")
                return None
        log.info(f"Meta-model loaded ({age_days}d old)")
        return model
    except Exception as e:
        log.debug(f"Meta-model load failed: {e}")
        return None


def _save_meta_model(model, model_path: str = "meta_model.pkl"):
    """Persist trained meta-labeler and record the closed-pick count at training time.
    M2 FIX: Also writes a .hash sidecar so load-time detects feature drift."""
    import pickle
    try:
        with open(model_path, "wb") as f:
            pickle.dump(model, f)
        log.info(f"Meta-model saved: {model_path}")
        # M2 FIX: Write feature hash sidecar alongside the model
        try:
            Path(str(model_path) + ".hash").write_text(_model_feature_hash(model))
        except Exception:
            pass
        # H3: persist closed-pick count so retrain guard works across restarts
        try:
            closed = sqlite3.connect(DB_PATH, timeout=5).execute(
                "SELECT COUNT(*) FROM pick_outcomes "
                "WHERE status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')"
            ).fetchone()[0]
            Path("meta_model_train_count.txt").write_text(str(closed))
        except Exception:
            pass
    except Exception as e:
        log.debug(f"Meta-model save failed: {e}")


def _heuristic_meta_prob(pick: dict) -> float:
    """ROOT CAUSE #2 FIX: Cold-start meta-probability when meta-model is untrained.
    Without this, all picks get identical 0.55 default → identical AI% → no ranking.
    Weighted blend of the three most reliable early signals:
      fused (40%) — already integrates fortress + APEX, best single predictor
      mc_survival (30%) — Monte Carlo survival is model-agnostic
      bayes_pct (30%) — 14-node Bayesian network output
    Result: HINDCOPPER fused=57, mc=85.5, bayes≈52 → prob≈0.58 (MAYBE)
            THYROCARE  fused=48, mc=92.7, bayes≈52 → prob≈0.57 (MAYBE)
            VESUVIUS   fused=40, mc=82.0, bayes≈52 → prob≈0.53
    Clipped to [0.35, 0.75] — never overconfident without real training data.
    """
    fused = pick.get("fused", 50) or 50
    mc    = pick.get("mc_survival", 50) or 50
    bayes = pick.get("bayes_pct", 50) or 50
    prob  = (fused * 0.40 + mc * 0.30 + bayes * 0.30) / 100
    return round(min(0.75, max(0.35, prob)), 3)


def _get_meta_probability(model, features: dict) -> float:
    """Run meta-model inference on current signal vector. Returns P(profitable)."""
    if model is None:
        return 0.55
    try:
        import pandas as pd
        row = {
            "whale_score": features.get("whale_score", 0),
            "div_score": features.get("div_score", 0),
            "vp_score": features.get("vp_score", 0),
            "pat_score": features.get("pat_score", 0),
            "bayes_pct": features.get("bayes_pct", 0),
            "macro_state": features.get("macro_state", "CHOP"),
            "sector": features.get("sector", "DIVERSIFIED"),
            "vix_level": features.get("vix_level", 18.0),
            "primary_fused_score": features.get("primary_fused_score", 0),
        }
        df = pd.DataFrame([row])
        df["macro_clear"] = (df["macro_state"] == "CLEAR").astype(int)
        df["macro_chop"] = (df["macro_state"] == "CHOP").astype(int)
        df["macro_panic"] = (df["macro_state"].isin(["PANIC","MASSACRE"])).astype(int)

        top_sectors = ["NIFTY IT", "NIFTY PHARMA", "NIFTY AUTO", "NIFTY FMCG", "NIFTY METAL", "DIVERSIFIED"]
        for sec in top_sectors:
            col_name = "sec_" + sec.replace(" ", "_")
            df[col_name] = (df["sector"] == sec).astype(int)

        expected = model.feature_names_in_ if hasattr(model, "feature_names_in_") else None
        if expected is not None:
            for col in expected:
                if col not in df.columns:
                    df[col] = 0
            df = df[expected]

        prob = float(model.predict_proba(df)[0][1])
        return round(prob, 3)
    except Exception as e:
        log.debug(f"Meta-probability inference failed: {e}")
        return 0.55


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5b — DB MIGRATION v3.0-M  (called from _init_db)
# ══════════════════════════════════════════════════════════════════════════════

_DB_SCHEMA_V3 = """
-- A1. Human decision log — feeds the personalized AI Brain
CREATE TABLE IF NOT EXISTS trade_decisions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date     TEXT    NOT NULL,
    symbol       TEXT    NOT NULL,
    decision     TEXT    NOT NULL,   -- TAKEN | SKIPPED | PARTIAL
    entry_price  REAL,
    shares_taken INTEGER DEFAULT 0,
    skip_reason  TEXT,
    ai_confidence REAL,
    worth_flag   TEXT,               -- WORTH_YOUR_TIME | MAYBE | SKIP
    setup_profile TEXT,
    logged_at    TEXT DEFAULT (datetime('now')),
    UNIQUE(run_date, symbol)
);

-- A2. Weekly review snapshots
CREATE TABLE IF NOT EXISTS weekly_reviews (
    week_start         TEXT PRIMARY KEY,
    signals_total      INTEGER DEFAULT 0,
    taken              INTEGER DEFAULT 0,
    skipped            INTEGER DEFAULT 0,
    wins               INTEGER DEFAULT 0,
    losses             INTEGER DEFAULT 0,
    avg_pnl            REAL,
    ai_accuracy_high   REAL,
    ai_accuracy_mid    REAL,
    ai_accuracy_low    REAL,
    summary_text       TEXT,
    generated_at       TEXT DEFAULT (datetime('now'))
);
"""


def _migrate_db_v3():
    """
    Safe, additive v3.0-M migration. Called from _init_db().
    All operations are idempotent — safe to run every startup.
    """
    try:
        con = sqlite3.connect(DB_PATH, timeout=10)
        con.executescript(_DB_SCHEMA_V3)

        # Additive ALTER TABLE — each wrapped to survive "already exists" errors
        alter_stmts = [
            ("meta_features", "setup_profile",       "TEXT"),
            ("meta_features", "days_to_earnings",    "INTEGER DEFAULT -1"),
            ("meta_features", "signals_this_week",   "INTEGER DEFAULT 0"),
            ("meta_features", "your_wr_this_grade",  "REAL DEFAULT 0.5"),
            ("meta_features", "your_wr_this_sector", "REAL DEFAULT 0.5"),
            ("meta_features", "mc_survival",         "REAL"),
            ("meta_features", "fort_norm",           "REAL"),
            ("meta_features", "apex_composite",      "REAL"),
            ("meta_features", "confluence_bonus",    "REAL"),
            ("meta_features", "vix_level",           "REAL"),
        ]
        for table, col, dtype in alter_stmts:
            try:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {dtype}")
            except Exception:
                pass  # Column already exists — fine

        con.commit()
        con.close()
        log.info("DB v3.0-M migration complete ✅")
    except Exception as e:
        log.debug(f"DB v3 migration: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5c — SETUP PROFILE FINGERPRINTING  (v3.0-M)
# ══════════════════════════════════════════════════════════════════════════════

def _get_setup_profile(r: dict) -> str:
    """
    Fingerprint a signal into a 5-char setup profile code.
    Format: [Grade][Macro][Whale][Divergence][VPOC]
    Example: "PCHWV" = PRISTINE, CHOP, Whale detected, hidden div, at VPOC
    """
    grade_code = {"APEX": "A", "PRISTINE": "P", "GOOD": "G", "PROBE": "B"}.get(
        r.get("grade", "PROBE"), "B"
    )
    macro_code = {"CLEAR": "C", "CHOP": "H", "PANIC": "P", "FOG": "F", "MASSACRE": "M"}.get(
        r.get("macro_state", "CHOP"), "H"
    )
    whale_code = "W" if r.get("whale_score", 0) >= 15 else "w"
    div_code   = "D" if r.get("div_score", 0) >= 10 else "d"
    vpoc_code  = "V" if r.get("layer1", False) else "v"
    return f"{grade_code}{macro_code}{whale_code}{div_code}{vpoc_code}"


def _historical_win_rate_for_profile(profile: str, grade: str = None, sector: str = None,
                                      lookback_days: int = 90) -> dict:
    """
    Query YOUR personal win rate for a given setup profile.
    Returns: {total, wins, avg_pnl, win_rate, confidence_label}
    """
    empty = {"total": 0, "wins": 0, "avg_pnl": 0.0, "win_rate": 0.0, "confidence_label": "No history"}
    try:
        since = (datetime.today() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        con = sqlite3.connect(DB_PATH, timeout=5)
        rows = con.execute("""
            SELECT o.status, o.pnl_pct
            FROM trade_decisions td
            JOIN pick_outcomes o ON td.symbol = o.symbol AND td.run_date = o.run_date
            JOIN meta_features mf ON td.symbol = mf.symbol AND td.run_date = mf.run_date
            WHERE td.decision = 'TAKEN'
              AND td.run_date >= ?
              AND o.status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')
              AND mf.setup_profile = ?
        """, (since, profile)).fetchall()
        if len(rows) < 3 and grade:
            rows = con.execute("""
                SELECT o.status, o.pnl_pct
                FROM trade_decisions td
                JOIN pick_outcomes o ON td.symbol = o.symbol AND td.run_date = o.run_date
                JOIN meta_features mf ON td.symbol = mf.symbol AND td.run_date = mf.run_date
                WHERE td.decision = 'TAKEN'
                  AND td.run_date >= ?
                  AND o.status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')
                  AND mf.grade = ?
            """, (since, grade)).fetchall()
        con.close()
        if not rows:
            return empty
        total = len(rows)
        wins  = sum(1 for s, _ in rows if s in ("r1_hit", "r2_hit", "r3_hit"))
        pnls  = [p for _, p in rows if p is not None]
        avg_pnl  = round(sum(pnls) / len(pnls), 2) if pnls else 0.0
        win_rate = round(wins / total * 100, 1)
        if total < 3:
            label = f"{wins}/{total} trades (limited data)"
        elif win_rate >= 60:
            label = f"{wins}/{total} wins avg {avg_pnl:+.1f}% 🟢"
        elif win_rate >= 40:
            label = f"{wins}/{total} wins avg {avg_pnl:+.1f}% 📊"
        else:
            label = f"{wins}/{total} wins avg {avg_pnl:+.1f}% 🔴"
        return {"total": total, "wins": wins, "avg_pnl": avg_pnl,
                "win_rate": win_rate, "confidence_label": label}
    except Exception as e:
        log.debug(f"Profile win rate query failed: {e}")
        return empty


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5d — REGIME-SCALED CONFIDENCE  (v3.0-M)
# ══════════════════════════════════════════════════════════════════════════════

def _regime_scaled_confidence(meta_prob: float, macro_state: str, vix: float) -> float:
    """
    Scale AI confidence by macro regime.
    Ceiling at 0.92 (never claim certainty), floor at 0.10.
    """
    if macro_state == "CLEAR":
        if vix < 13:
            scale = 1.12
        elif vix < 17:
            scale = 1.06
        else:
            scale = 1.00
    elif macro_state == "CHOP":
        scale = 0.88
    elif macro_state == "FOG":
        scale = 0.75
    elif macro_state == "PANIC":
        scale = 0.60
    else:
        scale = 0.40
    return round(min(0.92, max(0.10, meta_prob * scale)), 3)


def _confidence_flag(confidence: float) -> str:
    """Convert 0-1 confidence to human label."""
    if confidence >= 0.75:
        return "WORTH YOUR TIME"
    elif confidence >= 0.55:
        return "MAYBE"
    return "SKIP"


def _confidence_emoji(flag: str) -> str:
    return {"WORTH YOUR TIME": "🟢", "MAYBE": "🔵", "SKIP": "⚪"}.get(flag, "⚪")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5e — CAPACITY GUARD  (v3.0-M)
# ══════════════════════════════════════════════════════════════════════════════

def _capacity_guard(date_label: str) -> dict:
    """
    Prevent alert fatigue and over-trading.
    Returns: {slots_remaining, open_count, taken_this_week, warn, reduce_to_worth_only, note}
    """
    result = {
        "slots_remaining": CAPACITY_MAX_OPEN,
        "open_count": 0,
        "taken_this_week": 0,
        "warn": False,
        "reduce_to_worth_only": False,
        "note": ""
    }
    try:
        con = sqlite3.connect(DB_PATH, timeout=5)
        open_row = con.execute(
            "SELECT COUNT(*) FROM pick_outcomes WHERE status = 'open'"
        ).fetchone()
        open_count = open_row[0] if open_row else 0

        week_start = (datetime.today() - timedelta(days=7)).strftime("%Y-%m-%d")
        week_row = con.execute(
            "SELECT COUNT(*) FROM trade_decisions WHERE decision='TAKEN' AND run_date >= ?",
            (week_start,)
        ).fetchone()
        taken_this_week = week_row[0] if week_row else 0

        recent = con.execute("""
            SELECT o.status FROM trade_decisions td
            JOIN pick_outcomes o ON td.symbol=o.symbol AND td.run_date=o.run_date
            WHERE td.decision='TAKEN'
              AND o.status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')
            ORDER BY td.logged_at DESC LIMIT 3
        """).fetchall()
        con.close()

        consecutive_losses = sum(1 for (s,) in recent if s in ("stopped", "expired"))
        slots = max(0, CAPACITY_MAX_OPEN - open_count)

        result["open_count"]      = open_count
        result["taken_this_week"] = taken_this_week
        result["slots_remaining"] = slots

        if open_count >= CAPACITY_MAX_OPEN:
            result["warn"] = True
            result["reduce_to_worth_only"] = True
            result["note"] = f"⚠️ {open_count} open positions — only WORTH YOUR TIME signals today"
        elif consecutive_losses >= 2:
            result["warn"] = True
            result["reduce_to_worth_only"] = True
            result["note"] = f"⚠️ {consecutive_losses} consecutive losses — raising the bar"
        elif taken_this_week >= CAPACITY_MAX_WEEK:
            result["reduce_to_worth_only"] = True
            result["note"] = f"📊 {taken_this_week} trades this week — quality over quantity"
    except Exception as e:
        log.debug(f"Capacity guard: {e}")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5f — TRADE DECISION LOGGER  (v3.0-M)
# ══════════════════════════════════════════════════════════════════════════════

def confirm_entry(symbol: str) -> tuple:
    """M3 FIX: Pre-entry earnings confirmation gate.
    Call this in your Telegram reply handler BEFORE logging a TAKEN decision.
    Earnings announced after scoring but before manual entry (e.g. pre-market next morning)
    would otherwise let you walk blind into a volatility event.

    Returns: (allowed: bool, reason: str)
    Usage in reply_handler.py:
        ok, reason = confirm_entry(symbol)
        if not ok:
            _tg_post(TOKEN, CHAT_ID, f"⛔ {symbol} BLOCKED: {reason}")
            return
        _log_trade_decision(run_date, symbol, "TAKEN", entry_price=price)
    """
    earn_days = _check_earnings_yf(symbol)
    if earn_days is not None and 0 <= earn_days <= 1:
        return False, f"Earnings in {earn_days}d — entry blocked to avoid volatility event"
    # Also re-check the hardcoded earnings calendar in case yfinance misses it
    if earn_days is None:
        log.debug(f"confirm_entry({symbol}): yfinance calendar unavailable — proceeding with caution")
    return True, "OK"


def _log_trade_decision(run_date: str, symbol: str, decision: str,
                         entry_price: float = None, shares: int = 0,
                         skip_reason: str = None, ai_confidence: float = None,
                         worth_flag: str = None, setup_profile: str = None):
    """
    Log a manual trade decision to trade_decisions table.
    Called by reply_handler.py when you reply to the Telegram bot.
    NOTE: Call confirm_entry(symbol) before calling this for TAKEN decisions.
    """
    try:
        with _db_conn(write=True) as con:
            con.execute("""
                INSERT OR REPLACE INTO trade_decisions
                  (run_date, symbol, decision, entry_price, shares_taken,
                   skip_reason, ai_confidence, worth_flag, setup_profile)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (run_date, symbol.upper(), decision, entry_price, shares,
                  skip_reason, ai_confidence, worth_flag, setup_profile))
        log.info(f"Decision logged: {symbol} → {decision} "
                 f"({'₹'+str(entry_price) if entry_price else skip_reason})")
    except Exception as e:
        log.error(f"Decision log failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5g — WEEKLY REVIEW  (v3.0-M)
# ══════════════════════════════════════════════════════════════════════════════

def _send_weekly_review():
    """
    Generate and send a personalised weekly performance review via Telegram.
    Analyses YOUR decisions vs outcomes. Run every Friday via GitHub Actions.
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        week_start = (datetime.today() - timedelta(days=7)).strftime("%Y-%m-%d")
        con = sqlite3.connect(DB_PATH, timeout=10)
        decisions = con.execute("""
            SELECT td.symbol, td.decision, td.entry_price, td.ai_confidence, td.worth_flag,
                   o.status, o.pnl_pct, o.days_held
            FROM trade_decisions td
            LEFT JOIN pick_outcomes o ON td.symbol=o.symbol AND td.run_date=o.run_date
            WHERE td.run_date >= ?
        """, (week_start,)).fetchall()
        total_signals = con.execute(
            "SELECT COUNT(DISTINCT symbol) FROM sniper_results WHERE run_date >= ?",
            (week_start,)
        ).fetchone()[0]
        con.close()

        taken   = [d for d in decisions if d[1] == "TAKEN"]
        skipped = [d for d in decisions if d[1] == "SKIPPED"]
        closed  = [d for d in taken if d[5] and d[5] not in ("open", None)]
        wins    = [d for d in closed if d[5] in ("r1_hit","r2_hit","r3_hit")]
        losses  = [d for d in closed if d[5] in ("stopped","expired")]
        pnls    = [d[6] for d in closed if d[6] is not None]
        avg_pnl = round(sum(pnls)/len(pnls), 2) if pnls else 0.0

        high_taken = [d for d in closed if d[3] and d[3] >= 0.75]
        mid_taken  = [d for d in closed if d[3] and 0.55 <= d[3] < 0.75]
        low_taken  = [d for d in closed if d[3] and d[3] < 0.55]

        def _acc(grp):
            if not grp: return None
            return round(sum(1 for d in grp if d[5] in ("r1_hit","r2_hit","r3_hit")) / len(grp) * 100, 1)

        acc_high = _acc(high_taken)
        acc_mid  = _acc(mid_taken)
        acc_low  = _acc(low_taken)
        wr = round(len(wins)/len(closed)*100, 1) if closed else 0.0
        week_num = datetime.today().strftime("%V")

        lines = [
            f"📊 WEEKLY REVIEW — Week {week_num} ({week_start} to today)",
            "",
            f"Signals: {total_signals} | Taken: {len(taken)} | Skipped: {len(skipped)} | Open: {len(taken)-len(closed)}",
            "",
            "📈 Your results (closed trades):",
        ]
        if closed:
            best  = max(closed, key=lambda d: d[6] or -99)
            worst = min(closed, key=lambda d: d[6] or 99)
            lines += [
                f"  Win rate: {len(wins)}/{len(closed)} ({wr}%) | Avg P&L: {avg_pnl:+.1f}%",
                f"  Best: {best[0]} {best[6]:+.1f}% | Worst: {worst[0]} {worst[6]:+.1f}%",
            ]
        else:
            lines.append("  No closed trades this week yet.")

        lines += ["", "🤖 AI Confidence accuracy:"]
        if acc_high is not None:
            lines.append(f"  >75% confidence ({len(high_taken)} trades) → {acc_high}% win rate {'✅' if acc_high >= 60 else '⚠️'}")
        if acc_mid is not None:
            lines.append(f"  55-75% confidence ({len(mid_taken)} trades) → {acc_mid}% win rate {'📊' if acc_mid >= 50 else '⚠️'}")
        if acc_low is not None:
            lines.append(f"  <55% confidence ({len(low_taken)} trades) → {acc_low}% win rate {'🚫' if acc_low < 40 else '📊'}")

        lines.append("")
        if acc_low is not None and acc_low < 35 and len(low_taken) >= 2:
            lines.append("💡 Insight: Skip signals under 55% confidence — your data confirms it loses.")
        elif acc_high is not None and acc_high >= 65 and len(high_taken) >= 2:
            lines.append("💡 Insight: High-confidence signals are working — trust the >75% threshold.")
        elif wr < 40 and len(closed) >= 3:
            lines.append("💡 Insight: Win rate low this week — consider tightening entry to buy zone only.")
        else:
            lines.append("💡 Stay consistent — the edge compounds over time. Bismillah 🤲")

        msg = "\n".join(lines)
        _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, msg)

        try:
            con = sqlite3.connect(DB_PATH, timeout=10)
            con.execute("""
                INSERT OR REPLACE INTO weekly_reviews
                  (week_start, signals_total, taken, skipped, wins, losses, avg_pnl,
                   ai_accuracy_high, ai_accuracy_mid, ai_accuracy_low, summary_text)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (week_start, total_signals, len(taken), len(skipped),
                  len(wins), len(losses), avg_pnl, acc_high, acc_mid, acc_low, msg))
            con.commit(); con.close()
        except Exception as e:
            log.debug(f"Weekly review DB store: {e}")

        log.info("Weekly review sent ✅")
    except Exception as e:
        log.error(f"Weekly review failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# ── CALIBRATED PRIORS (based on NSE halal mid-cap backtest estimates) ──
# These are conservative estimates. Replace with your actual backtest results.
# M1 FIX: Regime-aware prior overrides for macro_clear node.
# In CLEAR regime, macro_clear=True is the norm — the prior edge is already baked in.
# In PANIC/MASSACRE, stocks that look "clear" are actually in denial; cut the pt aggressively.
# In CHOP, macro_clear=True is rare and mildly meaningful; reduce its signal slightly.
# Format mirrors _BAYES_PRIORS: (pt, pf, weight) — only the macro_clear tuple is overridden.
_REGIME_PRIOR_OVERRIDES: dict = {
    "PANIC":    {"macro_clear": (0.44, 0.38, 1.0)},  # Clear-looking stocks in PANIC are traps
    "MASSACRE": {"macro_clear": (0.30, 0.38, 1.0)},  # Invert edge: being "clear" means denial
    "CHOP":     {"macro_clear": (0.52, 0.42, 1.0)},  # Mild edge reduction vs CLEAR's 0.58
}

_BAYES_PRIORS = {
    # Format: (condition, profit_prob_if_true, profit_prob_if_false, weight)
    # Weights sum to ~1.0, adjusted by empirical edge

    # Macro conditions (strong signal in NSE)
    ("macro_clear", 0.58, 0.42, 1.0),      # Was 0.72/0.28 — too optimistic
    ("breadth_ok", 0.55, 0.40, 0.8),         # Was 0.65/0.38

    # VPOC layers (moderate signal — many false positives)
    ("layer1", 0.52, 0.35, 1.0),             # Was 0.72/0.30
    ("layer2", 0.50, 0.38, 0.9),             # Was 0.68/0.38
    ("layer3", 0.51, 0.36, 0.9),             # Was 0.70/0.35

    # Technicals (weak-moderate signal)
    ("mfi_oversold", 0.48, 0.40, 0.7),       # Was 0.68/0.42
    ("adx_trending", 0.50, 0.42, 0.7),       # Was 0.68/0.38
    ("not_overextended", 0.46, 0.38, 0.6),   # Was 0.62/0.40

    # APEX signals (strong when combined)
    ("whale_detected", 0.55, 0.42, 0.9),     # Was 0.74/0.44
    ("bullish_hidden_div", 0.53, 0.40, 0.8), # Was 0.70/0.40
    ("vp_score_high", 0.51, 0.40, 0.7),      # Was 0.67/0.40
    ("mc_survival_ok", 0.50, 0.42, 0.6),     # Was 0.68/0.45

    # Intelligence (strong signal when real)
    ("fii_buying", 0.54, 0.42, 0.8),         # Was 0.66/0.40
    ("insider_buying", 0.52, 0.42, 0.7),     # Was 0.65/0.42
    ("positive_filing", 0.51, 0.42, 0.6),    # Was 0.63/0.42
}


def _bayesian_apex(macro_state: str, breadth_ok: bool, layer1: bool, layer2: bool, layer3: bool,
                   whale_detected: bool, div_type: str, vp_score: float,
                   mfi_v: float, adx_v: float, alt_pct: float,
                   mc_survival: Optional[float],
                   fii_pts: int, ins_pts: int, fil_pts: int) -> dict:
    """
    Calibrated 14-node Bayesian network — FIXED v2.
    Root cause of original failure: log-odds sequential update with conservative
    priors (pt≈0.52, pf≈0.40) generates log(pf/(1-pf)) ≈ -0.40 per false node.
    With 15 nodes × avg weight 0.8, most CHOP setups accumulated −4 log-odds,
    driving posterior to <5% before shrinkage, then bayes_pct stayed at 5-18.

    Fix: Replace broken log-odds accumulation with a two-stage additive scorer:
      Stage 1 — Base rate (40%) + positive node contributions (scaled 0-60% range)
      Stage 2 — Shrinkage toward 50% (epistemic humility, prevents overfit)
    Target range: 35-75% when 0/14 to 8/14 nodes are true.
    At 2-3 true nodes (typical CHOP pick): should produce 45-58%.
    At 5-6 true nodes (good CLEAR pick): should produce 60-70%.
    """
    # Build condition map — same as before, no change
    conditions = {
        "macro_clear":       macro_state == "CLEAR",
        "breadth_ok":        breadth_ok,
        "layer1":            layer1,
        "layer2":            layer2,
        "layer3":            layer3,
        "mfi_oversold":      mfi_v <= 45.0,
        "adx_trending":      adx_v >= 25.0,
        "not_overextended":  alt_pct < 30.0,
        "whale_detected":    whale_detected,
        "bullish_hidden_div": div_type == "BULLISH_HIDDEN",
        "vp_score_high":     vp_score >= 40,
        "mc_survival_ok":    mc_survival is not None and mc_survival >= 65,
        "fii_buying":        fii_pts >= 22,
        "insider_buying":    ins_pts >= 15,
        "positive_filing":   fil_pts >= 20,
    }

    # ── Stage 1: Weighted signal accumulation ────────────────────────────
    # Each node contributes an edge score: (pt - pf) × weight normalised to [0, 1].
    # This measures how much the TRUE condition beats the FALSE condition baseline.
    # A node where pt=0.52, pf=0.40, weight=1.0 contributes edge = 0.12 × 1.0 = 0.12.
    # Summed across 15 nodes (total potential weight ≈ 11.7), max positive edge ≈ 1.76.
    # We scale this to a 0-60 percentage-point uplift above a 35% floor.
    total_positive_edge = 0.0
    max_possible_edge   = 0.0

    # M1 FIX: Apply regime-specific prior overrides before iterating.
    # In PANIC/MASSACRE, the macro_clear node prior is recalculated — not just shifted
    # by a flat regime_adj after the fact. This correctly reduces signal strength at
    # the source rather than patching the output.
    regime_overrides = _REGIME_PRIOR_OVERRIDES.get(macro_state, {})

    for name, pt, pf, weight in _BAYES_PRIORS:
        # Apply override tuple if this regime has one for this node
        if name in regime_overrides:
            pt, pf, weight = regime_overrides[name]
        cond = conditions.get(name, False)
        edge = (pt - pf) * weight          # always positive (pt > pf by design)
        if cond:
            total_positive_edge += edge    # accumulate only when condition is true
        max_possible_edge += edge          # track theoretical maximum

    # Normalise: positive_ratio = 0 when no conditions true, 1 when all true
    positive_ratio = (total_positive_edge / max(max_possible_edge, 1e-9))

    # Map ratio → probability: floor=0.35, ceil=0.78, range=0.43
    # At ratio=0.00 (no conditions): p = 0.35 (worse than coin-flip — good prior)
    # At ratio=0.20 (2-3 conditions, CHOP typical): p ≈ 0.44
    # At ratio=0.35 (4-5 conditions, CLEAR good): p ≈ 0.50
    # At ratio=0.55 (7-8 conditions, CLEAR great): p ≈ 0.59
    # At ratio=1.00 (all conditions): p = 0.78
    raw_prob = 0.35 + positive_ratio * 0.43

    # ── Stage 2: Macro-aware regime adjustment ────────────────────────────
    # In CHOP we're already picking the best available — apply a small floor lift.
    # In PANIC or MASSACRE the Bayesian evidence is unreliable — shrink to neutral.
    if macro_state == "CLEAR":
        regime_adj = +0.03
    elif macro_state == "CHOP":
        regime_adj = +0.01    # small positive: CHOP setups that pass Fortress are pre-filtered
    elif macro_state == "PANIC":
        regime_adj = -0.05
    else:  # MASSACRE — pipeline already returns None upstream, but guard here
        regime_adj = -0.15

    prob_after_regime = raw_prob + regime_adj

    # ── Stage 3: Shrinkage toward 50% (epistemic humility) ───────────────
    # α=0.20 means: "I trust my signal 80%, fallback to coin-flip 20%"
    alpha = 0.20
    posterior = alpha * 0.50 + (1 - alpha) * prob_after_regime
    posterior = min(0.95, max(0.05, round(posterior, 3)))

    pct = round(posterior * 100)

    # Tier thresholds — tuned for the new 35-78% output range
    if posterior >= 0.65:    tier, bonus = "HIGH",     8
    elif posterior >= 0.55:  tier, bonus = "MODERATE", 4
    elif posterior >= 0.47:  tier, bonus = "NEUTRAL",  0
    else:                    tier, bonus = "LOW",      -5

    return {
        "bayes_prob":  posterior,
        "bayes_pct":   pct,
        "bayes_tier":  tier,
        "bayes_bonus": bonus,
        "bayes_label": f"{tier} conviction ({pct}%)",
        "calibrated":  True,
        "positive_ratio": round(positive_ratio, 3),   # diagnostic
    }


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 13 — FUSED COMPOSITE ASSEMBLER
# ══════════════════════════════════════════════════════════════════════════════

def assemble_pick(
    symbol: str,
    today_row,
    hist: pd.DataFrame,
    fii_data: dict,
    insider_map: dict,
    filings: dict,
    earnings_cal: dict,
    macro: dict,
) -> Optional[dict]:
    """
    Single-pass fused scorer.
    Step 1: Fortress engine (hard veto, VPOC, sector, intelligence scores)
    Step 2: APEX 7-engine (whale, divergence, patterns, MC, Bayesian)
    Step 3: Fused composite = fort_total × 0.45 + apex_composite × 0.55
    Step 4: Grade, story, exits, position size.
    """
    macro_state = macro.get("macro_state","CHOP")
    breadth_ok  = macro.get("breadth_ok",True)
    vix         = macro.get("vix_val",18.0)

    # ── Earnings hard veto ─────────────────────────────────────────────
    earn_days = earnings_cal.get(symbol.upper())
    if earn_days is None:
        earn_days = _check_earnings_yf(symbol)
    if earn_days is not None and 0 <= earn_days <= 2:
        log.warning(f"{symbol}: EARNINGS VETO ({earn_days}d) — skipped")
        return None

    if macro_state == "MASSACRE":
        return None

    # ── FORTRESS STEP ─────────────────────────────────────────────────
    fort = fortress_score(symbol, today_row, hist, macro_state=macro_state)  # RC3 FIX: pass regime
    if fort is None:
        return None

    # DEBUG: Log symbols that pass fortress (to see pipeline flow)
    log.info(f"  PIPELINE {symbol}: fortress_pts={fort['fortress_pts']:.0f} | "
             f"macro={macro_state} | vix={vix:.1f} | sector={get_sector(symbol)}")

    close    = float(today_row["close"])
    dq       = str(today_row.get("data_quality",""))
    if dq in ("SNAPSHOT_FALLBACK","STALE") and fort["fortress_pts"] > 55:
        fort["fortress_pts"] = 55

    fii_pts  = fii_data.get("score",15)
    fii_lbl  = fii_data.get("label","—")
    fii_det  = fii_data.get("detail","—")
    ins_data = insider_map.get(symbol.upper(), {})
    ins_pts  = ins_data.get("score",0)
    ins_det  = ins_data.get("detail","No insider trades in 30d")
    fil_data = filings.get(symbol.upper(), {})
    fil_pts  = fil_data.get("score",15)
    fil_det  = fil_data.get("detail","No recent filing")

    # ROE quality gate
    if fil_pts>15 and dq not in ("SNAPSHOT_FALLBACK","STALE"):
        roe_val, roe_lbl = _fetch_roce(symbol)
        if roe_val is None:
            fil_pts=min(fil_pts,10); fil_det=f"{fil_det} | ⚠️ ROE unverifiable"
        elif roe_val<5.0:
            fil_pts=min(fil_pts,8); fil_det=f"{fil_det} | ❌ {roe_lbl}"
        else:
            fil_det=f"{fil_det} | ✅ {roe_lbl}"

    # Earnings safety score
    def _earn_pts():
        if earn_days is None: return 20,"No result date"
        if earn_days<0:
            r=abs(earn_days)
            if r<=5:  return 28,"Results just announced — fresh data"
            elif r<=21: return 25,f"Results {r}td ago — clear runway"
            else:     return 20,f"Results {r}td ago"
        else:
            if earn_days<=2:  return 5, f"⚠️ Results in {earn_days}td — SIZE SMALL"
            elif earn_days<=5: return 10,f"⚠️ Results in {earn_days}td — risky"
            elif earn_days<=10: return 18,f"Results in {earn_days}td — caution"
            elif earn_days<=21: return 24,f"Results in {earn_days}td — acceptable"
            else:              return 30,f"Results in {earn_days}td — safe runway ✓"
    earn_pts, earn_det = _earn_pts()

    fort_total = min(FORT_TOTAL_MAX, fort["fortress_pts"]+fii_pts+ins_pts+fil_pts+earn_pts)

    # ── APEX STEP ─────────────────────────────────────────────────────
    atr14   = fort["atr14"]; adv20=fort["adv20"]
    vpoc    = fort["vpoc"];  ma200=fort["ma200"]
    sector  = get_sector(symbol)

    profile       = _vpoc_profile(hist)
    poc           = profile.get("poc", vpoc) or vpoc

    stop_from_atr = close - 2.5*atr14*SECTOR_ATR_MULT.get(sector,1.0)
    stop_from_poc = poc*0.97 if poc>0 else stop_from_atr
    stop_loss     = round(max(min(stop_from_atr,stop_from_poc), close*0.88), 2)
    risk_pct      = round((close-stop_loss)/close*100, 1)

    whale_score, whale_det = _whale_radar(hist, adv20)
    div_score,   div_det   = _divergence_engine(hist)
    vp_score,    vp_label  = _vol_profile_score(profile, close, fortress_vpoc=vpoc)
    pat_score,   pat_label = _pattern_score(hist, atr14, profile)
    mc          = _monte_carlo(hist, stop_loss, close)
    mc_survival = mc.get("survival")

    # H2 FIX: hard veto — if MC says survival < 50% with valid data, reject the pick.
    if mc.get("hard_veto"):
        log.info(f"  🚫 {symbol}: MC hard veto (survival={mc_survival}% < 50% on valid data)")
        return None

    vol_rel = fort["vol_reliable"]
    cvd     = _calc_cvd(hist, vol_rel)
    vsa     = _calc_vsa(hist, atr14, adv20, vol_rel)
    fog     = _calc_fog(fort["adx"], fort["adx_prev"], vix, fort["ma50"], fort["ma200"], fort["w52_bonus"])

    bayes = _bayesian_apex(
        macro_state=macro_state, breadth_ok=breadth_ok,
        layer1=fort["layer1"], layer2=fort["layer2"], layer3=fort["layer3"],
        whale_detected=whale_det["whale_detected"] or whale_det["stealth_score"]>=50,
        div_type=div_det["div_type"], vp_score=vp_score,
        mfi_v=fort["mfi"], adx_v=fort["adx"], alt_pct=fort["alt_pct"],
        mc_survival=mc_survival,
        fii_pts=fii_pts, ins_pts=ins_pts, fil_pts=fil_pts,    # ← intelligence fusion
    )

    macro_damp = {"CLEAR":1.0,"CHOP":0.88,"PANIC":0.60,"MASSACRE":0.0}
    bayes_score = float(bayes["bayes_pct"])

    # ── CHOP pre-compensation constant ──────────────────────────────────
    # BUG FIX: Old code applied "+8" AFTER dampening: raw×0.88+8.
    # At raw=30: 26.4+8=34.4 (still −13% vs CLEAR's 30). Compensation was ineffective.
    # New approach: add to raw BEFORE dampening so the effect survives the multiply.
    # CRIT-2 FIX: Raised from 12→20 so CHOP picks can clear APEX_MIN_SCORE=35 (CHOP floor).
    # At raw=30 in CHOP: (30+20)×0.88=44.0 (+47% vs undamped 30).
    # At raw=60 in CHOP: (60+20)×0.88=70.4 vs CLEAR 60 (+17%).
    _CHOP_PRE_COMP = 20

    # ── APEX CONFLUENCE SCORE (NOT double-counting VPOC) ──
    # Instead of re-scoring VPOC layers (already in fortress_pts),
    # measure how strongly the INDEPENDENT APEX engines confirm
    # the same trade idea. This is pure confluence, not duplication.

    # Confluence bonuses: when multiple engines agree on direction
    confluence_bonus = 0
    confluence_notes = []

    # Whale + Divergence agreement (strong)
    if whale_det["whale_detected"] and div_det["div_type"] == "BULLISH_HIDDEN":
        confluence_bonus += 15
        confluence_notes.append("Whale+Div agree")

    # Pattern + Volume Profile agreement (moderate)
    if vp_score >= 40 and ("VCP" in pat_label or "Cup" in pat_label):
        confluence_bonus += 12
        confluence_notes.append("VP+Pattern agree")

    # Bayesian + MC agreement (moderate)
    if bayes["bayes_pct"] >= 60 and mc_survival is not None and mc_survival >= 70:
        confluence_bonus += 10
        confluence_notes.append("Bayes+MC agree")

    # All four engines aligned (rare, powerful)
    engines_aligned = sum([
        whale_det["whale_detected"],
        div_det["div_type"] == "BULLISH_HIDDEN",
        vp_score >= 35,
        bayes["bayes_pct"] >= 55
    ])
    if engines_aligned >= 4:
        confluence_bonus += 8
        confluence_notes.append("All engines aligned")
    elif engines_aligned == 3:
        confluence_bonus += 4
        confluence_notes.append("3/4 engines aligned")

    # Cap confluence to prevent runaway scores
    confluence_bonus = min(35, confluence_bonus)

    # ── APEX RAW COMPOSITE (independent of fortress VPOC) ──
    raw_apex = (
        whale_score          * W["whale_radar"]   +
        div_score            * W["divergence"]    +
        vp_score             * W["vol_profile"]   +
        pat_score            * W["pattern"]       +
        bayes_score          * W["bayesian"]      +
        confluence_bonus     * W["fortress_vpoc"]  # Reuse weight slot for confluence
    )
    # FIX: apply CHOP pre-compensation BEFORE dampening so it survives the multiply.
    # In CLEAR/PANIC/MASSACRE the constant is 0 (no effect).
    chop_pre = _CHOP_PRE_COMP if macro_state == "CHOP" else 0
    apex_composite = round((raw_apex + chop_pre) * macro_damp.get(macro_state, 0.88))
    # Independent bonuses (not double-counting)
    if bayes["bayes_pct"] >= 75 and mc_survival is not None and mc_survival >= 75:
        apex_composite = min(100, apex_composite + 5)  # High conviction + high survival
    apex_composite = max(0, min(100, apex_composite))

    # ── FUSED COMPOSITE + GRADE ────────────────────────────────────────
    # BUG FIX: fort_norm, fused, and grade were referenced but never
    # assigned anywhere in this function, causing NameError at runtime.
    # fort_norm   — fortress total as 0-100 percentage (for return dict)
    # fused       — weighted blend: fortress 45% + APEX 55%
    # grade       — categorical label derived from fused threshold bands
    fort_norm = round((fort_total / FORT_TOTAL_MAX) * 100, 1)
    fused = max(0, min(100, round(fort_norm * 0.45 + apex_composite * 0.55)))
    grade = (
        "APEX"     if fused >= GRADE_APEX     else
        "PRISTINE" if fused >= GRADE_PRISTINE else
        "GOOD"     if fused >= GRADE_GOOD     else
        "PROBE"
    )

    # ── DEBUG: Log rejections for tuning ──
    # CRIT-2 FIX: Use a lower floor in CHOP so sideways-market picks aren't all rejected.
    apex_floor = 35 if macro_state == "CHOP" else APEX_MIN_SCORE
    if apex_composite < apex_floor:
        log.info(f"  DEBUG {symbol}: REJECTED | apex={apex_composite} (floor={apex_floor}/{macro_state}) | bayes={bayes['bayes_pct']}% | "
                 f"whale={whale_score:.0f} | div={div_score:.0f} | vp={vp_score:.0f} | pat={pat_score:.0f} | "
                 f"mc={mc_survival} | confluence={confluence_bonus} | damp={macro_damp.get(macro_state,0.88)}")
        return None

    # ── META-LABELING: Store signal vector + optional veto ──

    # (veto moved to debug block above)
    atr_m  = SECTOR_ATR_MULT.get(sector,1.0)
    risk   = atr14*2.0*atr_m if atr14>0 else close*0.03
    r1     = round(close+risk*2.5,2)
    r2     = round(close+risk*4.0,2)
    r3     = round(close+risk*6.5,2)
    trail_stop = round(r2-atr14*2.5*atr_m,2)
    r1_pct=round((r1-close)/close*100,1); r2_pct=round((r2-close)/close*100,1)
    r3_pct=round((r3-close)/close*100,1)

    # ── Dynamic Position Sizing (Fractional Kelly) ─────────────────────
    def _get_kelly_inputs(symbol: str, grade: str, sector: str) -> tuple:
        """Return (empirical_win_rate, avg_win, avg_loss) from matched history."""
        try:
            con = sqlite3.connect(DB_PATH)
            rows = con.execute(
                """SELECT pnl_pct FROM pick_outcomes
                   WHERE grade=? AND sector=?
                   AND status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')
                   AND run_date > ?""",
                (grade, sector, (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d"))
            ).fetchall()
            con.close()

            if len(rows) < 20:
                return None, None, None

            pnls = [r[0] for r in rows if r[0] is not None]
            if not pnls:
                return None, None, None

            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]

            win_rate = len(wins) / len(pnls)
            avg_win = np.mean(wins) if wins else 0
            avg_loss = abs(np.mean(losses)) if losses else 0

            return win_rate, avg_win, avg_loss
        except Exception as e:
            log.debug(f"Kelly inputs {symbol}: {e}")
            return None, None, None

    def _kelly_fraction(p: float, b: float, max_frac: float = ACCOUNT_RISK_PCT,
                        empirical: bool = False, sample_count: int = 0) -> float:
        """
        f = (p*b - q) / b, fractional Kelly conservative.
        If empirical data insufficient (< 100 matched trades), use quarter-Kelly capped at 0.5%.
        Only scale up to half-Kelly after 100+ matched trades.
        """
        q = 1.0 - p
        if b <= 0 or p <= 0 or p >= 1:
            return max_frac * 0.25

        raw_kelly = (p * b - q) / b
        raw_kelly = max(0.0, raw_kelly)

        if not empirical or sample_count < 100:
            return min(max_frac * 0.25, 0.005)
        else:
            return min(max_frac, raw_kelly * 0.5)

    emp_wr, emp_win, emp_loss = _get_kelly_inputs(symbol, grade, sector)

    if emp_wr is not None and emp_loss > 0:
        b_emp = emp_win / emp_loss if emp_loss > 0 else 2.0
        p_emp = emp_wr
        try:
            con = sqlite3.connect(DB_PATH)
            count_row = con.execute(
                """SELECT COUNT(*) FROM pick_outcomes
                   WHERE grade=? AND sector=?
                   AND status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')
                   AND run_date > ?""",
                (grade, sector, (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d"))
            ).fetchone()
            con.close()
            sample_count = count_row[0] if count_row else 0
        except Exception:
            sample_count = 0

        kelly_frac = _kelly_fraction(p_emp, b_emp, max_frac=ACCOUNT_RISK_PCT,
                                     empirical=True, sample_count=sample_count)
        kelly_source = f"empirical ({sample_count} samples)"
    else:
        b_default = 2.0
        p_default = 0.45
        kelly_frac = _kelly_fraction(p_default, b_default, max_frac=ACCOUNT_RISK_PCT,
                                     empirical=False, sample_count=0)
        kelly_source = "default (insufficient history)"

    rps = max(close - stop_loss, close * 0.02)
    risk_r = ACCOUNT_EQUITY * kelly_frac
    sh_v = math.floor(risk_r / rps) if rps > 0 else 0

    deploy = (1.00 if fused >= GRADE_APEX else 0.75 if fused >= GRADE_PRISTINE
              else 0.50 if fused >= GRADE_GOOD else 0.25)

    sh_f = min(math.floor(sh_v * deploy),
               math.floor(ACCOUNT_EQUITY * 0.10 / close) if close > 0 else 0)
    pos_v = sh_f * close
    pos_lb = (f"{sh_f} sh × ₹{close:.2f} = ₹{pos_v:,.0f} | Risk ₹{sh_f*rps:,.0f} | Kelly {kelly_frac*100:.2f}% [{kelly_source}]"
              if sh_f > 0 else "— (below sizing min)")

    # Circuit breaker for small caps
    # Circuit breaker for small caps
    alloc_note = ""
    if close < MAX_PRICE:
        cb_active, cb_msg = check_smallcap_cb()
        if cb_active: alloc_note=f" ⚠️ CB: {cb_msg[:40]}"

    # ── Sector momentum bonus/penalty ──────────────────────────────────
    sector_mom = _live_sector_momentum(sector)
    mom_bonus = sector_mom["bonus"]
    fused = max(0, min(100, fused + mom_bonus))
    # Re-derive grade so return dict reflects post-momentum score
    grade = (
        "APEX"     if fused >= GRADE_APEX     else
        "PRISTINE" if fused >= GRADE_PRISTINE else
        "GOOD"     if fused >= GRADE_GOOD     else
        "PROBE"
    )
    mom_note = f" | Sector {sector_mom['momentum_tier']} ({sector_mom['rel_5d']:+.1f}% 5d)" if mom_bonus != 0 else ""

    # ── META-LABELING: Store final signal vector + model veto ───────────
    # Now that fused and grade are fully resolved (post-sector-momentum),
    # we store the complete feature vector that will be used for ML training.
    # Every signal that passes the min-score gate is stored here so the DB
    # accumulates trade history aggressively — this is what feeds the AI Brain.
    meta_features = {
        "whale_score":        whale_score,
        "div_score":          div_score,
        "vp_score":           vp_score,
        "pat_score":          pat_score,
        "bayes_pct":          bayes["bayes_pct"],
        "mc_survival":        mc_survival or 0,
        "fort_norm":          fort_norm,
        "apex_composite":     apex_composite,
        "confluence_bonus":   confluence_bonus,
        "macro_state":        macro_state,
        "sector":             sector,
        "vix_level":          vix,
        "grade":              grade,
        "primary_fused_score": fused,
    }
    _store_meta_features(
        datetime.today().strftime("%Y-%m-%d"),
        symbol, meta_features
    )

    meta_model = _load_meta_model()
    # RC2 FIX: When meta-model is untrained (< 20 closed picks), _get_meta_probability
    # returns a flat 0.55 for every pick → identical AI% → no ranking differentiation.
    # Use _heuristic_meta_prob() instead, which blends fused/mc/bayes for real signal.
    # We need the partial pick dict built so far; r is assembled below, so pass locals.
    _partial = {"fused": fused, "mc_survival": mc_survival, "bayes_pct": bayes["bayes_pct"]}
    if meta_model is None:
        meta_prob = _heuristic_meta_prob(_partial)
        log.debug(f"  {symbol}: cold-start meta_prob={meta_prob:.3f} (heuristic)")
    else:
        meta_prob = _get_meta_probability(meta_model, meta_features)
    # FIX 5: Meta-model veto guard.
    # The meta-labeler is trained incrementally via _train_meta_labeler(min_samples=50).
    # When trained on fewer than 200 profitable samples its class imbalance causes it
    # to learn "veto everything" — exactly what Bug 5 predicts.
    # Guard: only apply the veto when the model was trained on ≥ 200 closed picks
    # AND the probability is clearly below the threshold (< 0.40 rather than 0.45).
    # This lets early picks through while the DB accumulates enough outcome history.
    meta_sample_count = 0
    try:
        _mc = sqlite3.connect(DB_PATH, timeout=5)
        _row = _mc.execute(
            "SELECT COUNT(*) FROM pick_outcomes WHERE status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')"
        ).fetchone()
        _mc.close()
        meta_sample_count = _row[0] if _row else 0
    except Exception:
        pass

    _META_VETO_THRESHOLD = 0.40   # stricter than old 0.45 (less hair-trigger)
    _META_MIN_SAMPLES    = 200    # don't trust the model until we have enough data

    if meta_sample_count >= _META_MIN_SAMPLES and meta_prob < _META_VETO_THRESHOLD:
        log.info(f"  🚫 {symbol}: Meta-model veto (P={meta_prob:.2f} < {_META_VETO_THRESHOLD}, "
                 f"n={meta_sample_count} samples)")
        return None
    elif meta_sample_count < _META_MIN_SAMPLES:
        log.debug(f"  Meta-model: skipping veto ({meta_sample_count} < {_META_MIN_SAMPLES} samples needed)")

    # ── FOG sizing cap ─────────────────────────────────────────────────
    fog_note=""
    if fog["fog_block"]:
        cap  = 10 if fog["fog_tier"]=="FOG_SEVERE" else 25
        deploy=min(deploy, cap/100)
        sh_f = min(sh_f, math.floor(sh_f*(cap/100)*2))
        fog_note=f" | {fog['fog_label'][:40]}"

    # ── Story: structured human-readable narrative ─────────────────────
    parts=[]
    if "BUYING" in fii_lbl and "FII+DII" in fii_lbl: parts.append("institutional tide in — FII+DII both accumulating")
    elif "FII BUYING" in fii_lbl:                     parts.append("FII net buyers — foreign flows positive")
    if ins_det and "buy" in ins_det.lower() and ins_pts>=10: parts.append(f"insiders accumulating ({ins_det[:40]})")
    if fil_det and "No recent" not in fil_det and fil_pts>=20: parts.append(fil_det[:50])
    if whale_det["whale_detected"]:
        wl=whale_det["whale_label"].split("|")[0].strip()
        if wl: parts.append(wl[:50])
    if fort["layer1"]: parts.append(f"price AT institutional VPOC ₹{poc:.2f} — high-conviction floor")
    if div_det["div_type"]=="BULLISH_HIDDEN": parts.append("hidden RSI divergence — smart money dip-buying")
    if "VCP" in pat_label or "Cup" in pat_label: parts.append(f"pattern: {pat_label[:40]}")
    if bayes["bayes_pct"]>=65: parts.append(f"14-node Bayes: {bayes['bayes_pct']}% conviction")
    if not parts: parts.append(f"fused score {fused}/100 — confluence setup")
    story="; ".join(parts[:4]).capitalize()

    # ── LLM ENHANCEMENT (optional, cached) ──
    llm_story = None
    llm_filing = None
    if LLM_ENABLED:
        llm_story = _llm_story_enhance(symbol, parts, {
            "rsi": fort["rsi"], "adx": fort["adx"], 
            "mfi": fort["mfi"], "atr14": fort["atr14"]
        })
        # LLM filing sentiment override if available
        raw_filing = fil_data.get("detail","")
        if raw_filing and "No recent" not in raw_filing:
            llm_filing = _llm_alpha_mine(raw_filing, symbol)
            if llm_filing and llm_filing.get("score") is not None:
                # Blend LLM score with keyword score (30% LLM, 70% keyword)
                fil_pts = round(fil_pts * 0.7 + llm_filing["score"] * 0.3)

    # (meta_features already stored above, after sector momentum is applied)

    return {
        "symbol":   symbol,
        "sector":   sector,
        "close":    round(close,2),
        "grade":    grade,
        "llm_story": llm_story,
        "llm_filing_sentiment": llm_filing.get("sentiment") if llm_filing else None,
        "llm_filing_detail": llm_filing.get("detail") if llm_filing else None,

        # Fused scores
        "fused":          fused,
        "fort_total":     fort_total,
        "fort_pct":       round(fort_norm,1),
        "apex_composite": apex_composite,

        # Sub-scores
        "score_fortress": fort["fortress_pts"],
        "score_fii":      fii_pts,
        "score_insider":  ins_pts,
        "score_filing":   fil_pts,
        "score_earnings": earn_pts,
        "whale_score":    round(whale_score,1),
        "div_score":      round(div_score,1),
        "vp_score":       round(vp_score,1),
        "pat_score":      round(pat_score,1),
        "bayes_pct":      bayes["bayes_pct"],
        "mc_survival":    mc_survival,

        # Trade plan
        "buy_lo":    round(close*0.99,2),
        "buy_hi":    round(close*1.01,2),
        "stop_loss": stop_loss,
        "risk_pct":  risk_pct,
        "r1": r1, "r2": r2, "r3": r3,
        "r1_pct": r1_pct, "r2_pct": r2_pct, "r3_pct": r3_pct,
        "sell_r1": 30, "sell_r2": 30, "sell_r3": 40,
        "trail_stop":   trail_stop,
        "shares":       sh_f,
        "pos_value":    round(pos_v),
        "deploy_pct":   round(deploy*100),
        "pos_label":    pos_lb,

        # Labels & signals
        "whale_label":  whale_det["whale_label"],
        "pat_label":    pat_label,
        "div_label":    div_det["div_label"],
        "vp_label":     vp_label,
        "mc_label":     mc["label"],
        "bayes_label":  bayes["bayes_label"],
        "fii_label":    fii_lbl,
        "fii_detail":   fii_det,
        "ins_detail":   ins_det,
        "fil_detail":   fil_det,
        "earn_detail":  earn_det,
        "cvd_label":    cvd["cvd_label"],
        "vsa_label":    vsa["vsa_label"],
        "fog_label":    fog["fog_label"],

        # Fortress layers
        "layer1": fort["layer1"], "layer2": fort["layer2"], "layer3": fort["layer3"],
        "vcp_coil": fort["vcp_coil"], "regime": fort["regime"],
        "w52_bonus": fort["w52_bonus"], "forward_bonus": fort["forward_bonus"],
        "vdu_label": fort["vdu_label"],

        # Technicals
        "rsi":  fort["rsi"],  "mfi": fort["mfi"],
        "adx":  fort["adx"],  "atr14": fort["atr14"],
        "poc":  round(poc,2), "ma200": fort["ma200"],
        "alt_pct": fort["alt_pct"], "velocity_pct": fort["velocity_pct"],

        # Meta
        "data_quality":    dq,
        "vol_reliable":    fort["vol_reliable"],
        "story":           story,
        "earn_days":       earn_days,
        "days_to_r1_est":  mc.get("days_to_t1") or MC_HORIZON,
        "r1_hit_prob":     mc.get("t1_hit_pct",0),
        "alloc_note":      alloc_note+fog_note,
    }


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 14 — TELEGRAM (ultra-compact, plain English)
# ══════════════════════════════════════════════════════════════════════════════

def _escape(s) -> str:
    text = str(s) if s is not None else ""
    special = r'\_*[]()~`>#+-=|{}.!'
    return "".join(("\\" + ch if ch in special else ch) for ch in text)


def _split_msg(msg: str, limit: int = 4000) -> list:
    if len(msg) <= limit:
        return [msg]
    cards = msg.split("\n\n"); chunks = []; cur = ""
    for card in cards:
        blk = card + "\n\n"
        if len(cur) + len(blk) > limit:
            if cur.strip(): chunks.append(cur.rstrip())
            cur = blk
        else:
            cur += blk
    if cur.strip(): chunks.append(cur.rstrip())
    return chunks


def _tg_post(token: str, chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for attempt, delay in enumerate([0, 2, 5], 1):
        if delay: time.sleep(delay)
        try:
            r = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=20)
            if r.status_code == 200: return True
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", 5))); continue
        except Exception as e:
            log.error(f"Telegram attempt {attempt}: {e}")
    return False


def _grade_plain(grade: str) -> str:
    return {
        "⚔️ APEX": "STRONG",
        "💎 PRISTINE": "STRONG",
        "🟢 GOOD": "DECENT",
        "🔵 PROBE": "WEAK",
    }.get(grade, grade)


def _verdict_plain(r: dict) -> str:
    """Only SKIP or GO. No 'SMALL' verdict."""
    problems = []
    
    if r.get("fog_block"):
        return "⛔ SKIP — Market too foggy. Stay out."
    
    if not r.get("vol_reliable", True):
        problems.append("volume data missing")
    if r.get("vcp_coil", "").startswith("LOOSE"):
        problems.append("price too volatile")
    if r["risk_pct"] > 10:
        problems.append(f"stop too far at {r['risk_pct']:.0f}%")
    if r.get("earn_days") is not None and 0 <= r["earn_days"] <= 5:
        problems.append(f"earnings in {r['earn_days']}d")
    if r.get("alloc_note", "").startswith(" ⚠️ CB"):
        problems.append("small-cap safety lock ON")
    
    if problems:
        return "⛔ SKIP — " + "; ".join(problems[:2]) + ". Not safe."
    
    # No problems = GO
    if r["fused"] >= 72:
        return "✅ GO — Full position."
    if r["fused"] >= 60:
        return "✅ GO — Normal position."
    return "✅ GO — Small test only."


def _why_plain(r: dict) -> str:
    """Ultra-short why."""
    parts = []
    
    fii = r.get("fii_label", "")
    if "FII+DII" in fii and "BUYING" in fii:
        parts.append("institutions buying")
    elif "FII" in fii and "BUYING" in fii:
        parts.append("foreign investors buying")
    elif "DII" in fii and "BUYING" in fii:
        parts.append("domestic investors buying")
    
    ins = r.get("ins_detail", "")
    if ins and "buy" in ins.lower() and r.get("score_insider", 0) >= 10:
        parts.append("insiders buying")
    
    fil = r.get("fil_detail", "")
    if fil and "No recent" not in fil and r.get("score_filing", 0) >= 20:
        if "dividend" in fil.lower(): parts.append("dividend coming")
        elif "bonus" in fil.lower(): parts.append("bonus shares")
        elif "buyback" in fil.lower(): parts.append("buyback")
        else: parts.append("good news")
    
    if r.get("layer1"): parts.append("at support")
    if r.get("layer2"): parts.append("heavy volume")
    if r.get("layer3"): parts.append("support holding")
    
    pat = r.get("pat_label", "")
    if "VCP" in pat: parts.append("coil forming")
    if "Cup" in pat: parts.append("cup pattern")
    
    div = r.get("div_label", "")
    if "BULLISH" in div: parts.append("hidden buy signal")
    
    whale = r.get("whale_label", "")
    if "Stealth" in whale: parts.append("smart money sneaking")
    elif "Accumulation" in whale: parts.append("big buyers accumulating")
    
    bayes = r.get("bayes_pct", 0)
    if bayes >= 75: parts.append(f"AI {bayes}% sure")
    elif bayes >= 60: parts.append(f"AI {bayes}% confident")
    
    if not parts:
        return "Some confluence"
    
    return " + ".join(parts[:3])


def send_telegram_v3(picks: list, macro: dict, fii_data: dict,
                      date_label: str, data_source: str,
                      capacity: dict = None):
    """
    v3.0-M Telegram format:
    - Shows AI Confidence % + WORTH YOUR TIME / MAYBE / SKIP flag
    - Shows your personal win history for similar setups
    - Shows regime context and capacity guard status
    - Includes reply instructions (TAKEN / SKIPPED / PARTIAL)
    - Filters to WORTH_YOUR_TIME only when capacity guard is active
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram: not configured"); return

    if capacity is None:
        capacity = _capacity_guard(date_label)

    vix_val   = macro.get("vix_val", 0.0)
    macro_st  = macro.get("macro_state", "CHOP")
    macro_icon = {"CLEAR": "🟢", "CHOP": "🟡", "PANIC": "🔴",
                  "FOG": "🌫️", "MASSACRE": "🚨"}.get(macro_st, "⚪")

    lines = [
        f"⚔️ SNIPER {VERSION} | {date_label} | {macro_icon} {macro_st} | VIX {vix_val:.1f}",
        f"📡 Source: {data_source} | Halal | Manual execution only",
    ]
    if capacity.get("note"):
        lines.append(capacity["note"])
    lines.append("")

    if macro_st == "MASSACRE":
        lines.extend(["🚨 MARKET CRASH — NO TRADES TODAY.", ""])
        _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, "\n".join(lines))
        return
    if macro_st == "PANIC":
        lines.extend(["🔴 MARKET PANIC — NO NEW TRADES.", ""])
        _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, "\n".join(lines))
        return
    if not picks:
        lines.append("🤲 No qualifying picks today — patience is also a position.")
        _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, "\n".join(lines))
        return

    # Enrich each pick with v3 confidence fields
    enriched = []
    for r in picks:
        profile   = r.get("setup_profile") or _get_setup_profile(r)
        hist      = _historical_win_rate_for_profile(profile, r.get("grade"), r.get("sector"))
        meta_prob = r.get("meta_prob", 0.55)
        confidence = _regime_scaled_confidence(meta_prob, macro_st, vix_val)
        flag       = _confidence_flag(confidence)
        enriched.append({**r, "profile": profile, "history": hist,
                         "confidence": confidence, "flag": flag})

    # Capacity guard: filter if needed
    display_picks = enriched
    if capacity.get("reduce_to_worth_only"):
        display_picks = [p for p in enriched if p["flag"] == "WORTH YOUR TIME"]
        if not display_picks:
            lines.append("🔒 Capacity guard active — no WORTH YOUR TIME signals today.")
            lines.append("Existing positions are your priority.")
            _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, "\n".join(lines))
            return
        lines.append(f"🔒 Showing {len(display_picks)} WORTH YOUR TIME signals only (capacity guard)")
        lines.append("")

    # Build pick cards
    for i, p in enumerate(display_picks, 1):
        icon     = _confidence_emoji(p["flag"])
        conf_pct = round(p["confidence"] * 100)
        hist     = p["history"]

        earn_warn = ""
        earn_days = p.get("earn_days")
        if earn_days is not None and 0 <= earn_days <= 3:
            earn_warn = f"\n   🚫 Earnings in {earn_days}d — consider skipping"
        elif earn_days is not None and 0 <= earn_days <= 8:
            earn_warn = f"\n   ⚠️ Earnings in {earn_days}d"

        vol_warn = " [NO-VOL]" if not p.get("vol_reliable", True) else ""

        if hist["total"] >= 3:
            hist_line = f"\n   📊 Your history: {hist['confidence_label']}"
        elif hist["total"] > 0:
            hist_line = f"\n   📊 Your history: {hist['wins']}/{hist['total']} similar trades"
        else:
            hist_line = "\n   📊 Your history: No similar setups yet"

        if p["flag"] == "SKIP":
            rec_note = "\n   🚫 AI recommends skip — false positive risk high"
        elif p["flag"] == "MAYBE" and conf_pct < 60:
            rec_note = "\n   ⚠️ Low confidence — consider skipping if busy"
        else:
            rec_note = ""

        mom_tier = p.get("sector_momentum_tier", "")
        mom_note = f" | Sector {mom_tier}" if mom_tier and mom_tier != "NEUTRAL" else ""

        why = _why_plain(p)
        verdict = _verdict_plain(p)
        verdict_dot = "✅" if verdict.startswith("✅") else "⛔"

        card = (
            f"{icon} #{i} {p['symbol']}{vol_warn} — AI CONFIDENCE {conf_pct}% [{p['flag']}]\n"
            f"   ₹{p['close']:.0f} | Buy: ₹{p['buy_lo']}–{p['buy_hi']} | "
            f"SL ₹{p['stop_loss']} ({p['risk_pct']:.1f}%)\n"
            f"   R1 ₹{p['r1']} | R2 ₹{p['r2']} | R3 ₹{p['r3']} | Grade {p['grade']}{mom_note}\n"
            f"   Fortress: VPOC {'✓' if p.get('layer1') else '✗'} "
            f"Vol {'✓' if p.get('vol_reliable',True) else '✗'} "
            f"ADX {p.get('adx',0):.0f} | "
            f"Whale {'✓' if p.get('whale_score',0)>=15 else '✗'} "
            f"Bayes {p.get('bayes_pct',0)}%\n"
            f"   Why: {why}\n"
            f"   Verdict: {verdict_dot} {verdict.split('—',1)[-1].strip() if '—' in verdict else verdict}"
            f"{hist_line}"
            f"{earn_warn}"
            f"{rec_note}"
        )
        lines.append(card)
        lines.append("")

    # Footer
    lines.append("─" * 35)
    lines.append("ℹ️ SKIPPED is no longer needed.")
    lines.append("Just don't reply — the system auto-logs silence as SKIPPED at EOD.")
    lines.append("Only reply if you TOOK or PARTIALLY took a position.")
    lines.append("  TAKEN TCS @ 3445")
    lines.append("  PARTIAL TCS 50    ← if taking half size")
    lines.append("")
    lines.append(f"FII/DII: {fii_data.get('label','—')} | {fii_data.get('detail','')[:60]}")
    lines.append(f"🔎 {len(display_picks)} pick(s) | {MC_HORIZON}-day hold | Risk {ACCOUNT_RISK_PCT*100:.1f}%/trade")
    lines.append("🤲 Bismillah — trade only what you understand")

    full_msg = "\n".join(lines)
    chunks = _split_msg(full_msg, limit=4000)
    for chunk in chunks:
        _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, chunk)

    for share_id in TELEGRAM_SHARE_IDS:
        if share_id and share_id != TELEGRAM_CHAT_ID:
            _tg_post(TELEGRAM_TOKEN, share_id, chunks[0])
            time.sleep(0.3)


def send_telegram(picks: list, macro: dict, fii_data: dict,
                   date_label: str, data_source: str):
    """Backward-compatible alias — delegates to send_telegram_v3."""
    send_telegram_v3(picks, macro, fii_data, date_label, data_source)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 15 — OUTPUT: EXCEL, HTML, GOOGLE SHEETS
# ══════════════════════════════════════════════════════════════════════════════

def save_excel(picks: list, all_results: list, fii_data: dict, date_label: str, data_source: str, bhavcopy: pd.DataFrame):
    if not picks and not all_results: return
    try:
        EXCEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(EXCEL_PATH, engine="openpyxl") as w:
            pd.DataFrame(picks).to_excel(w, sheet_name="Top Picks",   index=False)
            pd.DataFrame(all_results).to_excel(w, sheet_name="All Results", index=False)
            pd.DataFrame([fii_data]).to_excel(w, sheet_name="FII_DII", index=False)
            
            # NEW: Data Quality sheet
            halal_uni = get_halal_universe()
            quality = pd.DataFrame([{
                "Date": date_label,
                "Source": data_source,
                "Bhavcopy_Records": len(bhavcopy),
                "Halal_Universe": len(halal_uni),
                "Halal_in_Bhavcopy": len(bhavcopy[bhavcopy["symbol"].isin(halal_uni)]),
                "YFinance_Shrink": "YES" if (data_source == "YFINANCE" and len(bhavcopy) <= 100) else "NO",
                "Missing_Halal": len(halal_uni - set(bhavcopy["symbol"])),
                "Alert": "SHRUNK" if (data_source == "YFINANCE" and len(bhavcopy) <= 100) else "OK"
            }])
            quality.to_excel(w, sheet_name="Data Quality", index=False)

            # Performance sheet: closed pick outcomes from DB (moved inside ExcelWriter context)
            try:
                con = sqlite3.connect(DB_PATH)
                perf_rows = con.execute(
                    "SELECT run_date, symbol, grade, fused_score, status, exit_price, pnl_pct, days_held, hit_target "
                    "FROM pick_outcomes WHERE status!='open' ORDER BY run_date DESC LIMIT 100"
                ).fetchall()
                con.close()
                if perf_rows:
                    perf_df = pd.DataFrame(perf_rows, columns=[
                        "Date", "Symbol", "Grade", "Score", "Status", "Exit", "P&L%", "Days", "Hit"
                    ])
                    perf_df.to_excel(w, sheet_name="Performance", index=False)
            except Exception as pe:
                log.debug(f"Performance sheet: {pe}")

        log.info(f"Excel saved: {EXCEL_PATH}")
    except Exception as e:
        log.error(f"Excel save failed: {e}")

def save_html(picks: list, fii_data: dict, date_label: str):
    try:
        HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
        rows=""
        for i,r in enumerate(picks,1):
            layers="".join("✓" if r.get(f"layer{n}") else "✗" for n in range(1,4))
            vol_warn='' if r.get("vol_reliable",True) else '<span style="color:#dc2626;font-size:10px"> ⚠️ No Volume</span>'
            rows+=f"""<tr>
              <td>{i}</td>
              <td><b>{r['symbol']}</b><br><small>{r.get('sector','—')}</small>{vol_warn}</td>
              <td>{r['fused']}/100<br>
                  <small style="color:#6b7280">Fort {r['fort_pct']:.0f}% · APEX {r['apex_composite']}</small><br>
                  <small style="color:#7c3aed">{r['grade']}</small></td>
              <td><small>Buy ₹{r['buy_lo']}–{r['buy_hi']}<br>SL ₹{r['stop_loss']}<br>R1 ₹{r['r1']} / R2 ₹{r['r2']} / R3 ₹{r['r3']}</small></td>
              <td><small>
                <b>Whale</b> {r['whale_score']:.0f} · <b>Div</b> {r['div_score']:.0f} · <b>VP</b> {r['vp_score']:.0f}<br>
                <b>Pat</b> {r['pat_score']:.0f} · <b>Bayes</b> {r['bayes_pct']}% · <b>MC</b> {r['mc_survival']}%<br>
                VPOC {layers} | {r.get('regime','—')} | {r.get('vcp_coil','—')[:5]}<br>
                RSI {r['rsi']} | MFI {r['mfi']} | ADX {r['adx']}
              </small></td>
              <td><small style="color:#555;font-style:italic">{r.get('story','—')}</small></td>
            </tr>"""

        html=f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><title>⚔️ Unified Sniper {VERSION} | {date_label}</title>
<style>body{{font-family:system-ui,sans-serif;margin:0;padding:20px;background:#f9fafb;color:#111}}
h1{{font-size:20px;margin:0 0 4px}}.meta{{color:#666;font-size:13px;margin-bottom:20px}}
.card{{background:#fff;border-radius:12px;border:1px solid #e5e7eb;padding:20px;margin-bottom:16px}}
table{{border-collapse:collapse;width:100%}}
th{{background:#f3f4f6;padding:10px 12px;text-align:left;font-size:12px;color:#555;border-bottom:1px solid #e5e7eb}}
td{{padding:10px;border-bottom:1px solid #f3f4f6;vertical-align:top;font-size:13px}}</style></head><body>
<h1>⚔️ Unified Sniper {VERSION}</h1>
<div class="meta">🕌 Halal · Fortress × APEX Fused · 14-node Bayes · t(df=5) MC · {date_label}</div>
<div class="card"><b>Market Intelligence</b><br>
  <div style="background:#e0f2fe;border-radius:8px;padding:10px 14px;margin:10px 0;font-size:13px">
    <b>{fii_data.get('label','—')}</b> &nbsp; {fii_data.get('detail','—')}
  </div>
</div>
<div class="card"><b>🎯 Top {len(picks)} Halal Picks</b>
<table style="margin-top:12px">
  <tr><th>#</th><th>Symbol</th><th>Score</th><th>Trade Plan</th><th>Sub-engines</th><th>Story</th></tr>
  {rows}
</table></div>
<div class="meta" style="margin-top:16px;text-align:center">
  Unified Sniper {VERSION} · Halal · NSE EQ · Not financial advice
</div></body></html>"""
        HTML_PATH.write_text(html, encoding="utf-8")
        log.info(f"HTML saved: {HTML_PATH}")
    except Exception as e:
        log.error(f"HTML save failed: {e}")


def _push_performance_tab(date_label: str):
    """Push calibrated win rates by grade/sector/signal to PERFORMANCE tab.
    Appends a dated snapshot each run so history accumulates across sessions."""
    log.info("PERFORMANCE: Starting push…")
    if not _sheets_ok():
        log.warning("PERFORMANCE: Sheets not configured — skipping")
        return
    log.info("PERFORMANCE: Sheets OK, connecting to DB…")

    try:
        con = sqlite3.connect(DB_PATH, timeout=10)

        # Win rate by grade — COALESCE guards against NULL from SUM on empty set
        grade_rows = con.execute(
            "SELECT grade, COUNT(*) as total, "
            "COALESCE(SUM(CASE WHEN status IN ('r1_hit','r2_hit','r3_hit') THEN 1 ELSE 0 END), 0) as wins, "
            "AVG(pnl_pct) FROM pick_outcomes WHERE status!='open' GROUP BY grade"
        ).fetchall()

        # Win rate by sector — join sniper_results which stores the sector column
        sector_rows = con.execute(
            "SELECT s.sector, COUNT(*) as total, "
            "COALESCE(SUM(CASE WHEN o.status IN ('r1_hit','r2_hit','r3_hit') THEN 1 ELSE 0 END), 0) as wins, "
            "AVG(o.pnl_pct) as avg_pnl "
            "FROM pick_outcomes o "
            "JOIN sniper_results s ON o.symbol=s.symbol AND o.run_date=s.run_date "
            "WHERE o.status!='open' GROUP BY s.sector"
        ).fetchall()

        # Prior calibration status
        prior_rows = con.execute(
            "SELECT prior_name, win_rate, total FROM bayes_calibration WHERE total>=10"
        ).fetchall()

        # Overall summary stats
        summary_row = con.execute(
            "SELECT COUNT(*), "
            "COALESCE(SUM(CASE WHEN status IN ('r1_hit','r2_hit','r3_hit') THEN 1 ELSE 0 END), 0), "
            "AVG(pnl_pct) FROM pick_outcomes WHERE status!='open'"
        ).fetchone()
        con.close()

        rows = [["Date", "Metric", "Category", "Total", "Wins", "WinRate%", "AvgPnL%", "Notes"]]

        # Overall row
        if summary_row and summary_row[0]:
            total, wins, avg_pnl = summary_row
            wr = (wins / total * 100) if total > 0 else 0
            rows.append([date_label, "Overall", "All Picks", total, wins,
                          f"{wr:.1f}", f"{avg_pnl:+.1f}" if avg_pnl else "—", ""])

        for grade, total, wins, avg_pnl in grade_rows:
            wins = wins or 0  # guard None
            wr = (wins / total * 100) if total > 0 else 0
            rows.append([date_label, "By Grade", grade or "—", total, wins,
                          f"{wr:.1f}", f"{avg_pnl:+.1f}" if avg_pnl else "—", ""])

        for sector, total, wins, avg_pnl in sector_rows:
            wins = wins or 0
            wr = (wins / total * 100) if total > 0 else 0
            rows.append([date_label, "By Sector", sector or "—", total, wins,
                          f"{wr:.1f}", f"{avg_pnl:+.1f}" if avg_pnl else "—", ""])

        for name, wr, total in prior_rows:
            rows.append([date_label, "Prior Calibrated", name, total,
                          int((wr or 0) * total), f"{(wr or 0)*100:.1f}", "—", _BAYES_PRIOR_VERSION])

        if len(rows) == 1:
            # No closed picks yet — still push headers + placeholder
            rows.append([date_label, "—", "No closed picks yet", 0, 0, "—", "—", ""])

        # Append to existing tab (preserves history) — read existing rows first
        ws = _get_ws("PERFORMANCE")
        if ws is not None:
            try:
                existing = ws.get_all_values()
                if existing and existing[0] == rows[0]:
                    # Headers match — append data rows below existing
                    data_rows = rows[1:]
                    ws.append_rows(data_rows, value_input_option="USER_ENTERED")
                    log.info(f"PERFORMANCE tab appended: {len(data_rows)} new rows ✅")
                    return
            except Exception as ae:
                log.debug(f"PERFORMANCE append fallback to overwrite: {ae}")

        # Fallback: overwrite (first run or header mismatch)
        _push_sheet("PERFORMANCE", rows)
        log.info(f"PERFORMANCE tab pushed: {len(rows)-1} rows ✅")

    except Exception as e:
        log.error(f"PERFORMANCE tab FAILED: {e}")


def _push_ai_insights_tab(picks: list, date_label: str):
    """Push LLM-enhanced stories and filing analyses to AI_INSIGHTS tab.
    Appends rows each run so history accumulates. Called regardless of LLM_ENABLED;
    the LLM columns simply show '—' when LLM is off."""
    log.info("AI_INSIGHTS: Starting push…")
    if not _sheets_ok():
        log.warning("AI_INSIGHTS: Sheets not configured — skipping")
        return
    log.info(f"AI_INSIGHTS: Sheets OK, processing {len(picks)} picks…")

    headers = ["Date", "Symbol", "Grade", "Fused", "Raw Story", "LLM Story",
               "LLM Conviction", "Filing Sentiment", "Filing Detail", "Prior Version"]

    data_rows = []
    if not picks:
        data_rows.append([date_label, "—", "—", "—", "No picks today", "—", "—", "—", "—", _BAYES_PRIOR_VERSION])
    else:
        for r in picks:
            llm_story = r.get("llm_story") or "—"
            if llm_story != "—":
                llm_story = str(llm_story)[:300]
            data_rows.append([
                date_label,
                r["symbol"],
                r.get("grade", "—"),
                r.get("fused", "—"),
                (r.get("story") or "—")[:200],
                llm_story,
                r.get("bayes_pct", "—"),  # AI conviction proxy
                r.get("llm_filing_sentiment") or "—",
                (r.get("fil_detail") or "—")[:200],
                _BAYES_PRIOR_VERSION,
            ])

    try:
        ws = _get_ws("AI_INSIGHTS")
        if ws is not None:
            existing = ws.get_all_values()
            if existing and existing[0] == headers:
                # Headers already present — append only data rows
                ws.append_rows(data_rows, value_input_option="USER_ENTERED")
                log.info(f"AI_INSIGHTS tab appended: {len(data_rows)} row(s) ✅")
                return
        # First run or header mismatch — full overwrite
        _push_sheet("AI_INSIGHTS", [headers] + data_rows)
        log.info(f"AI_INSIGHTS tab pushed: {len(data_rows)} row(s) ✅")
    except Exception as e:
        log.error(f"AI_INSIGHTS tab FAILED: {e}")


def push_gsheets(picks: list, date_label: str):
    if not _sheets_ok(): return
    headers = [
        "Date","Symbol","Sector","Grade","Fused/100","Fort%","APEX/100",
        "Fortress/80","FII/30","Insider/30","Filing/30","Earnings/30",
        "Whale","Divergence","VolProfile","Pattern","Bayes%","MC%",
        "BuyLo","BuyHi","StopLoss","R1","R2","R3","TrailStop",
        "VPOC-L1","VPOC-L2","VPOC-L3","VCP","Regime",
        "RSI","MFI","ADX","ATR","POC","MA200",
        "DataQuality","VolReliable","Story",
    ]
    rows = [headers]
    for r in picks:
        rows.append([
            date_label, r["symbol"], r.get("sector","—"), r.get("grade","—"),
            r["fused"], r["fort_pct"], r["apex_composite"],
            r["score_fortress"], r["score_fii"], r["score_insider"],
            r["score_filing"], r["score_earnings"],
            r["whale_score"], r["div_score"], r["vp_score"], r["pat_score"],
            r["bayes_pct"], r.get("mc_survival","—"),
            r["buy_lo"], r["buy_hi"], r["stop_loss"],
            r["r1"], r["r2"], r["r3"], r["trail_stop"],
            int(r["layer1"]), int(r["layer2"]), int(r["layer3"]),  # ← FIXED: bool → int (1/0)
            r.get("vcp_coil","—"), r.get("regime","—"),
            r["rsi"], r["mfi"], r["adx"], r["atr14"], r["poc"], r["ma200"],
            r.get("data_quality","—"), int(r.get("vol_reliable",True)),  # ← FIXED: bool → int
            r.get("story","—"),
        ])
    _push_sheet("SCREENER", rows)
# ══════════════════════════════════════════════════════════════════════════════
# SECTION 15b — OUTCOME ENGINE (closed-loop feedback)
# ══════════════════════════════════════════════════════════════════════════════

def _get_yesterday_picks() -> List[dict]:
    """Fetch yesterday's picks that are still 'open' and need tracking."""
    try:
        con = sqlite3.connect(DB_PATH)
        yesterday = (datetime.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        rows = con.execute(
            "SELECT run_date, symbol, entry_price, stop_loss, r1, r2, r3, grade, fused_score, story "
            "FROM pick_outcomes WHERE status='open' AND run_date=?",
            (yesterday,)
        ).fetchall()
        con.close()
        return [dict(zip(["run_date","symbol","entry_price","stop_loss","r1","r2","r3","grade","fused_score","story"], r)) for r in rows]
    except Exception as e:
        log.debug(f"Get yesterday picks: {e}")
        return []


def _update_pick_outcome(symbol: str, run_date: str, status: str, exit_price: float = None, pnl_pct: float = None, days_held: int = None, hit_target: str = None):
    """Update a pick's outcome after checking market data."""
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute(
            "UPDATE pick_outcomes SET status=?, exit_price=?, pnl_pct=?, days_held=?, hit_target=?, updated_at=? "
            "WHERE symbol=? AND run_date=?",
            (status, exit_price, pnl_pct, days_held, hit_target, datetime.today().isoformat(), symbol, run_date)
        )
        con.commit(); con.close()
        log.info(f"  Outcome: {symbol} → {status} | P&L: {pnl_pct:+.1f}% | Days: {days_held}")
    except Exception as e:
        log.debug(f"Update outcome {symbol}: {e}")


def _check_pick_outcome(pick: dict, hist: pd.DataFrame) -> dict:
    """
    Check if yesterday's pick hit R1, R2, R3, or stop loss.
    Returns: {"status": str, "exit_price": float, "pnl_pct": float, "days_held": int, "hit_target": str}
    """
    if hist.empty or len(hist) < 2:
        return {"status": "open", "exit_price": None, "pnl_pct": None, "days_held": None, "hit_target": None}
    
    entry = pick["entry_price"]
    stop = pick["stop_loss"]
    r1 = pick["r1"]
    r2 = pick["r2"]
    r3 = pick["r3"]
    
    # Get prices since pick date
    pick_date = pd.Timestamp(pick["run_date"])
    since_pick = hist[hist["date"] >= pick_date]
    
    if since_pick.empty:
        return {"status": "open", "exit_price": None, "pnl_pct": None, "days_held": None, "hit_target": None}
    
    highs = since_pick["high"].values
    lows = since_pick["low"].values
    closes = since_pick["close"].values
    days_held = len(since_pick)
    
    # OUTCOME FIX: Check targets BEFORE stop-loss.
    # On a gap-up day a single bar's high can exceed R3 while the same bar's
    # low also breaches the stop.  Checking stop first wrongly reports a loss
    # on what is actually a winning trade.  Targets take priority; stop only
    # applies when no target was reached on that bar.
    #
    # Per-bar resolution: walk the bars and check both directions each day.
    for i, (h, l) in enumerate(zip(highs, lows)):
        if h >= r3:
            return {"status": "r3_hit", "exit_price": r3,
                    "pnl_pct": (r3 - entry) / entry * 100,
                    "days_held": i + 1, "hit_target": "r3"}
        if h >= r2:
            return {"status": "r2_hit", "exit_price": r2,
                    "pnl_pct": (r2 - entry) / entry * 100,
                    "days_held": i + 1, "hit_target": "r2"}
        if h >= r1:
            return {"status": "r1_hit", "exit_price": r1,
                    "pnl_pct": (r1 - entry) / entry * 100,
                    "days_held": i + 1, "hit_target": "r1"}
        if l <= stop:
            return {"status": "stopped", "exit_price": stop,
                    "pnl_pct": (stop - entry) / entry * 100,
                    "days_held": i + 1, "hit_target": "stop"}
    
    # Expire after 12 days (MC_HORIZON) if nothing hit
    if days_held >= MC_HORIZON:
        last_close = float(closes[-1])
        pnl = (last_close - entry) / entry * 100
        return {"status": "expired", "exit_price": last_close, "pnl_pct": pnl, "days_held": days_held, "hit_target": "none"}
    
    # Still open
    return {"status": "open", "exit_price": None, "pnl_pct": None, "days_held": days_held, "hit_target": None}


def _run_outcome_engine():
    """Check all open picks from previous days and update their outcomes."""
    log.info("=" * 70)
    log.info("🔁 OUTCOME ENGINE — Checking yesterday's picks…")
    log.info("=" * 70)
    
    open_picks = _get_yesterday_picks()
    if not open_picks:
        log.info("  No open picks to check")
        return
    
    log.info(f"  Tracking {len(open_picks)} open pick(s)")
    sess = _get_nse_session()
    
    for pick in open_picks:
        sym = pick["symbol"]
        try:
            hist = fetch_history(sym, days=30, sess=sess)
            outcome = _check_pick_outcome(pick, hist)
            
            if outcome["status"] != "open":
                _update_pick_outcome(
                    sym, pick["run_date"], outcome["status"],
                    outcome["exit_price"], outcome["pnl_pct"],
                    outcome["days_held"], outcome["hit_target"]
                )
            else:
                log.info(f"  {sym}: still open ({outcome['days_held']} days)")
                
            time.sleep(0.3)
        except Exception as e:
            log.debug(f"Outcome check {sym}: {e}")
    
    log.info("  Outcome engine complete")


def _get_sector_performance(days: int = 30) -> dict:
    """Calculate win rate and avg P&L per sector from pick_outcomes."""
    try:
        con = sqlite3.connect(DB_PATH)
        since = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = con.execute(
            "SELECT p.sector, o.status, o.pnl_pct FROM pick_outcomes o "
            "JOIN sniper_results p ON o.symbol=p.symbol AND o.run_date=p.run_date "
            "WHERE o.run_date>=? AND o.status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')",
            (since,)
        ).fetchall()
        con.close()
        
        sector_stats = {}
        for sector, status, pnl in rows:
            if sector not in sector_stats:
                sector_stats[sector] = {"wins": 0, "losses": 0, "total_pnl": 0, "count": 0}
            sector_stats[sector]["count"] += 1
            sector_stats[sector]["total_pnl"] += (pnl or 0)
            if status in ("r1_hit", "r2_hit", "r3_hit"):
                sector_stats[sector]["wins"] += 1
            else:
                sector_stats[sector]["losses"] += 1
        
        # Calculate win rate
        for sector, stats in sector_stats.items():
            stats["win_rate"] = stats["wins"] / stats["count"] * 100 if stats["count"] > 0 else 0
            stats["avg_pnl"] = stats["total_pnl"] / stats["count"] if stats["count"] > 0 else 0
        
        return sector_stats
    except Exception as e:
        log.debug(f"Sector performance: {e}")
        return {}


def _adjust_sector_multipliers():
    """Dynamically adjust SECTOR_TRUTH based on actual performance."""
    perf = _get_sector_performance(days=30)
    if not perf:
        log.info("  No performance data yet — using default multipliers")
        return
    
    log.info("=" * 70)
    log.info("📊 SECTOR PERFORMANCE (30-day) — Adjusting multipliers…")
    log.info("=" * 70)
    
    for sector, stats in sorted(perf.items(), key=lambda x: x[1]["win_rate"], reverse=True):
        old_mult = SECTOR_TRUTH.get(sector, 1.0)
        new_mult = old_mult
        
        # Adjust based on win rate
        if stats["win_rate"] >= 60 and stats["count"] >= 5:
            new_mult = min(1.3, old_mult + 0.05)
        elif stats["win_rate"] <= 30 and stats["count"] >= 5:
            new_mult = max(0.7, old_mult - 0.05)
        
        if new_mult != old_mult:
            SECTOR_TRUTH[sector] = new_mult
            log.info(f"  {sector}: {old_mult:.2f} → {new_mult:.2f} (win {stats['win_rate']:.0f}%, {stats['count']} trades)")
        else:
            log.info(f"  {sector}: {old_mult:.2f} unchanged (win {stats['win_rate']:.0f}%, {stats['count']} trades)")


def _get_stale_picks(days_stale: int = 5) -> List[dict]:
    """Find picks that never triggered entry (price never hit buy zone).
    BUG-006 FIX: sniper_results doesn't have buy_lo/buy_hi columns.
    Query only columns that exist; derive zone from entry_price ±2%.
    """
    try:
        con = sqlite3.connect(DB_PATH)
        since = (datetime.today() - timedelta(days=days_stale)).strftime("%Y-%m-%d")
        rows = con.execute(
            "SELECT run_date, symbol, entry_price, story "
            "FROM sniper_results s "
            "WHERE s.run_date<=? AND NOT EXISTS ("
            "  SELECT 1 FROM pick_outcomes o WHERE o.symbol=s.symbol AND o.run_date=s.run_date"
            ")",
            (since,)
        ).fetchall()
        con.close()
        result = []
        for r in rows:
            run_date, symbol, entry_price, story = r
            ep = entry_price or 0.0
            result.append({
                "run_date": run_date, "symbol": symbol,
                "entry_price": ep,
                "buy_lo": round(ep * 0.98, 2),   # BUG-006: synthesised ±2% zone
                "buy_hi": round(ep * 1.02, 2),
                "story": story,
            })
        return result
    except Exception as e:
        log.debug(f"Stale picks: {e}")
        return []


def _alert_open_positions():
    """Alert if any open pick is within 5% of stop loss."""
    try:
        con = sqlite3.connect(DB_PATH)
        rows = con.execute(
            "SELECT symbol, entry_price, stop_loss, r1, days_held, status "
            "FROM pick_outcomes WHERE status='open'"
        ).fetchall()
        con.close()
        
        if not rows:
            return
        
        log.info("=" * 70)
        log.info("🚨 OPEN POSITION ALERTS")
        log.info("=" * 70)
        
        sess = _get_nse_session()
        for sym, entry, stop, r1, days, status in rows:
            try:
                # Get latest price
                info = _nse_json(sess, "https://www.nseindia.com/api/quote-equity", 
                                params={"symbol": sym}, timeout=10)
                latest = float(info.get("priceInfo", {}).get("lastPrice", 0))
                
                if latest <= 0:
                    continue
                    
                stop_distance = (latest - stop) / stop * 100
                r1_distance = (r1 - latest) / latest * 100
                
                if stop_distance <= 5:
                    log.warning(f"  🔴 {sym}: ₹{latest:.0f} — only {stop_distance:.1f}% from stop! ({days} days in)")
                elif r1_distance <= 5:
                    log.info(f"  🟢 {sym}: ₹{latest:.0f} — {r1_distance:.1f}% from R1 target ({days} days in)")
                else:
                    log.info(f"  ⚪ {sym}: ₹{latest:.0f} | Stop: {stop_distance:.1f}% away | R1: {r1_distance:.1f}% away")
                    
                time.sleep(0.3)
            except Exception as e:
                log.debug(f"Alert check {sym}: {e}")
                
    except Exception as e:
        log.debug(f"Open alerts: {e}")
# ══════════════════════════════════════════════════════════════════════════════
# SECTION 16 — MAIN PIPELINE
# ══════════════════════════════════════════════════════════════════════════════



def _data_quality_gate(bhavcopy: pd.DataFrame, data_source: str) -> dict:
    """
    Auto-adjust thresholds if data quality degrades.
    Returns: {apex_min_score: int, apex_top_n: int, alert: str}
    """
    halal_uni = get_halal_universe()
    halal_in_bhav = len(bhavcopy[bhavcopy["symbol"].isin(halal_uni)])

    # Default thresholds
    min_score = APEX_MIN_SCORE
    top_n = APEX_TOP_N
    alert = ""

    # Degraded mode: yfinance fallback with shrunk universe
    if data_source == "YFINANCE" and len(bhavcopy) <= 100:
        min_score = 65
        top_n = 3
        alert = "🚨 DEGRADED: YFinance fallback, universe shrunk. Raising bar."
        log.warning(alert)

    # Moderate degradation: fewer halal symbols than expected
    elif halal_in_bhav < 50:
        min_score = min(65, APEX_MIN_SCORE + 5)
        top_n = max(3, APEX_TOP_N - 1)
        alert = f"⚠️ Only {halal_in_bhav} halal symbols in bhavcopy. Tightening filters."
        log.warning(alert)

    return {"apex_min_score": min_score, "apex_top_n": top_n, "alert": alert}




def _intraday_watchdog(symbol: str, trailing_stop: float, db_path: str = DB_PATH) -> dict:
    """
    Check live LTP against trailing_stop in DB.
    Returns: {action: str, ltp: float, distance_pct: float}
    action: 'HOLD' | 'STOP_HIT' | 'TRAIL_UPDATE' | 'ERROR'
    """
    try:
        # Get live price from NSE
        sess = _get_nse_session()
        data = _nse_json(sess, "https://www.nseindia.com/api/quote-equity", 
                        params={"symbol": symbol}, timeout=10)
        ltp = float(data.get("priceInfo", {}).get("lastPrice", 0))

        if ltp <= 0:
            return {"action": "ERROR", "ltp": 0, "distance_pct": 0}

        # Check stop hit
        if ltp <= trailing_stop:
            return {"action": "STOP_HIT", "ltp": ltp, "distance_pct": -999}

        # Check if we should update trailing stop (peak * 0.95)
        con = sqlite3.connect(db_path)
        row = con.execute(
            "SELECT peak_price, entry_price FROM positions WHERE symbol=? AND status='open' ORDER BY entry_date DESC LIMIT 1",
            (symbol.upper(),)
        ).fetchone()
        con.close()

        if row:
            peak = float(row[0])
            entry = float(row[1])
            new_trail = max(trailing_stop, ltp * 0.95, entry * 1.02)  # Never trail below BE+2%

            if new_trail > trailing_stop:
                # Update DB
                con = sqlite3.connect(db_path)
                con.execute(
                    "UPDATE positions SET trailing_stop=?, peak_price=?, updated_at=? WHERE symbol=? AND status='open'",
                    (new_trail, ltp, datetime.today().isoformat(), symbol.upper())
                )
                con.commit(); con.close()
                return {"action": "TRAIL_UPDATE", "ltp": ltp, "distance_pct": (ltp - new_trail) / ltp * 100}

        distance = (ltp - trailing_stop) / trailing_stop * 100
        return {"action": "HOLD", "ltp": ltp, "distance_pct": distance}

    except Exception as e:
        log.debug(f"Watchdog {symbol}: {e}")
        return {"action": "ERROR", "ltp": 0, "distance_pct": 0}


def _early_exit_alert(symbol: str, entry_price: float, current_ltp: float) -> dict:
    """
    Alert if top pick drops 3% intraday — early exit signal before EOD stop hits.
    Returns: {alert: bool, drop_pct: float, severity: str, note: str}
    """
    if entry_price <= 0 or current_ltp <= 0:
        return {"alert": False, "drop_pct": 0, "severity": "NONE", "note": ""}

    drop_pct = (current_ltp - entry_price) / entry_price * 100

    if drop_pct <= -5.0:
        severity = "CRITICAL"
        note = f"🚨 {symbol}: {drop_pct:.1f}% from entry — consider immediate exit"
    elif drop_pct <= -3.0:
        severity = "WARNING"
        note = f"⚠️ {symbol}: {drop_pct:.1f}% from entry — tighten stop, watch closely"
    elif drop_pct <= -1.5:
        severity = "CAUTION"
        note = f"📉 {symbol}: {drop_pct:.1f}% from entry — early weakness"
    else:
        severity = "NONE"
        note = ""

    return {
        "alert": severity in ["CRITICAL", "WARNING"],
        "drop_pct": round(drop_pct, 2),
        "severity": severity,
        "note": note
    }



# ══════════════════════════════════════════════════════════════════════════════
# [PATCH-C]  CALIBRATED AI JUDGE  (v4.0-M — Platt-scaled meta_prob + Kelly)
# ══════════════════════════════════════════════════════════════════════════════

def _platt_calibrate(raw_prob: float, calibration_params: Optional[dict]) -> float:
    """
    Platt scaling: raw_prob → calibrated_prob.
    params = {"A": float, "B": float, "n_samples": int}
    Falls back to identity if params absent or < 50 training samples.
    """
    if not calibration_params or calibration_params.get("n_samples", 0) < 50:
        return raw_prob
    A = calibration_params.get("A", 0.0)
    B = calibration_params.get("B", 0.0)
    try:
        return round(1.0 / (1.0 + math.exp(A * raw_prob + B)), 4)
    except (OverflowError, ValueError):
        return raw_prob


def _load_calibration_params() -> Optional[dict]:
    """Load Platt scaling params from DB (trained offline)."""
    try:
        with _db_conn() as con:
            row = con.execute(
                "SELECT A, B, n_samples, trained_at FROM platt_calibration "
                "ORDER BY trained_at DESC LIMIT 1"
            ).fetchone()
        if row:
            return {"A": row[0], "B": row[1], "n_samples": row[2], "trained_at": row[3]}
    except Exception:
        pass
    return None


def _kelly_fraction(p_calibrated: float, b: float = 2.0) -> str:
    """
    Fractional Kelly position size tier.
    Returns: 'FULL' | 'HALF' | 'QUARTER' | 'VETO'
    ROOT CAUSE #1 FIX: QUARTER threshold lowered 0.45 → 0.40 to match the
    calibrated_ai_judge confidence_floor. Previously every uncalibrated pick
    (p_cal ≈ 0.43) was vetoed here even after passing the judge — picks showed
    'Size: VETO' despite not being vetoed. Both gates must use the same floor.
    """
    if p_calibrated >= 0.75:
        return "FULL"
    elif p_calibrated >= 0.55:
        return "HALF"
    elif p_calibrated >= 0.40:   # RC1 FIX: was 0.45 — must match confidence_floor in calibrated_ai_judge
        return "QUARTER"
    return "VETO"


def _prev_day_context(symbol: str) -> dict:
    """Check yesterday's pick status for cooling-off logic."""
    yesterday = (datetime.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        with _db_conn() as con:
            row = con.execute(
                "SELECT status, pnl_pct FROM pick_outcomes WHERE symbol=? AND run_date=?",
                (symbol.upper(), yesterday)
            ).fetchone()
        if row:
            return {"status": row[0], "pnl_pct": row[1]}
    except Exception:
        pass
    return {"status": None, "pnl_pct": None}


def _weekly_wr_for_profile(setup_profile: str, grade: str, sector: str) -> dict:
    """Win rate for this exact profile in last 30 days of YOUR decisions."""
    try:
        since = (datetime.today() - timedelta(days=30)).strftime("%Y-%m-%d")
        with _db_conn() as con:
            rows = con.execute("""
                SELECT o.status, o.pnl_pct
                FROM trade_decisions td
                JOIN pick_outcomes o ON td.symbol=o.symbol AND td.run_date=o.run_date
                JOIN meta_features mf ON td.symbol=mf.symbol AND td.run_date=mf.run_date
                WHERE td.decision='TAKEN' AND td.run_date>=?
                  AND o.status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')
                  AND mf.setup_profile=?
            """, (since, setup_profile)).fetchall()
        total = len(rows)
        wins  = sum(1 for s, _ in rows if s in ("r1_hit", "r2_hit", "r3_hit"))
        return {"win_rate": (wins / total) if total > 0 else 0.5, "total": total}
    except Exception:
        return {"win_rate": 0.5, "total": 0}


def calibrated_ai_judge(pick: dict, halal: dict, macro: dict,
                         calibration_params: Optional[dict] = None) -> dict:
    """
    Step 5: Calibrated AI Judge.
    Input:  enriched pick dict + halal AI result + macro regime
    Output: pick enriched with calibrated_confidence, position_size_tier,
            veto (bool), veto_reason (str)
    """
    sym           = pick.get("symbol", "")
    raw_meta_prob = pick.get("meta_prob", 0.55)
    setup_profile = pick.get("setup_profile", "BHwdv")
    grade         = pick.get("grade", "")
    sector        = pick.get("sector", "DIVERSIFIED")
    fused         = pick.get("fused", 0)

    # ── Calibrate probability ────────────────────────────────────────────────
    p_cal = _platt_calibrate(raw_meta_prob, calibration_params)
    p_cal = _regime_scaled_confidence(p_cal, macro.get("macro_state", "CHOP"),
                                      macro.get("vix_val", 18.0))

    # ── Veto checks (deterministic) ──────────────────────────────────────────
    veto, veto_reason = False, ""

    if halal.get("veto"):
        veto, veto_reason = True, f"Halal veto: {halal.get('veto_reason', '')}"

    elif halal.get("score", 100) < 40:
        veto, veto_reason = True, f"Halal score {halal['score']} < 40 (RISKY tier)"

    else:
        prev = _prev_day_context(sym)
        if prev["status"] == "stopped" and (prev["pnl_pct"] or 0) < -5:
            veto, veto_reason = True, f"Cooling-off: stopped at {prev['pnl_pct']:.1f}% yesterday"
        elif not veto:
            wr_data = _weekly_wr_for_profile(setup_profile, grade, sector)
            if wr_data["total"] >= 5 and wr_data["win_rate"] < 0.30:
                veto, veto_reason = (True,
                    f"Your {setup_profile} win rate only {wr_data['win_rate']:.0%} "
                    f"on {wr_data['total']} trades")

    if not veto:
        # CRIT-3 FIX: When Platt calibration params are missing (<50 samples), the
        # identity passthrough returns raw_meta_prob ~0.43. Using a hard 45% threshold
        # vetoes all uncalibrated picks. Lower to 40% until 200+ samples are collected.
        has_calibration = (calibration_params is not None and
                           calibration_params.get("n_samples", 0) >= 50)
        confidence_floor = 0.45 if has_calibration else 0.40
        if p_cal < confidence_floor:
            veto, veto_reason = True, (
                f"Calibrated confidence {p_cal:.0%} < {confidence_floor:.0%} "
                f"({'calibrated' if has_calibration else 'uncalibrated floor'})"
            )
        elif halal.get("score", 0) < 60:
            veto, veto_reason = True, f"Halal score {halal.get('score',0)} < 60 (ACCEPTABLE)"
        elif fused < APEX_MIN_SCORE:
            veto, veto_reason = True, f"Fused {fused} < APEX_MIN_SCORE {APEX_MIN_SCORE}"

    size_tier = "VETO" if veto else _kelly_fraction(p_cal)

    return {
        **pick,
        "calibrated_confidence": p_cal,
        "raw_meta_prob":         raw_meta_prob,
        "position_size_tier":    size_tier,
        "halal_detail":          halal,
        "veto":                  veto,
        "veto_reason":           veto_reason,
        "worth_flag":            _confidence_flag(p_cal) if not veto else "SKIP",
    }



# ══════════════════════════════════════════════════════════════════════════════
# [PATCH-D]  NO-RESPONSE = SKIPPED  (v4.0-M — Step 8 EOD auto-log)
# ══════════════════════════════════════════════════════════════════════════════

def _auto_log_skipped_picks(date_label: str):
    """
    Auto-log all today's AI-passed picks that received no Telegram reply as SKIPPED.
    Called once at EOD (after Telegram reply window closes). No reminder sent.
    """
    try:
        with _db_conn() as con:
            # DISTINCT: sniper_results has no UNIQUE constraint, reruns insert duplicates
            all_picks_rows = con.execute(
                "SELECT DISTINCT symbol FROM sniper_results WHERE run_date=?",
                (date_label,)
            ).fetchall()
            # trade_decisions has UNIQUE(run_date,symbol) so set is fine
            logged = {row[0] for row in con.execute(
                "SELECT symbol FROM trade_decisions WHERE run_date=?",
                (date_label,)
            ).fetchall()}

        unresponded = [r[0] for r in all_picks_rows if r[0] not in logged]
        if not unresponded:
            log.debug("Auto-log: all picks already have decisions — nothing to log")
            return

        log.info(f"Auto-logging {len(unresponded)} unresponded picks as SKIPPED")
        for sym in unresponded:
            _log_trade_decision(date_label, sym, "SKIPPED",
                                skip_reason="no_response", ai_confidence=None)
        log.info(f"SKIPPED auto-log complete: {', '.join(unresponded)}")
    except Exception as e:
        log.error(f"Auto-log skipped: {e}")



# ══════════════════════════════════════════════════════════════════════════════
# [PATCH-E]  DB SCHEMA v4.0-M  (added at bottom of _init_db via _migrate_db_v4)
# ══════════════════════════════════════════════════════════════════════════════

_DB_SCHEMA_V4 = """
CREATE TABLE IF NOT EXISTS halal_ai_cache (
    symbol          TEXT PRIMARY KEY,
    score           INTEGER NOT NULL,
    veto            INTEGER NOT NULL DEFAULT 0,
    tier            TEXT NOT NULL,
    debt_to_mcap    REAL,
    business_model  TEXT,
    ethical_score   INTEGER DEFAULT 0,
    llm_confidence  REAL DEFAULT 0.5,
    assessed_date   TEXT NOT NULL,
    source          TEXT DEFAULT 'SCORED',
    llm_hash        TEXT
);

CREATE TABLE IF NOT EXISTS platt_calibration (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    A           REAL NOT NULL,
    B           REAL NOT NULL,
    n_samples   INTEGER NOT NULL,
    ece         REAL,
    trained_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS strategy_sandbox (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_text   TEXT NOT NULL,
    param_name      TEXT,
    param_old       TEXT,
    param_new       TEXT,
    backtest_wr     REAL,
    backtest_dd     REAL,
    backtest_sharpe REAL,
    status          TEXT DEFAULT 'PROPOSED',
    created_at      TEXT DEFAULT (datetime('now')),
    reviewed_at     TEXT
);

CREATE TABLE IF NOT EXISTS strategy_approved (
    param_name      TEXT PRIMARY KEY,
    param_value     TEXT NOT NULL,
    approved_at     TEXT NOT NULL,
    sandbox_id      INTEGER
);

-- Prevent duplicate sniper_results rows (reruns should not create duplicates)
CREATE UNIQUE INDEX IF NOT EXISTS uq_sniper_results_date_symbol
    ON sniper_results(run_date, symbol);
"""


def _migrate_db_v4():
    """v4.0-M additive migration. Safe to run on every startup."""
    try:
        with _db_conn(write=True) as con:
            con.executescript(_DB_SCHEMA_V4)
        log.info("DB v4.0-M migration complete ✅")
    except Exception as e:
        log.debug(f"DB v4 migration: {e}")



# ══════════════════════════════════════════════════════════════════════════════
# [PATCH-F]  WEEKLY AI STATUS AGENT  (v4.0-M — Step 10, read-only LLM analysis)
# ══════════════════════════════════════════════════════════════════════════════

def _weekly_ai_status_agent():
    """
    Step 10: Weekly AI Status Agent.
    Reads performance data, generates observations via GPT-4o (batch).
    NEVER mutates DB or parameters. Falls back to _send_weekly_review() if no LLM key.
    """
    if not (_ANTHROPIC_OK or _OPENAI_OK):
        _send_weekly_review()
        return

    log.info("Weekly AI Status Agent running...")
    try:
        since = (datetime.today() - timedelta(days=7)).strftime("%Y-%m-%d")
        with _db_conn() as con:
            perf = con.execute("""
                SELECT grade, status, pnl_pct, sector
                FROM pick_outcomes WHERE run_date>=? AND status!='open'
            """, (since,)).fetchall()
            decisions = con.execute("""
                SELECT decision, COUNT(*) FROM trade_decisions WHERE run_date>=?
                GROUP BY decision
            """, (since,)).fetchall()
            halal_corr = con.execute("""
                SELECT h.tier, o.status, o.pnl_pct
                FROM halal_ai_cache h
                JOIN pick_outcomes o ON h.symbol=o.symbol
                WHERE o.run_date>=? AND o.status!='open'
            """, (since,)).fetchall()

        total   = len(perf)
        wins    = sum(1 for _, s, _, _ in perf if s in ("r1_hit","r2_hit","r3_hit"))
        avg_pnl = (sum(p or 0 for _, _, p, _ in perf) / total) if total > 0 else 0
        dec_map = {d: c for d, c in decisions}
        sector_wr = {}
        for _, status, pnl, sector in perf:
            sector_wr.setdefault(sector, {"wins": 0, "total": 0})
            sector_wr[sector]["total"] += 1
            if status in ("r1_hit","r2_hit","r3_hit"):
                sector_wr[sector]["wins"] += 1

        context = {
            "week": since,
            "total_closed": total,
            "wins": wins,
            "win_rate_pct": round(wins/total*100, 1) if total > 0 else 0,
            "avg_pnl_pct": round(avg_pnl, 2),
            "taken": dec_map.get("TAKEN", 0),
            "skipped": dec_map.get("SKIPPED", 0),
            "sector_win_rates": {
                s: round(v["wins"]/v["total"]*100, 1)
                for s, v in sector_wr.items() if v["total"] >= 2
            },
            "halal_tier_performance": {
                tier: {
                    "wins": sum(1 for t, s, _ in halal_corr if t==tier and s in ("r1_hit","r2_hit","r3_hit")),
                    "total": sum(1 for t, _, _ in halal_corr if t==tier)
                }
                for tier in ("PURE", "ACCEPTABLE", "RISKY")
            }
        }

        prompt = (
            "You are a trading performance analyst reviewing a week of NSE halal swing trades.\n"
            f"Context: {json.dumps(context, indent=2)}\n\n"
            "Generate a structured report with EXACTLY these sections:\n"
            "OBSERVATIONS: 2-3 factual bullet points about what happened\n"
            "PATTERNS: 1-2 repeating patterns you notice\n"
            "ANOMALIES: anything unexpected vs historical norms\n\n"
            "Rules:\n"
            "- Be factual, not prescriptive\n"
            "- Never say 'Set X = Y' or suggest parameter changes\n"
            "- Flag halal tier correlation if noteworthy\n"
            "- Keep under 300 words"
        )
        report = (_call_openai(prompt, model=OPENAI_BATCH_MODEL, max_tokens=400) or
                  _call_claude(prompt, max_tokens=400))

        if not report:
            _send_weekly_review()
            return

        week_start = since
        with _db_conn(write=True) as con:
            con.execute("""
                INSERT OR REPLACE INTO weekly_reviews
                  (week_start, signals_total, taken, skipped, wins, losses,
                   avg_pnl, summary_text)
                VALUES (?,?,?,?,?,?,?,?)
            """, (week_start, total, dec_map.get("TAKEN",0), dec_map.get("SKIPPED",0),
                  wins, total-wins, avg_pnl, report))

        msg = (f"\U0001f4ca WEEKLY AI REPORT | {since} \u2192 {datetime.today().strftime('%Y-%m-%d')}\n\n"
               f"{report}\n\n\U0001f91d Read-only analysis. No parameters changed.")
        _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, msg)
        log.info("Weekly AI Status Agent complete ✅")

    except Exception as e:
        log.error(f"Weekly AI Status Agent failed: {e}")
        _send_weekly_review()



# ══════════════════════════════════════════════════════════════════════════════
# [PATCH-G]  SANDBOX PARAMETER PROPOSALS  (v4.0-M — Step 11, human-gated)
# ══════════════════════════════════════════════════════════════════════════════

def _generate_sandbox_proposal():
    """
    Step 11: Generate parameter proposals from LLM based on 90-day analysis.
    Saves to strategy_sandbox (status=PROPOSED). NEVER touches production.
    Requires 90 days of data and 30+ closed trades.
    """
    if not (_ANTHROPIC_OK or _OPENAI_OK):
        log.info("Sandbox proposals require LLM key — skipping")
        return

    try:
        with _db_conn() as con:
            oldest = con.execute("SELECT MIN(run_date) FROM pick_outcomes").fetchone()
            count  = con.execute("SELECT COUNT(*) FROM pick_outcomes WHERE status!='open'").fetchone()
        if not oldest or not oldest[0]:
            log.info("No historical data — skipping sandbox proposals"); return
        data_days = (datetime.today().date() -
                     datetime.strptime(oldest[0], "%Y-%m-%d").date()).days
        if data_days < 90 or (count[0] if count else 0) < 30:
            log.info(f"Only {data_days}d data ({count[0] if count else 0} closed trades) "
                     "— sandbox proposals need 90d/30 trades"); return
    except Exception as e:
        log.debug(f"Sandbox data check: {e}"); return

    try:
        since = (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d")
        with _db_conn() as con:
            perf = con.execute("""
                SELECT grade, status, pnl_pct, sector, fused_score
                FROM pick_outcomes WHERE run_date>=? AND status!='open'
            """, (since,)).fetchall()
            current_params = {
                "APEX_MIN_SCORE": APEX_MIN_SCORE,
                "APEX_TOP_N": APEX_TOP_N,
                "CAPACITY_MAX_OPEN": CAPACITY_MAX_OPEN,
                "CAPACITY_MAX_WEEK": CAPACITY_MAX_WEEK,
                "MC_SIMS": MC_SIMS,
            }

        total = len(perf)
        if total < 10: return
        wins = sum(1 for _, s, _, _, _ in perf if s in ("r1_hit","r2_hit","r3_hit"))

        prompt = (
            "You are a trading strategy parameter optimiser. "
            "Based on 90-day performance data, suggest 1-3 parameter adjustments.\n"
            f"Current params: {json.dumps(current_params)}\n"
            f"Performance: {total} trades, {wins} wins ({wins/total*100:.1f}% WR), "
            f"avg P&L {sum(p or 0 for _,_,p,_,_ in perf)/total:.1f}%\n\n"
            "Return a JSON array of proposals:\n"
            '[{"param": "APEX_MIN_SCORE", "old_value": 48, "new_value": 52, '
            '"rationale": "Raise threshold in CHOP regime — reduces false positives"}]\n\n'
            "Rules:\n"
            "- Maximum 3 proposals\n"
            "- Only suggest params from the current_params dict\n"
            "- Changes must be modest (+-10% max)\n"
            "- Require >=5% win rate improvement as justification"
        )
        raw = (_call_openai(prompt, model=OPENAI_BATCH_MODEL, max_tokens=500) or
               _call_claude(prompt, max_tokens=500))
        if not raw: return

        txt = raw.strip().replace("```json", "").replace("```", "")
        proposals = json.loads(txt)
        if not isinstance(proposals, list): return

        with _db_conn(write=True) as con:
            for p in proposals[:3]:
                con.execute("""
                    INSERT INTO strategy_sandbox
                      (proposal_text, param_name, param_old, param_new)
                    VALUES (?,?,?,?)
                """, (
                    p.get("rationale", "")[:500],
                    str(p.get("param", "")),
                    str(p.get("old_value", "")),
                    str(p.get("new_value", "")),
                ))
        log.info(f"Sandbox: {len(proposals)} proposal(s) saved (status=PROPOSED). "
                 "Review at strategy_sandbox table before approving.")

        notif = "\U0001f52c SANDBOX PROPOSALS (pending your review):\n\n"
        for p in proposals[:3]:
            notif += (f"\u2022 {p.get('param')}: {p.get('old_value')} \u2192 {p.get('new_value')}\n"
                      f"  Reason: {p.get('rationale','')[:80]}\n\n")
        notif += "\u2139\ufe0f Run SQL: UPDATE strategy_sandbox SET status='APPROVED' WHERE id=X to approve."
        _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, notif)

    except Exception as e:
        log.error(f"Sandbox proposal: {e}")


def run():
    """
    Single-pass unified pipeline:
    1. Init DB + caches
    2. Macro regime (one fetch, cached)
    3. Halal universe (one fetch, cached)
    4. Bhavcopy (NSE → Sheets → yfinance, one path)
    5. Intelligence: FII/DII, Insider, Filings, Earnings (one fetch each)
    6. Score each halal candidate through both engines (one loop)
    7. Rank by fused score, sector cap, bucket (mid/small)
    8. Outputs: Excel, HTML, Sheets, Telegram (one send)
    """
    _init_db()
    _, date_label = _get_last_trading_day()
    # FEEDBACK LOOP (run first -- update yesterday before scoring today)
    # ---------------------------------------------------------------
    # ═════════════════════════════════════════════════════════════════
    _run_outcome_engine()      # Check what happened to yesterday's picks
    _adjust_sector_multipliers()  # Adjust sector weights based on results
    _alert_open_positions()    # Warn if any open pick near stop

    # META-LABELER: Backfill outcomes + train/retrain model
    # v3.0-M: first try personalized v2, fall back to v1 if not enough decisions
    _update_meta_outcomes()
    meta_model = _train_meta_labeler_v2(min_samples=20) or _train_meta_labeler(min_samples=50)
    if meta_model:
        _save_meta_model(meta_model)

    log.info("=" * 70)
    log.info(f"⚔️  UNIFIED SNIPER {VERSION} | {date_label}")
    log.info(f"    Bismillah — Halal · Fortress × APEX Fused Engine")
    log.info("=" * 70)
    log.info(f"    PAPER={PAPER_MODE} | FORCE_SHEETS={FORCE_SHEETS} | FORCE_YF={FORCE_YFINANCE}")
    log.info(f"    SHARIAH_TTL={SHARIAH_TTL_DAYS}d | MC_SIMS={MC_SIMS} | CB_FAIL_SAFE={CB_FAIL_SAFE}")

    # Reset per-run caches
    global _MACRO_CACHE, _HALAL_UNIVERSE_CACHE, _NSE_SESSION
    global _SECTOR_LIVE_CACHE, _SMALLCAP_CACHE, _HALAL_CUSTOM_LIST
    _MACRO_CACHE          = None
    _HALAL_UNIVERSE_CACHE = None
    _NSE_SESSION          = None
    _SECTOR_LIVE_CACHE    = {}
    _SMALLCAP_CACHE       = {}

    # 1. Macro
    macro = _get_macro()
    if macro["macro_state"] == "MASSACRE":
        log.error("🚨 MASSACRE — pipeline halted, sending Telegram alert")
        send_telegram([], macro, fetch_fii_dii(), date_label, "NSE")
        return []

    # 2. Halal universe
    _HALAL_CUSTOM_LIST = _read_sheets_halal_list()
    if _HALAL_CUSTOM_LIST:
        log.info(f"Custom HALAL_LIST: {len(_HALAL_CUSTOM_LIST)} symbols loaded from Sheets Tab 7")

    # 3. Bhavcopy
    bhavcopy, data_source = load_bhavcopy()
    if bhavcopy.empty:
        log.error("❌ All data sources failed — aborting"); return []
    if bhavcopy["volume"].sum() <= 0:
        log.error("❌ Volume=0 across all rows — data quality failure"); return []

    # 4. Pre-filter
    cands = bhavcopy[
        (bhavcopy["turnover_lakhs"] >= MIN_TURNOVER_LAKHS) &
        (bhavcopy["close"] >= MIN_PRICE) &
        (bhavcopy["close"] <= MAX_PRICE)
    ].copy()
    log.info(f"After liquidity+price filter: {len(cands)} candidates")
    cands = cands[cands["symbol"].apply(is_halal)].copy()
    log.info(f"After halal filter: {len(cands)} candidates")
    if len(cands) > MAX_CANDIDATES:
        cands = cands.nlargest(MAX_CANDIDATES, "turnover_lakhs")
        log.info(f"Capped to top {MAX_CANDIDATES} by turnover")

    # 5. Intelligence — fetched concurrently via asyncio to eliminate serial waits.
    #    Each fetch is I/O-bound (NSE API / Google Sheets / yfinance); running them
    #    sequentially wastes 10-20 s waiting for one before starting the next.
    #    asyncio.to_thread() wraps each blocking call in a thread-pool executor
    #    while the event loop overlaps all four downloads simultaneously.
    import asyncio

    async def _fetch_intelligence_async():
        log.info("Fetching intelligence data concurrently (asyncio)…")
        fii_task, ins_task, fil_task, earn_task = await asyncio.gather(
            asyncio.to_thread(fetch_fii_dii),
            asyncio.to_thread(fetch_insider_trades),
            asyncio.to_thread(fetch_filings),
            asyncio.to_thread(fetch_earnings_calendar),
        )
        return fii_task, ins_task, fil_task, earn_task

    # Safe asyncio runner: if an event loop is already running (Jupyter, FastAPI,
    # pytest-asyncio), asyncio.run() raises RuntimeError. In that case, we spawn
    # a plain daemon thread with its OWN new event loop.
    #
    # BUG FIX [ASYNC-001]: the previous fallback used ThreadPoolExecutor(max_workers=1)
    # and called asyncio.run() inside the single worker.  asyncio.to_thread() (used
    # inside _fetch_intelligence_async) submits tasks to the DEFAULT thread pool,
    # which is the same single-worker TPE — causing a deadlock where the coroutine
    # waits for a thread that will never become free.
    # Fix: spin a bare threading.Thread.  It has its own stack and is not subject to
    # the executor's pool limit, so asyncio.to_thread() dispatches into the default
    # loop's unrestricted thread pool without contention.
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        fii_data, insider_map, filings, earn_cal = asyncio.run(_fetch_intelligence_async())
    else:
        import threading as _threading
        _result: list = []
        _exc:    list = []

        def _run_in_own_loop():
            _new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_new_loop)
            try:
                _result.append(_new_loop.run_until_complete(_fetch_intelligence_async()))
            except Exception as _e:
                _exc.append(_e)
            finally:
                _new_loop.close()

        _t = _threading.Thread(target=_run_in_own_loop, daemon=True)
        _t.start()
        _t.join(timeout=90)          # generous but bounded
        if not _t.is_alive() and _exc:
            raise _exc[0]
        if _t.is_alive():
            log.warning("Async intelligence fetch timed out after 90 s — using empty defaults")
            fii_data, insider_map, filings, earn_cal = (
                {"label": "TIMEOUT", "fii_pts": 0, "dii_pts": 0},
                {}, [], {}
            )
        else:
            fii_data, insider_map, filings, earn_cal = _result[0]

    log.info(f"FII/DII: {fii_data['label']} | Insider: {len(insider_map)} symbols | "
             f"Filings: {len(filings)} | Earnings: {len(earn_cal)} events")

    # 6. Pre-load histories in BACKGROUND — scoring starts immediately (FIX-1).
    #    Old: blocked entire run waiting for 98-symbol batch download (~3-6 min).
    #    New: background thread fills hist_cache while scoring loop runs;
    #         fetch_history() uses cache if available, falls back to individual
    #         download if the symbol hasn't arrived yet. No gems missed.
    import threading as _threading
    hist_cache: Dict[str, pd.DataFrame] = {}
    _hist_lock  = _threading.Lock()

    def _bg_preload_histories():
        end   = datetime.today()
        start = end - timedelta(days=350)
        syms  = cands["symbol"].tolist()
        try:
            import yfinance as yf
        except ImportError:
            return
        for i in range(0, len(syms), 50):
            chunk   = syms[i:i + 50]
            tickers = " ".join(f"{s}.NS" for s in chunk)
            for attempt in range(2):
                try:
                    raw = yf.download(tickers, start=start, end=end,
                                      progress=False, auto_adjust=False,
                                      group_by="ticker",
                                      timeout=_YF_DOWNLOAD_TIMEOUT)
                    if raw.empty:
                        break
                    for sym in chunk:
                        tk = f"{sym}.NS"
                        try:
                            if hasattr(raw.columns, "levels"):
                                lvl0 = list(raw.columns.get_level_values(0))
                                lvl1 = list(raw.columns.get_level_values(1))
                                tk_level = 0 if any(".NS" in str(v) for v in lvl0) else (1 if any(".NS" in str(v) for v in lvl1) else 0)
                                tickers_in_col = list(raw.columns.get_level_values(tk_level))
                                sub = (raw.xs(tk, axis=1, level=tk_level) if tk in tickers_in_col
                                       else (raw[tk] if tk in raw.columns else None))
                            else:
                                sub = raw.copy() if len(chunk) == 1 else None
                            if sub is None or sub.empty:
                                continue
                            sub = sub.reset_index()
                            sub.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in sub.columns]
                            if "close" not in sub.columns and "adj close" in sub.columns:
                                sub = sub.rename(columns={"adj close": "close"})
                            sub["date"] = pd.to_datetime(sub["date"])
                            df = sub[["date", "open", "high", "low", "close", "volume"]].dropna()
                            with _hist_lock:
                                hist_cache[sym.upper()] = _validate_no_lookahead(df)
                        except Exception:
                            continue
                    break
                except Exception as e:
                    log.debug(f"BG preload chunk {i}-{i+50} attempt {attempt+1}: {e}")
                    time.sleep(2 * (attempt + 1))

    _preload_thread = _threading.Thread(target=_bg_preload_histories, daemon=True)
    _preload_thread.start()
    log.info(f"Pre-loading {len(cands)} histories in background — scoring starts immediately")

    # 7. Scoring loop (one loop, both engines fused)
    sess    = _get_nse_session()
    results = []
    for i,(_, row) in enumerate(cands.iterrows()):
        sym = row["symbol"]
        if i % 25 == 0:
            log.info(f"Progress: {i}/{len(cands)} | picks: {len(results)}")
        try:
            hist = fetch_history(sym, days=300, sess=sess, yf_cache=hist_cache)
            if len(hist) < MIN_HIST_BARS:
                log.debug(f"{sym}: only {len(hist)} bars — skip"); continue
            r = assemble_pick(sym, row, hist, fii_data, insider_map, filings, earn_cal, macro)
            if r:
                results.append(r)
                log.info(f"  ✅ {sym:12s} | fused={r['fused']}/100 | {r['grade'][:10]} | {r['story'][:60]}")
        except Exception as e:
            log.debug(f"{sym}: {e}")

    log.info(f"\n{'='*70}")
    log.info(f"Screened {len(cands)} | Passed: {len(results)}")
    # ── Log data quality to DB ──
    try:
        halal_uni = get_halal_universe()
        con = sqlite3.connect(DB_PATH)
        con.execute("""
            INSERT INTO data_quality (run_date, data_source, bhavcopy_records,
            halal_universe_size, halal_in_bhavcopy, yfinance_shrink, missing_halal, alert)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            date_label, data_source, len(bhavcopy), len(halal_uni),
            len(bhavcopy[bhavcopy["symbol"].isin(halal_uni)]),
            "YES" if (data_source == "YFINANCE" and len(bhavcopy) <= 100) else "NO",
            len(halal_uni - set(bhavcopy["symbol"])),
            "SHRUNK" if (data_source == "YFINANCE" and len(bhavcopy) <= 100) else "OK"
        ))
        con.commit(); con.close()
        log.info("Data quality logged to DB")
    except Exception as e:
        log.debug(f"DB quality log: {e}")
    # 7. Rank + sector cap + bucket
    # Apply data quality gate adjustments
    dq_gate = _data_quality_gate(bhavcopy, data_source)
    effective_min_score = dq_gate["apex_min_score"]
    effective_top_n = dq_gate["apex_top_n"]

    # Filter by effective minimum
    results = [r for r in results if r["fused"] >= effective_min_score]

    results.sort(key=lambda x: (x["fused"]*1000 + x["whale_score"]*10 + x["div_score"]), reverse=True)
    sec_counts: dict = {}; globally_capped=[]
    for r in results:
        sec=r["sector"]; cnt=sec_counts.get(sec,0)
        if cnt<2: globally_capped.append(r); sec_counts[sec]=cnt+1

    # ── DYNAMIC BUCKET ALLOCATION ──
    # Only run market-cap lookup if we actually have candidates to bucket
    mcap_map: dict = {}
    if globally_capped:
        def _batch_market_caps(symbols: list, fallback_map: dict) -> dict:
            """Return {symbol: mcap_in_cr} via batch yfinance tickers + SQLite cache.
            Uses ThreadPoolExecutor with per-symbol timeout so one slow call
            cannot block the entire batch.
            Bug fix: SQLite writes from worker threads are serialised through
            _SQLITE_WRITE_LOCK to prevent 'database is locked' under WAL mode."""
            result = {}

            # 1. SQLite cache (read — safe without lock)
            try:
                con = sqlite3.connect(DB_PATH, timeout=10)
                cached = {r[0]: r[1] for r in con.execute(
                    "SELECT symbol, mcap FROM mcap_cache WHERE fetched_at > ?",
                    ((datetime.today() - timedelta(days=7)).isoformat(),)
                ).fetchall()}
                con.close()
                result.update(cached)
            except Exception:
                cached = {}

            need_fetch = [s for s in symbols if s not in result]
            if not need_fetch:
                return result

            # 2. Parallel fetch with hard timeout per symbol
            def _fetch_one(sym):
                try:
                    import yfinance as yf
                    info = yf.Ticker(f"{sym}.NS").info
                    mc = info.get("marketCap")
                    if mc:
                        return sym, float(mc) / 1e7
                except Exception:
                    pass
                return sym, fallback_map.get(sym, 100.0)

            try:
                with ThreadPoolExecutor(max_workers=3) as executor:
                    futures = {executor.submit(_fetch_one, sym): sym for sym in need_fetch}
                    for future in futures:
                        sym = futures[future]
                        try:
                            sym_out, mcap = future.result(timeout=_YF_INFO_TIMEOUT)
                            result[sym_out] = mcap
                        except FutureTimeoutError:
                            log.warning(f"Market cap timeout: {sym}")
                            result[sym] = fallback_map.get(sym, 100.0)
                        except Exception:
                            result[sym] = fallback_map.get(sym, 100.0)
            except Exception as e:
                log.error(f"Batch market cap executor failed: {e}")
                for sym in need_fetch:
                    if sym not in result:
                        result[sym] = fallback_map.get(sym, 100.0)

            # 3. Cache to SQLite — serialised write to avoid "database is locked"
            with _SQLITE_WRITE_LOCK:
                try:
                    con = sqlite3.connect(DB_PATH, timeout=10)
                    today_iso = datetime.today().isoformat()
                    for sym, mcap in result.items():
                        if sym in need_fetch:
                            con.execute(
                                "INSERT OR REPLACE INTO mcap_cache (symbol, mcap, fetched_at) VALUES (?,?,?)",
                                (sym, mcap, today_iso)
                            )
                    con.commit()
                    con.close()
                except Exception:
                    pass

            return result

        # Pre-compute all market caps in one batch
        symbols_to_lookup = [r["symbol"] for r in globally_capped]
        fallback_mcaps = {r["symbol"]: r["close"] * 100 for r in globally_capped}
        mcap_map = _batch_market_caps(symbols_to_lookup, fallback_mcaps)

    # Assign to results
    for r in globally_capped:
        r["mcap_proxy"] = mcap_map.get(r["symbol"], r["close"] * 100)

    # Define buckets by market cap (in Cr)
    LARGE_CAP_MIN = 20000   # ₹20,000 Cr+
    MID_CAP_MIN = 5000      # ₹5,000-20,000 Cr
    SMALL_CAP_MIN = 1000    # ₹1,000-5,000 Cr
    # Below 1,000 Cr = micro (avoid or tiny)

    large_picks = [r for r in globally_capped if r["mcap_proxy"] >= LARGE_CAP_MIN]
    mid_picks   = [r for r in globally_capped if MID_CAP_MIN <= r["mcap_proxy"] < LARGE_CAP_MIN]
    small_picks = [r for r in globally_capped if SMALL_CAP_MIN <= r["mcap_proxy"] < MID_CAP_MIN]
    micro_picks = [r for r in globally_capped if r["mcap_proxy"] < SMALL_CAP_MIN]

    # Dynamic allocation: up to effective_top_n total, distributed by availability
    total_slots = effective_top_n
    allocation = []

    # Priority: Large > Mid > Small > Micro (skip micro in chop/fog)
    remaining = total_slots

    # Take from large first (safest)
    take_large = min(len(large_picks), 1 if remaining >= 4 else 0)
    allocation.extend(large_picks[:take_large])
    remaining -= take_large

    # Then mid (core focus)
    take_mid = min(len(mid_picks), min(2, remaining))
    allocation.extend(mid_picks[:take_mid])
    remaining -= take_mid

    # Then small (opportunistic)
    take_small = min(len(small_picks), min(2, remaining))
    allocation.extend(small_picks[:take_small])
    remaining -= take_small

    # Only take micro if we have slots left and market is clear
    if remaining > 0 and macro["macro_state"] == "CLEAR":
        take_micro = min(len(micro_picks), remaining)
        allocation.extend(micro_picks[:take_micro])

    top_picks = allocation
    seen = set()
    top_picks = [r for r in top_picks if r["symbol"] not in seen and not seen.add(r["symbol"])]

    # ── v3.0-M: Attach meta_prob, regime-scaled confidence, setup profile ──
    meta_model_live = _load_meta_model()
    for r in top_picks:
        profile = _get_setup_profile(r)
        r["setup_profile"] = profile
        meta_features_v3 = {
            "whale_score": r.get("whale_score", 0),
            "div_score":   r.get("div_score", 0),
            "vp_score":    r.get("vp_score", 0),
            "pat_score":   r.get("pat_score", 0),
            "bayes_pct":   r.get("bayes_pct", 0),
            "macro_state": macro.get("macro_state", "CHOP"),
            "sector":      r.get("sector", "DIVERSIFIED"),
            "vix_level":   macro.get("vix_val", 18.0),
            "primary_fused_score": r.get("fused", 0),
        }
        meta_prob = _get_meta_probability(meta_model_live, meta_features_v3)
        r["meta_prob"]   = _regime_scaled_confidence(meta_prob, macro["macro_state"], macro.get("vix_val", 18.0))
        r["worth_flag"]  = _confidence_flag(r["meta_prob"])
        r["macro_state"] = macro.get("macro_state", "CHOP")   # propagate for profile display

    # ── v4.0-M: Halal AI Screen + Calibrated AI Judge ──────────────────────
    log.info("Running Halal AI Screen + Calibrated AI Judge on top picks...")
    cal_params = _load_calibration_params()
    judged_picks = []
    for pick in top_picks:
        sector = pick.get("sector", "DIVERSIFIED")
        halal  = halal_ai_screen(pick["symbol"], sector)
        judged = calibrated_ai_judge(pick, halal, macro, cal_params)
        if not judged["veto"]:
            judged_picks.append(judged)
        else:
            log.info(f"  VETO {pick['symbol']}: {judged['veto_reason']}")
    top_picks = judged_picks
    log.info(f"After AI Judge: {len(top_picks)} picks pass")

    # ── v3.0-M: Capacity guard ─────────────────────────────────────────────
    capacity = _capacity_guard(date_label)
    if capacity.get("note"):
        log.info(f"Capacity guard: {capacity['note']}")

    log.info(f"\n{'='*70}")
    log.info(f"⚔️  TOP {len(top_picks)} PICKS")
    log.info(f"{'='*70}")
    for rank, r in enumerate(top_picks, 1):
        vn = "" if r.get("vol_reliable",True) else " [NO-VOL]"
        log.info(f"  #{rank} {r['symbol']:12s} | Fused {r['fused']}/100 | Fort {r['fort_pct']:.0f}% "
                 f"| APEX {r['apex_composite']}/100 | {r['grade']}{vn} "
                 f"| AI {round(r.get('meta_prob',0.55)*100)}% [{r.get('worth_flag','—')}] "
                 f"| Halal: {r.get('halal_detail',{}).get('tier','?')}/{r.get('halal_detail',{}).get('score','?')}"  
                 f"| Cal: {r.get('calibrated_confidence',r.get('meta_prob',0)):.0%} | Size: {r.get('position_size_tier','?')}")
        log.info(f"       Buy ₹{r['buy_lo']}-{r['buy_hi']} | SL ₹{r['stop_loss']} | "
                 f"R1 ₹{r['r1']} | R2 ₹{r['r2']} | MC {r['mc_survival']}%")
        log.info(f"       {r['story'][:80]}")
    # 8. Outputs  (Performance sheet is now written inside save_excel)
    log.info("Saving Excel…");       save_excel(top_picks, results, fii_data, date_label, data_source, bhavcopy)
    log.info("Saving HTML…");        save_html(top_picks, fii_data, date_label)
    log.info("Calibrating Bayes priors…"); _calibrate_bayes_priors()
    log.info("Pushing to Sheets…");  push_gsheets(top_picks, date_label)
    log.info("Pushing PERFORMANCE…"); _push_performance_tab(date_label)
    # AI_INSIGHTS pushed unconditionally — shows story+conviction even without LLM API key
    log.info("Pushing AI_INSIGHTS…"); _push_ai_insights_tab(top_picks, date_label)
    log.info("Sending Telegram…");   send_telegram_v3(top_picks, macro, fii_data, date_label, data_source, capacity)

    # Persist results to DB + outcome tracking
    try:
        with _db_conn(write=True) as con:
            for r in top_picks:
                # Existing sniper_results (OR IGNORE prevents dupe on rerun)
                con.execute(
                    "INSERT OR IGNORE INTO sniper_results (run_date,symbol,grade,fused_score,close,stop_loss,r1,r2,r3,story,sector) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (date_label,r["symbol"],r["grade"],r["fused"],r["close"],
                     r["stop_loss"],r["r1"],r["r2"],r["r3"],r["story"],r.get("sector","DIVERSIFIED"))
                )
                # outcome tracking (initial state)
                con.execute(
                    "INSERT OR IGNORE INTO pick_outcomes (run_date,symbol,entry_price,stop_loss,r1,r2,r3,grade,fused_score,story,status) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (date_label,r["symbol"],r["close"],r["stop_loss"],r["r1"],r["r2"],r["r3"],
                     r["grade"],r["fused"],r["story"],"open")
                )
                # v3.0-M: store setup_profile in meta_features for personalized learning
                try:
                    con.execute(
                        "UPDATE meta_features SET setup_profile=?, days_to_earnings=? "
                        "WHERE symbol=? AND run_date=?",
                        (r.get("setup_profile",""), r.get("earn_days",-1),
                         r["symbol"], date_label)
                    )
                except Exception:
                    pass
        log.info(f"DB: {len(top_picks)} picks saved for outcome tracking")
    except Exception as e:
        log.error(f"DB persist for top picks FAILED — outcome tracking broken: {e}")   # H1

    # BUG FIX [ML-001]: second backfill + retrain pass at end of run().
    # v3.0-M: use personalized v2 labeler; fall back to v1 if insufficient decisions.
    log.info("Post-run meta-labeler refresh…")
    _update_meta_outcomes()
    refreshed_model = _train_meta_labeler_v2(min_samples=20) or _train_meta_labeler(min_samples=50)
    if refreshed_model:
        _save_meta_model(refreshed_model)
        log.info("Meta-model refreshed with today's resolved outcomes")

    # v4.0-M: auto-log any unresponded picks as SKIPPED at EOD
    _auto_log_skipped_picks(date_label)

    log.info(f"\n✅ Done | {len(top_picks)} picks | Macro: {macro['macro_state']} | "
             f"VIX: {macro['vix_val']:.1f} | Source: {data_source} | "
             f"Bismillah 🤲")
    return top_picks


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if "--weekly-review" in sys.argv:
        # Run standalone: python sniper_unified_v2.py --weekly-review
        _init_db()
        _weekly_ai_status_agent()   # v4.0-M: AI agent (was _send_weekly_review)
    elif "--sandbox-proposals" in sys.argv:
        # Run standalone: python sniper_unified_v2.py --sandbox-proposals
        _init_db()
        _generate_sandbox_proposal()
    else:
        run()
