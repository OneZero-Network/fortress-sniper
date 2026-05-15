"""
╔══════════════════════════════════════════════════════════════════════════╗
║        APEX SNIPER v1.2 — UNIFIED HALAL SWING INTELLIGENCE ENGINE      ║
║        Bismillah — In the name of Allah, the Most Gracious              ║
║                                                                          ║
║   SYNTHESIS OF:                                                          ║
║   ─ Fortress Screener v8.2   (Production-hardened screening core)       ║
║   ─ Smart Money Sniper v1.0  (Whale radar + 7-layer pearl engine)       ║
║   ─ Divergence Sniper v9.0   (Volume profile + Bayesian swing model)    ║
║                                                                          ║
║   WHAT'S NEW IN v1.1                                                    ║
║   ─────────────────────────────────────────────────────────────         ║
║   DATA:   4-tier cascade: Sheets → yfinance → Google Finance → nsepython
║           All gated by env toggles.                                     ║
║                                                                          ║
║   UNIFIED:  Single data fetch pipeline — one yfinance call per symbol   ║
║             feeds ALL sub-engines. Zero redundant API calls.            ║
║                                                                          ║
║   SCORING:  APEX COMPOSITE = weighted fusion of:                        ║
║             · Fortress VPOC Sniper Score (25%)                          ║
║             · Whale Radar + Stealth Accumulation (25%)                  ║
║             · Divergence Engine (RSI Hidden + OBV) (15%)               ║
║             · Volume Profile + POC Proximity (15%)                      ║
║             · Pattern Recognition (VCP/NR7/IB/Cup) (10%)               ║
║             · 11-Node Bayesian Network (10%)                            ║
║             All gated by: Macro Shield → Halal Guard → Liquidity        ║
║                                                                          ║
║   BAYESIAN: 13-node network (9 Fortress + 4 new divergence nodes)      ║
║             Prior = 0.30 → posterior drives conviction tier             ║
║                                                                          ║
║   POSITIONS: Tiered Kelly-like sizing:                                   ║
║             APEX (≥82): 100% • PRISTINE (≥72): 75% • GOOD (≥60): 50%  ║
║             PROBE (≥48): 25% • WATCH (<48): 0%                         ║
║                                                                          ║
║   EXITS:   3-Target graduated exit:                                      ║
║             R1 @ +8–10% → sell 30% • R2 @ +15–20% → sell 30%         ║
║             R3 @ +28–35% → sell 40% • Trailing ATR stop auto-armed     ║
║                                                                          ║
║   OUTPUT:  Telegram MarkdownV2 cards with full story per pick           ║
║                                                                          ║
║   USAGE:                                                                 ║
║   python apex_sniper_v1.py                                              ║
║                                                                          ║
║   ENV VARS                                                               ║
║   TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_SHARE_IDS                 ║
║   GOOGLE_SHEET_ID, GOOGLE_CREDS_JSON                                    ║
║   ACCOUNT_EQUITY     (default 500,000)                                  ║
║   ACCOUNT_RISK_PCT   (default 0.015 = 1.5%)                            ║
║   APEX_TOP_N         (default 5 picks)                                  ║
║   APEX_MIN_SCORE     (default 48)                                       ║
║   FORCE_YFINANCE     (default false)                                    ║
║   PAPER_MODE         (default false)                                    ║
║   GOOGLE_FINANCE_ENABLED (default false)                                ║
║   NSEPYTHON_ENABLED  (default false)                                    ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os, io, sys, time, json, math, logging, warnings, threading, sqlite3
import random, re, requests
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from functools import lru_cache

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("apex_sniper")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# ══════════════════════════════════════════════════════════════════════════
# SECTION 0 — CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════

TELEGRAM_TOKEN     = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_SHARE_IDS = [c.strip() for c in os.getenv("TELEGRAM_SHARE_IDS", "").split(",") if c.strip()]

GOOGLE_SHEET_ID   = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON", "")

DB_PATH         = Path(os.getenv("CACHE_PATH", "outputs/apex_cache.db"))
PAPER_MODE      = os.getenv("PAPER_MODE", "false").lower() == "true"
FORCE_YFINANCE  = os.getenv("FORCE_YFINANCE", "false").lower() == "true"
GOOGLE_FINANCE_ENABLED = os.getenv("GOOGLE_FINANCE_ENABLED", "false").lower() == "true"
NSEPYTHON_ENABLED = os.getenv("NSEPYTHON_ENABLED", "false").lower() == "true"

# Portfolio
ACCOUNT_EQUITY   = float(os.getenv("ACCOUNT_EQUITY", "500000"))
ACCOUNT_RISK_PCT = float(os.getenv("ACCOUNT_RISK_PCT", "0.015"))   # 1.5% per trade
APEX_TOP_N       = int(os.getenv("APEX_TOP_N", "5"))
APEX_MIN_SCORE   = int(os.getenv("APEX_MIN_SCORE", "48"))

# Universe filters
MIN_PRICE          = 50
MAX_PRICE          = 800
MIN_TURNOVER_LAKHS = 150

# Swing horizon
SWING_HORIZON_DAYS = 12   # 10-15d midpoint

# Scoring weights (must sum to 1.0)
W = dict(
    fortress_vpoc = 0.25,
    whale_radar   = 0.25,
    divergence    = 0.15,
    vol_profile   = 0.15,
    pattern       = 0.10,
    bayesian      = 0.10,
)
assert abs(sum(W.values()) - 1.0) < 0.01, "Weights must sum to 1.0"

# MC parameters
MC_SIMS       = 600
MC_FAT_DF     = 5      # Student-t degrees of freedom (heavier tails for overnight gaps)
MC_HORIZON    = SWING_HORIZON_DAYS

# Grade thresholds
GRADE_APEX     = 82
GRADE_PRISTINE = 72
GRADE_GOOD     = 60
GRADE_PROBE    = 48

# Sector ATR multipliers (from fortress v8.2 FIX-GAP-06)
SECTOR_ATR_MULT = {
    "NIFTY METAL": 1.20,
    "NIFTY IT":    0.90,
    "NIFTY PHARMA": 1.00,
    "NIFTY AUTO":  1.05,
    "NIFTY FMCG":  0.90,
    "DIVERSIFIED": 1.00,
}

SECTOR_TRUTH = {
    "NIFTY PHARMA":  1.15,
    "NIFTY IT":      1.10,
    "NIFTY AUTO":    1.00,
    "NIFTY FMCG":    0.95,
    "NIFTY METAL":   0.85,
    "DIVERSIFIED":   1.00,
    "NIFTY BANK":    0.00,   # Blocked (riba)
    "NIFTY ENERGY":  0.20,
}
SECTOR_BLOCKED = {"NIFTY BANK", "NIFTY ENERGY"}

# ══════════════════════════════════════════════════════════════════════════
# SECTION 1 — HALAL GUARD (from fortress v8.2, hardened)
# ══════════════════════════════════════════════════════════════════════════

HALAL_EXCLUDED = {
    "HDFCBANK","ICICIBANK","SBIN","KOTAKBANK","AXISBANK","INDUSINDBK",
    "BANDHANBNK","IDFCFIRSTB","FEDERALBNK","RBLBANK","BANKBARODA",
    "CANBK","UNIONBANK","PNB","INDIANB","AUBANK","DCBBANK","YESBANK",
    "BAJFINANCE","BAJAJFINSV","SBICARD","CHOLAFIN","HDFC","LICHSGFIN",
    "M&MFIN","SHRIRAMFIN","MUTHOOTFIN","MANAPPURAM","IIFL","SUNDARMFIN",
    "RECLTD","PFC","IRFC","HUDCO","PNBHOUSING",
    "HDFCLIFE","SBILIFE","ICICIPRU","LICI","STARHEALTH","GICRE","NIACL",
    "NIFTYBEES","JUNIORBEES","GOLDBEES","BANKBEES","LIQUIDBEES",
}

HALAL_WHITELIST = {
    "TCS","INFY","WIPRO","HCLTECH","TECHM","MPHASIS","COFORGE","PERSISTENT",
    "KPITTECH","TATAELXSI","ROUTE","TANLA","MASTEK","NEWGEN","SAKSOFT",
    "INTELLECT","DATAMATICS","ZENSAR","SUNPHARMA","DRREDDY","CIPLA",
    "DIVISLAB","AUROPHARMA","LUPIN","TORNTPHARM","ALKEM","IPCALAB",
    "NATCOPHARM","GRANULES","GLENMARK","AJANTPHARM","LALPATHLAB","METROPOLIS",
    "SYNGENE","MARKSANS","MARUTI","TATAMOTORS","M&M","HEROMOTOCO",
    "BAJAJ-AUTO","EICHERMOT","TVSMOTORS","MOTHERSON","BOSCHLTD","ENDURANCE",
    "APOLLOTYRE","CEATLTD","BALKRISIND","SUPRAJIT","GABRIEL","CRAFTSMAN",
    "TIINDIA","HINDUNILVR","NESTLEIND","BRITANNIA","DABUR","MARICO",
    "COLPAL","EMAMILTD","TATACONSUM","VBL","JUBLFOOD","KRBL","JYOTHYLAB",
    "PIDILITIND","FINEORG","GALAXYSURF","VINATIORG","NAVINFLUOR","ALKYLAMINE",
    "DEEPAKNI","TATACHEM","GHCL","ANUPAM","PCBL","AARTI","HIMADRI",
    "EPIGRAL","ATUL","NOCIL","LT","HAVELLS","VOLTAS","SIEMENS","ABB",
    "CUMMINSIND","THERMAX","KEC","POLYCAB","SCHAEFFLER","TIMKEN","GRINDWELL",
    "PRAJ","ELGIEQUIP","KAYNES","SYRMA","DLF","GODREJPROP","OBEROIRLTY",
    "PHOENIXLTD","SOBHA","CONCOR","BLUEDART","TCI","DELHIVERY","ALLCARGO",
    "KAVERI","DHANUKA","UPL","PIIND","COROMANDEL","PAGEIND","RAYMOND",
    "WELSPUNIND","VARDHMAN","TRIDENT","TATASTEEL","HINDALCO","JSWSTEEL",
    "NMDC","RATNAMANI","TITAN","TRENT","ASIANPAINT","BERGERPAINTS",
    "DIXON","AMBER","NTPC","TATAPOWER","TORNTPOWER","SUZLON","INOXWIND",
    "ADANIPORTS","ADANIENT","RELIANCE","ONGC",
}

HALAL_KW = (
    "bank","bancorp","finance","finserv","fincorp","financial",
    "insurance","insur","nifty","etf","reit","invit",
    "liquid","overnight","gilt","treasury",
)
_BEES_RE = re.compile(r'\bbees\b', re.IGNORECASE)

_SHARIAH_CACHE: Optional[set] = None
_SHARIAH_LOCK = threading.Lock()

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
    "NMDC":"NIFTY METAL","RATNAMANI":"NIFTY METAL",
    "HINDUNILVR":"NIFTY FMCG","NESTLEIND":"NIFTY FMCG",
    "BRITANNIA":"NIFTY FMCG","DABUR":"NIFTY FMCG",
    "MARICO":"NIFTY FMCG","COLPAL":"NIFTY FMCG",
    "DLF":"NIFTY REALTY","GODREJPROP":"NIFTY REALTY",
    "OBEROIRLTY":"NIFTY REALTY","PHOENIXLTD":"NIFTY REALTY",
}


def is_halal(symbol: str) -> bool:
    """Hard halal gate — excluded set checked before whitelist (fortress FIX-AUDIT-02)."""
    sym = symbol.upper().strip()
    if sym in HALAL_EXCLUDED:
        return False
    sl = sym.lower()
    if any(kw in sl for kw in HALAL_KW) or _BEES_RE.search(sl):
        return False
    universe = _get_shariah_universe()
    if universe:
        return sym in universe
    return sym in HALAL_WHITELIST


def _get_shariah_universe() -> set:
    global _SHARIAH_CACHE
    if _SHARIAH_CACHE is not None:
        return _SHARIAH_CACHE
    with _SHARIAH_LOCK:
        if _SHARIAH_CACHE is not None:
            return _SHARIAH_CACHE
        # Try to load from cache DB
        try:
            conn = sqlite3.connect(DB_PATH)
            row = conn.execute(
                "SELECT data, fetched_at FROM shariah_cache ORDER BY fetched_at DESC LIMIT 1"
            ).fetchone()
            if row:
                age_h = (datetime.now() - datetime.fromisoformat(row[1])).total_seconds() / 3600
                if age_h < 24:
                    _SHARIAH_CACHE = set(json.loads(row[0]))
                    conn.close()
                    return _SHARIAH_CACHE
            conn.close()
        except Exception:
            pass
        _SHARIAH_CACHE = set()   # fallback to HALAL_WHITELIST
    return _SHARIAH_CACHE


def get_sector(symbol: str) -> str:
    return SYMBOL_SECTOR.get(symbol.upper(), "DIVERSIFIED")


# ══════════════════════════════════════════════════════════════════════════
# SECTION 2 — DATABASE INIT
# ══════════════════════════════════════════════════════════════════════════

def _init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS shariah_cache (
            id INTEGER PRIMARY KEY,
            data TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS apex_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT,
            symbol TEXT,
            grade TEXT,
            composite_score REAL,
            close REAL,
            stop_loss REAL,
            t1 REAL,
            t2 REAL,
            t3 REAL,
            story TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════════════════════
# SECTION 3 — DATA LAYER (4-tier cascade)
# ══════════════════════════════════════════════════════════════════════════

def build_universe_yfinance() -> pd.DataFrame:
    """Fetch EOD snapshot for all halal candidates via yfinance batch."""
    candidates = sorted(HALAL_WHITELIST)
    try:
        import yfinance as yf
    except ImportError:
        log.error("yfinance not installed: pip install yfinance")
        return pd.DataFrame()

    records, CHUNK = [], 50
    for i in range(0, len(candidates), CHUNK):
        chunk   = candidates[i:i+CHUNK]
        tickers = " ".join(f"{s}.NS" for s in chunk)
        try:
            raw = yf.download(tickers, period="2d", interval="1d",
                              progress=False, auto_adjust=False, group_by="ticker")
            if raw.empty:
                continue
            for sym in chunk:
                tk = f"{sym}.NS"
                try:
                    if hasattr(raw.columns, "levels"):
                        lvl1 = list(raw.columns.get_level_values(1))
                        if tk in lvl1:
                            sub = raw.xs(tk, axis=1, level=1)
                        else:
                            continue
                        sub.columns = [c.lower() for c in sub.columns]
                    else:
                        sub = raw.copy()
                        sub.columns = [c.lower() for c in sub.columns]

                    cs = sub["close"].dropna()
                    vs = sub["volume"].dropna() if "volume" in sub.columns else pd.Series(dtype=float)
                    if cs.empty:
                        continue
                    close = float(cs.iloc[-1])
                    vol   = float(vs.iloc[-1]) if not vs.empty else 0.0
                    turnover = round((vol * close) / 100_000, 2)
                    if MIN_PRICE <= close <= MAX_PRICE:
                        records.append({
                            "symbol": sym,
                            "close":  round(close, 2),
                            "volume": vol,
                            "turnover_lakhs": turnover,
                        })
                except Exception:
                    continue
            time.sleep(0.4)
        except Exception as e:
            log.debug(f"Batch chunk {i}: {e}")

    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    return df[df["close"].between(MIN_PRICE, MAX_PRICE)].reset_index(drop=True)


def build_universe_google_finance() -> pd.DataFrame:
    """
    Tertiary fallback: scrape current price from Google Finance (unofficial).
    Best-effort only — Google has no official API. Polite delays + session reuse.
    """
    if not GOOGLE_FINANCE_ENABLED:
        return pd.DataFrame()

    candidates = sorted(HALAL_WHITELIST)
    records = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    session = requests.Session()

    for sym in candidates:
        try:
            url = f"https://www.google.com/finance/quote/{sym}:NSE"
            r = session.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                continue

            text = r.text
            # Try multiple extraction patterns (Google changes these often)
            close = None
            patterns = [
                r'data-last-price="(\d+\.?\d*)"',
                r'"(\d{1,3}(?:,\d{3})*\.\d{2})"\s*,\s*"\d{1,3}(?:,\d{3})*\.\d{2}"\s*,\s*"\d{1,3}(?:,\d{3})*\.\d{2}"\s*,\s*"\d{1,3}(?:,\d{3})*\.\d{2}"\s*,\s*"(\d{1,3}(?:,\d{3})*)"',
                r'class="YMlKec fxKbKc">(\d+,?\d*\.?\d*)<<',
                r'"price"\s*:\s*"?(\d+\.?\d*)"?',
            ]
            for pat in patterns:
                m = re.search(pat, text)
                if m:
                    close_str = m.group(1).replace(',', '')
                    try:
                        close = float(close_str)
                        break
                    except ValueError:
                        continue

            if close is None:
                continue

            # Volume is rarely on the main quote page; default to 0
            vol = 0.0
            turnover = round((vol * close) / 100_000, 2)

            if MIN_PRICE <= close <= MAX_PRICE:
                records.append({
                    "symbol": sym,
                    "close": round(close, 2),
                    "volume": vol,
                    "turnover_lakhs": turnover,
                })

            time.sleep(random.uniform(1.0, 2.0))  # polite crawl delay
        except Exception as e:
            log.debug(f"GF {sym}: {e}")
            continue

    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    log.info(f"Google Finance fallback: {len(df)} symbols scraped")
    return df[df["close"].between(MIN_PRICE, MAX_PRICE)].reset_index(drop=True)


def build_universe_nsepython() -> pd.DataFrame:
    """
    4th fallback: native NSE India public API via nsepython library.
    This is the most reliable source for Indian equities after Sheets/yfinance.
    """
    if not NSEPYTHON_ENABLED:
        return pd.DataFrame()

    try:
        from nsepython import nse_eq
    except ImportError:
        log.warning("nsepython not installed. Run: pip install nsepython")
        return pd.DataFrame()

    records = []
    for sym in sorted(HALAL_WHITELIST):
        try:
            data = nse_eq(sym)
            close = float(data.get("lastPrice", 0) or data.get("close", 0))
            vol = float(data.get("volume", 0))
            turnover = round((vol * close) / 100_000, 2)
            if MIN_PRICE <= close <= MAX_PRICE:
                records.append({
                    "symbol": sym,
                    "close": round(close, 2),
                    "volume": vol,
                    "turnover_lakhs": turnover,
                })
            time.sleep(0.15)
        except Exception as e:
            log.debug(f"nsepython {sym}: {e}")
            continue

    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    log.info(f"nsepython fallback: {len(df)} symbols fetched")
    return df[df["close"].between(MIN_PRICE, MAX_PRICE)].reset_index(drop=True)


def load_bhavcopy_sheets() -> pd.DataFrame:
    """Load BHAVCOPY tab from Google Sheets."""
    if not (GOOGLE_SHEET_ID and GOOGLE_CREDS_JSON):
        return pd.DataFrame()
    try:
        import gspread, base64
        from google.oauth2.service_account import Credentials
    except ImportError as ie:
        log.warning(f"load_bhavcopy_sheets: required package not installed — {ie}. "
                    f"Run: pip install gspread google-auth")
        return pd.DataFrame()
    try:
        raw = GOOGLE_CREDS_JSON.strip()
        try:
            creds_dict = json.loads(base64.b64decode(raw).decode())
        except Exception:
            creds_dict = json.loads(raw)
        scopes = ["https://spreadsheets.google.com/feeds",
                  "https://www.googleapis.com/auth/spreadsheets",
                  "https://www.googleapis.com/auth/drive"]
        creds  = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        wb     = client.open_by_key(GOOGLE_SHEET_ID)
        ws     = wb.worksheet("BHAVCOPY")
        data   = ws.get_all_values()
        if len(data) < 2:
            return pd.DataFrame()
        headers = [h.strip().upper() for h in data[0]]
        df = pd.DataFrame(data[1:], columns=headers)
        rename_map = {"SYMBOL":"symbol","CLOSE":"close","VOLUME":"volume",
                      "TURNOVER_LAKHS":"turnover_lakhs"}
        for src, dst in rename_map.items():
            if src in df.columns and dst not in df.columns:
                df = df.rename(columns={src: dst})
        for c in ["close","volume","turnover_lakhs"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        if "symbol" not in df.columns:
            return pd.DataFrame()
        df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
        return df[df["close"] > 0].dropna(subset=["close"]).reset_index(drop=True)
    except Exception as e:
        log.debug(f"Sheets bhavcopy: {e}")
        return pd.DataFrame()


def fetch_history(sym: str, days: int = 300) -> pd.DataFrame:
    """Fetch OHLCV history for a single symbol via yfinance."""
    try:
        import yfinance as yf
        end   = datetime.today()
        start = end - timedelta(days=days + 60)
        df    = yf.download(f"{sym}.NS", start=start, end=end,
                            progress=False, auto_adjust=False)
        if df.empty:
            return pd.DataFrame()
        df = df.reset_index()
        if hasattr(df.columns, "levels"):
            df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
        else:
            df.columns = [str(c).lower() for c in df.columns]
        if "close" not in df.columns and "adj close" in df.columns:
            df = df.rename(columns={"adj close": "close"})
        df["date"] = pd.to_datetime(df["date"])
        return df[["date","open","high","low","close","volume"]].sort_values("date").dropna().reset_index(drop=True)
    except Exception as e:
        log.debug(f"History {sym}: {e}")
        return pd.DataFrame()


def fetch_fii_dii_sheets() -> dict:
    """Load FII/DII data from Sheets. Returns dict with score/label."""
    if not (GOOGLE_SHEET_ID and GOOGLE_CREDS_JSON):
        return {"score": 15, "label": "↔ MIXED", "detail": "Sheets not configured"}
    try:
        import gspread, base64
        from google.oauth2.service_account import Credentials
        raw = GOOGLE_CREDS_JSON.strip()
        try:
            creds_dict = json.loads(base64.b64decode(raw).decode())
        except Exception:
            creds_dict = json.loads(raw)
        scopes = ["https://spreadsheets.google.com/feeds",
                  "https://www.googleapis.com/auth/spreadsheets",
                  "https://www.googleapis.com/auth/drive"]
        creds  = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        wb     = client.open_by_key(GOOGLE_SHEET_ID)
        ws     = wb.worksheet("FII_DII")
        rows   = ws.get_all_values()
        if len(rows) < 2:
            return {"score": 15, "label": "↔ MIXED", "detail": "No FII/DII data"}
        hdr    = [h.strip().upper() for h in rows[0]]
        df     = pd.DataFrame(rows[1:], columns=hdr)
        for c in ["FII_NET","DII_NET"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        recent = df.tail(5)
        fii_sum = float(recent["FII_NET"].sum()) if "FII_NET" in df.columns else 0.0
        dii_sum = float(recent["DII_NET"].sum()) if "DII_NET" in df.columns else 0.0
        both_buy  = fii_sum > 0 and dii_sum > 0
        fii_buy   = fii_sum > 0
        score = 28 if both_buy else 22 if fii_buy else 15 if dii_sum > 0 else 5
        label = ("🔥 FII+DII BOTH BUYING" if both_buy
                 else "✅ FII BUYING" if fii_buy
                 else "📘 DII BUYING" if dii_sum > 0
                 else "🔴 FII+DII SELLING")
        return {"score": score, "label": label,
                "detail": f"FII 5d: ₹{fii_sum/100:.0f}Cr | DII 5d: ₹{dii_sum/100:.0f}Cr"}
    except Exception as e:
        log.debug(f"FII/DII sheets: {e}")
        return {"score": 15, "label": "↔ MIXED", "detail": str(e)[:60]}


def fetch_macro_regime() -> dict:
    """
    Unified macro regime: CLEAR / CHOP / PANIC / MASSACRE.
    Uses India VIX + NIFTY 5d momentum + CNX500 breadth.
    """
    try:
        import yfinance as yf
        vix_df = yf.download("^INDIAVIX", period="5d", progress=False, auto_adjust=True)
        vix    = float(vix_df["Close"].squeeze().iloc[-1]) if not vix_df.empty else 18.0

        nifty_df = yf.download("^NSEI", period="15d", progress=False, auto_adjust=True)
        nifty_5d = 0.0
        breadth_ok = True
        nifty_above_ma50 = True
        if not nifty_df.empty and len(nifty_df) >= 5:
            nc = nifty_df["Close"].squeeze().values
            nifty_5d = float((nc[-1] - nc[-5]) / nc[-5] * 100)
            nifty_above_ma50 = float(nc[-1]) > float(np.mean(nc[-min(50,len(nc)):]))

        cnx_df = yf.download("^CNX500", period="60d", progress=False, auto_adjust=True)
        if not cnx_df.empty and len(cnx_df) >= 50:
            cc = cnx_df["Close"].squeeze().values
            breadth_ok = float(cc[-1]) > float(np.mean(cc[-50:]))

        if nifty_5d <= -3.0:
            state = "MASSACRE"
        elif vix >= 22.0:
            state = "PANIC"
        elif vix >= 16.0 or not breadth_ok:
            state = "CHOP"
        else:
            state = "CLEAR"

        log.info(f"Macro: {state} | VIX={vix:.1f} | NIFTY 5d={nifty_5d:+.1f}% | Breadth={'✓' if breadth_ok else '✗'}")
        return {"macro_state": state, "vix_val": vix, "nifty_5d": nifty_5d,
                "breadth_ok": breadth_ok, "nifty_above_ma50": nifty_above_ma50}
    except Exception as e:
        log.warning(f"Macro fetch failed: {e}")
        return {"macro_state": "CHOP", "vix_val": 18.0, "nifty_5d": 0.0,
                "breadth_ok": True, "nifty_above_ma50": True}


# ══════════════════════════════════════════════════════════════════════════
# SECTION 4 — INDICATOR TOOLKIT
# ══════════════════════════════════════════════════════════════════════════

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    d = series.diff()
    g = d.clip(lower=0).ewm(span=period, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(span=period, adjust=False).mean()
    return 100 - (100 / (1 + g / l.replace(0, np.nan)))


def _adx(df: pd.DataFrame, period: int = 14) -> float:
    h, l, c = df["high"], df["low"], df["close"]
    tr  = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    up  = h - h.shift(); dn = l.shift() - l
    pdm = up.where((up > dn) & (up > 0), 0)
    ndm = dn.where((dn > up) & (dn > 0), 0)
    pdi = 100 * pdm.ewm(span=period, adjust=False).mean() / atr
    ndi = 100 * ndm.ewm(span=period, adjust=False).mean() / atr
    dx  = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    val = float(dx.ewm(span=period, adjust=False).mean().iloc[-1])
    return val if not math.isnan(val) else 0.0


def _mfi(df: pd.DataFrame, period: int = 14) -> float:
    tp  = (df["high"] + df["low"] + df["close"]) / 3
    rmf = tp * df["volume"]
    pos = rmf.where(tp > tp.shift(), 0)
    neg = rmf.where(tp < tp.shift(), 0)
    mfr = pos.rolling(period).sum() / neg.rolling(period).sum().replace(0, np.nan)
    s   = 100 - (100 / (1 + mfr))
    v   = float(s.iloc[-1]) if not s.empty else 50.0
    return v if not math.isnan(v) else 50.0


def _obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff().fillna(0))
    return (df["volume"] * direction).cumsum()


def _vpoc(df: pd.DataFrame, n_bins: int = 50) -> dict:
    """
    Volume Profile — POC + Value Area (70% of volume).
    Returns dict with poc, va_high, va_low, whale_pct.
    """
    result = {"poc": 0.0, "va_high": 0.0, "va_low": 0.0, "whale_pct": 0.0}
    lookback = df.tail(63)
    if len(lookback) < 20:
        return result
    pmin, pmax = float(lookback["low"].min()), float(lookback["high"].max())
    if pmax <= pmin:
        return result
    total_vol = float(lookback["volume"].sum())
    if total_vol <= 0:
        return result

    bins = np.linspace(pmin, pmax, n_bins + 1)
    bin_vol = np.zeros(n_bins)
    for _, row in lookback.iterrows():
        bl, bh, vol = float(row["low"]), float(row["high"]), float(row["volume"])
        if vol <= 0 or bh <= bl:
            continue
        overlap = np.maximum(0.0, np.minimum(bh, bins[1:]) - np.maximum(bl, bins[:-1]))
        bin_vol += vol * (overlap / (bh - bl))

    poc_idx = int(np.argmax(bin_vol))
    result["poc"] = float((bins[poc_idx] + bins[poc_idx + 1]) / 2)
    result["whale_pct"] = float(bin_vol[poc_idx] / total_vol * 100)

    sorted_idx = np.argsort(bin_vol)[::-1]
    cum_vol    = np.cumsum(bin_vol[sorted_idx])
    va_idx     = sorted_idx[cum_vol <= total_vol * 0.70]
    if len(va_idx) > 0:
        result["va_low"]  = float(bins[va_idx.min()])
        result["va_high"] = float(bins[va_idx.max() + 1])
    return result


# ══════════════════════════════════════════════════════════════════════════
# SECTION 5 — FORTRESS VPOC SNIPER ENGINE (from fortress v8.2)
# ══════════════════════════════════════════════════════════════════════════

def calc_fortress_vpoc_score(hist: pd.DataFrame, close: float, atr14: float,
                              adv20: float, vpoc: float, ma200: float,
                              sector: str) -> Tuple[float, dict]:
    """
    6-Layer VPOC Sniper (fortress v8.2 calc_sniper_vpoc_layers).
    Returns (score 0-100, layer_dict).
    """
    vpoc_band = 0.02
    sector_atr_mult = SECTOR_ATR_MULT.get(sector, 1.0)

    layer1 = (abs(close - vpoc) / vpoc <= vpoc_band) if vpoc > 0 else False

    if len(hist) >= 252 and adv20 > 0:
        spike_days = int((hist["volume"].tail(252) > 2 * adv20).sum())
        layer2 = spike_days >= 35
    else:
        layer2 = False

    recency = min(45, len(hist))
    touches = sum(1 for _, r in hist.tail(recency).iterrows()
                  if vpoc > 0 and abs(float(r["close"]) - vpoc) / vpoc <= 0.03)
    layer3 = touches >= 3

    turnover_cr = float(hist["volume"].iloc[-1]) * close / 1e7 if len(hist) > 0 else 0
    vol_ok  = adv20 > 0 and float(hist["volume"].iloc[-1]) >= 2.0 * adv20
    turn_ok = turnover_cr >= 3.0
    layer4  = vol_ok and turn_ok

    if len(hist) >= 52:
        h52    = float(hist["high"].tail(252).max())
        l52    = float(hist["low"].tail(252).min())
        fib618 = l52 + 0.618 * (h52 - l52) if h52 > l52 else close
        layer5 = close > vpoc or abs(close - fib618) / fib618 <= 0.03
    else:
        layer5 = close >= vpoc

    alt_pct = (close - ma200) / ma200 * 100 if ma200 > 0 else 0
    layer6  = alt_pct < 60.0

    raw = (25 if layer1 else 0) + (20 if layer2 else 0) + (25 if layer3 else 0) + \
          (15 if layer4 else 0) + (10 if layer5 else 0) + (5  if layer6 else 0)

    return float(raw), {
        "layer1": layer1, "layer2": layer2, "layer3": layer3,
        "layer4": layer4, "layer5": layer5, "layer6": layer6,
        "all_layers": all([layer1, layer2, layer3, layer4, layer5, layer6]),
        "alt_pct": round(alt_pct, 1), "touches": touches,
    }


# ══════════════════════════════════════════════════════════════════════════
# SECTION 6 — WHALE RADAR (from Smart Money Sniper v1.0, enhanced)
# ══════════════════════════════════════════════════════════════════════════

def calc_whale_radar(hist: pd.DataFrame, adv20: float) -> Tuple[float, dict]:
    """
    Detects silent institutional accumulation: price flat, volume rising.
    Combines v1.0 OBV slope + v9.0 stealth score + volume spike concentration.
    Returns (score 0-100, detail_dict).
    """
    LOOKBACK     = 15
    PRICE_FLAT   = 0.03   # ±3% = flat
    VOL_UP_RATIO = 0.30   # 20d MA > 30% above 60d MA

    if len(hist) < max(LOOKBACK, 60):
        return 0.0, {"whale_detected": False, "signal_type": "NONE",
                     "whale_label": "", "stealth_score": 0}

    tail   = hist.tail(LOOKBACK)
    p_vel  = float((tail["close"].iloc[-1] - tail["close"].iloc[0]) /
                    tail["close"].iloc[0] * 100) if float(tail["close"].iloc[0]) > 0 else 0.0
    flat   = abs(p_vel) < PRICE_FLAT * 100

    vol20 = float(hist["volume"].tail(20).mean())
    vol60 = float(hist["volume"].tail(60).mean())
    if vol60 <= 0:   # APEX-LOW-01: explicit guard before division
        return 0.0, {"whale_detected": False, "signal_type": "NONE",
                     "whale_label": "", "stealth_score": 0}
    vol_rising = (vol20 / vol60 - 1) >= VOL_UP_RATIO

    # OBV slope
    obv_s = _obv(tail)
    obv_slope = float(obv_s.iloc[-1] - obv_s.iloc[0]) / max(1, abs(float(obv_s.iloc[0])) + 1)
    obv_up = obv_slope > 0

    # Volume spikes (≥2.5x ADV)
    spike_days = int((tail["volume"] > 2.5 * max(adv20, 1)).sum()) if adv20 > 0 else 0

    # Price range compression
    rng_now  = float(tail["high"].tail(5).max() - tail["low"].tail(5).min())
    rng_prev = float(hist.tail(40).head(35)["high"].max() - hist.tail(40).head(35)["low"].min())
    compressed = rng_prev > 0 and (rng_now / rng_prev) < 0.40

    # Stealth: price change within ±1.5%, volume trend positive
    price_window = hist["close"].tail(5).values
    vol_window   = hist["volume"].tail(5).values.astype(float)
    price_rng_pct = float(abs(price_window[-1] - price_window[0]) / max(price_window[0], 1) * 100)
    vol_trend     = float(np.polyfit(range(5), vol_window, 1)[0]) if len(vol_window) == 5 else 0
    stealth = price_rng_pct <= 1.5 and vol_trend > 0 and adv20 > 0 and vol_window[-1] > adv20 * 1.2
    stealth_score = min(100.0, 40 + abs(vol_trend) * 10) if stealth else 0.0

    # Signal classification
    signal_type = "NONE"
    if flat and vol_rising:
        signal_type = "STEALTH" if stealth_score > 40 else "ACCUMULATION"
    elif flat and obv_up:
        signal_type = "STEALTH"
    elif not flat and vol_rising:
        signal_type = "ACCUMULATION"

    # Score
    score = 0
    parts = []
    if flat and vol_rising:
        score += 40
        parts.append(f"🐋 Flat+Vol ({(vol20/max(vol60,1)-1)*100:.0f}% above 60d MA)")
    if stealth_score > 40:
        score += int(stealth_score * 0.35)
        parts.append(f"🕵️ Stealth {stealth_score:.0f}")
    if obv_up and flat:
        score += 20
        parts.append("📈 OBV rising on flat price")
    if spike_days >= 3:
        score += min(20, spike_days * 5)
        parts.append(f"🔦 {spike_days} vol spikes")
    if compressed:
        score += 15
        parts.append(f"🌀 Range compressed {rng_now/max(rng_prev,1)*100:.0f}%")
    if not flat and vol_rising:
        score += 10
        parts.append(f"⚡ Expanding volume")

    score = min(100, score)
    label = " | ".join(parts) if parts else ""
    detected = score >= 35 or stealth_score >= 50

    return float(score), {
        "whale_detected": detected,
        "signal_type":    signal_type,
        "whale_label":    label,
        "stealth_score":  stealth_score,
        "price_velocity": round(p_vel, 2),
        "vol_velocity":   round((vol20 / max(vol60, 1) - 1) * 100, 1),
        "spike_days":     spike_days,
        "obv_rising":     obv_up,
    }


# ══════════════════════════════════════════════════════════════════════════
# SECTION 7 — DIVERGENCE ENGINE (from Divergence Sniper v9.0)
# ══════════════════════════════════════════════════════════════════════════

def calc_divergence(hist: pd.DataFrame) -> Tuple[float, dict]:
    """
    Detect RSI Hidden Divergence + OBV divergence for swing continuation.
    BULLISH HIDDEN: Price HL, RSI LL → institutional dip buying.
    Returns (score 0-100, detail_dict).
    """
    WINDOW = 15

    if len(hist) < WINDOW + 20:
        return 0.0, {"div_type": "NONE", "div_label": "Insufficient data", "div_strength": 0}

    rsi_s = _rsi(hist["close"])
    obv_s = _obv(hist)

    lookback  = hist.tail(WINDOW + 5)
    prices    = lookback["close"].values
    rsis      = rsi_s.tail(len(lookback)).values
    obvs      = obv_s.tail(len(lookback)).values

    def find_pivots(arr, w=3):
        highs, lows = [], []
        for i in range(w, len(arr) - w):
            if all(arr[i] >= arr[i-j] for j in range(1, w+1)) and \
               all(arr[i] >= arr[i+j] for j in range(1, w+1)):
                highs.append((i, arr[i]))
            if all(arr[i] <= arr[i-j] for j in range(1, w+1)) and \
               all(arr[i] <= arr[i+j] for j in range(1, w+1)):
                lows.append((i, arr[i]))
        return highs, lows

    _, p_lows   = find_pivots(prices)
    r_highs, r_lows = find_pivots(rsis)
    o_highs, _  = find_pivots(obvs)

    div_type   = "NONE"
    strength   = 0.0
    confirm_bars = 0

    if len(p_lows) >= 2 and len(r_lows) >= 2:
        pl1, pl2 = p_lows[-2], p_lows[-1]
        rl1, rl2 = r_lows[-2], r_lows[-1]
        if pl2[1] > pl1[1] and rl2[1] < rl1[1]:
            div_type     = "BULLISH_HIDDEN"
            strength     = min(100.0, float((rl1[1] - rl2[1]) * 2 + 25))
            confirm_bars = len(prices) - pl2[0]

    # OBV rising while price stalling → hidden bullish confirmation
    obv_bonus = 0.0
    if len(o_highs) >= 2 and o_highs[-1][1] > o_highs[-2][1]:
        obv_bonus = 15.0

    div_score = strength * 0.85 + obv_bonus
    div_score = min(100.0, div_score)

    type_mult = {"BULLISH_HIDDEN": 1.0, "NONE": 0.0}
    div_score *= type_mult.get(div_type, 0.5)

    label = (f"🔀 {div_type} ({strength:.0f}%, {confirm_bars}d confirm)"
             if div_type != "NONE" else "No divergence")

    return float(div_score), {
        "div_type": div_type, "div_label": label,
        "div_strength": round(strength, 1),
        "confirm_bars": confirm_bars,
        "obv_bonus": round(obv_bonus, 1),
    }


# ══════════════════════════════════════════════════════════════════════════
# SECTION 8 — VOLUME PROFILE SCORE (from Divergence Sniper v9.0)
# ══════════════════════════════════════════════════════════════════════════

def calc_vol_profile_score(profile: dict, close: float) -> Tuple[float, str]:
    """Score price proximity to POC + Value Area. Returns (score 0-100, label)."""
    poc = profile.get("poc", 0)
    if poc <= 0:
        return 0.0, "No vol profile"

    score, notes = 0, []
    poc_dist = abs(close - poc) / poc * 100

    if poc_dist <= 1.0:
        score += 40; notes.append("AT POC 🎯")
    elif poc_dist <= 3.0:
        score += 25; notes.append("NEAR POC")
    elif poc_dist <= 5.0:
        score += 12; notes.append("POC ZONE")

    va_lo = profile.get("va_low", 0)
    va_hi = profile.get("va_high", 0)
    if va_lo > 0 and va_hi > 0:
        if va_lo <= close <= va_hi:
            score += 20; notes.append("INSIDE VA")
        elif close < va_lo:
            score += 8;  notes.append("BELOW VA (discount)")

    whale_pct = profile.get("whale_pct", 0)
    if whale_pct >= 35:
        score += 25; notes.append(f"WHALE DEFENSE {whale_pct:.0f}%")
    elif whale_pct >= 25:
        score += 15; notes.append(f"Strong POC {whale_pct:.0f}%")

    # Tight value area = institutional price control
    va_width = (va_hi - va_lo) / poc * 100 if poc > 0 and va_hi > va_lo else 0
    if 0 < va_width <= 8:
        score += 10; notes.append("TIGHT VA")

    label = " · ".join(notes) if notes else "Diffuse vol profile"
    return float(min(100, score)), label


# ══════════════════════════════════════════════════════════════════════════
# SECTION 9 — PATTERN RECOGNITION (from Smart Money Sniper v1.0 + v9.0)
# ══════════════════════════════════════════════════════════════════════════

def calc_pattern_score(hist: pd.DataFrame, atr14: float, profile: dict) -> Tuple[float, str]:
    """
    Detect high-probability swing setups:
    NR7, Inside Bar, VCP, Flat Base, Pocket Pivot, Cup & Handle, POC Bounce.
    Returns (score 0-100, label).
    """
    if len(hist) < 20:
        return 0.0, "No pattern"

    close  = hist["close"].values
    high   = hist["high"].values
    low    = hist["low"].values
    volume = hist["volume"].values
    n      = len(hist)
    score, patterns = 0, []

    # NR7 — Narrowest range in 7 bars
    if n >= 7:
        ranges = high - low
        if ranges[-1] <= ranges[-7:].min() + 1e-9:
            score += 20; patterns.append("NR7 🌀")

    # Inside Bar
    if n >= 2:
        today_rng = high[-1] - low[-1]
        prev_rng  = high[-2] - low[-2]
        if prev_rng > 0 and today_rng / prev_rng < 0.60:
            score += 15; patterns.append("Inside-Bar")

    # VCP — Volatility Contraction Pattern
    if n >= 30:
        pivots = []
        for i in range(5, n - 1):
            if high[i] >= high[i-1] and high[i] >= high[i-3]:
                pivots.append(("H", i, high[i]))
            elif low[i] <= low[i-1] and low[i] <= low[i-3]:
                pivots.append(("L", i, low[i]))
        if len(pivots) >= 3:
            last_p = pivots[-3:]
            swings = [abs(last_p[i][2] - last_p[i-1][2]) for i in range(1, len(last_p))]
            if len(swings) >= 2 and all(swings[i] < swings[i-1] for i in range(1, len(swings))):
                score += 30; patterns.append(f"VCP-{len(last_p)}P 🎯")

    # Flat Base (< 5% band over 10 bars)
    if n >= 10:
        r10    = close[-10:]
        band   = (r10.max() - r10.min()) / r10.mean() * 100
        if band < 5.0:
            score += 15; patterns.append(f"Flat-Base({band:.1f}%)")

    # Pocket Pivot
    if n >= 12:
        down_vols = volume[-10:][np.diff(close[-11:]) < 0]
        max_down  = float(down_vols.max()) if len(down_vols) > 0 else 0
        if max_down > 0 and volume[-1] > max_down and close[-1] > close[-2]:
            score += 20; patterns.append("Pocket-Pivot 💉")

    # Cup & Handle (proxy)
    if n >= 40:
        mid        = n // 2
        left_high  = float(hist["high"].iloc[:mid].max())
        right_high = float(hist["high"].iloc[mid:].max())
        mid_low    = float(hist["low"].iloc[mid-5:mid+5].min())
        cup_depth  = (left_high - mid_low) / left_high if left_high > 0 else 0
        if 0.05 <= cup_depth <= 0.20 and right_high >= left_high * 0.98 and close[-1] >= left_high * 0.95:
            score += 25; patterns.append("Cup&Handle 🏆")

    # POC Bounce
    poc = profile.get("poc", 0)
    if poc > 0 and n >= 5:
        for i in range(-5, 0):
            if abs(float(hist["low"].iloc[i]) - poc) / poc <= 0.015:
                if hist["close"].iloc[i] > hist["open"].iloc[i]:
                    score += 15; patterns.append("POC-Bounce")
                    break

    label = " + ".join(patterns) if patterns else "No pattern"
    return float(min(100, score)), label


# ══════════════════════════════════════════════════════════════════════════
# SECTION 10 — MONTE CARLO EDGE
# ══════════════════════════════════════════════════════════════════════════

def calc_monte_carlo(hist: pd.DataFrame, stop_loss: float, close: float) -> dict:
    """
    Student-t(df=5) Monte Carlo — survival + T1 hit probability.
    Slight heavier df=5 tail vs v1.0 (df=4) for overnight gap exposure.
    """
    if len(hist) < 30 or stop_loss <= 0:
        return {"survival": None, "t1_hit_pct": 0.0, "days_to_t1": None, "label": "MC: insufficient data"}

    closes  = hist["close"].values.astype(float)
    log_ret = np.diff(np.log(closes[closes > 0]))
    if len(log_ret) < 10:
        return {"survival": None, "t1_hit_pct": 0.0, "days_to_t1": None, "label": "MC: too few returns"}

    mu, sigma = float(np.mean(log_ret)), float(np.std(log_ret))
    rng       = np.random.default_rng(42)
    df        = MC_FAT_DF
    t_scale   = sigma * math.sqrt((df - 2) / df) if df > 2 else sigma
    t1_target = close * 1.10

    survived = hit_t1 = days_total = 0
    for _ in range(MC_SIMS):
        raw = rng.standard_t(df, size=MC_HORIZON)
        path = close * np.exp(np.cumsum(mu + t_scale * raw))
        if float(np.min(path)) > stop_loss:
            survived += 1
        if float(np.max(path)) >= t1_target:
            hit_t1 += 1
            for d, p in enumerate(path, 1):
                if p >= t1_target:
                    days_total += d
                    break

    surv_pct  = round(survived / MC_SIMS * 100, 1)
    t1_pct    = round(hit_t1 / MC_SIMS * 100, 1)
    avg_days  = round(days_total / max(1, hit_t1), 1) if hit_t1 > 0 else None

    # FIX-GAP-04: convergence check (two independent half-batch comparison)
    # APEX-MED-01: use separate seeds so s1/s2 are stochastically independent
    half  = MC_SIMS // 2
    rng1  = np.random.default_rng(42)
    rng2  = np.random.default_rng(43)
    s1    = sum(1 for _ in range(half) for p in [close * np.exp(np.cumsum(mu + t_scale * rng1.standard_t(df, size=MC_HORIZON)))]
               if float(np.min(p)) > stop_loss)
    s2    = sum(1 for _ in range(half) for p in [close * np.exp(np.cumsum(mu + t_scale * rng2.standard_t(df, size=MC_HORIZON)))]
               if float(np.min(p)) > stop_loss)
    converged = abs(s1 / max(1, half) * 100 - s2 / max(1, half) * 100) <= 8.0

    label = (f"✅ MC {surv_pct}% survive ({MC_HORIZON}d, t-df{df})" +
             ("" if converged else " [NOT CONVERGED]"))

    return {"survival": surv_pct, "t1_hit_pct": t1_pct, "days_to_t1": avg_days,
            "label": label, "converged": converged}


# ══════════════════════════════════════════════════════════════════════════
# SECTION 11 — 13-NODE BAYESIAN NETWORK (fortress 9-node + 4 new nodes)
# ══════════════════════════════════════════════════════════════════════════

def calc_bayesian_apex(
    macro_state: str, breadth_ok: bool,
    layer1: bool, layer2: bool, layer3: bool,   # VPOC layers
    whale_detected: bool,                      # MERGED: whale + stealth
    div_type: str, vol_profile_score: float,
    mfi_v: float, adx_v: float, alt_pct: float,
    mc_survival: float
) -> dict:
    """
    11-Node Bayesian Belief Network (deduplicated from v1.1's 13-node).
    FIX APEX-CRIT-03: Whale merged (no separate stealth node), VPOC merged.

    Prior: 0.30 (base hit-rate for profitable swing in Indian market)
    Laplace smoothing alpha: 0.12 (from fortress SNIPER_CFG)
    """
    prior = 0.30
    alpha = 0.12

    nodes = [
        # (condition, p_true, p_false)
        # --- Fortress nodes ---
        (macro_state == "CLEAR",          0.72, 0.28),
        (breadth_ok,                      0.65, 0.38),
        (layer1,                          0.72, 0.30),
        (layer2,                          0.68, 0.38),
        (layer3,                          0.70, 0.35),
        (mfi_v <= 45.0,                   0.68, 0.42),
        (adx_v >= 25.0,                   0.68, 0.38),
        (alt_pct < 30.0,                  0.62, 0.40),
        (whale_detected,                  0.74, 0.44),  # MERGED N9+N10
        # --- New APEX nodes ---
        (div_type == "BULLISH_HIDDEN",    0.70, 0.40),  # N11: Hidden divergence
        (vol_profile_score >= 40,         0.67, 0.40),  # N12: POC proximity
        (mc_survival is not None and mc_survival >= 65, 0.68, 0.45),  # N13: MC survival
    ]

    posterior = prior
    for condition, p_true, p_false in nodes:
        lk = p_true if condition else p_false
        posterior = (lk * posterior) / max(1e-9, lk * posterior + (1 - lk) * (1 - posterior))

    # Laplace smoothing
    posterior = alpha * prior + (1 - alpha) * posterior
    posterior = min(0.99, max(0.01, round(posterior, 3)))
    pct       = round(posterior * 100)

    if posterior >= 0.75:   tier, bonus = "🧠 VERY HIGH", 12
    elif posterior >= 0.65: tier, bonus = "🧠 HIGH",      8
    elif posterior >= 0.55: tier, bonus = "🧠 MODERATE",  4
    elif posterior >= 0.45: tier, bonus = "🧠 NEUTRAL",   0
    else:                   tier, bonus = "🧠 LOW",        -5

    return {"bayes_prob": posterior, "bayes_pct": pct,
            "bayes_tier": tier, "bayes_bonus": bonus,
            "bayes_label": f"{tier} conviction ({pct}%)"}


# ══════════════════════════════════════════════════════════════════════════
# SECTION 12 — APEX POSITION SIZING & EXIT PLAN
# ══════════════════════════════════════════════════════════════════════════

def calc_position(close: float, stop_loss: float, composite: float) -> dict:
    """
    Tiered Kelly-like sizing: risk% of equity per trade.
    Blend of vol-based and score-based share count.
    """
    risk_pct_equity = ACCOUNT_RISK_PCT
    risk_per_sh     = max(close - stop_loss, close * 0.02)
    risk_rupees     = ACCOUNT_EQUITY * risk_pct_equity

    shares_vol   = math.floor(risk_rupees / risk_per_sh) if risk_per_sh > 0 else 0
    score_factor = (composite / 100.0) ** 0.5
    shares_blend = math.floor(shares_vol * (0.5 + 0.5 * score_factor))

    # Grade-based deploy multiplier
    if composite >= GRADE_APEX:     deploy = 1.00
    elif composite >= GRADE_PRISTINE: deploy = 0.75
    elif composite >= GRADE_GOOD:   deploy = 0.50
    elif composite >= GRADE_PROBE:  deploy = 0.25
    else:                           deploy = 0.0

    shares_final = math.floor(shares_blend * deploy)
    max_shares   = math.floor((ACCOUNT_EQUITY * 0.10) / close) if close > 0 else 0
    shares_final = min(shares_final, max_shares)
    pos_value    = shares_final * close
    risk_actual  = shares_final * risk_per_sh / ACCOUNT_EQUITY * 100 if ACCOUNT_EQUITY > 0 else 0

    pos_label = (f"{shares_final} sh × ₹{close:.2f} = ₹{pos_value:,.0f} | "
                 f"Risk ₹{shares_final*risk_per_sh:,.0f} ({risk_actual:.1f}%)"
                 if shares_final > 0 else "— (below sizing min)")

    return {"shares": shares_final, "pos_value": round(pos_value), "deploy_pct": round(deploy * 100),
            "risk_actual_pct": round(risk_actual, 2), "pos_label": pos_label}


def calc_exit_plan(close: float, atr14: float, sector: str) -> dict:
    """
    3-Target graduated exit.
    R1 @ +8-10% → sell 30% | R2 @ +15-20% → sell 30% | R3 @ +28-35% → sell 40%.
    Trailing stop arms at R2.
    """
    atr_mult = SECTOR_ATR_MULT.get(sector, 1.0)
    risk     = atr14 * 2.0 * atr_mult if atr14 > 0 else close * 0.03

    r1 = round(close + risk * 2.5, 2)     # ~8-10%
    r2 = round(close + risk * 4.0, 2)     # ~15-20%
    r3 = round(close + risk * 6.5, 2)     # ~28-35%
    trail_trigger = r2
    trail_stop    = round(r2 - atr14 * 2.5 * atr_mult, 2)

    r1_pct = round((r1 - close) / close * 100, 1)
    r2_pct = round((r2 - close) / close * 100, 1)
    r3_pct = round((r3 - close) / close * 100, 1)

    return {
        "r1": r1, "r2": r2, "r3": r3,
        "r1_pct": r1_pct, "r2_pct": r2_pct, "r3_pct": r3_pct,
        "trail_trigger": trail_trigger, "trail_stop": trail_stop,
        "sell_pct_r1": 30, "sell_pct_r2": 30, "sell_pct_r3": 40,
    }


# ══════════════════════════════════════════════════════════════════════════
# SECTION 13 — APEX COMPOSITE SCORING ENGINE (FIXED)
# ══════════════════════════════════════════════════════════════════════════

# FIX APEX-CRIT-02: Earnings veto at GATE 0
def score_symbol(sym: str, hist: pd.DataFrame, close: float,
                 turnover_lakhs: float, macro: dict,
                 fii_data: dict) -> Optional[dict]:
    """Master scoring function. Earnings veto at GATE 0."""

    # ── GATE 0: Earnings veto (cheap, do first) ────────────────────────
    earnings_days = _check_earnings(sym)
    if earnings_days is not None and 0 <= earnings_days <= 3:
        log.warning(f"{sym}: EARNINGS VETO ({earnings_days}d) — skipped before scoring")
        return None

    # ── Hard gates ──────────────────────────────────────────────────────
    if not is_halal(sym):
        return None

    sector = get_sector(sym)
    if sector in SECTOR_BLOCKED:
        return None

    if len(hist) < 30:
        return None

    if turnover_lakhs < MIN_TURNOVER_LAKHS:
        return None

    macro_state = macro.get("macro_state", "CHOP")
    if macro_state == "MASSACRE":
        return None

    # ── Indicators ──────────────────────────────────────────────────────
    atr_series = _atr(hist, 14)
    atr14      = float(atr_series.iloc[-1]) if not atr_series.empty else 0.0
    if atr14 <= 0:
        return None

    sector_atr_mult = SECTOR_ATR_MULT.get(sector, 1.0)
    atr14_adj       = atr14 * sector_atr_mult

    rsi_v = float(_rsi(hist["close"]).iloc[-1])
    mfi_v = _mfi(hist)
    adx_v = _adx(hist)
    adv20 = float(hist["volume"].tail(20).mean())

    ma200 = float(hist["close"].tail(200).mean()) if len(hist) >= 200 else float(hist["close"].mean())
    alt_pct = (close - ma200) / ma200 * 100 if ma200 > 0 else 0

    # Hard gate: must be above MA200 (not in freefall)
    if alt_pct < -5.0:
        return None

    # ── Volume Profile ───────────────────────────────────────────────────
    profile    = _vpoc(hist)
    poc        = profile.get("poc", 0.0)

    # ── Stop Loss calculation ────────────────────────────────────────────
    stop_from_atr = close - 2.5 * atr14_adj
    stop_from_poc = poc * 0.97 if poc > 0 else stop_from_atr
    stop_loss     = round(max(min(stop_from_atr, stop_from_poc), close * 0.88), 2)
    risk_pct      = round((close - stop_loss) / close * 100, 1)

    # ── Sub-engine scores ───────────────────────────────────────────────

    # A. Fortress VPOC Sniper (0-100)
    vpoc_score, vpoc_layers = calc_fortress_vpoc_score(
        hist, close, atr14, adv20, poc, ma200, sector
    )

    # B. Whale Radar (0-100)
    whale_score, whale_detail = calc_whale_radar(hist, adv20)

    # C. Divergence Engine (0-100)
    div_score, div_detail = calc_divergence(hist)

    # D. Volume Profile Score (0-100)
    vp_score, vp_label = calc_vol_profile_score(profile, close)

    # E. Pattern Recognition (0-100)
    pat_score, pat_label = calc_pattern_score(hist, atr14, profile)

    # F. Monte Carlo
    mc = calc_monte_carlo(hist, stop_loss, close)
    mc_survival = mc.get("survival")

    # G. 13-Node Bayesian
    # FIX APEX-CRIT-03: De-duplicated Bayesian (whale merged, VPOC merged)
    bayes = calc_bayesian_apex(
        macro_state   = macro_state,
        breadth_ok    = macro.get("breadth_ok", True),
        layer1        = vpoc_layers["layer1"],
        layer2        = vpoc_layers["layer2"],
        layer3        = vpoc_layers["layer3"],
        whale_detected= whale_detail["whale_detected"] or whale_detail["stealth_score"] >= 50,
        div_type      = div_detail["div_type"],
        vol_profile_score = vp_score,
        mfi_v         = mfi_v,
        adx_v         = adx_v,
        alt_pct       = alt_pct,
        mc_survival   = mc_survival,
    )

    # ── APEX COMPOSITE ───────────────────────────────────────────────────
    mc_score = mc_survival if mc_survival is not None else 50.0
    bayes_score = float(bayes["bayes_pct"])

    raw_composite = (
        vpoc_score  * W["fortress_vpoc"] +
        whale_score * W["whale_radar"]   +
        div_score   * W["divergence"]    +
        vp_score    * W["vol_profile"]   +
        pat_score   * W["pattern"]       +
        bayes_score * W["bayesian"]
    )

    # Macro damping
    macro_damp = {"CLEAR": 1.0, "CHOP": 0.88, "PANIC": 0.60, "MASSACRE": 0.0}
    composite  = round(raw_composite * macro_damp.get(macro_state, 0.88))
    composite  = min(100, max(0, composite))

    # Bonus: Whale STEALTH + strong VPOC layers (the gold combo)
    if whale_detail["signal_type"] == "STEALTH" and vpoc_layers["all_layers"]:
        composite = min(100, composite + 8)

    # Bonus: full bayes alignment
    if bayes["bayes_pct"] >= 70:
        composite = min(100, composite + 5)

    # Filter below minimum
    if composite < APEX_MIN_SCORE:
        return None

    # ── Grade ─────────────────────────────────────────────────────────
    if composite >= GRADE_APEX:
        grade, grade_icon = "⚔️ APEX",    "⚔️"
    elif composite >= GRADE_PRISTINE:
        grade, grade_icon = "💎 PRISTINE", "💎"
    elif composite >= GRADE_GOOD:
        grade, grade_icon = "🟢 GOOD",     "🟢"
    elif composite >= GRADE_PROBE:
        grade, grade_icon = "🔵 PROBE",    "🔵"
    else:
        return None

    # ── Exit plan & position ────────────────────────────────────────────
    exits    = calc_exit_plan(close, atr14_adj, sector)
    position = calc_position(close, stop_loss, composite)

    # ── Story (why to buy) ───────────────────────────────────────────────
    story_parts = []
    if whale_detail["whale_detected"]:
        story_parts.append(whale_detail["whale_label"].split("|")[0].strip()[:60])
    if vpoc_layers["layer1"]:
        story_parts.append(f"Price AT institutional POC (₹{poc:.2f})")
    if div_detail["div_type"] == "BULLISH_HIDDEN":
        story_parts.append("Hidden RSI divergence — smart money dip-buying")
    if "Cup" in pat_label or "VCP" in pat_label:
        story_parts.append(f"Pattern: {pat_label[:50]}")
    if bayes["bayes_pct"] >= 65:
        story_parts.append(f"11-node Bayes: {bayes['bayes_pct']}% conviction")
    if not story_parts:
        story_parts.append(f"APEX score {composite}/100 — composite setup")
    story = "; ".join(story_parts[:3])

    # ── Earnings proximity (yfinance best-effort) ────────────────────────
    earnings_days = _check_earnings(sym)

    return {
        "symbol":    sym,
        "sector":    sector,
        "close":     round(close, 2),
        "composite": composite,
        "grade":     grade,
        "grade_icon": grade_icon,

        # Trade plan
        "stop_loss":  stop_loss,
        "risk_pct":   risk_pct,
        "buy_lo":     round(close * 0.99, 2),
        "buy_hi":     round(close * 1.01, 2),

        # Exits
        "r1": exits["r1"], "r2": exits["r2"], "r3": exits["r3"],
        "r1_pct": exits["r1_pct"], "r2_pct": exits["r2_pct"], "r3_pct": exits["r3_pct"],
        "sell_r1": exits["sell_pct_r1"], "sell_r2": exits["sell_pct_r2"], "sell_r3": exits["sell_pct_r3"],
        "trail_stop": exits["trail_stop"],

        # Position
        "shares":       position["shares"],
        "pos_value":    position["pos_value"],
        "deploy_pct":   position["deploy_pct"],
        "pos_label":    position["pos_label"],

        # Sub-scores
        "vpoc_score":  round(vpoc_score, 1),
        "whale_score": round(whale_score, 1),
        "div_score":   round(div_score, 1),
        "vp_score":    round(vp_score, 1),
        "pat_score":   round(pat_score, 1),
        "bayes_pct":   bayes["bayes_pct"],
        "mc_survival": mc_survival,

        # Labels
        "whale_label":  whale_detail["whale_label"],
        "pat_label":    pat_label,
        "div_label":    div_detail["div_label"],
        "div_detail":   div_detail,
        "vp_label":     vp_label,
        "mc_label":     mc["label"],
        "bayes_label":  bayes["bayes_label"],
        "vpoc_layers":  vpoc_layers,

        # Fundamentals
        "rsi":    round(rsi_v, 1),
        "mfi":    round(mfi_v, 1),
        "adx":    round(adx_v, 1),
        "atr14":  round(atr14, 2),
        "poc":    round(poc, 2),
        "ma200":  round(ma200, 2),
        "alt_pct": round(alt_pct, 1),
        "adv20":   round(adv20, 0),
        "turnover_lakhs": round(turnover_lakhs, 1),
        "whale_signal": whale_detail["signal_type"],

        # Story
        "story":         story,
        "earnings_days": earnings_days,

        # MC
        "days_to_r1_est": mc.get("days_to_t1") or SWING_HORIZON_DAYS,
        "r1_hit_prob":    mc.get("t1_hit_pct", 0),
    }


# FIX APEX-CRIT-02: Returns nearest future date, not first parsed
def _check_earnings(sym: str) -> Optional[int]:
    """Best-effort earnings proximity check via yfinance. Returns nearest future date."""
    try:
        import yfinance as yf
        t   = yf.Ticker(f"{sym}.NS")
        cal = t.calendar
        if cal is None:
            return None
        dates = cal.get("Earnings Date", []) if isinstance(cal, dict) else []
        if hasattr(cal, "T"):
            try:
                dates = cal.T.get("Earnings Date", [])
            except Exception:
                pass
        today = datetime.today()
        future_days = []
        for d in (dates if hasattr(dates, "__iter__") else [dates]):
            try:
                dt = pd.to_datetime(d).to_pydatetime()
                days = (dt - today).days
                if days >= 0:
                    future_days.append(days)
            except Exception:
                pass
        return min(future_days) if future_days else None
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════════
# SECTION 14 — TELEGRAM FORMATTER (fortress v8.2 MarkdownV2 escaped)
# ══════════════════════════════════════════════════════════════════════════

_MD_SPECIAL = r'\_*[]()~`>#+-=|{}.!'

def _em(s) -> str:
    """Escape all MarkdownV2 special characters for structural markdown (fortress FIX-AUDIT-01)."""
    text = str(s) if s is not None else ""
    out  = []
    for ch in text:
        if ch in _MD_SPECIAL:
            out.append("\\")
        out.append(ch)
    return "".join(out)


# APEX-LOW-02: separate escaper for user-facing data values (labels, story text).
# Only escapes chars that break MarkdownV2 *outside* bold/italic structural positions,
# so emojis and label text (e.g. "🐋 Flat+Vol") are not double-escaped.
_MD_DATA_SPECIAL = r'\_*[]()~`>#+=|{}.!'   # excludes '-' which is safe in data text

def _em_data(s) -> str:
    """Escape MarkdownV2 special chars for data/label values. Safe for emoji-prefixed strings."""
    text = str(s) if s is not None else ""
    out  = []
    for ch in text:
        if ch in _MD_DATA_SPECIAL:
            out.append("\\")
        out.append(ch)
    return "".join(out)


def format_pick_telegram(r: dict, rank: int, macro: dict, date_label: str) -> str:
    sym   = _em(r["symbol"])
    sec   = _em(r["sector"])
    price = _em(f"₹{r['close']:.2f}")
    blo   = _em(f"₹{r['buy_lo']:.2f}")
    bhi   = _em(f"₹{r['buy_hi']:.2f}")
    sl    = _em(f"₹{r['stop_loss']:.2f}")
    risk  = _em(f"{r['risk_pct']}%")
    r1    = _em(f"₹{r['r1']:.2f} (+{r['r1_pct']}%) → sell {r['sell_r1']}%")
    r2    = _em(f"₹{r['r2']:.2f} (+{r['r2_pct']}%) → sell {r['sell_r2']}%")
    r3    = _em(f"₹{r['r3']:.2f} (+{r['r3_pct']}%) → sell {r['sell_r3']}%")
    trail = _em(f"₹{r['trail_stop']:.2f}")
    score = _em(r["composite"])
    days  = _em(r["days_to_r1_est"])
    hitp  = _em(f"{r['r1_hit_prob']:.0f}%")
    surv  = _em(f"{r['mc_survival']:.0f}%") if r["mc_survival"] else _em("N/A")
    grade = r["grade"]

    # Sub-scores
    vs = _em(f"{r['vpoc_score']:.0f}")
    ws = _em(f"{r['whale_score']:.0f}")
    ds = _em(f"{r['div_score']:.0f}")
    ps = _em(f"{r['pat_score']:.0f}")
    bs = _em(f"{r['bayes_pct']}")
    story = _em_data(r["story"])
    whale_lbl = _em_data(r["whale_label"][:70]) if r["whale_label"] else _em("None")
    pat_lbl   = _em_data(r["pat_label"])
    div_lbl   = _em_data(r["div_label"][:60])
    pos_lbl   = _em_data(r["pos_label"])

    vix = macro.get("vix_val", 18.0)
    macro_state = macro.get("macro_state", "CHOP")
    macro_icon  = {"CLEAR":"✅","CHOP":"⚠️","PANIC":"🔴","MASSACRE":"💀"}.get(macro_state, "❓")

    layers = r.get("vpoc_layers", {})
    layer_str = "".join(["✓" if layers.get(f"layer{i}") else "✗" for i in range(1, 7)])

    lines = [
        f"{grade} \\#{rank} — *{sym}* \\| {sec}",
        f"",
        f"💰 *Price:* {price} \\| 📊 *Score:* {score}/100",
        f"",
        f"🎯 *BUY Zone:* {blo} – {bhi}",
        f"🛑 *Stop Loss:* {sl} \\(Risk {risk}\\)",
        f"",
        f"📈 *Exit Plan:*",
        f"  R1 → {r1}",
        f"  R2 → {r2}",
        f"  R3 → {r3}",
        f"  🛡 *Trail:* arms at R2 → stop {trail}",
        f"",
        f"⏱ *R1 est:* ~{days} days \\| *Hit prob:* {hitp} \\| *MC Survival:* {surv}",
        f"",
        f"🔬 *Layer Scores \\(APEX Fusion\\):*",
        f"  🏛 VPOC Sniper: {vs}/100 \\[{_em(layer_str)}\\]",
        f"  🐋 Whale Radar: {ws}/100 — {whale_lbl}",
        f"  🔀 Divergence:  {ds}/100 — {div_lbl}",
        f"  📐 Pattern:     {ps}/100 — {pat_lbl}",
        f"  🧠 Bayes \\(13\\-node\\): {bs}%",
        f"",
        f"💼 *Position:* {pos_lbl}",
        f"",
        f"❓ *Why:* _{story}_",
        f"",
        f"📅 {_em(date_label)} \\| {macro_icon} {_em(macro_state)} \\| VIX {_em(f'{vix:.1f}')}",
    ]
    return "\n".join(lines)


def format_header_telegram(n: int, date_label: str, macro: dict, data_source: str) -> str:
    macro_state = macro.get("macro_state", "CHOP")
    vix         = macro.get("vix_val", 18.0)
    icon        = {"CLEAR":"✅","CHOP":"⚠️","PANIC":"🔴","MASSACRE":"💀"}.get(macro_state, "❓")
    return (
        f"⚔️ *APEX SNIPER v1\\.1 — HALAL SWING INTELLIGENCE*\n"
        f"📅 {_em(date_label)} \\| {icon} {_em(macro_state)} \\| VIX {_em(f'{vix:.1f}')} "
        f"\\| {_em(data_source)}\n"
        f"💎 *{n} Premium Setup\\(s\\) — All layers fused*\n"
        f"{'─' * 34}"
    )


def format_footer_telegram(count: int, screened: int) -> str:
    return (
        f"\n{'─' * 34}\n"
        f"🔎 Screened {_em(screened)} halal candidates → {_em(count)} picks\n"
        f"⚖️ Shariah compliant \\| 10\\-15 day swing \\| Risk 1\\.5% per trade\n"
        f"🤲 _Bismillah — trade with discipline and tawakkul_"
    )


def _send_telegram(token: str, chat_id: str, text: str):
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chunk in _split_msg(text):
        try:
            r = requests.post(url, json={"chat_id": chat_id, "text": chunk,
                                          "parse_mode": ""}, timeout=20)  # Plain text, no MarkdownV2
            if not r.ok:
                log.warning(f"Telegram {r.status_code}: {r.text[:200]}")
        except Exception as e:
            log.warning(f"Telegram error: {e}")


def _split_msg(msg: str, limit: int = 4000) -> List[str]:
    """Split long message, walking back up to 20 chars to avoid cutting MarkdownV2 escapes."""
    if len(msg) <= limit:
        return [msg]
    parts = []
    while msg:
        if len(msg) <= limit:
            parts.append(msg); break
        cut = limit
        for i in range(min(20, cut), 0, -1):
            if msg[cut - i] == "\n":
                cut = cut - i; break
        parts.append(msg[:cut])
        msg = msg[cut:].lstrip("\n")
    return parts


def send_all_telegram(messages: List[str]):
    targets = [TELEGRAM_CHAT_ID] + TELEGRAM_SHARE_IDS
    for cid in targets:
        if not cid:
            continue
        for msg in messages:
            _send_telegram(TELEGRAM_TOKEN, cid, msg)
            time.sleep(0.4)


# ══════════════════════════════════════════════════════════════════════════
# SECTION 15 — PERSISTENCE
# ══════════════════════════════════════════════════════════════════════════

# FIX APEX-HIGH-05: save_results properly defined
def save_results(picks: List[dict], run_date: str):
    if not picks:
        return
    try:
        conn = sqlite3.connect(DB_PATH)
        for r in picks:
            conn.execute("""
                INSERT OR IGNORE INTO apex_results
                (run_date, symbol, grade, composite_score, close, stop_loss, t1, t2, t3, story)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (run_date, r["symbol"], r["grade"], r["composite"],
                  r["close"], r["stop_loss"], r["r1"], r["r2"], r["r3"], r["story"]))
        conn.commit()
        conn.close()
        log.info(f"Persisted {len(picks)} picks to DB")
    except Exception as e:
        log.error(f"DB save failed: {e}")


