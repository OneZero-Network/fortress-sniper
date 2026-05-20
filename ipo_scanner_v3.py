#!/usr/bin/env python3
"""
IPO FETCH ENGINE v4.0 — Production Grade
=========================================
WHY THE OLD SCRAPER FAILS (root cause diagnosis):
  1. Chittorgarh renders its IPO table via JavaScript / DataTables AJAX.
     A plain requests.get() fetches the HTML *shell* — no rows, ever.
  2. NSE / Chittorgarh / Investorgain return host_not_allowed (403) inside
     sandboxed environments (Claude, Replit free tier, some CI runners).

WHAT THIS FILE PROVIDES:
  Strategy A — NSE official API  (works on GitHub Actions, your local machine)
  Strategy B — Playwright headless browser for Chittorgarh  (JS-rendered tables)
  Strategy C — Fallback CSV  (always runs)

INSTALLATION (run once, or add to requirements.txt):
  pip install requests pandas beautifulsoup4 playwright
  playwright install chromium        # one-time browser download

USAGE:
  python ipo_fetch_engine_v4.py      # standalone test
  from ipo_fetch_engine_v4 import fetch_ipo_calendar   # drop-in for v3
"""

import os
import re
import time
import random
import logging
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup

log = logging.getLogger("IPO-FETCH-v4")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)-8s | %(message)s")

FALLBACK_CSV = Path("data/ipo_fallback.csv")
np.random.seed(42)

# ═══════════════════════════════════════════════════════════
# BROWSER HEADERS (for requests-based calls)
# ═══════════════════════════════════════════════════════════
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
    "DNT": "1",
}

def _jitter(lo=1.0, hi=3.0):
    time.sleep(random.uniform(lo, hi))

def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_HEADERS)
    return s

def _nse_warmup(sess: requests.Session):
    """Warm the NSE session cookie — same pattern as Fortress Sniper."""
    for url in [
        "https://www.nseindia.com",
        "https://www.nseindia.com/market-data/upcoming-issues-ipo",
    ]:
        try:
            r = sess.get(url, timeout=15)
            log.debug(f"NSE warmup {url[-40:]}: {r.status_code}")
        except Exception as exc:
            log.warning(f"NSE warmup failed for {url}: {exc}")
        _jitter(1.5, 2.5)

# ═══════════════════════════════════════════════════════════
# STRATEGY A — NSE Official IPO APIs
# ═══════════════════════════════════════════════════════════
# NSE exposes several undocumented but stable JSON endpoints.
# These work from GitHub Actions (confirmed in Fortress Sniper v2.x).

NSE_IPO_ENDPOINTS = [
    # Current/upcoming IPOs on mainboard
    "https://www.nseindia.com/api/ipo",
    # SME / Emerge IPOs
    "https://www.nseindia.com/api/emerge-ipo",
    # New issues (broader)
    "https://www.nseindia.com/api/otherMarketData?identifier=UPCOMING_IPO",
    # Allotment status list (recently opened)
    "https://www.nseindia.com/api/ipo-current-allotment",
]

NSE_REFERER = "https://www.nseindia.com/market-data/upcoming-issues-ipo"


