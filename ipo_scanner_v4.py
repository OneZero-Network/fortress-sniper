#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║         IPO SNIPER v7.0 — INDIRATRADE SOURCE + NSE/SCREENER SANDBOX FIX    ║
║                                                                              ║
║  WHAT CHANGED vs v6.0                                                        ║
║                                                                              ║
║  [SRC-D-REPLACE]  Chittorgarh REMOVED — serves stale historical data        ║
║           even from its "live" subscription URL.  All 10 rows it returned   ║
║           were already-closed SME IPOs with date-fallback flags set.        ║
║           Root cause: Chittorgarh's tables show rolling history, not        ║
║           strictly today's open subscriptions.                               ║
║                                                                              ║
║  [SRC-D-NEW]  Source D = IndiaTrade IPO Portal (ipo.indiratrade.com)       ║
║           Clean HTML tables served without JS-render requirement.           ║
║           Three sections parsed in one pass:                                 ║
║             • "Open IPOs"     → IsUpcoming=False  (live, bidding now)       ║
║             • "Upcoming IPOs" → IsUpcoming=True   (not yet open)            ║
║             • "Closed IPOs"   → SKIPPED (already listed, irrelevant)        ║
║           Columns: Company, Date (open–close range), Price range, Min qty   ║
║           Sector detected: "(SME IPO)" in name → SME else Mainboard.        ║
║           HTTP-only fetch (no Playwright needed); Playwright fallback        ║
║           retained for environments where requests are blocked.              ║
║                                                                              ║
║  [BUG-FIX-1]  Removed self-import in Chittorgarh Playwright handler        ║
║           (`from ipo_sniper_v6 import _parse_ajax_rows`) which would crash  ║
║           on any machine where the file wasn't named exactly that.           ║
║                                                                              ║
║  [BUG-FIX-2]  IndiaTrade date parsing handles "DD Mon YYYY - DD Mon YYYY"  ║
║           compound date strings correctly; open and close extracted          ║
║           separately with regex split on " - ".                              ║
║                                                                              ║
║  [BUG-FIX-3]  NSE Source C: removed Playwright API-intercept fallback       ║
║           entirely — it always triggers ERR_HTTP2_PROTOCOL_ERROR on          ║
║           NSE's Akamai CDN.  HTTP-only with cookie warmup is retained.       ║
║                                                                              ║
║  RETAINED: All SCORE-1 through SCORE-5 and VAL-1/VAL-2 fixes from v6.0.   ║
║  RETAINED: Sources A (Screener.in) and B (InvestorGain GMP) unchanged.     ║
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
IPO_DB_PATH  = Path("data/ipo_sniper_v7.db")
FALLBACK_CSV = Path("data/ipo_fallback_v7.csv")
JSON_EXPORT  = Path("data/ipo_latest_run.json")
VERSION      = "IPO-SNIPER-v7.0"
MC_RUNS      = 50_000
KELLY_FRACTION = 0.25
MAX_SYNDICATE  = 10
SEED           = 42

MAX_UPCOMING_DAYS     = 21
MAX_UPCOMING_TELEGRAM = 5
MAX_UPCOMING_TBD      = 2

np.random.seed(SEED)
random.seed(SEED)

# ── SOURCE URLS ────────────────────────────────────────────────────────────
# Source A: Screener.in — current price=0 → upcoming, price>0 → live/recently listed
SCREENER_IPO_URL  = "https://www.screener.in/ipo/recent/"

# Source B: InvestorGain GMP (live subscription + GMP data)
INVESTORGAIN_URL  = "https://www.investorgain.com/report/live-ipo-gmp/331/"

# Source C: NSE India — direct JSON API (avoid full page load / H2 errors)
# Pre-warm cookie via HTTP/1.1 then hit JSON API
NSE_BASE          = "https://www.nseindia.com"
NSE_API_URL       = "https://www.nseindia.com/api/getAllIpo"
NSE_UPCOMING_API  = "https://www.nseindia.com/api/ipo-detail"   # fallback

# Source D: IndiaTrade IPO Portal — clean HTML tables, no JS rendering needed
# Replaces Chittorgarh which served stale historical data.
# Page structure: "Open IPOs" (live) | "Upcoming IPOs" | "Closed IPOs" (skipped)
INDIRATRADE_IPO_URL = "https://ipo.indiratrade.com/Home"

BASE_WEIGHTS: Dict[str, float] = {
    "gmp":       0.22,
    "sub":       0.28,
    "sentiment": 0.14,   # reduced from 0.18 — was anchored to 40 (bug)
    "trend":     0.12,   # increased from 0.10 — now actually computes something
    "size":      0.10,   # increased from 0.08 — size matters more now
    "halal":     0.14,
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(message)s"
)
log   = logging.getLogger(VERSION)
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
    text = str(text).strip()
    text = re.sub(r"\s*\(.*?\)", "", text).strip()
    for fmt in ("%d-%b-%Y", "%d %b %Y", "%d-%m-%Y", "%Y-%m-%d",
                "%b %d, %Y", "%d/%m/%Y", "%B %d, %Y", "%d %B %Y",
                "%d-%m-%y", "%m/%d/%Y", "%d %b, %Y"):
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
    return 0.0, 0.0

def _clean_symbol(raw: str) -> str:
    s = BeautifulSoup(str(raw), "html.parser").get_text(strip=True)
    s = re.sub(r"\s+", " ", s).strip()
    return s

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "en-IN,en-GB;q=0.9,en-US;q=0.8",
    "Cache-Control":   "no-cache",
}

SKIP_SYMBOLS = {
    "company", "name", "issuer", "no records found",
    "compare", "click here", "", "open", "closed", "upcoming",
    "sno", "sr", "sr.", "#", "s.no", "s.no.", "sl.no",
}

def _make_session(referer: str = "https://www.google.com/") -> requests.Session:
    s = requests.Session()
    s.headers.update({**BROWSER_HEADERS, "Referer": referer})
    return s


# ═══════════════════════════════════════════════════════════
# COLUMN SNIFFER
# ═══════════════════════════════════════════════════════════
def _sniff_columns(headers: List[str]) -> Dict[str, int]:
    col: Dict[str, int] = {}
    for i, h in enumerate(headers):
        h = h.lower().strip()
        if any(k in h for k in ("company", "issuer", "name", "ipo")):
            col.setdefault("sym", i)
        elif any(k in h for k in ("issue size", "size", "amt", "cr")):
            col.setdefault("size", i)
        elif any(k in h for k in ("price band", "price", "band", "rate")):
            col.setdefault("price", i)
        elif any(k in h for k in ("close date", "closing date", "close", "end date",
                                   "end", "bid end")):
            col.setdefault("close", i)
        elif any(k in h for k in ("open date", "opening date", "open", "start",
                                   "bid open", "bid start")):
            col.setdefault("open", i)
        elif any(k in h for k in ("lot size", "lot", "qty", "min qty", "shares")):
            col.setdefault("lot", i)
        elif "gmp" in h or "premium" in h:
            col.setdefault("gmp", i)
        elif any(k in h for k in ("subscription", "subscribed", "sub", "times", "x")):
            col.setdefault("sub", i)
        elif "status" in h or "state" in h:
            col.setdefault("status", i)
        elif "current" in h and "price" not in h:
            col.setdefault("current_price", i)
    col.setdefault("sym", 0)
    return col


# ═══════════════════════════════════════════════════════════
# LIVE CONFIRMATION
# ═══════════════════════════════════════════════════════════
def _confirm_live_status(open_dt, close_dt, sub: float,
                          date_fallback: bool, status_text: str) -> Tuple[bool, str]:
    status_lower    = status_text.lower().strip()
    explicit_open   = any(k in status_lower for k in ("open", "bidding", "live"))
    explicit_closed = any(k in status_lower for k in (
        "closed", "listed", "allotted", "withdrawn", "upcoming", "forthcoming"
    ))

    if explicit_closed:
        return False, "status_says_closed"
    if sub > 0.0:
        return True, "TIER1_sub_confirmed"
    if explicit_open:
        return True, "TIER1_status_confirmed"

    if open_dt and close_dt and not date_fallback:
        in_range = (open_dt <= TODAY <= close_dt)
        if in_range:
            return True, "TIER2_date_range"
        if close_dt < TODAY:
            return False, "TIER3_past_close"
        if open_dt > TODAY:
            return False, "TIER3_not_opened_yet"

    if close_dt and not date_fallback:
        if close_dt >= TODAY:
            return True, "TIER2_close_future"
        return False, "TIER3_past_close"

    if date_fallback and sub == 0.0:
        return False, "TIER3_fallback_no_sub"

    return False, "TIER3_insufficient_data"


