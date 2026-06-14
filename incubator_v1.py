#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   PROJECT FORTRESS — INCUBATOR v12.0 (THE INSIDER SYNDICATE)                ║
║   Bismillah — In the name of Allah, the Most Gracious, the Most Merciful   ║
║                                                                              ║
║   MISSION: Find stocks at ₹40 before they become ₹150 (3-6 month horizon) ║
║                                                                              ║
║   ARCHITECTURE: 3-Stage Funnel                                              ║
║   RUNS: Friday 16:00 IST (11:30 UTC) via GitHub Actions — zero VPS cost    ║
║                                                                              ║
║   STAGE 1 — MATH SWEEP (all 400 candidates)                                ║
║     GATE-1  RUBBLE CHECK: price ≥30% below 52W high (forgotten by public)  ║
║     GATE-2  EPS ACCELERATION: ≥+25% QoQ (CANSLIM 'E')                     ║
║     GATE-3  SPONGE VOLUME: dry red weeks + wet green weeks (whale buying)  ║
║     → Top 25 math survivors advance                                         ║
║                                                                              ║
║   STAGE 2 — SHARIA AUDIT (25 survivors)                                    ║
║     Layer 1: Ticker keyword veto (BANK/FINANCE/INSURE/etc.)                ║
║     Layer 2: OpenAI dynamic business model audit                           ║
║     → Confirmed halal names advance                                         ║
║                                                                              ║
║   STAGE 3 — INSIDER DATA HEIST + LLM AUDIT (halal survivors only)         ║
║     curl_cffi Chrome TLS impersonation defeats NSE 403 blocks              ║
║     Scrapes NSE Corporate Announcements + SAST Insider Trade filings       ║
║     OpenAI "Insider Friend" reads legal filings for stealth catalysts      ║
║     → Top 5 Pearls to Telegram + Google Sheets                             ║
║                                                                              ║
║   HALAL: Dynamic OpenAI audit — no manual list maintenance required        ║
║   BYPASS: pip install curl_cffi required on runner                         ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os, io, re, json, math, time, random, logging, hashlib
import threading, warnings, subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import requests
import numpy as np
import pandas as pd

try:
    import yfinance as yf
    _YFINANCE_OK = True
except ImportError:
    _YFINANCE_OK = False

# curl_cffi: Chrome TLS impersonation — defeats NSE Cloudflare 403 blocks
# pip install curl_cffi
try:
    from curl_cffi import requests as cffi_requests
    _CFFI_OK = True
except ImportError:
    _CFFI_OK = False
    log_tmp = logging.getLogger("incubator_v6")
    log_tmp.warning("curl_cffi not installed — NSE bypass disabled. Run: pip install curl_cffi")

warnings.filterwarnings("ignore", category=FutureWarning)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("incubator_v6")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — CONFIG
# ══════════════════════════════════════════════════════════════════════════════

VERSION = "INCUBATOR v13.0 INSIDER SYNDICATE + INDEX ALPHA (passive-etf-flow-engine)"

OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY", "")
OPENAI_MINI_MODEL  = os.getenv("OPENAI_MINI_MODEL", "gpt-4o-mini")
_OPENAI_OK         = bool(OPENAI_API_KEY)

TELEGRAM_TOKEN     = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

GOOGLE_SHEET_ID    = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_CREDS_JSON  = os.getenv("GOOGLE_CREDS_JSON", "")

SCRAPERAPI_KEY     = os.getenv("SCRAPERAPI_KEY", "")

# Stage 1 thresholds
STAGE1_MA200_FLAT_PCT   = float(os.getenv("STAGE1_MA200_FLAT_PCT",   "0.06"))   # ±6% — allows natural rounding bottoms
STAGE1_BOX_WIDTH_MAX    = float(os.getenv("STAGE1_BOX_WIDTH_MAX",    "0.35"))   # <35% box
STAGE1_BOX_WEEKS_MIN    = int(os.getenv("STAGE1_BOX_WEEKS_MIN",      "12"))     # ≥12 weeks
STAGE1_PRICE_FROM_MA200 = float(os.getenv("STAGE1_PRICE_FROM_MA200", "0.20"))   # within 20%

# EPS gate
EPS_ACCEL_PCT_MIN  = float(os.getenv("EPS_ACCEL_PCT_MIN", "0.25"))   # ≥25% QoQ EPS growth

# Sponge volume
SPONGE_DRY_VOL_PCT = float(os.getenv("SPONGE_DRY_VOL_PCT", "0.60"))  # red weeks < 60% avg
SPONGE_WET_VOL_PCT = float(os.getenv("SPONGE_WET_VOL_PCT", "1.50"))  # ≥1 green week >150% avg

# Screening
MIN_PRICE          = float(os.getenv("MIN_PRICE",          "15"))
MAX_PRICE          = float(os.getenv("MAX_PRICE",          "500"))    # Stones are cheap
MIN_TURNOVER_LAKHS = float(os.getenv("MIN_TURNOVER_LAKHS", "20"))     # lower than sniper
MAX_CANDIDATES     = int(os.getenv("MAX_CANDIDATES",       "500"))   # doc recommends 500 for mid/small cap coverage
STONE_SCORE_MIN    = int(os.getenv("STONE_SCORE_MIN",      "60"))     # /120 total
TOP_N_STONES       = int(os.getenv("TOP_N_STONES",         "5"))

OUTPUTS_DIR = Path(os.getenv("CACHE_PATH", "outputs/incubator_cache.db")).parent

# ── Index Alpha (Passive ETF Flow Engine) ────────────────────────────────────
# Runs compute_rolling_index_alpha() against the top 150 liquid NSE stocks.
# Stocks ranking ≤50 (near Nifty 50 / Next 50 inclusion boundary) get +25
# bonus points and are upgraded to DIAMOND grade — passive ETF inflow acts as
# a structural price catalyst independent of insider or fundamental signals.
INDEX_ALPHA_ENABLED     = os.getenv("INDEX_ALPHA_ENABLED", "1") != "0"
INDEX_ALPHA_UNIVERSE_N  = int(os.getenv("INDEX_ALPHA_UNIVERSE_N", "150"))  # top-N liquid symbols to scan
INDEX_ALPHA_RANK_CUTOFF = int(os.getenv("INDEX_ALPHA_RANK_CUTOFF", "50"))  # rank ≤ this → DIAMOND bonus
INDEX_ALPHA_BONUS_PTS   = int(os.getenv("INDEX_ALPHA_BONUS_PTS",  "25"))   # score bonus for qualifying rank
INDEX_ALPHA_LOOKBACK    = int(os.getenv("INDEX_ALPHA_LOOKBACK",   "180"))  # days of history for rolling calc

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — NSE SESSION (curl_cffi Chrome TLS impersonation)
# ══════════════════════════════════════════════════════════════════════════════
# curl_cffi mimics the exact TLS fingerprint of Chrome — NSE Cloudflare
# cannot distinguish it from a human browser. Defeats 403 blocks entirely.
# Falls back to standard requests if curl_cffi not installed.

_NSE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/",
    "Connection": "keep-alive",
}
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

_NSE_SESSION_CACHE  = None
_NSE_SESSION_TS     = 0.0
_NSE_SESSION_LOCK   = threading.Lock()

def _get_nse_session():
    """
    Returns a curl_cffi session with Chrome TLS impersonation (preferred)
    or a standard requests session as fallback.
    Session is cached for 5 minutes to avoid repeated handshakes.
    """
    global _NSE_SESSION_CACHE, _NSE_SESSION_TS
    with _NSE_SESSION_LOCK:
        now = time.time()
        if _NSE_SESSION_CACHE and (now - _NSE_SESSION_TS) < 300:
            return _NSE_SESSION_CACHE

        if _CFFI_OK:
            log.info("Booting curl_cffi Chrome TLS impersonation for NSE bypass...")
            sess = cffi_requests.Session(impersonate="chrome110")
            sess.headers.update(_NSE_HEADERS)
        else:
            log.warning("curl_cffi unavailable — using standard requests (may hit 403)")
            sess = requests.Session()
            sess.headers.update({**_NSE_HEADERS,
                                  "User-Agent": random.choice(_UA_POOL)})

        try:
            r1 = sess.get("https://www.nseindia.com", timeout=15)
            log.info(f"NSE handshake: HTTP {r1.status_code}")
            time.sleep(1.2)
            r2 = sess.get("https://www.nseindia.com/api/allIndices", timeout=15)
            log.info(f"NSE API unlock: HTTP {r2.status_code}")
            time.sleep(0.8)
        except Exception as e:
            log.warning(f"NSE session handshake: {e}")

        _NSE_SESSION_CACHE = sess
        _NSE_SESSION_TS    = now
        return sess

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — GOOGLE SHEETS
# ══════════════════════════════════════════════════════════════════════════════

_GS_WB: Any = None
_GS_LOCK = threading.Lock()

def _gs_ok() -> bool:
    return bool(GOOGLE_SHEET_ID and GOOGLE_CREDS_JSON)

def _get_workbook():
    global _GS_WB
    if _GS_WB:
        return _GS_WB
    with _GS_LOCK:
        if _GS_WB:
            return _GS_WB
        if not _gs_ok():
            return None
        try:
            import gspread
            from google.oauth2.service_account import Credentials
            creds_dict = json.loads(GOOGLE_CREDS_JSON)
            scopes = ["https://www.googleapis.com/auth/spreadsheets",
                      "https://www.googleapis.com/auth/drive"]
            creds  = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            gc     = gspread.authorize(creds)
            _GS_WB = gc.open_by_key(GOOGLE_SHEET_ID)
            log.info("Google Sheets connected ✅")
        except Exception as e:
            log.warning(f"Sheets connect: {e}")
    return _GS_WB

def _get_ws(tab: str):
    wb = _get_workbook()
    if not wb:
        return None
    try:
        return wb.worksheet(tab)
    except Exception:
        try:
            return wb.add_worksheet(title=tab, rows=500, cols=30)
        except Exception as e:
            log.warning(f"_get_ws {tab}: {e}")
            return None

def _push_sheet(tab: str, rows: list):
    ws = _get_ws(tab)
    if not ws or not rows:
        return
    try:
        ws.clear()
        ws.update("A1", rows, value_input_option="USER_ENTERED")
        log.info(f"Sheets {tab}: {len(rows)-1} rows ✅")
    except Exception as e:
        log.warning(f"_push_sheet {tab}: {e}")

def _read_sheet(tab: str) -> list:
    ws = _get_ws(tab)
    if not ws:
        return []
    try:
        return ws.get_all_values()
    except Exception:
        return []

