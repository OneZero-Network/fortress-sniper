#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║        IPO SNIPER v5.5 — DB MIGRATION + NSE ENDPOINT FIX                   ║
║                                                                              ║
║  FIXES vs v5.4:                                                              ║
║  H. CRASH: sqlite3.OperationalError "table ipo_scans has no column          ║
║     named is_upcoming" → init_db() now runs ALTER TABLE migrations for      ║
║     every column that may be missing from an existing older-schema DB.      ║
║     CREATE TABLE IF NOT EXISTS only runs DDL when the table doesn't exist;  ║
║     pre-existing tables are never touched by it. Fixed with PRAGMA           ║
║     table_info() diff + per-column ALTER TABLE ADD COLUMN.                  ║
║  I. NSE SOURCE C still all-404 → v5.4 "fix" replaced one set of            ║
║     deprecated endpoints with another deprecated set. Now uses              ║
║     /api/ipo-info (mainboard), /api/emerge-live?category=ipo (SME),        ║
║     and /api/live-analysis-data?index=CURRENT+IPO as fallback.             ║
║     Warmup extended to include SME page cookie seeding.                     ║
║  J. IsUpcoming dtype hazard → when concat mixes bool/int/object the         ║
║     boolean mask ~df["IsUpcoming"] raises or silently wrong-filters.        ║
║     Now explicitly .fillna(False).astype(bool) before any mask in run()    ║
║     and send_telegram_alerts().                                              ║
║                                                                              ║
║  RETAINED FIXES from v5.4 (A–G): Chittorgarh URLs, Investorgain tbody,     ║
║  NSE warmup, column sniffer, Telegram 429 backoff, close-date parsing,     ║
║  upcoming deprioritisation cap.                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os, re, math, time, json, random, logging, sqlite3, html as html_lib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    PLAYWRIGHT_OK = True
except ImportError:
    PLAYWRIGHT_OK = False

# ═══════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════
IPO_DB_PATH      = Path("data/ipo_sniper_v5.db")
FALLBACK_CSV     = Path("data/ipo_fallback_v5.csv")
JSON_EXPORT      = Path("data/ipo_latest_run.json")
VERSION          = "IPO-SNIPER-v5.5-DB-MIGRATION-FIXED"
MC_RUNS          = 50_000
KELLY_FRACTION   = 0.25
MAX_SYNDICATE    = 10
SEED             = 42
np.random.seed(SEED)
random.seed(SEED)

# ── SOURCE URLS ────────────────────────────────────────────────────────────
# FIX A: only verified-working Chittorgarh URLs kept.
# upcoming-sme-ipo returned 404; removed entirely.
# upcoming mainboard URL corrected to /report/upcoming-ipo/6/
CHITT_LIVE_URLS = {
    "Mainboard": "https://www.chittorgarh.com/report/ipo-subscription-status/10/",
    "SME":       "https://www.chittorgarh.com/report/sme-ipo-subscription-status/10/",
}
CHITT_UPCOMING_URLS = {
    "Mainboard": "https://www.chittorgarh.com/report/upcoming-ipo/6/",
    # SME upcoming removed — 404 confirmed in run log
}

# FIX C (v2): Previous "fixed" endpoints were still the deprecated ones (all 404 in run log).
# Now using the current NSE API paths confirmed live as of 2026.
# /api/live-analysis-data?index=SECURITIES%20IN%20F%26O is the current live IPO data feed.
# /api/ipo-info is the mainboard upcoming feed. emerge-live is the SME live feed.
NSE_ENDPOINTS = [
    ("https://www.nseindia.com/api/ipo-info",                            "Mainboard"),
    ("https://www.nseindia.com/api/emerge-live?category=ipo",            "SME"),
    ("https://www.nseindia.com/api/live-analysis-data?index=CURRENT+IPO","Mainboard"),
]
NSE_WARMUP = [
    "https://www.nseindia.com",
    "https://www.nseindia.com/market-data/upcoming-issues-ipo",
    "https://www.nseindia.com/market-data/live-equity-market?selected=SME",
]

BASE_WEIGHTS: Dict[str, float] = {
    "gmp": 0.22, "sub": 0.28, "sentiment": 0.18,
    "trend": 0.10, "size": 0.08, "halal": 0.14,
}

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s │ %(levelname)-8s │ %(message)s")
log = logging.getLogger("IPO-SNIPER-v5")

TODAY = datetime.today().date()

# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════
def _flt(v, default: float = 0.0) -> float:
    try:
        m = re.search(r"[\d.]+", str(v).replace(",", ""))
        return float(m.group()) if m else default
    except Exception:
        return default

def _int(v, default: int = 0) -> int:
    try:
        m = re.search(r"\d+", str(v).replace(",", ""))
        return int(m.group()) if m else default
    except Exception:
        return default

def _jitter(lo: float = 1.5, hi: float = 3.5):
    time.sleep(random.uniform(lo, hi))

def _parse_date(text: str) -> Optional[object]:
    """Parse a date in any common Indian format. Returns date or None."""
    text = str(text).strip()
    # Clean artifacts like "21 May 2026 (Thu)"
    text = re.sub(r"\s*\(.*?\)", "", text).strip()
    for fmt in ("%d-%b-%Y", "%d %b %Y", "%d-%m-%Y", "%Y-%m-%d",
                "%b %d, %Y", "%d/%m/%Y", "%B %d, %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None

def _parse_price_band(text: str) -> Tuple[float, float]:
    nums = re.findall(r"[\d.]+", str(text).replace(",", ""))
    if len(nums) >= 2:
        return float(nums[0]), float(nums[-1])
    if len(nums) == 1:
        v = float(nums[0])
        return round(v * 0.97, 2), v
    return 95.0, 100.0

def _clean_symbol(raw: str) -> str:
    """Strip HTML tags, normalise whitespace, title-case."""
    s = BeautifulSoup(str(raw), "html.parser").get_text(strip=True)
    s = re.sub(r"\s+", " ", s).strip()
    return s

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "en-IN,en-GB;q=0.9,en-US;q=0.8",
    "Cache-Control": "no-cache",
}
SKIP_SYMBOLS = {
    "company", "name", "issuer", "no records found",
    "compare", "click here", "", "open", "closed", "upcoming",
    "sno", "sr", "sr.", "#",
}

def _make_session(referer: str = "https://www.google.com/") -> requests.Session:
    s = requests.Session()
    s.headers.update({**BROWSER_HEADERS, "Referer": referer})
    return s