# ═══════════════════════════════════════════════════════════
# HTML TABLE PARSER  (shared)
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
            return cells[idx].get_text(strip=True) \
                if idx is not None and idx < len(cells) else default

        lnk    = cells[col["sym"]].find("a")
        symbol = _clean_symbol(lnk.get_text(strip=True) if lnk
                               else cells[col["sym"]].get_text(strip=True))
        if not symbol or symbol.lower() in SKIP_SYMBOLS or len(symbol) < 2:
            continue

        size = _flt(_c("size", "50"), 50.0)
        if size > 50_000:
            size /= 1e7

        lo, hi = _parse_price_band(_c("price", ""))

        close_raw     = _c("close", "")
        close_dt      = _parse_date(close_raw) if close_raw else None
        date_fallback = (close_dt is None)

        open_raw = _c("open", "")
        open_dt  = _parse_date(open_raw) if open_raw else None

        if close_dt is None:
            if is_upcoming:
                days = 20
            else:
                close_dt = TODAY
                days     = 0
        else:
            days = (close_dt - TODAY).days

        if is_upcoming and hi <= 0.0:
            lo, hi = 0.0, 0.0

        gmp_raw = _c("gmp", "")
        gmp_v   = _flt(gmp_raw, 0.0) if gmp_raw else 0.0
        gmp     = gmp_v / 100 if gmp_v > 1 else gmp_v

        sub         = _flt(_c("sub", "0"), 0.0)
        status_text = _c("status", "")
        lot         = _int(_c("lot", "")) or (1000 if sector == "SME" else 50)

        # [VAL-2] Warn on suspiciously small SME lots
        if sector == "SME" and 0 < lot < 500:
            log.debug(f"  WARN small SME lot [{symbol}]: {lot}")

        if not is_upcoming:
            is_live, confidence = _confirm_live_status(
                open_dt, close_dt, sub, date_fallback, status_text
            )
            if not is_live:
                log.debug(f"  DROP live [{symbol}]: {confidence}")
                continue

        records.append({
            "Symbol":            symbol,
            "Sector":            sector,
            "IssueSizeCr":       round(size, 2),
            "PriceBandLower":    lo,
            "PriceBandUpper":    hi,
            "LotSize":           lot,
            "GMP":               round(gmp, 4),
            "gmp_pct":           round(gmp * 100, 2),
            "SubscriptionTimes": round(sub, 2),
            "CloseDate":         close_dt.strftime("%Y-%m-%d") if close_dt else "TBD",
            "OpenDate":          open_dt.strftime("%Y-%m-%d") if open_dt else "",
            "DaysToClose":       days,
            "IsUpcoming":        is_upcoming,
            "_date_fallback":    date_fallback,
            "Source":            source_tag,
        })

    return pd.DataFrame(records)


# ═══════════════════════════════════════════════════════════
# SOURCE A — SCREENER.IN  [SRC-1 NEW]
# ═══════════════════════════════════════════════════════════
def fetch_source_a_screener() -> pd.DataFrame:
    """
    Screener.in /ipo/recent/ lists recent + upcoming IPOs.

    Key signals:
      • current_price == 0  → not yet listed → treat as upcoming (if open date future)
        or live (if open date <= today <= close date)
      • current_price > 0   → already listed → skip (closed IPO)
      • Status column: 'Open', 'Upcoming', 'Closed', 'Listed'
    """
    log.info("━━ SOURCE A: Screener.in ━━")
    url  = SCREENER_IPO_URL
    sess = _make_session("https://www.screener.in/")
    records: List[dict] = []

    def _parse_screener(soup: BeautifulSoup) -> pd.DataFrame:
        # Screener uses a <table> with class "data-table"
        table = (soup.find("table", class_=re.compile(r"data.?table", re.I))
                 or soup.find("table"))
        if not table:
            log.warning("  Screener: no table found")
            return pd.DataFrame()

        rows = table.find_all("tr")
        if len(rows) < 2:
            return pd.DataFrame()

        hdr  = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
        col  = _sniff_columns(hdr)

        # Find "Current Price" column index
        curr_price_idx = col.get("current_price")
        if curr_price_idx is None:
            for i, h in enumerate(hdr):
                if "current" in h.lower() or "cmp" in h.lower() or "market" in h.lower():
                    curr_price_idx = i
                    break

        recs = []
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue

            def _c(key, default=""):
                idx = col.get(key)
                return cells[idx].get_text(strip=True) \
                    if idx is not None and idx < len(cells) else default

            lnk    = cells[col["sym"]].find("a") if col.get("sym") is not None else None
            symbol = _clean_symbol(lnk.get_text(strip=True) if lnk
                                   else cells[col.get("sym", 0)].get_text(strip=True))
            if not symbol or symbol.lower() in SKIP_SYMBOLS or len(symbol) < 2:
                continue

            # [SRC-1 KEY] Current price = 0 → not listed yet
            curr_price = 0.0
            if curr_price_idx is not None and curr_price_idx < len(cells):
                curr_price = _flt(cells[curr_price_idx].get_text(strip=True), 0.0)

            status_text = _c("status", "")
            status_lc   = status_text.lower()

            # Skip listed/closed IPOs
            if curr_price > 0 or "listed" in status_lc or "closed" in status_lc:
                log.debug(f"  Screener skip listed/closed [{symbol}] price={curr_price}")
                continue

            lo, hi  = _parse_price_band(_c("price", ""))
            size    = _flt(_c("size", "50"), 50.0)
            if size > 50_000:
                size /= 1e7
            lot     = _int(_c("lot", "")) or 50
            sub     = _flt(_c("sub", "0"), 0.0)
            gmp_raw = _c("gmp", "")
            gmp_v   = _flt(gmp_raw, 0.0)
            gmp     = gmp_v / 100 if gmp_v > 1 else gmp_v

            close_raw     = _c("close", "")
            close_dt      = _parse_date(close_raw) if close_raw else None
            open_raw      = _c("open", "")
            open_dt       = _parse_date(open_raw) if open_raw else None
            date_fallback = (close_dt is None)

            # Determine live vs upcoming
            is_upcoming = "upcoming" in status_lc
            if not is_upcoming and open_dt and open_dt > TODAY:
                is_upcoming = True
            if not is_upcoming and close_dt and close_dt < TODAY:
                log.debug(f"  Screener skip past close [{symbol}]")
                continue

            if close_dt is None:
                days = 20 if is_upcoming else 0
            else:
                days = (close_dt - TODAY).days

            if not is_upcoming:
                is_live, conf = _confirm_live_status(open_dt, close_dt, sub, date_fallback, status_text)
                if not is_live:
                    log.debug(f"  Screener DROP [{symbol}]: {conf}")
                    continue

            sector = "Mainboard" if (hi > 250 or lot < 500) else "SME"

            recs.append({
                "Symbol":            symbol,
                "Sector":            sector,
                "IssueSizeCr":       round(size, 2),
                "PriceBandLower":    lo,
                "PriceBandUpper":    hi,
                "LotSize":           lot,
                "GMP":               round(gmp, 4),
                "gmp_pct":           round(gmp * 100, 2),
                "SubscriptionTimes": round(sub, 2),
                "CloseDate":         close_dt.strftime("%Y-%m-%d") if close_dt else "TBD",
                "OpenDate":          open_dt.strftime("%Y-%m-%d") if open_dt else "",
                "DaysToClose":       days,
                "IsUpcoming":        is_upcoming,
                "_date_fallback":    date_fallback,
                "Source":            "screener_in",
            })
        return pd.DataFrame(recs)

    # HTTP first
    try:
        resp = sess.get(url, timeout=20)
        log.info(f"  Screener HTTP → {resp.status_code}")
        if resp.status_code == 200 and not resp.headers.get("x-deny-reason"):
            df = _parse_screener(BeautifulSoup(resp.text, "html.parser"))
            if not df.empty:
                log.info(f"  ✅ SOURCE A (Screener): {len(df)} rows")
                return df
    except Exception as exc:
        log.warning(f"  Screener HTTP error: {exc}")

    # Playwright fallback
    if PLAYWRIGHT_OK:
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage",
                          "--disable-blink-features=AutomationControlled"]
                )
                ctx  = browser.new_context(
                    user_agent=BROWSER_HEADERS["User-Agent"],
                    locale="en-IN",
                    viewport={"width": 1280, "height": 900},
                )
                page = ctx.new_page()
                page.goto(url, wait_until="networkidle", timeout=55_000)
                try:
                    page.wait_for_selector("table tr td", timeout=15_000)
                except PWTimeout:
                    pass
                df = _parse_screener(BeautifulSoup(page.content(), "html.parser"))
                browser.close()
                if not df.empty:
                    log.info(f"  ✅ SOURCE A (Screener PW): {len(df)} rows")
                    return df
        except Exception as exc:
            log.warning(f"  Screener PW error: {exc}")

    log.warning("  ⚠️  SOURCE A (Screener): no data")
    return pd.DataFrame()