def _parse_nse_ipo_row(r: dict, sector: str) -> Optional[dict]:
    """Convert a raw NSE API row dict into a standardised IPO record."""
    today = datetime.today().date()

    def _f(v, default=0.0):
        try:
            return float(str(v).replace(",", "").replace("₹", ""))
        except Exception:
            return default

    def _i(v, default=0):
        try:
            return int(str(v).replace(",", ""))
        except Exception:
            return default

    symbol = str(r.get("symbol", r.get("companyName", r.get("issuerName", "")))).strip()
    if not symbol or len(symbol) < 2:
        return None

    # Price band — NSE sends "100 to 105" or "100-105" or a single number
    price_text = str(r.get("priceBand", r.get("issuePrice", r.get("price", "100"))))
    prices = re.findall(r"[\d.]+", price_text)
    price_lower = _f(prices[0], 95.0) if prices else 95.0
    price_upper = _f(prices[-1], 100.0) if prices else 100.0

    # Issue size
    size = _f(r.get("issueSize", r.get("totalIssueSizeCr", r.get("issueSizeCrores", 50.0))), 50.0)
    if size > 50000:                  # NSE sometimes sends rupees not crores
        size /= 1e7

    # Lot size
    lot = _i(r.get("lotSize", r.get("minBidQuantity", 1 if sector == "SME" else 1)))
    if lot <= 0:
        lot = 1000 if sector == "SME" else 50

    # Subscription
    sub_text = str(r.get("subscriptionTimes", r.get("subscriptionStatus", "0")))
    sub = _f(re.search(r"[\d.]+", sub_text).group() if re.search(r"[\d.]+", sub_text) else "0", 0.0)

    # GMP — not from NSE (they don't publish it); left at 0 to be merged later
    gmp = 0.0

    # Close date
    close_raw = str(r.get("closeDate", r.get("biddingEndDate", r.get("closingDate", ""))))
    close_date = today + timedelta(days=10)
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%b %d, %Y", "%d %b %Y"):
        try:
            close_date = datetime.strptime(close_raw, fmt).date()
            break
        except ValueError:
            pass

    days_to_close = max(0, (close_date - today).days)

    return {
        "Symbol":            symbol,
        "Sector":            sector,
        "IssueSizeCr":       round(size, 2),
        "PriceBandLower":    price_lower,
        "PriceBandUpper":    price_upper,
        "LotSize":           lot,
        "GMP":               gmp,
        "gmp_pct":           0.0,
        "SubscriptionTimes": round(sub, 2),
        "CloseDate":         close_date.strftime("%Y-%m-%d"),
        "DaysToClose":       days_to_close,
        "Source":            "nse_api",
    }


def fetch_nse_ipo_api() -> pd.DataFrame:
    """
    Hit NSE's JSON endpoints and return a unified DataFrame.
    Works reliably on GitHub Actions (same session warmup as Fortress Sniper).
    Returns empty DataFrame if every endpoint fails.
    """
    sess = _make_session()
    _nse_warmup(sess)

    all_rows: List[dict] = []
    seen_symbols: set = set()

    for endpoint in NSE_IPO_ENDPOINTS:
        try:
            log.info(f"  NSE API → {endpoint.replace('https://www.nseindia.com/api/','')}")
            resp = sess.get(endpoint, timeout=20,
                            headers={"Referer": NSE_REFERER,
                                     "X-Requested-With": "XMLHttpRequest"})
            log.debug(f"  {resp.status_code} {len(resp.content)}B deny={resp.headers.get('x-deny-reason','none')}")

            if resp.status_code != 200 or len(resp.content) < 20:
                continue

            raw = resp.content.lstrip()
            if raw[:1] == b"<":
                log.warning("  HTML returned (IP blocked or rate-limited) — skipping endpoint")
                continue

            data = resp.json()
            items = data if isinstance(data, list) else data.get("data", [])
            if not items:
                log.warning(f"  Empty data from {endpoint}")
                continue

            log.info(f"  Got {len(items)} rows")
            for item in items:
                sector = "SME" if "sme" in endpoint or "emerge" in endpoint else "Mainboard"
                rec = _parse_nse_ipo_row(item, sector)
                if rec and rec["Symbol"] not in seen_symbols:
                    seen_symbols.add(rec["Symbol"])
                    all_rows.append(rec)

            _jitter(1.5, 3.0)
        except Exception as exc:
            log.warning(f"  NSE endpoint failed ({endpoint[-50:]}): {exc}")

    if not all_rows:
        log.warning("NSE API: no rows from any endpoint.")
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    log.info(f"✅ NSE API: {len(df)} unique IPOs collected.")
    return df


# ═══════════════════════════════════════════════════════════
# STRATEGY B — Playwright headless browser for Chittorgarh
# ═══════════════════════════════════════════════════════════
# Chittorgarh renders its table via DataTables AJAX after page load.
# requests can never see these rows. Playwright renders the full page.
#
# Install once:  pip install playwright && playwright install chromium
#
# On GitHub Actions, add to your workflow:
#   - run: pip install playwright && playwright install --with-deps chromium

CHITTORGARH_URLS = {
    "SME":       "https://www.chittorgarh.com/report/upcoming-ipos-drhp-filed/158/?cat=sme",
    "Mainboard": "https://www.chittorgarh.com/report/upcoming-ipos-drhp-filed/158/",
    "Open_SME":  "https://www.chittorgarh.com/report/sme-ipo-subscription-status/10/",
    "Open_Main": "https://www.chittorgarh.com/report/ipo-subscription-status/10/",
}

