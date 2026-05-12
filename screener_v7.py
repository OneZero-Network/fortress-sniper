"""
╔══════════════════════════════════════════════════════════════════════╗
║   FORTRESS SCREENER v7.0 — UNIFIED SNIPER ENGINE                   ║
║   Bismillah — In the name of Allah, the Most Gracious              ║
║                                                                      ║
║   ARCHITECTURE: Single-file merge of v5.7 + v6.0                  ║
║   No sibling imports. One file. One truth. No silent failures.      ║
║                                                                      ║
║   v7.0 NEW: GOOGLE SHEETS AS MASTER DATA SOURCE                    ║
║   ─────────────────────────────────────────────────────────────     ║
║   The screener now reads 5 data inputs from dedicated worksheets    ║
║   inside a single Google Workbook. You populate these manually      ║
║   each evening (or automate via macros). GitHub Actions runs the    ║
║   scoring engine on that data and sends results to Telegram.        ║
║                                                                      ║
║   WORKBOOK SHEET MAP:                                               ║
║   ┌──────┬──────────────────────────────────────────┬──────────┐   ║
║   │  #   │  Sheet Name                              │  Score   │   ║
║   ├──────┼──────────────────────────────────────────┼──────────┤   ║
║   │  1   │  Bhavcopy  — Price, Volume, VPOC data   │ 80 pts   │   ║
║   │  2   │  FII_DII   — Institutional flow         │ 30 pts   │   ║
║   │  3   │  Insider   — Insider trading data       │ 30 pts   │   ║
║   │  4   │  Filings   — Corporate announcements    │ 30 pts   │   ║
║   │  5   │  Earnings  — Earnings event calendar    │ 30 pts   │   ║
║   └──────┴──────────────────────────────────────────┴──────────┘   ║
║   Total: 200 base pts + 30 forward bonus = 230 maximum             ║
║                                                                      ║
║   NSE LIVE FETCH is still attempted first. If NSE is blocked,      ║
║   the workbook data is the authoritative fallback (not yfinance).   ║
║   If neither is available, yfinance is the last resort.             ║
║                                                                      ║
║   SHEET COLUMN SCHEMAS (fill these in your workbook):              ║
║                                                                      ║
║   Bhavcopy:  SYMBOL | OPEN | HIGH | LOW | CLOSE | VOLUME |         ║
║              TURNOVER_LAKHS | SERIES (optional, defaults EQ)        ║
║                                                                      ║
║   FII_DII:   DATE | FII_NET_CR | DII_NET_CR                        ║
║              (₹ crore, positive = buying)                           ║
║                                                                      ║
║   Insider:   SYMBOL | PERSON | SHARES | VALUE_LAKHS | DATE |       ║
║              TYPE  (Buy/Sell — only Buy rows counted)               ║
║                                                                      ║
║   Filings:   SYMBOL | DATE | SUBJECT | SENTIMENT                   ║
║              (SENTIMENT: positive / negative / neutral)             ║
║                                                                      ║
║   Earnings:  SYMBOL | RESULT_DATE | PURPOSE                        ║
║              (PURPOSE: results / dividend — other rows ignored)     ║
║                                                                      ║
║   DATA PRIORITY ORDER:                                              ║
║     1. Live NSE API  (fastest, full 2000+ stock universe)           ║
║     2. Google Sheets (your manually curated workbook)               ║
║     3. yfinance      (last resort, 300-stock watchlist)             ║
║                                                                      ║
║   RETAINED FROM v5.7 + v6.0 (all features intact):                ║
║   ✓ SN-1 Directive | SN-2 6-layer VPOC | SN-3 9-node Bayes        ║
║   ✓ SN-4 Macro Hard Filters | SN-5 Vol-Scaled Sizing              ║
║   ✓ SN-6 Dynamic Exit Engine | SN-7 Sniper Telegram Format        ║
║   ✓ CVD Divergence | VSA Absorption | Momentum Exhaustion          ║
║   ✓ Exit Liquidity | Fog Engine | Dynamic Weights                  ║
║   ✓ Monte Carlo | Bayesian 9-node | Trailing Stop + BE             ║
║   ✓ 52W Compression | ATR Velocity | PEAD Drift                    ║
║   ✓ EOD SQLite Cache | Halal Filter | ROCE Gate                    ║
║   ✓ Round-Trip Guard | Smallcap Circuit Breaker                    ║
║   ✓ Paper Mode | Sector Truth | VPOC bin-histogram                 ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import os, io, sys, time, json, logging, math, random, warnings, sqlite3
import threading
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Union

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger(__name__)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("peewee").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.WARNING)


# ══════════════════════════════════════════════════════════════════════
# SECTION 1 — CONFIG & CONSTANTS
# ══════════════════════════════════════════════════════════════════════

TELEGRAM_TOKEN     = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_SHARE_IDS = [
    cid.strip() for cid in os.getenv("TELEGRAM_SHARE_IDS", "").split(",")
    if cid.strip()
]
GOOGLE_SHEET_ID    = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_CREDS_JSON  = os.getenv("GOOGLE_CREDS_JSON", "")
EXCEL_OUTPUT_PATH  = Path("outputs/fortress_screener.xlsx")
HTML_OUTPUT_PATH   = Path("outputs/report.html")
DB_PATH            = Path("outputs/fortress_cache.db")

PAPER_MODE         = os.getenv("PAPER_MODE", "false").lower() == "true"
ACCOUNT_EQUITY     = float(os.getenv("ACCOUNT_EQUITY", "500000"))
ACCOUNT_RISK_PCT   = float(os.getenv("ACCOUNT_RISK_PCT", "0.01"))

# ── v7.0: Force data source flags ──────────────────────────────────
# FORCE_SHEETS=true → skip NSE attempt, go straight to workbook data
# FORCE_YFINANCE=true → skip NSE + Sheets, use yfinance only
FORCE_SHEETS   = os.getenv("FORCE_SHEETS", "false").lower() == "true"
FORCE_YFINANCE = os.getenv("FORCE_YFINANCE", "false").lower() == "true"

# ── Google Sheets sheet name constants ─────────────────────────────
# These are the EXACT tab names your workbook must use.
# Tab 1 → BHAVCOPY   (2000+ rows — price/volume data)
# Tab 2 → FII_DII    (1–5 rows — institutional flow, latest date last)
# Tab 3 → INSIDER    (variable rows — insider buy transactions)
# Tab 4 → FILINGS    (variable rows — corporate announcements)
# Tab 5 → EARNINGS   (variable rows — result / dividend dates)
# Tab 6 → SCREENER   (output — written by the screener automatically)
#
# Override any tab name via GitHub Actions secret / env var if needed:
#   e.g.  SHEET_BHAVCOPY=MY_PRICES
SHEET_BHAVCOPY  = os.getenv("SHEET_BHAVCOPY",  "BHAVCOPY")
SHEET_FII_DII   = os.getenv("SHEET_FII_DII",   "FII_DII")
SHEET_INSIDER   = os.getenv("SHEET_INSIDER",   "INSIDER")
SHEET_FILINGS   = os.getenv("SHEET_FILINGS",   "FILINGS")
SHEET_EARNINGS  = os.getenv("SHEET_EARNINGS",  "EARNINGS")
SHEET_SCREENER  = os.getenv("SHEET_SCREENER",  "SCREENER")   # output tab

SCORE_WEIGHTS = dict(fortress=80, fii_dii=30, insider=30, filing=30, earnings=30)
MAX_SCORE     = sum(SCORE_WEIGHTS.values())   # 200

MID_CAP_PICKS   = 2   # FIX #2: was 1
SMALL_CAP_PICKS = 2   # FIX #2: was 1
LARGE_CAP_PICKS = 1   # FIX #2: new bucket — stocks ≥ ₹2 000 were silently discarded

RANKS = [
    (160, "⚔️ ELITE",    "FULL 100%"),
    (130, "🟢 PRISTINE", "FULL 100%"),
    (105, "🟡 HIGH",     "HALF 50%"),
    ( 85, "🟠 MODERATE", "QTR 25%"),
    ( 65, "🔵 PROBE",    "PROBE 10%"),
    (  0, None,           None),
]

CFG = dict(
    vol_ratio        = 2.5,
    turnover_lakhs   = 300,
    atr_t2           = 1.5,
    atr_t3           = 1.75,
    alt_warn_pct     = 40.0,
    # FIX #9: raised from 50 → 60 so the progressive altitude penalty (40–60%)
    # covers a meaningful 20-pt window instead of a barely-reachable 10-pt band.
    alt_stop_pct     = 60.0,
    mfi_accum        = 40,
    mfi_dist         = 60,
    recency_days     = 45,
    adx_trend        = 25.0,
    adx_range        = 18.0,
    top_n            = 5,
    max_candidates   = 200,
    ma200_tolerance  = 0.05,
    min_hist_bars    = 30,
)

# ── Sniper v6.0 thresholds ──────────────────────────────────────────
SNIPER_CFG = dict(
    vix_panic          = 22.0,
    vix_chop           = 15.0,
    nifty_massacre     = -3.0,
    vpoc_band_pct      = 0.02,
    vpoc_weeks         = 52,
    vol_spikes_52w     = 35,
    bounce_recency     = 45,
    min_bounces        = 3,
    liquidity_mult     = 2.0,
    min_turnover_cr    = 3.0,
    alt_warn_pct       = 40.0,
    alt_stop_pct       = 60.0,   # FIX #9: raised from 50 → 60 (matches CFG)
    score_pristine     = 85,
    score_good         = 70,
    score_marginal     = 58,
    score_probe        = 45,
    risk_per_trade     = 0.015,
    max_pos_pct        = 0.10,
    atr_stop_mult      = 2.0,
    be_atr_mult        = 2.0,
    exit_trail_mult    = 1.5,
    trail_trigger_pct  = 15.0,
    trail_atr_mult     = 2.5,
    score_size_blend   = 0.50,
    r1_pct             = 30.0,
    r2_pct             = 60.0,
    r3_pct             = 100.0,
    r1_sell_pct        = 30,
    r2_sell_pct        = 30,
    r3_sell_pct        = 40,
    bayes_alpha        = 0.12,
    vpoc_3m_wt         = 0.40,
    vpoc_6m_wt         = 0.35,
    vpoc_12m_wt        = 0.25,
)

SECTOR_INDICES = {
    "NIFTY BANK":   "NIFTYBANK",
    "NIFTY IT":     "CNXIT",
    "NIFTY PHARMA": "CNXPHARMA",
    "NIFTY AUTO":   "CNXAUTO",
    "NIFTY FMCG":   "CNXFMCG",
    "NIFTY METAL":  "CNXMETAL",
}

SECTOR_TRUTH = {
    "NIFTY PHARMA":  1.15,
    "NIFTY IT":      1.10,
    "NIFTY AUTO":    1.00,
    "NIFTY FMCG":    0.95,
    "NIFTY METAL":   0.85,
    "NIFTY BANK":    0.00,   # blocked — interest-based
    "NIFTY REALTY":  0.75,
    "NIFTY ENERGY":  0.20,
    "DIVERSIFIED":   1.00,
}
SECTOR_BLOCKED = {"NIFTY BANK", "NIFTY ENERGY"}

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
    "insurance","insur","nifty","bees","etf","reit","invit",
    "liquid","overnight","gilt","treasury",
)

SYMBOL_SECTOR = {
    "TCS":"NIFTY IT","INFY":"NIFTY IT","WIPRO":"NIFTY IT",
    "HCLTECH":"NIFTY IT","TECHM":"NIFTY IT","LTIM":"NIFTY IT",
    "MPHASIS":"NIFTY IT","COFORGE":"NIFTY IT","PERSISTENT":"NIFTY IT",
    "SUNPHARMA":"NIFTY PHARMA","DRREDDY":"NIFTY PHARMA",
    "CIPLA":"NIFTY PHARMA","DIVISLAB":"NIFTY PHARMA",
    "AUROPHARMA":"NIFTY PHARMA","LUPIN":"NIFTY PHARMA",
    "TORNTPHARM":"NIFTY PHARMA","ALKEM":"NIFTY PHARMA",
    "MARUTI":"NIFTY AUTO","TATAMOTORS":"NIFTY AUTO",
    "M&M":"NIFTY AUTO","HEROMOTOCO":"NIFTY AUTO",
    "BAJAJ-AUTO":"NIFTY AUTO","EICHERMOT":"NIFTY AUTO",
    "TVSMOTORS":"NIFTY AUTO","BOSCHLTD":"NIFTY AUTO",
    "TATASTEEL":"NIFTY METAL","JSWSTEEL":"NIFTY METAL",
    "HINDALCO":"NIFTY METAL","SAIL":"NIFTY METAL",
    "NMDC":"NIFTY METAL","VEDL":"NIFTY METAL",
    "HINDUNILVR":"NIFTY FMCG","NESTLEIND":"NIFTY FMCG",
    "BRITANNIA":"NIFTY FMCG","DABUR":"NIFTY FMCG",
    "MARICO":"NIFTY FMCG","COLPAL":"NIFTY FMCG",
    "DLF":"NIFTY REALTY","GODREJPROP":"NIFTY REALTY",
    "OBEROIRLTY":"NIFTY REALTY","PHOENIXLTD":"NIFTY REALTY",
}

# Curated halal-compatible fallback used ONLY when all live Shariah sources fail.
# Expanded to ~150 symbols (was 85) to improve coverage of valid mid-cap setups.
# Every symbol here has been manually verified against Nifty500 Shariah index history.
# Banks, insurance, NBFCs, ETFs, and interest-based businesses are excluded.
_HALAL_FALLBACK_85 = {
    # ── IT & Software ─────────────────────────────────────────────────────────
    "TCS","INFY","WIPRO","HCLTECH","TECHM","LTIM","MPHASIS","COFORGE","PERSISTENT",
    "KPITTECH","TATAELXSI","TANLA","MASTEK","ROUTE",
    "NEWGEN","SAKSOFT","INTELLECT","DATAMATICS","ZENSAR",
    # ── Pharma & Healthcare ───────────────────────────────────────────────────
    "SUNPHARMA","DRREDDY","CIPLA","DIVISLAB","AUROPHARMA","LUPIN","TORNTPHARM",
    "ALKEM","IPCALAB","NATCOPHARM","GRANULES","GLENMARK","AJANTPHARM","SYNGENE",
    "LALPATHLAB","METROPOLIS","MARKSANS","LAURUSLABS","GLAND",
    # ── Auto & Auto Ancillaries ───────────────────────────────────────────────
    "MARUTI","TATAMOTORS","M&M","HEROMOTOCO","BAJAJ-AUTO","EICHERMOT","TVSMOTORS",
    "MOTHERSON","BOSCHLTD","ENDURANCE","APOLLOTYRE","BALKRISIND","SUPRAJIT","GABRIEL",
    "CEATLTD","CRAFTSMAN","TIINDIA",
    # ── FMCG & Consumer ──────────────────────────────────────────────────────
    "HINDUNILVR","NESTLEIND","BRITANNIA","DABUR","MARICO","COLPAL","EMAMILTD",
    "TATACONSUM","VBL","JUBLFOOD","KRBL","JYOTHYLAB",
    # ── Chemicals & Materials ─────────────────────────────────────────────────
    "PIDILITIND","FINEORG","GALAXYSURF","VINATIORG","NAVINFLUOR","ALKYLAMINE",
    "DEEPAKNI","TATACHEM","GHCL","ANUPAM","PCBL","AARTI","HIMADRI",
    "ATUL","NOCIL","EPIGRAL","SUDARSCHEM","LAXMICHEM","BALAMINES",
    # ── Engineering & Industrials ─────────────────────────────────────────────
    "LT","HAVELLS","VOLTAS","SIEMENS","ABB","CUMMINSIND","THERMAX","KEC",
    "POLYCAB","SCHAEFFLER","TIMKEN","GRINDWELL","PRAJ","ELGIEQUIP","KAYNES","SYRMA",
    # ── Realty ───────────────────────────────────────────────────────────────
    "DLF","GODREJPROP","OBEROIRLTY","PHOENIXLTD","SOBHA",
    # ── Logistics & Infra ────────────────────────────────────────────────────
    "CONCOR","BLUEDART","TCI","DELHIVERY","ALLCARGO","GATI","AEGISLOG",
    # ── Agri, Fertilisers & Food ─────────────────────────────────────────────
    "KAVERI","DHANUKA","UPL","PIIND","AVANTIFEED","COROMANDEL","CHAMBLFERT","GSFC",
    # ── Textiles & Apparel ───────────────────────────────────────────────────
    "PAGEIND","RAYMOND","WELSPUNIND","VARDHMAN","TRIDENT","KPRMILL",
    # ── Metals ───────────────────────────────────────────────────────────────
    "TATASTEEL","HINDALCO","JSWSTEEL","NMDC","RATNAMANI",
    # ── Consumer Durables / Retail / Misc ────────────────────────────────────
    "TITAN","TRENT","ASIANPAINT","BERGERPAINTS","DIXON","AMBER",
    # ── Energy Transition ────────────────────────────────────────────────────
    "SUZLON","INOXWIND","WEBELSOLAR","TATAPOWER","TORNTPOWER",
}
# Alias so existing code that references _HALAL_FALLBACK_85 keeps working
_HALAL_FALLBACK_150 = _HALAL_FALLBACK_85   # same set; name reflects ~150 symbols now

_YF_UNIVERSE_300 = [
    "TCS","INFY","WIPRO","HCLTECH","TECHM","LTIM","MPHASIS","COFORGE",
    "PERSISTENT","KPITTECH","TATAELXSI","ROUTE","TANLA","MASTEK",
    "NEWGEN","SAKSOFT","INTELLECT","DATAMATICS","ZENSAR",
    "SUNPHARMA","DRREDDY","CIPLA","DIVISLAB","AUROPHARMA","LUPIN",
    "TORNTPHARM","ALKEM","IPCALAB","NATCOPHARM","GRANULES","GLENMARK",
    "AJANTPHARM","LALPATHLAB","METROPOLIS","SYNGENE","MARKSANS",
    "MARUTI","TATAMOTORS","M&M","HEROMOTOCO","BAJAJ-AUTO","EICHERMOT",
    "TVSMOTORS","MOTHERSON","BOSCHLTD","ENDURANCE","APOLLOTYRE","CEATLTD",
    "BALKRISIND","SUPRAJIT","GABRIEL","CRAFTSMAN","TIINDIA",
    "HINDUNILVR","NESTLEIND","BRITANNIA","DABUR","MARICO","COLPAL",
    "EMAMILTD","TATACONSUM","VBL","JUBLFOOD","KRBL","JYOTHYLAB",
    "PIDILITIND","FINEORG","GALAXYSURF","VINATIORG","NAVINFLUOR",
    "ALKYLAMINE","DEEPAKNI","TATACHEM","GHCL","ANUPAM","PCBL",
    "AARTI","HIMADRI","EPIGRAL","ATUL","NOCIL",
    "LT","HAVELLS","VOLTAS","SIEMENS","ABB","CUMMINSIND",
    "THERMAX","KEC","POLYCAB","SCHAEFFLER","TIMKEN",
    "GRINDWELL","PRAJ","ELGIEQUIP","KAYNES","SYRMA",
    "DLF","GODREJPROP","OBEROIRLTY","PHOENIXLTD","SOBHA",
    "CONCOR","BLUEDART","TCI","DELHIVERY","ALLCARGO",
    "KAVERI","DHANUKA","UPL","PIIND","COROMANDEL",
    "PAGEIND","RAYMOND","WELSPUNIND","VARDHMAN","TRIDENT",
    "TATASTEEL","HINDALCO","JSWSTEEL","NMDC","RATNAMANI",
    "TITAN","TRENT","ASIANPAINT","BERGERPAINTS","DIXON","AMBER",
    "NTPC","TATAPOWER","TORNTPOWER","SUZLON","INOXWIND",
]

_SHARIAH_UNIVERSE_CACHE: Optional[set] = None
_SECTOR_LIVE_CACHE: dict = {}
_MACRO_REGIME_CACHE: Optional[Dict] = None
_MACRO_REGIME_LOCK = threading.Lock()
_smallcap_index_cache: dict = {}
_ROCE_CACHE_TTL_SECONDS = 86_400
_roce_cache: dict = {}


# ══════════════════════════════════════════════════════════════════════
# SECTION 2 — GOOGLE SHEETS CLIENT  (quota-safe, single-call bulk reads)
# ══════════════════════════════════════════════════════════════════════
#
# ┌─────────────────────────────────────────────────────────────────┐
# │  GOOGLE API QUOTA RULE — READ BEFORE TOUCHING THIS SECTION     │
# │                                                                 │
# │  Google enforces 300 Read requests / minute / project.         │
# │  The BHAVCOPY sheet has 2 000+ rows.                           │
# │                                                                 │
# │  ✗ WRONG — row-by-row loop = 2 000 API calls in 10 seconds     │
# │            → instant 429 RESOURCE_EXHAUSTED crash              │
# │                                                                 │
# │  ✓ RIGHT — ONE bulk call per sheet using get_all_values()      │
# │            → entire 2 000-row sheet = exactly 1 API call       │
# │                                                                 │
# │  Pattern enforced below:                                        │
# │    raw = worksheet.get_all_values()   # 1 call — all rows      │
# │    df  = pd.DataFrame(raw[1:], columns=raw[0])  # in-memory    │
# │                                                                 │
# │  Rate-limit retry: exponential backoff on 429 / APIError.      │
# │  Workbook object is cached for the entire run (one open()).    │
# └─────────────────────────────────────────────────────────────────┘

# Module-level cache — workbook opened once per GitHub Actions job run
_GS_CLIENT    = None   # authorised gspread.Client
_GS_WORKBOOK  = None   # opened Spreadsheet object
_GS_WS_CACHE  = {}     # {sheet_name: Worksheet} — avoid repeated .worksheet() calls
_GS_INIT_LOCK = threading.Lock()

_SHEETS_SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Retry config for 429 / transient errors
_GS_RETRY_ATTEMPTS = 4
_GS_RETRY_BACKOFFS = [5, 15, 45, 120]   # seconds between attempts


def _sheets_retry(fn, *args, label="sheets_call", **kwargs):
    """
    Call fn(*args, **kwargs) with exponential backoff on gspread APIError (429)
    or any transient network error.  Returns result or raises on final failure.
    """
    import gspread.exceptions as gse
    last_exc = None
    for attempt, backoff in enumerate(
        _GS_RETRY_BACKOFFS[:_GS_RETRY_ATTEMPTS], start=1
    ):
        try:
            return fn(*args, **kwargs)
        except gse.APIError as e:
            code = getattr(e, "response", None)
            code = code.status_code if code else 0
            if code == 429 or "RESOURCE_EXHAUSTED" in str(e):
                log.warning(
                    f"[{label}] Google 429 quota hit (attempt {attempt}/"
                    f"{_GS_RETRY_ATTEMPTS}) — sleeping {backoff}s ..."
                )
            else:
                log.warning(f"[{label}] gspread APIError {code}: {e} — retry {attempt}")
            last_exc = e
            time.sleep(backoff + random.uniform(0, 2))
        except Exception as e:
            log.warning(f"[{label}] transient error: {e} — retry {attempt}")
            last_exc = e
            time.sleep(backoff)
    raise last_exc


def _init_sheets_client() -> bool:
    """
    Authenticate once and open the workbook once.
    Caches both in module globals so the rest of the run pays zero overhead.
    Returns True if ready, False if not configured / auth failed.
    """
    global _GS_CLIENT, _GS_WORKBOOK
    if _GS_WORKBOOK is not None:
        return True
    with _GS_INIT_LOCK:
        if _GS_WORKBOOK is not None:   # double-checked inside lock
            return True
        if not GOOGLE_SHEET_ID or not GOOGLE_CREDS_JSON:
            log.info("Google Sheets: GOOGLE_SHEET_ID or GOOGLE_CREDS_JSON not set — skipping")
            return False
        try:
            import gspread
            from google.oauth2.service_account import Credentials
            import base64

            raw = GOOGLE_CREDS_JSON.strip()
            # Accept both raw JSON and base64-encoded JSON (common in GH Actions secrets)
            try:
                decoded    = base64.b64decode(raw).decode("utf-8")
                creds_dict = json.loads(decoded)
            except Exception:
                creds_dict = json.loads(raw)

            creds       = Credentials.from_service_account_info(creds_dict, scopes=_SHEETS_SCOPES)
            _GS_CLIENT  = gspread.authorize(creds)
            _GS_WORKBOOK = _sheets_retry(
                _GS_CLIENT.open_by_key, GOOGLE_SHEET_ID,
                label="open_workbook"
            )
            log.info(f"Google Sheets workbook opened: '{_GS_WORKBOOK.title}' ✅")
            return True
        except Exception as e:
            log.error(f"Google Sheets auth/open failed: {e}")
            return False


def _get_worksheet(tab_name: str):
    """
    Return the Worksheet for tab_name.  Uses module-level cache so
    each tab is opened with exactly ONE .worksheet() API call per run.
    Returns None if not found or not configured.
    """
    if tab_name in _GS_WS_CACHE:
        return _GS_WS_CACHE[tab_name]
    if not _init_sheets_client():
        return None
    try:
        ws = _sheets_retry(
            _GS_WORKBOOK.worksheet, tab_name,
            label=f"worksheet({tab_name})"
        )
        _GS_WS_CACHE[tab_name] = ws
        log.info(f"  Worksheet '{tab_name}' opened ✅")
        return ws
    except Exception as e:
        log.warning(f"Worksheet '{tab_name}' not found: {e}")
        log.warning(
            f"  ↳ Your workbook must have a tab named exactly '{tab_name}'. "
            f"Check spelling and case."
        )
        _GS_WS_CACHE[tab_name] = None   # cache the miss — don't retry in same run
        return None


def _bulk_read_sheet(tab_name: str) -> pd.DataFrame:
    """
    THE ONLY FUNCTION ALLOWED TO READ SHEET DATA.

    Fetches the entire worksheet in ONE API call using get_all_values().
    Row 0 = headers.  Remaining rows = data.
    Converts to a pandas DataFrame entirely in memory.

    Cost: exactly 1 Google API read request, regardless of row count.
    This is the pattern that keeps us inside the 300 req/min quota even
    for the 2 000+ row BHAVCOPY tab.

    Returns empty DataFrame if tab is missing, empty, or on error.
    """
    ws = _get_worksheet(tab_name)
    if ws is None:
        return pd.DataFrame()
    try:
        # ONE API call — fetches all rows including header
        raw = _sheets_retry(ws.get_all_values, label=f"get_all_values({tab_name})")
        if not raw or len(raw) < 2:
            log.info(f"  Sheet '{tab_name}': empty or header-only — 0 data rows")
            return pd.DataFrame()
        # FIX #2: strip leading/trailing commas and whitespace that appear when
        # a Google Sheet tab was imported from CSV (common with NSE FII/DII exports).
        # e.g. ",DATE" → "DATE",  "(₹ CRORES),SELL VALUE" → "(₹ CRORES),SELL VALUE"
        headers = [str(h).strip().lstrip(",").rstrip(",").strip().upper() for h in raw[0]]
        df      = pd.DataFrame(raw[1:], columns=headers)
        # Drop completely empty rows (all cells blank)
        df = df[~df.apply(lambda r: r.str.strip().eq("").all(), axis=1)].reset_index(drop=True)
        log.info(f"  Sheet '{tab_name}': {len(df)} data rows loaded (1 API call) ✅")
        return df
    except Exception as e:
        log.error(f"  Sheet '{tab_name}' bulk read failed: {e}")
        return pd.DataFrame()


# ── Dedicated reader for each of the 5 input tabs ──────────────────
# Each function reads ONLY its own tab.  Nothing is shared or mixed.

def _read_sheet_bhavcopy() -> pd.DataFrame:
    """
    Read Tab 1 — BHAVCOPY.
    Required columns (case-insensitive in sheet, uppercased internally):
      SYMBOL | OPEN | HIGH | LOW | CLOSE | VOLUME | TURNOVER_LAKHS
    Optional: SERIES  — if present, only EQ rows are kept.

    ⚠️  This tab can have 2 000+ rows.
    Fetched in 1 API call. Never iterated row-by-row.
    """
    return _bulk_read_sheet(SHEET_BHAVCOPY)


def _read_sheet_fii_dii() -> pd.DataFrame:
    """
    Read Tab 2 — FII_DII.
    Required columns: DATE | FII_NET_CR | DII_NET_CR
    Values in ₹ crore (positive = buying, negative = selling).
    Newest date should be the LAST row.  Only the last row is used.
    """
    return _bulk_read_sheet(SHEET_FII_DII)


def _read_sheet_insider() -> pd.DataFrame:
    """
    Read Tab 3 — INSIDER.
    Required columns: SYMBOL | SHARES | DATE | TYPE
    Optional:         PERSON | VALUE_LAKHS
    TYPE must contain 'buy'/'purchase'/'acqui' (case-insensitive) to be counted.
    Sell / pledge rows are silently ignored.
    """
    return _bulk_read_sheet(SHEET_INSIDER)


def _read_sheet_filings() -> pd.DataFrame:
    """
    Read Tab 4 — FILINGS.
    Required columns: SYMBOL | DATE | SUBJECT
    Optional:         SENTIMENT  (positive / negative / neutral)
    If SENTIMENT is absent, keyword scoring on SUBJECT is used automatically.
    """
    return _bulk_read_sheet(SHEET_FILINGS)


def _read_sheet_earnings() -> pd.DataFrame:
    """
    Read Tab 5 — EARNINGS.
    Required columns: SYMBOL | RESULT_DATE
    Optional:         PURPOSE  (results / dividend — other values ignored)
    If PURPOSE is absent, all rows are treated as result dates.
    """
    return _bulk_read_sheet(SHEET_EARNINGS)


def _sheets_configured() -> bool:
    """True if both GOOGLE_SHEET_ID and GOOGLE_CREDS_JSON are set."""
    return bool(GOOGLE_SHEET_ID and GOOGLE_CREDS_JSON)


# ══════════════════════════════════════════════════════════════════════
# SECTION 3 — HALAL / SHARIAH UNIVERSE
# ══════════════════════════════════════════════════════════════════════

def _fetch_shariah_csv() -> set:
    """
    Fetch live Nifty 500 Shariah constituents from NSE/Nifty Indices.
    Tries multiple URL patterns, handles Cloudflare/redirects, validates
    content carefully, and falls back to NSE JSON API before giving up.
    Returns empty set if ALL sources fail — caller decides on fallback.
    """
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/csv,text/plain,application/octet-stream,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.niftyindices.com/",
        "Connection": "keep-alive",
        "DNT": "1",
    })

    # Prime cookies from main site
    try:
        sess.get("https://www.niftyindices.com/", timeout=15)
        time.sleep(1)
    except Exception:
        pass

    urls = [
        # Primary (Nifty Indices — most reliable as of 2025-26)
        "https://www.niftyindices.com/IndexConstituents/ind_nifty500shariah.csv",
        # NSE legacy archives
        "https://archives.nseindia.com/content/indices/ind_nifty500shariah.csv",
        # NSE alternate subdomain
        "https://www.nseindia.com/content/indices/ind_nifty500shariah.csv",
    ]
    # Expanded header keywords including newer NSE column names
    VALID_HEADERS = ("symbol", "company", "ticker", "isin", "scrip", "name", "security")

    for url in urls:
        try:
            resp = sess.get(url, timeout=25, allow_redirects=True)
            if resp.status_code != 200:
                log.debug(f"Shariah CSV {url}: HTTP {resp.status_code}")
                continue

            # Content-length guard: a valid CSV is always >200 chars
            text = resp.text.lstrip()
            if len(text) < 200:
                log.debug(f"Shariah CSV {url}: body too short ({len(text)} chars) — likely Cloudflare block")
                continue

            # Header keyword check (don't reject on mime-type alone — NSE sends inconsistent types)
            first_line = text[:200].lower()
            if not any(kw in first_line for kw in VALID_HEADERS):
                log.debug(f"Shariah CSV {url}: no valid header keyword in first 200 chars")
                continue

            df = pd.read_csv(io.StringIO(text))
            df.columns = df.columns.str.strip().str.upper()

            # Flexible symbol column detection
            sym_col = next(
                (c for c in df.columns
                 if any(k in c for k in ("SYMBOL","TICKER","SCRIP","SECURITY","NAME","COMPANY"))),
                None
            )
            if sym_col is None:
                log.warning(f"Shariah CSV {url}: columns {list(df.columns)} — no symbol column found")
                continue

            # Filter out non-stock rows (index names, header artifacts, totals)
            syms = set()
            for s in df[sym_col]:
                if pd.isna(s):
                    continue
                sym = str(s).strip().upper()
                if sym and not sym.startswith(("INDEX","NIFTY","TOTAL","DATE","SYMBOL","SL","SR")):
                    syms.add(sym)

            if len(syms) >= 100:
                log.info(f"Shariah CSV loaded LIVE: {len(syms)} symbols from {url} ✅")
                return syms
            else:
                log.warning(f"Shariah CSV {url}: only {len(syms)} symbols — suspicious, skipping")

        except Exception as e:
            log.debug(f"Shariah CSV {url}: {e}")

    # ── Fallback: NSE JSON API ────────────────────────────────────────────────
    try:
        nse_sess = nse_session()
        data = _nse_json(nse_sess, "https://www.nseindia.com/api/equity-stockIndices",
                         params={"index": "NIFTY500 SHARIAH"}, timeout=15)
        if isinstance(data, dict) and "data" in data:
            syms = {
                str(r.get("symbol","")).strip().upper()
                for r in data["data"]
                if str(r.get("symbol","")).strip()
            }
            if len(syms) >= 100:
                log.info(f"Shariah JSON API loaded: {len(syms)} symbols ✅")
                return syms
            log.debug(f"Shariah JSON API: only {len(syms)} symbols")
    except Exception as e:
        log.debug(f"Shariah JSON API failed: {e}")

    log.warning("All live Shariah sources failed — will use curated fallback")
    return set()   # caller (get_halal_universe) decides on fallback


def _load_shariah_from_db() -> set:
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("SELECT symbol, cached_date FROM halal_cache LIMIT 1")
        row = cur.fetchone()
        if row:
            cached_date = datetime.strptime(row[1], "%Y-%m-%d").date()
            if (datetime.today().date() - cached_date).days <= 7:
                cur.execute("SELECT symbol FROM halal_cache")
                syms = {r[0] for r in cur.fetchall()}
                con.close()
                return syms
        con.close()
    except Exception:
        pass
    return set()


def _save_shariah_to_db(syms: set):
    try:
        today = datetime.today().strftime("%Y-%m-%d")
        con = sqlite3.connect(DB_PATH)
        con.execute("DELETE FROM halal_cache")
        con.executemany(
            "INSERT OR REPLACE INTO halal_cache (symbol, cached_date) VALUES (?,?)",
            [(s, today) for s in syms]
        )
        con.commit()
        con.close()
    except Exception as e:
        log.debug(f"Shariah DB save: {e}")


def get_halal_universe() -> set:
    """
    Returns the active halal universe.  Priority:
      1. In-memory cache (free)
      2. SQLite cache (7-day TTL, survives between GitHub Actions jobs)
      3. Live Shariah CSV / NSE JSON API fetch
      4. Curated fallback (~150 symbols) — ONLY if live fetch returns < 100 symbols

    The >= 100 guard prevents a partial/malformed response from silently replacing
    a good cached universe with a tiny set that looks valid but isn't.
    """
    global _SHARIAH_UNIVERSE_CACHE
    if _SHARIAH_UNIVERSE_CACHE is not None:
        return _SHARIAH_UNIVERSE_CACHE

    # Try SQLite cache first (7-day TTL)
    cached = _load_shariah_from_db()
    if cached and len(cached) >= 100:
        log.info(f"Halal universe from SQLite cache: {len(cached)} symbols")
        _SHARIAH_UNIVERSE_CACHE = cached
        return cached

    # Try live fetch
    live = _fetch_shariah_csv()
    if live and len(live) >= 100:
        _save_shariah_to_db(live)
        _SHARIAH_UNIVERSE_CACHE = live
        log.info(f"Halal universe LIVE: {len(live)} symbols")
        return live

    # Only fall back to curated list if live truly failed
    log.warning(
        f"Shariah live fetch returned {len(live)} symbols (need ≥100) — "
        f"using curated fallback ({len(_HALAL_FALLBACK_85)} symbols)"
    )
    _SHARIAH_UNIVERSE_CACHE = _HALAL_FALLBACK_85
    return _HALAL_FALLBACK_85


def is_halal(symbol: str) -> bool:
    sym_upper = symbol.upper()
    # Hard exclusion list first (banks, insurance, ETFs, etc.)
    if sym_upper in HALAL_EXCLUDED:
        return False
    # Keyword exclusion (catches anything with "bank", "finance", "nifty", etc.)
    sl = symbol.lower()
    if any(kw in sl for kw in HALAL_KW):
        return False
    # FIX #1 (critical): the old code returned True for ALL symbols when the
    # Shariah CSV failed and the fallback set was used. This let 1,117 stocks
    # through instead of ~85, making the halal filter effectively dead and
    # allowing non-halal stocks like RELIANCE into the output.
    # Fix: always check membership — if the symbol isn't in the fallback set
    # it is NOT considered halal. No short-circuit.
    universe = get_halal_universe()
    return sym_upper in universe


# ══════════════════════════════════════════════════════════════════════
# SECTION 4 — SECTOR LOOKUP
# ══════════════════════════════════════════════════════════════════════

def get_sector(sym: str) -> str:
    sym_upper = sym.upper()
    static = SYMBOL_SECTOR.get(sym_upper)
    if static:
        return static
    if sym_upper in _SECTOR_LIVE_CACHE:
        return _SECTOR_LIVE_CACHE[sym_upper]
    sector = _lookup_sector_nse(sym_upper)
    _SECTOR_LIVE_CACHE[sym_upper] = sector
    return sector


def _lookup_sector_nse(sym: str) -> str:
    try:
        sess = nse_session()
        data = _nse_json(sess, "https://www.nseindia.com/api/quote-equity",
                         params={"symbol": sym}, timeout=10)
        if isinstance(data, dict):
            info = data.get("info", data)
            industry = (info.get("industry") or info.get("macro") or
                        info.get("basicIndustry") or "")
            if industry:
                il = industry.lower()
                if any(k in il for k in ("pharma","health","drug","biotech")):
                    return "NIFTY PHARMA"
                if any(k in il for k in ("software","it services","technology","computer")):
                    return "NIFTY IT"
                if any(k in il for k in ("auto","vehicle","tyre","ancillar")):
                    return "NIFTY AUTO"
                if any(k in il for k in ("fmcg","consumer","food","beverag")):
                    return "NIFTY FMCG"
                if any(k in il for k in ("metal","steel","alumin","copper","mining")):
                    return "NIFTY METAL"
                if any(k in il for k in ("energy","power","oil","gas","petro")):
                    return "NIFTY ENERGY"
                if any(k in il for k in ("realty","real estate","construct","housing")):
                    return "NIFTY REALTY"
    except Exception as e:
        log.debug(f"Sector lookup {sym}: {e}")
    return "DIVERSIFIED"


# ══════════════════════════════════════════════════════════════════════
# SECTION 5 — NSE SESSION & JSON HELPERS
# ══════════════════════════════════════════════════════════════════════

def nse_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
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
            s.get(url, timeout=15)
            time.sleep(1.0)
        except Exception:
            pass
    return s


def _nse_json(sess: requests.Session, url: str, params: dict = None, timeout: int = 15):
    resp = sess.get(url, params=params, timeout=timeout)
    body = resp.text.strip()
    if not body or body.startswith("<"):
        raise ValueError(
            f"NSE returned empty/HTML body for {url} (status={resp.status_code})"
        )
    return resp.json()


# ══════════════════════════════════════════════════════════════════════
# SECTION 6 — SQLITE DATABASE
# ══════════════════════════════════════════════════════════════════════

def _init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)
    try:
        result = con.execute("PRAGMA journal_mode=WAL").fetchone()
        if not (result and result[0].upper() == "WAL"):
            con.execute("PRAGMA journal_mode=DELETE")
    except Exception:
        pass
    con.execute("PRAGMA busy_timeout=5000")
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS eod_cache (
            symbol        TEXT NOT NULL,
            trade_date    TEXT NOT NULL,
            open          REAL,
            high          REAL,
            low           REAL,
            close         REAL NOT NULL,
            volume        REAL,
            turnover_lakhs REAL,
            data_quality  TEXT NOT NULL,
            fetched_at    TEXT NOT NULL,
            PRIMARY KEY (symbol, trade_date)
        );
        CREATE TABLE IF NOT EXISTS halal_cache (
            symbol        TEXT PRIMARY KEY,
            cached_date   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS roce_cache (
            symbol        TEXT PRIMARY KEY,
            value         REAL,
            label         TEXT NOT NULL,
            fetched_at    TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS positions (
            symbol        TEXT PRIMARY KEY,
            entry_price   REAL NOT NULL,
            entry_date    TEXT NOT NULL,
            initial_t3    REAL NOT NULL,
            peak_price    REAL NOT NULL,
            trailing_stop REAL NOT NULL,
            be_triggered  INTEGER DEFAULT 0,
            updated_at    TEXT NOT NULL
        );
    """)
    con.commit()
    con.close()