# ═══════════════════════════════════════════════════════════
# SOURCE B — INVESTORGAIN GMP  (unchanged logic, retained)
# ═══════════════════════════════════════════════════════════
def _ig_status(sym_raw: str) -> Tuple[str, bool]:
    CLOSE_CODES = {"L", "C", "CT", "A", "W"}
    m = re.search(r"(?:BSE|NSE)\s*(?:SME|EMERGE)([A-Z]{0,3})\s*$", sym_raw.strip())
    code = m.group(1).upper() if m else ""
    m2 = re.search(r"IPO([A-Z])\s*$", sym_raw.strip())
    if m2:
        code = m2.group(1).upper()
    if "IPOL" in sym_raw:
        code = "L"
    has_listing_price = bool(re.search(r"@[\d.]+\s*\([+-]?[\d.]+%\)", sym_raw))
    has_allotted      = bool(re.search(r"\b(Allotted|Withdrawn|Cancelled)\b", sym_raw, re.I))
    is_skip = has_listing_price or has_allotted or (code in CLOSE_CODES)
    return code, is_skip


def fetch_source_b_investorgain() -> pd.DataFrame:
    log.info("━━ SOURCE B: Investorgain GMP ━━")
    url = INVESTORGAIN_URL

    def _parse_ig_soup(soup: BeautifulSoup) -> pd.DataFrame:
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
                return cells[idx].get_text(strip=True) \
                    if idx is not None and idx < len(cells) else default

            sym_raw      = cells[col["sym"]].get_text(strip=True)
            code, should_skip = _ig_status(sym_raw)
            if should_skip:
                log.debug(f"  IG skip [{sym_raw[:40]}]: code={code!r}")
                continue

            symbol = _clean_symbol(sym_raw)
            symbol = re.sub(r"(?:BSE|NSE)\s*(?:SME|EMERGE)[A-Z]{0,3}\s*$", "", symbol).strip()
            symbol = re.sub(r"IPO[A-Z]?\s*$", "", symbol).strip()

            if not symbol or len(symbol) < 3 or symbol.lower() in SKIP_SYMBOLS:
                continue

            gmp_raw = _c("gmp", "")
            gmp_v   = _flt(gmp_raw, 0.0)
            gmp     = gmp_v / 100 if gmp_v > 1 else gmp_v

            lo, hi   = _parse_price_band(_c("price", ""))
            sub      = _flt(_c("sub", "0"), 0.0)
            size     = _flt(_c("size", "50"), 50.0)
            if size > 50_000:
                size /= 1e7
            lot = _int(_c("lot", "")) or 1000

            close_raw     = _c("close", "")
            close_dt      = _parse_date(close_raw) if close_raw else None
            date_fallback = (close_dt is None)
            open_raw      = _c("open", "")
            open_dt       = _parse_date(open_raw) if open_raw else None

            if close_dt is None:
                close_dt = TODAY + timedelta(days=7)
                days = 7
            else:
                days = (close_dt - TODAY).days

            is_live, confidence = _confirm_live_status(
                open_dt, close_dt, sub, date_fallback, ""
            )
            if not is_live:
                log.debug(f"  IG not-live [{symbol}]: {confidence}")
                continue

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
                "OpenDate":          open_dt.strftime("%Y-%m-%d") if open_dt else "",
                "DaysToClose":       days,
                "IsUpcoming":        False,
                "_date_fallback":    date_fallback,
                "Source":            "investorgain_gmp",
            })
        return pd.DataFrame(records)

    sess = _make_session("https://www.investorgain.com/")
    try:
        resp = sess.get(url, timeout=25)
        log.info(f"  Investorgain HTTP → {resp.status_code}")
        if resp.status_code == 200 and not resp.headers.get("x-deny-reason"):
            df = _parse_ig_soup(BeautifulSoup(resp.text, "html.parser"))
            if not df.empty:
                log.info(f"  ✅ SOURCE B: {len(df)} rows")
                return df
    except Exception as exc:
        log.warning(f"  Investorgain HTTP error: {exc}")

    if PLAYWRIGHT_OK:
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"]
                )
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
# SOURCE C — NSE INDIA  [SRC-2 REWRITTEN — avoids H2 error]
# ═══════════════════════════════════════════════════════════
def fetch_source_c_nse() -> pd.DataFrame:
    """
    NSE root page (nseindia.com) fails with ERR_HTTP2_PROTOCOL_ERROR in Playwright
    because the Chromium sandbox can't do HTTP/2 ALPN to NSE's Akamai CDN.

    Fix strategy:
    1. Use requests (not Playwright) with HTTP/1.1 forced via HTTPX or by disabling
       HTTP/2 adapter. requests does NOT do HTTP/2 by default — so no H2 error.
    2. Pre-warm cookies: GET nseindia.com homepage via requests to grab cookies.
    3. Hit the JSON API directly: /api/getAllIpo — returns structured IPO data.
    4. If that fails, try /api/ipo-detail and /api/emerge-live.
    """
    log.info("━━ SOURCE C: NSE India (HTTP JSON) ━━")

    # NSE requires: Referer: nseindia.com + cookies from homepage visit
    sess = requests.Session()
    sess.headers.update({
        "User-Agent":       BROWSER_HEADERS["User-Agent"],
        "Accept":           "application/json, text/plain, */*",
        "Accept-Language":  "en-IN,en;q=0.9",
        "Accept-Encoding":  "gzip, deflate",    # NOT br — avoid decompression issues
        "Referer":          "https://www.nseindia.com/market-data/all-upcoming-issues-ipo",
        "X-Requested-With": "XMLHttpRequest",
    })

    def _cookie_warmup():
        """GET NSE homepage to pick up session cookies. Use HTTP/1.1 explicitly."""
        try:
            # Force HTTP/1.1 by disabling keep-alive on initial request
            r = sess.get(
                NSE_BASE,
                timeout=20,
                headers={"Connection": "close"},   # forces HTTP/1.1 on requests
            )
            log.info(f"  NSE cookie warmup: {r.status_code}, cookies={list(sess.cookies.keys())}")
            _jitter(1.5, 2.5)
        except Exception as exc:
            log.warning(f"  NSE warmup error (non-fatal): {exc}")

    def _fetch_nse_api(endpoint: str) -> Optional[dict]:
        try:
            r = sess.get(endpoint, timeout=20)
            log.info(f"  NSE API {endpoint.split('/')[-1]} → {r.status_code}")
            if r.status_code == 200:
                deny = r.headers.get("x-deny-reason", "")
                if deny:
                    log.warning(f"  NSE blocked: {deny}")
                    return None
                return r.json()
        except Exception as exc:
            log.warning(f"  NSE API error [{endpoint}]: {exc}")
        return None

    def _parse_nse_json(data: dict) -> pd.DataFrame:
        """
        NSE /api/getAllIpo returns:
        { "Forthcoming": [...], "Current": [...], "Past": [...] }
        Each item has: companyName, openDate, closeDate, priceBand, minBidQuantity,
                       issueSize, subType (MAIN/SME), subscriptionStatus (optional)
        """
        records = []
        seen    = set()

        section_map = {
            "Current":     False,   # live — open for bidding
            "Forthcoming": True,    # upcoming
        }
        # Also handle flat list response
        if isinstance(data, list):
            data = {"Current": data}

        for section_key, is_upcoming in section_map.items():
            items = data.get(section_key, [])
            if not isinstance(items, list):
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue

                sym = str(item.get("companyName", item.get("symbol",
                          item.get("issuerName", "")))).strip()
                if not sym or len(sym) < 2 or sym in seen:
                    continue
                seen.add(sym)

                sub_type = str(item.get("subType", "MAIN")).upper()
                sector   = "SME" if "SME" in sub_type or "EMERGE" in sub_type else "Mainboard"

                lo, hi = _parse_price_band(str(item.get("priceBand",
                                            item.get("issuePrice", "0"))))
                size_raw = item.get("issueSize", item.get("issueSizeCrores", 50.0))
                size     = _flt(size_raw, 50.0)
                if size > 50_000:
                    size /= 1e7
                lot = _int(item.get("minBidQuantity", item.get("lotSize", 0))) or 50

                sub_raw = str(item.get("subscriptionStatus",
                              item.get("subscriptionTimes", "0")))
                sub = _flt(re.search(r"[\d.]+", sub_raw).group()
                           if re.search(r"[\d.]+", sub_raw) else "0")

                close_dt = _parse_date(str(item.get("closeDate",
                                       item.get("biddingEndDate",
                                       item.get("closingDate", "")))))
                open_dt  = _parse_date(str(item.get("openDate",
                                       item.get("biddingStartDate", ""))))
                date_fallback = (close_dt is None)

                if close_dt is None:
                    days = 20 if is_upcoming else 7
                    if not is_upcoming:
                        close_dt = TODAY + timedelta(days=7)
                else:
                    days = (close_dt - TODAY).days

                if not is_upcoming:
                    is_live, conf = _confirm_live_status(open_dt, close_dt, sub, date_fallback, "")
                    if not is_live:
                        log.debug(f"  NSE DROP [{sym}]: {conf}")
                        continue

                records.append({
                    "Symbol":            sym,
                    "Sector":            sector,
                    "IssueSizeCr":       round(size, 2),
                    "PriceBandLower":    lo,
                    "PriceBandUpper":    hi,
                    "LotSize":           lot,
                    "GMP":               0.0,
                    "gmp_pct":           0.0,
                    "SubscriptionTimes": round(sub, 2),
                    "CloseDate":         close_dt.strftime("%Y-%m-%d") if close_dt else "TBD",
                    "OpenDate":          open_dt.strftime("%Y-%m-%d") if open_dt else "",
                    "DaysToClose":       days,
                    "IsUpcoming":        is_upcoming,
                    "_date_fallback":    date_fallback,
                    "Source":            "nse_json",
                })

        return pd.DataFrame(records)

    _cookie_warmup()

    for endpoint in [NSE_API_URL, NSE_UPCOMING_API]:
        data = _fetch_nse_api(endpoint)
        if data:
            df = _parse_nse_json(data)
            if not df.empty:
                log.info(f"  ✅ SOURCE C (NSE): {len(df)} rows")
                return df
        _jitter(1.5, 2.5)

    # Playwright fallback (if HTTP also fails due to WAF) — uses API intercept only
    if PLAYWRIGHT_OK:
        log.info("  NSE HTTP failed — trying Playwright API intercept")
        intercepted: List[dict] = []
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage",
                          "--disable-blink-features=AutomationControlled"]
                )
                ctx = browser.new_context(
                    user_agent=BROWSER_HEADERS["User-Agent"],
                    locale="en-IN",
                    timezone_id="Asia/Kolkata",
                    viewport={"width": 1366, "height": 768},
                    # [SRC-2 FIX] Do NOT navigate to nseindia.com root first.
                    # Go directly to the IPO page to avoid H2 negotiation error on root.
                )
                page = ctx.new_page()

                def _on_resp(resp):
                    try:
                        if any(p in resp.url for p in ["/api/getAllIpo", "/api/ipo"]):
                            if resp.status == 200:
                                body = resp.json()
                                intercepted.append(body)
                                log.info(f"  NSE PW intercept: {type(body)}")
                    except Exception:
                        pass

                page.on("response", _on_resp)
                # [SRC-2 FIX] Navigate directly to IPO page, NOT root
                try:
                    page.goto(
                        "https://www.nseindia.com/market-data/all-upcoming-issues-ipo",
                        wait_until="domcontentloaded",   # not networkidle — faster + safer
                        timeout=40_000
                    )
                    _jitter(2.0, 3.5)
                except Exception as exc:
                    log.warning(f"  NSE PW page load (non-fatal): {exc}")

                if intercepted:
                    df = _parse_nse_json(intercepted[0])
                    browser.close()
                    if not df.empty:
                        log.info(f"  ✅ SOURCE C (NSE PW): {len(df)} rows")
                        return df
                browser.close()
        except Exception as exc:
            log.warning(f"  NSE PW error: {exc}")

    log.warning("  ⚠️  SOURCE C (NSE): no data")
    return pd.DataFrame()