# Chittorgarh's AJAX endpoint (discovered via browser DevTools Network tab)
# The DataTable posts to this URL — send a POST with standard DataTables params.
CHITTORGARH_AJAX = "https://www.chittorgarh.com/report/upcoming-ipos-drhp-filed/158/?ajax=1"


def fetch_chittorgarh_ajax(url: str, ipo_type: str) -> pd.DataFrame:
    """
    Try Chittorgarh's DataTables AJAX endpoint directly.
    DataTables sends a POST with draw/start/length params.
    This avoids needing Playwright if the endpoint is reachable.
    """
    sess = _make_session()
    try:
        # First hit the page to get session cookie
        sess.get(url, timeout=15)
        _jitter(1.0, 2.0)
    except Exception:
        pass

    # Standard DataTables server-side POST body
    post_data = {
        "draw": "1",
        "start": "0",
        "length": "200",
        "search[value]": "",
        "search[regex]": "false",
        "order[0][column]": "0",
        "order[0][dir]": "asc",
    }

    ajax_candidates = [
        url.rstrip("/") + "?ajax=1",
        url.rstrip("/") + "?draw=1",
        "https://www.chittorgarh.com/ajax/ipo_list.php",
        "https://www.chittorgarh.com/ajax/getIPOList.php",
    ]

    for ajax_url in ajax_candidates:
        try:
            resp = sess.post(ajax_url, data=post_data, timeout=15,
                             headers={"X-Requested-With": "XMLHttpRequest",
                                      "Referer": url})
            if resp.status_code == 200 and len(resp.content) > 100:
                deny = resp.headers.get('x-deny-reason', 'none')
                if deny != 'none':
                    log.warning(f"  Chittorgarh AJAX blocked: {deny}")
                    continue
                try:
                    data = resp.json()
                    rows_raw = data.get("data", data.get("aaData", []))
                    if rows_raw:
                        log.info(f"  Chittorgarh AJAX hit: {len(rows_raw)} rows from {ajax_url}")
                        return _parse_chittorgarh_ajax_rows(rows_raw, ipo_type)
                except json.JSONDecodeError:
                    # Maybe it's an HTML fragment — try BS4
                    soup = BeautifulSoup(resp.text, "html.parser")
                    table = soup.find("table")
                    if table:
                        return _parse_chittorgarh_html_table(table, ipo_type)
        except Exception as exc:
            log.debug(f"  AJAX attempt {ajax_url}: {exc}")

    return pd.DataFrame()


def _parse_chittorgarh_ajax_rows(rows: list, ipo_type: str) -> pd.DataFrame:
    """Parse DataTables JSON rows — each row is a list of HTML cell strings."""
    today = datetime.today().date()
    sector = "Mainboard" if ipo_type in ("Mainboard", "Open_Main") else "SME"
    records = []
    for row in rows:
        cells = row if isinstance(row, list) else list(row.values())
        if not cells:
            continue
        # Strip HTML from cells
        clean = [BeautifulSoup(str(c), "html.parser").get_text(strip=True) for c in cells]
        if not clean[0] or len(clean[0]) < 2:
            continue
        symbol = clean[0]
        size   = float(re.search(r"[\d.]+", clean[1]).group()) if len(clean) > 1 and re.search(r"[\d.]+", clean[1]) else 50.0
        price  = _extract_price_band(clean[2] if len(clean) > 2 else "100")
        lot    = int(re.search(r"\d+", clean[3]).group()) if len(clean) > 3 and re.search(r"\d+", clean[3]) else (1000 if sector == "SME" else 50)
        close  = _parse_date(clean[4] if len(clean) > 4 else "", today + timedelta(days=10))
        sub    = float(re.search(r"[\d.]+", clean[5]).group()) if len(clean) > 5 and re.search(r"[\d.]+", clean[5]) else 0.0
        gmp    = float(re.search(r"[\d.]+", clean[6]).group()) / 100 if len(clean) > 6 and re.search(r"[\d.]+", clean[6]) else 0.0
        records.append({
            "Symbol": symbol, "Sector": sector, "IssueSizeCr": round(size, 2),
            "PriceBandLower": price[0], "PriceBandUpper": price[1],
            "LotSize": lot, "GMP": gmp, "gmp_pct": round(gmp * 100, 2),
            "SubscriptionTimes": round(sub, 2),
            "CloseDate": close.strftime("%Y-%m-%d"),
            "DaysToClose": max(0, (close - today).days),
            "Source": "chittorgarh_ajax",
        })
    return pd.DataFrame(records)