def _db_get_eod(symbol: str, trade_date: str) -> Optional[dict]:
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute(
            "SELECT open,high,low,close,volume,turnover_lakhs,data_quality "
            "FROM eod_cache WHERE symbol=? AND trade_date=?",
            (symbol.upper(), trade_date)
        )
        row = cur.fetchone()
        con.close()
        if row:
            return dict(zip(["open","high","low","close","volume",
                              "turnover_lakhs","data_quality"], row))
    except Exception as e:
        log.debug(f"DB read {symbol}: {e}")
    return None


def _db_put_eod(symbol: str, trade_date: str, rec: dict):
    dq = rec.get("data_quality")
    if dq is not None and str(dq).strip().upper() == "STALE":
        return
    try:
        con = sqlite3.connect(DB_PATH, timeout=5)
        con.execute(
            """INSERT OR REPLACE INTO eod_cache
               (symbol,trade_date,open,high,low,close,volume,turnover_lakhs,data_quality,fetched_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (symbol.upper(), trade_date,
             rec.get("open"), rec.get("high"), rec.get("low"),
             rec["close"], rec.get("volume"), rec.get("turnover_lakhs"),
             rec.get("data_quality","UNKNOWN"), datetime.now().isoformat())
        )
        con.commit()
        con.close()
    except Exception as e:
        log.debug(f"DB write {symbol}: {e}")


def _db_get_roce(symbol: str):
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("SELECT value, label, fetched_at FROM roce_cache WHERE symbol=?",
                    (symbol.upper(),))
        row = cur.fetchone()
        con.close()
        if row:
            return row[0], row[1], float(row[2]) if row[2] else 0.0
    except Exception:
        pass
    return None


def _db_put_roce(symbol: str, value, label: str, fetched_at: float):
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute(
            "INSERT OR REPLACE INTO roce_cache (symbol, value, label, fetched_at) "
            "VALUES (?,?,?,?)",
            (symbol.upper(), value, label, str(fetched_at))
        )
        con.commit()
        con.close()
    except Exception:
        pass


def _get_position(symbol: str) -> Optional[dict]:
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute(
            "SELECT entry_price,entry_date,initial_t3,peak_price,trailing_stop,be_triggered "
            "FROM positions WHERE symbol=?", (symbol.upper(),)
        )
        row = cur.fetchone()
        con.close()
        if row:
            return dict(zip(["entry_price","entry_date","initial_t3",
                              "peak_price","trailing_stop","be_triggered"], row))
    except Exception:
        pass
    return None


def _put_position(symbol: str, entry_price: float, entry_date: str,
                  initial_t3: float, peak_price: float,
                  trailing_stop: float, be_triggered: int = 0):
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute(
            "INSERT OR REPLACE INTO positions "
            "(symbol,entry_price,entry_date,initial_t3,peak_price,trailing_stop,be_triggered,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (symbol.upper(), entry_price, entry_date, initial_t3,
             peak_price, trailing_stop, be_triggered,
             datetime.today().isoformat())
        )
        con.commit()
        con.close()
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
# SECTION 7 — BHAVCOPY DATA (NSE → Sheets → yfinance)
# ══════════════════════════════════════════════════════════════════════

def get_last_trading_day():
    d = datetime.today()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%d%m%Y"), d.strftime("%Y-%m-%d")


def _month_abbr(mm: str) -> str:
    m = {"01":"JAN","02":"FEB","03":"MAR","04":"APR","05":"MAY","06":"JUN",
         "07":"JUL","08":"AUG","09":"SEP","10":"OCT","11":"NOV","12":"DEC"}
    return m.get(mm, mm)


def download_bhavcopy(date_str: str) -> pd.DataFrame:
    dd, mm, yyyy = date_str[:2], date_str[2:4], date_str[4:]
    mon      = _month_abbr(mm)
    yyyymmdd = f"{yyyy}{mm}{dd}"
    urls = [
        (f"https://nsearchives.nseindia.com/content/cm/"
         f"BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip", True),
        (f"https://nsearchives.nseindia.com/products/content/"
         f"sec_bhavdata_full_{date_str}.csv", False),
        (f"https://archives.nseindia.com/content/historical/EQUITIES/"
         f"{yyyy}/{mon}/cm{date_str}bhav.csv.zip", True),
    ]
    sess = nse_session()
    for url, is_zip in urls:
        try:
            resp = sess.get(url, timeout=30)
            if resp.status_code == 200 and len(resp.content) > 1000:
                df = (pd.read_csv(io.BytesIO(resp.content), compression="zip")
                      if is_zip
                      else pd.read_csv(io.BytesIO(resp.content)))
                df.columns = df.columns.str.strip()
                if len(df) > 100:
                    return df
        except Exception as e:
            log.warning(f"Bhavcopy URL failed: {e}")
            time.sleep(1)
    raise Exception(f"All bhavcopy URLs failed for {date_str}")


def clean_bhavcopy(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = df.columns.str.strip().str.upper()
    col_maps = [
        {"TCKRSYMB":"symbol","SCTYSRS":"series","OPNPRIC":"open","HGHPRIC":"high",
         "LWPRIC":"low","CLSPRIC":"close","TTLTRADGVOL":"volume","TTLTRFVAL":"turnover"},
        {"SYMBOL":"symbol","SERIES":"series","OPEN":"open","HIGH":"high","LOW":"low",
         "CLOSE":"close","TOTTRDQTY":"volume","TOTTRDVAL":"turnover"},
        {"SYMBOL":"symbol","SERIES":"series","OPEN_PRICE":"open","HIGH_PRICE":"high",
         "LOW_PRICE":"low","CLOSE_PRICE":"close","TTL_TRD_QNTY":"volume",
         "TURNOVER_LACS":"turnover_lakhs"},
    ]
    matched = False
    for mapping in col_maps:
        if all(k in df.columns for k in mapping.keys()):
            df = df.rename(columns=mapping)
            matched = True
            break
    if not matched:
        log.warning(f"Bhavcopy: unrecognised columns: {list(df.columns[:8])}")
        return pd.DataFrame()
    if "series" in df.columns:
        df = df[df["series"].astype(str).str.strip() == "EQ"].copy()
    if "turnover_lakhs" not in df.columns:
        if "turnover" in df.columns:
            df["turnover_lakhs"] = pd.to_numeric(df["turnover"], errors="coerce").fillna(0) / 100_000
        else:
            df["turnover_lakhs"] = 0
    for col in ["open","high","low","close","volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[["symbol","open","high","low","close","volume","turnover_lakhs"]].reset_index(drop=True)
    df = df[df["close"] > 0].dropna(subset=["close"])
    df["data_quality"] = "EOD_FRESH"
    return df


# ── v7.0: Load Bhavcopy from Google Sheets (Tab 1 — BHAVCOPY) ──────

def load_bhavcopy_from_sheets() -> pd.DataFrame:
    """
    Read Tab 1 — BHAVCOPY — in ONE bulk API call.

    Expected tab name  : BHAVCOPY  (exact, case-sensitive)
    Required columns   : SYMBOL | OPEN | HIGH | LOW | CLOSE | VOLUME
    Optional columns   : TURNOVER_LAKHS | SERIES

    Column matching is flexible (any order, any extra columns ignored).
    If SERIES column exists, only EQ rows are kept.
    If TURNOVER_LAKHS is absent, it is computed from VOLUME × CLOSE.

    API cost: 1 read request (entire 2 000+ row sheet in one HTTP call).
    Returns DataFrame with data_quality='SHEETS_EOD', or empty on failure.
    """
    if not _sheets_configured():
        return pd.DataFrame()

    log.info(f"Reading Tab 1 (BHAVCOPY) — single bulk API call ...")
    raw = _read_sheet_bhavcopy()   # ← exactly 1 API call inside here
    if raw.empty:
        log.info("  BHAVCOPY tab: empty or not found")
        return pd.DataFrame()

    # ── Flexible column mapping ──────────────────────────────────────
    # Columns are already uppercased by _bulk_read_sheet.
    # We try obvious exact names first, then substring match.
    col_map = {}
    targets = {
        "symbol":         ["SYMBOL", "SCRIP", "TICKER"],
        "open":           ["OPEN", "OPEN_PRICE", "OPNPRIC"],
        "high":           ["HIGH", "HIGH_PRICE", "HGHPRIC"],
        "low":            ["LOW",  "LOW_PRICE",  "LWPRIC"],
        "close":          ["CLOSE","CLOSE_PRICE","CLSPRIC","LTP"],
        "volume":         ["VOLUME","TOTTRDQTY","TTLTRADGVOL","QTY"],
        "turnover_lakhs": ["TURNOVER_LAKHS","TURNOVER_LACS","TOTTRDVAL","TTLTRFVAL"],
        "series":         ["SERIES","SCTYSRS"],
    }
    for internal, candidates in targets.items():
        for cand in candidates:
            if cand in raw.columns:
                col_map[cand] = internal
                break
        else:
            # substring fallback
            matched = next(
                (c for c in raw.columns
                 if any(sub in c for sub in candidates[:2])),
                None
            )
            if matched:
                col_map[matched] = internal

    df = raw.rename(columns=col_map)

    required = {"symbol", "open", "high", "low", "close", "volume"}
    missing  = required - set(df.columns)
    if missing:
        log.warning(
            f"  BHAVCOPY tab missing required columns: {missing}. "
            f"Available: {list(raw.columns[:10])}"
        )
        return pd.DataFrame()

    # ── EQ series filter ────────────────────────────────────────────
    if "series" in df.columns:
        before = len(df)
        df = df[df["series"].astype(str).str.strip().str.upper() == "EQ"].copy()
        log.info(f"  BHAVCOPY: {before} total rows → {len(df)} EQ rows after series filter")
    else:
        log.info(f"  BHAVCOPY: no SERIES column — treating all {len(df)} rows as EQ")

    # ── Numeric coercion ─────────────────────────────────────────────
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # ── Derived turnover ─────────────────────────────────────────────
    if "turnover_lakhs" in df.columns:
        df["turnover_lakhs"] = pd.to_numeric(df["turnover_lakhs"], errors="coerce")
        # NSE bhavcopy sometimes stores turnover in actual rupees (not lakhs)
        # Detect: if median turnover per row > 1e7 it's in rupees — convert
        median_t = df["turnover_lakhs"].median()
        if median_t > 1_000_000:
            df["turnover_lakhs"] = df["turnover_lakhs"] / 100_000
            log.info("  BHAVCOPY: auto-converted TURNOVER from ₹ to Lakhs")
    else:
        df["turnover_lakhs"] = (df["volume"] * df["close"]) / 100_000
        log.info("  BHAVCOPY: TURNOVER_LAKHS derived from VOLUME × CLOSE")

    df["symbol"]       = df["symbol"].astype(str).str.strip().str.upper()
    df["data_quality"] = "SHEETS_EOD"

    keep_cols = ["symbol","open","high","low","close","volume","turnover_lakhs","data_quality"]
    df = df[[c for c in keep_cols if c in df.columns]]
    df = df[df["close"] > 0].dropna(subset=["close"]).reset_index(drop=True)

    log.info(f"  BHAVCOPY: {len(df)} clean EQ records ready ✅")
    return df


def build_yfinance_universe() -> pd.DataFrame:
    """Batch yfinance fallback (~300 halal-compatible stocks). Last resort only."""
    try:
        import yfinance as yf
    except ImportError:
        return pd.DataFrame()

    universe = get_halal_universe()
    candidates = ([s for s in _YF_UNIVERSE_300 if s.upper() in universe]
                  if universe is not _HALAL_FALLBACK_85
                  else [s for s in _YF_UNIVERSE_300 if is_halal(s)])
    if len(candidates) < 50:
        candidates = [s for s in _YF_UNIVERSE_300 if is_halal(s)]

    log.info(f"yfinance batch fallback: {len(candidates)} halal candidates")
    _, trade_date = get_last_trading_day()

    CHUNK_SIZE  = 50
    MIN_CHUNK   = 10
    BACKOFF     = [3, 12, 45]
    consec_fail = 0
    batch_close: dict = {}
    batch_vol:   dict = {}

    chunks = [candidates[i:i+CHUNK_SIZE] for i in range(0, len(candidates), CHUNK_SIZE)]
    for chunk_idx, chunk in enumerate(chunks, 1):
        # Adaptive halving: after 2 consecutive failures, halve chunk size
        if consec_fail >= 2 and len(chunk) > MIN_CHUNK:
            half = max(MIN_CHUNK, len(chunk) // 2)
            log.warning(f"yfinance: {consec_fail} consecutive failures — "
                        f"halving chunk {len(chunk)}→{half} (chunk {chunk_idx})")
            sub_chunks = [chunk[i:i+half] for i in range(0, len(chunk), half)]
        else:
            sub_chunks = [chunk]

        for sub_chunk in sub_chunks:
          tickers = " ".join(f"{s}.NS" for s in sub_chunk)
          for attempt, backoff in enumerate(BACKOFF, 1):
              try:
                  raw = yf.download(tickers, period="2d", interval="1d",
                                    progress=False, auto_adjust=False, group_by="ticker")
                  if raw.empty:
                      consec_fail += 1
                      time.sleep(backoff + random.uniform(0, 2))
                      continue
                  for sym in sub_chunk:
                      try:
                          tk = f"{sym}.NS"
                          sub = (raw[tk] if hasattr(raw.columns,"levels") and
                                 tk in raw.columns.get_level_values(0) else raw)
                          sub.columns = [c.lower() for c in sub.columns]
                          cs = sub["close"].dropna() if "close" in sub.columns else pd.Series(dtype=float)
                          vs = sub["volume"].dropna() if "volume" in sub.columns else pd.Series(dtype=float)
                          if not cs.empty:
                              batch_close[sym] = float(cs.iloc[-1])
                              batch_vol[sym]   = float(vs.iloc[-1]) if not vs.empty else 0.0
                      except Exception:
                          continue
                  consec_fail = 0
                  time.sleep(1)
                  break
              except Exception as e:
                  consec_fail += 1
                  time.sleep(backoff + random.uniform(0, 2))

    records = []
    for sym in candidates:
        close = batch_close.get(sym, 0.0)
        vol   = batch_vol.get(sym, 0.0)
        if close > 0:
            records.append({
                "symbol":         sym,
                "open":           close, "high": close, "low": close,
                "close":          round(close, 2),
                "volume":         vol,
                "turnover_lakhs": round((vol * close) / 100_000, 2),
                "data_quality":   "EOD_FRESH",
            })

    log.info(f"yfinance batch complete: {len(records)}/{len(candidates)} symbols")
    return pd.DataFrame(records) if records else pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════
# SECTION 8 — HISTORICAL OHLCV (NSE → yfinance)
# ══════════════════════════════════════════════════════════════════════

def validate_no_lookahead(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "date" not in df.columns:
        return df
    df = df.sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)
    today = pd.Timestamp(datetime.today().date())
    return df[df["date"] <= today].copy()


def fetch_history_nse(symbol: str, days: int = 300,
                      sess: "requests.Session | None" = None) -> pd.DataFrame:
    end   = datetime.today()
    start = end - timedelta(days=days + 50)
    if sess is None:
        sess = nse_session()
    params = {
        "symbol": symbol, "series": "[\"EQ\"]",
        "from": start.strftime("%d-%m-%Y"), "to": end.strftime("%d-%m-%Y"),
    }
    try:
        data = _nse_json(sess, "https://www.nseindia.com/api/historical/cm/equity",
                         params=params, timeout=20)
        records = data.get("data", []) if isinstance(data, dict) else []
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records).rename(columns={
            "CH_TIMESTAMP":"date","CH_OPENING_PRICE":"open",
            "CH_TRADE_HIGH_PRICE":"high","CH_TRADE_LOW_PRICE":"low",
            "CH_CLOSING_PRICE":"close","CH_TOT_TRADED_QTY":"volume",
        })
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        for c in ["open","high","low","close","volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df[["date","open","high","low","close","volume"]].dropna()
    except Exception as e:
        log.debug(f"NSE history {symbol}: {e}")
        return pd.DataFrame()


def fetch_history_yfinance(symbol: str, days: int = 300) -> pd.DataFrame:
    try:
        import yfinance as yf
        end   = datetime.today()
        start = end - timedelta(days=days + 50)
        df    = yf.download(f"{symbol}.NS", start=start, end=end,
                            progress=False, auto_adjust=False)
        if df.empty:
            return pd.DataFrame()
        df = df.reset_index()
        if hasattr(df.columns, "levels"):
            df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                          for c in df.columns]
        else:
            df.columns = [c.lower() if isinstance(c, str) else str(c).lower()
                          for c in df.columns]
        df = df.rename(columns={"date":"date","open":"open","high":"high",
                                 "low":"low","close":"close","volume":"volume"})
        if "close" not in df.columns and "adj close" in df.columns:
            df = df.rename(columns={"adj close":"close"})
        df["date"] = pd.to_datetime(df["date"])
        return df[["date","open","high","low","close","volume"]].dropna()
    except Exception as e:
        log.debug(f"yfinance history {symbol}: {e}")
        return pd.DataFrame()


def fetch_history(symbol: str, days: int = 300,
                  sess: "requests.Session | None" = None) -> pd.DataFrame:
    df = fetch_history_nse(symbol, days, sess=sess)
    if len(df) < CFG["min_hist_bars"]:
        df = fetch_history_yfinance(symbol, days)
    return validate_no_lookahead(df)


# ══════════════════════════════════════════════════════════════════════
# SECTION 9 — FII / DII DATA (NSE → Sheets → yfinance proxy)
# Sheet 2: FII_DII | Columns: DATE | FII_NET_CR | DII_NET_CR
# ══════════════════════════════════════════════════════════════════════

def _load_fii_dii_from_sheets() -> Optional[dict]:
    """
    Read Tab 2 — FII_DII — in ONE bulk API call.

    Expected tab name  : FII_DII  (exact, case-sensitive)
    Required columns   : DATE | FII_NET_CR | DII_NET_CR
    Values             : ₹ crore — positive = buying, negative = selling

    Populate daily after 4 PM from NSE or Moneycontrol.
    Append new rows — script always uses the LAST row (most recent date).

    API cost: 1 read request.
    Returns scored dict compatible with assemble_result(), or None if unavailable.
    """
    if not _sheets_configured():
        return None

    log.info(f"Reading Tab 2 (FII_DII) — single bulk API call ...")
    df = _read_sheet_fii_dii()   # ← exactly 1 API call
    if df.empty:
        log.info("  FII_DII tab: empty or not found")
        return None

    # ── Locate FII and DII columns ───────────────────────────────────
    # FIX #2b: broadened matching to handle NSE standard import artifacts.
    # NSE FII/DII CSV has columns like: "BUY VALUE (₹ CRORES)", "SELL VALUE (₹ CRORES)"
    # after import these may become: ",BUY VALUE", "(₹ CRORES),SELL VALUE" etc.
    # Strategy: prefer NET columns; fall back to any column containing FII/DII keyword;
    # if sheet uses BUY/SELL columns, derive net = BUY - SELL downstream.
    fii_col = next(
        (c for c in df.columns if "FII" in c and any(k in c for k in ("NET","BUY","VALUE","CR"))),
        next((c for c in df.columns if "FII" in c), None)
    )
    dii_col = next(
        (c for c in df.columns if "DII" in c and any(k in c for k in ("NET","BUY","VALUE","CR"))),
        next((c for c in df.columns if "DII" in c), None)
    )
    # For NSE standard format: BUY VALUE - SELL VALUE = NET
    fii_buy_col  = next((c for c in df.columns if "FII" in c and "BUY" in c), None)
    fii_sell_col = next((c for c in df.columns if "FII" in c and "SELL" in c), None)
    dii_buy_col  = next((c for c in df.columns if "DII" in c and "BUY" in c), None)
    dii_sell_col = next((c for c in df.columns if "DII" in c and "SELL" in c), None)

    if not fii_col and not (fii_buy_col and fii_sell_col):
        log.warning(
            f"  FII_DII tab: FII column not found. "
            f"Expected FII_NET_CR or FII BUY/SELL columns. Got: {list(df.columns)}"
        )
        return None
    if not dii_col and not (dii_buy_col and dii_sell_col):
        log.warning(
            f"  FII_DII tab: DII column not found. "
            f"Expected DII_NET_CR or DII BUY/SELL columns. Got: {list(df.columns)}"
        )
        return None

    # Use the last non-empty row
    df_valid = df[df[fii_col].astype(str).str.strip().ne("")]
    if df_valid.empty:
        log.warning("  FII_DII tab: all FII value cells are empty")
        return None

    def _parse_cr(cell) -> float:
        """Strip currency symbols, commas, brackets, units and return float crore value."""
        s = str(cell).replace(",","").replace("₹","").replace("(","").replace(")","")
        s = s.replace("CRORES","").replace("CR","").replace(" ","").strip()
        try:
            return float(s or 0)
        except ValueError:
            return 0.0

    try:
        row = df_valid.iloc[-1]
        # FIX #2b continued: derive net from BUY-SELL if a direct NET column is absent
        if fii_col:
            fii_net = _parse_cr(row[fii_col])
        else:
            fii_net = _parse_cr(row[fii_buy_col]) - _parse_cr(row[fii_sell_col])
        if dii_col:
            dii_net = _parse_cr(row[dii_col])
        else:
            dii_net = _parse_cr(row[dii_buy_col]) - _parse_cr(row[dii_sell_col])
    except Exception as e:
        log.warning(f"  FII_DII tab parse error on last row: {e}")
        return None

    # ── Score ─────────────────────────────────────────────────────────
    both_buy  = fii_net > 0 and dii_net > 0
    fii_buy   = fii_net > 0
    dii_buy   = dii_net > 0
    both_sell = fii_net < 0 and dii_net < 0

    if both_buy:    score = 30; label = "🟢 FII+DII BUYING"
    elif fii_buy:   score = 22; label = "✅ FII BUYING"
    elif dii_buy:   score = 18; label = "✅ DII BUYING"
    elif both_sell: score = 5;  label = "🔴 FII+DII SELLING"
    else:           score = 12; label = "↔ MIXED"

    # Magnitude bonus: every ₹1 000 Cr of combined flow adds 1 pt (cap 5)
    mag_bonus = min(5, int((abs(fii_net) + abs(dii_net)) / 1000))
    score     = min(30, score + (mag_bonus if fii_buy else 0))

    log.info(
        f"  FII_DII: FII ₹{fii_net:+,.0f} Cr | DII ₹{dii_net:+,.0f} Cr "
        f"→ {score}/30 [{label}] ✅"
    )
    return {
        "fii_net": round(fii_net, 0),
        "dii_net": round(dii_net, 0),
        "score":   score,
        "label":   label,
        "detail":  f"FII ₹{fii_net:+,.0f} Cr | DII ₹{dii_net:+,.0f} Cr [SHEETS Tab 2]",
    }


def fetch_fii_dii() -> dict:
    neutral = {"fii_net":0,"dii_net":0,"score":15,"label":"↔ MIXED",
               "detail":"FII/DII data unavailable — neutral score"}

    # ── 1. NSE live ──────────────────────────────────────────────────
    if not FORCE_SHEETS and not FORCE_YFINANCE:
        try:
            sess = nse_session()
            data = _nse_json(sess, "https://www.nseindia.com/api/fiidiiTradeReact")
            if data:
                row     = data[0] if isinstance(data, list) else data
                fii_net = float(str(row.get("fiiNet", row.get("FII_NET_PURCHASE_SALES", 0))).replace(",",""))
                dii_net = float(str(row.get("diiNet", row.get("DII_NET_PURCHASE_SALES", 0))).replace(",",""))
                both_buy  = fii_net > 0 and dii_net > 0
                fii_buy   = fii_net > 0
                dii_buy   = dii_net > 0
                both_sell = fii_net < 0 and dii_net < 0
                if both_buy:    score=30; label="🟢 FII+DII BUYING"
                elif fii_buy:   score=22; label="✅ FII BUYING"
                elif dii_buy:   score=18; label="✅ DII BUYING"
                elif both_sell: score=5;  label="🔴 FII+DII SELLING"
                else:           score=12; label="↔ MIXED"
                mag_bonus = min(5, int((abs(fii_net)+abs(dii_net))/1000))
                score     = min(30, score + (mag_bonus if fii_buy else 0))
                fii_cr = fii_net/100; dii_cr = dii_net/100
                log.info(f"FII/DII NSE: FII ₹{fii_cr:+,.0f} Cr | DII ₹{dii_cr:+,.0f} Cr → {score}/30")
                return {"fii_net":round(fii_cr,0),"dii_net":round(dii_cr,0),
                        "score":score,"label":label,
                        "detail":f"FII ₹{fii_cr:+,.0f} Cr | DII ₹{dii_cr:+,.0f} Cr"}
        except Exception as e:
            log.warning(f"FII/DII NSE failed: {e}")

    # ── 2. Google Sheets (your manual workbook entry) ────────────────
    sheets_result = _load_fii_dii_from_sheets()
    if sheets_result:
        return sheets_result

    # ── 3. VIX proxy (last resort) ───────────────────────────────────
    try:
        import yfinance as yf
        vix_df = yf.download("^INDIAVIX", period="10d", progress=False, auto_adjust=True)
        if not vix_df.empty and len(vix_df) >= 2:
            # FIX #12: squeeze() on a 1-row DataFrame returns a scalar, and .values
            # then raises AttributeError. Use to_numpy().flatten() which is safe
            # for both single-row and multi-row DataFrames.
            vix_vals = vix_df["Close"].to_numpy().flatten()
            vix_now  = float(vix_vals[-1]); vix_prev = float(vix_vals[-2])
            vix_chg  = (vix_now - vix_prev) / vix_prev * 100
            vix_5d_avg = float(vix_vals[-5:].mean()) if len(vix_vals) >= 5 else vix_now
            if vix_chg < -5:
                score=25; label="🟢 VIX falling sharply (flow proxy: FII buying)"
            elif vix_chg < -2:
                score=20; label="✅ VIX declining (flow proxy: risk appetite improving)"
            elif vix_now < 14:
                score=18; label="↔ VIX low/complacent (DII/SIP accumulation likely)"
            elif vix_chg > 5:
                score=7; label="🔴 VIX rising sharply (flow proxy: FII selling/risk-off)"
            elif vix_now > 20:
                score=8; label="↔ VIX elevated (flow uncertain)"
            else:
                score=14; label="↔ VIX stable (neutral flow)"
            return {"fii_net":0,"dii_net":0,"score":score,"label":label,
                    "detail":f"VIX proxy: {vix_now:.1f} ({vix_chg:+.1f}% 1d) — ⚠️ NSE+Sheets blocked",
                    "_fallback_note":True}
    except Exception:
        pass

    return neutral


# ══════════════════════════════════════════════════════════════════════
# SECTION 10 — INSIDER TRADING (NSE → Sheets → yfinance)
# Sheet 3: Insider | Columns: SYMBOL | PERSON | SHARES | VALUE_LAKHS | DATE | TYPE
# ══════════════════════════════════════════════════════════════════════

def _load_insider_from_sheets() -> Optional[dict]:
    """
    Read Tab 3 — INSIDER — in ONE bulk API call.

    Expected tab name  : INSIDER  (exact, case-sensitive)
    Required columns   : SYMBOL | SHARES | DATE | TYPE
    Optional columns   : PERSON | VALUE_LAKHS

    Populate from NSE PIT disclosures or BSE bulk deals.
    Only rows where TYPE contains 'buy'/'purchase'/'acqui' are scored.
    Sell / pledge / transfer rows are silently ignored.
    Rows older than 30 days are ignored.

    API cost: 1 read request.
    Returns insider_map {SYMBOL: {score, detail, ...}} or None.
    """
    if not _sheets_configured():
        return None

    log.info(f"Reading Tab 3 (INSIDER) — single bulk API call ...")
    df = _read_sheet_insider()   # ← exactly 1 API call
    if df.empty:
        log.info("  INSIDER tab: empty or not found")
        return None

    # ── Locate columns ───────────────────────────────────────────────
    sym_col = next((c for c in df.columns if "SYMBOL" in c or "SCRIP" in c), None)
    typ_col = next((c for c in df.columns
                    if any(k in c for k in ("TYPE","ACQMODE","MODE","TRANSACTION","BUYSELL"))), None)
    val_col = next((c for c in df.columns
                    if any(k in c for k in ("VALUE","LAKH","AMOUNT","CONSIDERATION"))), None)
    shr_col = next((c for c in df.columns
                    if any(k in c for k in ("SHARE","QTY","QUANTITY","SECACQ","TOTSHR"))), None)
    dt_col  = next((c for c in df.columns
                    if any(k in c for k in ("DATE","ACQFROM","TXDATE"))), None)
    per_col = next((c for c in df.columns
                    if any(k in c for k in ("PERSON","NAME","ACQNAME","INSIDER","WHO"))), None)

    if not sym_col:
        log.warning(f"  INSIDER tab: no SYMBOL column. Got: {list(df.columns)}")
        return None

    # ── Filter buy transactions only ─────────────────────────────────
    if typ_col:
        # FIX #4: broadened regex to catch common NSE/BSE TYPE column values:
        # "Buy", "Purchase", "Market Purchase", "Open Market", "Acquisition",
        # "B" (single-letter code used in some bulk deal exports), "Market"
        buy_mask = df[typ_col].astype(str).str.lower().str.contains(
            r"buy|purchase|acqui|market|open|\\bb\\b", na=False, regex=True
        )
        df = df[buy_mask].copy()
        log.info(f"  INSIDER: {len(df)} buy-type rows after TYPE filter")
    else:
        log.info(f"  INSIDER: no TYPE column — treating all {len(df)} rows as buys")

    if df.empty:
        return None

    # ── Score each symbol ─────────────────────────────────────────────
    insider_map: dict = {}
    cutoff = datetime.today() - timedelta(days=30)

    for _, row in df.iterrows():
        sym = str(row.get(sym_col, "")).strip().upper()
        if not sym or not is_halal(sym):
            continue

        # Recency gate
        days_ago = 30
        if dt_col:
            try:
                tx_date  = pd.to_datetime(str(row[dt_col]), dayfirst=True, errors="coerce")
                if pd.isna(tx_date) or tx_date < cutoff:
                    continue
                days_ago = max(0, (datetime.today() - tx_date).days)
            except Exception:
                pass

        # Value
        val_rupees = 0.0
        if val_col:
            try:
                raw_val    = str(row[val_col]).replace(",","").replace("₹","").strip()
                val_lakh   = float(raw_val or 0)
                # Auto-detect unit: if value > 1 000 it's already in rupees not lakhs
                val_rupees = val_lakh * 100_000 if val_lakh < 100_000 else val_lakh
            except Exception:
                pass

        # Shares
        shares = 0.0
        if shr_col:
            try:
                shares = float(str(row[shr_col]).replace(",","").strip() or 0)
            except Exception:
                pass

        person = str(row[per_col]).strip() if per_col else "Insider"

        if sym not in insider_map:
            insider_map[sym] = {
                "transactions": [], "total_shares": 0.0, "total_value_rupees": 0.0
            }
        insider_map[sym]["transactions"].append({
            "person": person, "shares": shares, "days_ago": days_ago,
            "type": "buy", "value_rupees": val_rupees,
        })
        insider_map[sym]["total_shares"]       += shares
        insider_map[sym]["total_value_rupees"] += val_rupees

    # Score
    for sym, d in insider_map.items():
        val_rupees = d["total_value_rupees"]
        if val_rupees == 0 and d["total_shares"] > 0:
            val_rupees = d["total_shares"] * 10   # rough proxy ₹10/share

        # Recency weight: most recent transaction wins
        recency_weight = 0.70
        for tx in d["transactions"]:
            da = tx.get("days_ago", 30)
            if da < 7:    recency_weight = max(recency_weight, 1.00)
            elif da < 14: recency_weight = max(recency_weight, 0.85)

        if val_rupees > 0:
            log_val = math.log10(max(1, val_rupees))
            score   = max(5, min(30, round((log_val - 4) * 5 * recency_weight)))
        else:
            score = 0

        n            = len(d["transactions"])
        d["score"]   = score
        d["detail"]  = (
            f"{n} insider buy(s) [SHEETS Tab 3] | "
            f"~₹{val_rupees/1e7:.1f}Cr | recency×{recency_weight:.2f} → {score}pts"
        )

    if insider_map:
        log.info(f"  INSIDER: {len(insider_map)} symbols with scored buy transactions ✅")
        return insider_map
    return None


def fetch_insider_trades(days_back: int = 30) -> dict:
    insider_map: dict = {}

    # ── 1. NSE live ──────────────────────────────────────────────────
    if not FORCE_SHEETS and not FORCE_YFINANCE:
        try:
            sess  = nse_session()
            data  = _nse_json(sess, "https://www.nseindia.com/api/corporates-pit",
                              params={"index":"equities"})
            data  = data.get("data", []) if isinstance(data, dict) else data
            cutoff = datetime.today() - timedelta(days=days_back)
            for row in data:
                try:
                    sym = str(row.get("symbol","")).upper()
                    if not sym or not is_halal(sym): continue
                    acq_type = str(row.get("acqMode","")).lower()
                    if "sell" in acq_type or "pledge" in acq_type: continue
                    try:
                        trade_date = pd.to_datetime(row.get("date", row.get("acqfromDt","")))
                        if trade_date < cutoff: continue
                    except Exception:
                        pass
                    val_shrs   = float(str(row.get("totAcqShrs", row.get("secAcq",0))).replace(",",""))
                    val_lakh   = row.get("secVal", row.get("totVal", 0))
                    try: val_rupees = float(str(val_lakh).replace(",","")) * 100_000
                    except: val_rupees = val_shrs * 10
                    if sym not in insider_map:
                        insider_map[sym] = {"transactions":[],"total_shares":0,"total_value_rupees":0}
                    insider_map[sym]["transactions"].append({"person":row.get("acqName","Insider"),
                        "shares":val_shrs,"date":row.get("date",""),"type":acq_type,"value_rupees":val_rupees})
                    insider_map[sym]["total_shares"]       += val_shrs
                    insider_map[sym]["total_value_rupees"] += val_rupees
                except Exception:
                    continue
            for sym, d in insider_map.items():
                value_rupees = d.get("total_value_rupees", d["total_shares"]*10)
                recency_weight = 0.70
                for tx in d["transactions"]:
                    try:
                        da = (datetime.today() - pd.to_datetime(tx.get("date",""))).days
                        if da < 7: recency_weight = max(recency_weight, 1.00)
                        elif da < 14: recency_weight = max(recency_weight, 0.85)
                    except: pass
                if value_rupees > 0:
                    log_val = math.log10(max(1, value_rupees))
                    score   = max(5, min(30, round((log_val-4)*5*recency_weight)))
                else: score = 0
                d["score"]  = score
                d["detail"] = (f"{len(d['transactions'])} buy(s) | "
                               f"~₹{value_rupees/1e7:.1f}Cr | ×{recency_weight:.2f} → {score}pts")
            if insider_map:
                log.info(f"Insider NSE: {len(insider_map)} stocks with buys")
                return insider_map
        except Exception as e:
            log.warning(f"Insider NSE failed: {e}")

    # ── 2. Google Sheets ─────────────────────────────────────────────
    sheets_insider = _load_insider_from_sheets()
    if sheets_insider:
        return sheets_insider

    # ── 3. yfinance fallback ─────────────────────────────────────────
    try:
        import yfinance as yf
        cutoff  = datetime.today() - timedelta(days=days_back)
        yf_map  = {}
        for sym in list(_HALAL_FALLBACK_85)[:80]:
            try:
                ticker = yf.Ticker(f"{sym}.NS")
                df     = ticker.insider_transactions
                if df is None or (hasattr(df,"empty") and df.empty): continue
                tx_col = next((c for c in df.columns
                               if c.lower() in ("transaction","type","buysell","direction")), None)
                if tx_col is None: continue
                if "Date" in df.columns:
                    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
                    df = df[df["Date"] >= pd.Timestamp(cutoff)]
                buys = df[df[tx_col].astype(str).str.contains(
                    r"Purchase|Buy|Acqui", case=False, na=False, regex=True)]
                n = len(buys)
                if n == 0 or n > 20: continue
                score = 30 if n >= 3 else 24 if n == 2 else 18
                yf_map[sym] = {"score":score,"detail":f"{n} insider buy(s) [yfinance]",
                               "transactions":[],"total_shares":0}
            except Exception:
                continue
        if yf_map:
            log.info(f"Insider yfinance fallback: {len(yf_map)} stocks")
            return yf_map
    except Exception:
        pass

    return insider_map


# ══════════════════════════════════════════════════════════════════════
# SECTION 11 — CORPORATE FILINGS (NSE → Sheets → yfinance)
# Sheet 4: Filings | Columns: SYMBOL | DATE | SUBJECT | SENTIMENT
# ══════════════════════════════════════════════════════════════════════

def _load_filings_from_sheets() -> Optional[dict]:
    """
    Read Tab 4 — FILINGS — in ONE bulk API call.

    Expected tab name  : FILINGS  (exact, case-sensitive)
    Required columns   : SYMBOL | DATE | SUBJECT
    Optional columns   : SENTIMENT  (positive / negative / neutral / strong)

    Populate from NSE corporate action page or BSE announcements.
    Rows older than 14 days are ignored.
    If SENTIMENT is absent, keyword scoring on SUBJECT is applied automatically.

    API cost: 1 read request.
    Returns filings dict {SYMBOL: {score, detail}} or None.
    """
    if not _sheets_configured():
        return None

    log.info(f"Reading Tab 4 (FILINGS) — single bulk API call ...")
    df = _read_sheet_filings()   # ← exactly 1 API call
    if df.empty:
        log.info("  FILINGS tab: empty or not found")
        return None

    # ── Locate columns ───────────────────────────────────────────────
    sym_col  = next((c for c in df.columns if "SYMBOL" in c or "SCRIP" in c), None)
    subj_col = next((c for c in df.columns
                     if any(k in c for k in ("SUBJECT","DESC","FILING","ANNOUNCEMENT","HEADLINE","TITLE"))), None)
    sent_col = next((c for c in df.columns
                     if any(k in c for k in ("SENTIMENT","SIGNAL","IMPACT","OUTLOOK"))), None)
    dt_col   = next((c for c in df.columns if "DATE" in c), None)

    if not sym_col:
        log.warning(f"  FILINGS tab: no SYMBOL column. Got: {list(df.columns)}")
        return None
    if not subj_col:
        log.warning(f"  FILINGS tab: no SUBJECT/DESC column. Got: {list(df.columns)}")
        return None

    positive_kw = [
        "bonus","dividend","buyback","split","record date","profit","growth",
        "expansion","order","contract","win","award","acquisition","launch",
        "guidance raised","upgrade","beat","record","approved",
    ]
    negative_kw = [
        "loss","write-off","write off","penalty","fraud","probe","npa","default",
        "downgrade","miss","warning","regulatory","sebi notice","court","litigation",
    ]

    filings : dict = {}
    cutoff  = datetime.today() - timedelta(days=14)

    for _, row in df.iterrows():
        sym = str(row.get(sym_col, "")).strip().upper()
        if not sym:
            continue

        # Recency gate
        if dt_col:
            try:
                row_date = pd.to_datetime(str(row[dt_col]), dayfirst=True, errors="coerce")
                if pd.isna(row_date) or row_date < cutoff:
                    continue
            except Exception:
                pass

        subject = str(row.get(subj_col, "")).lower() if subj_col else ""

        # ── Score via SENTIMENT column first (most reliable) ──────────
        if sent_col:
            sent = str(row.get(sent_col, "")).strip().lower()
            if any(s in sent for s in ("strong positive","very positive","bullish strong")):
                score = 30
            elif any(s in sent for s in ("positive","bullish")):
                score = 25
            elif any(s in sent for s in ("negative","bearish")):
                score = 5
            elif any(s in sent for s in ("strong negative","very negative")):
                score = 2
            else:
                # neutral or blank — fall through to keyword score
                pos   = sum(1 for k in positive_kw if k in subject)
                neg   = sum(1 for k in negative_kw if k in subject)
                score = min(30, max(0, 15 + pos * 5 - neg * 8))
        else:
            pos   = sum(1 for k in positive_kw if k in subject)
            neg   = sum(1 for k in negative_kw if k in subject)
            score = min(30, max(0, 15 + pos * 5 - neg * 8))

        detail = (subject[:80].capitalize() if subject else "Corporate filing") + " [SHEETS Tab 4]"

        # Keep highest score per symbol (best filing wins)
        if sym not in filings or score > filings[sym]["score"]:
            filings[sym] = {"score": score, "detail": detail}

    if filings:
        log.info(f"  FILINGS: {len(filings)} symbols with scored filings ✅")
        return filings
    return None


def fetch_recent_filings(days_back: int = 14) -> dict:
    filings: dict = {}

    # ── 1. NSE live ──────────────────────────────────────────────────
    if not FORCE_SHEETS and not FORCE_YFINANCE:
        try:
            sess = nse_session()
            data = _nse_json(
                sess, "https://www.nseindia.com/api/corporates-corporateActions",
                params={"index":"equities",
                        "from_date":(datetime.today()-timedelta(days=days_back)).strftime("%d-%m-%Y"),
                        "to_date":datetime.today().strftime("%d-%m-%Y"),
                        "type":"announcements"},
            )
            if isinstance(data, dict): data = data.get("data", [])
            # FIX #13: verify the endpoint returned usable records before proceeding.
            # NSE's actual announcements endpoint may differ from what's coded above;
            # if the response lacks expected keys it silently produced wrong data.
            if not data or not isinstance(data, list):
                log.warning(
                    f"Filings NSE: response missing 'data' list or returned empty "
                    f"(type={type(data).__name__}) — check NSE API endpoint. "
                    f"Falling back to Sheets."
                )
                raise ValueError("NSE filings: no usable data in response")
            first = data[0] if data else {}
            if not any(k in first for k in ("symbol","subject","desc","Symbol","Subject")):
                log.warning(
                    f"Filings NSE: response keys {list(first.keys())[:8]} don't match "
                    f"expected schema (symbol/subject) — endpoint may have changed. "
                    f"Falling back to Sheets."
                )
                raise ValueError("NSE filings: unexpected response schema")
            pos_kw = ["bonus","dividend","buyback","split","record date",
                      "profit","growth","expansion","order","contract","win"]
            neg_kw = ["loss","write-off","penalty","fraud","probe","npa","default"]
            for row in data:
                try:
                    sym     = str(row.get("symbol","")).upper()
                    subject = str(row.get("subject", row.get("desc",""))).lower()
                    if not sym: continue
                    pos   = sum(1 for k in pos_kw if k in subject)
                    neg   = sum(1 for k in neg_kw if k in subject)
                    score = min(30, max(0, 15 + pos*5 - neg*8))
                    if sym not in filings or score > filings[sym]["score"]:
                        filings[sym] = {"score":score,"detail":subject[:80].capitalize()}
                except Exception:
                    continue
            if filings:
                log.info(f"Filings NSE: {len(filings)} symbols")
                return filings
        except Exception as e:
            log.warning(f"Filings NSE failed: {e}")

    # ── 2. Google Sheets ─────────────────────────────────────────────
    sheets_filings = _load_filings_from_sheets()
    if sheets_filings:
        return sheets_filings

    # ── 3. yfinance news fallback ─────────────────────────────────────
    try:
        import yfinance as yf
        pos_kw = ["bonus","dividend","buyback","split","profit","growth",
                  "expansion","order","contract","win"]
        neg_kw = ["loss","write-off","penalty","fraud","probe","npa","default"]
        cutoff_ts = (datetime.today()-timedelta(days=days_back)).timestamp()
        yf_filings: dict = {}
        for sym in list(_HALAL_FALLBACK_85)[:80]:
            try:
                news = yf.Ticker(f"{sym}.NS").news or []
                best = 15
                best_detail = "No significant filing"
                for item in news:
                    if item.get("providerPublishTime",0) < cutoff_ts: continue
                    headline = (item.get("title","")+" "+item.get("summary","")).lower()
                    pos = sum(1 for k in pos_kw if k in headline)
                    neg = sum(1 for k in neg_kw if k in headline)
                    score = min(30, max(0, 15 + pos*4 - neg*7))
                    if score > best:
                        best = score
                        best_detail = item.get("title","News signal")[:80]
                if best != 15:
                    yf_filings[sym] = {"score":best,"detail":best_detail}
            except Exception:
                continue
        if yf_filings:
            return yf_filings
    except Exception:
        pass
    return filings


# ══════════════════════════════════════════════════════════════════════
# SECTION 12 — EARNINGS CALENDAR (NSE → Sheets → yfinance)
# Sheet 5: Earnings | Columns: SYMBOL | RESULT_DATE | PURPOSE
# ══════════════════════════════════════════════════════════════════════

def _count_nse_trading_days(from_date: datetime, to_date: datetime) -> int:
    try:
        import pandas_market_calendars as mcal
        nse_cal  = mcal.get_calendar("NSE")
        schedule = nse_cal.schedule(start_date=from_date.strftime("%Y-%m-%d"),
                                    end_date=to_date.strftime("%Y-%m-%d"))
        return max(1, len(schedule))
    except Exception:
        calendar_days = max(1, (to_date - from_date).days)
        return max(1, round(calendar_days * 5 / 7))


def _load_earnings_from_sheets() -> Optional[dict]:
    """
    Read Tab 5 — EARNINGS — in ONE bulk API call.

    Expected tab name  : EARNINGS  (exact, case-sensitive)
    Required columns   : SYMBOL | RESULT_DATE
    Optional columns   : PURPOSE  (results / dividend — other values ignored)

    If PURPOSE column is absent, all rows are treated as result dates.
    Delta stored as TRADING DAYS from today:
        positive = event is in the future
        negative = event has already passed

    Populate from NSE event calendar page before market hours.

    API cost: 1 read request.
    Returns earnings_cal dict {SYMBOL: trading_day_delta} or None.
    """
    if not _sheets_configured():
        return None

    log.info(f"Reading Tab 5 (EARNINGS) — single bulk API call ...")
    df = _read_sheet_earnings()   # ← exactly 1 API call
    if df.empty:
        log.info("  EARNINGS tab: empty or not found")
        return None

    # ── Locate columns ───────────────────────────────────────────────
    sym_col  = next((c for c in df.columns if "SYMBOL" in c or "SCRIP" in c), None)
    date_col = next((c for c in df.columns
                     if any(k in c for k in ("RESULT_DATE","DATE","RESULT","EVENT_DATE"))), None)
    pur_col  = next((c for c in df.columns
                     if any(k in c for k in ("PURPOSE","TYPE","EVENT","CATEGORY"))), None)

    if not sym_col:
        log.warning(f"  EARNINGS tab: no SYMBOL column. Got: {list(df.columns)}")
        return None
    if not date_col:
        log.warning(f"  EARNINGS tab: no DATE/RESULT_DATE column. Got: {list(df.columns)}")
        return None

    cal   : dict = {}
    today = datetime.today()

    for _, row in df.iterrows():
        try:
            sym = str(row.get(sym_col, "")).strip().upper()
            if not sym:
                continue

            # PURPOSE filter — skip AGM, board meeting, etc. if column exists
            if pur_col:
                pur = str(row.get(pur_col, "")).strip().lower()
                if pur and not any(k in pur for k in ("result","dividend","earning","q1","q2","q3","q4","annual")):
                    continue

            raw_date = str(row[date_col]).strip()
            if not raw_date:
                continue
            dt = pd.to_datetime(raw_date, dayfirst=True, errors="coerce")
            if pd.isna(dt):
                continue

            dt_py         = dt.to_pydatetime()
            calendar_days = (dt_py - today).days
            if calendar_days >= 0:
                td_delta = _count_nse_trading_days(today, dt_py)
            else:
                td_delta = -_count_nse_trading_days(dt_py, today)

            # Keep the nearest event per symbol
            if sym not in cal or abs(td_delta) < abs(cal[sym]):
                cal[sym] = td_delta

        except Exception as e:
            log.debug(f"  EARNINGS row parse error: {e}")
            continue

    if cal:
        log.info(f"  EARNINGS: {len(cal)} events loaded (trading-day deltas) ✅")
        return cal
    return None


def fetch_earnings_calendar() -> dict:
    cal: dict = {}

    # ── 1. NSE live ──────────────────────────────────────────────────
    if not FORCE_SHEETS and not FORCE_YFINANCE:
        try:
            sess   = nse_session()
            events = _nse_json(sess, "https://www.nseindia.com/api/event-calendar",
                               params={"index":"equities"})
            if isinstance(events, dict): events = events.get("data", [])
            today = datetime.today()
            for ev in events:
                try:
                    sym = str(ev.get("symbol","")).upper()
                    pur = str(ev.get("purpose","")).lower()
                    if "result" not in pur and "dividend" not in pur: continue
                    dt  = pd.to_datetime(ev.get("date",""))
                    cal_days = (dt - today).days
                    if cal_days >= 0:
                        td_delta = _count_nse_trading_days(today, dt.to_pydatetime())
                    else:
                        td_delta = -_count_nse_trading_days(dt.to_pydatetime(), today)
                    if sym not in cal or abs(td_delta) < abs(cal[sym]):
                        cal[sym] = td_delta
                except Exception:
                    continue
            if cal:
                log.info(f"Earnings NSE: {len(cal)} events (trading-day deltas)")
                return cal
        except Exception as e:
            log.warning(f"Earnings NSE failed: {e}")

    # ── 2. Google Sheets ─────────────────────────────────────────────
    sheets_cal = _load_earnings_from_sheets()
    if sheets_cal:
        return sheets_cal

    # ── 3. yfinance fallback ─────────────────────────────────────────
    try:
        import yfinance as yf
        today = datetime.today()
        yf_cal: dict = {}
        for sym in list(_HALAL_FALLBACK_85)[:80]:
            try:
                cal_data = yf.Ticker(f"{sym}.NS").calendar
                if cal_data is None: continue
                earn_dates = (cal_data.get("Earnings Date") or
                              cal_data.get("earningsDate") or [])
                if not earn_dates: continue
                dt = pd.to_datetime(earn_dates[0])
                cal_days = (dt - today).days
                if cal_days >= 0:
                    td_delta = _count_nse_trading_days(today, dt.to_pydatetime())
                else:
                    td_delta = -_count_nse_trading_days(dt.to_pydatetime(), today)
                yf_cal[sym] = td_delta
            except Exception:
                continue
        if yf_cal:
            return yf_cal
    except Exception:
        pass

    return cal


# ══════════════════════════════════════════════════════════════════════
# SECTION 13 — ROCE QUALITY GATE
# ══════════════════════════════════════════════════════════════════════

def fetch_roce_proxy(symbol: str) -> tuple:
    sym_upper = symbol.upper()
    if sym_upper in _roce_cache:
        cached_val, cached_label, cached_at = _roce_cache[sym_upper]
        if time.time() - cached_at < _ROCE_CACHE_TTL_SECONDS:
            return cached_val, cached_label

    db_row = _db_get_roce(sym_upper)
    if db_row is not None:
        db_val, db_label, db_at = db_row
        if time.time() - db_at < _ROCE_CACHE_TTL_SECONDS:
            _roce_cache[sym_upper] = (db_val, db_label, db_at)
            return db_val, db_label

    result = (None, "ROE quality data unavailable")
    try:
        import yfinance as yf
        info = yf.Ticker(f"{symbol}.NS").info
        roe  = info.get("returnOnEquity")
        roa  = info.get("returnOnAssets")
        debt = info.get("debtToEquity", 0) or 0
        if roe is not None:
            roe_pct = float(roe) * 100
            quality = ("HIGH ✓" if roe_pct >= 15
                       else "ACCEPTABLE" if roe_pct >= 5
                       else "LOW ⚠️" if roe_pct >= 0
                       else "NEGATIVE ❌")
            debt_note = f" | D/E:{debt:.1f}" if debt else ""
            result = (roe_pct, f"ROE(proxy) {roe_pct:.1f}% [{quality}]{debt_note}")
        elif roa is not None:
            roa_pct = float(roa) * 100
            quality = "ACCEPTABLE" if roa_pct >= 5 else "LOW ⚠️"
            result = (roa_pct, f"ROA(proxy) {roa_pct:.1f}% [{quality}]")
    except Exception as e:
        log.debug(f"ROCE fetch {symbol}: {e}")

    _roce_cache[sym_upper] = (result[0], result[1], time.time())
    _db_put_roce(sym_upper, result[0], result[1], time.time())
    return result


# ══════════════════════════════════════════════════════════════════════
# SECTION 14 — INDICATOR ENGINE
# ══════════════════════════════════════════════════════════════════════

def calc_atr(df, period=14):
    h,l,c = df["high"],df["low"],df["close"]
    tr = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.ewm(span=period,adjust=False).mean()

def calc_rsi(s, period=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(span=period,adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(span=period,adjust=False).mean()
    return 100-(100/(1+g/l.replace(0,np.nan)))

def calc_mfi(df, period=14):
    tp  = (df["high"]+df["low"]+df["close"])/3
    rmf = tp*df["volume"]
    pos = rmf.where(tp>tp.shift(),0)
    neg = rmf.where(tp<tp.shift(),0)
    mfr = pos.rolling(period).sum()/neg.rolling(period).sum().replace(0,np.nan)
    return 100-(100/(1+mfr))

def _calc_vpoc_single(df: pd.DataFrame, lookback: int, n_bins: int = 100) -> float:
    """
    Internal: bin-histogram VPOC for a single lookback window.
    Bars are time-weighted so that recent sessions count more than old ones.
    This prevents a strong recent downtrend from dragging VPOC to current price
    when the structural HVN (High Volume Node) lies higher.
    """
    r = df.tail(lookback).copy()
    if len(r) < 20:
        return float(df["close"].iloc[-1])
    price_min = float(r["low"].min()); price_max = float(r["high"].max())
    if price_max <= price_min:
        return float(r["close"].iloc[-1])
    bins       = np.linspace(price_min, price_max, n_bins + 1)
    bin_volume = np.zeros(n_bins)
    n          = len(r)
    lows    = r["low"].values.astype(float)
    highs   = r["high"].values.astype(float)
    volumes = r["volume"].values.astype(float)
    # Recency weight: oldest bar=0.5, newest bar=1.0 (linear ramp)
    # This ensures the dominant trading zone from a prior range isn't buried by
    # a thin-volume recent drawdown.
    recency_weights = np.linspace(0.5, 1.0, n)
    for i in range(n):
        bl, bh, vol = lows[i], highs[i], volumes[i]
        if vol <= 0 or bh <= bl:
            continue
        overlap = np.maximum(0.0,
                    np.minimum(bh, bins[1:]) - np.maximum(bl, bins[:-1]))
        bin_volume += recency_weights[i] * vol * (overlap / (bh - bl))
    vpoc_idx = int(np.argmax(bin_volume))
    return float((bins[vpoc_idx] + bins[vpoc_idx + 1]) / 2.0)


def calc_vpoc(df: pd.DataFrame, lookback: int = 252, n_bins: int = 100) -> float:
    """
    Multi-timeframe weighted VPOC — implements the vpoc_3m_wt / vpoc_6m_wt /
    vpoc_12m_wt weights defined in SNIPER_CFG (previously configured but unused).

    Three lookback windows:
      3M  ≈  63 bars  weight 0.40  (near-term HVN — most actionable)
      6M  ≈ 126 bars  weight 0.35  (medium-term structure)
     12M  ≈ 252 bars  weight 0.25  (annual structural floor)

    The weighted blend prevents a downtrend from dragging the VPOC to the
    current price when the real High Volume Node sits higher (e.g. INOXWIND
    traded 3M of heavy volume at 110-116 before the sell-off — that HVN is
    the true VPOC, not the thin-volume bounce zone at 97-99).
    """
    wt_3m  = SNIPER_CFG.get("vpoc_3m_wt",  0.40)
    wt_6m  = SNIPER_CFG.get("vpoc_6m_wt",  0.35)
    wt_12m = SNIPER_CFG.get("vpoc_12m_wt", 0.25)

    lb_3m  = min(63,  len(df))
    lb_6m  = min(126, len(df))
    lb_12m = min(252, len(df))

    vpoc_3m  = _calc_vpoc_single(df, lb_3m,  n_bins)
    vpoc_6m  = _calc_vpoc_single(df, lb_6m,  n_bins)
    vpoc_12m = _calc_vpoc_single(df, lb_12m, n_bins)

    # If 3M and 6M are far apart (>10%), the structure is trending —
    # lean more on the 6M/12M node which holds the dominant HVN.
    divergence = abs(vpoc_3m - vpoc_6m) / max(vpoc_6m, 1e-6)
    if divergence > 0.10:
        # Structural divergence: shift weight toward longer-term HVN
        wt_3m, wt_6m, wt_12m = 0.20, 0.45, 0.35

    total_wt = wt_3m + wt_6m + wt_12m
    vpoc_blended = (vpoc_3m * wt_3m + vpoc_6m * wt_6m + vpoc_12m * wt_12m) / total_wt
    return round(float(vpoc_blended), 2)

def calc_adx(df, period=14):
    h,l,c = df["high"],df["low"],df["close"]
    tr  = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    atr = tr.ewm(span=period,adjust=False).mean()
    up  = h-h.shift(); dn = l.shift()-l
    pdm = up.where((up>dn)&(up>0),0); ndm = dn.where((dn>up)&(dn>0),0)
    pdi = 100*pdm.ewm(span=period,adjust=False).mean()/atr
    ndi = 100*ndm.ewm(span=period,adjust=False).mean()/atr
    dx  = 100*(pdi-ndi).abs()/(pdi+ndi).replace(0,np.nan)
    return float(dx.ewm(span=period,adjust=False).mean().iloc[-1])


# ══════════════════════════════════════════════════════════════════════
# SECTION 15 — FORWARD-LOOKING SIGNALS (52W / ATR-V / PEAD)
# ══════════════════════════════════════════════════════════════════════

def calc_52w_compression(hist: pd.DataFrame, close: float, atr14: float) -> tuple:
    if len(hist) < 20: return 0, "52W: insufficient data"
    lookback  = hist.tail(252)
    high_52w  = float(lookback["high"].max())
    if high_52w <= 0 or close <= 0: return 0, "52W: price error"
    pct_from_high = (high_52w - close) / high_52w * 100
    atr100_val    = float(calc_atr(hist, 100).iloc[-1]) if len(hist) >= 100 else atr14
    atr_tight     = atr14 > 0 and atr100_val > 0 and (atr14/atr100_val) < 0.70
    if pct_from_high <= 5.0:
        bonus=12 if atr_tight else 9; tier="ELITE COIL 🎯" if atr_tight else "AT 52W HIGH"
    elif pct_from_high <= 10.0:
        bonus=7 if atr_tight else 5; tier="NEAR HIGH+COIL" if atr_tight else "NEAR 52W HIGH"
    elif pct_from_high <= 15.0:
        bonus=3; tier="APPROACHING HIGH"
    else:
        bonus=0; tier=f"{pct_from_high:.0f}% from 52W high"
    return bonus, f"52W: {pct_from_high:.1f}% from ₹{high_52w:.0f} [{tier}] +{bonus}pts"


def calc_atr_velocity(hist: pd.DataFrame) -> tuple:
    if len(hist) < 55: return 0, "ATR-V: insufficient data"
    atr7=float(calc_atr(hist,7).iloc[-1]); atr20=float(calc_atr(hist,20).iloc[-1])
    atr50=float(calc_atr(hist,50).iloc[-1])
    if atr50 <= 0: return 0, "ATR-V: baseline zero"
    full_contraction = atr7<atr20 and atr20<atr50
    partial          = atr7<atr50
    rate             = 1.0-(atr7/atr50)
    if full_contraction:
        if rate>0.50: bonus,tier=8,"🌀 COIL CRITICAL (+8pts)"
        elif rate>0.30: bonus,tier=6,"🌀 COIL TIGHT (+6pts)"
        else: bonus,tier=4,"🌀 COILING (+4pts)"
    elif partial: bonus,tier=2,"COMPRESSING (+2pts)"
    else: bonus,tier=0,"EXPANDING"
    return bonus, f"ATR-V: {rate*100:.0f}% compressed [{tier}]"


def calc_pead_bonus(symbol: str, earnings_cal: dict, hist: pd.DataFrame) -> tuple:
    days = earnings_cal.get(symbol.upper())
    if days is None: return 0, ""
    if days >= 0: return 0, ""
    recency = abs(days)
    if recency > 21: return 0, ""
    if len(hist) < 5: return 0, ""
    try:
        lookback  = min(recency, len(hist)-1)
        close_now = float(hist["close"].iloc[-1])
        close_pre = float(hist["close"].iloc[-lookback-1])
        drift_pct = (close_now-close_pre)/close_pre*100 if close_pre>0 else 0
        if drift_pct >= 3.0 and recency <= 5:
            return 10, f"🔥 HOT PEAD — {drift_pct:.1f}% drift {recency}td post-results (+10pts)"
        elif drift_pct >= 1.5 and recency <= 14:
            return 7, f"📈 PEAD DRIFT — {drift_pct:.1f}% over {recency}td (+7pts)"
        elif recency <= 21 and drift_pct >= 0:
            return 4, f"PEAD window {recency}td, drift {drift_pct:.1f}% (+4pts)"
    except Exception:
        pass
    return 0, ""


# ══════════════════════════════════════════════════════════════════════
# SECTION 16 — HELPER FUNCTIONS (entry zones, stops, circuit breaker)
# ══════════════════════════════════════════════════════════════════════

def get_entry_tolerance(price: float, atr14: float = 0.0,
                        gap_buffer: float = 0.01) -> tuple:
    if atr14 > 0 and price > 0:
        atr_pct = atr14/price
        lo_pct  = max(0.005, min(0.05, atr_pct*0.8))
        hi_pct  = max(0.003, min(0.03, atr_pct*0.5)) + gap_buffer
        return lo_pct, hi_pct
    if price < 100:   return 0.030, 0.025+gap_buffer
    elif price < 300: return 0.020, 0.015+gap_buffer
    elif price < 1000:return 0.012, 0.010+gap_buffer
    else:             return 0.008, 0.006+gap_buffer


def get_atr_stop_multiplier(price: float) -> float:
    if price < 100:   return 0.75
    elif price < 300: return 1.00
    elif price < 1000:return 1.40
    else:             return 1.75


def check_smallcap_circuit_breaker() -> tuple:
    if "result" in _smallcap_index_cache:
        return _smallcap_index_cache["result"]
    result = (False, "Smallcap circuit breaker: data unavailable (pass)")
    try:
        import yfinance as yf
        df = yf.download("^CNXSC", period="60d", progress=False, auto_adjust=True)
        if df.empty:
            df = yf.download("NIFTYSMLCAP100.NS", period="60d",
                             progress=False, auto_adjust=True)
        if not df.empty and len(df) >= 20:
            closes = df["Close"].squeeze().values
            ma20   = float(np.mean(closes[-20:]))
            last   = float(closes[-1])
            if last < ma20:
                pct_below = (ma20-last)/ma20*100
                result = (True, f"⚠️ SMALLCAP CIRCUIT BREAKER ACTIVE — "
                                f"Nifty Smallcap 100 {pct_below:.1f}% below 20-DMA")
            else:
                pct_above = (last-ma20)/ma20*100
                result = (False, f"Smallcap healthy — {pct_above:.1f}% above 20-DMA ✓")
    except Exception as e:
        log.debug(f"Circuit breaker: {e}")
    _smallcap_index_cache["result"] = result
    return result


def earnings_safety_score(symbol: str, earnings_cal: dict) -> tuple:
    days = earnings_cal.get(symbol.upper())
    if days is None: return 20, "No result date found (neutral)"
    if days < 0:
        recency = abs(days)
        if recency <= 5:  return 28, f"Results just {recency}td ago — fresh data"
        elif recency <= 21:return 25, f"Results {recency}td ago — clear runway"
        else:             return 20, f"Results {recency}td ago"
    else:
        if days <= 2:   return 5,  f"⚠️ Results in {days}td — SIZE SMALL (10%)"
        elif days <= 5: return 10, f"⚠️ Results in {days}td — risky, size to PROBE"
        elif days <= 10:return 18, f"Results in {days}td — caution"
        elif days <= 21:return 24, f"Results in {days}td — acceptable window"
        else:           return 30, f"Results in {days}td — safe runway ✓"


def _get_vix_now() -> float:
    try:
        import yfinance as yf
        vdf = yf.download("^INDIAVIX", period="5d", progress=False, auto_adjust=True)
        if not vdf.empty:
            return float(vdf["Close"].squeeze().iloc[-1])
    except Exception:
        pass
    return 18.0


# ══════════════════════════════════════════════════════════════════════
# SECTION 17 — v5.7 FEATURE FUNCTIONS
# ══════════════════════════════════════════════════════════════════════

def calc_position_size(close: float, atr14: float, atr_mult: float) -> dict:
    if atr14 <= 0 or atr_mult <= 0 or close <= 0:
        return {"pos_shares":0,"pos_amount":0.0,"pos_label":"—"}
    risk_rupees = ACCOUNT_RISK_PCT * ACCOUNT_EQUITY
    shares      = max(1, int(risk_rupees/(atr14*atr_mult)))
    amount      = round(shares*close, 2)
    return {"pos_shares":shares,"pos_amount":amount,
            "pos_label":f"{shares} shares · ₹{amount:,.0f}  (risk ₹{risk_rupees:,.0f})"}


def calc_trailing_stop(symbol: str, close: float, t3_initial: float,
                       atr14: float, atr_mult: float) -> dict:
    pos = _get_position(symbol)
    if pos is None:
        return {"trailing_stop":round(t3_initial,2),
                "trailing_label":f"Initial stop ₹{t3_initial:.2f}","trail_be_active":False}
    entry_price  = pos["entry_price"]
    initial_t3   = pos["initial_t3"]
    peak_price   = max(pos["peak_price"], close)
    be_triggered = bool(pos["be_triggered"])
    be_threshold = entry_price + 1.0*atr14
    if not be_triggered and close >= be_threshold:
        be_triggered = True
    if be_triggered:
        trail_t3 = max(entry_price+0.25*atr14, peak_price-1.5*atr14)
        label    = f"Trail ₹{trail_t3:.2f}  BE+0.25ATR floor"
    else:
        trail_t3 = max(initial_t3, peak_price-atr_mult*atr14)
        label    = f"Trail ₹{trail_t3:.2f}  ratchet"
    trail_t3 = round(max(trail_t3, 0.01), 2)
    _put_position(symbol, entry_price, pos["entry_date"], initial_t3,
                  peak_price, trail_t3, int(be_triggered))
    return {"trailing_stop":trail_t3,"trailing_label":label,
            "trail_be_active":be_triggered,"trail_peak":round(peak_price,2)}


def calc_cvd_divergence(hist: pd.DataFrame, close: float) -> dict:
    if len(hist) < 12:
        return {"cvd_signal":"NEUTRAL","cvd_label":"","cvd_bonus":0}
    h = hist.copy()
    h["cvd_bar"] = h.apply(
        lambda r: float(r["volume"]) if r["close"]>r["open"] else -float(r["volume"]), axis=1)
    h["cvd"] = h["cvd_bar"].cumsum()
    window   = 10
    cvd_now  = float(h["cvd"].iloc[-1]); cvd_10d = float(h["cvd"].iloc[-window-1])
    px_now   = float(h["close"].iloc[-1]); px_10d = float(h["close"].iloc[-window-1])
    cvd_chg  = cvd_now-cvd_10d; px_chg = px_now-px_10d
    if px_chg>0 and cvd_chg<0:
        return {"cvd_signal":"DISTRIBUTION","cvd_label":"🔴 CVD Diverge — distribution","cvd_bonus":-5}
    elif px_chg<=0 and cvd_chg>0:
        return {"cvd_signal":"ACCUMULATION","cvd_label":"🟢 CVD Accum — smart money","cvd_bonus":+5}
    return {"cvd_signal":"NEUTRAL","cvd_label":"","cvd_bonus":0}


def calc_vsa_absorption(hist: pd.DataFrame, atr14: float, adv20: float) -> dict:
    if len(hist)<5 or atr14<=0 or adv20<=0:
        return {"vsa_absorption":False,"vsa_label":"","vsa_bonus":0}
    bullish_bars = 0
    bearish_bars = 0   # FIX (audit round 2): bearish absorption = distribution, NOT smart-money buy
    for _, row in hist.tail(5).iterrows():
        spread=float(row["high"])-float(row["low"]); vol=float(row["volume"])
        cl=float(row["close"]); lo=float(row["low"]); hi=float(row["high"])
        bar_rng=hi-lo
        if bar_rng<=0: continue
        close_pct=(cl-lo)/bar_rng
        # Bullish absorption: high vol, tight spread, close near HIGH = demand absorbing supply
        bullish_absorb = spread<0.5*atr14 and vol>1.5*adv20 and close_pct>=0.60
        # Bearish absorption: high vol, tight spread, close near LOW = supply overwhelming demand
        # Per VSA literature this is DISTRIBUTION / forced selling — scored NEGATIVE, not positive
        bearish_absorb = spread<0.5*atr14 and vol>1.5*adv20 and close_pct<=0.40
        if bullish_absorb: bullish_bars += 1
        elif bearish_absorb: bearish_bars += 1
    net = bullish_bars - bearish_bars
    if bullish_bars >= 1 and net > 0:
        return {"vsa_absorption":True,
                "vsa_signal":"BULLISH",
                "vsa_label":f"🟢 VSA Bullish Absorption ({bullish_bars} bar{'s' if bullish_bars>1 else ''})",
                "vsa_bonus":min(8, bullish_bars*4)}
    elif bearish_bars >= 1 and net < 0:
        return {"vsa_absorption":False,
                "vsa_signal":"BEARISH",
                "vsa_label":f"🔴 VSA Distribution ({bearish_bars} bar{'s' if bearish_bars>1 else ''})",
                "vsa_bonus":-min(4, bearish_bars*2)}   # negative bonus = penalty
    return {"vsa_absorption":False,"vsa_signal":"NEUTRAL","vsa_label":"","vsa_bonus":0}


def calc_momentum_exhaustion(hist: pd.DataFrame, rsi_v: float,
                              close: float, adv20: float) -> dict:
    if len(hist)<12 or adv20<=0:
        return {"exhaustion_flag":False,"exhaustion_label":"","exhaustion_penalty":0}
    warnings_=[]; penalty=0
    if rsi_v>75: warnings_.append(f"RSI {rsi_v:.1f}>75"); penalty+=5
    if len(hist)>=11:
        px_10=float(hist["close"].iloc[-11])
        rsi_s=calc_rsi(hist["close"]); rsi_10=float(rsi_s.iloc[-11]) if len(rsi_s)>=11 else rsi_v
        if close>px_10 and rsi_v<rsi_10: warnings_.append("RSI bearish divergence"); penalty+=8
    last_vol=float(hist["volume"].iloc[-1])
    if last_vol>3*adv20: warnings_.append(f"Vol climax {last_vol/adv20:.1f}×ADV"); penalty+=5
    if len(warnings_)>=2:
        return {"exhaustion_flag":True,
                "exhaustion_label":"⚠️ EXHAUSTION_WARNING — "+" · ".join(warnings_),
                "exhaustion_penalty":penalty}
    return {"exhaustion_flag":False,"exhaustion_label":"","exhaustion_penalty":0}


def calc_exit_liquidity(hist: pd.DataFrame, close: float, rsi_v: float,
                        vpoc: float, atr14: float, adv20: float) -> dict:
    if len(hist)<2 or atr14<=0 or adv20<=0:
        return {"exit_liq_score":0,"exit_liq_flag":False,"exit_liq_label":""}
    last=hist.iloc[-1]
    op=float(last["open"]); hi=float(last["high"]); lo=float(last["low"])
    cl=float(last["close"]); vol=float(last["volume"])
    body=abs(cl-op); wick=hi-max(cl,op); score=0; sigs=[]
    if vol>2*adv20 and cl<op: score+=1; sigs.append("vol spike on red")
    if cl<op and vol>1.5*adv20: score+=1; sigs.append("close<open high vol")
    if body>0 and wick>2*body: score+=1; sigs.append("upper wick 2×body")
    if rsi_v>70: score+=1; sigs.append(f"RSI {rsi_v:.0f}>70")
    if vpoc>0 and close>vpoc+3*atr14: score+=1; sigs.append("close>VPOC+3ATR")
    flag=score>=3
    label=(f"🚨 EXIT_LIQUIDITY ({score}/5) — "+" · ".join(sigs)) if flag else ""
    return {"exit_liq_score":score,"exit_liq_flag":flag,"exit_liq_label":label}


def calc_fog_enhanced(adx_v: float, adx_prev: float, vix_now: float,
                      ma50: float, ma200: float, w52_bonus: int) -> dict:
    fog_score=0; reasons=[]
    ranging=adx_v<=18.0
    if ranging and adx_v<adx_prev: fog_score+=1; reasons.append(f"ADX {adx_v:.1f}↓")
    if vix_now>20: fog_score+=1; reasons.append(f"VIX {vix_now:.1f}>20")
    if ma200>0 and ma50>0:
        ma_diff_pct=abs(ma50-ma200)/ma200
        if ma_diff_pct<=0.03: fog_score+=1; reasons.append(f"MA compressed {ma_diff_pct*100:.1f}%")
    if ranging and w52_bonus==0: fog_score+=1; reasons.append("no 52W coil")
    if fog_score>=3: tier="FOG_SEVERE"; block=True
    elif fog_score>=2: tier="FOG_WARNING"; block=True
    else: tier="CLEAR"; block=False
    label=(f"🌫️ {tier} — "+" · ".join(reasons)) if block else ""
    return {"fog_tier":tier,"fog_block":block,"fog_label":label,"fog_score":fog_score}


def calc_bayesian_score(adx_v: float, mfi_v: float, cvd_signal: str,
                        layer3: bool, fii_pts: int, vix_now: float) -> dict:
    """4-node Bayesian from v5.7 (9-node upgrade in SN-3 below)."""
    prior = 0.35
    nodes = [
        (adx_v >= 25.0,   0.72, 0.30),
        (mfi_v <= 45.0,   0.68, 0.40),
        (cvd_signal == "ACCUMULATION", 0.75, 0.45),
        (layer3,          0.70, 0.35),
        (fii_pts >= 22,   0.65, 0.40),
        (vix_now < 15.0,  0.60, 0.45),
    ]
    posterior = prior
    for condition, p_true, p_false in nodes:
        likelihood = p_true if condition else p_false
        posterior  = (likelihood * posterior) / max(1e-9,
                      likelihood * posterior + (1-likelihood) * (1-posterior))
    posterior = round(posterior, 3)
    bayes_pct = round(posterior * 100)
    if posterior >= 0.70: bonus=10; label=f"🧠 Bayes {bayes_pct}% — HIGH conviction"
    elif posterior >= 0.55: bonus=5; label=f"🧠 Bayes {bayes_pct}% — moderate"
    elif posterior >= 0.40: bonus=0; label=f"🧠 Bayes {bayes_pct}% — neutral"
    else: bonus=-5; label=f"🧠 Bayes {bayes_pct}% — LOW conviction"
    return {"bayes_prob":bayes_pct,"bayes_bonus":bonus,"bayes_label":label}


def calc_dynamic_score_weights(fii_data: dict, vix_now: float) -> dict:
    # FIX #10: the old logic boosted weights["fii_dii"] to 40 but fii_pts was
    # already hard-capped at 30, so dyn_max ballooned while components never
    # filled the gap — the total = min(dyn_max, ...) line was effectively dead.
    # Fix: only adjust dyn_max when we also return rescaling hints that callers
    # can apply, and keep dyn_max numerically coherent with actual component caps.
    weights=dict(SCORE_WEIGHTS); reasons=[]
    vix_boost = False
    if vix_now>20:
        # Increase FII weight intention but cap at the real component maximum (30)
        weights["fii_dii"]  = 30   # already maxed — document the intent, don't break math
        weights["fortress"] = max(60, weights["fortress"]-10)
        vix_boost = True
        reasons.append("VIX>20: FII weight prioritised")
    fii_score = fii_data.get("score",15)
    if fii_score < 10:
        # When FII is selling, insider signals matter more
        weights["insider"] = min(35, weights.get("insider",30)+5)
        weights["filing"]  = max(20, weights.get("filing",30)-5)
        reasons.append("FII selling: insider weight +5")
    # dyn_max reflects actual achievable total given real component caps
    dyn_max = sum(weights.values())
    label   = " | ".join(reasons) if reasons else "Standard weights"
    return {"dyn_weights":weights,"dyn_max":dyn_max,"dyn_label":label}


def calc_monte_carlo_survival(hist: pd.DataFrame, t3: float,
                               n_sims: int = 500, horizon: int = 20) -> dict:
    if len(hist) < 30 or t3 <= 0:
        return {"mc_survival_pct":None,"mc_label":"MC: insufficient data"}
    try:
        closes    = hist["close"].values.astype(float)
        log_ret   = np.diff(np.log(closes[closes>0]))
        if len(log_ret) < 10:
            return {"mc_survival_pct":None,"mc_label":"MC: insufficient returns"}
        mu, sigma = float(np.mean(log_ret)), float(np.std(log_ret))
        current   = float(closes[-1])
        survived  = 0
        # scipy is optional — numpy's random.normal is a perfectly adequate substitute
        try:
            from scipy import stats as _sp   # noqa: F401 — only imported for parity check
        except ImportError:
            pass   # scipy absent; numpy path below handles all simulation needs
        rng = np.random.default_rng()
        for _ in range(n_sims):
            ret  = np.cumsum(rng.normal(mu, sigma, horizon))
            path = current * np.exp(ret)
            if float(np.min(path)) > t3:
                survived += 1
        pct = round(survived/n_sims*100, 1)
        label = (f"✅ MC survival {pct}% ({n_sims} sims, {horizon}d)" if pct >= 70
                 else f"⚠️ MC survival {pct}%")
        return {"mc_survival_pct":pct,"mc_label":label}
    except Exception as e:
        return {"mc_survival_pct":None,"mc_label":f"MC error: {e}"}


def calc_round_trip_guard(hist: pd.DataFrame, close: float, t1: float) -> dict:
    if len(hist)<20:
        return {"round_trip_risk":False,"round_trip_label":""}
    peak_20=float(hist["high"].tail(20).max())
    if close<peak_20*0.90 and close>t1:
        return {"round_trip_risk":True,
                "round_trip_label":f"⚠️ ROUND_TRIP_RISK — close {close:.0f} < 90% of {peak_20:.0f}"}
    return {"round_trip_risk":False,"round_trip_label":""}


# ══════════════════════════════════════════════════════════════════════
# SECTION 18 — FORTRESS CORE SCORING ENGINE
# ══════════════════════════════════════════════════════════════════════

def fortress_score(symbol: str, today_row, hist: pd.DataFrame) -> Optional[dict]:
    if len(hist) < CFG["min_hist_bars"]:
        return None

    close  = float(today_row["close"])
    volume = float(today_row.get("volume", hist["volume"].iloc[-1] if "volume" in hist.columns else 0))

    # Indicators
    atr14_s  = calc_atr(hist, 14)
    atr14    = float(atr14_s.iloc[-1]) if not atr14_s.empty else 0.0
    rsi_v    = float(calc_rsi(hist["close"]).iloc[-1])
    mfi_v    = float(calc_mfi(hist, 14).iloc[-1])
    adx_v    = calc_adx(hist, 14)
    adx_prev = float(calc_adx(hist.iloc[:-1], 14)) if len(hist) > 14 else adx_v
    vpoc     = calc_vpoc(hist, lookback=252)

    adv20    = float(hist["volume"].tail(20).mean()) if len(hist) >= 20 else volume
    ma50_v   = float(hist["close"].tail(50).mean())  if len(hist) >= 50 else close
    ma200_v  = float(hist["close"].tail(200).mean()) if len(hist) >= 200 else close

    # Momentum velocity (20-bar return)
    if len(hist) >= 21:
        close_20  = float(hist["close"].iloc[-21])
        velocity  = (close - close_20) / close_20 * 100 if close_20 > 0 else 0.0
    else:
        velocity  = 0.0

    # ── Adaptive MA fallback chain (v5.7): MA200 → MA100 → MA50 ────
    # Only use a shorter MA if there are insufficient bars for the longer one.
    if len(hist) >= 200:
        ma_ref   = ma200_v
        ma_label = "MA200"
    elif len(hist) >= 100:
        ma_ref   = float(hist["close"].tail(100).mean())
        ma_label = "MA100"
        log.debug(f"{symbol}: insufficient bars for MA200 — using MA100")
    else:
        ma_ref   = ma50_v
        ma_label = "MA50"
        log.debug(f"{symbol}: insufficient bars for MA100 — using MA50")
    below_tolerance = (close < ma_ref * (1 - CFG["ma200_tolerance"]))
    # FIX #7 (refined per audit round 2): hard veto ONLY when below MA200.
    # MA100/MA50 pullbacks are valid buy-at-support setups — vetoing them kills
    # legitimate entries (e.g. stock at ₹95 bouncing off MA100 at ₹100).
    # For shorter-term MA refs, apply a score penalty instead of a full veto.
    if below_tolerance:
        if ma_label == "MA200":
            return None   # hard veto: structural downtrend below long-term MA
        else:
            # Penalty path: reduce fortress pts 15% — still eligible but deprioritised
            pass   # penalty applied later in pts calculation (see below_tolerance_pen)

    alt_pct  = ((close - ma_ref) / ma_ref * 100) if ma_ref > 0 else 0.0
    alt_warn = alt_pct > CFG["alt_warn_pct"]
    alt_stop = alt_pct > CFG["alt_stop_pct"]
    if alt_stop:
        return None   # hard veto: stock too extended above MA200

    sector      = get_sector(symbol)
    sector_mult = SECTOR_TRUTH.get(sector, 1.0)
    if sector in SECTOR_BLOCKED:
        return None   # blocked sector

    # Sector RS override: if stock outperforms sector by >5%, use neutral mult
    try:
        sect_20 = 0.0
        if sector in SECTOR_INDICES:
            import yfinance as yf
            idx_df = yf.download(f"^{SECTOR_INDICES[sector]}", period="30d",
                                  progress=False, auto_adjust=True)
            if not idx_df.empty and len(idx_df) >= 2:
                ic = idx_df["Close"].squeeze().values
                sect_20 = (ic[-1]-ic[-20])/ic[-20]*100 if len(ic)>=20 else 0.0
        if velocity > sect_20 + 5.0:
            sector_mult = max(sector_mult, 1.0)
    except Exception:
        pass

    # Turnover gate
    turnover_lakhs = float(today_row.get("turnover_lakhs", 0))
    turnover_cr    = turnover_lakhs / 100
    if turnover_lakhs < CFG["turnover_lakhs"]:
        return None

    # MFI interpretation
    if mfi_v <= CFG["mfi_accum"]:   mfi_status = "ACCUMULATION 🟢"
    elif mfi_v >= CFG["mfi_dist"]:  mfi_status = "DISTRIBUTION 🔴"
    else:                            mfi_status = "NEUTRAL ↔"

    # ADX regime
    if adx_v >= CFG["adx_trend"]:   regime = "MOMENTUM"
    elif adx_v >= CFG["adx_range"]: regime = "TRANSITION"
    else:                            regime = "RANGING"

    # Entry zone
    lo_pct, hi_pct = get_entry_tolerance(close, atr14)
    t1         = round(vpoc, 2)
    entry_lo   = round(t1 * (1 - lo_pct), 2)
    entry_hi   = round(t1 * (1 + hi_pct), 2)
    entry_zone = "PRISTINE" if entry_lo <= close <= entry_hi else (
                 "ABOVE" if close > entry_hi else "BELOW")
    entry_band = f"₹{entry_lo:.2f}–₹{entry_hi:.2f}"

    # ATR stops
    atr_mult = get_atr_stop_multiplier(close)
    t2       = round(close + CFG["atr_t2"] * atr14, 2)
    t3       = round(close - atr_mult * atr14, 2)
    if t3 <= 0: t3 = round(close * 0.93, 2)
    risk_pct_val = round((close - t3) / close * 100, 2) if close > 0 else 0

    r1 = round(close * 1.15, 2)
    r2 = round(close * 1.30, 2)
    r3 = round(close * 1.50, 2)
    rr = round((r1 - close) / (close - t3), 2) if (close - t3) > 0 else 0

    stop_note = (f"⚠️ {alt_pct:.0f}% above {ma_label} — altitude warning" if alt_warn
                 else f"ATR-{atr_mult:.2f}× stop")

    # VCP coil: current ATR < 70% of 100-bar ATR AND volume contracting
    atr100    = float(calc_atr(hist, 100).iloc[-1]) if len(hist) >= 100 else atr14
    vol_contract = (adv20 > 0 and volume < adv20 * 0.8)
    vcp_coil  = ("TIGHT 🟢"
                 if atr14 > 0 and atr100 > 0 and (atr14/atr100) < 0.70 and vol_contract
                 else "LOOSE")

    # Layer 1: Close within ±2% of VPOC
    layer1 = abs(close - vpoc) / vpoc <= 0.02 if vpoc > 0 else False

    # Layer 2: Volume spike (≥ vol_ratio × ADV20) in last 5 bars
    layer2 = any(float(hist["volume"].iloc[-(i+1)]) >= CFG["vol_ratio"] * adv20
                 for i in range(min(5, len(hist)))) if adv20 > 0 else False

    # Layer 3: Pivot bounce recency (close near VPOC within 45 days)
    # v5.7 momentum_mode override: if ADX ≥ 25 AND close > MA50, grant
    # layer3 regardless of VPOC touch count (trend-follow mode).
    recency_bars  = min(CFG["recency_days"], len(hist))
    recent_hist   = hist.tail(recency_bars)
    vpoc_touches  = sum(1 for _, r in recent_hist.iterrows()
                        if abs(float(r["close"]) - vpoc) / vpoc <= 0.03)
    momentum_mode = (adx_v >= 25 and close > ma50_v)
    layer3        = vpoc_touches >= 2 or momentum_mode

    # NOTE (audit round 2): fog_pre previously computed here with a hardcoded vix=18
    # placeholder and returned as fog_block_pre / fog_tier_pre — but assemble_result
    # recomputes FOG with the real live VIX and that is the value actually used.
    # fog_pre was dead code: computed but never read by any caller. Removed.

    pts = 0.0

    # VPOC / floor layers
    if layer1: pts += 25
    elif abs(close - vpoc) / vpoc <= 0.05: pts += 15

    if layer2: pts += 20
    if layer3: pts += 15

    # Regime bonus
    if regime == "MOMENTUM":  pts += 10
    elif regime == "TRANSITION": pts += 5

    # MFI accumulation bonus
    if mfi_v <= 40: pts += 8
    elif mfi_v <= 50: pts += 4

    # VCP coil bonus
    if vcp_coil == "TIGHT 🟢": pts += 5

    # Sector truth multiplier
    pts *= sector_mult

    # below_tolerance penalty for MA100/MA50 pullbacks (MA200 already vetoed above)
    if below_tolerance and ma_label != "MA200":
        pts *= 0.85   # 15% haircut — still eligible, just deprioritised vs at-support setups

    # Altitude penalty (v5.7 progressive alt_pen, not just binary)
    # alt_stop is already guarded above. Apply graded penalty here:
    if alt_pct > CFG["alt_warn_pct"]:
        # Progressive: every 5% above alt_warn cuts 8% more (capped at -40%)
        excess_bands = min(5, int((alt_pct - CFG["alt_warn_pct"]) / 5))
        alt_pen      = 0.80 * (0.92 ** excess_bands)   # 0.80 → 0.74 → 0.68 …
        pts         *= alt_pen
    elif alt_pct > 30.0:
        pts *= 0.92   # mild early-altitude haircut

    # Forward-looking bonuses
    w52_bonus,  w52_label  = calc_52w_compression(hist, close, atr14)
    atrv_bonus, atrv_label = calc_atr_velocity(hist)
    forward_bonus = w52_bonus + atrv_bonus
    pts += forward_bonus

    pts = min(int(pts), SCORE_WEIGHTS["fortress"] + 30)   # hard cap

    return {
        "fortress_pts":    pts,
        "layer1":          layer1,
        "layer2":          layer2,
        "layer3":          layer3,
        "vcp_coil":        vcp_coil,
        "entry_zone":      entry_zone,
        "entry_band":      entry_band,
        "stop_note":       stop_note,
        "atr_mult":        atr_mult,
        "alt_pct":         round(alt_pct, 2),
        "sector_mult":     round(sector_mult, 3),
        "regime":          regime,
        "mfi":             round(mfi_v, 1),
        "mfi_status":      mfi_status,
        "rsi":             round(rsi_v, 1),
        "adx":             round(adx_v, 1),
        "adx_prev":        round(adx_prev, 1),
        "t1":              t1,
        "t2":              t2,
        "t3":              t3,
        "r1":              r1,
        "r2":              r2,
        "r3":              r3,
        "risk_pct":        risk_pct_val,
        "rr":              rr,
        "atr14_val":       round(atr14, 2),
        "adv20_val":       round(adv20, 0),
        "vpoc_val":        round(vpoc, 2),
        "ma50_val":        round(ma50_v, 2),
        "ma200_val":       round(ma200_v, 2),
        "ma_label":        ma_label,
        "turnover_cr":     round(turnover_cr, 2),
        "w52_bonus":       w52_bonus,
        "w52_label":       w52_label,
        "atrv_bonus":      atrv_bonus,
        "atrv_label":      atrv_label,
        "forward_bonus":   forward_bonus,
        "momentum_velocity_pct": round(velocity, 2),
        # FOG pre-calc (placeholder vix; authoritative value recomputed in assemble_result)
        # fog_block_pre / fog_tier_pre removed — dead code (see audit round 2 note above)
    }


# ══════════════════════════════════════════════════════════════════════
# SECTION 19 — PAPER MODE
# ══════════════════════════════════════════════════════════════════════

def paper_score(symbol: str, hist: pd.DataFrame, close: float) -> dict:
    if len(hist) < 30:
        return {"paper_total":0,"paper_momentum":0,"paper_volume":0,"paper_vpoc":0}
    vpoc  = calc_vpoc(hist, lookback=252)
    atr14 = float(calc_atr(hist, 14).iloc[-1])
    adv20 = float(hist["volume"].tail(20).mean())
    vol   = float(hist["volume"].iloc[-1])
    mfi_v = float(calc_mfi(hist, 14).iloc[-1])
    rsi_v = float(calc_rsi(hist["close"]).iloc[-1])

    # Factor 1: Momentum (50 pts)
    close_20 = float(hist["close"].iloc[-21]) if len(hist) >= 21 else close
    mom_20   = (close-close_20)/close_20*100 if close_20 > 0 else 0
    mom_score = (25 if mom_20 > 10 else 15 if mom_20 > 5 else 10 if mom_20 > 0 else 3)
    rsi_score = (25 if 40<=rsi_v<=65 else 15 if 35<=rsi_v<=70 else 5)
    paper_momentum = min(50, mom_score + rsi_score)

    # Factor 2: Volume (25 pts)
    vol_score = (15 if adv20>0 and vol>=adv20*1.5 else 8 if vol>=adv20 else 0)
    vol_score += (10 if mfi_v<=45 else 5 if mfi_v<=55 else 0)
    paper_volume = min(25, vol_score)

    # Factor 3: VPOC Proximity (25 pts)
    dist = abs(close-vpoc)/atr14 if atr14 > 0 else 99
    vpoc_score = 25 if dist<=0.5 else 18 if dist<=1.0 else 10 if dist<=2.0 else 2
    paper_vpoc = vpoc_score

    return {"paper_total":paper_momentum+paper_volume+paper_vpoc,
            "paper_momentum":paper_momentum,"paper_volume":paper_volume,"paper_vpoc":paper_vpoc}


# ══════════════════════════════════════════════════════════════════════
# SECTION 20 — ASSEMBLE UNIFIED RESULT (v5.7 base)
# ══════════════════════════════════════════════════════════════════════

def get_rank(total: int) -> tuple:
    for threshold, label, alloc in RANKS:
        if total >= threshold and label:
            return label, alloc
    return None, None


def build_story(r: dict) -> str:
    parts = []
    fii = r.get("fii_label","")
    if "BUYING" in fii and "FII+DII" in fii:
        parts.append("institutional tide is in — FII+DII both accumulating")
    elif "FII BUYING" in fii:
        parts.append("foreign money flowing in — FII net buyers")
    ins = r.get("insider_detail","")
    if ins and "buy" in ins.lower():
        parts.append(f"insiders putting own money in ({ins[:50]})")
    fil = r.get("filing_detail","")
    if fil and fil != "—":
        parts.append(f"recent filing: {fil[:50]}")
    earn = r.get("earnings_detail","")
    if "safe runway" in earn: parts.append("clear of earnings risk")
    elif "just announced" in earn: parts.append("fresh results — full visibility")
    elif "SIZE SMALL" in earn: parts.append("⚠️ near earnings — size to 10%")
    l1,l2,l3 = r.get("layer1",False),r.get("layer2",False),r.get("layer3",False)
    layers = sum([l1,l2,l3]); vcp = r.get("vcp_coil",""); mult = r.get("sector_mult",1.0)
    if layers==3 and "TIGHT" in vcp: parts.append("all 3 Fortress layers + VCP coil")
    elif layers>=2: parts.append(f"{layers}/3 Fortress layers at VPOC floor")
    elif "TIGHT" in vcp: parts.append("VCP coil tightening at support")
    if mult >= 1.10: parts.append(f"Sector Truth boost ({mult:.2f}x)")
    w52 = r.get("w52_label","")
    if "ELITE COIL" in w52: parts.append("price coiling at 52W high — breakout imminent 🎯")
    pead = r.get("pead_label","")
    if "HOT PEAD" in pead: parts.append("post-earnings drift active 🔥")
    if not parts: parts.append(f"Fortress score {r.get('score_fortress',0)}/80 — setup active")
    return "; ".join(parts[:4]).capitalize()


def assemble_result(symbol: str, today_row, hist: pd.DataFrame,
                    fii_data: dict, insider_map: dict,
                    filings: dict, earnings_cal: dict,
                    vix_now_cached: float = None) -> Optional[dict]:

    ins_det  = "No insider trades in 30d"; fil_det = "No recent filing"
    earn_det = "—"; ins_pts = 0; fil_pts = 15; earn_pts = 0
    roce_val, roce_label = None, "Not checked"

    fort = fortress_score(symbol, today_row, hist)
    if fort is None:
        return None

    dq = str(today_row.get("data_quality",""))
    if dq in ("SNAPSHOT_FALLBACK","STALE") and fort["fortress_pts"] > 55:
        fort["fortress_pts"] = 55

    fii_pts  = fii_data.get("score", 15)
    fii_lbl  = fii_data.get("label", "—")
    fii_det  = fii_data.get("detail", "—")

    ins_data = insider_map.get(symbol.upper(), {})
    ins_pts  = ins_data.get("score",  ins_pts)
    ins_det  = ins_data.get("detail", ins_det)

    fil_data = filings.get(symbol.upper(), {})
    fil_pts  = fil_data.get("score",  fil_pts)
    fil_det  = fil_data.get("detail", fil_det)

    price = float(today_row["close"])
    # FIX #5 (corrected): skip ROCE proxy only when in yfinance degraded mode —
    # SNAPSHOT_FALLBACK/STALE data means financials are unreliable anyway.
    # In NSE/Sheets mode (EOD_FRESH, SHEETS_EOD, EOD_CACHED) ROCE IS gated
    # because fresh data makes the quality check meaningful and worth the latency.
    # Previous version had this inverted: it ran ROCE for EOD_FRESH and skipped
    # it for Sheets — backwards from the intent.
    _is_yfinance_fallback = (
        str(today_row.get("data_quality","")) in ("SNAPSHOT_FALLBACK", "STALE")
        or FORCE_YFINANCE
    )
    if price < 300 and fil_pts > 15 and not _is_yfinance_fallback:
        roce_val, roce_label = fetch_roce_proxy(symbol)
        if roce_val is None:
            fil_pts = min(fil_pts, 10)
            fil_det = f"{fil_det} | ⚠️ ROCE unverifiable — filing capped"
        elif roce_val < 5.0:
            fil_pts = min(fil_pts, 8)
            fil_det = f"{fil_det} | ❌ {roce_label} — weak fundamentals"
        else:
            fil_det = f"{fil_det} | ✅ {roce_label}"

    earn_pts, earn_det = earnings_safety_score(symbol, earnings_cal)
    pead_bonus, pead_label = calc_pead_bonus(symbol, earnings_cal, hist)
    earn_pts = min(30, earn_pts + pead_bonus)

    total = fort["fortress_pts"] + fii_pts + ins_pts + fil_pts + earn_pts
    total = min(total, MAX_SCORE)

    rank, alloc = get_rank(total)
    if rank is None:
        return None

    close    = float(today_row["close"])
    atr14    = fort.get("atr14_val", 0.0)
    atr_mult = fort.get("atr_mult", 1.75)
    adv20    = fort.get("adv20_val", 1.0)
    adx_v    = fort.get("adx", 20.0)
    adx_prev = fort.get("adx_prev", adx_v)
    mfi_v    = fort.get("mfi", 50.0)
    rsi_v    = fort.get("rsi", 50.0)
    layer3   = fort.get("layer3", False)
    w52_bonus= fort.get("w52_bonus", 0)
    vpoc_val = fort.get("vpoc_val", close)
    t3_val   = fort.get("t3", 0.0)
    ma50_val = fort.get("ma50_val", 0.0)
    ma200_val= fort.get("ma200_val", 0.0)

    # FIX #4: fetch VIX once here and pass it down — eliminates ~200 redundant yfinance calls
    vix_now  = vix_now_cached if vix_now_cached is not None else _get_vix_now()
    cvd      = calc_cvd_divergence(hist, close)
    vsa      = calc_vsa_absorption(hist, atr14 if atr14 > 0 else 1.0,
                                   adv20 if adv20 > 0 else 1.0)
    exh      = calc_momentum_exhaustion(hist, rsi_v, close, adv20 if adv20 > 0 else 1.0)
    exlq     = calc_exit_liquidity(hist, close, rsi_v, vpoc_val,
                                   atr14 if atr14 > 0 else 1.0, adv20 if adv20 > 0 else 1.0)
    fog_enh  = calc_fog_enhanced(adx_v, adx_prev, vix_now, ma50_val, ma200_val, w52_bonus)
    # FIX #1: calc_bayesian_score (4-node) removed here — SN-3 (9-node) in assemble_result_v7
    # is the single source of Bayes truth. Adding both inflated scores by up to +22 pts.
    dyn      = calc_dynamic_score_weights(fii_data, vix_now)

    # FIX #1: score_adj uses only CVD + VSA – Exhaustion (no Bayes bonus here)
    score_adj = cvd["cvd_bonus"] + vsa.get("vsa_bonus",0) - exh["exhaustion_penalty"]
    total     = min(dyn["dyn_max"], max(0, total + score_adj))

    rank, alloc = get_rank(total)
    if rank is None:
        return None

    mc   = calc_monte_carlo_survival(hist, t3_val)
    pos  = calc_position_size(close, atr14 if atr14 > 0 else 1.0, atr_mult)
    trail= calc_trailing_stop(symbol, close, t3_val, atr14 if atr14 > 0 else 1.0, atr_mult)

    result = {
        "symbol":          symbol,
        "sector":          get_sector(symbol),
        "close":           round(close, 2),
        "total_score":     total,
        "max_score":       dyn["dyn_max"],
        "rank":            rank,
        "alloc":           alloc,
        "score_fortress":  fort["fortress_pts"],
        "score_fii":       fii_pts,
        "score_insider":   ins_pts,
        "score_filing":    fil_pts,
        "score_earnings":  earn_pts,
        "t1":              fort["t1"],
        "t2":              fort["t2"],
        "t3":              fort["t3"],
        "r1":              fort["r1"],
        "r2":              fort["r2"],
        "r3":              fort["r3"],
        "risk_pct":        fort["risk_pct"],
        "rr":              fort["rr"],
        "mfi":             fort["mfi"],
        "rsi":             fort["rsi"],
        "adx":             fort["adx"],
        "regime":          fort["regime"],
        "vcp_coil":        fort["vcp_coil"],
        "mfi_status":      fort["mfi_status"],
        "entry_zone":      fort["entry_zone"],
        "entry_band":      fort.get("entry_band","—"),
        "stop_note":       fort.get("stop_note","—"),
        "atr_mult":        atr_mult,
        "alt_pct":         fort["alt_pct"],
        "layer1":          fort["layer1"],
        "layer2":          fort["layer2"],
        "layer3":          layer3,
        "turnover_cr":     fort["turnover_cr"],
        "ma_label":        fort.get("ma_label","MA200"),
        "sector_mult":     fort.get("sector_mult", 1.0),
        "fii_label":       fii_lbl,
        "fii_detail":      fii_det,
        "insider_detail":  ins_det,
        "filing_detail":   fil_det,
        "earnings_detail": earn_det,
        "roce_label":      roce_label,
        "halal":           True,
        "w52_label":       fort.get("w52_label","—"),
        "w52_bonus":       w52_bonus,
        "atrv_label":      fort.get("atrv_label","—"),
        "atrv_bonus":      fort.get("atrv_bonus",0),
        "forward_bonus":   fort.get("forward_bonus",0),
        "pead_label":      pead_label,
        "pead_bonus":      pead_bonus,
        "data_quality":    dq,
        "fog_block":       fog_enh["fog_block"],
        "fog_label":       fog_enh["fog_label"],
        "fog_tier":        fog_enh["fog_tier"],
        "trailing_stop":   trail["trailing_stop"],
        "trailing_label":  trail["trailing_label"],
        "trail_be_active": trail["trail_be_active"],
        "pos_shares":      pos["pos_shares"],
        "pos_amount":      pos["pos_amount"],
        "pos_label":       pos["pos_label"],
        "bayes_prob":      0,    # placeholder — SN-3 9-node Bayes set in assemble_result_v7
        "bayes_bonus":     0,
        "bayes_label":     "—  (see sn_bayes_label for 9-node result)",
        "mc_survival_pct": mc["mc_survival_pct"],
        "mc_label":        mc["mc_label"],
        "cvd_signal":      cvd["cvd_signal"],
        "cvd_label":       cvd["cvd_label"],
        "vsa_absorption":  vsa["vsa_absorption"],
        "vsa_label":       vsa["vsa_label"],
        "vsa_bonus":       vsa.get("vsa_bonus",0),
        "dyn_weight_label":dyn["dyn_label"],
        "exhaustion_flag": exh["exhaustion_flag"],
        "exhaustion_label":exh["exhaustion_label"],
        "exit_liq_flag":   exlq["exit_liq_flag"],
        "exit_liq_label":  exlq["exit_liq_label"],
        "exit_liq_score":  exlq["exit_liq_score"],
        "momentum_velocity_pct": fort.get("momentum_velocity_pct",0.0),
        "atr14_val":       fort.get("atr14_val",0.0),
        "adv20_val":       fort.get("adv20_val",0.0),
        "vpoc_val":        fort.get("vpoc_val",0.0),
    }

    if price < 300:
        cb_active, cb_msg = check_smallcap_circuit_breaker()
        result["alloc"]           = "PROBE 10% ⚠️ CB" if cb_active else result["alloc"]
        result["circuit_breaker"] = cb_msg
    else:
        result["circuit_breaker"] = "N/A (large-cap)"

    result["story"] = build_story(result)

    rt_guard = calc_round_trip_guard(hist, close, result["t1"])
    result.update(rt_guard)

    if result.get("fog_block"):
        result["alloc"] = "PROBE 10% 🌫️"
        # Inject FOG into the directive text so Telegram matches Pine's
        # "FOG — CAUTION · HOLD FIRE" label instead of silently showing
        # the action directive while fog_block is quietly overriding alloc.
        fog_tier = result.get("fog_tier", "FOG_WARNING")
        existing_dir = result.get("sniper_directive", "")
        if "FOG" not in existing_dir:
            result["sniper_directive"] = (
                f"🌫️ {fog_tier} — CAUTION · HOLD FIRE\n"
                f"  ({existing_dir})"
            )
        result["sniper_deploy"] = 0   # hard-zero deploy under fog

    if PAPER_MODE:
        result.update(paper_score(symbol, hist, close))

    return result


# ══════════════════════════════════════════════════════════════════════
# SECTION 21 — v6.0 SNIPER HYBRID SYSTEMS (SN-1 through SN-7)
# ══════════════════════════════════════════════════════════════════════

# ── SN-4: Macro Regime ─────────────────────────────────────────────

def fetch_macro_regime() -> dict:
    try:
        import yfinance as yf
        vix_df   = yf.download("^INDIAVIX", period="5d",  progress=False, auto_adjust=True)
        nifty_df = yf.download("^NSEI",     period="10d", progress=False, auto_adjust=True)
        cnx_df   = yf.download("^CNX500",   period="60d", progress=False, auto_adjust=True)
    except Exception as e:
        log.debug(f"Macro regime fetch failed: {e}")
        return {"macro_state":"CHOP","breadth_ok":True,"vix_val":18.0,
                "nifty_chg":0.0,"cnx500_below_ma50":False}

    vix_val = 18.0
    if not vix_df.empty:
        try: vix_val = float(vix_df["Close"].squeeze().iloc[-1])
        except: pass

    nifty_chg = 0.0
    if not nifty_df.empty and len(nifty_df) >= 2:
        try:
            nc = nifty_df["Close"].squeeze().values
            nifty_chg = (nc[-1]-nc[-2])/nc[-2]*100
        except: pass

    cnx500_below_ma50 = False
    if not cnx_df.empty and len(cnx_df) >= 50:
        try:
            cc = cnx_df["Close"].squeeze()
            cnx500_below_ma50 = float(cc.iloc[-1]) < float(cc.rolling(50).mean().iloc[-1])
        except: pass

    breadth_ok = not cnx500_below_ma50

    if nifty_chg <= SNIPER_CFG["nifty_massacre"]:
        macro_state = "MASSACRE"
    elif vix_val >= SNIPER_CFG["vix_panic"]:
        macro_state = "PANIC"
    elif vix_val >= SNIPER_CFG["vix_chop"]:
        macro_state = "CHOP"
    else:
        nifty_above_ma50 = True
        if not nifty_df.empty and len(nifty_df) >= 50:
            try:
                nc = nifty_df["Close"].squeeze()
                nifty_above_ma50 = float(nc.iloc[-1]) > float(nc.rolling(50).mean().iloc[-1])
            except: pass
        macro_state = "CLEAR" if nifty_above_ma50 else "CHOP"

    log.info(f"Macro: {macro_state} | VIX={vix_val:.1f} | NIFTY {nifty_chg:+.2f}%")
    return {"macro_state":macro_state,"breadth_ok":breadth_ok,
            "vix_val":round(vix_val,2),"nifty_chg":round(nifty_chg,2),
            "cnx500_below_ma50":cnx500_below_ma50}


def _get_macro_regime() -> dict:
    global _MACRO_REGIME_CACHE
    if _MACRO_REGIME_CACHE is not None:
        return _MACRO_REGIME_CACHE
    with _MACRO_REGIME_LOCK:
        if _MACRO_REGIME_CACHE is None:
            _MACRO_REGIME_CACHE = fetch_macro_regime()
    return _MACRO_REGIME_CACHE


# ── SN-1: Composite + Directive ────────────────────────────────────

def calc_sniper_composite(fort: dict, fii_pts: int, macro_state: str,
                           sn_layers: dict = None) -> int:
    """
    SN-1 composite score (0-100).

    IMPORTANT: uses SN-2 layers (sn_layer1..3) when available, NOT the
    fortress scoring layers (layer1/2/3). The two layer sets use different
    VPOC tolerances and liquidity gates. Mixing them inflated the composite
    and caused false PROBE signals (INOXWIND: Python 62 vs Pine 13).
    """
    macro_map = {"CLEAR":100,"CHOP":50,"PANIC":20,"MASSACRE":0}
    macro_score = macro_map.get(macro_state, 50)

    # Prefer SN-2 layers; fall back to fortress layers if SN-2 not yet computed
    if sn_layers:
        l1 = sn_layers.get("sn_layer1", False)
        l2 = sn_layers.get("sn_layer2", False)
        l3 = sn_layers.get("sn_layer3", False)
        vcp_coil = fort.get("vcp_coil","LOOSE") == "TIGHT 🟢"
    else:
        l1 = fort.get("layer1", False)
        l2 = fort.get("layer2", False)
        l3 = fort.get("layer3", False)
        vcp_coil = fort.get("vcp_coil","LOOSE") == "TIGHT 🟢"

    alt_ok  = fort.get("alt_pct", 100) < SNIPER_CFG["alt_warn_pct"]
    sect_ok = fort.get("sector_mult", 1.0) >= 1.0
    vcp_score = ((25 if l1 else 0) + (20 if l2 else 0) + (25 if l3 else 0) +
                 (15 if vcp_coil else 0) + (10 if sect_ok else 0) + (5 if alt_ok else 0))
    rsi_v      = fort.get("rsi", 50.0)
    flow_score = (100 if rsi_v < 40 else 70 if rsi_v < 50 else 40 if rsi_v < 60 else 20)
    composite  = round(macro_score * 0.30 + vcp_score * 0.50 + flow_score * 0.20)
    return min(100, max(0, composite))


def calc_sniper_directive(symbol, fort, result, macro_state, breadth_ok,
                          composite, has_position) -> dict:
    scfg = SNIPER_CFG
    all_layers = fort.get("layer1") and fort.get("layer2") and fort.get("layer3")
    t1=result.get("t1",0.0); t3=result.get("t3",0.0); close=result.get("close",0.0)
    trail_stop=result.get("trailing_stop")
    active_stop=trail_stop if (trail_stop and trail_stop>t3) else t3
    entry_price=None

    is_pristine = (composite>=scfg["score_pristine"] and all_layers
                   and macro_state=="CLEAR" and breadth_ok
                   and fort.get("regime")=="MOMENTUM")
    is_good     = (composite>=scfg["score_good"] and all_layers
                   and macro_state not in ("PANIC","MASSACRE") and breadth_ok)
    is_marginal = (composite>=scfg["score_marginal"] and fort.get("layer1")
                   and fort.get("layer2") and macro_state not in ("PANIC","MASSACRE"))
    is_probe    = (composite>=scfg["score_probe"] and fort.get("layer1")
                   and macro_state!="MASSACRE")

    if macro_state == "MASSACRE":
        return {"sniper_directive":"⚠️ HALT — MARKET MASSACRE","sniper_action":"CLOSE_ALL",
                "sniper_deploy":0,"sniper_entry":None,"sn_active_stop":active_stop,
                "is_pristine":False,"is_good":False,"is_marginal":False,
                "is_probe":False,"all_layers":all_layers}
    elif macro_state == "PANIC":
        return {"sniper_directive":"🔴 HALT — VIX PANIC","sniper_action":"HOLD",
                "sniper_deploy":0,"sniper_entry":None,"sn_active_stop":active_stop,
                "is_pristine":False,"is_good":False,"is_marginal":False,
                "is_probe":False,"all_layers":all_layers}

    if has_position:
        r1_hit=close>=result.get("sn_r1",float("inf"))
        r2_hit=close>=result.get("sn_r2",float("inf"))
        if r2_hit:
            return {"sniper_directive":"📈 HOLD — R2 HIT — trail 2.5×ATR","sniper_action":"TRAIL",
                    "sniper_deploy":0,"sniper_entry":active_stop,"sn_active_stop":active_stop,
                    "is_pristine":is_pristine,"is_good":is_good,"is_marginal":is_marginal,
                    "is_probe":is_probe,"all_layers":all_layers}
        if r1_hit:
            return {"sniper_directive":"🎯 PARTIAL SELL — R1 HIT (30% sell)","sniper_action":"PARTIAL_SELL",
                    "sniper_deploy":0,"sniper_entry":active_stop,"sn_active_stop":active_stop,
                    "is_pristine":is_pristine,"is_good":is_good,"is_marginal":is_marginal,
                    "is_probe":is_probe,"all_layers":all_layers}

    if is_pristine:
        entry_price=t1; deploy=100
        directive=f"⚔️ SNIPER SHOT PRISTINE — BUY @ ₹{t1:.2f}"
    elif is_good:
        entry_price=t1; deploy=75
        directive=f"🟢 GOOD SHOT — BUY @ ₹{t1:.2f}"
    elif is_marginal:
        entry_price=t1*(1-0.005); deploy=50
        directive=f"🟡 MARGINAL — BUY LIMIT ₹{entry_price:.2f}"
    elif is_probe:
        entry_price=t1*(1-0.01); deploy=25
        directive=f"🔵 PROBE — SMALL BUY ₹{entry_price:.2f}"
    else:
        close_vs_t1=((close-t1)/t1*100) if t1>0 else 0
        directive=f"👁️ WATCHING — score {composite}/100 · {close_vs_t1:+.1f}% vs T1"
        deploy=0; entry_price=None

    return {"sniper_directive":directive,"sniper_action":"BUY" if deploy>0 else "WATCH",
            "sniper_deploy":deploy,"sniper_entry":entry_price,"sn_active_stop":active_stop,
            "is_pristine":is_pristine,"is_good":is_good,"is_marginal":is_marginal,
            "is_probe":is_probe,"all_layers":all_layers}


# ── SN-2: 6-Layer VPOC Validation ──────────────────────────────────

def calc_sniper_vpoc_layers(hist, close, atr14, adv20, turnover_cr, vpoc, ma200) -> dict:
    scfg  = SNIPER_CFG
    band  = scfg["vpoc_band_pct"]
    # Layer 1: VPOC alignment
    layer1 = abs(close-vpoc)/vpoc <= band if vpoc>0 else False
    # Layer 2: Volume spikes (≥35 in 252 bars)
    if len(hist) >= 252 and adv20 > 0:
        spike_days = (hist["volume"].tail(252) > 2*adv20).sum()
        layer2 = spike_days >= scfg["vol_spikes_52w"]
    else:
        layer2 = False
    # Layer 3: Pivot bounce recency (45d)
    recency_bars = min(scfg["bounce_recency"], len(hist))
    touches = sum(1 for _,r in hist.tail(recency_bars).iterrows()
                  if abs(float(r["close"])-vpoc)/vpoc <= 0.03) if vpoc>0 else 0
    layer3  = touches >= scfg["min_bounces"]
    # Layer 4: Liquidity gate
    vol_ok  = adv20 > 0 and float(hist["volume"].iloc[-1]) >= scfg["liquidity_mult"]*adv20
    turn_ok = turnover_cr >= scfg["min_turnover_cr"]
    layer4  = vol_ok and turn_ok
    # Layer 5: Structural alignment (close > VPOC OR within fib 61.8%)
    if len(hist) >= 52:
        h52 = float(hist["high"].tail(252).max())
        l52 = float(hist["low"].tail(252).min())
        fib618 = l52 + 0.618*(h52-l52) if h52>l52 else close
        layer5 = close > vpoc or abs(close-fib618)/fib618 <= 0.03
    else:
        layer5 = close >= vpoc
    # Layer 6: Altitude gate (<40% above MA200)
    layer6 = (close-ma200)/ma200*100 < scfg["alt_stop_pct"] if ma200>0 else True

    sn_layer_score = (25 if layer1 else 0)+(20 if layer2 else 0)+(25 if layer3 else 0)+(15 if layer4 else 0)+(10 if layer5 else 0)+(5 if layer6 else 0)
    return {"sn_layer1":layer1,"sn_layer2":layer2,"sn_layer3":layer3,
            "sn_layer4":layer4,"sn_layer5":layer5,"sn_layer6":layer6,
            "sn_all_layers":all([layer1,layer2,layer3,layer4,layer5,layer6]),
            "sn_layer_score":sn_layer_score,"sn_alt_pct":(close-ma200)/ma200*100 if ma200>0 else 0}


# ── SN-3: 9-Node Bayesian ──────────────────────────────────────────

def calc_sniper_bayesian(layer1, layer2, layer3, vcp_coil, mfi_v, cvd_signal,
                         vsa_absorption, breadth_ok, sector_mult, macro_state,
                         adx_v, velocity_pct, alt_pct) -> dict:
    scfg  = SNIPER_CFG
    prior = 0.35
    macro_boost = {"CLEAR":0.65,"CHOP":0.45,"PANIC":0.20,"MASSACRE":0.05}
    nodes = [
        (macro_state=="CLEAR",          macro_boost.get(macro_state,0.45), 0.25),
        (layer1,                        0.72, 0.30),
        (layer2,                        0.68, 0.38),
        (layer3,                        0.70, 0.35),
        (vcp_coil,                      0.75, 0.42),
        (mfi_v <= 45.0,                 0.68, 0.42),
        (cvd_signal == "ACCUMULATION",  0.74, 0.44),
        (vsa_absorption,                0.72, 0.45),
        (breadth_ok,                    0.62, 0.40),
        (sector_mult >= 1.10,           0.65, 0.45),
        (adx_v >= 25.0,                 0.68, 0.38),
        (velocity_pct > 5.0,            0.65, 0.42),
        (alt_pct < 30.0,                0.60, 0.40),
    ]
    posterior = prior
    for condition, p_true, p_false in nodes:
        lk = p_true if condition else p_false
        posterior = (lk*posterior) / max(1e-9, lk*posterior+(1-lk)*(1-posterior))

    # EMA smoothing
    try:
        alpha = scfg["bayes_alpha"]
        posterior = alpha*prior + (1-alpha)*posterior
    except Exception:
        pass

    posterior = min(0.99, max(0.01, round(posterior, 3)))
    bayes_pct = round(posterior*100)
    if posterior >= 0.75: bonus=12; label=f"🧠 Sniper Bayes {bayes_pct}% — VERY HIGH"
    elif posterior >= 0.65: bonus=8; label=f"🧠 Sniper Bayes {bayes_pct}% — HIGH"
    elif posterior >= 0.55: bonus=4; label=f"🧠 Sniper Bayes {bayes_pct}% — moderate"
    elif posterior >= 0.45: bonus=0; label=f"🧠 Sniper Bayes {bayes_pct}% — neutral"
    else: bonus=-5; label=f"🧠 Sniper Bayes {bayes_pct}% — LOW"
    return {"sn_bayes_prob":posterior,"sn_bayes_pct":bayes_pct,
            "sn_bayes_bonus":bonus,"sn_bayes_label":label}


# ── SN-5: Position Sizing ───────────────────────────────────────────

def calc_sniper_position(close, atr14, composite, deploy_pct,
                         account=None) -> dict:
    if account is None: account = ACCOUNT_EQUITY
    if atr14<=0 or close<=0:
        return {"sn_shares":0,"sn_amount":0,"sn_pos_label":"—","sn_risk_pct_actual":0.0}
    scfg=SNIPER_CFG
    risk_rupees  = account*scfg["risk_per_trade"]
    risk_per_sh  = atr14*scfg["atr_stop_mult"]
    shares_vol   = math.floor(risk_rupees/risk_per_sh) if risk_per_sh>0 else 0
    score_factor = (composite/100.0)**0.5
    shares_score = math.floor(shares_vol*score_factor)
    blend        = scfg["score_size_blend"]
    shares_blend = math.floor(shares_vol*(1-blend)+shares_score*blend)
    deploy_factor= deploy_pct/100.0
    shares_final = math.floor(shares_blend*deploy_factor)
    max_shares   = math.floor((account*scfg["max_pos_pct"])/close)
    shares_final = min(shares_final, max_shares)
    pos_amount   = shares_final*close
    risk_actual  = (shares_final*risk_per_sh/account*100 if account>0 else 0.0)
    pos_label    = (f"{shares_final} sh | ₹{pos_amount:,.0f} | {deploy_pct}% deploy | "
                    f"Risk ₹{shares_final*risk_per_sh:,.0f}" if shares_final>0 else "— (below min)")
    return {"sn_shares":shares_final,"sn_amount":round(pos_amount,0),
            "sn_pos_label":pos_label,"sn_risk_pct_actual":round(risk_actual,2),
            "sn_risk_per_share":round(risk_per_sh,2)}


# ── SN-6: Dynamic Exit Plan ─────────────────────────────────────────

def calc_sniper_exit_plan(close, t1, t3, atr14, trail_stop_existing=None) -> dict:
    scfg = SNIPER_CFG
    if t1<=0 or atr14<=0:
        return {"sn_be_trigger":None,"sn_be_active":False,"sn_trail_active":False,
                "sn_trail_stop":t3,"sn_active_stop":t3,
                "sn_r1":t1*1.30,"sn_r2":t1*1.60,"sn_r3":t1*2.00,
                "sn_r1_action":f"Sell {scfg['r1_sell_pct']}% | Move stop to T1",
                "sn_r2_action":f"Sell {scfg['r2_sell_pct']}% | Trail 2.5×ATR",
                "sn_r3_action":f"Sell {scfg['r3_sell_pct']}% | Trail rest aggressively",
                "sn_gain_pct":0.0}
    gain_pct    = ((close-t1)/t1*100) if t1>0 else 0.0
    be_trigger  = t1+atr14*scfg["be_atr_mult"]
    be_active   = close>=be_trigger
    trail_trigger=t1*(1+scfg["trail_trigger_pct"]/100)
    trail_active = close>=trail_trigger
    if trail_active:
        new_trail = close-atr14*scfg["trail_atr_mult"]
        trail_stop = (trail_stop_existing
                      if trail_stop_existing and trail_stop_existing>new_trail
                      else max(new_trail,t3))
    else:
        trail_stop = t3
    active_stop = trail_stop if (trail_active and trail_stop>t3) else t3
    if be_active: active_stop=max(active_stop,t1)
    r1=t1*(1+scfg["r1_pct"]/100); r2=t1*(1+scfg["r2_pct"]/100); r3=t1*(1+scfg["r3_pct"]/100)
    return {"sn_be_trigger":round(be_trigger,2),"sn_be_active":be_active,
            "sn_trail_active":trail_active,"sn_trail_stop":round(trail_stop,2),
            "sn_active_stop":round(active_stop,2),"sn_r1":round(r1,2),
            "sn_r2":round(r2,2),"sn_r3":round(r3,2),
            "sn_r1_action":f"Sell {scfg['r1_sell_pct']}% | Move stop to T1 ₹{t1:.2f}",
            "sn_r2_action":f"Sell {scfg['r2_sell_pct']}% | Trail 2.5×ATR",
            "sn_r3_action":f"Sell {scfg['r3_sell_pct']}% | Trail rest aggressively",
            "sn_gain_pct":round(gain_pct,1)}


# ── Assemble v6.0 enriched result ──────────────────────────────────

def assemble_result_v7(symbol, today_row, hist, fii_data, insider_map,
                       filings, earnings_cal) -> Optional[dict]:
    """Full v7.0 assemble: v5.7 scoring + all 7 Sniper Hybrid systems."""
    # FIX: fetch macro BEFORE calling assemble_result so vix_now_cached is defined.
    # Previously macro was referenced before assignment, causing NameError on every stock.
    # _get_macro_regime() is thread-safe and cached — zero extra network calls.
    macro      = _get_macro_regime()
    macro_state= macro["macro_state"]
    breadth_ok = macro["breadth_ok"]

    result = assemble_result(symbol, today_row, hist, fii_data, insider_map,
                              filings, earnings_cal,
                              vix_now_cached=macro.get("vix_val"))
    if result is None:
        return None

    close  = float(today_row["close"])
    fort = {k: result[k] for k in (
        "layer1","layer2","layer3","vcp_coil","entry_zone","entry_band",
        "stop_note","atr_mult","alt_pct","sector_mult","regime","mfi",
        "mfi_status","rsi","adx","adx_prev","t1","t2","t3","r1","r2","r3",
        "risk_pct","rr","atr14_val","adv20_val","vpoc_val","ma50_val",
        "ma200_val","ma_label","w52_bonus","w52_label","atrv_bonus",
        "atrv_label","forward_bonus","momentum_velocity_pct",
    ) if k in result}
    fort["fortress_pts"] = result.get("score_fortress", 0)

    if macro_state == "MASSACRE":
        result["sniper_directive"] = "⚠️ HALT — MARKET MASSACRE"
        result["sniper_action"]    = "CLOSE_ALL"
        result["macro_state"]      = macro_state
        return result

    atr14      = fort.get("atr14_val", 1.0)
    adv20      = fort.get("adv20_val", 1.0)
    vpoc       = fort.get("vpoc_val", close)
    ma200      = fort.get("ma200_val", 0.0)
    turnover_cr= result.get("turnover_cr", 0.0)

    # SN-2
    layers6 = calc_sniper_vpoc_layers(hist, close, atr14, adv20, turnover_cr, vpoc, ma200)
    result.update(layers6)

    # SN-3
    sn_bayes = calc_sniper_bayesian(
        layer1=layers6["sn_layer1"], layer2=layers6["sn_layer2"],
        layer3=layers6["sn_layer3"], vcp_coil=fort.get("vcp_coil","LOOSE")=="TIGHT 🟢",
        mfi_v=fort.get("mfi",50.0), cvd_signal=result.get("cvd_signal","NEUTRAL"),
        vsa_absorption=result.get("vsa_absorption",False), breadth_ok=breadth_ok,
        sector_mult=fort.get("sector_mult",1.0), macro_state=macro_state,
        adx_v=fort.get("adx",20.0), velocity_pct=fort.get("momentum_velocity_pct",0.0),
        alt_pct=fort.get("alt_pct",0.0),
    )
    result.update(sn_bayes)
    result["total_score"] = min(MAX_SCORE, result["total_score"] + sn_bayes["sn_bayes_bonus"])

    # SN-1 composite — pass SN-2 layers so composite uses the stricter 6-layer
    # validation gates rather than fortress scoring layers (prevents inflation)
    composite = calc_sniper_composite(fort, result.get("score_fii",15), macro_state,
                                      sn_layers=layers6)
    result["sniper_composite"] = composite

    # SN-6 exit plan
    t1=result.get("t1",close); t3=result.get("t3",close*0.90)
    exit_plan = calc_sniper_exit_plan(close, t1, t3, atr14, result.get("trailing_stop"))
    result.update(exit_plan)
    result["r1"]=exit_plan["sn_r1"]; result["r2"]=exit_plan["sn_r2"]; result["r3"]=exit_plan["sn_r3"]

    # SN-1 directive
    # FIX #3: SQLite position table is the ONLY source of truth for position ownership.
    # The old `close > t1*1.03` heuristic emitted PARTIAL_SELL/TRAIL for stocks
    # the user never entered whenever price happened to trade 3% above VPOC floor.
    has_position = _get_position(symbol) is not None
    directive = calc_sniper_directive(symbol, fort, result, macro_state,
                                      breadth_ok, composite, has_position)
    result.update(directive)

    # ── FOG post-directive override ──────────────────────────────────
    # assemble_result() already set fog_block and overrode alloc to PROBE 10% 🌫️
    # but the directive text was set before FOG was checked. Re-apply here
    # so the Telegram directive label matches Pine's "FOG — CAUTION · HOLD FIRE".
    if result.get("fog_block"):
        fog_tier = result.get("fog_tier", "FOG_WARNING")
        existing_dir = result.get("sniper_directive", "")
        if "FOG" not in existing_dir:
            result["sniper_directive"] = (
                f"🌫️ {fog_tier} — CAUTION · HOLD FIRE\n"
                f"  ({existing_dir})"
            )
        result["sniper_deploy"] = 0   # hard-zero deploy under fog

    # SN-5 sizing — recompute after fog may have zeroed deploy
    sn_pos = calc_sniper_position(close, atr14, composite,
                                   result.get("sniper_deploy", directive["sniper_deploy"]))
    result.update(sn_pos)

    result["macro_state"] = macro_state
    result["breadth_ok"]  = breadth_ok
    result["vix_val"]     = macro.get("vix_val", 18.0)
    result["nifty_chg"]   = macro.get("nifty_chg", 0.0)
    return result


# ══════════════════════════════════════════════════════════════════════
# SECTION 22 — OUTPUT HELPERS
# ══════════════════════════════════════════════════════════════════════

def _escape_md(s) -> str:
    # FIX #3: use raw strings to avoid SyntaxWarning (will be SyntaxError in Python 3.13)
    if s is None: return ""
    return str(s).replace("_", r"\_").replace("*", r"\*").replace("`", r"\`").replace("[", r"\[")

def _score_bar(score, max_score, color="#7c3aed", width=80) -> str:
    pct = min(100, max(0, score/max_score*100)) if max_score>0 else 0
    bar_w = int(width*pct/100)
    return (f'<div style="background:#e5e7eb;border-radius:4px;height:8px;width:{width}px;display:inline-block">'
            f'<div style="background:{color};height:8px;border-radius:4px;width:{bar_w}px"></div></div>'
            f' <span style="font-size:11px;color:#555">{score}/{max_score}</span>')

def _mini_bar(score, max_score) -> str:
    pct = min(100, max(0, score/max_score*100)) if max_score>0 else 0
    return f"{'█'*int(pct/10)}{'░'*(10-int(pct/10))} {score}/{max_score}"

def _dq_badge(dq: str) -> str:
    badges = {"EOD_FRESH":"🟢 FRESH","SHEETS_EOD":"📊 SHEETS","EOD_CACHED":"✅ CACHED",
              "SNAPSHOT_FALLBACK":"⚠️ SNAPSHOT","STALE":"❌ STALE"}
    return badges.get(dq, dq)

def _rank_medal(rank: str) -> str:
    if "ELITE" in rank:    return "⚔️"
    if "PRISTINE" in rank: return "🟢"
    if "HIGH" in rank:     return "🟡"
    if "MODERATE" in rank: return "🟠"
    if "PROBE" in rank:    return "🔵"
    return "▪️"

def _split_telegram_message(msg: str, limit: int = 4000) -> list:
    if len(msg) <= limit:
        return [msg]
    lines  = msg.split("\n")
    chunks = []; cur = ""
    for line in lines:
        if len(cur)+len(line)+1 > limit:
            chunks.append(cur); cur = line+"\n"
        else:
            cur += line+"\n"
    if cur.strip(): chunks.append(cur)
    return chunks


def validate_telegram_token(token: str) -> tuple:
    if not token or token.strip() == "":
        return False, "EMPTY_TOKEN ❌"
    parts = token.strip().split(":")
    if len(parts) != 2 or not parts[0].isdigit() or len(parts[1]) < 30:
        return False, f"MALFORMED_TOKEN ❌ — expected 'bot_id:hash', got {token[:20]}..."
    try:
        resp = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        if resp.status_code == 200:
            bot_name = resp.json().get("result", {}).get("username","unknown")
            return True, f"Token valid ✅ — bot: @{bot_name}"
        return False, f"HTTP {resp.status_code} from Telegram"
    except Exception as e:
        return False, f"Network error: {e}"


# ── SN-7: Sniper Telegram Format ───────────────────────────────────

def send_telegram_v7(top5, sector_trends, fii_data, date_label, macro,
                     using_fallback=False, data_source="NSE"):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.info("Telegram not configured — skipping")
        return
    token_ok, token_msg = validate_telegram_token(TELEGRAM_TOKEN)
    if not token_ok:
        log.error(f"Telegram SKIPPED — {token_msg}")
        return

    macro_state=macro.get("macro_state","CHOP"); vix_val=macro.get("vix_val",0.0)
    nifty_chg=macro.get("nifty_chg",0.0); breadth_ok=macro.get("breadth_ok",True)
    macro_icon={"CLEAR":"✅","CHOP":"⚠️","PANIC":"🔴","MASSACRE":"⚠️"}.get(macro_state,"↔")
    trending=[k for k,v in sector_trends.items() if "STRONG" in v.get("trend","")]
    sector_line=("🔥 "+" | ".join(s.replace("NIFTY ","") for s in trending)
                 if trending else "No strong sectors today")

    # Data source banner
    src_badge = {"NSE":"🟢 NSE Live","SHEETS":"📊 Google Sheets","YFINANCE":"⚠️ yfinance Watchlist"}.get(data_source,"—")

    lines = [
        f"⚔️ *FORTRESS SNIPER v7.0* | `{date_label}`",
        f"🕌 _Halal · Unified · 9-node Bayes · 6-layer VPOC · CVD · VSA_",
        f"📡 Data: {src_badge}",
    ]
    if using_fallback:
        lines.append("⚠️ *DEGRADED* — Sheets/NSE blocked · yfinance watchlist only")
    lines += [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🌍 *Macro:* {macro_icon} {macro_state} | VIX {vix_val:.1f} | NIFTY {nifty_chg:+.2f}%",
        f"   Breadth: {'✅ CNX500 above MA50' if breadth_ok else '🔴 CNX500 below MA50 — CAUTION'}",
        f"📊 *Sectors:* {sector_line}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    if macro_state == "MASSACRE":
        lines += ["","⚠️ *MARKET MASSACRE — ALL ENTRIES HALTED*",
                  "_NIFTY collapsed ≥3%. Close open positions._"]
    elif macro_state == "PANIC":
        lines += ["","🔴 *VIX PANIC — ENTRIES HALTED*",
                  "_India VIX ≥22. Wait for fear to subside._"]
    elif not top5:
        lines += ["","📭 *No halal sniper setups passed all filters today*"]
    else:
        lines.append(f"🎯 *TODAY'S SNIPER SETUPS ({len(top5)})*")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        for i, r in enumerate(top5, 1):
            sym       = _escape_md(r["symbol"])
            directive = _escape_md(r.get("sniper_directive","MONITOR"))
            entry     = r.get("sniper_entry") or r.get("t1")
            stop      = r.get("sn_active_stop") or r.get("t3")
            # Guard against None — fall back to em-dash so f-string never raises
            entry_fmt = f"₹{entry:.2f}" if entry is not None else "—"
            stop_fmt  = f"₹{stop:.2f}"  if stop  is not None else "—"
            r1=r.get("sn_r1") or r.get("r1"); r2=r.get("sn_r2") or r.get("r2")
            r3=r.get("sn_r3") or r.get("r3")
            composite = r.get("sniper_composite",0); bayes_pct=r.get("sn_bayes_pct") or r.get("bayes_prob",0)
            mc_pct=r.get("mc_survival_pct"); deploy=r.get("sniper_deploy",0)
            pos_label=_escape_md(r.get("sn_pos_label") or r.get("pos_label","—"))
            risk_pct=r.get("risk_pct") or "—"; rr=r.get("rr") or "—"
            rank=r.get("rank","—"); total=r.get("total_score",0); max_s=r.get("max_score",MAX_SCORE)
            sector=_escape_md(r.get("sector","—")); close_px=r.get("close",0.0)
            vel=r.get("momentum_velocity_pct",0.0); dq=_dq_badge(r.get("data_quality",""))
            l1="✓" if r.get("sn_layer1") else "✗"; l2="✓" if r.get("sn_layer2") else "✗"
            l3="✓" if r.get("sn_layer3") else "✗"; l4="✓" if r.get("sn_layer4") else "✗"
            l5="✓" if r.get("sn_layer5") else "✗"; l6="✓" if r.get("sn_layer6") else "✗"
            warn_badges=[]
            if r.get("exhaustion_flag"): warn_badges.append("⚠️EXHST")
            if r.get("exit_liq_flag"):   warn_badges.append("🚨EXLIQ")
            if r.get("fog_block"):       warn_badges.append("🌫️FOG")
            if r.get("data_quality") == "SNAPSHOT_FALLBACK": warn_badges.append("⚠️SNAP")
            warn_str="  "+"  ".join(warn_badges) if warn_badges else ""
            signals=[]
            if "ACCUMULATION" in r.get("cvd_signal",""): signals.append("CVD🟢")
            if r.get("vsa_absorption"):  signals.append("VSA🟢")
            if r.get("w52_bonus",0)>0:   signals.append(f"52W🎯+{r.get('w52_bonus',0)}")
            if r.get("pead_bonus",0)>0:  signals.append(f"PEAD+{r.get('pead_bonus',0)}")
            if r.get("atrv_bonus",0)>0:  signals.append(f"ATR⚡+{r.get('atrv_bonus',0)}")
            sig_str="   📡 "+" · ".join(signals) if signals else ""
            story=_escape_md(r.get("story","—"))
            pick=[
                "",
                f"┌{'─'*30}",
                f"│ {'⚔️' if r.get('is_pristine') else '🟢' if r.get('is_good') else '🟡' if r.get('is_marginal') else '🔵'} "
                f"*#{i} — {sym}*  ₹{close_px}  {dq}{warn_str}",
                f"│ {rank}  ·  {sector}",
                f"└{'─'*30}",
                "",
                f"📌 *{directive}*",
                "",
                f"🔫 *Entry:* {entry_fmt}  →  *Stop:* {stop_fmt}",
                f"🎯 *Targets:*  R1 ₹{r1:.2f} ({SNIPER_CFG['r1_pct']:.0f}%)  ·  "
                f"R2 ₹{r2:.2f} ({SNIPER_CFG['r2_pct']:.0f}%)  ·  "
                f"R3 ₹{r3:.2f} ({SNIPER_CFG['r3_pct']:.0f}%)",
                "",
                f"📊 *Score:* `{total}/{max_s}` ({round(total/max_s*100)}%)  "
                f"Sniper `{composite}/100`  Bayes `{bayes_pct}%`",
                f"   L1{l1} L2{l2} L3{l3} L4{l4} L5{l5} L6{l6}  |  Vel {vel:+.1f}%",
                "",
                f"💼 *Size:* {deploy}% deploy  ·  {pos_label}",
                f"   Risk {risk_pct}%  ·  RR {rr}x"
                + (f"  ·  MC Survival {mc_pct}%" if mc_pct is not None else ""),
            ]
            if sig_str: pick.append(sig_str)
            if r.get("sn_be_active"):
                pick.append(f"   🔒 BE ARMED — stop → T1 ₹{r.get('t1',0):.2f}")
            if r.get("sn_trail_active"):
                pick.append(f"   📈 TRAIL ACTIVE — stop ₹{r.get('sn_trail_stop',0):.2f}")
            pick += ["", f"📋 _{story}_"]
            lines += pick

    lines += ["","━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
              "_v7.0 · Unified · 9-node Bayes · 6-layer VPOC · CVD · VSA · MC · Sheets_"]
    msg   = "\n".join(lines)
    token = TELEGRAM_TOKEN.strip()
    all_ids = [TELEGRAM_CHAT_ID] + (TELEGRAM_SHARE_IDS or [])
    for chat_id in all_ids:
        for chunk_idx, chunk in enumerate(_split_telegram_message(msg), 1):
            payload={"chat_id":chat_id,"text":chunk,"parse_mode":"Markdown"}
            try:
                resp = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                     data=payload, timeout=15, verify=True)
                if resp.status_code==200: log.info(f"Telegram chunk {chunk_idx} sent ✓")
                else: log.error(f"Telegram HTTP {resp.status_code}: {resp.text[:200]}")
            except Exception as e:
                log.error(f"Telegram send error: {e}"); break


# ══════════════════════════════════════════════════════════════════════
# SECTION 23 — SECTOR TRENDS
# ══════════════════════════════════════════════════════════════════════

def get_sector_trends() -> dict:
    trends = {}
    for name, idx in list(SECTOR_INDICES.items())[:6]:
        try:
            h = fetch_history(f"^{idx}", days=30)
            if len(h)<5: trends[name]={"trend":"NEUTRAL","label":"—"}; continue
            c=h["close"].values; ma20=float(pd.Series(c).rolling(20).mean().iloc[-1]) if len(c)>=20 else c[-1]
            last=c[-1]; up3=sum(1 for i in range(1,min(3,len(c))) if c[-i]>c[-i-1])
            trend=("🔥 STRONG" if last>ma20 and up3>=2 else
                   "✓ BULLISH" if last>ma20 else
                   "↔ WEAK"   if last>float(pd.Series(c).rolling(5).mean().iloc[-1]) else "⚠ BEARISH")
            trends[name]={"trend":trend,"label":trend}
            time.sleep(0.2)
        except Exception as e:
            log.warning(f"Sector {name}: {e}")
            trends[name]={"trend":"NEUTRAL","label":"—"}
    return trends


# ══════════════════════════════════════════════════════════════════════
# SECTION 24 — GOOGLE SHEETS OUTPUT (push results)
# ══════════════════════════════════════════════════════════════════════

def push_to_gsheets(top5: list, date_label: str):
    """
    Write screener output to Tab 6 — SCREENER.

    Uses the cached workbook opened during _init_sheets_client().
    One clear() + one batch append = 2 API write calls total.
    Tab is created automatically if it does not exist.
    """
    if not _sheets_configured():
        log.info("Google Sheets not configured — skipping output push")
        return
    if not _init_sheets_client():
        log.warning("push_to_gsheets: sheets client not ready — skipping")
        return
    try:
        # Try cached worksheet first; create if absent
        ws = _get_worksheet(SHEET_SCREENER)
        if ws is None:
            log.info(f"  Creating output tab '{SHEET_SCREENER}' ...")
            ws = _sheets_retry(
                _GS_WORKBOOK.add_worksheet,
                title=SHEET_SCREENER, rows=200, cols=35,
                label=f"add_worksheet({SHEET_SCREENER})"
            )
            _GS_WS_CACHE[SHEET_SCREENER] = ws

        _sheets_retry(ws.clear, label=f"clear({SHEET_SCREENER})")

        headers = [
            "Date","Symbol","Sector","Total Score","Max","Rank","Alloc",
            "Fortress/80","FII/30","Insider/30","Filing/30","Earnings/30",
            "Sniper Composite","Bayes%","Directive",
            "T1 Floor","T3 Stop","R1","R2","R3","RR",
            "Entry Zone","VCP","Regime","Sector Mult",
            "MC Survival%","Data Quality","Story",
        ]
        rows_to_write = [headers]
        for r in top5:
            rows_to_write.append([
                date_label,
                r["symbol"],
                r.get("sector","—"),
                r["total_score"],
                r.get("max_score", MAX_SCORE),
                r.get("rank","—"),
                r.get("alloc","—"),
                r.get("score_fortress", 0),
                r.get("score_fii", 0),
                r.get("score_insider", 0),
                r.get("score_filing", 0),
                r.get("score_earnings", 0),
                r.get("sniper_composite","—"),
                r.get("sn_bayes_pct","—"),
                r.get("sniper_directive","—"),
                r.get("t1","—"),
                r.get("t3","—"),
                r.get("sn_r1","—"),
                r.get("sn_r2","—"),
                r.get("sn_r3","—"),
                r.get("rr","—"),
                r.get("entry_zone","—"),
                r.get("vcp_coil","—"),
                r.get("regime","—"),
                r.get("sector_mult","—"),
                r.get("mc_survival_pct","—"),
                r.get("data_quality","—"),
                r.get("story",""),
            ])

        # Single batch update — 1 API write call for all rows
        # FIX #6 (hardened per audit round 2): gspread ≥6.0 uses update(range_name, values).
        # gspread <6.0 uses update(values) or update(range_name, values).
        # Use try/except to handle both versions gracefully instead of version-sniffing.
        try:
            _sheets_retry(
                ws.update, "A1", rows_to_write,
                label=f"batch_update({SHEET_SCREENER})"
            )
        except TypeError:
            # gspread <6.0 fallback: positional arg is values directly
            _sheets_retry(
                ws.update, rows_to_write,
                label=f"batch_update_legacy({SHEET_SCREENER})"
            )
        log.info(f"  Google Sheets Tab '{SHEET_SCREENER}' updated: {len(top5)} picks ✅")
    except Exception as e:
        log.error(f"push_to_gsheets failed: {e}")


def save_excel(top5: list, all_results: list, date_label: str, fii_data: dict):
    if not top5 and not all_results:
        return
    try:
        EXCEL_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(EXCEL_OUTPUT_PATH, engine="openpyxl") as writer:
            pd.DataFrame(top5).to_excel(writer, sheet_name="Top Picks", index=False)
            pd.DataFrame(all_results).to_excel(writer, sheet_name="All Results", index=False)
            pd.DataFrame([fii_data]).to_excel(writer, sheet_name="FII_DII", index=False)
        log.info(f"Excel saved: {EXCEL_OUTPUT_PATH}")
    except Exception as e:
        log.error(f"Excel save failed: {e}")


def save_html_report(top5: list, date_label: str, fii_data: dict, sector_trends: dict):
    try:
        HTML_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        rows = ""
        for i, r in enumerate(top5, 1):
            rank = r.get("rank","—"); score = r.get("total_score",0)
            max_s= r.get("max_score",MAX_SCORE); sym = r["symbol"]
            directive = r.get("sniper_directive","—"); composite = r.get("sniper_composite","—")
            entry = r.get("sniper_entry") or r.get("t1","—"); stop = r.get("sn_active_stop") or r.get("t3","—")
            rows += f"""<tr>
              <td>{i}</td><td><b>{sym}</b><br><small>{r.get('sector','—')}</small></td>
              <td>{score}/{max_s}<br><small>{rank}</small><br>
                  <small style="color:#7c3aed">Sniper {composite}/100</small></td>
              <td><small>{directive}</small></td>
              <td>
                <table style="font-size:11px;border-collapse:collapse">
                  <tr><td style="color:#555;padding:1px 4px">Fortress</td>
                      <td>{_score_bar(r.get('score_fortress',0),80,'#7c3aed',60)}</td></tr>
                  <tr><td style="color:#555;padding:1px 4px">FII/DII</td>
                      <td>{_score_bar(r.get('score_fii',0),30,'#0891b2',60)}</td></tr>
                  <tr><td style="color:#555;padding:1px 4px">Insider</td>
                      <td>{_score_bar(r.get('score_insider',0),30,'#16a34a',60)}</td></tr>
                  <tr><td style="color:#555;padding:1px 4px">Filing</td>
                      <td>{_score_bar(r.get('score_filing',0),30,'#ca8a04',60)}</td></tr>
                  <tr><td style="color:#555;padding:1px 4px">Earnings</td>
                      <td>{_score_bar(r.get('score_earnings',0),30,'#dc2626',60)}</td></tr>
                </table>
              </td>
              <td>₹{entry}<br><small style="color:#16a34a">Entry</small></td>
              <td>₹{stop}<br><small style="color:#dc2626">Stop</small></td>
              <td>₹{r.get('sn_r1','—')} / ₹{r.get('sn_r2','—')} / ₹{r.get('sn_r3','—')}</td>
              <td><small style="color:#555;font-style:italic">{r.get('story','—')}</small></td>
            </tr>"""

        sector_html = "".join(
            f'<span style="margin:4px;padding:4px 10px;border-radius:12px;background:#f3f4f6;'
            f'font-size:13px">{sec}: {v.get("label","—")}</span>'
            for sec,v in sector_trends.items()
        )

        html = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>⚔️ Fortress Sniper v7.0 | {date_label}</title>
<style>body{{font-family:system-ui,sans-serif;margin:0;padding:20px;background:#f9fafb;color:#111}}
h1{{font-size:22px;margin:0 0 4px}}.meta{{color:#666;font-size:14px;margin-bottom:20px}}
.card{{background:#fff;border-radius:12px;border:1px solid #e5e7eb;padding:20px;margin-bottom:16px}}
table{{border-collapse:collapse;width:100%}}
th{{background:#f3f4f6;padding:10px 12px;text-align:left;font-size:13px;color:#555;border-bottom:1px solid #e5e7eb}}
td{{padding:10px;border-bottom:1px solid #f3f4f6;vertical-align:top;font-size:13px}}
</style></head><body>
<h1>⚔️ Fortress Sniper v7.0 — Unified Engine</h1>
<div class="meta">🕌 Halal | 9-node Bayes | 6-layer VPOC | Google Sheets data source | {date_label}</div>
<div class="card">
  <b>🧠 Market Intelligence</b>
  <div style="background:#e0f2fe;border-radius:8px;padding:12px 16px;margin:12px 0">
    <b>{fii_data.get('label','—')}</b> &nbsp; {fii_data.get('detail','—')} &nbsp;
    <span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:10px;font-size:11px">Score {fii_data.get('score',0)}/30</span>
  </div>
  <div>{sector_html}</div>
</div>
<div class="card">
  <b>🎯 Top {len(top5)} Halal Sniper Picks</b>
  <table style="margin-top:12px">
    <tr><th>#</th><th>Symbol</th><th>Score</th><th>Directive</th>
        <th>Score Breakdown</th><th>Entry</th><th>Stop</th><th>Targets</th><th>Story</th></tr>
    {rows}
  </table>
</div>
<div class="meta" style="margin-top:20px;text-align:center">
  Fortress Screener v7.0 · Unified · Halal · NSE EQ · Not financial advice
</div></body></html>"""
        HTML_OUTPUT_PATH.write_text(html, encoding="utf-8")
        log.info(f"HTML report saved: {HTML_OUTPUT_PATH}")
    except Exception as e:
        log.error(f"HTML save failed: {e}")


# ══════════════════════════════════════════════════════════════════════
# SECTION 25 — MAIN SCREENER LOOP (v7.0 unified)
# ══════════════════════════════════════════════════════════════════════

def run_screener_v7():
    """
    v7.0 main entry point.

    Data priority:
      1. NSE bhavcopy (live, full 2000+ universe)
      2. Google Sheets 'Bhavcopy' tab (your manual data)
      3. yfinance batch (300-stock watchlist, last resort)

    Intelligence data (FII, Insider, Filings, Earnings) follows same
    NSE → Sheets → yfinance priority per data type.

    Scoring: v5.7 200-pt engine + SN-1 to SN-7 sniper enrichment.
    """
    _init_db()
    date_str, date_label = get_last_trading_day()
    log.info(f"=== FORTRESS SNIPER v7.0 | {date_label} ===")
    log.info(f"    FORCE_SHEETS={FORCE_SHEETS} | FORCE_YFINANCE={FORCE_YFINANCE}")

    # ── SN-4 macro regime (fetch once, thread-safe cache) ───────────
    macro = _get_macro_regime()
    log.info(f"Macro: {macro['macro_state']} | VIX={macro['vix_val']:.1f}")

    # ── 1. BHAVCOPY DATA SOURCE ──────────────────────────────────────
    bhavcopy       = None
    using_fallback = False
    data_source    = "NSE"

    if FORCE_YFINANCE:
        log.info("FORCE_YFINANCE=true — skipping NSE + Sheets")
    elif FORCE_SHEETS:
        log.info("FORCE_SHEETS=true — skipping NSE, reading from Google Sheets")
        bhavcopy    = load_bhavcopy_from_sheets()
        data_source = "SHEETS"
    else:
        # Try NSE bhavcopy for last 6 days
        for days_back in range(0, 6):
            try:
                d = datetime.today() - timedelta(days=days_back)
                while d.weekday() >= 5:
                    d -= timedelta(days=1)
                attempt_str = d.strftime("%d%m%Y")
                log.info(f"Trying NSE bhavcopy for {attempt_str}...")
                raw      = download_bhavcopy(attempt_str)
                bhavcopy = clean_bhavcopy(raw)
                if not bhavcopy.empty:
                    date_str   = attempt_str
                    date_label = d.strftime("%Y-%m-%d")
                    log.info(f"✅ NSE bhavcopy loaded: {len(bhavcopy)} EQ records")
                    data_source = "NSE"
                    break
            except Exception as e:
                log.warning(f"NSE bhavcopy {attempt_str}: {e}")
                time.sleep(1)

    # ── 2. SHEETS FALLBACK (if NSE failed) ──────────────────────────
    if (bhavcopy is None or bhavcopy.empty) and not FORCE_YFINANCE:
        log.warning("NSE bhavcopy unavailable — trying Google Sheets Bhavcopy tab...")
        bhavcopy    = load_bhavcopy_from_sheets()
        data_source = "SHEETS"
        if not bhavcopy.empty:
            log.info(f"✅ Bhavcopy from Sheets: {len(bhavcopy)} records")

    # ── 3. YFINANCE LAST RESORT ──────────────────────────────────────
    if bhavcopy is None or bhavcopy.empty:
        log.warning("="*60)
        log.warning("⚠️ DEGRADED MODE — NSE + Sheets unavailable")
        log.warning("   Falling back to yfinance ~300 symbol watchlist")
        log.warning("="*60)
        bhavcopy       = build_yfinance_universe()
        using_fallback = True
        data_source    = "YFINANCE"
        if bhavcopy.empty:
            log.error("❌ All data sources failed. Aborting.")
            return []

    # ── Pre-filter ───────────────────────────────────────────────────
    candidates = bhavcopy[
        (bhavcopy["turnover_lakhs"] >= CFG["turnover_lakhs"]) &
        (bhavcopy["close"] >= 50) &
        (bhavcopy["close"] <= 10000)
    ].copy()
    log.info(f"After liquidity filter: {len(candidates)}")
    candidates = candidates[candidates["symbol"].apply(is_halal)].copy()
    log.info(f"After halal filter: {len(candidates)}")
    if len(candidates) > CFG["max_candidates"]:
        candidates = candidates.nlargest(CFG["max_candidates"], "turnover_lakhs")
        log.info(f"Terminal Governor: capped to {CFG['max_candidates']}")

    # ── Intelligence data (all 5 sources) ───────────────────────────
    log.info("Fetching FII/DII (NSE → Sheets → proxy)...")
    fii_data     = fetch_fii_dii()

    log.info("Fetching insider trades (NSE → Sheets → yfinance)...")
    insider_map  = fetch_insider_trades(days_back=30)

    log.info("Fetching corporate filings (NSE → Sheets → yfinance)...")
    filings      = fetch_recent_filings(days_back=14)

    log.info("Fetching earnings calendar (NSE → Sheets → yfinance)...")
    earnings_cal = fetch_earnings_calendar()

    # ── Shared NSE session for history loop ──────────────────────────
    log.info("Building shared NSE session for history fetch loop...")
    _shared_nse_sess = nse_session()

    # ── Main stock scoring loop ──────────────────────────────────────
    results = []
    for i, (_, row) in enumerate(candidates.iterrows()):
        sym = row["symbol"]
        if i % 25 == 0: log.info(f"Progress: {i}/{len(candidates)}")
        try:
            hist = fetch_history(sym, days=300, sess=_shared_nse_sess)
            if len(hist) < CFG["min_hist_bars"]:
                log.debug(f"{sym}: only {len(hist)} bars — skipped")
                continue
            r = assemble_result_v7(sym, row, hist, fii_data, insider_map,
                                    filings, earnings_cal)
            if r: results.append(r)
            time.sleep(0.15)
        except Exception as e:
            log.debug(f"{sym}: {e}")

    results.sort(key=lambda x: (x.get("sniper_composite",0), x.get("total_score",0)), reverse=True)

    # FIX #2: 3-bucket picker — large caps (≥₹2000) were previously thrown into
    # overflow and never considered. Now they get their own LARGE_CAP_PICKS slot.
    MAX_PER_SECTOR = 2
    sector_counts: dict = {}
    large_picks=[]; mid_picks=[]; small_picks=[]; overflow=[]
    for r in results:
        price=r["close"]
        if price >= 2000:        large_picks.append(r)
        elif 200 <= price < 2000: mid_picks.append(r)
        elif 50 <= price < 200:   small_picks.append(r)
        else:                     overflow.append(r)

    def _pick_bucket(bucket, n, sc):
        picked=[]
        for r in bucket:
            if len(picked)>=n: break
            sec=r["sector"]; count=sc.get(sec,0)
            if count<MAX_PER_SECTOR:
                picked.append(r); sc[sec]=count+1
        return picked

    top5 = (_pick_bucket(large_picks, LARGE_CAP_PICKS, sector_counts) +
            _pick_bucket(mid_picks,   MID_CAP_PICKS,   sector_counts) +
            _pick_bucket(small_picks, SMALL_CAP_PICKS,  sector_counts))

    log.info(f"=== TOP {len(top5)} PICKS | {len(results)} total passed ===")
    for r in top5:
        log.info(f"  {r['symbol']:12s} | {r.get('total_score',0):3d}/{MAX_SCORE} "
                 f"| {r.get('rank','—'):15s} | Sniper {r.get('sniper_composite',0)}/100 "
                 f"| {r.get('sniper_directive','—')[:40]}")

    if using_fallback:
        fii_data["_fallback_note"] = "⚠️ NSE+Sheets unavailable — yfinance fallback"

    # ── Paper Mode comparison ────────────────────────────────────────
    if PAPER_MODE and top5:
        log.info("\n=== PAPER MODE COMPARISON ===")
        log.info(f"{'Symbol':<12} {'Live':>6} {'Paper':>6} {'Delta':>6} {'Signal'}")
        log.info("-"*45)
        for r in top5:
            live  = r.get("total_score",0); paper = r.get("paper_total",0)
            delta = live-paper
            signal = "✅ aligned" if abs(delta)<=20 else "⚠️ moderate" if abs(delta)<=40 else "🔴 review"
            log.info(f"  {r['symbol']:<12} {live:>6} {paper:>6} {delta:>+6} {signal}")

    # ── Outputs ──────────────────────────────────────────────────────
    log.info("Saving Excel report...")
    save_excel(top5, results, date_label, fii_data)

    log.info("Fetching sector trends...")
    sector_trends = get_sector_trends()

    log.info("Saving HTML report...")
    save_html_report(top5, date_label, fii_data, sector_trends)

    log.info("Pushing to Google Sheets (Screener tab)...")
    push_to_gsheets(top5, date_label)

    log.info("Sending Telegram...")
    send_telegram_v7(top5, sector_trends, fii_data, date_label, macro,
                     using_fallback, data_source)

    log.info(f"✅ Done | {len(top5)} setups | Macro: {macro['macro_state']} | "
             f"VIX: {macro['vix_val']:.1f} | Data: {data_source}")
    return top5


# ══════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    run_screener_v7()