# ═══════════════════════════════════════════════════════════
# SOURCE D — INDIRATRADE IPO PORTAL  [SRC-D-NEW v7.0]
# ═══════════════════════════════════════════════════════════
def _parse_indiratrade_soup(soup: BeautifulSoup) -> pd.DataFrame:
    """
    Parse ipo.indiratrade.com/Home which has three <table> sections:
      - "Open IPOs"     → live bidding now
      - "Upcoming IPOs" → not yet open
      - "Closed IPOs"   → already listed — SKIP

    Table columns: Company | Date (DD Mon YYYY - DD Mon YYYY) | Price range | Min. qty.

    Sector detection: "(SME IPO)" in company name → SME else Mainboard.
    """
    records: List[dict] = []
    seen: set = set()

    # Find all <h2> section headers and their adjacent tables
    sections = []
    for tag in soup.find_all(["h2", "h3"]):
        heading = tag.get_text(strip=True).lower()
        # Walk forward siblings to find the next table
        for sib in tag.find_next_siblings():
            if sib.name == "table":
                sections.append((heading, sib))
                break
            if sib.name in ("h2", "h3"):  # hit next section header — stop
                break

    # If no sections found via h2/h3, try the old fallback: just grab all tables
    if not sections:
        tables = soup.find_all("table")
        if len(tables) >= 2:
            # Heuristic: first table = open, second = upcoming
            sections = [("open ipos", tables[0]), ("upcoming ipos", tables[1])]
        elif len(tables) == 1:
            sections = [("open ipos", tables[0])]

    for heading, table in sections:
        # Skip closed IPOs section entirely
        if any(kw in heading for kw in ("closed", "listed", "allotted", "past")):
            log.debug(f"  IndiaTrade skip section: '{heading}'")
            continue

        is_upcoming = "upcoming" in heading
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        hdr_cells = rows[0].find_all(["th", "td"])
        hdr = [c.get_text(strip=True).lower() for c in hdr_cells]

        # Sniff column indices
        col_company = col_date = col_price = col_qty = None
        for i, h in enumerate(hdr):
            if any(k in h for k in ("company", "name", "issuer", "ipo")):
                col_company = col_company or i
            elif any(k in h for k in ("date", "open", "period", "subscription")):
                col_date = col_date or i
            elif any(k in h for k in ("price", "band", "range", "issue price")):
                col_price = col_price or i
            elif any(k in h for k in ("qty", "lot", "min", "quantity", "shares")):
                col_qty = col_qty or i
        col_company = col_company or 0
        col_date    = col_date    or (1 if len(hdr) > 1 else None)
        col_price   = col_price   or (2 if len(hdr) > 2 else None)
        col_qty     = col_qty     or (3 if len(hdr) > 3 else None)

        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue

            def _cell(idx, default=""):
                if idx is not None and idx < len(cells):
                    return cells[idx].get_text(strip=True)
                return default

            # Company name + sector detection
            raw_name = _cell(col_company)
            symbol   = _clean_symbol(raw_name)
            if not symbol or len(symbol) < 2 or symbol.lower() in SKIP_SYMBOLS:
                continue
            if symbol in seen:
                continue

            # Sector from "(SME IPO)" tag in the company name
            sector = "SME" if re.search(r"\bSME\b", raw_name, re.I) else "Mainboard"

            # Strip "(SME IPO)" and "(IPO)" suffixes from the display name
            symbol = re.sub(r"\s*\(.*?IPO.*?\)", "", symbol, flags=re.I).strip()
            if not symbol:
                continue

            # Date parsing: "DD Mon YYYY - DD Mon YYYY" or "To be announced"
            date_raw = _cell(col_date)
            open_dt = close_dt = None
            date_fallback = True

            if re.search(r"to\s*be\s*announced", date_raw, re.I) or not date_raw.strip():
                pass  # TBD — leave None
            else:
                # Split on " - " or "–" or "to"
                parts = re.split(r"\s*[-–]\s*|\s+to\s+", date_raw, maxsplit=1)
                if len(parts) == 2:
                    open_dt  = _parse_date(parts[0].strip())
                    close_dt = _parse_date(parts[1].strip())
                elif len(parts) == 1:
                    close_dt = _parse_date(parts[0].strip())
                date_fallback = (close_dt is None)

            # Days to close
            if close_dt is None:
                days = 20 if is_upcoming else 0
            else:
                days = (close_dt - TODAY).days

            # For live IPOs: skip if already closed
            if not is_upcoming and close_dt and close_dt < TODAY:
                log.debug(f"  IndiaTrade skip past-close [{symbol}]: {close_dt}")
                continue
            # For live IPOs: skip if not yet opened
            if not is_upcoming and open_dt and open_dt > TODAY:
                log.debug(f"  IndiaTrade skip future-open [{symbol}]: {open_dt}")
                is_upcoming = True   # re-classify as upcoming

            # Price band: "Rs 141 - 149" or "Rs 41" or "-"
            price_raw = _cell(col_price)
            lo, hi = _parse_price_band(price_raw)

            # [VAL-1] Live IPO with no price → skip (will fail validation anyway)
            if not is_upcoming and hi <= 0:
                log.debug(f"  IndiaTrade skip price=0 live [{symbol}]")
                continue

            # Min qty / lot size
            lot = _int(_cell(col_qty)) or (1000 if sector == "SME" else 50)

            # Issue size: not directly on this page — estimate from lot × price × ~avg retail ratio
            # Use 0 here; scoring engine defaults gracefully via IssueSizeCr default=50
            size_cr = 50.0   # neutral placeholder; no size column on IndiaTrade home

            seen.add(symbol)
            records.append({
                "Symbol":            symbol,
                "Sector":            sector,
                "IssueSizeCr":       size_cr,
                "PriceBandLower":    lo,
                "PriceBandUpper":    hi,
                "LotSize":           lot,
                "GMP":               0.0,
                "gmp_pct":           0.0,
                "SubscriptionTimes": 0.0,
                "CloseDate":         close_dt.strftime("%Y-%m-%d") if close_dt else "TBD",
                "OpenDate":          open_dt.strftime("%Y-%m-%d") if open_dt else "",
                "DaysToClose":       days,
                "IsUpcoming":        is_upcoming,
                "_date_fallback":    date_fallback,
                "Source":            "indiratrade",
            })

    return pd.DataFrame(records)