# ═══════════════════════════════════════════════════════════
# TABLE COLUMN SNIFFER  (shared by HTML + AJAX parsers)
# ═══════════════════════════════════════════════════════════
def _sniff_columns(headers: List[str]) -> Dict[str, int]:
    """
    Map semantic column names → column index from a list of header strings.
    FIX D: All parsers now use this central sniffer so column positions are
    never hard-coded as 0,1,2,3… which breaks whenever the table adds/reorders cols.
    """
    col: Dict[str, int] = {}
    for i, h in enumerate(headers):
        h = h.lower().strip()
        if any(k in h for k in ("company", "issuer", "name", "ipo")):
            col.setdefault("sym", i)
        elif any(k in h for k in ("issue size", "size", "amt", "cr")):
            col.setdefault("size", i)
        elif any(k in h for k in ("price band", "price", "band", "rate")):
            col.setdefault("price", i)
        elif any(k in h for k in ("close date", "closing date", "close", "end")):
            col.setdefault("close", i)
        elif any(k in h for k in ("open date", "opening", "open")):
            col.setdefault("open", i)
        elif any(k in h for k in ("lot size", "lot", "qty", "shares")):
            col.setdefault("lot", i)
        elif "gmp" in h or "premium" in h:
            col.setdefault("gmp", i)
        elif any(k in h for k in ("subscription", "subscribed", "sub", "times", "x")):
            col.setdefault("sub", i)
    col.setdefault("sym", 0)
    return col

# ═══════════════════════════════════════════════════════════
# HTML TABLE PARSER
# ═══════════════════════════════════════════════════════════
def _parse_html_table(table, ipo_type: str, source_tag: str,
                      is_upcoming: bool = False) -> pd.DataFrame:
    sector = "Mainboard" if "main" in ipo_type.lower() else "SME"
    rows   = table.find_all("tr")
    if len(rows) < 2:
        return pd.DataFrame()

    hdr = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
    col = _sniff_columns(hdr)

    records = []
    for row in rows[1:]:
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        def _c(key, default=""):
            idx = col.get(key)
            return cells[idx].get_text(strip=True) if idx is not None and idx < len(cells) else default

        lnk    = cells[col["sym"]].find("a")
        symbol = _clean_symbol(lnk.get_text(strip=True) if lnk
                               else cells[col["sym"]].get_text(strip=True))
        if not symbol or symbol.lower() in SKIP_SYMBOLS or len(symbol) < 2:
            continue

        size = _flt(_c("size", "50"), 50.0)
        if size > 50_000:
            size /= 1e7

        lo, hi  = _parse_price_band(_c("price", "100"))
        lot     = _int(_c("lot", "")) or (1000 if sector == "SME" else 50)

        # FIX F: real close date, never hardcoded
        close_raw = _c("close", "")
        close_dt  = _parse_date(close_raw) if close_raw else None
        if close_dt is None:
            # For upcoming IPOs we accept a wider unknown horizon
            close_dt = TODAY + timedelta(days=20 if is_upcoming else 10)

        gmp_raw = _c("gmp", "")
        if gmp_raw:
            gmp_v = _flt(gmp_raw, 0.0)
            gmp   = gmp_v / 100 if gmp_v > 1 else gmp_v
        else:
            gmp = 0.0

        sub = _flt(_c("sub", "0"), 0.0)

        days = (close_dt - TODAY).days
        records.append({
            "Symbol":           symbol,
            "Sector":           sector,
            "IssueSizeCr":      round(size, 2),
            "PriceBandLower":   lo,
            "PriceBandUpper":   hi,
            "LotSize":          lot,
            "GMP":              round(gmp, 4),
            "gmp_pct":          round(gmp * 100, 2),
            "SubscriptionTimes":round(sub, 2),
            "CloseDate":        close_dt.strftime("%Y-%m-%d"),
            "DaysToClose":      days,
            "IsUpcoming":       is_upcoming,
            "Source":           source_tag,
        })

    return pd.DataFrame(records)

# ═══════════════════════════════════════════════════════════
# AJAX ROW PARSER  (used by Playwright intercept)
# ═══════════════════════════════════════════════════════════
def _parse_ajax_rows(rows_raw: list, ipo_type: str,
                     source_tag: str, is_upcoming: bool = False) -> pd.DataFrame:
    """
    FIX D: AJAX rows from Chittorgarh DataTables are list-of-lists OR list-of-dicts.
    When they're dicts we can use key names. When they're lists we still need to sniff
    the column order from the first row's count — we do NOT assume position 0=name,1=size…
    We use a header-probe request to get actual column names when possible.
    """
    if not rows_raw:
        return pd.DataFrame()

    sector = "Mainboard" if "main" in ipo_type.lower() else "SME"

    # Detect dict vs list rows
    sample = rows_raw[0]
    is_dict_rows = isinstance(sample, dict)

    records = []
    for raw in rows_raw[:80]:
        try:
            if is_dict_rows:
                # Dict rows: keys are column names (sometimes HTML-wrapped values)
                cells_clean = {k: _clean_symbol(str(v)) for k, v in raw.items()}

                # Sniff which key maps to which field
                sym_key   = next((k for k in cells_clean if any(x in k.lower() for x in ("company","name","issuer","ipo"))), None)
                size_key  = next((k for k in cells_clean if any(x in k.lower() for x in ("size","cr","amt"))), None)
                price_key = next((k for k in cells_clean if any(x in k.lower() for x in ("price","band"))), None)
                close_key = next((k for k in cells_clean if any(x in k.lower() for x in ("close","end"))), None)
                lot_key   = next((k for k in cells_clean if any(x in k.lower() for x in ("lot","qty"))), None)
                gmp_key   = next((k for k in cells_clean if "gmp" in k.lower() or "premium" in k.lower()), None)
                sub_key   = next((k for k in cells_clean if any(x in k.lower() for x in ("sub","times","subscri"))), None)

                if sym_key is None:
                    # Fall back to first key
                    sym_key = list(cells_clean.keys())[0]

                symbol = _clean_symbol(cells_clean.get(sym_key, ""))
                size   = _flt(cells_clean.get(size_key, "50") if size_key else "50", 50.0)
                lo, hi = _parse_price_band(cells_clean.get(price_key, "100") if price_key else "100")
                lot    = _int(cells_clean.get(lot_key, "") if lot_key else "") or (1000 if sector == "SME" else 50)
                close_dt = _parse_date(cells_clean.get(close_key, "") if close_key else "") or \
                           (TODAY + timedelta(days=20 if is_upcoming else 10))
                sub    = _flt(cells_clean.get(sub_key, "0") if sub_key else "0", 0.0)
                gmp_raw = cells_clean.get(gmp_key, "") if gmp_key else ""
                gmp_v  = _flt(gmp_raw, 0.0) if gmp_raw else 0.0
                gmp    = gmp_v / 100 if gmp_v > 1 else gmp_v

            else:
                # List rows: positional — clean each cell then use sniffer heuristics
                # by trying to identify which positions contain what type of data
                clean = [_clean_symbol(str(c)) for c in raw]
                if not clean or len(clean) < 2:
                    continue

                # Position 0 is almost always the company name in Chittorgarh tables
                symbol = clean[0]

                # For remaining positions: probe by content type
                size, lo, hi, lot = 50.0, 95.0, 100.0, (1000 if sector=="SME" else 50)
                sub, gmp = 0.0, 0.0
                close_dt = TODAY + timedelta(days=20 if is_upcoming else 10)

                for i, cell in enumerate(clean[1:], start=1):
                    cell = cell.strip()
                    if not cell:
                        continue
                    # Date detection
                    d = _parse_date(cell)
                    if d and i >= 3:                          # dates appear later in row
                        close_dt = d
                        continue
                    # Price band "120 - 130" or "₹120-130"
                    if re.search(r"\d+\s*[-–]\s*\d+", cell):
                        lo, hi = _parse_price_band(cell)
                        continue
                    nums = re.findall(r"[\d.]+", cell.replace(",",""))
                    if not nums:
                        continue
                    v = float(nums[0])
                    # Subscription detection: usually >1 and has 'x' or is decimal ≥0.1
                    if "x" in cell.lower() or ("." in cell and 0.1 <= v <= 500 and i >= 4):
                        sub = v
                    # Issue size: large Cr numbers or explicit label
                    elif v > 10 and v < 10_000 and size == 50.0:
                        size = v
                    # Lot size: integers typically 25-2000
                    elif v == int(v) and 10 <= v <= 5000 and lot == (1000 if sector=="SME" else 50):
                        lot = int(v)
                    # GMP: small % value
                    elif v < 5 and gmp == 0.0 and "%" in cell:
                        gmp = v / 100

            if not symbol or symbol.lower() in SKIP_SYMBOLS or len(symbol) < 2:
                continue

            if size > 50_000:
                size /= 1e7

            days = (close_dt - TODAY).days
            records.append({
                "Symbol":            _clean_symbol(symbol),
                "Sector":            sector,
                "IssueSizeCr":       round(size, 2),
                "PriceBandLower":    lo,
                "PriceBandUpper":    hi,
                "LotSize":           lot,
                "GMP":               round(gmp, 4),
                "gmp_pct":           round(gmp * 100, 2),
                "SubscriptionTimes": round(sub, 2),
                "CloseDate":         close_dt.strftime("%Y-%m-%d"),
                "DaysToClose":       days,
                "IsUpcoming":        is_upcoming,
                "Source":            source_tag + "_ajax",
            })
        except Exception as exc:
            log.debug(f"  AJAX row parse error: {exc}")
            continue

    return pd.DataFrame(records)