def _append_row(tab: str, row: list):
    ws = _get_ws(tab)
    if not ws:
        return
    try:
        ws.append_row(row, value_input_option="USER_ENTERED")
    except Exception as e:
        log.debug(f"_append_row {tab}: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — SENTINEL + OPENAI
# ══════════════════════════════════════════════════════════════════════════════

def _write_sentinel(stage: str, extra: dict = None):
    try:
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        lines = [f"VERSION : {VERSION}",
                 f"STAGE   : {stage}",
                 f"UTCTIME : {datetime.utcnow().isoformat()}"]
        if extra:
            for k, v in extra.items():
                lines.append(f"{k:8s}: {v}")
        (OUTPUTS_DIR / "last_incubator_run.txt").write_text("\n".join(lines) + "\n")
    except Exception:
        pass

def _call_openai(prompt: str, max_tokens: int = 400) -> Optional[str]:
    if not _OPENAI_OK:
        return None
    h = hashlib.md5(prompt.encode()).hexdigest()
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
                return resp.json()["choices"][0]["message"]["content"].strip()
            elif resp.status_code == 429:
                time.sleep(2 ** attempt)
        except Exception as e:
            log.debug(f"_call_openai attempt {attempt}: {e}")
    return None

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — HALAL SCREEN (L1 keyword only — L2-L4 from sector map)
# ══════════════════════════════════════════════════════════════════════════════

# PATCH 1: Strict halal check — live Google Sheets HALAL_LIST + ticker keyword guard
# Replaces the hardcoded 40-stock sector map that let IIFL/GICRE/EDELWEISS through.

_HARAM_TICKER_KW = {"BANK", "FINANCE", "INSURE", "CAPITAL", "CREDIT",
                    "NBFC", "ALCOHOL", "BREWERY", "TOBACCO", "CASINO", "GAMBLING"}

_HARAM_TERMS = ["BANK", "FINANC", "INSURANCE", "ALCOHOL", "BREWERY",
                "DEFENCE", "GAMBLING", "PORK", "CIGARETTE", "TOBACCO"]

# Cache HALAL_LIST per run to avoid a Sheets call per stock
_HALAL_LIST_CACHE: Optional[list] = None
_HALAL_CACHE_TS: float = 0.0

def _get_halal_list() -> list:
    """Return HALAL_LIST rows, cached for the run (refreshes every 30 min)."""
    global _HALAL_LIST_CACHE, _HALAL_CACHE_TS
    now = time.time()
    if _HALAL_LIST_CACHE is not None and (now - _HALAL_CACHE_TS) < 1800:
        return _HALAL_LIST_CACHE
    rows = _read_sheet("HALAL_LIST")
    _HALAL_LIST_CACHE = rows or []
    _HALAL_CACHE_TS   = now
    log.info(f"HALAL_LIST loaded: {len(_HALAL_LIST_CACHE)} rows")
    return _HALAL_LIST_CACHE

def halal_ok(symbol: str) -> bool:
    """
    Strict Sharia screen inherited from sniper_v7 architecture.
    Layer 1: Reject if ticker itself contains haram keywords (BANK, FINANCE, etc.)
    Layer 2: Live check against HALAL_LIST Google Sheet.
             If sheet is down → fail-safe: reject everything (buy nothing).
    """
    sym = symbol.upper()

    # Layer 1: Ticker keyword hard-fail
    for kw in _HARAM_TICKER_KW:
        if kw in sym:
            log.debug(f"Halal FAIL (ticker kw '{kw}'): {sym}")
            return False

    # Layer 2: Live Google Sheets check
    raw_halal = _get_halal_list()
    if not raw_halal or len(raw_halal) < 2:
        log.warning(f"HALAL_LIST unavailable — fail-safe reject: {sym}")
        return False   # DB down → buy nothing

    for row in raw_halal[1:]:
        if not row:
            continue
        if str(row[0]).strip().upper() == sym:
            sector   = str(row[2]).strip().upper() if len(row) > 2 else ""
            industry = str(row[3]).strip().upper() if len(row) > 3 else ""
            if any(h in sector for h in _HARAM_TERMS) or any(h in industry for h in _HARAM_TERMS):
                log.debug(f"Halal FAIL (sector/industry): {sym} | {sector} | {industry}")
                return False
            return True   # Found in sheet, sector clean

    log.debug(f"Halal FAIL (not in HALAL_LIST): {sym}")
    return False   # Not in approved list → reject

def dynamic_shariah_audit(symbol: str) -> Tuple[bool, str, dict]:
    """
    Late-stage Sharia audit — runs only on top 25 math survivors.
    Returns (compliant, reason, log_data) — log_data written to SHARIA_LOG tab.
    Layer 1: Hard ticker keyword veto (instant, free).
    Layer 2: yfinance company profile injected into prompt (prevents LLM hallucination).
    Layer 3: OpenAI audits GROUNDED business description — not a blind ticker guess.
    """
    sym = symbol.upper().strip()
    _ld = {"symbol": sym, "company_name": sym, "industry": "Unknown",
           "biz_profile": "", "reason": "", "layer": "L1", "compliant": False}

    # Layer 1: Ticker keyword hard veto
    for kw in ["BANK", "FINANCE", "INSURE", "CAPITAL", "CREDIT",
               "INVEST", "MUTUAL", "HOLDING", "NBFC", "LEASING"]:
        if kw in sym:
            _ld["reason"] = f"Haram ticker keyword '{kw}'"
            return False, f"L1: Haram ticker keyword '{kw}'", _ld

    if not _OPENAI_OK:
        _ld.update({"compliant": True, "layer": "L0", "reason": "AI disabled"})
        return True, "Passed local gates (AI disabled)", _ld

    # Layer 2: Fetch real company profile from yfinance to ground the LLM
    # Prevents gpt-4o-mini from hallucinating "INDOTHAI = industrial" when it's a brokerage
    biz_profile  = "Not available"
    industry     = "Unknown"
    company_name = sym
    try:
        import yfinance as yf
        info         = yf.Ticker(f"{sym}.NS").info
        biz_profile  = (info.get("longBusinessSummary", "") or "")[:600]
        industry     = info.get("industry", "Unknown") or "Unknown"
        company_name = info.get("longName", sym)      or sym
        if not biz_profile:
            biz_profile = f"{company_name} — industry: {industry}"
    except Exception as e:
        log.debug(f"yfinance profile {sym}: {e}")

    _ld.update({"company_name": company_name, "industry": industry,
                "biz_profile": biz_profile[:200], "layer": "L2"})

    # Layer 3: LLM audits grounded profile, not a blind ticker guess
    prompt = f"""You are an Islamic finance compliance auditor verifying a stock for an investment fund.
Company: {company_name} (Ticker: {sym}, NSE India)
Industry: {industry}
Business Profile: {biz_profile}

Task: Determine if this company's PRIMARY business model is itself haram.

Prohibited: Conventional Banking, Insurance, NBFCs, Financial Lending, Brokerage/Securities,
Alcohol production/distribution, Tobacco, Gambling, Pork, Adult entertainment, Defense/Weapons.

STRICT RULES:
1. Judge ONLY the company's own primary business — not their customers.
2. Do NOT speculate. Only reject for EXPLICITLY prohibited activity.
3. Manufacturing, IT, pharma, FMCG, solar, construction materials, logistics, transport,
   textiles, pipes, footwear, chemicals = HALAL unless they make prohibited goods.
4. Hotels: only reject if explicitly operating bars/casinos as core revenue.
5. BPO/services: reject ONLY if the company itself provides financial lending/banking services,
   not merely IT services TO banks.

Respond ONLY in this JSON format (no markdown):
{{
  "is_compliant": true,
  "primary_business": "one sentence: what they make or sell",
  "reason": "if non-compliant, cite the EXPLICIT haram activity. If compliant write NONE"
}}"""

    raw = _call_openai(prompt, max_tokens=180)
    if raw:
        try:
            parsed    = json.loads(re.sub(r"```json|```", "", raw).strip())
            compliant = bool(parsed.get("is_compliant", False))
            reason    = str(parsed.get("reason", "NONE"))
            biz       = str(parsed.get("primary_business", "unknown"))
            _ld.update({"compliant": compliant, "reason": reason if not compliant else "NONE"})
            if not compliant:
                return False, f"L2 AI Audit: {reason} ({biz})", _ld
            return True, f"Passed AI audit: {biz}", _ld
        except Exception as e:
            log.debug(f"Shariah audit parse {sym}: {e}")

    _ld.update({"compliant": True, "reason": "parse error fallback"})
    return True, "Passed fallback (AI parse error)", _ld

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — BHAVCOPY (weekly — reads from Sheets BHAVCOPY tab first)
# ══════════════════════════════════════════════════════════════════════════════

def load_universe() -> pd.DataFrame:
    """
    Load full NSE EQ universe for Stone screening.
    Priority: Sheets BHAVCOPY tab → NSE bhavcopy → fallback symbol list.
    For weekly incubator, Sheets tab is always most reliable.
    """
    # Try Sheets BHAVCOPY first (populated by sniper_v7 runs)
    if _gs_ok():
        raw = _read_sheet("BHAVCOPY")
        if raw and len(raw) > 100:
            df = pd.DataFrame(raw[1:], columns=[str(h).strip().upper() for h in raw[0]])
            col_map = {}
            for internal, cands in {
                "symbol": ["SYMBOL"], "close": ["CLOSE","LTP","LAST"],
                "volume": ["VOLUME","TOTTRDQTY"], "high": ["HIGH"], "low": ["LOW"],
                "turnover_lakhs": ["TURNOVER_LAKHS","TOTTRDVAL"],
            }.items():
                for c in cands:
                    if c in df.columns:
                        col_map[c] = internal; break
            df = df.rename(columns=col_map)
            for col in ["close","volume","high","low","turnover_lakhs"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
            if "turnover_lakhs" not in df.columns:
                df["turnover_lakhs"] = df.get("volume", 0) * df.get("close", 0) / 100_000
            df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
            df = df.dropna(subset=["close"]).query("close > 0").reset_index(drop=True)

            # PATCH 1a: BAN ETFs, INDEX FUNDS, BONDS
            etf_keywords = ['ETF', 'BEES', 'QLITY', 'NIFTY', 'GSEC', 'BOND', 'LIQUIDCASE',
                            'LIQUID', 'GILT', 'CPSE', 'BHARAT', 'MAFSETF', 'JUNIORBEES']
            etf_pattern = '|'.join(etf_keywords)
            before = len(df)
            df = df[~df['symbol'].str.contains(etf_pattern, na=False)]
            log.info(f"ETF/Index filter removed {before - len(df)} symbols, {len(df)} remain")

            # PATCH 1b: PRICE FILTER BEFORE head(MAX_CANDIDATES) — ensures affordable stocks, not large-caps
            df = df[(df["close"] >= MIN_PRICE) & (df["close"] <= MAX_PRICE)]
            log.info(f"Price filter ₹{MIN_PRICE:.0f}-{MAX_PRICE:.0f}: {len(df)} remain")

            # PATCH 1c: SORT BY LIQUIDITY (turnover), NOT ALPHABET
            if "turnover_lakhs" in df.columns:
                df = df.sort_values("turnover_lakhs", ascending=False)
                log.info("Universe sorted by turnover_lakhs (liquidity) ✅")

            df = df.head(MAX_CANDIDATES).reset_index(drop=True)
            log.info(f"Universe: {len(df)} rows from Sheets BHAVCOPY ✅")
            return df

    # NSE bhavcopy fallback
    try:
        today = datetime.today()
        d = today - timedelta(days=1)
        for _ in range(5):
            if d.weekday() < 5: break
            d -= timedelta(days=1)
        dd = d.strftime("%d"); mm = d.strftime("%m"); yyyy = d.strftime("%Y")
        mmm = d.strftime("%b").upper()
        url = (f"https://archives.nseindia.com/content/historical/EQUITIES/"
               f"{yyyy}/{mmm}/cm{dd}{mmm}{yyyy}bhav.csv.zip")
        sess = _get_nse_session()
        resp = sess.get(url, headers=_NSE_HEADERS, timeout=25)
        if resp.status_code == 200 and len(resp.content) > 5000:
            from zipfile import ZipFile
            zf   = ZipFile(io.BytesIO(resp.content))
            name = [n for n in zf.namelist() if n.endswith(".csv")][0]
            df   = pd.read_csv(io.BytesIO(zf.read(name)))
            df.columns = [c.strip().upper() for c in df.columns]
            if "SERIES" in df.columns:
                df = df[df["SERIES"] == "EQ"]
            df = df.rename(columns={"SYMBOL":"symbol","CLOSE":"close",
                                    "HIGH":"high","LOW":"low",
                                    "TOTTRDQTY":"volume","TOTTRDVAL":"turnover_lakhs"})
            for col in ["close","high","low","volume","turnover_lakhs"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
            df["turnover_lakhs"] = df.get("turnover_lakhs", 0) / 100_000
            df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
            df = df.dropna(subset=["close"]).query("close > 0").reset_index(drop=True)

            # PATCH 1: BAN ETFs, INDEX FUNDS, BONDS
            etf_keywords = ['ETF', 'BEES', 'QLITY', 'NIFTY', 'GSEC', 'BOND', 'LIQUIDCASE',
                            'LIQUID', 'GILT', 'CPSE', 'BHARAT', 'MAFSETF', 'JUNIORBEES']
            etf_pattern = '|'.join(etf_keywords)
            before = len(df)
            df = df[~df['symbol'].str.contains(etf_pattern, na=False)]
            log.info(f"ETF/Index filter removed {before - len(df)} symbols, {len(df)} remain")

            # PATCH 1b: PRICE FILTER BEFORE head(MAX_CANDIDATES) — guarantees affordable candidates
            df = df[(df["close"] >= MIN_PRICE) & (df["close"] <= MAX_PRICE)]
            log.info(f"Price filter ₹{MIN_PRICE:.0f}-{MAX_PRICE:.0f}: {len(df)} remain")

            # PATCH 1: SORT BY LIQUIDITY, NOT ALPHABET
            if "turnover_lakhs" in df.columns:
                df = df.sort_values("turnover_lakhs", ascending=False)
                log.info("Universe sorted by turnover_lakhs (liquidity) ✅")

            log.info(f"Universe: {len(df)} rows from NSE bhavcopy ✅")
            return df.head(MAX_CANDIDATES).reset_index(drop=True)
    except Exception as e:
        log.warning(f"NSE bhavcopy: {e}")

    # Hardcoded fallback
    log.warning("Universe: using hardcoded symbol list")
    syms = [
        "RELIANCE","TCS","INFY","WIPRO","HCLTECH","TECHM","SUNPHARMA","DRREDDY",
        "CIPLA","DIVISLAB","HINDUNILVR","ITC","NESTLEIND","BRITANNIA","MARICO",
        "JSWSTEEL","TATASTEEL","HINDZINC","VEDL","MARUTI","TATAMOTORS","M&M",
        "LT","NCC","NBCC","CONCOR","DEEPAKNTR","PIIND","CHAMBLFERT","COROMANDEL",
        "GNFC","TATACHEM","NAVINFLUOR","FINEORG","ATUL","PIDILITIND","BERGEPAINT",
        "PAGEIND","RELAXO","TITAN","APOLLOHOSP","DMART","IRCTC","ADANIPORTS",
        "POLYCAB","DIXON","KAYNES","ABB","SIEMENS","CUMMINSIND","THERMAX",
        "SYNGENE","KALYANKJIL","MANINFRA","PRICOLLTD","APLLTD","SPARC","JAINREC",
        "PACEDIGITK","PINELABS","ZEEL","MOTHERSON","TMCV","WIPRO","CONCOR",
    ]
    return pd.DataFrame({"symbol": syms, "close": [100.0]*len(syms),
                         "volume": [100000]*len(syms), "high": [105.0]*len(syms),
                         "low": [95.0]*len(syms), "turnover_lakhs": [100.0]*len(syms)})

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — WEEKLY HISTORY (52 weeks)
# ══════════════════════════════════════════════════════════════════════════════

def fetch_weekly_history(symbol: str, weeks: int = 52) -> pd.DataFrame:
    """
    Fetch weekly OHLCV from NSE historical API.
    Falls back to yfinance weekly resampling.
    Returns DataFrame with columns: date, open, high, low, close, volume
    Indexed as weekly bars.
    """
    end_dt   = datetime.today()
    start_dt = end_dt - timedelta(days=(weeks + 8) * 7)
    end_str   = end_dt.strftime("%d-%m-%Y")
    start_str = start_dt.strftime("%d-%m-%Y")

    # NSE historical API (daily) → resample to weekly
    try:
        sess = _get_nse_session()
        url  = (f"https://www.nseindia.com/api/historical/cm/equity"
                f"?symbol={symbol}&series=[%22EQ%22]"
                f"&from={start_str}&to={end_str}&csv=true")
        resp = sess.get(url, headers={**_NSE_HEADERS,
                                      "Accept": "application/json",
                                      "X-Requested-With": "XMLHttpRequest",
                                      "Referer": f"https://www.nseindia.com/get-quotes/equity?symbol={symbol}"},
                        timeout=20)
        if resp.status_code == 200 and len(resp.content) > 200:
            data = resp.json()
            rows = data.get("data", data) if isinstance(data, dict) else data
            if rows and isinstance(rows, list):
                df = pd.DataFrame(rows)
                col_map = {}
                for c in df.columns:
                    cu = c.upper()
                    if "TIMESTAMP" in cu or "DATE" in cu: col_map[c] = "date"
                    elif "OPENING" in cu: col_map[c] = "open"
                    elif "HIGH"    in cu: col_map[c] = "high"
                    elif "LOW"     in cu: col_map[c] = "low"
                    elif "CLOSING" in cu or "CLOSE" in cu: col_map[c] = "close"
                    elif "QTY"     in cu or "VOLUME" in cu: col_map[c] = "volume"
                df = df.rename(columns=col_map)
                if all(c in df.columns for c in ["date","open","high","low","close","volume"]):
                    df["date"] = pd.to_datetime(df["date"], errors="coerce")
                    for col in ["open","high","low","close","volume"]:
                        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
                    df = df.dropna(subset=["date","close"]).sort_values("date")
                    df = df.set_index("date")
                    weekly = df[["open","high","low","close","volume"]].resample("W").agg({
                        "open":   "first",
                        "high":   "max",
                        "low":    "min",
                        "close":  "last",
                        "volume": "sum",
                    }).dropna().tail(weeks)
                    weekly = weekly.reset_index()
                    if len(weekly) >= 13:
                        log.debug(f"Weekly {symbol}: NSE_API {len(weekly)} bars")
                        return weekly
    except Exception as e:
        log.debug(f"fetch_weekly_history NSE {symbol}: {e}")

    # yfinance fallback
    try:
        import yfinance as yf
        raw = yf.download(f"{symbol}.NS", start=start_dt, end=end_dt,
                          interval="1wk", progress=False, auto_adjust=True, timeout=20)
        if not raw.empty:
            df = raw.reset_index()
            df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                          for c in df.columns]
            df["date"] = pd.to_datetime(df.get("date", df.get("datetime")))
            df = df[["date","open","high","low","close","volume"]].dropna()
            result = df.tail(weeks).reset_index(drop=True)
            log.debug(f"Weekly {symbol}: YFINANCE {len(result)} bars")
            return result
    except Exception as e:
        log.debug(f"fetch_weekly_history yfinance {symbol}: {e}")

    return pd.DataFrame()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — GATE 1: RUBBLE CHECK (inverted math — forgotten stocks near lows)
# ══════════════════════════════════════════════════════════════════════════════
# Philosophy pivot: instead of waiting for the lagging 200MA to flatten,
# we look for stocks that retail has completely forgotten (≥30% off 52W high)
# but that institutional flow shows is being quietly accumulated (Sponge).
# The 200MA is a LAGGING indicator. The 52W low discount is a CURRENT reality.

RUBBLE_DISCOUNT_MIN = float(os.getenv("RUBBLE_DISCOUNT_MIN", "0.30"))  # ≥30% below 52W high

def check_rubble_gate(symbol: str, weekly: pd.DataFrame,
                      close: float) -> Tuple[bool, dict]:
    """
    Rubble Gate: stock is deeply discounted (ignored by public) and below 52W high by ≥30%.
    This is the raw material before the Insider catalyst ignites it.
    Returns (passed: bool, details: dict)
    """
    details = {"high_52w": 0.0, "low_52w": 0.0, "discount_pct": 0.0,
               "box_weeks": 0, "box_width_pct": 0.0, "ma200": 0.0,
               "ma200_slope_pct": 0.0, "price_from_ma200": 0.0,
               "stage": "RUBBLE", "score": 0, "reason": ""}

    if weekly.empty or len(weekly) < 20:
        details["reason"] = f"insufficient data: {len(weekly)} weeks"
        return False, details

    high_w  = weekly["high"].values.astype(float)
    low_w   = weekly["low"].values.astype(float)
    close_w = weekly["close"].values.astype(float)

    high_52w = float(high_w.max())
    low_52w  = float(low_w.min())
    if high_52w <= 0:
        details["reason"] = "52W high = 0"
        return False, details

    discount_pct = (high_52w - close) / high_52w
    details["high_52w"]      = round(high_52w, 2)
    details["low_52w"]       = round(low_52w, 2)
    details["discount_pct"]  = round(discount_pct * 100, 1)

    # Gate: must be ≥30% below 52W high (true Rubble — forgotten by public)
    if discount_pct < RUBBLE_DISCOUNT_MIN:
        details["reason"] = (f"price only {discount_pct*100:.1f}% below 52W high "
                             f"(need ≥{RUBBLE_DISCOUNT_MIN*100:.0f}%)")
        return False, details

    # Guard: not a falling knife — must not be making new all-time lows this week
    # Price must be above the 52W low by at least 5% (some floor)
    if low_52w > 0 and close < low_52w * 1.05:
        details["reason"] = f"price too close to 52W low (falling knife risk)"
        return False, details

    # Still compute MA200 for output / scoring (no longer a hard gate)
    ma_period = min(40, len(close_w))
    ma200 = float(pd.Series(close_w).rolling(ma_period).mean().iloc[-1])
    details["ma200"] = round(ma200, 2) if ma200 > 0 else 0.0
    if ma200 > 0:
        slope_13w = 0.0
        if len(close_w) >= 13:
            ma_ago = float(pd.Series(close_w[:-13]).rolling(
                min(ma_period, len(close_w)-13)).mean().iloc[-1])
            slope_13w = (ma200 - ma_ago) / ma_ago if ma_ago > 0 else 0.0
        details["ma200_slope_pct"]   = round(slope_13w * 100, 2)
        details["price_from_ma200"]  = round((close - ma200) / ma200 * 100, 1)

    # Measure box width for output (not a hard gate in Rubble mode)
    box_weeks = 0
    for lb in range(min(40, len(close_w)), 0, -1):
        bh = float(high_w[-lb:].max())
        bl = float(low_w[-lb:].min())
        if bl > 0 and (bh / bl - 1) <= STAGE1_BOX_WIDTH_MAX:
            box_weeks = lb
            break
    details["box_weeks"]     = box_weeks
    details["box_width_pct"] = round(
        (high_w[-box_weeks:].max() / low_w[-box_weeks:].min() - 1) * 100
        if box_weeks > 0 else 99, 1
    )

    # Score (max 50): deeper discount + some consolidation = better rubble
    score = 0
    score += min(30, int(discount_pct * 100))   # 30% off → 30 pts, 50% off → 50 pts (capped)
    if box_weeks >= 8:   score += 10
    elif box_weeks >= 4: score += 5
    if details["box_width_pct"] < 25: score += 10
    score = min(50, score)

    details["score"]  = score
    details["reason"] = (f"Rubble ✅ {discount_pct*100:.1f}% below 52W high "
                         f"box={box_weeks}w ma200_slope={details['ma200_slope_pct']:+.1f}%")
    return True, details

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8b — UPGRADE 2.2: SECTOR ROTATION ALPHA
# ══════════════════════════════════════════════════════════════════════════════
# Indian market moves in 6-month sector cycles. A Stone in an accelerating
# sector breaks out faster. A Stone in a dying sector stays a stone forever.
# Checks NIFTY sector index 13-week momentum — adds up to +20 score bonus.

# Map NSE industry keywords → NIFTY sector index Yahoo Finance tickers
_SECTOR_INDEX_MAP = {
    "Cement":         "^CNXMETAL",   # proxy — no direct NIFTY Cement index on YF
    "Metals":         "^CNXMETAL",
    "Metal":          "^CNXMETAL",
    "Realty":         "^CNXREALTY",
    "Real Estate":    "^CNXREALTY",
    "Pharma":         "^CNXPHARMA",
    "Pharmaceuticals": "^CNXPHARMA",
    "IT":             "^CNXIT",
    "Software":       "^CNXIT",
    "Technology":     "^CNXIT",
    "Auto":           "^CNXAUTO",
    "Automobile":     "^CNXAUTO",
    "FMCG":           "^CNXFMCG",
    "Consumer":       "^CNXFMCG",
    "Energy":         "^CNXENERGY",
    "Power":          "^CNXENERGY",
    "Finance":        "^CNXFIN",
    "Banks":          "^NSEBANK",
    "Infra":          "^CNXINFRA",
    "Infrastructure": "^CNXINFRA",
    "Media":          "^CNXMEDIA",
}

_SECTOR_ALPHA_CACHE: Dict[str, Tuple[float, float]] = {}   # ticker → (momentum_pct, ts)

def get_sector_alpha(industry: str) -> Tuple[int, str]:
    """
    Returns (sector_alpha_score 0-20, description).
    Checks if the stock's NIFTY sector index is in a 13-week Stage 2 uptrend.
    Stocks in accelerating sectors score higher — they break out faster.
    score 20 = sector strongly accelerating
    score 10 = sector mildly positive
    score  0 = sector flat or declining
    score -10 = sector in strong downtrend (headwind)
    """
    if not industry or industry == "Unknown":
        return 0, "Sector unknown"

    # Find matching sector index
    sector_ticker = None
    for kw, idx_ticker in _SECTOR_INDEX_MAP.items():
        if kw.lower() in industry.lower():
            sector_ticker = idx_ticker
            break

    if not sector_ticker:
        return 0, f"No sector index mapped for: {industry}"

    # Cache for 1 hour — same index used for multiple stocks in same run
    now = time.time()
    cached = _SECTOR_ALPHA_CACHE.get(sector_ticker)
    if cached and (now - cached[1]) < 3600:
        momentum = cached[0]
    else:
        try:
            import yfinance as yf
            idx = yf.download(sector_ticker, period="4mo", interval="1wk",
                              progress=False, auto_adjust=True)
            if idx.empty or len(idx) < 13:
                return 0, f"Insufficient sector data: {sector_ticker}"
            closes = idx["Close"].values.astype(float)
            momentum = (closes[-1] - closes[-13]) / closes[-13]   # 13-week return
            _SECTOR_ALPHA_CACHE[sector_ticker] = (momentum, now)
            log.debug(f"SectorAlpha {sector_ticker}: 13w momentum={momentum*100:+.1f}%")
        except Exception as e:
            log.debug(f"SectorAlpha fetch {sector_ticker}: {e}")
            return 0, f"Sector fetch error: {e}"

    # Score based on momentum
    if momentum > 0.15:    return  20, f"Sector strongly accelerating ({momentum*100:+.0f}% 13w)"
    elif momentum > 0.05:  return  10, f"Sector mildly positive ({momentum*100:+.0f}% 13w)"
    elif momentum > -0.05: return   0, f"Sector flat ({momentum*100:+.0f}% 13w)"
    elif momentum > -0.15: return  -5, f"Sector declining ({momentum*100:+.0f}% 13w)"
    else:                  return -10, f"Sector in downtrend ({momentum*100:+.0f}% 13w)"

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — GATE 2: EPS ACCELERATION
# ══════════════════════════════════════════════════════════════════════════════

def fetch_quarterly_results(symbol: str) -> List[dict]:
    """
    Fetch last 4 quarters of NSE financial results.
    Returns list of dicts: [{period, eps, revenue, net_profit}]
    """
    results = []
    try:
        sess = _get_nse_session()
        # NSE corporate results API
        resp = sess.get(
            f"https://www.nseindia.com/api/quote-equity?symbol={symbol}&section=financials",
            headers={**_NSE_HEADERS, "Accept": "application/json",
                     "X-Requested-With": "XMLHttpRequest",
                     "Referer": f"https://www.nseindia.com/get-quotes/equity?symbol={symbol}"},
            timeout=15
        )
        if resp.status_code == 200:
            data = resp.json()
            # NSE returns financials under different keys depending on company type
            fin_data = (data.get("financials", {}) or
                        data.get("data", {}).get("financials", {}))
            quarterly = (fin_data.get("quarterly", []) or
                         fin_data.get("quarterlyResults", []))
            for q in quarterly[:4]:
                eps  = float(q.get("eps", q.get("basicEps", 0)) or 0)
                rev  = float(q.get("revenue", q.get("totalIncome", 0)) or 0)
                np_  = float(q.get("netProfit", q.get("pat", 0)) or 0)
                per  = str(q.get("period", q.get("quarter","")) or "")
                results.append({"period": per, "eps": eps,
                                 "revenue": rev, "net_profit": np_})
    except Exception as e:
        log.debug(f"fetch_quarterly_results {symbol}: {e}")

    # Screener.in fallback (public JSON endpoint, no auth needed)
    if not results:
        try:
            resp = requests.get(
                f"https://www.screener.in/api/company/{symbol}/",
                headers={"User-Agent": random.choice(_UA_POOL),
                         "Accept": "application/json"},
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                for q in (data.get("quarterly_results", []) or [])[:4]:
                    results.append({
                        "period":     str(q.get("period","")),
                        "eps":        float(q.get("eps", 0) or 0),
                        "revenue":    float(q.get("revenue", q.get("sales",0)) or 0),
                        "net_profit": float(q.get("net_profit", q.get("pat",0)) or 0),
                    })
        except Exception as e:
            log.debug(f"screener.in fallback {symbol}: {e}")

    # PATCH 2: yfinance fallback — free, unblocked, works for NSE stocks
    if not results:
        try:
            import yfinance as yf
            ticker = yf.Ticker(f"{symbol}.NS")
            q_fin = ticker.quarterly_income_stmt
            if q_fin is not None and not q_fin.empty:
                for dt in q_fin.columns[:4]:
                    net_inc = float(q_fin.loc["Net Income", dt]) if "Net Income" in q_fin.index else 0.0
                    rev     = float(q_fin.loc["Total Revenue", dt]) if "Total Revenue" in q_fin.index else 0.0
                    eps     = float(q_fin.loc["Basic EPS", dt]) if "Basic EPS" in q_fin.index else 0.0
                    results.append({
                        "period":     dt.strftime("%Y-%m-%d"),
                        "eps":        eps,
                        "revenue":    rev,
                        "net_profit": net_inc,
                    })
                log.debug(f"yfinance quarterly fallback {symbol}: {len(results)} quarters ✅")
        except Exception as e:
            log.debug(f"yfinance quarterly fallback {symbol}: {e}")

    return results

def check_eps_acceleration(symbol: str) -> Tuple[bool, dict]:
    """
    EPS acceleration gate: latest QTR EPS must be ≥ +25% above prior QTR.
    Falls back to net_profit growth if EPS unavailable.
    Returns (passed: bool, details: dict)
    """
    details = {"eps_latest": 0, "eps_prior": 0, "eps_growth_pct": 0,
               "reason": "", "score": 0}

    qtrs = fetch_quarterly_results(symbol)
    if len(qtrs) < 2:
        details["reason"] = f"insufficient quarterly data: {len(qtrs)} quarters — REJECTED"
        # PATCH 2: Hard reject — blind gamble without EPS data
        details["score"] = 0
        return False, details

    latest = qtrs[0]
    prior  = qtrs[1]

    # Use EPS if available; fall back to net_profit
    if latest["eps"] != 0 and prior["eps"] != 0:
        metric     = "EPS"
        val_latest = latest["eps"]
        val_prior  = prior["eps"]
    elif latest["net_profit"] != 0 and prior["net_profit"] != 0:
        metric     = "NET_PROFIT"
        val_latest = latest["net_profit"]
        val_prior  = prior["net_profit"]
    elif latest["revenue"] != 0 and prior["revenue"] != 0:
        metric     = "REVENUE"
        val_latest = latest["revenue"]
        val_prior  = prior["revenue"]
    else:
        details["reason"] = "no financial data available — REJECTED"
        details["score"]  = 0
        return False, details   # PATCH 2: Hard reject — no data = no trade

    # Both must be positive (no loss-making turnarounds — separate strategy)
    if val_prior <= 0:
        details["reason"] = f"{metric} prior={val_prior:.2f} ≤ 0 (loss-making)"
        return False, details

    # PATCH 2: Base-effect floor — prevents penny-stock 1000%+ hallucinations
    # e.g. ₹0.02 → ₹0.23 = +1050% but company is making pennies
    if val_prior < 1.0:
        details["reason"] = f"{metric} prior={val_prior:.2f} too close to zero (Base Effect Flaw)"
        return False, details

    growth_pct = (val_latest - val_prior) / abs(val_prior)
    details["eps_latest"]    = round(val_latest, 2)
    details["eps_prior"]     = round(val_prior,  2)
    details["eps_growth_pct"] = round(growth_pct * 100, 1)
    details["metric"]        = metric

    if growth_pct < EPS_ACCEL_PCT_MIN:
        details["reason"] = (f"{metric} growth {growth_pct*100:+.1f}% "
                             f"< min +{EPS_ACCEL_PCT_MIN*100:.0f}%")
        return False, details

    # Score: higher growth = more points (max 30)
    score = min(30, int(growth_pct * 100))
    details["score"]  = score
    details["reason"] = (f"EPS ✅ {metric} {growth_pct*100:+.1f}% "
                         f"latest={val_latest:.2f} prior={val_prior:.2f}")
    return True, details

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 10 — GATE 3: SPONGE VOLUME PROFILE
# ══════════════════════════════════════════════════════════════════════════════

def check_sponge_volume(weekly: pd.DataFrame) -> Tuple[bool, dict]:
    """
    Sponge volume = institutional quiet accumulation.
    Pattern: red weeks have dry volume (< 60% avg) = nobody selling.
             green weeks have sponge volume (≥1 week > 150% avg) = someone buying.
    Proves institutions absorbing supply without moving price (Stage 1 characteristic).
    """
    details = {"dry_up_weeks": 0, "sponge_weeks": 0,
               "dry_vol_avg_ratio": 0.0, "sponge_vol_max_ratio": 0.0,
               "reason": "", "score": 0}

    if weekly.empty or len(weekly) < 10:
        details["reason"] = f"insufficient weekly data: {len(weekly)} bars"
        details["score"]  = 5
        return True, details   # soft pass

    close_w = weekly["close"].values.astype(float)
    vol_w   = weekly["volume"].values.astype(float)
    lookback = min(20, len(weekly))

    close_r = close_w[-lookback:]
    vol_r   = vol_w[-lookback:]
    avg_vol = float(vol_r.mean())
    if avg_vol <= 0:
        details["reason"] = "avg volume = 0"
        details["score"]  = 5
        return True, details

    # Red weeks = close < prior close
    red_mask   = close_r[1:] < close_r[:-1]
    green_mask = close_r[1:] >= close_r[:-1]
    red_vols   = vol_r[1:][red_mask]
    green_vols = vol_r[1:][green_mask]

    dry_vol_ratio   = float(red_vols.mean()   / avg_vol) if len(red_vols)   > 0 else 1.0
    sponge_vol_max  = float(green_vols.max()  / avg_vol) if len(green_vols) > 0 else 0.0
    dry_up_weeks    = int((vol_r[1:][red_mask] < avg_vol * SPONGE_DRY_VOL_PCT).sum())
    sponge_weeks    = int((vol_r[1:][green_mask] > avg_vol * SPONGE_WET_VOL_PCT).sum())

    details["dry_up_weeks"]      = dry_up_weeks
    details["sponge_weeks"]      = sponge_weeks
    details["dry_vol_avg_ratio"] = round(dry_vol_ratio, 3)
    details["sponge_vol_max_ratio"] = round(sponge_vol_max, 3)

    # Gate: must have meaningful dry-up AND at least one sponge week
    if dry_vol_ratio > SPONGE_DRY_VOL_PCT and sponge_weeks == 0:
        details["reason"] = (f"no sponge pattern: dry={dry_vol_ratio:.2f} "
                             f"sponge_weeks={sponge_weeks}")
        return False, details

    score = 0
    if dry_up_weeks >= 3:   score += 10
    elif dry_up_weeks >= 1: score += 5
    if sponge_weeks >= 2:   score += 20
    elif sponge_weeks >= 1: score += 12
    if dry_vol_ratio < 0.50: score += 5    # extra quiet on red days

    details["score"]  = score
    details["reason"] = (f"Sponge ✅ dry={dry_up_weeks}w({dry_vol_ratio:.2f}x) "
                         f"sponge={sponge_weeks}w(max {sponge_vol_max:.2f}x)")
    return True, details

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 11 — CONCALL ANALYSIS (LLM bonus gate)
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_concall_text(symbol: str) -> str:
    """
    Fetch latest earnings call transcript text.
    Sources: NSE/BSE filing search → PDF text extraction.
    Returns raw text string (truncated to 8000 chars for LLM).
    """
    text = ""
    # Source 1: NSE investor presentations / concall filings
    try:
        sess = _get_nse_session()
        resp = sess.get(
            f"https://www.nseindia.com/api/annual-reports?index=equities&symbol={symbol}",
            headers={**_NSE_HEADERS, "Accept": "application/json",
                     "X-Requested-With": "XMLHttpRequest"},
            timeout=12
        )
        if resp.status_code == 200:
            filings = resp.json() if isinstance(resp.json(), list) else resp.json().get("data",[])
            for f in (filings or [])[:5]:
                subject = str(f.get("subject","") or f.get("desc","")).lower()
                if any(kw in subject for kw in ["concall","earnings call","investor call",
                                                 "con call","q1","q2","q3","q4","results"]):
                    pdf_url = f.get("fileName","") or f.get("fileLink","")
                    if pdf_url and pdf_url.endswith(".pdf"):
                        text = _extract_pdf_text(pdf_url)
                        if len(text) > 500:
                            break
    except Exception as e:
        log.debug(f"concall NSE {symbol}: {e}")

    # Source 2: BSE filings search
    if not text and SCRAPERAPI_KEY:
        try:
            target = f"https://www.bseindia.com/corporates/ann.html#{symbol}"
            resp = requests.get(
                "https://api.scraperapi.com/",
                params={"api_key": SCRAPERAPI_KEY, "url": target, "render": "false"},
                timeout=25,
            )
            if resp.status_code == 200:
                raw = resp.text[:3000]
                # Extract first PDF link containing concall keywords
                pdf_matches = re.findall(r'https?://[^\s"\']+\.pdf', raw, re.IGNORECASE)
                for url in pdf_matches[:3]:
                    t = _extract_pdf_text(url)
                    if len(t) > 500:
                        text = t
                        break
        except Exception as e:
            log.debug(f"concall BSE {symbol}: {e}")

    # PATCH 3: Source 3 — Screener.in concall page (most reliable for Indian mid-caps)
    if not text and SCRAPERAPI_KEY:
        try:
            # Screener.in concall page for this symbol
            screener_url = f"https://www.screener.in/company/{symbol}/concalls/"
            resp = requests.get(
                "https://api.scraperapi.com/",
                params={"api_key": SCRAPERAPI_KEY, "url": screener_url, "render": "false"},
                timeout=30,
            )
            if resp.status_code == 200 and len(resp.text) > 500:
                raw_html = resp.text
                # Extract transcript text — Screener wraps it in <div class="con-call">
                # or just grab all visible text between script/style tags
                clean = re.sub(r'<script[^>]*>.*?</script>', '', raw_html, flags=re.DOTALL)
                clean = re.sub(r'<style[^>]*>.*?</style>',  '', clean, flags=re.DOTALL)
                clean = re.sub(r'<[^>]+>', ' ', clean)
                clean = re.sub(r'\s+', ' ', clean).strip()
                if len(clean) > 500:
                    text = clean
                    log.info(f"Concall {symbol}: scraped Screener.in ({len(text)} chars) ✅")
        except Exception as e:
            log.debug(f"concall Screener.in {symbol}: {e}")

    return text[:8000]

def _extract_pdf_text(url: str) -> str:
    """Download PDF and extract text via pdfminer or subprocess pdftotext."""
    try:
        r = requests.get(url, headers={"User-Agent": random.choice(_UA_POOL)},
                         timeout=20)
        if r.status_code != 200 or len(r.content) < 1000:
            return ""
        # Try pdfminer
        try:
            from pdfminer.high_level import extract_text as pdf_extract
            return pdf_extract(io.BytesIO(r.content))[:8000]
        except ImportError:
            pass
        # Fallback: write to tmp and pdftotext
        tmp = Path("/tmp/concall_tmp.pdf")
        tmp.write_bytes(r.content)
        result = subprocess.run(["pdftotext", str(tmp), "-"],
                                capture_output=True, timeout=15)
        if result.returncode == 0:
            return result.stdout.decode("utf-8", errors="ignore")[:8000]
    except Exception as e:
        log.debug(f"_extract_pdf_text: {e}")
    return ""

def analyze_concall(symbol: str) -> dict:
    """
    LLM analysis of earnings call transcript.
    Hunts for CAPEX expansion + margin expansion signals.
    Returns {capex_signal: bool, margin_signal: bool, summary: str, score: int}
    """
    result = {"capex_signal": False, "margin_signal": False,
              "summary": "", "score": 0}

    if not _OPENAI_OK:
        result["summary"] = "LLM disabled (no OPENAI_API_KEY)"
        return result

    text = _fetch_concall_text(symbol)
    if not text or len(text) < 300:
        # PATCH 3: Admit failure — don't silently output False and mislead the scorer
        result["summary"] = "DATA_MISSING: No concall transcript could be extracted."
        result["capex_signal"]  = False
        result["margin_signal"] = False
        log.info(f"Concall {symbol}: DATA_MISSING — no transcript extracted")
        return result

    prompt = f"""You are a quantitative analyst reading an Indian company earnings call transcript.
Company: {symbol}

Transcript (may be partial):
{text[:6000]}

Respond ONLY as JSON (no markdown):
{{
  "capex_expansion": true/false,
  "capex_detail": "one sentence or empty string",
  "margin_expansion": true/false,
  "margin_detail": "one sentence or empty string",
  "confidence": 0.0-1.0,
  "summary": "2-3 sentences max"
}}

Rules:
- capex_expansion: true ONLY if management explicitly mentions new factory, new plant, capacity expansion, greenfield, brownfield, or major capex plan with ₹ amount
- margin_expansion: true ONLY if management explicitly mentions raw material cost reduction, operating leverage improvement, or margin guidance upgrade
- Do NOT infer. Only mark true if explicitly stated."""

    raw = _call_openai(prompt, max_tokens=300)
    if raw:
        try:
            parsed = json.loads(re.sub(r"```json|```", "", raw).strip())
            result["capex_signal"]   = bool(parsed.get("capex_expansion", False))
            result["margin_signal"]  = bool(parsed.get("margin_expansion", False))
            result["summary"]        = str(parsed.get("summary",""))[:200]
            result["confidence"]     = float(parsed.get("confidence", 0.5))
            result["capex_detail"]   = str(parsed.get("capex_detail",""))[:100]
            result["margin_detail"]  = str(parsed.get("margin_detail",""))[:100]
            score = 0
            if result["capex_signal"]:  score += 20
            if result["margin_signal"]: score += 20
            result["score"] = score
            log.info(f"Concall {symbol}: capex={result['capex_signal']} "
                     f"margin={result['margin_signal']} score={score}")
        except Exception as e:
            log.debug(f"concall parse {symbol}: {e}")
    return result

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 11b — THE DATA HEIST: NSE Insider Trades + Corporate Filings
# ══════════════════════════════════════════════════════════════════════════════
# Uses the curl_cffi session (Chrome TLS) to scrape two NSE endpoints:
#   1. Corporate Announcements — order wins, expansions, acquisitions
#   2. SAST Insider Trades (PIT) — promoter/director open-market buying

def fetch_insider_and_filings(symbol: str) -> Tuple[str, str, float]:
    """
    Fetch NSE Corporate Announcements + SAST Insider Trades + Promoter Pledge % for symbol.
    Returns (filings_text, insider_text, pledge_pct)
    pledge_pct = % of promoter shares pledged (0.0 = clean, >50 = red flag)
    """
    sess = _get_nse_session()
    filings_text = "No recent corporate filings found."
    insider_text = "No recent insider trades found."
    pledge_pct   = -1.0   # -1 = unknown (API failed)

    if not sess:
        return filings_text, insider_text, pledge_pct

    # ── 1. Corporate Announcements ────────────────────────────────────────────
    try:
        url = (f"https://www.nseindia.com/api/corporate-announcements"
               f"?index=equities&symbol={symbol}")
        r = sess.get(url, timeout=12)
        if r.status_code == 200:
            data = r.json()
            items = data if isinstance(data, list) else data.get("data", [])
            lines = []
            for item in (items or [])[:8]:
                dt  = str(item.get("an_dt", item.get("date", "")))
                sub = str(item.get("subject", item.get("desc", "")))
                det = str(item.get("desc", ""))[:200]
                lines.append(f"[{dt}] {sub} | {det}")
            if lines:
                filings_text = "\n".join(lines)
                log.debug(f"Filings {symbol}: {len(lines)} announcements")
    except Exception as e:
        log.debug(f"Filings fetch {symbol}: {e}")

    # ── 2. SAST / PIT Insider Trades ─────────────────────────────────────────
    try:
        url = (f"https://www.nseindia.com/api/corporates-pit"
               f"?index=equities&symbol={symbol}")
        r = sess.get(url, timeout=12)
        if r.status_code == 200:
            data = r.json().get("data", [])
            lines = []
            for item in (data or [])[:8]:
                mode = str(item.get("acqMode", ""))
                if any(kw in mode for kw in ["Buy", "Market Purchase", "Market Buy",
                                              "Acquisition", "ESOP"]):
                    person = str(item.get("personName", item.get("name", "")))
                    qty    = str(item.get("secAcq", item.get("noSecAcq", "")))
                    val    = str(item.get("secVal", item.get("val", "")))
                    dt     = str(item.get("date", item.get("intimDt", "")))
                    lines.append(
                        f"[{dt}] {person} | Bought {qty} shares | "
                        f"Value ₹{val}L | Mode: {mode}"
                    )
            if lines:
                insider_text = "\n".join(lines)
                log.debug(f"Insider {symbol}: {len(lines)} buy events")
    except Exception as e:
        log.debug(f"Insider fetch {symbol}: {e}")

    # ── 3. Promoter Pledge % (UPGRADE 2.3 — Promoter Trust Score) ────────────
    # Diamond: buying + 0% pledge. Red flag: buying + >50% pledge = debt stress.
    try:
        url = (f"https://www.nseindia.com/api/corporate-shareholding-patterns"
               f"?index=equities&symbol={symbol}")
        r = sess.get(url, timeout=12)
        if r.status_code == 200:
            data = r.json()
            items = data if isinstance(data, list) else data.get("data", [])
            if items:
                latest = items[0]   # most recent quarter
                # NSE returns pledged shares as % of promoter holding
                pledged = float(latest.get("promoterPledgedShares",
                                latest.get("percPledgedSharesPromoter",
                                latest.get("pledgedPct", -1))) or -1)
                if pledged >= 0:
                    pledge_pct = pledged
                    log.debug(f"Pledge {symbol}: {pledge_pct:.1f}%")
    except Exception as e:
        log.debug(f"Pledge fetch {symbol}: {e}")

    return filings_text, insider_text, pledge_pct


def insider_friend_audit(symbol: str, filings: str, insiders: str,
                         pledge_pct: float = -1.0) -> dict:
    """
    The Insider Friend LLM Audit.
    Reads legally binding NSE filings + SAST trades.
    UPGRADE 2.1: Also extracts risk/exit signals — high risk lowers confidence_score.
    UPGRADE 2.3: Classifies DIAMOND (buying + 0% pledge) vs RED_FLAG (buying + >50% pledge).

    Returns dict with all signals + pearl_grade (DIAMOND / PEARL / SKIP)
    """
    result = {
        "stealth_catalyst_found": False,
        "insider_buying_found":   False,
        "insider_summary":        "DATA_MISSING: No filing data extracted.",
        "risk_flags":             "",
        "risk_penalty":           0,
        "capex_signal":           False,
        "margin_signal":          False,
        "confidence_score":       0,
        "pledge_pct":             pledge_pct,
        "pearl_grade":            "UNKNOWN",
        "score":                  0,
    }

    if not _OPENAI_OK:
        result["insider_summary"] = "LLM disabled (no OPENAI_API_KEY)"
        return result

    if filings == "No recent corporate filings found." and insiders == "No recent insider trades found.":
        result["insider_summary"] = "DATA_MISSING: NSE returned no filings or insider trades."
        return result

    prompt = f"""You are an insider friend at a top quantitative hedge fund in Mumbai.
I am looking at {symbol} (NSE India). It is trading near its 52-week low, ignored by retail,
but our volume models show institutional sponge buying is occurring.

Here is the raw legal data extracted directly from the National Stock Exchange:

RECENT CORPORATE ANNOUNCEMENTS (last 8):
{filings[:3000]}

RECENT PROMOTER/INSIDER BUYING (SAST/PIT filings):
{insiders[:2000]}

Task A — Find the ENTRY catalyst (3 months early):
Look ONLY for explicitly stated evidence of:
1. Promoters/directors/founders buying their own stock from open market.
2. New capacity expansion, factory, land acquisition, greenfield/brownfield capex.
3. Massive new order wins, long-term contracts, government tenders won.
4. Merger/acquisition or delisting announcement.

Task B — Find EXIT RISK signals (the reason NOT to hold):
Look for EXPLICIT management mentions of:
1. Increased competition or market share loss.
2. Raw material cost headwinds or margin compression.
3. Regulatory hurdles, license risks, or legal proceedings.
4. Debt stress, working capital issues, or dividend cuts.

Do NOT speculate. Only report what is EXPLICITLY stated in the documents.

Respond ONLY in this exact JSON format (no markdown):
{{
  "stealth_catalyst_found": true/false,
  "insider_buying_found": true/false,
  "capex_expansion": true/false,
  "insider_summary": "1-2 sentence summary of catalyst found, or NONE",
  "risk_flags": "1 sentence on risks found, or NONE if no risks mentioned",
  "risk_severity": 0-3,
  "confidence_score": 0-100
}}

risk_severity: 0=no risks, 1=minor mentions, 2=significant headwinds, 3=existential threat"""

    raw = _call_openai(prompt, max_tokens=300)
    if raw:
        try:
            parsed = json.loads(re.sub(r"```json|```", "", raw).strip())
            result["stealth_catalyst_found"] = bool(parsed.get("stealth_catalyst_found", False))
            result["insider_buying_found"]   = bool(parsed.get("insider_buying_found",   False))
            result["capex_signal"]           = bool(parsed.get("capex_expansion",        False))
            result["insider_summary"]        = str(parsed.get("insider_summary", "NONE"))[:200]
            result["risk_flags"]             = str(parsed.get("risk_flags", "NONE"))[:150]
            risk_severity                    = int(parsed.get("risk_severity", 0))
            base_conf                        = int(parsed.get("confidence_score", 0))

            # UPGRADE 2.1: Risk penalty on confidence_score
            # severity 1 = -5, severity 2 = -15, severity 3 = -30
            risk_penalty = {0: 0, 1: 5, 2: 15, 3: 30}.get(risk_severity, 0)
            result["risk_penalty"]    = risk_penalty
            result["confidence_score"] = max(0, base_conf - risk_penalty)
            if risk_penalty > 0:
                log.info(f"  ⚠️ Risk penalty {symbol}: severity={risk_severity} "
                         f"conf {base_conf}→{result['confidence_score']} | {result['risk_flags'][:60]}")

            # UPGRADE 2.3: Promoter Trust / Pledge classification
            buying = result["insider_buying_found"]
            if buying and pledge_pct == 0.0:
                result["pearl_grade"] = "DIAMOND"   # clean promoter buying — max conviction
                log.info(f"  💎 DIAMOND {symbol}: insider buying + 0% pledge")
            elif buying and pledge_pct > 50.0:
                result["pearl_grade"] = "RED_FLAG"  # debt-stressed promoter — veto
                log.info(f"  🚩 RED_FLAG {symbol}: buying but pledge={pledge_pct:.0f}% — debt stress")
            elif buying:
                result["pearl_grade"] = "PEARL"     # buying, pledge unknown or moderate
            else:
                result["pearl_grade"] = "WATCH"     # no buying signal

            # Score: diamond=60, pearl=50, catalyst=25, capex=10. Red flag = 0.
            score = 0
            if result["pearl_grade"] == "RED_FLAG":
                score = 0   # hard veto on pledge > 50%
            else:
                if result["pearl_grade"] == "DIAMOND":        score += 60
                elif result["insider_buying_found"]:           score += 50
                if result["stealth_catalyst_found"]:           score += 25
                if result["capex_signal"]:                     score += 10
                score = max(0, score - risk_penalty)   # risk penalty applies to score too

            result["score"] = score
            log.info(f"InsiderAudit {symbol}: grade={result['pearl_grade']} "
                     f"catalyst={result['stealth_catalyst_found']} "
                     f"insider={result['insider_buying_found']} pledge={pledge_pct:.0f}% "
                     f"conf={result['confidence_score']} score={score}")
        except Exception as e:
            log.debug(f"InsiderAudit parse {symbol}: {e}")
    return result

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 12 — MATH SCORER (pure quant — no Sharia, no LLM)
# ══════════════════════════════════════════════════════════════════════════════
# Sharia audit and insider heist are late-stage operations in run() Stage 2/3.
# This function only runs the three quantitative gates and returns a score.

def score_stone_math(symbol: str, bhav_row: dict) -> Optional[dict]:
    """
    Pure mathematical Stone scorer — Rubble + EPS + Sponge only.
    Returns result dict or None if fails any hard gate.
    Halal check and LLM insider audit are intentionally excluded (handled in Stage 2/3).
    """
    sym   = symbol.upper()
    close = float(bhav_row.get("close", 0))

    if close <= 0 or close < MIN_PRICE or close > MAX_PRICE:
        return {"symbol": sym, "close": close, "reject_gate": "PRICE_FILTER",
                "reject_reason": f"close={close} outside ₹{MIN_PRICE}-{MAX_PRICE}", "math_score": 0}

    # Weekly history
    weekly = fetch_weekly_history(sym, weeks=52)
    if weekly.empty or len(weekly) < 13:
        log.info(f"  MATH_REJECT {sym:14s} | NO_WEEKLY_DATA bars={len(weekly)}")
        return {"symbol": sym, "close": close, "reject_gate": "NO_WEEKLY_DATA",
                "reject_reason": f"bars={len(weekly)}", "math_score": 0}

    # GATE 1: Rubble (price ≥30% below 52W high — forgotten by public)
    g1_ok, g1 = check_rubble_gate(sym, weekly, close)
    if not g1_ok:
        log.info(f"  MATH_REJECT {sym:14s} | RUBBLE_FAIL | {g1['reason']}")
        return {"symbol": sym, "close": close, "reject_gate": "RUBBLE_FAIL",
                "reject_reason": g1["reason"], "math_score": 0,
                "g1": g1, "g2": {}, "g3": {}}

    # GATE 2: EPS acceleration
    g2_ok, g2 = check_eps_acceleration(sym)
    if not g2_ok:
        log.info(f"  MATH_REJECT {sym:14s} | EPS_FAIL | {g2['reason']}")
        return {"symbol": sym, "close": close, "reject_gate": "EPS_FAIL",
                "reject_reason": g2["reason"], "math_score": 0,
                "g1": g1, "g2": g2, "g3": {}}

    # GATE 3: Sponge volume
    g3_ok, g3 = check_sponge_volume(weekly)
    if not g3_ok:
        log.info(f"  MATH_REJECT {sym:14s} | SPONGE_FAIL | {g3['reason']}")
        return {"symbol": sym, "close": close, "reject_gate": "SPONGE_FAIL",
                "reject_reason": g3["reason"], "math_score": 0,
                "g1": g1, "g2": g2, "g3": g3}

    math_score = g1.get("score", 0) + g2.get("score", 0) + g3.get("score", 0)

    # UPGRADE 2.2: Sector Rotation Alpha — bonus/penalty based on sector momentum
    industry = "Unknown"
    try:
        import yfinance as yf
        info = yf.Ticker(f"{sym}.NS").info
        industry = info.get("industry", "Unknown") or "Unknown"
    except Exception:
        pass
    sector_alpha, sector_desc = get_sector_alpha(industry)
    math_score = max(0, math_score + sector_alpha)
    log.debug(f"  SectorAlpha {sym}: {sector_desc} → score adj {sector_alpha:+d}")

    return {
        "symbol":       sym,
        "close":        close,
        "math_score":   math_score,
        "sector_alpha": sector_alpha,
        "sector_desc":  sector_desc,
        "industry":     industry,
        "weekly_df":    weekly,
        "g1": g1, "g2": g2, "g3": g3,
    }

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 13 — TELEGRAM
# ══════════════════════════════════════════════════════════════════════════════

def _send_tg(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    for attempt in range(3):
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
                timeout=15,
            )
            if resp.status_code == 200:
                return
            elif resp.status_code == 429:
                time.sleep(2 ** attempt)
        except Exception as e:
            log.debug(f"Telegram attempt {attempt}: {e}")

def send_telegram_stones(stones: List[dict], date_label: str, total_scanned: int):
    lines = [
        f"🕴️ <b>INSIDER SYNDICATE v12.0 — {date_label}</b>",
        f"Scanned: {total_scanned} | Pearls found: {len(stones)}",
        "",
    ]
    for s in stones[:TOP_N_STONES]:
        grade      = s.get("pearl_grade", "WATCH")
        grade_icon = {"DIAMOND": "💎", "PEARL": "🪨", "WATCH": "👁", "UNKNOWN": "❓"}.get(grade, "🪨")
        catalyst_tag = "🔥 CATALYST"    if s.get("stealth_catalyst") else ""
        insider_tag  = "👤 INSIDER BUY" if s.get("insider_buying")   else ""
        capex_tag    = "🏗 CAPEX"       if s.get("capex_signal")     else ""
        tags = " | ".join(t for t in [catalyst_tag, insider_tag, capex_tag] if t)
        pledge_str = f" | Pledge {s['pledge_pct']:.0f}%" if s.get("pledge_pct", -1) >= 0 else ""
        sector_str = f"\n   📊 {s['sector_desc']}" if s.get("sector_alpha", 0) != 0 and s.get("sector_desc") else ""
        lines += [
            f"{grade_icon} <b>{s['symbol']}</b> [{grade}] — Score {s['total_score']} | Conf {s.get('insider_confidence',0)}%{pledge_str}",
            f"   Close ₹{s['close']:.0f} | {s.get('discount_pct',0):.0f}% below 52W High",
            f"   EPS {s.get('eps_growth_pct',0):+.0f}% QoQ | Sponge {s.get('sponge_weeks',0)}w{sector_str}",
            f"   Target ₹{s['target_25pct']:.0f} (+{s['upside_6m_pct']:.0f}% in 6m) | Stop ₹{s['stop_loss']:.0f}",
            f"   {tags}",
        ]
        if s.get("insider_summary") and "DATA_MISSING" not in s.get("insider_summary", ""):
            lines.append(f"   🤫 <i>{s['insider_summary'][:120]}</i>")
        if s.get("risk_flags") and s.get("risk_flags") not in ("NONE", ""):
            lines.append(f"   ⚠️ <i>Risk: {s['risk_flags'][:100]}</i>")
        lines.append("")
    if not stones:
        lines.append("No stealth insider action detected this week.")
        lines.append("We wait in the shadows. 🕐")
    _send_tg("\n".join(lines))

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 14 — GOOGLE SHEETS OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

_INCUBATOR_HEADER = [
    # Identity
    "Date", "Symbol", "PearlGrade",
    # Scores
    "TotalScore", "RubbleScore", "EPSScore", "SpongeScore", "SectorAlpha", "InsiderScore",
    # Price & technicals
    "Close", "MA200", "Discount%", "High52W", "Low52W",
    "BoxWeeks", "BoxWidth%", "MA200Slope%",
    # EPS
    "EPS_Growth%", "EPS_Latest", "EPS_Prior", "EPS_Metric",
    # Volume
    "DryUpWeeks", "SpongeWeeks",
    # Sector
    "Industry", "SectorDesc",
    # Insider audit
    "StealthCatalyst", "InsiderBuying", "CapexSignal",
    "Pledge%", "InsiderConfidence", "RiskPenalty", "InsiderSummary", "RiskFlags",
    # Targets
    "StopLoss", "Target30%", "Target80%", "Upside6m%", "Upside12m%",
]

def _stone_to_row(s: dict) -> list:
    return [
        # Identity
        s.get("run_date", ""),
        s.get("symbol", ""),
        s.get("pearl_grade", "WATCH"),
        # Scores
        s.get("total_score", 0),
        s.get("rubble_score", 0),
        s.get("eps_score", 0),
        s.get("sponge_score", 0),
        s.get("sector_alpha", 0),
        s.get("insider_score", 0),
        # Price & technicals
        s.get("close", 0),
        s.get("ma200", 0),
        s.get("discount_pct", 0),
        s.get("high_52w", 0),
        s.get("low_52w", 0),
        s.get("box_weeks", 0),
        s.get("box_width_pct", 0),
        s.get("ma200_slope_pct", 0),
        # EPS
        s.get("eps_growth_pct", 0),
        s.get("eps_latest", 0),
        s.get("eps_prior", 0),
        s.get("eps_metric", "EPS"),
        # Volume
        s.get("dry_up_weeks", 0),
        s.get("sponge_weeks", 0),
        # Sector
        s.get("industry", ""),
        s.get("sector_desc", ""),
        # Insider audit
        "✅" if s.get("stealth_catalyst") else "",
        "✅" if s.get("insider_buying")   else "",
        "✅" if s.get("capex_signal")     else "",
        s.get("pledge_pct", -1),
        s.get("insider_confidence", 0),
        s.get("risk_penalty", 0),
        s.get("insider_summary", "")[:120],
        s.get("risk_flags", "")[:100],
        # Targets
        s.get("stop_loss", 0),
        s.get("target_25pct", 0),
        s.get("target_60pct", 0),
        s.get("upside_6m_pct", 0),
        s.get("upside_12m_pct", 0),
    ]

def push_stones_to_sheets(stones: List[dict], date_label: str):
    existing = _read_sheet("INCUBATOR")
    # Strip header row(s) and today's data rows, always re-write fresh header
    data_rows = [r for r in existing
                 if r and str(r[0]) not in (date_label, "Date", _INCUBATOR_HEADER[0])]
    rows = [_INCUBATOR_HEADER] + data_rows
    for s in stones:
        rows.append(_stone_to_row(s))
    _push_sheet("INCUBATOR", rows)
    log.info(f"INCUBATOR: {len(stones)} pearls written, {len(rows)-1} total rows ✅")

# ── Sandbox Training Logs ─────────────────────────────────────────────────────

_RUN_LOG_HEADER = [
    "Date","Version","Scanned","S1_Survivors","Halal","Pearls","Top5Symbols",
    "RunDurationSec","Notes",
]

_REJECTS_LOG_HEADER = [
    "Date","Symbol","Close","Gate","Reason","EPS_Growth%","Discount%","MathScore",
]

_SHARIA_LOG_HEADER = [
    "Date","Symbol","Compliant","CompanyName","Industry","BusinessProfile",
    "ShariaReason","Layer",
]

def push_run_log(date_label: str, scanned: int, s1: int, halal: int,
                 pearls: int, top5: List[str], duration_sec: float):
    """Append one summary row per run to RUN_LOG tab."""
    existing = _read_sheet("RUN_LOG")
    data_rows = [r for r in existing if r and str(r[0]) not in ("Date", _RUN_LOG_HEADER[0])]
    rows = [_RUN_LOG_HEADER] + data_rows
    rows.append([
        date_label, VERSION, scanned, s1, halal, pearls,
        " | ".join(top5), round(duration_sec, 1), "",
    ])
    _push_sheet("RUN_LOG", rows)
    log.info(f"RUN_LOG: appended run summary ✅")

def push_rejects_log(rejects: List[dict], date_label: str):
    """
    Append all Stage 1 rejections to REJECTS_LOG tab.
    Each reject dict: {symbol, close, gate, reason, eps_growth_pct, discount_pct, math_score}
    This is the primary training corpus — every stock the system ever saw and why it was rejected.
    """
    if not rejects:
        return
    existing = _read_sheet("REJECTS_LOG")
    data_rows = [r for r in existing if r and str(r[0]) not in ("Date", _REJECTS_LOG_HEADER[0])]
    rows = [_REJECTS_LOG_HEADER] + data_rows
    for r in rejects:
        rows.append([
            date_label,
            r.get("symbol", ""),
            r.get("close", 0),
            r.get("gate", ""),
            r.get("reason", "")[:120],
            r.get("eps_growth_pct", ""),
            r.get("discount_pct", ""),
            r.get("math_score", ""),
        ])
    _push_sheet("REJECTS_LOG", rows)
    log.info(f"REJECTS_LOG: {len(rejects)} rejects logged ✅")

def push_sharia_log(sharia_decisions: List[dict], date_label: str):
    """
    Append all Stage 2 Sharia audit decisions to SHARIA_LOG tab.
    Training corpus for fine-tuning or rule-extraction on halal/haram classifications.
    """
    if not sharia_decisions:
        return
    existing = _read_sheet("SHARIA_LOG")
    data_rows = [r for r in existing if r and str(r[0]) not in ("Date", _SHARIA_LOG_HEADER[0])]
    rows = [_SHARIA_LOG_HEADER] + data_rows
    for d in sharia_decisions:
        rows.append([
            date_label,
            d.get("symbol", ""),
            "✅" if d.get("compliant") else "❌",
            d.get("company_name", "")[:60],
            d.get("industry", "")[:40],
            d.get("biz_profile", "")[:200],
            d.get("reason", "")[:120],
            d.get("layer", ""),
        ])
    _push_sheet("SHARIA_LOG", rows)
    log.info(f"SHARIA_LOG: {len(sharia_decisions)} decisions logged ✅")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 15 — INDEX ALPHA ENGINE (Passive ETF Flow Target Detection)
# ══════════════════════════════════════════════════════════════════════════════
#
# Nifty 50 and Nifty Next 50 rebalancing creates predictable structural demand:
# passive ETFs tracking these indices MUST buy newly-included stocks regardless
# of price. A stock on the cusp of index inclusion (ranked just outside top 50
# by free-float market cap) becomes a high-conviction "structural multi-bagger"
# because ETF inflow provides a price floor independent of any single catalyst.
#
# This module calculates 6-month rolling free-float market cap for the top-N
# liquid NSE stocks and surfaces those nearest the Nifty 50 / Next 50 boundary.
# Qualifying stocks that also pass CANSLIM compression scoring are upgraded to
# DIAMOND grade with +25 bonus points in the main scoring loop.

_INDEX_ALPHA_CACHE: Optional[pd.DataFrame] = None
_INDEX_ALPHA_TS: float = 0.0
_INDEX_ALPHA_LOCK = threading.Lock()


def compute_rolling_index_alpha(universe_symbols: List[str]) -> pd.DataFrame:
    """
    Calculates 6-month rolling free-float market cap for every symbol in the
    provided universe and ranks them by descending free-float capitalisation.

    Used to detect stocks near the Nifty 50 / Next 50 index inclusion boundary
    — passive ETF rebalancing creates forced structural buying at those cutoffs.

    Args:
        universe_symbols: List of NSE ticker symbols (without .NS suffix).

    Returns:
        DataFrame with columns:
            symbol, free_float_mcap_cr, avg_turnover_cr, current_price, index_rank
        Sorted descending by free_float_mcap_cr.
        Empty DataFrame if yfinance is unavailable or no data fetched.
    """
    if not _YFINANCE_OK:
        log.warning("Index Alpha: yfinance not installed — skipping (pip install yfinance)")
        return pd.DataFrame()

    end_date   = datetime.today()
    start_date = end_date - timedelta(days=INDEX_ALPHA_LOOKBACK)

    rebalance_metrics: List[dict] = []
    total = len(universe_symbols)
    log.info(f"Index Alpha: computing free-float mcap for {total} symbols over "
             f"{INDEX_ALPHA_LOOKBACK}d window...")

    for idx, symbol in enumerate(universe_symbols):
        if (idx + 1) % 25 == 0:
            log.info(f"  Index Alpha progress: {idx+1}/{total}")
        try:
            ticker = yf.Ticker(f"{symbol}.NS")
            hist   = ticker.history(start=start_date, end=end_date, interval="1d")

            # Need ≥100 trading days for a meaningful rolling average
            if hist.empty or len(hist) < 100:
                continue

            info         = ticker.info
            total_shares = info.get("sharesOutstanding", 0)
            if not total_shares or total_shares <= 0:
                continue

            # Float factor: ratio of freely-tradeable shares to total issued shares.
            # Promoter/govt locked-in shares are excluded from index weight.
            # Default 0.45 (45%) is a conservative mid-cap estimate per NSE methodology.
            float_shares = info.get("floatShares", 0)
            if float_shares and float_shares > 0:
                float_factor = min(float_shares / total_shares, 1.0)
            else:
                float_factor = 0.45   # NSE default for unknown float

            # Typical price = (H+L+C)/3 — removes single-tick close bias
            hist["typical_price"] = (hist["High"] + hist["Low"] + hist["Close"]) / 3.0
            hist["daily_turnover"] = hist["Close"] * hist["Volume"]

            avg_close        = float(hist["Close"].mean())
            avg_turnover_cr  = float(hist["daily_turnover"].mean() / 1e7)   # ₹ crore

            # Free Float Market Cap = Total Shares × Avg Price × Float Factor
            raw_mcap         = total_shares * avg_close
            free_float_mcap_cr = (raw_mcap * float_factor) / 1e7   # ₹ crore

            rebalance_metrics.append({
                "symbol":            symbol,
                "free_float_mcap_cr": round(free_float_mcap_cr, 2),
                "avg_turnover_cr":    round(avg_turnover_cr, 2),
                "current_price":      round(float(hist["Close"].iloc[-1]), 2),
                "float_factor":       round(float_factor, 3),
            })

        except Exception as e:
            log.debug(f"Index Alpha {symbol}: {e}")
            continue

    if not rebalance_metrics:
        log.warning("Index Alpha: no metrics computed — returning empty frame")
        return pd.DataFrame()

    df = pd.DataFrame(rebalance_metrics)
    df["index_rank"] = df["free_float_mcap_cr"].rank(ascending=False, method="min").astype(int)
    df = df.sort_values("free_float_mcap_cr", ascending=False).reset_index(drop=True)

    log.info(f"Index Alpha: ranked {len(df)} symbols. "
             f"Top-3 by FF-Mcap: {list(df['symbol'].head(3))}")
    return df


def get_index_alpha(universe_symbols: List[str]) -> pd.DataFrame:
    """
    Thread-safe cached wrapper around compute_rolling_index_alpha().
    Re-computes at most once per run (cached for 6 hours).

    Returns the ranked DataFrame, or empty DataFrame on failure.
    """
    global _INDEX_ALPHA_CACHE, _INDEX_ALPHA_TS
    with _INDEX_ALPHA_LOCK:
        now = time.time()
        if _INDEX_ALPHA_CACHE is not None and (now - _INDEX_ALPHA_TS) < 21600:
            log.info("Index Alpha: returning cached result")
            return _INDEX_ALPHA_CACHE

        result = compute_rolling_index_alpha(universe_symbols)
        _INDEX_ALPHA_CACHE = result
        _INDEX_ALPHA_TS    = now
        return result


def apply_index_alpha_bonus(asset: dict, index_df: pd.DataFrame) -> dict:
    """
    Cross-references a scored asset against the index alpha rankings.
    If the asset ranks within INDEX_ALPHA_RANK_CUTOFF (default ≤50), it
    receives INDEX_ALPHA_BONUS_PTS bonus score points and is upgraded to
    DIAMOND grade — passive ETF rebalancing acts as a structural price floor.

    Args:
        asset:    Stone dict as produced by Stage 3 scoring loop.
        index_df: DataFrame from compute_rolling_index_alpha().

    Returns:
        Modified asset dict (mutated in-place and returned).
    """
    if index_df.empty:
        return asset

    sym   = asset.get("symbol", "")
    match = index_df[index_df["symbol"] == sym]

    if match.empty:
        return asset

    row  = match.iloc[0]
    rank = int(row["index_rank"])
    ff_mcap = round(float(row["free_float_mcap_cr"]), 0)

    asset["index_rank"]    = rank
    asset["ff_mcap_cr"]    = ff_mcap
    asset["float_factor"]  = float(row.get("float_factor", 0))

    if rank <= INDEX_ALPHA_RANK_CUTOFF:
        asset["total_score"] += INDEX_ALPHA_BONUS_PTS
        asset["pearl_grade"]  = "DIAMOND"
        tag = (f" | 📊 Passive ETF Flow Target — FF-MCap ₹{ff_mcap:,.0f}Cr"
               f" (Index Rank #{rank} — near Nifty inclusion boundary)")
        asset["story"] = asset.get("story", "") + tag
        log.info(f"  📊 INDEX ALPHA BONUS {sym} | rank=#{rank} | "
                 f"ff_mcap=₹{ff_mcap:,.0f}Cr | +{INDEX_ALPHA_BONUS_PTS}pts → DIAMOND")

    return asset


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 16 — MAIN RUN
# ══════════════════════════════════════════════════════════════════════════════

def run():
    log.info("=" * 70)
    log.info(f"  {VERSION}")
    log.info(f"  Stage1: Rubble+EPS+Sponge → Stage2: Sharia → Stage3: cffi-Heist+InsiderLLM+IndexAlpha")
    log.info(f"  Score gate: {STONE_SCORE_MIN} | Top N: {TOP_N_STONES} | IndexAlpha: {'ON' if INDEX_ALPHA_ENABLED else 'OFF'}")
    log.info("=" * 70)

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    _write_sentinel("STARTED")

    date_label = datetime.today().strftime("%Y-%m-%d")
    log.info(f"Date: {date_label}")
    run_start = time.time()

    # Load universe
    bhav = load_universe()
    if bhav.empty:
        log.error("Universe empty — abort")
        _send_tg(f"❌ <b>INSIDER SYNDICATE v13.0 — {date_label}</b>\nUniverse unavailable.")
        return []
    _write_sentinel("UNIVERSE_LOADED", {"ROWS": len(bhav)})

    # Turnover gate (liquidity floor only — price already filtered in load_universe)
    cands = bhav[bhav["turnover_lakhs"] >= MIN_TURNOVER_LAKHS].copy()
    log.info(f"Candidates after turnover gate: {len(cands)}")

    if cands.empty:
        _send_tg(f"📋 <b>INSIDER SYNDICATE v13.0 — {date_label}</b>\nNo candidates after turnover filter.")
        return []

    # ── STAGE 1: Pure Quantitative & Fundamental Sweep ───────────────────────
    preliminary_stones: List[dict] = []
    rejects_log:        List[dict] = []   # every reject → REJECTS_LOG tab
    total = len(cands)
    log.info(f"Stage 1: Running math filters on {total} candidates...")

    for i, (_, row) in enumerate(cands.iterrows()):
        sym = str(row.get("symbol", "")).upper()
        if not sym:
            continue
        if (i + 1) % 100 == 0:
            log.info(f"  Stage1 progress: {i+1}/{total} | survivors: {len(preliminary_stones)}")
        try:
            result = score_stone_math(sym, row.to_dict())
            if result and "reject_gate" not in result and result.get("math_score", 0) >= 45:
                preliminary_stones.append(result)
            else:
                # Collect reject for sandbox logging
                rejects_log.append({
                    "symbol":        sym,
                    "close":         float(row.get("close", 0)),
                    "gate":          result.get("reject_gate", "SCORE_LOW") if result else "NO_DATA",
                    "reason":        result.get("reject_reason", "") if result else "score_stone_math returned None",
                    "eps_growth_pct": result.get("g2", {}).get("eps_growth_pct", "") if result else "",
                    "discount_pct":   result.get("g1", {}).get("discount_pct", "") if result else "",
                    "math_score":     result.get("math_score", 0) if result else 0,
                })
        except Exception as e:
            log.debug(f"Stage1 {sym}: {e}")
            rejects_log.append({"symbol": sym, "close": float(row.get("close", 0)),
                                 "gate": "EXCEPTION", "reason": str(e)[:100],
                                 "eps_growth_pct": "", "discount_pct": "", "math_score": 0})

    # Sort by math score, keep top 25 for deep auditing
    preliminary_stones.sort(key=lambda x: x["math_score"], reverse=True)
    surv_candidates = preliminary_stones[:25]
    log.info(f"Stage 1 complete. {len(surv_candidates)} survivors → entering Sharia audit.")
    _write_sentinel("STAGE1_DONE", {"SCANNED": total, "SURVIVORS": len(surv_candidates)})

    # ── STAGE 2: Sharia Audit ─────────────────────────────────────────────────
    halal_survivors:   List[dict] = []
    sharia_decisions:  List[dict] = []   # every decision → SHARIA_LOG tab
    log.info(f"Stage 2: Sharia audit on {len(surv_candidates)} survivors...")

    for item in surv_candidates:
        sym = item["symbol"]
        is_compliant, sharia_reason, sharia_log_data = dynamic_shariah_audit(sym)
        sharia_decisions.append(sharia_log_data)   # log every decision, pass or fail
        if not is_compliant:
            log.info(f"  ❌ SHARIAH VETO | {sym} | {sharia_reason}")
            continue
        log.info(f"  ✅ Sharia OK | {sym} | {sharia_reason}")
        item["sharia_reason"] = sharia_reason
        halal_survivors.append(item)

    log.info(f"Stage 2 complete. {len(halal_survivors)} halal survivors → insider heist.")
    _write_sentinel("STAGE2_DONE", {"HALAL_SURVIVORS": len(halal_survivors)})

    # ── INDEX ALPHA: Pre-compute free-float mcap rankings ─────────────────────
    # Run once over the top-N liquid symbols so per-stock cross-reference is O(1).
    # Disabled via INDEX_ALPHA_ENABLED=0 env var (e.g. to save yfinance API time).
    index_df = pd.DataFrame()
    if INDEX_ALPHA_ENABLED:
        try:
            # Use the top INDEX_ALPHA_UNIVERSE_N symbols by turnover from the
            # bhavcopy universe (already liquidity-sorted by load_universe()).
            alpha_symbols = list(bhav["symbol"].head(INDEX_ALPHA_UNIVERSE_N))
            index_df = get_index_alpha(alpha_symbols)
            if not index_df.empty:
                _write_sentinel("INDEX_ALPHA_DONE", {"RANKED": len(index_df)})
        except Exception as e:
            log.warning(f"Index Alpha compute failed (non-fatal): {e}")
    else:
        log.info("Index Alpha: disabled via INDEX_ALPHA_ENABLED=0")

    # ── STAGE 3: Data Heist + Insider Friend LLM Audit ───────────────────────
    stones: List[dict] = []
    log.info(f"Stage 3: NSE heist + Insider LLM on {len(halal_survivors)} stocks...")

    for item in halal_survivors:
        sym = item["symbol"]
        log.info(f"  🕵️ Heisting NSE data for {sym}...")

        # Scrape NSE corporate announcements + SAST insider trades + pledge % via curl_cffi
        filings, insiders, pledge_pct = fetch_insider_and_filings(sym)

        # Insider Friend LLM reads the legal filings (+ risk extraction + pledge classification)
        audit = insider_friend_audit(sym, filings, insiders, pledge_pct)
        total_score = item["math_score"] + audit.get("score", 0)

        # Hard veto: promoter buying under debt stress (pledge > 50%)
        if audit.get("pearl_grade") == "RED_FLAG":
            log.info(f"  🚩 RED_FLAG VETO {sym} | pledge={pledge_pct:.0f}% debt stress — skip")
            continue

        has_signal   = audit.get("stealth_catalyst_found") or audit.get("insider_buying_found")
        confidence   = audit.get("confidence_score", 0)

        # Gate: explicit insider signal OR math confidence ≥90 (Weinstein: sponge volume IS stealth buying)
        # conf<90 + no signal = skip. Raises bar vs v8's 85 to eliminate ASHOKLEY-type borderline cases.
        if not has_signal and confidence < 90:
            log.info(f"  ⏭ SKIP {sym} | no signal + conf={confidence} < 90")
            continue

        # Build targets from rubble gate data
        g1 = item["g1"]; g2 = item["g2"]; g3 = item["g3"]
        weekly     = item["weekly_df"]
        high_52w   = g1.get("high_52w", float(weekly["high"].max()))
        stop_loss  = round(weekly["low"].tail(4).min() * 0.97, 2)
        target_6m  = round(item["close"] * 1.30, 2)   # 30% recovery from rubble
        target_12m = round(item["close"] * 1.80, 2)   # 80% full recovery thesis

        log.info(f"  💎 PEARL {sym} | total={total_score} | "
                 f"catalyst={audit['stealth_catalyst_found']} "
                 f"insider_buy={audit['insider_buying_found']} "
                 f"conf={audit['confidence_score']}")

        stones.append({
            "symbol":                 sym,
            "close":                  item["close"],
            "total_score":            total_score,
            "stage":                  "RUBBLE",
            # Rubble gate
            "discount_pct":           g1.get("discount_pct", 0),
            "high_52w":               g1.get("high_52w", 0),
            "low_52w":                g1.get("low_52w", 0),
            "box_weeks":              g1.get("box_weeks", 0),
            "box_width_pct":          g1.get("box_width_pct", 0),
            "ma200_slope_pct":        g1.get("ma200_slope_pct", 0),
            "ma200":                  g1.get("ma200", 0),
            "rubble_score":           g1.get("score", 0),
            # Sector alpha (upgrade 2.2)
            "sector_alpha":           item.get("sector_alpha", 0),
            "sector_desc":            item.get("sector_desc", ""),
            "industry":               item.get("industry", ""),
            # EPS
            "eps_growth_pct":         g2.get("eps_growth_pct", 0),
            "eps_latest":             g2.get("eps_latest", 0),
            "eps_prior":              g2.get("eps_prior", 0),
            "eps_metric":             g2.get("metric", "EPS"),
            "eps_score":              g2.get("score", 0),
            # Sponge
            "dry_up_weeks":           g3.get("dry_up_weeks", 0),
            "sponge_weeks":           g3.get("sponge_weeks", 0),
            "sponge_score":           g3.get("score", 0),
            # Insider audit (upgrades 2.1 + 2.3)
            "pearl_grade":            audit.get("pearl_grade", "WATCH"),
            "stealth_catalyst":       audit.get("stealth_catalyst_found", False),
            "insider_buying":         audit.get("insider_buying_found", False),
            "capex_signal":           audit.get("capex_signal", False),
            "pledge_pct":             audit.get("pledge_pct", -1),
            "risk_flags":             audit.get("risk_flags", "")[:100],
            "risk_penalty":           audit.get("risk_penalty", 0),
            "insider_summary":        audit.get("insider_summary", "")[:150],
            "insider_confidence":     audit.get("confidence_score", 0),
            "insider_score":          audit.get("score", 0),
            # Targets
            "stop_loss":              stop_loss,
            "target_25pct":           target_6m,
            "target_60pct":           target_12m,
            "upside_6m_pct":          round((target_6m  / item["close"] - 1) * 100, 1),
            "upside_12m_pct":         round((target_12m / item["close"] - 1) * 100, 1),
            # Index Alpha fields (populated by apply_index_alpha_bonus below)
            "index_rank":             -1,
            "ff_mcap_cr":             0.0,
            "float_factor":           0.0,
            "story":                  "",
            "run_date":               date_label,
        })

        # ── Index Alpha cross-reference ────────────────────────────────────────
        # Mutates the stone just appended: may award +25 pts and DIAMOND upgrade.
        stones[-1] = apply_index_alpha_bonus(stones[-1], index_df)

    # Final sort — DIAMOND first, then catalyst+buying, then math score
    def _sort_key(x):
        grade_order = {"DIAMOND": 3, "PEARL": 2, "WATCH": 1, "UNKNOWN": 0}
        return (grade_order.get(x.get("pearl_grade", "UNKNOWN"), 0),
                int(x.get("stealth_catalyst", False)) + int(x.get("insider_buying", False)),
                x["total_score"])

    stones.sort(key=_sort_key, reverse=True)
    top_stones = stones[:TOP_N_STONES]
    run_duration = time.time() - run_start

    log.info("─" * 60)
    log.info(f"SYNDICATE SUMMARY | scanned={total} | s1={len(surv_candidates)} | "
             f"halal={len(halal_survivors)} | pearls={len(stones)} | "
             f"top{TOP_N_STONES}={[s['symbol'] for s in top_stones]} | "
             f"duration={run_duration:.0f}s")
    log.info("─" * 60)

    _write_sentinel("COMPLETE", {
        "SCANNED    ": total,
        "S1_SURVIVORS": len(surv_candidates),
        "HALAL      ": len(halal_survivors),
        "PEARLS     ": len(stones),
        "TOP_N      ": len(top_stones),
        "SYMBOLS    ": " ".join(s["symbol"] for s in top_stones),
        "DURATION_S ": round(run_duration, 1),
    })

    # ── Sandbox Training Logs — push every run regardless of results ──────────
    try:
        push_rejects_log(rejects_log, date_label)
    except Exception as e:
        log.warning(f"REJECTS_LOG push failed: {e}")
    try:
        push_sharia_log(sharia_decisions, date_label)
    except Exception as e:
        log.warning(f"SHARIA_LOG push failed: {e}")
    try:
        push_run_log(date_label, total, len(surv_candidates), len(halal_survivors),
                     len(stones), [s["symbol"] for s in top_stones], run_duration)
    except Exception as e:
        log.warning(f"RUN_LOG push failed: {e}")

    if not top_stones:
        _send_tg(
            f"🕴️ <b>INSIDER SYNDICATE v13.0 — {date_label}</b>\n"
            f"Scanned {total} stocks. No Pearls surfaced this week.\n"
            f"No stealth insider action detected. We wait in the shadows. 🕐"
        )
        return []

    push_stones_to_sheets(top_stones, date_label)
    send_telegram_stones(top_stones, date_label, total)

    return top_stones

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 16 — CLI
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fortress Incubator v13.0 Insider Syndicate + Index Alpha")
    parser.add_argument("--symbol", help="Score a single symbol for debug")
    args = parser.parse_args()

    if args.symbol:
        logging.getLogger().setLevel(logging.DEBUG)
        sym  = args.symbol.upper()
        bhav = load_universe()
        row  = bhav[bhav["symbol"] == sym]
        if row.empty:
            print(f"{sym} not in universe — using close=100")
            result = score_stone_math(sym, {"symbol": sym, "close": 100.0,
                                            "volume": 100000, "turnover_lakhs": 100.0})
        else:
            result = score_stone_math(sym, row.iloc[0].to_dict())
        if result:
            compliant, reason = dynamic_shariah_audit(sym)
            result["sharia_compliant"] = compliant
            result["sharia_reason"]    = reason
            result.pop("weekly_df", None)   # not JSON-serialisable
        print(json.dumps(result, indent=2, default=str) if result else f"{sym}: did not pass math gates")
    else:
        run()