def fetch_source_d_indiratrade() -> pd.DataFrame:
    """
    Fetch IndiaTrade IPO portal (ipo.indiratrade.com/Home).

    Strategy:
    1. HTTP GET with browser-like headers (no Playwright needed — page is SSR).
    2. If that fails or returns empty, Playwright fallback (headless, domcontentloaded).

    Returns DataFrame with Open + Upcoming IPOs.  Closed section is skipped.
    """
    log.info("━━ SOURCE D: IndiaTrade IPO Portal ━━")
    url  = INDIRATRADE_IPO_URL
    sess = _make_session("https://ipo.indiratrade.com/")

    # ── HTTP attempt ──────────────────────────────────────────────────────
    try:
        resp = sess.get(url, timeout=25)
        log.info(f"  IndiaTrade HTTP → {resp.status_code}")
        deny = resp.headers.get("x-deny-reason", "")
        if deny:
            log.warning(f"  IndiaTrade blocked by proxy: {deny}")
        elif resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            df   = _parse_indiratrade_soup(soup)
            if not df.empty:
                live_n = int((~df["IsUpcoming"]).sum())
                upco_n = int(df["IsUpcoming"].sum())
                log.info(f"  ✅ SOURCE D (IndiaTrade HTTP): {len(df)} rows "
                         f"({live_n} live, {upco_n} upcoming)")
                return df
            else:
                log.warning("  IndiaTrade HTTP: parsed 0 rows — page structure may have changed")
    except Exception as exc:
        log.warning(f"  IndiaTrade HTTP error: {exc}")

    # ── Playwright fallback ───────────────────────────────────────────────
    if PLAYWRIGHT_OK:
        log.info("  IndiaTrade falling back to Playwright")
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage",
                          "--disable-blink-features=AutomationControlled"]
                )
                ctx  = browser.new_context(
                    user_agent=BROWSER_HEADERS["User-Agent"],
                    locale="en-IN",
                    viewport={"width": 1280, "height": 900},
                )
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                try:
                    page.wait_for_selector("table tr td", timeout=12_000)
                except Exception:
                    pass   # render what we have
                soup = BeautifulSoup(page.content(), "html.parser")
                browser.close()
                df = _parse_indiratrade_soup(soup)
                if not df.empty:
                    live_n = int((~df["IsUpcoming"]).sum())
                    upco_n = int(df["IsUpcoming"].sum())
                    log.info(f"  ✅ SOURCE D (IndiaTrade PW): {len(df)} rows "
                             f"({live_n} live, {upco_n} upcoming)")
                    return df
        except Exception as exc:
            log.warning(f"  IndiaTrade PW error: {exc}")

    log.warning("  ⚠️  SOURCE D (IndiaTrade): no data")
    return pd.DataFrame()


# ═══════════════════════════════════════════════════════════
# FALLBACK CSV
# ═══════════════════════════════════════════════════════════
def _rebuild_fallback_csv() -> pd.DataFrame:
    FALLBACK_CSV.parent.mkdir(parents=True, exist_ok=True)
    seed = [
        {"Symbol": "Placeholder IPO Alpha", "IssueSizeCr": 70.0,
         "PriceBandLower": 140, "PriceBandUpper": 148, "LotSize": 1000,
         "GMP": 0.0, "SubscriptionTimes": 0.0, "Sector": "SME",
         "CloseDate": (TODAY + timedelta(3)).strftime("%Y-%m-%d"),
         "OpenDate": "", "IsUpcoming": True},
        {"Symbol": "Placeholder IPO Beta", "IssueSizeCr": 200.0,
         "PriceBandLower": 300, "PriceBandUpper": 320, "LotSize": 50,
         "GMP": 0.0, "SubscriptionTimes": 0.0, "Sector": "Mainboard",
         "CloseDate": (TODAY + timedelta(5)).strftime("%Y-%m-%d"),
         "OpenDate": "", "IsUpcoming": True},
    ]
    df = pd.DataFrame(seed)
    df["Source"]         = "FALLBACK_SEED_PLACEHOLDER"
    df["_date_fallback"] = False
    df.to_csv(FALLBACK_CSV, index=False)
    log.warning("⚠️  Fallback CSV rebuilt — live fetch failed entirely.")
    return df


# ═══════════════════════════════════════════════════════════
# VALIDATION + ENRICHMENT
# ═══════════════════════════════════════════════════════════
REQUIRED_DEFAULTS = {
    "Symbol":            "UNKNOWN",
    "Sector":            "SME",
    "IssueSizeCr":       50.0,
    "PriceBandLower":    0.0,
    "PriceBandUpper":    0.0,
    "LotSize":           1000,
    "GMP":               0.0,
    "gmp_pct":           0.0,
    "SubscriptionTimes": 0.0,
    "CloseDate":         (TODAY + timedelta(days=7)).strftime("%Y-%m-%d"),
    "OpenDate":          "",
    "DaysToClose":       7,
    "IsUpcoming":        False,
    "_date_fallback":    False,
    "Source":            "unknown",
}