# ══════════════════════════════════════════════════════════════════════════
# SECTION 16 — MAIN ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════

def run_apex_sniper() -> List[dict]:
    """
    Main entry point. Full pipeline:
    1. DB init
    2. Macro regime
    3. Universe load (Sheets → yfinance → Google Finance → nsepython)
    4. FII/DII
    5. Score each candidate (all 7 engines per symbol)
    6. Rank + sector cap
    7. Telegram output
    8. Persist results
    """
    _init_db()
    date_label = datetime.today().strftime("%d %b %Y")

    log.info("=" * 70)
    log.info(f"⚔️  APEX SNIPER v1.2 — {date_label}")
    log.info(f"    Bismillah — Unified Halal Swing Intelligence Engine")
    log.info("=" * 70)

    # ── Macro ─────────────────────────────────────────────────────────────
    macro = fetch_macro_regime()

    if macro["macro_state"] == "MASSACRE":
        msg = "💀 MARKET MASSACRE — APEX Sniper halted\\. No entries today\\. Stay in cash\\."
        send_all_telegram([msg])
        log.error("🚨 MASSACRE state — all entries halted")
        return []

    if macro["macro_state"] == "PANIC":
        log.warning("🔴 VIX PANIC — only PROBE-grade entries pass this session")

    # ── Universe ──────────────────────────────────────────────────────────
    data_source = "SHEETS"
    universe    = pd.DataFrame()

    if not FORCE_YFINANCE:
        log.info("Loading BHAVCOPY from Google Sheets...")
        universe = load_bhavcopy_sheets()
        if universe.empty:
            log.warning("Sheets unavailable — falling back to yfinance snapshot")

    if universe.empty and not FORCE_YFINANCE:
        log.info("Building yfinance universe snapshot...")
        universe    = build_universe_yfinance()
        data_source = "YFINANCE"

    if universe.empty and GOOGLE_FINANCE_ENABLED:
        log.info("Building Google Finance universe snapshot...")
        universe    = build_universe_google_finance()
        data_source = "GOOGLE_FINANCE"

    if universe.empty and NSEPYTHON_ENABLED:
        log.info("Building nsepython universe snapshot...")
        universe    = build_universe_nsepython()
        data_source = "NSEPYTHON"

    if universe.empty:
        log.error("❌ No data source available. Abort.")
        return []

    log.info(f"Universe: {len(universe)} rows from {data_source}")

    # Normalise
    for c in ["close", "turnover_lakhs"]:
        if c in universe.columns:
            universe[c] = pd.to_numeric(universe[c], errors="coerce")
    if "turnover_lakhs" not in universe.columns:
        universe["turnover_lakhs"] = 0.0
    universe["symbol"] = universe["symbol"].astype(str).str.strip().str.upper()

    # Pre-filter
    candidates = universe[
        universe["close"].between(MIN_PRICE, MAX_PRICE) &
        (universe["turnover_lakhs"] >= MIN_TURNOVER_LAKHS) &
        universe["symbol"].apply(is_halal)
    ].sort_values("turnover_lakhs", ascending=False).head(200).reset_index(drop=True)

    log.info(f"Candidates after filter: {len(candidates)}")

    # ── FII/DII ───────────────────────────────────────────────────────────
    log.info("Fetching FII/DII data...")
    fii_data = fetch_fii_dii_sheets()
    log.info(f"FII/DII: {fii_data['label']}")

    # ── Main scoring loop ─────────────────────────────────────────────────
    results, screened = [], 0

    for i, (_, row) in enumerate(candidates.iterrows()):
        sym   = row["symbol"]
        close = float(row.get("close", 0))
        tover = float(row.get("turnover_lakhs", 0))

        if i % 20 == 0:
            log.info(f"Progress: {i}/{len(candidates)} | picks so far: {len(results)}")

        try:
            hist = fetch_history(sym, days=300)
            if len(hist) < 30:
                log.debug(f"{sym}: only {len(hist)} bars — skip")
                continue

            screened += 1
            result = score_symbol(sym, hist, close, tover, macro, fii_data)
            if result:
                results.append(result)
                log.info(f"  ✅ {sym} | {result['composite']}/100 | {result['grade']}")

            time.sleep(0.20)

        except Exception as e:
            log.debug(f"{sym}: {e}")

    log.info(f"Screened: {screened} | Picks found: {len(results)}")

    # ── Rank by composite (whale × vpoc combo bonus) ─────────────────────
    results.sort(
        key=lambda x: (
            x["composite"] * 1000
            + x["whale_score"] * 10
            + x["vpoc_score"]
        ),
        reverse=True
    )

    # ── Sector cap: max 2 per sector ──────────────────────────────────────
    sector_counts: dict = {}
    capped: List[dict]  = []
    for r in results:
        sec = r["sector"]
        if sector_counts.get(sec, 0) < 2:
            capped.append(r)
            sector_counts[sec] = sector_counts.get(sec, 0) + 1

    top_picks = capped[:APEX_TOP_N]

    log.info(f"\n{'=' * 70}")
    log.info(f"⚔️  APEX SNIPER TOP {len(top_picks)} PICKS")
    log.info(f"{'=' * 70}")
    for rank, r in enumerate(top_picks, 1):
        log.info(
            f"#{rank} {r['symbol']:12s} | {r['grade']:15s} | Score {r['composite']}/100 "
            f"| ₹{r['close']} | SL ₹{r['stop_loss']} | R1 ₹{r['r1']} | R2 ₹{r['r2']}"
        )
        log.info(f"     {r['story']}")

    # ── Telegram ──────────────────────────────────────────────────────────
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        messages = [format_header_telegram(len(top_picks), date_label, macro, data_source)]
        for rank, r in enumerate(top_picks, 1):
            messages.append(format_pick_telegram_clean(r, rank))
            messages.append("─" * 30)  # Separator between picks
        messages.append(format_footer_telegram(len(top_picks), screened))
        send_all_telegram(messages)
        log.info(f"Telegram sent: {len(messages)} messages")
    else:
        log.info("Telegram not configured — results printed above")

    # ── PAPER MODE ────────────────────────────────────────────────────────
    if PAPER_MODE and top_picks:
        log.info("\n=== PAPER MODE ===")
        for r in top_picks:
            log.info(
                f"{r['symbol']:12s} | Grade {r['grade']} | "
                f"Score {r['composite']}/100 | Entry ₹{r['buy_lo']}-{r['buy_hi']} "
                f"| SL ₹{r['stop_loss']} | R1 ₹{r['r1']} | R2 ₹{r['r2']} | R3 ₹{r['r3']}"
            )

    # ── Persist ───────────────────────────────────────────────────────────
    save_results(top_picks, date_label)

    return top_picks


