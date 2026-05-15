"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   UNIFIED HALAL SNIPER v1.0 — FORTRESS × APEX FUSED ENGINE                ║
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
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)
for _noisy in ("yfinance", "peewee", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.CRITICAL)

VERSION = "UNIFIED v1.0"

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

SHARIAH_TTL_DAYS = int(os.getenv("SHARIAH_CACHE_TTL_DAYS", "1"))
APEX_TOP_N       = int(os.getenv("APEX_TOP_N", "5"))
APEX_MIN_SCORE   = int(os.getenv("APEX_MIN_SCORE", "48"))

MC_SIMS    = int(os.getenv("MC_SIMS", "600"))
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

_SECTOR_LIVE_CACHE: Dict[str, str] = {}


def get_sector(sym: str) -> str:
    s = sym.upper()
    if s in SYMBOL_SECTOR:
        return SYMBOL_SECTOR[s]
    if s in _SECTOR_LIVE_CACHE:
        return _SECTOR_LIVE_CACHE[s]
    sec = _lookup_sector_nse(s)
    _SECTOR_LIVE_CACHE[s] = sec
    return sec


def _lookup_sector_nse(sym: str) -> str:
    try:
        sess = _get_nse_session()
        data = _nse_json(sess, "https://www.nseindia.com/api/quote-equity", params={"symbol": sym}, timeout=10)
        if isinstance(data, dict):
            info = data.get("info", data)
            ind  = (info.get("industry") or info.get("macro") or info.get("basicIndustry") or "").lower()
            if any(k in ind for k in ("pharma","health","drug","biotech")):         return "NIFTY PHARMA"
            if any(k in ind for k in ("software","it services","technology")):      return "NIFTY IT"
            if any(k in ind for k in ("auto","vehicle","tyre","ancillar")):         return "NIFTY AUTO"
            if any(k in ind for k in ("fmcg","consumer","food","beverag")):         return "NIFTY FMCG"
            if any(k in ind for k in ("metal","steel","alumin","copper","mining")): return "NIFTY METAL"
            if any(k in ind for k in ("energy","power","oil","gas","petro")):       return "NIFTY ENERGY"
            if any(k in ind for k in ("realty","real estate","construct")):         return "NIFTY REALTY"
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
            log.debug(f"Shariah CSV {url}: {e}")
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
        return
    try:
        ws = _get_ws(tab)
        if ws is None:
            ws = _GS_WORKBOOK.add_worksheet(title=tab, rows=300, cols=40)
            _GS_WS_CACHE[tab] = ws
        ws.clear()
        try:
            ws.update("A1", rows)
        except TypeError:
            ws.update(rows)
        log.info(f"Sheets tab '{tab}' updated: {len(rows)-1} rows ✅")
    except Exception as e:
        log.error(f"push_sheet '{tab}': {e}")


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
    resp = sess.get(url, params=params, timeout=timeout)
    body = resp.text.strip()
    if not body or body.startswith("<"):
        raise ValueError(f"NSE empty/HTML body ({resp.status_code}) for {url}")
    return resp.json()


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
            created_at    TEXT DEFAULT CURRENT_TIMESTAMP
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
    con.commit()
    con.close()


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
                                  progress=False, auto_adjust=False, group_by="ticker")
                if raw.empty:
                    break
                for sym in chunk:
                    tk = f"{sym}.NS"
                    try:
                        if hasattr(raw.columns, "levels"):
                            lvl1 = list(raw.columns.get_level_values(1))
                            lvl0 = list(raw.columns.get_level_values(0))
                            sub  = raw.xs(tk, axis=1, level=1) if tk in lvl1 else (raw[tk] if tk in lvl0 else None)
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
    return _bhavcopy_from_yfinance(), "YFINANCE"


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — HISTORICAL OHLCV
# ══════════════════════════════════════════════════════════════════════════════

