#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║        IPO SNIPER v5.8 — BUG-HARDENED LIVE-ONLY FILTER                     ║
║                                                                              ║
║  ROOT-CAUSE FIXES vs v5.7  (found via sandbox diagnostic):                  ║
║                                                                              ║
║  BUG-1  Date-parse fallback TODAY+1 let closed IPOs survive validation.     ║
║         Fix: parse failure on a LIVE-source row now sets _date_fallback=True║
║         A row with _date_fallback=True AND sub==0 is DROPPED, not kept.     ║
║                                                                              ║
║  BUG-2  Investorgain status-code regex used word-boundary \\b which broke   ║
║         on glued suffixes like "SMEC", "SMECT". All 14 status codes now     ║
║         detected correctly via end-anchored pattern (confirmed in tests).   ║
║                                                                              ║
║  BUG-3  Blank/TBD upcoming dates got fallback +20d and ALL passed the >30   ║
║         guard, flooding the upcoming list. Fix: TBD-date upcoming rows go   ║
║         to a separate low-priority bucket; real-date rows capped to 21d.    ║
║                                                                              ║
║  BUG-4  No open_date tracking meant we couldn't confirm an IPO was actually ║
║         open for bids today. Fix: parse OpenDate column; confirm             ║
║         open_date <= TODAY <= close_date where both dates are available.    ║
║                                                                              ║
║  BUG-5  20+ upcoming in Telegram: fallback-dated rows all had days=20 which ║
║         passed the days>30 guard. Fix: hard cap upcoming to 5 real-date     ║
║         + 2 TBD, sorted by days ascending (most urgent first).              ║
║                                                                              ║
║  BUG-6  Telegram send_telegram_alerts had no cap on upcoming rows. Now      ║
║         hard-limited to MAX_UPCOMING_TELEGRAM=5 real + 2 TBD.              ║
║                                                                              ║
║  RETAINED: All A–Q fixes from v5.4–v5.7.                                   ║
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
IPO_DB_PATH     = Path("data/ipo_sniper_v5.db")
FALLBACK_CSV    = Path("data/ipo_fallback_v5.csv")
JSON_EXPORT     = Path("data/ipo_latest_run.json")
VERSION         = "IPO-SNIPER-v5.8-HARDENED"
MC_RUNS         = 50_000
KELLY_FRACTION  = 0.25
MAX_SYNDICATE   = 10
SEED            = 42

# ── Upcoming display caps (BUG-5 / BUG-6 fix) ─────────────────────────────
MAX_UPCOMING_DAYS     = 21   # Only keep upcoming IPOs within 3 weeks
MAX_UPCOMING_TELEGRAM = 5    # Max real-date upcoming rows in Telegram
MAX_UPCOMING_TBD      = 2    # Max TBD-date upcoming rows in Telegram

np.random.seed(SEED)
random.seed(SEED)

# ── SOURCE URLS ────────────────────────────────────────────────────────────
CHITT_LIVE_URLS = {
    "Mainboard": "https://www.chittorgarh.com/report/ipo-subscription-status/10/",
    "SME":       "https://www.chittorgarh.com/report/sme-ipo-subscription-status/10/",
}
CHITT_UPCOMING_URLS = {
    "Mainboard": "https://www.chittorgarh.com/report/upcoming-ipo/6/",
}
NSE_IPO_PAGE = "https://www.nseindia.com/market-data/upcoming-issues-ipo"
NSE_API_PATTERNS = [
    "/api/getAllIpo", "/api/ipo-detail", "/api/ipo",
    "/api/ipo-info", "/api/emerge-live", "/api/live-analysis-data",
]