# ══════════════════════════════════════════════════════════════════════════
# SECTION 17 — FORTRESS / FORTRESS_v82 INTEGRATION BRIDGE
# ══════════════════════════════════════════════════════════════════════════

# FIX APEX-CRIT-04: MASSACRE/PANIC abort at top
def run_apex_after_fortress(
    fortress_results: List[dict],
    bhavcopy_df: pd.DataFrame,
    fii_data: dict,
) -> List[dict]:
    """Drop-in: call after fortress run_screener_v8() completes."""
    log.info("⚔️  APEX Sniper — Fortress integration mode")
    macro = fetch_macro_regime()

    # FIX: Abort early on MASSACRE/PANIC
    if macro.get("macro_state") in ("MASSACRE", "PANIC"):
        log.warning(f"Macro={macro['macro_state']} — APEX universe scan aborted.")
        return []

    return _run_apex_on_universe(bhavcopy_df, macro, fii_data)


def _run_apex_on_universe(universe: pd.DataFrame, macro: dict, fii_data: dict) -> List[dict]:
    """Internal: score a pre-filtered universe DataFrame."""
    # FIX APEX-CRIT-04: Abort on MASSACRE/PANIC
    if macro.get("macro_state") in ("MASSACRE", "PANIC"):
        log.warning(f"Macro={macro['macro_state']} — APEX universe scan aborted.")
        return []

    for c in ["close", "turnover_lakhs"]:
        if c in universe.columns:
            universe[c] = pd.to_numeric(universe[c], errors="coerce")
    if "turnover_lakhs" not in universe.columns:
        universe["turnover_lakhs"] = 0.0
    universe["symbol"] = universe["symbol"].astype(str).str.strip().str.upper()

    candidates = universe[
        universe["close"].between(MIN_PRICE, MAX_PRICE) &
        (universe["turnover_lakhs"] >= MIN_TURNOVER_LAKHS) &
        universe["symbol"].apply(is_halal)
    ].sort_values("turnover_lakhs", ascending=False).head(200)

    results = []
    for _, row in candidates.iterrows():
        sym   = row["symbol"]
        close = float(row.get("close", 0))
        tover = float(row.get("turnover_lakhs", 0))
        try:
            hist = fetch_history(sym, days=300)
            if len(hist) < 30:
                continue
            r = score_symbol(sym, hist, close, tover, macro, fii_data)
            if r:
                results.append(r)
            time.sleep(0.15)
        except Exception as e:
            log.debug(f"{sym}: {e}")

    results.sort(key=lambda x: x["composite"], reverse=True)
    return results[:APEX_TOP_N]