def _validate_no_lookahead(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "date" not in df.columns:
        return df
    df    = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    today = pd.Timestamp(datetime.today().date())
    return df[df["date"] <= today].copy()


def fetch_history(symbol: str, days: int = 300,
                  sess: Optional[requests.Session] = None) -> pd.DataFrame:
    """NSE historical API → yfinance fallback."""
    # NSE API
    try:
        if sess is None:
            sess = _get_nse_session()
        end = datetime.today(); start = end - timedelta(days=days + 50)
        data = _nse_json(sess, "https://www.nseindia.com/api/historical/cm/equity",
                         params={"symbol": symbol, "series": '["EQ"]',
                                 "from": start.strftime("%d-%m-%Y"), "to": end.strftime("%d-%m-%Y")},
                         timeout=20)
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
                return _validate_no_lookahead(df)
    except Exception as e:
        log.debug(f"NSE history {symbol}: {e}")

    # yfinance fallback
    try:
        import yfinance as yf
        end = datetime.today(); start = end - timedelta(days=days + 50)
        raw = yf.download(f"{symbol}.NS", start=start, end=end,
                          progress=False, auto_adjust=False)
        if not raw.empty:
            raw = raw.reset_index()
            raw.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in raw.columns]
            if "close" not in raw.columns and "adj close" in raw.columns:
                raw = raw.rename(columns={"adj close": "close"})
            raw["date"] = pd.to_datetime(raw["date"])
            df = raw[["date","open","high","low","close","volume"]].dropna()
            return _validate_no_lookahead(df)
    except Exception as e:
        log.debug(f"yfinance history {symbol}: {e}")

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
    POS_KW = ["bonus","dividend","buyback","split","profit","growth","order",
              "contract","win","award","acquisition","launch","upgrade","beat"]
    NEG_KW = ["loss","write-off","penalty","fraud","probe","npa","default",
              "downgrade","miss","warning","sebi notice","court"]
    result: dict = {}

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
                pos = sum(1 for k in POS_KW if k in subject)
                neg = sum(1 for k in NEG_KW if k in subject)
                score  = min(30, max(0, 15 + pos*5 - neg*8))
                # Build structured detail — not raw subject text
                if pos > 0:
                    matched = [k for k in POS_KW if k in subject]
                    detail  = f"Corporate action: {', '.join(matched[:2])}"
                elif neg > 0:
                    matched = [k for k in NEG_KW if k in subject]
                    detail  = f"⚠️ Regulatory/risk: {', '.join(matched[:2])}"
                else:
                    detail  = "Recent filing — neutral"
                if sym not in result or score > result[sym]["score"]:
                    result[sym] = {"score": score, "detail": detail}
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
                    pos = sum(1 for k in POS_KW if k in raw_subj)
                    neg = sum(1 for k in NEG_KW if k in raw_subj)
                    score = min(30, max(0, 15 + pos*5 - neg*8))
                    if pos > 0:
                        matched = [k.title() for k in POS_KW if k in raw_subj]
                        detail  = f"Filing: {', '.join(matched[:2])}"
                    elif neg > 0:
                        matched = [k.title() for k in NEG_KW if k in raw_subj]
                        detail  = f"⚠️ Filing risk: {', '.join(matched[:2])}"
                    else:
                        detail = "Corporate filing"
                    if sym not in result or score > result[sym]["score"]:
                        result[sym] = {"score": score, "detail": detail}
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
        vix_df   = yf.download("^INDIAVIX", period="5d",  progress=False, auto_adjust=True)
        nifty_df = yf.download("^NSEI",     period="10d", progress=False, auto_adjust=True)
        cnx_df   = yf.download("^CNX500",   period="60d", progress=False, auto_adjust=True)
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
        df = yf.download("^CNXSC", period="60d", progress=False, auto_adjust=True)
        if df.empty:
            df = yf.download("NIFTYSMLCAP100.NS", period="60d", progress=False, auto_adjust=True)
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