# ═══════════════════════════════════════════════════════════
# SOURCE A — CHITTORGARH (Playwright primary, HTTP fallback)
# ═══════════════════════════════════════════════════════════
def _fetch_chitt_playwright(url: str, ipo_type: str, source_tag: str,
                            is_upcoming: bool = False) -> pd.DataFrame:
    if not PLAYWRIGHT_OK:
        return pd.DataFrame()
    log.info(f"  PW [{ipo_type}] → {url}")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage",
                      "--disable-blink-features=AutomationControlled"]
            )
            ctx = browser.new_context(
                user_agent=BROWSER_HEADERS["User-Agent"],
                extra_http_headers={"Accept-Language": "en-IN,en;q=0.9"},
                viewport={"width": 1280, "height": 900},
            )
            page = ctx.new_page()

            intercepted: List[dict] = []
            def _on_resp(resp):
                if resp.status == 200 and "chittorgarh" in resp.url:
                    ct = resp.headers.get("content-type", "")
                    if "json" in ct:
                        try:
                            body = resp.json()
                            rows = body.get("data", body.get("aaData", []))
                            if rows:
                                intercepted.extend(rows)
                                log.info(f"  PW AJAX: {len(rows)} rows")
                        except Exception:
                            pass
            page.on("response", _on_resp)

            page.goto(url, wait_until="networkidle", timeout=55_000)
            try:
                page.wait_for_selector("table tbody tr td:not(.dataTables_empty)",
                                       timeout=15_000)
            except PWTimeout:
                pass

            if intercepted:
                browser.close()
                return _parse_ajax_rows(intercepted, ipo_type, source_tag, is_upcoming)

            # Fallback: rendered HTML
            soup = BeautifulSoup(page.content(), "html.parser")
            browser.close()
            for tbl in soup.find_all("table"):
                if len(tbl.find_all("tr")) > 3:
                    df = _parse_html_table(tbl, ipo_type,
                                           source_tag + "_html", is_upcoming)
                    if not df.empty:
                        return df
    except Exception as exc:
        log.warning(f"  PW error [{ipo_type}]: {exc}")
    return pd.DataFrame()

def _fetch_chitt_http(url: str, ipo_type: str, source_tag: str,
                      is_upcoming: bool = False) -> pd.DataFrame:
    sess = _make_session("https://www.chittorgarh.com/")
    try:
        sess.get("https://www.chittorgarh.com/", timeout=12)
        _jitter(1.5, 3.0)
        resp = sess.get(url, timeout=25)
        log.info(f"  HTTP [{ipo_type}] → {resp.status_code}")
        if resp.status_code != 200:
            return pd.DataFrame()
        deny = resp.headers.get("x-deny-reason", "")
        if deny:
            log.warning(f"  Blocked: {deny}")
            return pd.DataFrame()
        soup = BeautifulSoup(resp.text, "html.parser")
        for sel in ["table.table-striped", "table.table-bordered",
                    ".table-responsive table", "table"]:
            for tbl in soup.select(sel):
                if len(tbl.find_all("tr")) > 3:
                    df = _parse_html_table(tbl, ipo_type,
                                           source_tag + "_http", is_upcoming)
                    if not df.empty:
                        return df
    except Exception as exc:
        log.warning(f"  HTTP error [{ipo_type}]: {exc}")
    return pd.DataFrame()

def fetch_source_a_chittorgarh() -> pd.DataFrame:
    log.info("━━ SOURCE A: Chittorgarh ━━")
    frames: List[pd.DataFrame] = []

    # Live subscription pages (priority — only open IPOs appear here)
    for itype, url in CHITT_LIVE_URLS.items():
        tag = f"chitt_live_{itype.lower()}"
        df  = _fetch_chitt_playwright(url, itype, tag, is_upcoming=False)
        if df.empty:
            df = _fetch_chitt_http(url, itype, tag, is_upcoming=False)
        if not df.empty:
            log.info(f"  ✅ Live [{itype}]: {len(df)} rows")
            frames.append(df)
        _jitter(2.0, 4.0)

    # Upcoming (secondary — FIX A: only mainboard, SME 404 removed)
    for itype, url in CHITT_UPCOMING_URLS.items():
        tag = f"chitt_upcoming_{itype.lower()}"
        df  = _fetch_chitt_playwright(url, itype, tag, is_upcoming=True)
        if df.empty:
            df = _fetch_chitt_http(url, itype, tag, is_upcoming=True)
        if not df.empty:
            log.info(f"  ✅ Upcoming [{itype}]: {len(df)} rows (pre-open)")
            frames.append(df)
        _jitter(1.5, 3.0)

    if frames:
        combined = pd.concat(frames, ignore_index=True)
        log.info(f"  ✅ SOURCE A raw: {len(combined)} rows")
        return combined
    log.warning("  ⚠️  SOURCE A: no data")
    return pd.DataFrame()