# ══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    picks = run_apex_sniper()

    print(f"\n{'═' * 70}")
    print(f"⚔️  APEX SNIPER v1.2 — RESULTS")
    print(f"{'═' * 70}")

    if not picks:
        print("No picks today. Either market is in MASSACRE/PANIC, or no setup passed all 7 layers.")
        print("This is the system working correctly — capital preservation is the first rule.")
    else:
        for i, r in enumerate(picks, 1):
            print(f"\n{'─' * 50}")
            print(f"#{i}  {r['symbol']}  {r['grade']}  |  Score {r['composite']}/100")
            print(f"    Sector  : {r['sector']}")
            print(f"    Price   : ₹{r['close']}")
            print(f"    BUY     : ₹{r['buy_lo']} – ₹{r['buy_hi']}")
            print(f"    Stop    : ₹{r['stop_loss']}  (Risk {r['risk_pct']}%)")
            print(f"    R1      : ₹{r['r1']}  (+{r['r1_pct']}%)  → sell {r['sell_r1']}%")
            print(f"    R2      : ₹{r['r2']}  (+{r['r2_pct']}%)  → sell {r['sell_r2']}%")
            print(f"    R3      : ₹{r['r3']}  (+{r['r3_pct']}%)  → sell {r['sell_r3']}%")
            print(f"    Trail   : arms at R2 → ₹{r['trail_stop']}")
            print(f"    Position: {r['pos_label']}")
            print(f"    R1 est  : ~{r['days_to_r1_est']} days  |  Hit prob {r['r1_hit_prob']:.0f}%  |  MC Survival {r['mc_survival']}%")
            print(f"")
            print(f"    Sub-scores:")
            print(f"      VPOC Sniper : {r['vpoc_score']:.0f}/100  [{', '.join([f'L{j}='+('✓' if r['vpoc_layers'].get(f'layer{j}') else '✗') for j in range(1,7)])}]")
            print(f"      Whale Radar : {r['whale_score']:.0f}/100  {r['whale_signal']}")
            print(f"      Divergence  : {r['div_score']:.0f}/100  {r['div_detail']['div_type'] if 'div_detail' in r else r['div_label']}")
            print(f"      Vol Profile : {r['vp_score']:.0f}/100")
            print(f"      Pattern     : {r['pat_score']:.0f}/100  {r['pat_label']}")
            print(f"      Bayes       : {r['bayes_pct']}%")
            print(f"      MC Survival : {r['mc_survival']}%")
            print(f"")
            print(f"    Why   : {r['story']}")
            print(f"    RSI {r['rsi']} | MFI {r['mfi']} | ADX {r['adx']} | ATR ₹{r['atr14']} | POC ₹{r['poc']}")

    print(f"\n{'═' * 70}")
    print("🤲 Bismillah — trade with discipline, tawakkul, and halal intention")
    print(f"{'═' * 70}")