def fortress_score(symbol: str, today_row, hist: pd.DataFrame) -> Optional[dict]:
    """
    Core Fortress engine: 6-layer VPOC, regime, MFI/ADX, sector truth,
    52W compression, ATR velocity, VDU, VCP coil.
    Returns dict or None (hard-veto).
    """
    if len(hist) < MIN_HIST_BARS:
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
        return None
    if alt_pct > SNIPER_CFG["alt_stop_pct"]:
        return None

    sector      = get_sector(symbol)
    sector_mult = SECTOR_TRUTH.get(sector, 1.0)
    if sector in SECTOR_BLOCKED:
        return None

    # Sector RS override
    sect_20: Optional[float] = None
    if sector in SECTOR_INDICES:
        try:
            import yfinance as yf
            idf = yf.download(f"^{SECTOR_INDICES[sector]}", period="30d", progress=False, auto_adjust=True)
            if not idf.empty and len(idf)>=2:
                ic = idf["Close"].squeeze().values
                sect_20 = float((ic[-1]-ic[-20])/ic[-20]*100) if len(ic)>=20 else None
        except Exception as se:
            log.debug(f"Sector RS {sector}: {se}")
    if sect_20 is not None and velocity > sect_20+5.0:
        sector_mult = max(sector_mult, 1.0)

    turnover_lakhs = float(today_row.get("turnover_lakhs", 0))
    if turnover_lakhs < SNIPER_CFG["turnover_lakhs"]:
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


def _vol_profile_score(profile: dict, close: float) -> Tuple[float, str]:
    poc=profile.get("poc",0)
    if poc<=0: return 0.0,"No vol profile"
    score=0; notes=[]
    dist=abs(close-poc)/poc*100
    if dist<=1.0:   score+=40; notes.append("AT POC 🎯")
    elif dist<=3.0: score+=25; notes.append("NEAR POC")
    elif dist<=5.0: score+=12; notes.append("POC ZONE")
    va_lo=profile.get("va_low",0); va_hi=profile.get("va_high",0)
    if va_lo>0 and va_hi>0:
        if va_lo<=close<=va_hi: score+=20; notes.append("INSIDE VA")
        elif close<va_lo:       score+=8;  notes.append("BELOW VA")
    wp=profile.get("whale_pct",0)
    if wp>=35:   score+=25; notes.append(f"WHALE DEF {wp:.0f}%")
    elif wp>=25: score+=15; notes.append(f"Strong POC {wp:.0f}%")
    va_w=(va_hi-va_lo)/poc*100 if poc>0 and va_hi>va_lo else 0
    if 0<va_w<=8: score+=10; notes.append("TIGHT VA")
    return float(min(100,score))," · ".join(notes) if notes else "Diffuse"


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
    EMPTY={"survival":None,"t1_hit_pct":0.0,"days_to_t1":None,"label":"MC: insufficient data"}
    if len(hist)<30 or stop_loss<=0: return EMPTY
    closes=hist["close"].values.astype(float)
    lr=np.diff(np.log(closes[closes>0]))
    if len(lr)<10: return EMPTY
    mu,sigma=float(np.mean(lr)),float(np.std(lr))
    df=MC_FAT_DF; ts=sigma*math.sqrt((df-2)/df) if df>2 else sigma
    t1t=close*1.10
    rng=np.random.default_rng(42)
    surv=hit=days_tot=0
    for _ in range(MC_SIMS):
        path=close*np.exp(np.cumsum(mu+ts*rng.standard_t(df,size=MC_HORIZON)))
        if float(np.min(path))>stop_loss: surv+=1
        if float(np.max(path))>=t1t:
            hit+=1
            for d,p in enumerate(path,1):
                if p>=t1t: days_tot+=d; break
    sp=round(surv/MC_SIMS*100,1); tp=round(hit/MC_SIMS*100,1)
    ad=round(days_tot/max(1,hit),1) if hit>0 else None
    # convergence check
    h=MC_SIMS//2
    r1=np.random.default_rng(42); r2=np.random.default_rng(43)
    s1=sum(1 for _ in range(h) for p in [close*np.exp(np.cumsum(mu+ts*r1.standard_t(df,size=MC_HORIZON)))] if float(np.min(p))>stop_loss)
    s2=sum(1 for _ in range(h) for p in [close*np.exp(np.cumsum(mu+ts*r2.standard_t(df,size=MC_HORIZON)))] if float(np.min(p))>stop_loss)
    conv=abs(s1/max(1,h)*100-s2/max(1,h)*100)<=8.0
    lbl=f"✅ MC {sp}% survive ({MC_HORIZON}d, t-df{df})"+("" if conv else " [NOT CONVERGED]")
    return {"survival":sp,"t1_hit_pct":tp,"days_to_t1":ad,"label":lbl,"converged":conv}