def _parse_chittorgarh_html_table(table, ipo_type: str) -> pd.DataFrame:
    """Parse a BeautifulSoup <table> from Chittorgarh into standard DataFrame."""
    today  = datetime.today().date()
    sector = "Mainboard" if "main" in ipo_type.lower() else "SME"
    rows   = table.find_all("tr")
    if len(rows) < 2:
        return pd.DataFrame()

    headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th","td"])]
    col = {}
    for i, h in enumerate(headers):
        if any(k in h for k in ("company","issuer","name")):   col.setdefault("sym", i)
        elif any(k in h for k in ("size","cr","amt")):          col.setdefault("size", i)
        elif any(k in h for k in ("price","band")):             col.setdefault("price", i)
        elif any(k in h for k in ("close","end","date")):       col.setdefault("close", i)
        elif any(k in h for k in ("lot","qty")):                col.setdefault("lot", i)
        elif "gmp" in h:                                        col.setdefault("gmp", i)
        elif any(k in h for k in ("sub","times")):              col.setdefault("sub", i)
    col.setdefault("sym", 0)

    records = []
    for row in rows[1:]:
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        sym_cell = cells[col["sym"]]
        link = sym_cell.find("a")
        symbol = (link.get_text(strip=True) if link else sym_cell.get_text(strip=True)).strip()
        if not symbol or len(symbol) < 2:
            continue
        def _cell(key, default=""):
            i = col.get(key)
            return cells[i].get_text(strip=True) if i is not None and len(cells) > i else default
        size  = float(re.search(r"[\d.]+", _cell("size","50")).group()) if re.search(r"[\d.]+", _cell("size","50")) else 50.0
        price = _extract_price_band(_cell("price","100"))
        lot   = int(re.search(r"\d+", _cell("lot","1000")).group()) if re.search(r"\d+", _cell("lot","1000")) else (1000 if sector=="SME" else 50)
        close = _parse_date(_cell("close",""), today + timedelta(days=10))
        gmp_t = _cell("gmp","0")
        gmp   = float(re.search(r"[\d.]+", gmp_t).group()) / (1 if float(re.search(r"[\d.]+", gmp_t).group() if re.search(r"[\d.]+", gmp_t) else "1") <= 1 else 100) if re.search(r"[\d.]+", gmp_t) else 0.0
        sub_t = _cell("sub","0")
        sub   = float(re.search(r"[\d.]+", sub_t).group()) if re.search(r"[\d.]+", sub_t) else 0.0
        records.append({
            "Symbol": symbol, "Sector": sector, "IssueSizeCr": round(size, 2),
            "PriceBandLower": price[0], "PriceBandUpper": price[1],
            "LotSize": lot, "GMP": gmp, "gmp_pct": round(gmp*100, 2),
            "SubscriptionTimes": round(sub, 2),
            "CloseDate": close.strftime("%Y-%m-%d"),
            "DaysToClose": max(0, (close - today).days),
            "Source": "chittorgarh_html",
        })
    return pd.DataFrame(records)