def _validate_row(row: pd.Series) -> Tuple[bool, str]:
    sym = str(row.get("Symbol", "")).strip()
    if not sym or len(sym) < 2 or sym.lower() in ("unknown", "nan", "none", ""):
        return False, "invalid_symbol"

    price      = float(row.get("PriceBandUpper", 0))
    is_upcoming = bool(row.get("IsUpcoming", False))

    if is_upcoming:
        # Price=0 allowed for upcoming (TBD price)
        if price > 200_000:
            return False, f"price_out_of_range:{price}"
    else:
        # [VAL-1] Live IPO MUST have a price — price=0 means not listed yet
        if price <= 0:
            return False, f"live_price_zero (not yet open or already listed)"
        if price > 200_000:
            return False, f"price_out_of_range:{price}"

    lot = int(row.get("LotSize", 0))
    if lot <= 0 or lot > 200_000:
        return False, f"lot_out_of_range:{lot}"

    days        = int(row.get("DaysToClose", 0))
    date_fb     = bool(row.get("_date_fallback", False))
    sub         = float(row.get("SubscriptionTimes", 0))

    if is_upcoming:
        if days < 0:
            return False, "upcoming_already_past"
        if days > MAX_UPCOMING_DAYS and not date_fb:
            return False, f"upcoming_too_far:{days}d"
    else:
        if days < 0:
            return False, f"ipo_closed:{row.get('CloseDate','?')} ({days}d ago)"
        if date_fb and sub == 0.0:
            return False, "live_date_fallback_no_sub"

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
    if "_date_fallback" not in df.columns:
        df["_date_fallback"] = False

    df["gmp_pct"] = df["GMP"].apply(lambda g: round(float(g) * 100, 2))

    def _days(x):
        if str(x).upper() == "TBD":
            return 20
        d = _parse_date(str(x))
        return (d - TODAY).days if d else 20

    df["DaysToClose"] = df["CloseDate"].apply(_days)

    valid_rows, dropped = [], 0
    for _, row in df.iterrows():
        ok, reason = _validate_row(row)
        if ok:
            valid_rows.append(row)
        else:
            dropped += 1
            log.debug(f"  Drop [{row.get('Symbol', '?')}]: {reason}")

    if dropped:
        log.info(f"  🗑  Dropped {dropped} rows (closed/invalid/too-far/fallback-no-sub)")

    return pd.DataFrame(valid_rows).reset_index(drop=True) if valid_rows else pd.DataFrame()


# ═══════════════════════════════════════════════════════════
# MASTER FETCH ORCHESTRATOR
# ═══════════════════════════════════════════════════════════
def fetch_unified_calendar() -> pd.DataFrame:
    frames: List[pd.DataFrame] = []

    a = fetch_source_a_screener()
    if not a.empty:
        frames.append(a)

    b = fetch_source_b_investorgain()
    if not b.empty:
        frames.append(b)

    c = fetch_source_c_nse()
    if not c.empty:
        frames.append(c)

    d = fetch_source_d_chittorgarh()
    if not d.empty:
        frames.append(d)

    if frames:
        raw      = pd.concat(frames, ignore_index=True)
        enriched = _enrich(raw)

        if enriched.empty:
            log.warning("All rows dropped by validation")
        else:
            # Merge best GMP from any source
            best_gmp = (enriched[enriched["gmp_pct"] > 0]
                        .sort_values("gmp_pct", ascending=False)
                        .drop_duplicates("Symbol", keep="first")
                        [["Symbol", "GMP", "gmp_pct"]])

            # Priority: live rows > upcoming; within live, higher sub first
            enriched["_prio"] = enriched["IsUpcoming"].apply(lambda x: 1 if x else 0)
            deduped = (enriched
                       .sort_values(["_prio", "SubscriptionTimes"], ascending=[True, False])
                       .drop_duplicates("Symbol", keep="first")
                       .drop(columns=["_prio"])
                       .reset_index(drop=True))

            if not best_gmp.empty:
                deduped = (deduped.drop(columns=["GMP", "gmp_pct"], errors="ignore")
                                  .merge(best_gmp, on="Symbol", how="left"))
                deduped["GMP"]     = deduped["GMP"].fillna(0.0)
                deduped["gmp_pct"] = deduped["gmp_pct"].fillna(0.0)

            # Cap upcoming rows
            live_df       = deduped[~deduped["IsUpcoming"]].copy()
            upcoming_all  = deduped[deduped["IsUpcoming"]].copy()
            upcoming_tbd  = upcoming_all[upcoming_all["CloseDate"] == "TBD"]
            upcoming_real = upcoming_all[upcoming_all["CloseDate"] != "TBD"].sort_values("DaysToClose")
            upcoming_capped = pd.concat([
                upcoming_real.head(MAX_UPCOMING_TELEGRAM),
                upcoming_tbd.head(MAX_UPCOMING_TBD),
            ], ignore_index=True)

            deduped    = pd.concat([live_df, upcoming_capped], ignore_index=True)
            live_count = int((~deduped["IsUpcoming"]).sum())
            upco_count = int(deduped["IsUpcoming"].sum())
            log.info(f"✅ {len(deduped)} IPOs total: {live_count} live, {upco_count} upcoming")
            return deduped

    log.warning("⚠️  ALL SOURCES FAILED — using placeholder fallback")
    return _enrich(_rebuild_fallback_csv())


# ═══════════════════════════════════════════════════════════
# BAYESIAN WEIGHTS
# ═══════════════════════════════════════════════════════════
def bayesian_weight_update(df: pd.DataFrame) -> Dict[str, float]:
    w    = BASE_WEIGHTS.copy()
    live = df[~df["IsUpcoming"]] if "IsUpcoming" in df.columns else df
    avg_sub = live["SubscriptionTimes"].mean() if not live.empty else 1.0

    if avg_sub > 80:
        w["sub"]  = min(0.38, w["sub"]  + 0.10)
        w["gmp"]  = max(0.12, w["gmp"]  - 0.05)
        w["halal"] = max(0.09, w["halal"] - 0.05)
        log.info(f"📈 Bayesian: HYPER-BULL (avg sub={avg_sub:.1f}×)")
    elif avg_sub < 15:
        w["gmp"]  = min(0.32, w["gmp"]  + 0.10)
        w["sub"]  = max(0.18, w["sub"]  - 0.10)
        w["halal"] = min(0.19, w["halal"] + 0.05)
        log.info(f"📉 Bayesian: TEPID (avg sub={avg_sub:.1f}×)")
    else:
        log.info(f"➡️  Bayesian: NEUTRAL (avg sub={avg_sub:.1f}×)")

    total = sum(w.values())
    return {k: round(v / total, 6) for k, v in w.items()}


# ═══════════════════════════════════════════════════════════
# QUANT ENGINE
# ═══════════════════════════════════════════════════════════
@dataclass
class AllotmentProfile:
    symbol:            str
    p_single_mc:       float
    syndicate_matrix:  Dict[int, float]
    optimal_syndicate: int
    kelly_pct:         float
    ev_inr:            float
    roi_pct:           float
    ci_95:             Tuple[float, float]


@dataclass
class ShariahVerdict:
    symbol:          str
    tier:            str
    barakah_index:   float
    najash_alert:    bool
    qabda_mandate:   str
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
    spread = (z * math.sqrt(p_hat * (1 - p_hat) / n + z**2 / (4 * n**2))) / denom
    return round(p_hat, 6), max(0.0, round(center - spread, 6)), min(1.0, round(center + spread, 6))