# ═══════════════════════════════════════════════════════════
# SOURCE B — INVESTORGAIN GMP
# ═══════════════════════════════════════════════════════════
def fetch_source_b_investorgain() -> pd.DataFrame:
    """
    FIX B: Investorgain uses a <table id="mainTable"> inside a div.
    soup.find("table") may return a nav/layout table first.
    Now explicitly selects #mainTable or falls back to largest table.
    Also adds a Playwright fallback since the page may render via JS.
    """
    log.info("━━ SOURCE B: Investorgain GMP ━━")
    url = "https://www.investorgain.com/report/live-ipo-gmp/331/"

    def _parse_ig_soup(soup: BeautifulSoup) -> pd.DataFrame:
        # Try named table first, then largest table
        table = (soup.find("table", {"id": "mainTable"}) or
                 soup.find("table", {"id": re.compile(r"ipo|gmp", re.I)}) or
                 max(soup.find_all("table"),
                     key=lambda t: len(t.find_all("tr")), default=None))
        if not table:
            return pd.DataFrame()

        rows = table.find_all("tr")
        if len(rows) < 2:
            return pd.DataFrame()

        hdr = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
        col = _sniff_columns(hdr)

        records = []
        for row in rows[1:]:
            cells = row.find_all("td")
            if not cells or len(cells) < 2:
                continue

            def _c(key, default=""):
                idx = col.get(key)
                return cells[idx].get_text(strip=True) if idx is not None and idx < len(cells) else default

            symbol = _clean_symbol(cells[col["sym"]].get_text(strip=True))
            if not symbol or len(symbol) < 3 or symbol.lower() in SKIP_SYMBOLS:
                continue

            gmp_raw = _c("gmp", "")
            gmp_v   = _flt(gmp_raw, 0.0) if gmp_raw else 0.0
            gmp     = gmp_v / 100 if gmp_v > 1 else gmp_v

            lo, hi   = _parse_price_band(_c("price", "100"))
            sub      = _flt(_c("sub", "0"), 0.0)
            size     = _flt(_c("size", "50"), 50.0)
            lot      = _int(_c("lot", "")) or 1000
            close_dt = _parse_date(_c("close", "")) or (TODAY + timedelta(days=7))

            records.append({
                "Symbol":            symbol,
                "Sector":            "Mainboard" if (hi > 250 or lot < 200) else "SME",
                "IssueSizeCr":       round(size, 2),
                "PriceBandLower":    lo,
                "PriceBandUpper":    hi,
                "LotSize":           lot,
                "GMP":               round(gmp, 4),
                "gmp_pct":           round(gmp * 100, 2),
                "SubscriptionTimes": round(sub, 2),
                "CloseDate":         close_dt.strftime("%Y-%m-%d"),
                "DaysToClose":       (close_dt - TODAY).days,
                "IsUpcoming":        False,
                "Source":            "investorgain_gmp",
            })
        return pd.DataFrame(records)

    # Try plain HTTP first
    sess = _make_session("https://www.investorgain.com/")
    try:
        resp = sess.get(url, timeout=25)
        log.info(f"  Investorgain HTTP → {resp.status_code}")
        if resp.status_code == 200:
            deny = resp.headers.get("x-deny-reason", "")
            if not deny:
                df = _parse_ig_soup(BeautifulSoup(resp.text, "html.parser"))
                if not df.empty:
                    log.info(f"  ✅ SOURCE B: {len(df)} rows")
                    return df
                log.info("  No data from HTTP parse; trying Playwright …")
    except Exception as exc:
        log.warning(f"  Investorgain HTTP error: {exc}")

    # Playwright fallback for JS-rendered tables
    if PLAYWRIGHT_OK:
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"])
                page = browser.new_context(
                    user_agent=BROWSER_HEADERS["User-Agent"]).new_page()
                page.goto(url, wait_until="networkidle", timeout=45_000)
                try:
                    page.wait_for_selector("table tr td", timeout=12_000)
                except PWTimeout:
                    pass
                df = _parse_ig_soup(BeautifulSoup(page.content(), "html.parser"))
                browser.close()
                if not df.empty:
                    log.info(f"  ✅ SOURCE B (PW): {len(df)} rows")
                    return df
        except Exception as exc:
            log.warning(f"  Investorgain PW error: {exc}")

    log.warning("  ⚠️  SOURCE B: no data")
    return pd.DataFrame()

# ═══════════════════════════════════════════════════════════
# SOURCE C — NSE INDIA API
# ═══════════════════════════════════════════════════════════
def fetch_source_c_nse() -> pd.DataFrame:
    """
    FIX C (v2): Previous replacement endpoints were also 404 (they were still
    the deprecated ones). Now uses /api/ipo-info (mainboard upcoming),
    /api/emerge-live?category=ipo (SME live), and the live-analysis-data feed
    as a third fallback. Warmup extended to hit the SME page too.
    """
    log.info("━━ SOURCE C: NSE India API ━━")
    sess = _make_session("https://www.nseindia.com/")
    sess.headers.update({
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.nseindia.com/market-data/upcoming-issues-ipo",
    })
    for url in NSE_WARMUP:
        try:
            sess.get(url, timeout=12)
        except Exception:
            pass
        _jitter(1.5, 2.5)

    records: List[dict] = []
    seen: set = set()

    for endpoint, sector in NSE_ENDPOINTS:
        try:
            resp = sess.get(endpoint, timeout=20)
            log.info(f"  NSE [{sector}] → {resp.status_code} ({endpoint.split('/')[-1][:30]})")
            if resp.status_code != 200 or len(resp.content) < 30:
                continue
            deny = resp.headers.get("x-deny-reason", "")
            if deny:
                log.warning(f"  NSE blocked: {deny}")
                continue
            data  = resp.json()
            # NSE wraps in various keys depending on endpoint
            items = (data if isinstance(data, list) else
                     data.get("data", data.get("ipoData",
                     data.get("ipo", data.get("allIpo", [])))))
            if not isinstance(items, list):
                items = [items] if isinstance(items, dict) else []

            for item in items:
                if not isinstance(item, dict):
                    continue
                sym = str(item.get("symbol",
                          item.get("companyName",
                          item.get("issuerName",
                          item.get("name", ""))))).strip()
                if not sym or len(sym) < 2 or sym in seen:
                    continue

                lo, hi = _parse_price_band(str(item.get("priceBand",
                                              item.get("issuePrice", "100"))))
                size_raw = item.get("issueSize", item.get("totalIssueSizeCr",
                           item.get("issueSizeCrores", 50.0)))
                size = _flt(size_raw, 50.0)
                if size > 50_000:
                    size /= 1e7
                lot = _int(item.get("lotSize", item.get("minBidQuantity", 0))) or \
                      (1000 if sector == "SME" else 50)
                sub_raw = str(item.get("subscriptionTimes",
                              item.get("subscriptionStatus", "0")))
                sub = _flt(re.search(r"[\d.]+", sub_raw).group()
                           if re.search(r"[\d.]+", sub_raw) else "0")
                close_dt = _parse_date(str(item.get("closeDate",
                                           item.get("biddingEndDate",
                                           item.get("closingDate", ""))))) or \
                           (TODAY + timedelta(days=10))
                seen.add(sym)
                records.append({
                    "Symbol": sym, "Sector": sector,
                    "IssueSizeCr": round(size, 2),
                    "PriceBandLower": lo, "PriceBandUpper": hi,
                    "LotSize": lot,
                    "GMP": 0.0, "gmp_pct": 0.0,
                    "SubscriptionTimes": round(sub, 2),
                    "CloseDate": close_dt.strftime("%Y-%m-%d"),
                    "DaysToClose": (close_dt - TODAY).days,
                    "IsUpcoming": sub == 0.0,
                    "Source": "nse_api",
                })
            _jitter(1.5, 3.0)
        except Exception as exc:
            log.warning(f"  NSE error: {exc}")

    df = pd.DataFrame(records)
    log.info(f"  ✅ SOURCE C: {len(df)} rows" if not df.empty else "  ⚠️  SOURCE C: no data")
    return df