def fetch_chittorgarh_playwright(url: str, ipo_type: str) -> pd.DataFrame:
    """
    Use Playwright to fully render the Chittorgarh page and extract the
    DataTables AJAX data after JavaScript execution.

    Requires:  pip install playwright && playwright install chromium

    On GitHub Actions add to your YAML workflow:
        - name: Install Playwright browsers
          run: playwright install --with-deps chromium
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning("Playwright not installed — run: pip install playwright && playwright install chromium")
        return pd.DataFrame()

    today  = datetime.today().date()
    sector = "Mainboard" if "main" in ipo_type.lower() else "SME"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage"])
        page    = browser.new_page(
            user_agent=_HEADERS["User-Agent"],
            extra_http_headers={"Accept-Language": "en-IN,en;q=0.9"},
        )

        # Intercept the DataTables AJAX response
        intercepted_data = []

        def intercept(response):
            try:
                if response.status == 200 and "chittorgarh" in response.url:
                    ct = response.headers.get("content-type","")
                    if "json" in ct or "javascript" in ct:
                        body = response.json()
                        rows = body.get("data", body.get("aaData", []))
                        if rows:
                            log.info(f"  Playwright intercepted AJAX: {len(rows)} rows from {response.url}")
                            intercepted_data.extend(rows)
            except Exception:
                pass

        page.on("response", intercept)

        try:
            page.goto(url, wait_until="networkidle", timeout=45000)
            # Wait for any DataTable to finish loading
            try:
                page.wait_for_selector("table tbody tr td:not(.dataTables_empty)", timeout=15000)
            except Exception:
                pass

            # If we caught AJAX data, use it
            if intercepted_data:
                df = _parse_chittorgarh_ajax_rows(intercepted_data, ipo_type)
                browser.close()
                return df

            # Otherwise parse rendered HTML
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            for table in soup.find_all("table"):
                if len(table.find_all("tr")) > 3:
                    df = _parse_chittorgarh_html_table(table, ipo_type)
                    if not df.empty:
                        browser.close()
                        log.info(f"  Playwright HTML parse: {len(df)} rows")
                        return df

        except Exception as exc:
            log.warning(f"  Playwright page error: {exc}")
        finally:
            browser.close()

    return pd.DataFrame()


# ═══════════════════════════════════════════════════════════
# STRATEGY C — Fallback CSV (unchanged from v3)
# ═══════════════════════════════════════════════════════════

def _ensure_fallback_csv() -> pd.DataFrame:
    FALLBACK_CSV.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.today()
    seed_ipos = [
        {"Symbol":"Merritronix Ltd",       "IssueSizeCr":70.03,  "PriceBandLower":141,"PriceBandUpper":149,"LotSize":1000,"GMP":0.25,"SubscriptionTimes":45.2, "Sector":"SME",      "CloseDate":(today+timedelta(days=3)).strftime("%Y-%m-%d")},
        {"Symbol":"SMR Jewels Ltd",         "IssueSizeCr":67.23,  "PriceBandLower":128,"PriceBandUpper":135,"LotSize":1000,"GMP":0.10,"SubscriptionTimes":12.4, "Sector":"SME",      "CloseDate":(today+timedelta(days=5)).strftime("%Y-%m-%d")},
        {"Symbol":"Yaashvi Jewellers Ltd",  "IssueSizeCr":43.88,  "PriceBandLower":83, "PriceBandUpper":83, "LotSize":1000,"GMP":0.00,"SubscriptionTimes":1.1,  "Sector":"SME",      "CloseDate":(today+timedelta(days=7)).strftime("%Y-%m-%d")},
        {"Symbol":"M R Maniveni Foods Ltd", "IssueSizeCr":27.04,  "PriceBandLower":51, "PriceBandUpper":52, "LotSize":1000,"GMP":0.55,"SubscriptionTimes":112.4,"Sector":"SME",      "CloseDate":(today+timedelta(days=2)).strftime("%Y-%m-%d")},
        {"Symbol":"Q-Line Biotech Ltd",     "IssueSizeCr":214.48, "PriceBandLower":326,"PriceBandUpper":343,"LotSize":50,  "GMP":0.40,"SubscriptionTimes":85.3, "Sector":"Mainboard","CloseDate":(today+timedelta(days=1)).strftime("%Y-%m-%d")},
    ]
    if not FALLBACK_CSV.exists():
        pd.DataFrame(seed_ipos).to_csv(FALLBACK_CSV, index=False)
        log.info(f"Created seed fallback CSV: {FALLBACK_CSV}")
    try:
        return pd.read_csv(FALLBACK_CSV)
    except Exception:
        return pd.DataFrame(seed_ipos)


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════

def _extract_price_band(text: str):
    nums = re.findall(r"[\d.]+", str(text))
    if len(nums) >= 2:
        return float(nums[0]), float(nums[-1])
    if len(nums) == 1:
        v = float(nums[0])
        return v * 0.97, v
    return 95.0, 100.0

def _parse_date(text: str, default):
    for fmt in ("%d-%b-%Y", "%d %b %Y", "%d-%m-%Y", "%Y-%m-%d", "%b %d, %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(text).strip(), fmt).date()
        except ValueError:
            pass
    return default

def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    today = datetime.today().date()
    defaults = {
        "Symbol":"UNKNOWN","Sector":"SME","IssueSizeCr":50.0,
        "PriceBandLower":95.0,"PriceBandUpper":100.0,"LotSize":1000,
        "GMP":0.0,"gmp_pct":0.0,"SubscriptionTimes":1.0,
        "CloseDate":(today+timedelta(days=7)).strftime("%Y-%m-%d"),
        "DaysToClose":7,"Source":"unknown",
    }
    for col, val in defaults.items():
        if col not in df.columns:
            df[col] = val
    df["gmp_pct"]     = df["GMP"].apply(lambda g: round(float(g)*100, 2))
    df["DaysToClose"] = df["CloseDate"].apply(
        lambda x: max(0, (datetime.strptime(str(x), "%Y-%m-%d").date() - today).days)
    )
    df = df[df["Symbol"].astype(str).str.strip().ne("")]
    df = df[df["Symbol"].astype(str).str.lower().ne("unknown")]
    return df.reset_index(drop=True)


# ═══════════════════════════════════════════════════════════
# MASTER FETCH FUNCTION — drop-in replacement for v3
# ═══════════════════════════════════════════════════════════

def fetch_ipo_calendar(use_playwright: bool = True) -> pd.DataFrame:
    """
    Main entry point. Returns a fully enriched DataFrame of active IPOs.

    Strategy waterfall:
      A → NSE API (GitHub Actions / local machine)
      B → Playwright headless for Chittorgarh (if installed)
      C → Fallback CSV (always available)

    Args:
        use_playwright: Set False to skip Playwright (faster if not installed)
    """
    frames = []

    # ── Strategy A: NSE API ────────────────────────────────────────
    log.info("=" * 55)
    log.info("Strategy A: NSE official IPO API")
    try:
        nse_df = fetch_nse_ipo_api()
        if not nse_df.empty:
            frames.append(nse_df)
            log.info(f"  ✅ NSE API: {len(nse_df)} IPOs")
        else:
            log.warning("  NSE API: 0 rows — likely blocked (sandbox/CI IP restriction)")
    except Exception as exc:
        log.warning(f"  NSE API error: {exc}")

    # ── Strategy B: Chittorgarh ────────────────────────────────────
    log.info("Strategy B: Chittorgarh (AJAX probe + Playwright fallback)")
    for ipo_type, url in CHITTORGARH_URLS.items():
        # B1: Try the AJAX endpoint directly (no browser needed)
        log.info(f"  B1 AJAX probe [{ipo_type}]")
        try:
            df = fetch_chittorgarh_ajax(url, ipo_type)
            if not df.empty:
                frames.append(df)
                log.info(f"  ✅ Chittorgarh AJAX [{ipo_type}]: {len(df)} rows")
                continue
        except Exception as exc:
            log.warning(f"  Chittorgarh AJAX [{ipo_type}]: {exc}")

        # B2: Playwright headless browser (JS-rendered table)
        if use_playwright:
            log.info(f"  B2 Playwright [{ipo_type}]")
            try:
                df = fetch_chittorgarh_playwright(url, ipo_type)
                if not df.empty:
                    frames.append(df)
                    log.info(f"  ✅ Playwright [{ipo_type}]: {len(df)} rows")
            except Exception as exc:
                log.warning(f"  Playwright [{ipo_type}]: {exc}")
        _jitter(1.0, 2.0)

    # ── Combine and deduplicate ────────────────────────────────────
    if frames:
        combined = pd.concat(frames, ignore_index=True)
        if "Symbol" in combined.columns:
            combined = (combined
                        .sort_values("SubscriptionTimes", ascending=False)
                        .drop_duplicates(subset="Symbol", keep="first")
                        .reset_index(drop=True))
        if len(combined) >= 2:
            log.info(f"✅ Strategies A+B: {len(combined)} unique IPOs")
            return _enrich(combined)

    # ── Strategy C: Fallback CSV ───────────────────────────────────
    log.info("⚠️  Strategy C: Fallback CSV (no live data available)")
    df = _ensure_fallback_csv()
    return _enrich(df)


# ═══════════════════════════════════════════════════════════
# QUICK TEST
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  IPO FETCH ENGINE v4.0 — self-test")
    print("=" * 60)
    df = fetch_ipo_calendar(use_playwright=True)
    if df.empty:
        print("No data returned.")
    else:
        print(f"\n{len(df)} IPOs fetched:\n")
        print(df[["Symbol","Sector","IssueSizeCr","PriceBandUpper",
                   "SubscriptionTimes","GMP","DaysToClose","Source"]].to_string(index=False))