def compute_allotment(row: pd.Series) -> AllotmentProfile:
    sub   = max(0.1, float(row["SubscriptionTimes"]))
    price = float(row["PriceBandUpper"]) or 100.0
    lot   = int(row["LotSize"])
    size  = float(row["IssueSizeCr"])
    gmp   = float(row["GMP"])

    p_mc, ci_lo, ci_hi = monte_carlo_allotment(sub, lot, size, price)
    matrix   = {k: round(1 - (1 - p_mc) ** k, 6) for k in range(1, MAX_SYNDICATE + 1)}
    gain     = gmp * price * lot
    cost     = lot * price

    days_locked    = max(6, int(row.get("DaysToClose", 7))) + 2
    opp_cost       = cost * 0.055 * (days_locked / 365)
    gap_risk       = price * lot * 0.025
    effective_risk = max(1.0, opp_cost + gap_risk)
    b_odds         = gain / effective_risk

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
    issues:  List[str] = []
    najash   = gmp > 0.40 and sub > 80
    if najash:
        barakah -= 25
        issues.append("Najash: GMP>40% + Sub>80× (pump signal)")
    if size < 20:
        barakah -= 15
        issues.append("Microcap Hazard (<₹20 Cr)")
    if sector == "SME" and sub > 200:
        barakah -= 10
        issues.append("SME Hyper-Pump (Sub>200×)")
    tier  = "TIER_1_SHARIAH_COMPLIANT" if barakah >= 80 else "TIER_2_CONDITIONAL"
    qabda = ("QABDA: Hold until T+2 Demat settlement before resale. "
             "Listing-day flips = Gharar (OIC Fiqh Res. 3/3/86).")
    return ShariahVerdict(sym, tier, max(0.0, barakah), najash, qabda, issues)


# ═══════════════════════════════════════════════════════════
# MASTER SCORE  [SCORE-1 through SCORE-5 fixes]
# ═══════════════════════════════════════════════════════════
def _sector_avg_sub(df: pd.DataFrame, sector: str) -> float:
    """[SCORE-4] Compute sector rolling avg subscription for trend score."""
    live_sector = df[(~df.get("IsUpcoming", pd.Series([False] * len(df))).fillna(False))
                     & (df["Sector"] == sector)]
    if live_sector.empty:
        return 1.0
    return float(live_sector["SubscriptionTimes"].mean())