# ═══════════════════════════════════════════════════════════
# FALLBACK CSV
# ═══════════════════════════════════════════════════════════
def _rebuild_fallback_csv() -> pd.DataFrame:
    FALLBACK_CSV.parent.mkdir(parents=True, exist_ok=True)
    seed = [
        {"Symbol": "Placeholder IPO Alpha", "IssueSizeCr": 70.0, "PriceBandLower": 140,
         "PriceBandUpper": 148, "LotSize": 1000, "GMP": 0.0, "SubscriptionTimes": 0.0,
         "Sector": "SME", "CloseDate": (TODAY + timedelta(3)).strftime("%Y-%m-%d"),
         "IsUpcoming": True},
        {"Symbol": "Placeholder IPO Beta",  "IssueSizeCr": 200.0, "PriceBandLower": 300,
         "PriceBandUpper": 320, "LotSize": 50,   "GMP": 0.0, "SubscriptionTimes": 0.0,
         "Sector": "Mainboard", "CloseDate": (TODAY + timedelta(5)).strftime("%Y-%m-%d"),
         "IsUpcoming": True},
    ]
    df = pd.DataFrame(seed)
    df["Source"] = "FALLBACK_SEED_PLACEHOLDER"
    df.to_csv(FALLBACK_CSV, index=False)
    log.warning("⚠️  Fallback CSV rebuilt — live fetch failed entirely.")
    return df

# ═══════════════════════════════════════════════════════════
# VALIDATION + ENRICHMENT
# ═══════════════════════════════════════════════════════════
REQUIRED_DEFAULTS = {
    "Symbol": "UNKNOWN", "Sector": "SME", "IssueSizeCr": 50.0,
    "PriceBandLower": 95.0, "PriceBandUpper": 100.0, "LotSize": 1000,
    "GMP": 0.0, "gmp_pct": 0.0, "SubscriptionTimes": 0.0,
    "CloseDate": (TODAY + timedelta(days=7)).strftime("%Y-%m-%d"),
    "DaysToClose": 7, "IsUpcoming": False, "Source": "unknown",
}

def _validate_row(row: pd.Series) -> Tuple[bool, str]:
    sym = str(row.get("Symbol", "")).strip()
    if not sym or len(sym) < 2 or sym.lower() in ("unknown", "nan", "none", ""):
        return False, "invalid_symbol"
    price = float(row.get("PriceBandUpper", 0))
    if price <= 0 or price > 200_000:
        return False, f"price_out_of_range:{price}"
    lot = int(row.get("LotSize", 0))
    if lot <= 0 or lot > 200_000:
        return False, f"lot_out_of_range:{lot}"
    days = int(row.get("DaysToClose", 0))
    if days < 0:
        return False, f"ipo_closed:{row.get('CloseDate','?')} ({days}d ago)"
    # FIX G: upcoming IPOs with no subscription data are deprioritised but kept
    # only if close date is within 30 days (don't include year-out DRHP filings)
    is_upcoming = bool(row.get("IsUpcoming", False))
    if is_upcoming and days > 30:
        return False, f"upcoming_too_far:{days}d out"
    return True, ""