def _bayesian_apex(macro_state: str, breadth_ok: bool, layer1: bool, layer2: bool, layer3: bool,
                   whale_detected: bool, div_type: str, vp_score: float,
                   mfi_v: float, adx_v: float, alt_pct: float,
                   mc_survival: Optional[float],
                   # ← Intelligence bonus inputs from Fortress
                   fii_pts: int, ins_pts: int, fil_pts: int) -> dict:
    """
    11-node Bayesian + 3 intelligence nodes = 14-node network.
    FII/insider/filing scores now influence posterior via dedicated nodes,
    so Fortress's intelligence data meaningfully tightens APEX conviction.
    """
    prior = 0.30; alpha = 0.12
    nodes = [
        (macro_state=="CLEAR",              0.72, 0.28),
        (breadth_ok,                        0.65, 0.38),
        (layer1,                            0.72, 0.30),
        (layer2,                            0.68, 0.38),
        (layer3,                            0.70, 0.35),
        (mfi_v<=45.0,                       0.68, 0.42),
        (adx_v>=25.0,                       0.68, 0.38),
        (alt_pct<30.0,                      0.62, 0.40),
        (whale_detected,                    0.74, 0.44),
        (div_type=="BULLISH_HIDDEN",        0.70, 0.40),
        (vp_score>=40,                      0.67, 0.40),
        (mc_survival is not None and mc_survival>=65, 0.68, 0.45),
        # Intelligence nodes — FII, insider, filing quality gates
        (fii_pts>=22,                       0.66, 0.40),   # FII/DII buying
        (ins_pts>=15,                       0.65, 0.42),   # Insider accumulation
        (fil_pts>=20,                       0.63, 0.42),   # Positive corporate filing
    ]
    posterior=prior
    for cond,pt,pf in nodes:
        lk=pt if cond else pf
        posterior=(lk*posterior)/max(1e-9,lk*posterior+(1-lk)*(1-posterior))
    posterior=alpha*prior+(1-alpha)*posterior
    posterior=min(0.99,max(0.01,round(posterior,3)))
    pct=round(posterior*100)
    if posterior>=0.75:   tier,bonus="🧠 VERY HIGH",12
    elif posterior>=0.65: tier,bonus="🧠 HIGH",8
    elif posterior>=0.55: tier,bonus="🧠 MODERATE",4
    elif posterior>=0.45: tier,bonus="🧠 NEUTRAL",0
    else:                 tier,bonus="🧠 LOW",-5
    return {"bayes_prob":posterior,"bayes_pct":pct,"bayes_tier":tier,
            "bayes_bonus":bonus,"bayes_label":f"{tier} conviction ({pct}%)"}


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
    fort = fortress_score(symbol, today_row, hist)
    if fort is None:
        return None

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
    vp_score,    vp_label  = _vol_profile_score(profile, close)
    pat_score,   pat_label = _pattern_score(hist, atr14, profile)
    mc          = _monte_carlo(hist, stop_loss, close)
    mc_survival = mc.get("survival")

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
    raw_apex = (
        whale_score * W["whale_radar"] +
        div_score   * W["divergence"]  +
        vp_score    * W["vol_profile"] +
        pat_score   * W["pattern"]     +
        bayes_score * W["bayesian"]    +
        float(vpoc_score_val := (
    25 if fort["layer1"] else
    15 if poc > 0 and abs(close-poc)/poc <= 0.05 else
    0)) * W["fortress_vpoc"]        # VPOC sub-score into APEX weight
    )
    # score variable reuse fix
    vpoc_for_apex = (
        25*(fort["layer1"]) +
        20*(fort["layer2"]) +
        25*(fort["layer3"]) +
        10*(fort["sector_mult"]>=1.0) +
        5*(fort["alt_pct"]<SNIPER_CFG["alt_warn_pct"])
    )
    raw_apex = (
        float(vpoc_for_apex) * W["fortress_vpoc"] +
        whale_score          * W["whale_radar"]   +
        div_score            * W["divergence"]    +
        vp_score             * W["vol_profile"]   +
        pat_score            * W["pattern"]       +
        bayes_score          * W["bayesian"]
    )
    apex_composite = round(raw_apex * macro_damp.get(macro_state,0.88))
    if whale_det["signal_type"]=="STEALTH" and fort["layer1"] and fort["layer2"] and fort["layer3"]:
        apex_composite=min(100,apex_composite+8)
    if bayes["bayes_pct"]>=70: apex_composite=min(100,apex_composite+5)
    apex_composite=max(0,min(100,apex_composite))

    if apex_composite < APEX_MIN_SCORE:
        return None

    # ── CVD / VSA adjustments to fortress total ───────────────────────
    adj       = cvd["cvd_bonus"]+vsa.get("vsa_bonus",0)
    fort_total= min(FORT_TOTAL_MAX, max(0, fort_total+adj))

    # ── FUSED COMPOSITE ───────────────────────────────────────────────
    fort_norm  = fort_total / FORT_TOTAL_MAX * 100   # normalise to 0-100
    fused      = round(fort_norm*0.45 + apex_composite*0.55)
    fused      = max(0, min(100, fused))

    # ── Grade ─────────────────────────────────────────────────────────
    if fused>=GRADE_APEX:      grade="⚔️ APEX"
    elif fused>=GRADE_PRISTINE: grade="💎 PRISTINE"
    elif fused>=GRADE_GOOD:    grade="🟢 GOOD"
    elif fused>=GRADE_PROBE:   grade="🔵 PROBE"
    else:                       return None

    # ── Exit plan (APEX ATR-based) ─────────────────────────────────────
    atr_m  = SECTOR_ATR_MULT.get(sector,1.0)
    risk   = atr14*2.0*atr_m if atr14>0 else close*0.03
    r1     = round(close+risk*2.5,2)
    r2     = round(close+risk*4.0,2)
    r3     = round(close+risk*6.5,2)
    trail_stop = round(r2-atr14*2.5*atr_m,2)
    r1_pct=round((r1-close)/close*100,1); r2_pct=round((r2-close)/close*100,1)
    r3_pct=round((r3-close)/close*100,1)

    # ── Position size ──────────────────────────────────────────────────
    rps    = max(close-stop_loss, close*0.02)
    risk_r = ACCOUNT_EQUITY*ACCOUNT_RISK_PCT
    sh_v   = math.floor(risk_r/rps) if rps>0 else 0
    deploy = (1.00 if fused>=GRADE_APEX else 0.75 if fused>=GRADE_PRISTINE
              else 0.50 if fused>=GRADE_GOOD else 0.25)
    sh_f   = min(math.floor(sh_v*(0.5+0.5*(fused/100)**0.5)*deploy),
                 math.floor(ACCOUNT_EQUITY*0.10/close) if close>0 else 0)
    pos_v  = sh_f*close
    pos_lb = (f"{sh_f} sh × ₹{close:.2f} = ₹{pos_v:,.0f} | Risk ₹{sh_f*rps:,.0f}"
              if sh_f>0 else "— (below sizing min)")

    # Circuit breaker for small caps
    alloc_note = ""
    if close < MAX_PRICE:
        cb_active, cb_msg = check_smallcap_cb()
        if cb_active: alloc_note=f" ⚠️ CB: {cb_msg[:40]}"

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

    return {
        "symbol":   symbol,
        "sector":   sector,
        "close":    round(close,2),
        "grade":    grade,

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
# SECTION 14 — TELEGRAM (single send, plain-text safe, MarkdownV2 clean)
# ══════════════════════════════════════════════════════════════════════════════

def _escape(s) -> str:
    """Escape Telegram MarkdownV2 special chars (FIX-AUDIT-01)."""
    text = str(s) if s is not None else ""
    special = r'\_*[]()~`>#+-=|{}.!'
    return "".join(("\\" + ch if ch in special else ch) for ch in text)


def _split_msg(msg: str, limit: int = 4000) -> list:
    """Split at card boundaries, escape-safe hard-split fallback."""
    if len(msg) <= limit:
        return [msg]
    cards  = msg.split("\n\n"); chunks=[]; cur=""
    for card in cards:
        blk = card+"\n\n"
        if len(cur)+len(blk)>limit:
            if cur.strip(): chunks.append(cur.rstrip())
            cur = blk
        else:
            cur += blk
    if cur.strip(): chunks.append(cur.rstrip())
    result=[]
    for chunk in chunks:
        while len(chunk)>limit:
            at=limit
            for off in range(0,min(20,at)):
                pos=at-off
                if pos>0 and chunk[pos-1]=="\\": continue
                chunk_head,chunk=chunk[:pos],chunk[pos:]
                if chunk_head.strip(): result.append(chunk_head)
                break
            else:
                result.append(chunk[:limit]); chunk=chunk[limit:]
        if chunk.strip(): result.append(chunk)
    return result


def _tg_post(token: str, chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for attempt,delay in enumerate([0,2,5],1):
        if delay: time.sleep(delay)
        try:
            r=requests.post(url, json={"chat_id":chat_id,"text":text}, timeout=20)
            if r.status_code==200: return True
            if r.status_code==429:
                ra=int(r.headers.get("Retry-After",5)); time.sleep(ra); continue
            log.error(f"Telegram {r.status_code} → {chat_id}: {r.text[:100]}")
        except Exception as e:
            log.error(f"Telegram attempt {attempt}: {e}")
    return False


def send_telegram(picks: list, macro: dict, fii_data: dict,
                   date_label: str, data_source: str):
    """One clean message per pick — plain text, no MarkdownV2 parse failures."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.info("Telegram not configured — skipping"); return

    ms      = macro.get("macro_state","CHOP")
    vix     = macro.get("vix_val",0.0)
    nchg    = macro.get("nifty_chg",0.0)
    ms_icon = {"CLEAR":"✅","CHOP":"⚠️","PANIC":"🔴","MASSACRE":"🚨"}.get(ms,"↔")

    header_lines = [
        f"⚔️ UNIFIED SNIPER {VERSION} | {date_label} | {data_source}",
        f"{ms_icon} {ms} | VIX {vix:.1f} | NIFTY {nchg:+.2f}%",
        f"{fii_data.get('label','—')} | {fii_data.get('detail','—')[:50]}",
        "─" * 34,
    ]

    if ms == "MASSACRE":
        header_lines.append("\n🚨 MARKET MASSACRE — ALL ENTRIES HALTED. Capital preservation mode.")
    elif ms == "PANIC":
        header_lines.append("\n🔴 VIX PANIC — NO NEW ENTRIES.")
    elif not picks:
        header_lines.append("\n📭 No halal setups cleared all filters today.\nThis is the system working correctly.")
    else:
        for i,r in enumerate(picks,1):
            sym    = r["symbol"]
            grade  = r["grade"]
            fused  = r["fused"]
            close  = r["close"]
            stop   = r["stop_loss"]
            r1_p   = r["r1"]
            r2_p   = r["r2"]
            r1_pct = r["r1_pct"]
            days   = r["days_to_r1_est"]
            story  = r["story"]
            mc_s   = r["mc_survival"]
            layers = "".join("✓" if r.get(f"layer{n}") else "✗" for n in range(1,4))

            block = [
                "",
                f"{grade} #{i} — {sym} (₹{close:.2f})",
                f"Fused {fused}/100 | Fort {r['fort_pct']:.0f}% | APEX {r['apex_composite']}/100",
                f"Buy  ₹{r['buy_lo']:.2f} – ₹{r['buy_hi']:.2f}",
                f"SL   ₹{stop:.2f}  (risk {r['risk_pct']}%)",
                f"R1   ₹{r1_p:.2f} (+{r1_pct}%)  → sell 30%",
                f"R2   ₹{r2_p:.2f} (+{r['r2_pct']}%)  → sell 30%",
                f"R3   ₹{r['r3']:.2f} (+{r['r3_pct']}%)  → sell 40%",
                f"Trail ₹{r['trail_stop']:.2f}  (arms at R2)",
                f"",
                f"Est. ~{days}d to R1 | MC survive {mc_s}%",
                f"VPOC layers {layers} | {r.get('regime','—')} | VCP {r.get('vcp_coil','—')[:5]}",
                f"RSI {r['rsi']} | MFI {r['mfi']} | ADX {r['adx']} | ATR ₹{r['atr14']}",
                f"Bayes {r['bayes_pct']}% | Whale {r['whale_score']:.0f}/100 | Div {r['div_score']:.0f}/100",
                f"",
                f"Why: {story[:120]}{'...' if len(story)>120 else ''}",
            ]
            if r.get("alloc_note"): block.append(r["alloc_note"][:80])
            if r.get("fog_label"):  block.append(f"⚠️ {r['fog_label'][:60]}")
            if not r.get("vol_reliable",True): block.append("⚠️ Volume data unreliable — VPOC layers L1/L2 suppressed")
            block.append("─" * 34)
            header_lines.extend(block)

    footer_lines = [
        "",
        f"🔎 Screened halal candidates → {len(picks)} setup(s)",
        f"Shariah compliant | {MC_HORIZON}-day swing | Risk {ACCOUNT_RISK_PCT*100:.1f}% per trade",
        "🤲 Bismillah — trade with discipline and tawakkul",
    ]

    full_msg = "\n".join(header_lines + footer_lines)
    targets  = [TELEGRAM_CHAT_ID] + TELEGRAM_SHARE_IDS

    for msg_part in _split_msg(full_msg):
        for chat_id in targets:
            if not chat_id: continue
            _tg_post(TELEGRAM_TOKEN, chat_id, msg_part)
            time.sleep(0.3)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 15 — OUTPUT: EXCEL, HTML, GOOGLE SHEETS
# ══════════════════════════════════════════════════════════════════════════════

def save_excel(picks: list, all_results: list, fii_data: dict, date_label: str):
    if not picks and not all_results: return
    try:
        EXCEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(EXCEL_PATH, engine="openpyxl") as w:
            pd.DataFrame(picks).to_excel(w, sheet_name="Top Picks",   index=False)
            pd.DataFrame(all_results).to_excel(w, sheet_name="All Results", index=False)
            pd.DataFrame([fii_data]).to_excel(w, sheet_name="FII_DII", index=False)
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
            r["layer1"], r["layer2"], r["layer3"],
            r.get("vcp_coil","—"), r.get("regime","—"),
            r["rsi"], r["mfi"], r["adx"], r["atr14"], r["poc"], r["ma200"],
            r.get("data_quality","—"), r.get("vol_reliable",True), r.get("story","—"),
        ])
    _push_sheet("SCREENER", rows)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 16 — MAIN PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

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

    # 5. Intelligence (one fetch each, shared across all symbols)
    log.info("Fetching FII/DII…");     fii_data    = fetch_fii_dii()
    log.info("Fetching insider trades…"); insider_map = fetch_insider_trades()
    log.info("Fetching filings…");     filings     = fetch_filings()
    log.info("Fetching earnings…");    earn_cal    = fetch_earnings_calendar()
    log.info(f"FII/DII: {fii_data['label']} | Insider: {len(insider_map)} symbols | "
             f"Filings: {len(filings)} | Earnings: {len(earn_cal)} events")

    # 6. Scoring loop (one loop, both engines fused)
    sess    = _get_nse_session()
    results = []
    for i,(_, row) in enumerate(cands.iterrows()):
        sym = row["symbol"]
        if i % 25 == 0:
            log.info(f"Progress: {i}/{len(cands)} | picks: {len(results)}")
        try:
            hist = fetch_history(sym, days=300, sess=sess)
            if len(hist) < MIN_HIST_BARS:
                log.debug(f"{sym}: only {len(hist)} bars — skip"); continue
            r = assemble_pick(sym, row, hist, fii_data, insider_map, filings, earn_cal, macro)
            if r:
                results.append(r)
                log.info(f"  ✅ {sym:12s} | fused={r['fused']}/100 | {r['grade'][:10]} | {r['story'][:60]}")
            time.sleep(0.15)
        except Exception as e:
            log.debug(f"{sym}: {e}")

    log.info(f"\n{'='*70}")
    log.info(f"Screened {len(cands)} | Passed: {len(results)}")

    # 7. Rank + sector cap + bucket
    results.sort(key=lambda x: (x["fused"]*1000 + x["whale_score"]*10 + x["div_score"]), reverse=True)
    sec_counts: dict = {}; globally_capped=[]
    for r in results:
        sec=r["sector"]; cnt=sec_counts.get(sec,0)
        if cnt<2: globally_capped.append(r); sec_counts[sec]=cnt+1

    mid_picks   = [r for r in globally_capped if 200<=r["close"]<=MAX_PRICE]
    small_picks = [r for r in globally_capped if MIN_PRICE<=r["close"]<200]
    top_picks   = mid_picks[:2] + small_picks[:2]
    seen: set   = set()
    top_picks   = [r for r in top_picks if r["symbol"] not in seen and not seen.add(r["symbol"])]

    log.info(f"\n{'='*70}")
    log.info(f"⚔️  TOP {len(top_picks)} PICKS")
    log.info(f"{'='*70}")
    for rank, r in enumerate(top_picks, 1):
        vn = "" if r.get("vol_reliable",True) else " [NO-VOL]"
        log.info(f"  #{rank} {r['symbol']:12s} | Fused {r['fused']}/100 | Fort {r['fort_pct']:.0f}% "
                 f"| APEX {r['apex_composite']}/100 | {r['grade']}{vn}")
        log.info(f"       Buy ₹{r['buy_lo']}-{r['buy_hi']} | SL ₹{r['stop_loss']} | "
                 f"R1 ₹{r['r1']} | R2 ₹{r['r2']} | MC {r['mc_survival']}%")
        log.info(f"       {r['story'][:80]}")

    # 8. Outputs
    log.info("Saving Excel…");       save_excel(top_picks, results, fii_data, date_label)
    log.info("Saving HTML…");        save_html(top_picks, fii_data, date_label)
    log.info("Pushing to Sheets…");  push_gsheets(top_picks, date_label)
    log.info("Sending Telegram…");   send_telegram(top_picks, macro, fii_data, date_label, data_source)

    # Persist results to DB
    try:
        con = sqlite3.connect(DB_PATH)
        for r in top_picks:
            con.execute(
                "INSERT INTO sniper_results (run_date,symbol,grade,fused_score,close,stop_loss,r1,r2,r3,story) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (date_label,r["symbol"],r["grade"],r["fused"],r["close"],
                 r["stop_loss"],r["r1"],r["r2"],r["r3"],r["story"])
            )
        con.commit(); con.close()
    except Exception as e:
        log.debug(f"DB persist: {e}")

    log.info(f"\n✅ Done | {len(top_picks)} picks | Macro: {macro['macro_state']} | "
             f"VIX: {macro['vix_val']:.1f} | Source: {data_source} | "
             f"Bismillah 🤲")
    return top_picks


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    run()