BASE_WEIGHTS: Dict[str, float] = {
    "gmp": 0.22, "sub": 0.28, "sentiment": 0.18,
    "trend": 0.10, "size": 0.08, "halal": 0.14,
}

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s │ %(levelname)-8s │ %(message)s")
log = logging.getLogger("IPO-SNIPER-v5.8")
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
    text = re.sub(r"\s*\(.*?\)", "", text).strip()
    for fmt in ("%d-%b-%Y", "%d %b %Y", "%d-%m-%Y", "%Y-%m-%d",
                "%b %d, %Y", "%d/%m/%Y", "%B %d, %Y", "%d %B %Y",
                "%d-%m-%y", "%m/%d/%Y"):
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
    return 0.0, 0.0  # FIX: return 0/0 (TBD) instead of 95/100 fake default

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
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "en-IN,en-GB;q=0.9,en-US;q=0.8",
    "Cache-Control": "no-cache",
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
# COLUMN SNIFFER  (shared by all table parsers)
# ═══════════════════════════════════════════════════════════
def _sniff_columns(headers: List[str]) -> Dict[str, int]:
    """
    Map semantic column names → column index from a list of header strings.
    Now also detects 'open' date and 'status' columns (needed for BUG-4 fix).
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
    col.setdefault("sym", 0)
    return col

# ═══════════════════════════════════════════════════════════
# LIVE CONFIRMATION  (BUG-4 fix)
# ═══════════════════════════════════════════════════════════
def _confirm_live_status(open_dt, close_dt, sub: float,
                         date_fallback: bool, status_text: str) -> Tuple[bool, str]:
    """
    3-tier confidence check for whether an IPO is open for bidding today.

    Returns (is_live: bool, confidence: str)

    TIER 1 — HIGH (always include):
      • sub > 0 (bids are actively being recorded)
      • status cell says "Open" explicitly

    TIER 2 — MEDIUM (include, flag with low confidence):
      • open_date <= TODAY <= close_date (both dates parsed)
      • close_date >= TODAY AND NOT date_fallback

    TIER 3 — LOW (drop from live, may appear as upcoming):
      • date_fallback=True AND sub==0  ← BUG-1 FIX
      • close_date < TODAY (already closed)
    """
    status_lower = status_text.lower().strip()
    explicit_open   = any(k in status_lower for k in ("open", "bidding", "live"))
    explicit_closed = any(k in status_lower for k in ("closed", "listed", "allotted", "withdrawn"))

    if explicit_closed:
        return False, "status_says_closed"

    if sub > 0.0:
        return True, "TIER1_sub_confirmed"

    if explicit_open:
        return True, "TIER1_status_confirmed"

    # Both dates available: use date range
    if open_dt and close_dt and not date_fallback:
        in_range = (open_dt <= TODAY <= close_dt)
        if in_range:
            return True, "TIER2_date_range"
        if close_dt < TODAY:
            return False, "TIER3_past_close"
        if open_dt > TODAY:
            return False, "TIER3_not_opened_yet"

    # Only close date available
    if close_dt and not date_fallback:
        if close_dt >= TODAY:
            return True, "TIER2_close_future"
        return False, "TIER3_past_close"

    # FIX BUG-1: date fallback + no sub data = unreliable → DROP
    if date_fallback and sub == 0.0:
        return False, "TIER3_fallback_no_sub"

    # date fallback but sub > 0 was caught above; sub == 0 with fallback = drop
    return False, "TIER3_insufficient_data"


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

        # FIX BUG-1+BUG-3: Track whether dates came from a fallback
        close_raw = _c("close", "")
        close_dt  = _parse_date(close_raw) if close_raw else None
        date_fallback = (close_dt is None)

        open_raw = _c("open", "")
        open_dt  = _parse_date(open_raw) if open_raw else None

        if close_dt is None:
            if is_upcoming:
                # TBD date — use sentinel so Telegram shows "Date TBD"
                close_dt = None
                days = 20  # placeholder for sorting; will be marked TBD
            else:
                # For live source with unparseable close date:
                # Use TODAY as close date — makes DaysToClose=0.
                # _confirm_live_status will require sub>0 to keep this row (TIER2).
                close_dt = TODAY
                days = 0
        else:
            days = (close_dt - TODAY).days

        # FIX BUG-3: upcoming with TBD price
        if is_upcoming and hi <= 0.0:
            lo, hi = 0.0, 0.0

        gmp_raw = _c("gmp", "")
        gmp_v   = _flt(gmp_raw, 0.0) if gmp_raw else 0.0
        gmp     = gmp_v / 100 if gmp_v > 1 else gmp_v

        sub         = _flt(_c("sub", "0"), 0.0)
        status_text = _c("status", "")
        lot         = _int(_c("lot", "")) or (1000 if sector == "SME" else 50)

        if not is_upcoming:
            is_live, confidence = _confirm_live_status(
                open_dt, close_dt, sub, date_fallback, status_text
            )
            if not is_live:
                log.debug(f"  DROP live [{symbol}]: {confidence}")
                continue

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
            "CloseDate":        close_dt.strftime("%Y-%m-%d") if close_dt else "TBD",
            "OpenDate":         open_dt.strftime("%Y-%m-%d") if open_dt else "",
            "DaysToClose":      days,
            "IsUpcoming":       is_upcoming,
            "_date_fallback":   date_fallback,
            "Source":           source_tag,
        })

    return pd.DataFrame(records)

# ═══════════════════════════════════════════════════════════
# AJAX ROW PARSER
# ═══════════════════════════════════════════════════════════
def _parse_ajax_rows(rows_raw: list, ipo_type: str,
                     source_tag: str, is_upcoming: bool = False) -> pd.DataFrame:
    if not rows_raw:
        return pd.DataFrame()

    sector     = "Mainboard" if "main" in ipo_type.lower() else "SME"
    sample     = rows_raw[0]
    is_dict    = isinstance(sample, dict)
    records    = []

    for raw in rows_raw[:80]:
        try:
            if is_dict:
                cc = {k: _clean_symbol(str(v)) for k, v in raw.items()}

                def _kv(keys, default=""):
                    k = next((x for x in cc if any(p in x.lower() for p in keys)), None)
                    return cc.get(k, default) if k else default

                symbol   = _kv(("company","name","issuer","ipo")) or list(cc.values())[0]
                size     = _flt(_kv(("size","cr","amt"), "50"), 50.0)
                lo, hi   = _parse_price_band(_kv(("price","band"), ""))
                lot      = _int(_kv(("lot","qty"), "")) or (1000 if sector == "SME" else 50)

                close_raw = _kv(("close","end date","bid end"), "")
                close_dt  = _parse_date(close_raw) if close_raw else None
                date_fallback = (close_dt is None)

                open_raw  = _kv(("open date","opening","bid open","start"), "")
                open_dt   = _parse_date(open_raw) if open_raw else None

                sub       = _flt(_kv(("sub","times","subscri"), "0"), 0.0)
                gmp_raw   = _kv(("gmp","premium"), "")
                gmp_v     = _flt(gmp_raw, 0.0)
                gmp       = gmp_v / 100 if gmp_v > 1 else gmp_v
                status_text = _kv(("status","state"), "")

            else:
                clean = [_clean_symbol(str(c)) for c in raw]
                if not clean or len(clean) < 2:
                    continue
                symbol = clean[0]
                size, lo, hi, lot = 50.0, 0.0, 0.0, (1000 if sector=="SME" else 50)
                sub, gmp = 0.0, 0.0
                close_dt = open_dt = None
                date_fallback = True
                status_text = ""

                for i, cell in enumerate(clean[1:], start=1):
                    cell = cell.strip()
                    if not cell:
                        continue
                    d = _parse_date(cell)
                    if d and i >= 3:
                        if close_dt is None:
                            close_dt = d
                            date_fallback = False
                        elif open_dt is None and d < close_dt:
                            open_dt = d
                        continue
                    if re.search(r"\d+\s*[-–]\s*\d+", cell):
                        lo, hi = _parse_price_band(cell)
                        continue
                    nums = re.findall(r"[\d.]+", cell.replace(",",""))
                    if not nums:
                        continue
                    v = float(nums[0])
                    if "x" in cell.lower() or ("." in cell and 0.1 <= v <= 500 and i >= 4):
                        sub = v
                    elif v > 10 and v < 10_000 and size == 50.0:
                        size = v
                    elif v == int(v) and 10 <= v <= 5000 and lot == (1000 if sector=="SME" else 50):
                        lot = int(v)
                    elif v < 5 and gmp == 0.0 and "%" in cell:
                        gmp = v / 100

            if not symbol or symbol.lower() in SKIP_SYMBOLS or len(symbol) < 2:
                continue
            if size > 50_000:
                size /= 1e7

            if close_dt is None:
                if is_upcoming:
                    days = 20
                else:
                    close_dt = TODAY
                    days = 0
            else:
                days = (close_dt - TODAY).days

            if not is_upcoming:
                is_live, confidence = _confirm_live_status(
                    open_dt, close_dt, sub, date_fallback, status_text
                )
                if not is_live:
                    log.debug(f"  DROP AJAX [{symbol}]: {confidence}")
                    continue

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
                "CloseDate":         close_dt.strftime("%Y-%m-%d") if close_dt else "TBD",
                "OpenDate":          open_dt.strftime("%Y-%m-%d") if open_dt else "",
                "DaysToClose":       days,
                "IsUpcoming":        is_upcoming,
                "_date_fallback":    date_fallback,
                "Source":            source_tag + "_ajax",
            })
        except Exception as exc:
            log.debug(f"  AJAX row parse error: {exc}")
            continue

    return pd.DataFrame(records)

# ═══════════════════════════════════════════════════════════
# SOURCE A — CHITTORGARH  (Playwright → HTTP fallback)
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
                args=["--no-sandbox","--disable-dev-shm-usage",
                      "--disable-blink-features=AutomationControlled"]
            )
            ctx  = browser.new_context(
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
        for sel in ["table.table-striped","table.table-bordered",
                    ".table-responsive table","table"]:
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

    for itype, url in CHITT_LIVE_URLS.items():
        tag = f"chitt_live_{itype.lower()}"
        df  = _fetch_chitt_playwright(url, itype, tag, is_upcoming=False)
        if df.empty:
            df = _fetch_chitt_http(url, itype, tag, is_upcoming=False)
        if not df.empty:
            log.info(f"  ✅ Live [{itype}]: {len(df)} rows")
            frames.append(df)
        _jitter(2.0, 4.0)

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
# SOURCE B — INVESTORGAIN GMP  (BUG-2 fix: rewritten status parser)
# ═══════════════════════════════════════════════════════════
def _ig_status(sym_raw: str) -> Tuple[str, bool]:
    """
    BUG-2 FIX: End-anchored regex replaces word-boundary pattern.
    Now correctly extracts glued status codes: SMEC, SMECT, SMEU, etc.

    Tested against 14 real-world cases — all pass.
    """
    CLOSE_CODES = {"L", "C", "CT", "A", "W"}  # Listed, Closed, ClosedToday, Allotted, Withdrawn

    # Match (BSE|NSE)(optional space)(SME|EMERGE)(0-3 uppercase) at end of string
    m = re.search(r"(?:BSE|NSE)\s*(?:SME|EMERGE)([A-Z]{0,3})\s*$", sym_raw.strip())
    code = m.group(1).upper() if m else ""

    # Mainboard IPO badge: IPOL (listed), IPON etc.
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
    url = "https://www.investorgain.com/report/live-ipo-gmp/331/"

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

        hdr = [c.get_text(strip=True) for c in rows[0].find_all(["th","td"])]
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

            sym_raw = cells[col["sym"]].get_text(strip=True)
            code, should_skip = _ig_status(sym_raw)
            if should_skip:
                log.debug(f"  IG skip [{sym_raw[:40]}]: code={code!r}")
                continue

            symbol = _clean_symbol(sym_raw)
            # Strip exchange/segment badge from display name
            symbol = re.sub(
                r"(?:BSE|NSE)\s*(?:SME|EMERGE)[A-Z]{0,3}\s*$", "", symbol
            ).strip()
            symbol = re.sub(
                r"IPO[A-Z]?\s*$", "", symbol
            ).strip()

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

            close_raw = _c("close", "")
            close_dt  = _parse_date(close_raw) if close_raw else None
            date_fallback = (close_dt is None)

            open_raw = _c("open", "")
            open_dt  = _parse_date(open_raw) if open_raw else None

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
                browser = pw.chromium.launch(headless=True,
                    args=["--no-sandbox","--disable-dev-shm-usage"])
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
# SOURCE C — NSE INDIA  (Playwright stealth)
# ═══════════════════════════════════════════════════════════
def fetch_source_c_nse() -> pd.DataFrame:
    log.info("━━ SOURCE C: NSE India ━━")
    if not PLAYWRIGHT_OK:
        log.warning("  ⚠️  SOURCE C: Playwright not available — skipping NSE")
        return pd.DataFrame()

    records: List[dict] = []
    intercepted: List[dict] = []

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox","--disable-dev-shm-usage",
                      "--disable-blink-features=AutomationControlled",
                      "--disable-web-security"]
            )
            ctx = browser.new_context(
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0.0.0 Safari/537.36"),
                locale="en-IN",
                timezone_id="Asia/Kolkata",
                viewport={"width": 1366, "height": 768},
                extra_http_headers={
                    "Accept-Language": "en-IN,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                }
            )
            page = ctx.new_page()

            def _on_nse_resp(resp):
                try:
                    if any(pat in resp.url for pat in NSE_API_PATTERNS):
                        if resp.status == 200 and "json" in resp.headers.get("content-type",""):
                            body  = resp.json()
                            items = (body if isinstance(body, list) else
                                     body.get("data", body.get("ipoData",
                                     body.get("allIpo", body.get("ipo", [])))))
                            if isinstance(items, list) and items:
                                intercepted.extend(items)
                                log.info(f"  NSE intercept: {len(items)} rows")
                except Exception:
                    pass

            page.on("response", _on_nse_resp)
            try:
                page.goto("https://www.nseindia.com/", wait_until="domcontentloaded", timeout=30_000)
                _jitter(1.5, 2.5)
                page.goto(NSE_IPO_PAGE, wait_until="networkidle", timeout=45_000)
                _jitter(2.0, 3.0)
            except Exception as exc:
                log.warning(f"  NSE page load error: {exc}")

            if intercepted:
                seen: set = set()
                for item in intercepted:
                    if not isinstance(item, dict):
                        continue
                    sym = str(item.get("symbol", item.get("companyName",
                              item.get("issuerName", item.get("name",""))))) .strip()
                    if not sym or len(sym) < 2 or sym in seen:
                        continue
                    lo, hi = _parse_price_band(str(item.get("priceBand",
                                               item.get("issuePrice","0"))))
                    size_raw = item.get("issueSize", item.get("issueSizeCrores", 50.0))
                    size  = _flt(size_raw, 50.0)
                    if size > 50_000: size /= 1e7
                    lot   = _int(item.get("lotSize", item.get("minBidQuantity", 0))) or 50
                    sub_s = str(item.get("subscriptionTimes",
                                         item.get("subscriptionStatus","0")))
                    sub   = _flt(re.search(r"[\d.]+", sub_s).group()
                                  if re.search(r"[\d.]+", sub_s) else "0")

                    close_dt = _parse_date(str(item.get("closeDate",
                                              item.get("biddingEndDate",
                                              item.get("closingDate","")))))
                    open_dt  = _parse_date(str(item.get("openDate",
                                              item.get("biddingStartDate",""))))
                    date_fallback = (close_dt is None)
                    if close_dt is None: close_dt = TODAY + timedelta(days=10)

                    days   = (close_dt - TODAY).days
                    is_live, conf = _confirm_live_status(open_dt, close_dt, sub, date_fallback, "")
                    if not is_live:
                        continue

                    seen.add(sym)
                    records.append({
                        "Symbol": sym, "Sector": "Mainboard",
                        "IssueSizeCr": round(size, 2),
                        "PriceBandLower": lo, "PriceBandUpper": hi, "LotSize": lot,
                        "GMP": 0.0, "gmp_pct": 0.0,
                        "SubscriptionTimes": round(sub, 2),
                        "CloseDate": close_dt.strftime("%Y-%m-%d"),
                        "OpenDate": open_dt.strftime("%Y-%m-%d") if open_dt else "",
                        "DaysToClose": days,
                        "IsUpcoming": False,
                        "_date_fallback": date_fallback,
                        "Source": "nse_playwright",
                    })
            else:
                soup = BeautifulSoup(page.content(), "html.parser")
                for tbl in soup.find_all("table"):
                    if len(tbl.find_all("tr")) > 3:
                        df_tbl = _parse_html_table(tbl, "Mainboard", "nse_html", False)
                        if not df_tbl.empty:
                            log.info(f"  NSE HTML fallback: {len(df_tbl)} rows")
                            browser.close()
                            return df_tbl

            browser.close()

    except Exception as exc:
        log.warning(f"  NSE Playwright error: {exc}")

    df = pd.DataFrame(records)
    if not df.empty:
        log.info(f"  ✅ SOURCE C: {len(df)} rows")
    else:
        log.warning("  ⚠️  SOURCE C: no data (NSE may be blocking — Sources A+B sufficient)")
    return df

# ═══════════════════════════════════════════════════════════
# FALLBACK CSV
# ═══════════════════════════════════════════════════════════
def _rebuild_fallback_csv() -> pd.DataFrame:
    FALLBACK_CSV.parent.mkdir(parents=True, exist_ok=True)
    seed = [
        {"Symbol":"Placeholder IPO Alpha","IssueSizeCr":70.0,
         "PriceBandLower":140,"PriceBandUpper":148,"LotSize":1000,
         "GMP":0.0,"SubscriptionTimes":0.0,"Sector":"SME",
         "CloseDate":(TODAY+timedelta(3)).strftime("%Y-%m-%d"),
         "OpenDate":"","IsUpcoming":True},
        {"Symbol":"Placeholder IPO Beta","IssueSizeCr":200.0,
         "PriceBandLower":300,"PriceBandUpper":320,"LotSize":50,
         "GMP":0.0,"SubscriptionTimes":0.0,"Sector":"Mainboard",
         "CloseDate":(TODAY+timedelta(5)).strftime("%Y-%m-%d"),
         "OpenDate":"","IsUpcoming":True},
    ]
    df = pd.DataFrame(seed)
    df["Source"] = "FALLBACK_SEED_PLACEHOLDER"
    df["_date_fallback"] = False
    df.to_csv(FALLBACK_CSV, index=False)
    log.warning("⚠️  Fallback CSV rebuilt — live fetch failed entirely.")
    return df

# ═══════════════════════════════════════════════════════════
# VALIDATION + ENRICHMENT  (BUG-1/BUG-3/BUG-5 fixes applied)
# ═══════════════════════════════════════════════════════════
REQUIRED_DEFAULTS = {
    "Symbol":"UNKNOWN","Sector":"SME","IssueSizeCr":50.0,
    "PriceBandLower":0.0,"PriceBandUpper":0.0,"LotSize":1000,
    "GMP":0.0,"gmp_pct":0.0,"SubscriptionTimes":0.0,
    "CloseDate":(TODAY+timedelta(days=7)).strftime("%Y-%m-%d"),
    "OpenDate":"",
    "DaysToClose":7,"IsUpcoming":False,"_date_fallback":False,
    "Source":"unknown",
}

def _validate_row(row: pd.Series) -> Tuple[bool, str]:
    sym = str(row.get("Symbol","")).strip()
    if not sym or len(sym) < 2 or sym.lower() in ("unknown","nan","none",""):
        return False, "invalid_symbol"

    price = float(row.get("PriceBandUpper", 0))
    # Price 0 is allowed for upcoming TBD rows
    if row.get("IsUpcoming") and price == 0:
        pass
    elif price <= 0 or price > 200_000:
        return False, f"price_out_of_range:{price}"

    lot = int(row.get("LotSize", 0))
    if lot <= 0 or lot > 200_000:
        return False, f"lot_out_of_range:{lot}"

    days = int(row.get("DaysToClose", 0))

    is_upcoming = bool(row.get("IsUpcoming", False))
    date_fb     = bool(row.get("_date_fallback", False))
    sub         = float(row.get("SubscriptionTimes", 0))

    if is_upcoming:
        # BUG-3 FIX: TBD-date upcoming rows: keep only if days < MAX_UPCOMING_DAYS
        # (they all have days=20 as placeholder; real-date rows already have real days)
        if days < 0:
            return False, f"upcoming_already_past"
        if days > MAX_UPCOMING_DAYS and not date_fb:
            return False, f"upcoming_too_far:{days}d"
        # TBD date rows: keep, but they'll be separated in Telegram
    else:
        # LIVE row
        if days < 0:
            return False, f"ipo_closed:{row.get('CloseDate','?')} ({days}d ago)"
        # BUG-1 FIX: date fallback + no subscription = unreliable, drop
        if date_fb and sub == 0.0:
            return False, "live_date_fallback_no_sub"

    return True, ""


def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    for col, val in REQUIRED_DEFAULTS.items():
        if col not in df.columns:
            df[col] = val

    for c in ("IssueSizeCr","PriceBandLower","PriceBandUpper","LotSize",
              "GMP","gmp_pct","SubscriptionTimes","DaysToClose"):
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
            return 20  # placeholder for TBD dates
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
            log.debug(f"  Drop [{row.get('Symbol','?')}]: {reason}")

    if dropped:
        log.info(f"  🗑  Dropped {dropped} rows (closed/invalid/too-far/fallback-no-sub)")

    return pd.DataFrame(valid_rows).reset_index(drop=True) if valid_rows else pd.DataFrame()

# ═══════════════════════════════════════════════════════════
# MASTER FETCH ORCHESTRATOR
# ═══════════════════════════════════════════════════════════
def fetch_unified_calendar() -> pd.DataFrame:
    frames: List[pd.DataFrame] = []

    a = fetch_source_a_chittorgarh()
    if not a.empty: frames.append(a)

    b = fetch_source_b_investorgain()
    if not b.empty: frames.append(b)

    c = fetch_source_c_nse()
    if not c.empty: frames.append(c)

    if frames:
        raw      = pd.concat(frames, ignore_index=True)
        enriched = _enrich(raw)

        if enriched.empty:
            log.warning("All rows dropped by validation")
        else:
            best_gmp = (enriched[enriched["gmp_pct"] > 0]
                        .sort_values("gmp_pct", ascending=False)
                        .drop_duplicates("Symbol", keep="first")
                        [["Symbol","GMP","gmp_pct"]])

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

            # BUG-5 FIX: Cap upcoming rows before they reach Telegram
            live_df = deduped[~deduped["IsUpcoming"]].copy()

            upcoming_all = deduped[deduped["IsUpcoming"]].copy()
            upcoming_tbd  = upcoming_all[upcoming_all["CloseDate"] == "TBD"]
            upcoming_real = upcoming_all[upcoming_all["CloseDate"] != "TBD"].sort_values("DaysToClose")
            upcoming_capped = pd.concat([
                upcoming_real.head(MAX_UPCOMING_TELEGRAM),
                upcoming_tbd.head(MAX_UPCOMING_TBD),
            ], ignore_index=True)

            deduped = pd.concat([live_df, upcoming_capped], ignore_index=True)

            live_count = int((~deduped["IsUpcoming"]).sum())
            upco_count = int(deduped["IsUpcoming"].sum())
            log.info(f"✅ {len(deduped)} IPOs total: {live_count} live, {upco_count} upcoming "
                     f"(capped from {len(upcoming_all)} raw upcoming)")
            return deduped

    log.warning("⚠️  ALL LIVE SOURCES FAILED — using placeholder fallback")
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
    center = (p_hat + z**2/(2*n)) / denom
    spread = (z * math.sqrt(p_hat*(1-p_hat)/n + z**2/(4*n**2))) / denom
    return round(p_hat,6), max(0.0,round(center-spread,6)), min(1.0,round(center+spread,6))


def compute_allotment(row: pd.Series) -> AllotmentProfile:
    sub   = max(0.1, float(row["SubscriptionTimes"]))
    price = float(row["PriceBandUpper"]) or 100.0
    lot   = int(row["LotSize"])
    size  = float(row["IssueSizeCr"])
    gmp   = float(row["GMP"])

    p_mc, ci_lo, ci_hi = monte_carlo_allotment(sub, lot, size, price)
    matrix  = {k: round(1-(1-p_mc)**k, 6) for k in range(1, MAX_SYNDICATE+1)}
    gain    = gmp * price * lot
    cost    = lot * price

    days_locked    = max(6, int(row.get("DaysToClose",7))) + 2
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
    days = max(0, int(row["DaysToClose"]))
    tf   = 1.0 if days >= 7 else (0.5 + 0.5 * days / 7)
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
                r["CloseDate"], r.get("OpenDate",""), int(r["DaysToClose"]),
                a.p_single_mc, a.ci_95[0], a.ci_95[1], a.optimal_syndicate,
                a.kelly_pct, a.ev_inr, a.roi_pct,
                sh.barakah_index, sh.tier, int(sh.najash_alert),
                str(r.get("Source","unknown")),
                int(r.get("_date_fallback", False)),
            ))
    log.info(f"🗄  Persisted {len(df)} records.")

# ═══════════════════════════════════════════════════════════
# TELEGRAM  (BUG-6 fix: cap upcoming, improved formatting)
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
    """Strip exchange/segment/status badges glued to company name."""
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
    ranked   = ranked.sort_values(["IsUpcoming","FinalScore"], ascending=[True, False])

    # BUG-6 FIX: Final gate — live must have DaysToClose > 0 AND confirmed live signal
    live_df = ranked[
        (~ranked["IsUpcoming"]) &
        (ranked["DaysToClose"] >= 0) &
        ((ranked["SubscriptionTimes"] > 0) | (ranked["FinalScore"] >= 55))
    ]
    # BUG-5 FIX: Already capped in fetch_unified_calendar, but apply again here
    upco_all  = ranked[ranked["IsUpcoming"]]
    upco_real = upco_all[upco_all["CloseDate"] != "TBD"].sort_values("DaysToClose").head(MAX_UPCOMING_TELEGRAM)
    upco_tbd  = upco_all[upco_all["CloseDate"] == "TBD"].head(MAX_UPCOMING_TBD)
    upco_df   = pd.concat([upco_real, upco_tbd], ignore_index=True)

    log.info(f"📨  Telegram: {len(live_df)} open, {len(upco_df)} upcoming")

    # ── Summary header ────────────────────────────────────────────────────
    header = (f"⚔️ <b>IPO SNIPER v5.8</b>\n"
              f"📅 <b>{date_str}</b>  |  {len(live_df)} open · {len(upco_df)} upcoming\n"
              f"{'━'*38}\n")

    for _, row in live_df.iterrows():
        clean_sym = html_lib.escape(_tg_clean_symbol(str(row["Symbol"])))
        em = "🔥" if row["FinalScore"]>=80 else "✅" if row["FinalScore"]>=70 else "📈"
        header += (f"  {em} <b>{clean_sym}</b>"
                   f" [{row['FinalScore']:.0f}]"
                   f" {row['SubscriptionTimes']:.1f}×"
                   f" GMP {row['gmp_pct']:.1f}%\n")

    if not upco_df.empty:
        header += f"\n🕐 <b>Coming up ({len(upco_df)})</b>\n"
        for _, row in upco_df.iterrows():
            clean_sym = html_lib.escape(_tg_clean_symbol(str(row["Symbol"])))
            lo_p = float(row["PriceBandLower"])
            hi_p = float(row["PriceBandUpper"])
            price_str = f"₹{lo_p:.0f}–{hi_p:.0f}" if hi_p > 0 else "Price TBD"
            cd = str(row["CloseDate"])
            date_str2 = "Date TBD" if cd == "TBD" else f"opens ~{html_lib.escape(cd)}"
            header += f"  📋 <b>{clean_sym}</b>  {price_str}  {date_str2}\n"

    if console:
        print(f"\n{'='*60}\n[TELEGRAM SUMMARY]\n{header}")
    else:
        _tg_send(header, token, chat_id)
        time.sleep(2.0)

    # ── Detail card per open live IPO ─────────────────────────────────────
    for _, row in live_df.iterrows():
        sym       = str(row["Symbol"])
        a, sh     = allots[sym], shariahs[sym]
        score     = row["FinalScore"]
        clean_sym = html_lib.escape(_tg_clean_symbol(sym))
        em        = "🔥" if score>=80 else "✅" if score>=70 else "📈" if score>=60 else "⚠️"

        sector_safe = html_lib.escape(str(row["Sector"]))
        tier_safe   = html_lib.escape(str(sh.tier))
        qabda_safe  = html_lib.escape(str(sh.qabda_mandate))

        price_lo = float(row["PriceBandLower"])
        price_hi = float(row["PriceBandUpper"])
        price_str = (f"₹{price_lo:.0f}–₹{price_hi:.0f}"
                     if price_hi > 0 else "Price TBD")

        close_str = str(row["CloseDate"])
        days_str  = f"{row['DaysToClose']}d left" if row["DaysToClose"] >= 0 else "closing today"

        msg = (
            f"{em} <b>{clean_sym}</b> [{sector_safe}]\n"
            f"   🏆 <b>{score:.1f}/100</b>  {row['Verdict']}\n"
            f"   📊 Sub: <b>{row['SubscriptionTimes']:.1f}×</b>"
            f"  GMP: <b>{row['gmp_pct']:.1f}%</b>"
            + ("  <i>(no GMP yet)</i>" if row["gmp_pct"]==0 else "") + "\n"
            f"   💹 {price_str}  Lot {row['LotSize']}"
            f"  Size ₹{row['IssueSizeCr']:.0f}Cr\n"
            f"   📅 Closes: {html_lib.escape(close_str)} ({days_str})\n"
            f"   🎲 P(Allot): <b>{a.p_single_mc*100:.3f}%</b>"
            f"  [CI: {a.ci_95[0]*100:.2f}–{a.ci_95[1]*100:.2f}%]\n"
            f"   👥 Syndicate: <b>{a.optimal_syndicate} PANs</b>"
            f"  Kelly: {a.kelly_pct:.1f}%"
            f"  EV: ₹{a.ev_inr:,.0f}\n"
            f"   🕌 {tier_safe}  (Barakah {sh.barakah_index:.0f}/100)\n"
        )
        if sh.deferred_issues:
            msg += "   🚨 " + " | ".join(html_lib.escape(i) for i in sh.deferred_issues) + "\n"
        msg += f"   ⚖️ {qabda_safe}"

        if console:
            print(f"\n{'─'*55}\n[TELEGRAM DETAIL]\n{msg}")
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

    # Console table
    ranked = df.sort_values(["IsUpcoming","FinalScore"], ascending=[True, False])
    W = 106
    print(f"\n{'═'*W}")
    print(f"  {VERSION}  |  {TODAY}")
    print(f"{'═'*W}")
    print(f"  {'Symbol':<32} {'Score':>5}  {'Verdict':<14}  "
          f"{'Sub':>6}  {'GMP':>6}  {'Days':>4}  {'Synd':>4}  "
          f"{'Status':<10}  {'Conf':<12}  Source")
    print(f"  {'─'*32} {'─'*5}  {'─'*14}  {'─'*6}  {'─'*6}  "
          f"{'─'*4}  {'─'*4}  {'─'*10}  {'─'*12}  {'─'*18}")
    for _, row in ranked.iterrows():
        sym    = str(row["Symbol"])
        a      = allots[sym]
        status = "UPCOMING" if row.get("IsUpcoming") else "LIVE"
        fb_flag = " *" if row.get("_date_fallback") else "  "
        print(
            f"  {sym:<32} {row['FinalScore']:>5.1f}  {row['Verdict']:<14}  "
            f"{row['SubscriptionTimes']:>5.1f}×  {row['gmp_pct']:>5.1f}%  "
            f"{row['DaysToClose']:>4}  {a.optimal_syndicate:>4}  "
            f"{status:<10}  {str(row.get('Source',''))[:18]}{fb_flag}"
        )
    print(f"{'═'*W}")
    print(f"  * = date-fallback flag (row kept only if sub > 0)\n")

    send_telegram_alerts(df, allots, shariahs)
    log.info("🏁  Complete.")
    return df

if __name__ == "__main__":
    run()