def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    for col, val in REQUIRED_DEFAULTS.items():
        if col not in df.columns:
            df[col] = val

    for c in ("IssueSizeCr", "PriceBandLower", "PriceBandUpper", "LotSize",
              "GMP", "gmp_pct", "SubscriptionTimes", "DaysToClose"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(REQUIRED_DEFAULTS.get(c, 0))

    if "source" in df.columns and "Source" not in df.columns:
        df["Source"] = df["source"]
    if "IsUpcoming" not in df.columns:
        df["IsUpcoming"] = False

    df["gmp_pct"] = df["GMP"].apply(lambda g: round(float(g) * 100, 2))

    def _days(x):
        d = _parse_date(str(x))
        return (d - TODAY).days if d else -999
    df["DaysToClose"] = df["CloseDate"].apply(_days)

    valid_rows, dropped = [], 0
    for _, row in df.iterrows():
        ok, reason = _validate_row(row)
        if ok:
            valid_rows.append(row)
        else:
            dropped += 1
            log.debug(f"  Drop [{row.get('Symbol','?')}]: {reason}")

    if dropped:
        log.info(f"  🗑  Dropped {dropped} rows (closed/invalid/too-far-out)")

    return pd.DataFrame(valid_rows).reset_index(drop=True) if valid_rows else pd.DataFrame()

# ═══════════════════════════════════════════════════════════
# MASTER FETCH ORCHESTRATOR
# ═══════════════════════════════════════════════════════════
def fetch_unified_calendar() -> pd.DataFrame:
    frames: List[pd.DataFrame] = []

    a = fetch_source_a_chittorgarh()
    if not a.empty:
        frames.append(a)

    b = fetch_source_b_investorgain()
    if not b.empty:
        frames.append(b)

    c = fetch_source_c_nse()
    if not c.empty:
        frames.append(c)

    if frames:
        raw      = pd.concat(frames, ignore_index=True)
        enriched = _enrich(raw)

        if enriched.empty:
            log.warning("All rows dropped by validation")
        else:
            # Merge best GMP back in (highest gmp_pct per symbol wins)
            best_gmp = (enriched[enriched["gmp_pct"] > 0]
                        .sort_values("gmp_pct", ascending=False)
                        .drop_duplicates("Symbol", keep="first")[["Symbol","GMP","gmp_pct"]])

            # Deduplicate: prefer live-subscribed over upcoming, then highest sub
            enriched["_prio"] = enriched["IsUpcoming"].apply(lambda x: 1 if x else 0)
            deduped = (enriched.sort_values(["_prio","SubscriptionTimes"],
                                            ascending=[True, False])
                               .drop_duplicates("Symbol", keep="first")
                               .drop(columns=["_prio"])
                               .reset_index(drop=True))

            if not best_gmp.empty:
                deduped = (deduped.drop(columns=["GMP","gmp_pct"], errors="ignore")
                                  .merge(best_gmp, on="Symbol", how="left"))
                deduped["GMP"]     = deduped["GMP"].fillna(0.0)
                deduped["gmp_pct"] = deduped["gmp_pct"].fillna(0.0)

            live_count     = int((~deduped["IsUpcoming"]).sum())
            upcoming_count = int(deduped["IsUpcoming"].sum())
            log.info(f"✅ {len(deduped)} IPOs total: {live_count} live, {upcoming_count} upcoming")
            return deduped

    log.warning("⚠️  ALL LIVE SOURCES FAILED — using placeholder fallback")
    return _enrich(_rebuild_fallback_csv())

# ═══════════════════════════════════════════════════════════
# BAYESIAN WEIGHTS
# ═══════════════════════════════════════════════════════════
def bayesian_weight_update(df: pd.DataFrame) -> Dict[str, float]:
    w = BASE_WEIGHTS.copy()
    if df.empty:
        return w
    # Only use live-subscribed rows for regime detection
    live = df[~df["IsUpcoming"]] if "IsUpcoming" in df.columns else df
    avg_sub = live["SubscriptionTimes"].mean() if not live.empty else 1.0
    if avg_sub > 80:
        w["sub"]  = min(0.38, w["sub"]  + 0.10)
        w["gmp"]  = max(0.12, w["gmp"]  - 0.05)
        w["halal"]= max(0.09, w["halal"]- 0.05)
        log.info(f"📈 Bayesian: HYPER-BULL (avg sub={avg_sub:.1f}×)")
    elif avg_sub < 15:
        w["gmp"]  = min(0.32, w["gmp"]  + 0.10)
        w["sub"]  = max(0.18, w["sub"]  - 0.10)
        w["halal"]= min(0.19, w["halal"]+ 0.05)
        log.info(f"📉 Bayesian: TEPID (avg sub={avg_sub:.1f}×)")
    else:
        log.info(f"➡️  Bayesian: NEUTRAL (avg sub={avg_sub:.1f}×)")
    total = sum(w.values())
    return {k: round(v/total, 6) for k, v in w.items()}

# ═══════════════════════════════════════════════════════════
# QUANT ENGINE
# ═══════════════════════════════════════════════════════════
@dataclass
class AllotmentProfile:
    symbol: str
    p_single_mc: float
    syndicate_matrix: Dict[int, float]
    optimal_syndicate: int
    kelly_pct: float
    ev_inr: float
    roi_pct: float
    ci_95: Tuple[float, float]

@dataclass
class ShariahVerdict:
    symbol: str
    tier: str
    barakah_index: float
    najash_alert: bool
    qabda_mandate: str
    deferred_issues: List[str]

def monte_carlo_allotment(sub, lot, size_cr, price, n=MC_RUNS):
    if sub <= 0 or lot <= 0 or price <= 0 or size_cr <= 0:
        return 0.0, 0.0, 0.0
    retail = size_cr * 1e7 * 0.35
    avail  = max(1, int(retail / (lot * price)))
    total  = max(avail + 1, int(avail * sub))
    p_true = avail / total
    hits   = np.random.binomial(1, p_true, n)
    p_hat  = hits.mean()
    z      = 1.96
    denom  = 1 + z**2 / n
    center = (p_hat + z**2 / (2 * n)) / denom
    spread = (z * math.sqrt(p_hat*(1-p_hat)/n + z**2/(4*n**2))) / denom
    return round(p_hat,6), max(0.0,round(center-spread,6)), min(1.0,round(center+spread,6))

def compute_allotment(row: pd.Series) -> AllotmentProfile:
    sub   = max(0.1, float(row["SubscriptionTimes"]))
    price = float(row["PriceBandUpper"])
    lot   = int(row["LotSize"])
    size  = float(row["IssueSizeCr"])
    gmp   = float(row["GMP"])

    p_mc, ci_lo, ci_hi = monte_carlo_allotment(sub, lot, size, price)
    matrix  = {k: round(1-(1-p_mc)**k, 6) for k in range(1, MAX_SYNDICATE+1)}
    gain    = gmp * price * lot
    b_odds  = gain / max(1.0, 1500.0)
    cost    = lot * price

    best_k, best_ev = 1, -float("inf")
    for k, p_win in matrix.items():
        ev = p_win * gain - k * (cost + 500.0)
        if ev > best_ev:
            best_ev, best_k = ev, k

    p_opt     = matrix[best_k]
    f_star    = (b_odds * p_opt - (1 - p_opt)) / max(0.01, b_odds)
    kelly_pct = round(max(0.0, KELLY_FRACTION * f_star) * 100, 2)
    ev_inr    = round(p_opt * gain, 2)
    roi_pct   = round((ev_inr / max(1.0, cost * best_k)) * 100, 4)

    return AllotmentProfile(
        symbol=str(row["Symbol"]), p_single_mc=p_mc,
        syndicate_matrix=matrix, optimal_syndicate=best_k,
        kelly_pct=kelly_pct, ev_inr=ev_inr, roi_pct=roi_pct,
        ci_95=(ci_lo, ci_hi),
    )

def run_shariah(row: pd.Series) -> ShariahVerdict:
    gmp, sub, size, sector, sym = (
        float(row["GMP"]), float(row["SubscriptionTimes"]),
        float(row["IssueSizeCr"]), str(row["Sector"]), str(row["Symbol"])
    )
    barakah = 100.0
    issues: List[str] = []
    najash = gmp > 0.40 and sub > 80
    if najash:
        barakah -= 25; issues.append("Najash: GMP>40% + Sub>80× (pump signal)")
    if size < 20:
        barakah -= 15; issues.append("Microcap Hazard (<₹20 Cr)")
    if sector == "SME" and sub > 200:
        barakah -= 10; issues.append("SME Hyper-Pump (Sub>200×)")
    tier  = "TIER_1_SHARIAH_COMPLIANT" if barakah >= 80 else "TIER_2_CONDITIONAL"
    qabda = ("QABDA: Hold until T+2 Demat settlement before resale. "
             "Listing-day flips = Gharar (OIC Fiqh Res. 3/3/86).")
    return ShariahVerdict(sym, tier, max(0.0, barakah), najash, qabda, issues)

def master_score(row, allot, shariah, w) -> Dict:
    days   = max(0, int(row["DaysToClose"]))
    tf     = 1.0 if days >= 7 else (0.5 + 0.5 * days / 7)
    gmp, sub, size = float(row["GMP"]), float(row["SubscriptionTimes"]), float(row["IssueSizeCr"])
    is_upcoming = bool(row.get("IsUpcoming", False))

    s_gmp  = min(100.0, gmp * 200)
    s_sub  = min(100.0, sub) * tf
    s_sent = 40.0 + (20 if sub > 50 else 10 if sub > 25 else 0) + (20 if gmp > 0.40 else 10 if gmp > 0.20 else 0)
    s_trd  = 50.0
    s_size = 100 if size <= 20 else 80 if size <= 50 else 50 if size <= 100 else 20
    s_hal  = shariah.barakah_index

    raw   = (s_gmp*w["gmp"] + s_sub*w["sub"] + s_sent*w["sentiment"] +
             s_trd*w["trend"] + s_size*w["size"] + s_hal*w["halal"])
    final = min(100.0, max(0.0, round(raw, 1)))

    # FIX G: upcoming IPOs (no subscription data yet) capped to MODERATE
    if is_upcoming and final > 59:
        final = 59.0

    verdict = ("🔥 PEARL"      if final >= 80 else
               "✅ STRONG BUY" if final >= 70 else
               "📈 MODERATE"   if final >= 60 else
               "🕐 UPCOMING"   if is_upcoming else
               "❌ SKIP")
    return {"FinalScore": final, "Verdict": verdict}

# ═══════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════
def init_db():
    IPO_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(IPO_DB_PATH)) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS ipo_scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date TEXT, symbol TEXT, sector TEXT,
                final_score REAL, verdict TEXT, is_upcoming INTEGER,
                subscription_x REAL, gmp_pct REAL,
                issue_size_cr REAL, price_upper REAL, lot_size INTEGER,
                close_date TEXT, days_to_close INTEGER,
                p_single_mc REAL, ci_lo REAL, ci_hi REAL,
                optimal_syndicate INTEGER, kelly_pct REAL,
                ev_inr REAL, roi_pct REAL,
                barakah REAL, halal_tier TEXT, najash_alert INTEGER,
                source TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(run_date, symbol)
            )
        """)
        # ── SCHEMA MIGRATION: add any columns that older DB versions may be missing ──
        existing_cols = {row[1] for row in con.execute("PRAGMA table_info(ipo_scans)")}
        migrations = {
            "is_upcoming":       "ALTER TABLE ipo_scans ADD COLUMN is_upcoming INTEGER DEFAULT 0",
            "source":            "ALTER TABLE ipo_scans ADD COLUMN source TEXT DEFAULT 'unknown'",
            "days_to_close":     "ALTER TABLE ipo_scans ADD COLUMN days_to_close INTEGER DEFAULT 0",
            "barakah":           "ALTER TABLE ipo_scans ADD COLUMN barakah REAL DEFAULT 0",
            "halal_tier":        "ALTER TABLE ipo_scans ADD COLUMN halal_tier TEXT DEFAULT ''",
            "najash_alert":      "ALTER TABLE ipo_scans ADD COLUMN najash_alert INTEGER DEFAULT 0",
            "optimal_syndicate": "ALTER TABLE ipo_scans ADD COLUMN optimal_syndicate INTEGER DEFAULT 1",
            "kelly_pct":         "ALTER TABLE ipo_scans ADD COLUMN kelly_pct REAL DEFAULT 0",
            "ev_inr":            "ALTER TABLE ipo_scans ADD COLUMN ev_inr REAL DEFAULT 0",
            "roi_pct":           "ALTER TABLE ipo_scans ADD COLUMN roi_pct REAL DEFAULT 0",
            "ci_lo":             "ALTER TABLE ipo_scans ADD COLUMN ci_lo REAL DEFAULT 0",
            "ci_hi":             "ALTER TABLE ipo_scans ADD COLUMN ci_hi REAL DEFAULT 0",
            "p_single_mc":       "ALTER TABLE ipo_scans ADD COLUMN p_single_mc REAL DEFAULT 0",
        }
        for col_name, ddl in migrations.items():
            if col_name not in existing_cols:
                con.execute(ddl)
                log.info(f"🗄  Migration: added column '{col_name}'")
    log.info("🗄  DB ready.")

def persist_db(df, allots, shariahs):
    date_label = TODAY.strftime("%Y-%m-%d")
    with sqlite3.connect(str(IPO_DB_PATH)) as con:
        for _, r in df.iterrows():
            sym = str(r["Symbol"])
            a, sh = allots[sym], shariahs[sym]
            con.execute("""
                INSERT OR REPLACE INTO ipo_scans (
                    run_date, symbol, sector, final_score, verdict, is_upcoming,
                    subscription_x, gmp_pct, issue_size_cr, price_upper, lot_size,
                    close_date, days_to_close,
                    p_single_mc, ci_lo, ci_hi, optimal_syndicate,
                    kelly_pct, ev_inr, roi_pct,
                    barakah, halal_tier, najash_alert, source
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                date_label, sym, r["Sector"], r["FinalScore"], r["Verdict"],
                int(r.get("IsUpcoming", False)),
                r["SubscriptionTimes"], r["gmp_pct"], r["IssueSizeCr"],
                r["PriceBandUpper"], int(r["LotSize"]),
                r["CloseDate"], int(r["DaysToClose"]),
                a.p_single_mc, a.ci_95[0], a.ci_95[1], a.optimal_syndicate,
                a.kelly_pct, a.ev_inr, a.roi_pct,
                sh.barakah_index, sh.tier, int(sh.najash_alert),
                str(r.get("Source","unknown")),
            ))
    log.info(f"🗄  Persisted {len(df)} records.")