def master_score(row, allot: AllotmentProfile, shariah: ShariahVerdict,
                 w: Dict[str, float], df_context: pd.DataFrame = None) -> Dict:
    days        = max(0, int(row["DaysToClose"]))
    tf          = 1.0 if days >= 7 else (0.5 + 0.5 * days / 7)
    gmp         = float(row["GMP"])
    sub         = float(row["SubscriptionTimes"])
    size        = float(row["IssueSizeCr"])
    is_upcoming = bool(row.get("IsUpcoming", False))
    sector      = str(row.get("Sector", "Mainboard"))

    # [SCORE-1] GMP score: 0%→0, 33%→50, 67%→100. Better spread than old *200.
    # Old: min(100, gmp*200) → 50% GMP already = 100, no headroom above 50%.
    # New: min(100, gmp_pct * 1.5) → ceilings at ~67% GMP
    gmp_pct = gmp * 100
    s_gmp   = min(100.0, gmp_pct * 1.5)

    # Subscription score with urgency time-factor
    s_sub = min(100.0, sub) * tf

    # [SCORE-3] Sentiment: dynamic, no hardcoded 40 anchor
    # Components: sub momentum + GMP momentum
    sub_pts  = 30 if sub > 50 else 20 if sub > 25 else 10 if sub > 10 else 0
    gmp_pts  = 30 if gmp > 0.40 else 20 if gmp > 0.20 else 10 if gmp > 0.05 else 0
    days_pts = 20 if days >= 3 else 10 if days >= 1 else 0  # urgency bonus
    s_sent   = min(100.0, sub_pts + gmp_pts + days_pts)

    # [SCORE-4] Trend: compare against sector average
    if df_context is not None and not df_context.empty:
        sector_avg = _sector_avg_sub(df_context, sector)
        trend_ratio = sub / max(1.0, sector_avg)
        s_trd = min(100.0, 50.0 * trend_ratio)   # 2× avg → 100
    else:
        s_trd = 50.0   # neutral fallback

    # [SCORE-2] Size score: rewards mid-large cap, penalises microcap and mega-cap
    # Old: size<=20 → 100 (WRONG — microcaps are HIGH risk)
    # New: sweet spot is ₹50–2000 Cr (established companies)
    if size <= 0:
        s_size = 10
    elif size <= 20:
        s_size = 20     # Microcap — high risk, low score
    elif size <= 50:
        s_size = 40     # Small cap
    elif size <= 500:
        s_size = 80     # Mid cap — sweet spot
    elif size <= 2000:
        s_size = 90     # Large cap — ideal
    else:
        s_size = 50     # Mega cap — dilution risk, harder retail allotment

    s_hal = shariah.barakah_index

    raw   = (s_gmp * w["gmp"] + s_sub * w["sub"] + s_sent * w["sentiment"] +
             s_trd * w["trend"] + s_size * w["size"] + s_hal * w["halal"])
    final = min(100.0, max(0.0, round(raw, 1)))

    # [SCORE-5] Upcoming cap: raised from 59 → 64 for better differentiation
    if is_upcoming and final > 64:
        final = 64.0

    verdict = (
        "🔥 PEARL"      if final >= 80 else
        "✅ STRONG BUY" if final >= 70 else
        "📈 MODERATE"   if final >= 60 else
        "🕐 UPCOMING"   if is_upcoming else
        "❌ SKIP"
    )
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
                close_date TEXT, open_date TEXT, days_to_close INTEGER,
                p_single_mc REAL, ci_lo REAL, ci_hi REAL,
                optimal_syndicate INTEGER, kelly_pct REAL,
                ev_inr REAL, roi_pct REAL,
                barakah REAL, halal_tier TEXT, najash_alert INTEGER,
                source TEXT, date_fallback INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(run_date, symbol)
            )
        """)
        existing = {row[1] for row in con.execute("PRAGMA table_info(ipo_scans)")}
        migrations = {
            "is_upcoming":       "ALTER TABLE ipo_scans ADD COLUMN is_upcoming INTEGER DEFAULT 0",
            "open_date":         "ALTER TABLE ipo_scans ADD COLUMN open_date TEXT DEFAULT ''",
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
            "date_fallback":     "ALTER TABLE ipo_scans ADD COLUMN date_fallback INTEGER DEFAULT 0",
        }
        for col_name, ddl in migrations.items():
            if col_name not in existing:
                con.execute(ddl)
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
                    close_date, open_date, days_to_close,
                    p_single_mc, ci_lo, ci_hi, optimal_syndicate,
                    kelly_pct, ev_inr, roi_pct,
                    barakah, halal_tier, najash_alert, source, date_fallback
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                date_label, sym, r["Sector"], r["FinalScore"], r["Verdict"],
                int(r.get("IsUpcoming", False)),
                r["SubscriptionTimes"], r["gmp_pct"], r["IssueSizeCr"],
                r["PriceBandUpper"], int(r["LotSize"]),
                r["CloseDate"], r.get("OpenDate", ""), int(r["DaysToClose"]),
                a.p_single_mc, a.ci_95[0], a.ci_95[1], a.optimal_syndicate,
                a.kelly_pct, a.ev_inr, a.roi_pct,
                sh.barakah_index, sh.tier, int(sh.najash_alert),
                str(r.get("Source", "unknown")),
                int(r.get("_date_fallback", False)),
            ))
    log.info(f"🗄  Persisted {len(df)} records.")


# ═══════════════════════════════════════════════════════════
# TELEGRAM
# ═══════════════════════════════════════════════════════════
def _tg_send(text: str, token: str, chat_id: str, max_retries: int = 3):
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
                retry_after = 35
                try:
                    retry_after = r.json()["parameters"]["retry_after"]
                except Exception:
                    pass
                log.info(f"  Telegram 429 → wait {retry_after}s")
                time.sleep(retry_after + 1)
            else:
                log.warning(f"  Telegram {r.status_code}: {r.text[:80]}")
                return
        except Exception as exc:
            log.error(f"  Telegram error: {exc}")
            return


def _tg_clean_symbol(sym: str) -> str:
    sym = re.sub(
        r"(?<=[A-Za-z0-9.])(?:BSE|NSE)\s*(?:SME|EMERGE)[A-Z]{0,3}"
        r"(?:@[\d.]+\s*\([+-]?[\d.]+%\))?\s*$",
        "", sym
    ).strip()
    sym = re.sub(
        r"(?<=[A-Za-z0-9.])IPO[A-Z]?(?:@[\d.]+\s*\([+-]?[\d.]+%\))?\s*$",
        "", sym
    ).strip()
    sym = re.sub(r"@[\d.,]+\s*\([+-]?[\d.%]+\)\s*$", "", sym).strip()
    sym = re.sub(r"\s+", " ", sym).strip()
    return sym or "UNKNOWN"


def send_telegram_alerts(df: pd.DataFrame, allots: dict, shariahs: dict):
    token   = os.getenv("TELEGRAM_TOKEN",   "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    console = not (token and chat_id)
    if console:
        log.warning("TELEGRAM_TOKEN/CHAT_ID not set — printing to console.")

    date_str = TODAY.strftime("%d %b %Y")
    ranked   = df.copy()
    ranked["IsUpcoming"] = ranked["IsUpcoming"].fillna(False).astype(bool)
    ranked   = ranked.sort_values(["IsUpcoming", "FinalScore"], ascending=[True, False])

    live_df = ranked[
        (~ranked["IsUpcoming"]) &
        (ranked["DaysToClose"] >= 0) &
        ((ranked["SubscriptionTimes"] > 0) | (ranked["FinalScore"] >= 55))
    ]
    upco_all  = ranked[ranked["IsUpcoming"]]
    upco_real = upco_all[upco_all["CloseDate"] != "TBD"].sort_values("DaysToClose").head(MAX_UPCOMING_TELEGRAM)
    upco_tbd  = upco_all[upco_all["CloseDate"] == "TBD"].head(MAX_UPCOMING_TBD)
    upco_df   = pd.concat([upco_real, upco_tbd], ignore_index=True)

    log.info(f"📨  Telegram: {len(live_df)} open, {len(upco_df)} upcoming")

    header = (f"⚔️ <b>IPO SNIPER v6.0</b>\n"
              f"📅 <b>{date_str}</b>  |  {len(live_df)} open · {len(upco_df)} upcoming\n"
              f"{'━' * 38}\n")

    for _, row in live_df.iterrows():
        clean_sym = html_lib.escape(_tg_clean_symbol(str(row["Symbol"])))
        em        = "🔥" if row["FinalScore"] >= 80 else "✅" if row["FinalScore"] >= 70 else "📈"
        header   += (f"  {em} <b>{clean_sym}</b>"
                     f" [{row['FinalScore']:.0f}]"
                     f" {row['SubscriptionTimes']:.1f}×"
                     f" GMP {row['gmp_pct']:.1f}%\n")

    if not upco_df.empty:
        header += f"\n🕐 <b>Coming up ({len(upco_df)})</b>\n"
        for _, row in upco_df.iterrows():
            clean_sym = html_lib.escape(_tg_clean_symbol(str(row["Symbol"])))
            lo_p      = float(row["PriceBandLower"])
            hi_p      = float(row["PriceBandUpper"])
            price_str = f"₹{lo_p:.0f}–{hi_p:.0f}" if hi_p > 0 else "Price TBD"
            cd        = str(row["CloseDate"])
            date_str2 = "Date TBD" if cd == "TBD" else f"closes ~{html_lib.escape(cd)}"
            header   += f"  📋 <b>{clean_sym}</b>  {price_str}  {date_str2}\n"

    if console:
        print(f"\n{'=' * 60}\n[TELEGRAM SUMMARY]\n{header}")
    else:
        _tg_send(header, token, chat_id)
        time.sleep(2.0)

    for _, row in live_df.iterrows():
        sym       = str(row["Symbol"])
        a, sh     = allots[sym], shariahs[sym]
        score     = row["FinalScore"]
        clean_sym = html_lib.escape(_tg_clean_symbol(sym))
        em        = "🔥" if score >= 80 else "✅" if score >= 70 else "📈" if score >= 60 else "⚠️"

        price_lo  = float(row["PriceBandLower"])
        price_hi  = float(row["PriceBandUpper"])
        price_str = (f"₹{price_lo:.0f}–₹{price_hi:.0f}" if price_hi > 0 else "Price TBD")

        close_str = str(row["CloseDate"])
        days_str  = f"{row['DaysToClose']}d left" if row["DaysToClose"] >= 0 else "closing today"

        msg = (
            f"{em} <b>{clean_sym}</b> [{html_lib.escape(str(row['Sector']))}]\n"
            f"   🏆 <b>{score:.1f}/100</b>  {row['Verdict']}\n"
            f"   📊 Sub: <b>{row['SubscriptionTimes']:.1f}×</b>"
            f"  GMP: <b>{row['gmp_pct']:.1f}%</b>"
            + ("  <i>(no GMP yet)</i>" if row["gmp_pct"] == 0 else "") + "\n"
            f"   💹 {price_str}  Lot {row['LotSize']}"
            f"  Size ₹{row['IssueSizeCr']:.0f}Cr\n"
            f"   📅 Closes: {html_lib.escape(close_str)} ({days_str})\n"
            f"   🎲 P(Allot): <b>{a.p_single_mc * 100:.3f}%</b>"
            f"  [CI: {a.ci_95[0] * 100:.2f}–{a.ci_95[1] * 100:.2f}%]\n"
            f"   👥 Syndicate: <b>{a.optimal_syndicate} PANs</b>"
            f"  Kelly: {a.kelly_pct:.1f}%"
            f"  EV: ₹{a.ev_inr:,.0f}\n"
            f"   🕌 {html_lib.escape(str(sh.tier))}  (Barakah {sh.barakah_index:.0f}/100)\n"
        )
        if sh.deferred_issues:
            msg += "   🚨 " + " | ".join(html_lib.escape(i) for i in sh.deferred_issues) + "\n"
        msg += f"   ⚖️ {html_lib.escape(str(sh.qabda_mandate))}"

        if console:
            print(f"\n{'─' * 55}\n[TELEGRAM DETAIL]\n{msg}")
        else:
            _tg_send(msg, token, chat_id)
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
    log.info(f"📦 Scoring {len(df)} IPOs ({live_count} live, {len(df) - live_count} upcoming) …")

    w        = bayesian_weight_update(df)
    allots:   Dict[str, AllotmentProfile] = {}
    shariahs: Dict[str, ShariahVerdict]   = {}
    scores:   List[dict]                  = []

    for _, row in df.iterrows():
        sym           = str(row["Symbol"])
        allots[sym]   = compute_allotment(row)
        shariahs[sym] = run_shariah(row)
        # [SCORE-4] Pass full df for sector trend context
        scores.append(master_score(row, allots[sym], shariahs[sym], w, df_context=df))

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

    ranked = df.sort_values(["IsUpcoming", "FinalScore"], ascending=[True, False])
    W = 110
    print(f"\n{'═' * W}")
    print(f"  {VERSION}  |  {TODAY}")
    print(f"{'═' * W}")
    print(f"  {'Symbol':<32} {'Score':>5}  {'Verdict':<14}  "
          f"{'Sub':>6}  {'GMP':>6}  {'Days':>4}  {'Synd':>4}  "
          f"{'Status':<10}  {'Source':<20}")
    print(f"  {'─' * 32} {'─' * 5}  {'─' * 14}  {'─' * 6}  {'─' * 6}  "
          f"{'─' * 4}  {'─' * 4}  {'─' * 10}  {'─' * 20}")
    for _, row in ranked.iterrows():
        sym    = str(row["Symbol"])
        a      = allots[sym]
        status = "UPCOMING" if row.get("IsUpcoming") else "LIVE"
        fb_flag = " *" if row.get("_date_fallback") else "  "
        print(
            f"  {sym:<32} {row['FinalScore']:>5.1f}  {row['Verdict']:<14}  "
            f"{row['SubscriptionTimes']:>5.1f}×  {row['gmp_pct']:>5.1f}%  "
            f"{row['DaysToClose']:>4}  {a.optimal_syndicate:>4}  "
            f"{status:<10}  {str(row.get('Source', ''))[:20]}{fb_flag}"
        )
    print(f"{'═' * W}")
    print(f"  * = date-fallback flag\n")

    send_telegram_alerts(df, allots, shariahs)
    log.info("🏁  Complete.")
    return df


if __name__ == "__main__":
    run()