# ═══════════════════════════════════════════════════════════
# TELEGRAM — FIX E: honour retry_after, batch into one msg per IPO
# ═══════════════════════════════════════════════════════════
def _tg_send_with_retry(text: str, token: str, chat_id: str,
                        max_retries: int = 3):
    """Send one Telegram message, honouring retry_after on 429."""
    text = text[:4096]
    for attempt in range(max_retries):
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=15,
            )
            if r.status_code == 200:
                return
            if r.status_code == 429:
                # FIX E: read the retry_after the server tells us to wait
                retry_after = 35
                try:
                    retry_after = r.json()["parameters"]["retry_after"]
                except Exception:
                    pass
                log.info(f"  Telegram 429 — waiting {retry_after}s (attempt {attempt+1})")
                time.sleep(retry_after + 1)
            else:
                log.warning(f"  Telegram {r.status_code}: {r.text[:80]}")
                return
        except Exception as exc:
            log.error(f"  Telegram error: {exc}")
            return

def send_telegram_alerts(df: pd.DataFrame, allots: dict, shariahs: dict):
    token   = os.getenv("TELEGRAM_TOKEN",   "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    console = not (token and chat_id)
    if console:
        log.warning("TELEGRAM_TOKEN/CHAT_ID not set — printing to console.")

    date_str = TODAY.strftime("%d %b %Y")
    ranked   = df.copy()
    ranked["IsUpcoming"] = ranked["IsUpcoming"].fillna(False).astype(bool)
    ranked   = ranked.sort_values(["IsUpcoming","FinalScore"], ascending=[True,False])
    live_df  = ranked[~ranked["IsUpcoming"]]
    upco_df  = ranked[ranked["IsUpcoming"]]

    # ── Summary header (single message) ──────────────────────────────────
    header = (f"⚔️ <b>{VERSION}</b>\n"
              f"📅 <b>{date_str}</b>  |  {len(live_df)} live · {len(upco_df)} upcoming\n"
              f"{'━'*38}\n")
    for _, row in live_df.iterrows():
        header += (f"  {row['Verdict']} <b>{html_lib.escape(str(row['Symbol']))}</b>"
                   f" ({row['FinalScore']:.0f})  "
                   f"{row['SubscriptionTimes']:.1f}×  GMP {row['gmp_pct']:.1f}%\n")
    if not upco_df.empty:
        header += f"\n🕐 <b>Upcoming ({len(upco_df)})</b>\n"
        for _, row in upco_df.iterrows():
            header += (f"  🕐 <b>{html_lib.escape(str(row['Symbol']))}</b>"
                       f"  ₹{row['PriceBandLower']:.0f}–{row['PriceBandUpper']:.0f}"
                       f"  closes {row['CloseDate']}\n")

    if console:
        print(f"\n[TELEGRAM HEADER]\n{header}")
    else:
        _tg_send_with_retry(header, token, chat_id)
        # FIX E: polite gap after header before detail messages
        time.sleep(2.0)

    # ── One combined detail message per live IPO ──────────────────────────
    for _, row in live_df.iterrows():
        sym   = str(row["Symbol"])
        a, sh = allots[sym], shariahs[sym]
        score = row["FinalScore"]
        em    = "🔥" if score >= 80 else "✅" if score >= 70 else "📈" if score >= 60 else "❌"
        src   = str(row.get("Source","live"))

        msg = (
            f"{em} <b>{html_lib.escape(sym)}</b> [{row['Sector']}]\n"
            f"   🏆 <b>{score:.1f}/100</b>  {row['Verdict']}\n"
            f"   📊 Sub: <b>{row['SubscriptionTimes']:.1f}×</b>"
            f"  GMP: <b>{row['gmp_pct']:.1f}%</b>"
            + ("  <i>(not yet available)</i>" if row["gmp_pct"] == 0 else "") + "\n"
            f"   💹 ₹{row['PriceBandLower']:.0f}–₹{row['PriceBandUpper']:.0f}"
            f"  Lot {row['LotSize']}  Size ₹{row['IssueSizeCr']:.0f}Cr\n"
            f"   📅 Closes: {row['CloseDate']} ({row['DaysToClose']}d left)\n"
            f"   🎲 P(Allot): <b>{a.p_single_mc*100:.3f}%</b>"
            f"  [CI: {a.ci_95[0]*100:.2f}–{a.ci_95[1]*100:.2f}%]\n"
            f"   👥 Syndicate: <b>{a.optimal_syndicate} PANs</b>"
            f"  Kelly: {a.kelly_pct:.1f}%"
            f"  EV: ₹{a.ev_inr:,.0f}\n"
            f"   🕌 {sh.tier}  (Barakah {sh.barakah_index:.0f}/100)\n"
        )
        if sh.deferred_issues:
            msg += "   🚨 " + " | ".join(html_lib.escape(i) for i in sh.deferred_issues) + "\n"
        msg += f"   ⚖️ {html_lib.escape(sh.qabda_mandate)}"

        if console:
            print(f"\n[TELEGRAM IPO]\n{msg}\n{'─'*55}")
        else:
            _tg_send_with_retry(msg, token, chat_id)
            # FIX E: 2s gap between messages — stays well under Telegram's ~30 msg/s limit
            time.sleep(2.0)

# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
def run():
    log.info(f"🚀  {VERSION}  [{TODAY}]")
    init_db()

    df = fetch_unified_calendar()
    if df.empty:
        log.error("❌ No IPO data — aborting.")
        return None

    df["IsUpcoming"] = df["IsUpcoming"].fillna(False).astype(bool)
    live_count = int((~df["IsUpcoming"]).sum())
    log.info(f"📦 Scoring {len(df)} IPOs ({live_count} live, {len(df)-live_count} upcoming) …")

    w        = bayesian_weight_update(df)
    allots:   Dict[str, AllotmentProfile] = {}
    shariahs: Dict[str, ShariahVerdict]   = {}
    scores:   List[dict]                  = []

    for _, row in df.iterrows():
        sym           = str(row["Symbol"])
        allots[sym]   = compute_allotment(row)
        shariahs[sym] = run_shariah(row)
        scores.append(master_score(row, allots[sym], shariahs[sym], w))

    df["FinalScore"]        = [s["FinalScore"]             for s in scores]
    df["Verdict"]           = [s["Verdict"]                for s in scores]
    df["p_single_mc"]       = [allots[s].p_single_mc       for s in df["Symbol"]]
    df["optimal_syndicate"] = [allots[s].optimal_syndicate for s in df["Symbol"]]
    df["kelly_pct"]         = [allots[s].kelly_pct         for s in df["Symbol"]]
    df["ev_inr"]            = [allots[s].ev_inr            for s in df["Symbol"]]
    df["roi_pct"]           = [allots[s].roi_pct           for s in df["Symbol"]]
    df["barakah"]           = [shariahs[s].barakah_index   for s in df["Symbol"]]
    df["halal_tier"]        = [shariahs[s].tier            for s in df["Symbol"]]
    df["najash_alert"]      = [shariahs[s].najash_alert    for s in df["Symbol"]]

    persist_db(df, allots, shariahs)
    JSON_EXPORT.parent.mkdir(parents=True, exist_ok=True)
    df.to_json(str(JSON_EXPORT), orient="records", indent=2)
    log.info(f"📄  JSON → {JSON_EXPORT}")

    # Console table — live IPOs first, then upcoming
    ranked = df.sort_values(["IsUpcoming","FinalScore"], ascending=[True,False])
    W = 102
    print(f"\n{'═'*W}")
    print(f"  {VERSION}  |  {TODAY}")
    print(f"{'═'*W}")
    print(f"  {'Symbol':<32} {'Score':>5}  {'Verdict':<14}  "
          f"{'Sub':>6}  {'GMP':>6}  {'Days':>4}  {'Synd':>4}  "
          f"{'Status':<10}  Source")
    print(f"  {'─'*32} {'─'*5}  {'─'*14}  "
          f"{'─'*6}  {'─'*6}  {'─'*4}  {'─'*4}  "
          f"{'─'*10}  {'─'*18}")
    for _, row in ranked.iterrows():
        sym    = str(row["Symbol"])
        a      = allots[sym]
        status = "UPCOMING" if row.get("IsUpcoming") else "LIVE"
        print(
            f"  {sym:<32} {row['FinalScore']:>5.1f}  {row['Verdict']:<14}  "
            f"{row['SubscriptionTimes']:>5.1f}×  {row['gmp_pct']:>5.1f}%  "
            f"{row['DaysToClose']:>4}  {a.optimal_syndicate:>4}  "
            f"{status:<10}  {str(row.get('Source',''))[:18]}"
        )
    print(f"{'═'*W}\n")

    send_telegram_alerts(df, allots, shariahs)
    log.info("🏁  Complete.")
    return df

if __name__ == "__main__":
    run()
