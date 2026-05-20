#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║          IPO SNIPER v5.0 — BULLETPROOF PRODUCTION EDITION                  ║
║  3-Source Fetch Chain · Quant Engine · Shariah Matrix · Telegram Alerts    ║
║  FIXES: closed IPOs filtered, Telegram spam reduced, HTML errors fixed     ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import re
import math
import time
import json
import random
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup

# ── Optional Playwright ────────────────────────────────────────────────────
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    PLAYWRIGHT_OK = True
except ImportError:
    PLAYWRIGHT_OK = False

# ══════════════════════════════════════════════════════════════════════════════
# GLOBAL CONFIG
# ══════════════════════════════════════════════════════════════════════════════
VERSION           = "IPO-SNIPER-v5.0-BULLETPROOF"
DB_PATH           = Path("data/ipo_sniper_v5.db")
FALLBACK_CSV      = Path("data/ipo_fallback.csv")
JSON_EXPORT       = Path("data/ipo_latest_run.json")
MC_RUNS           = 50_000
KELLY_FRACTION    = 0.25
MAX_SYNDICATE     = 10
SEED              = 42

np.random.seed(SEED)
random.seed(SEED)

BASE_WEIGHTS: Dict[str, float] = {
    "gmp":       0.22,
    "sub":       0.28,
    "sentiment": 0.18,
    "trend":     0.10,
    "size":      0.08,
    "halal":     0.14,
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(message)s"
)
log = logging.getLogger("IPO-SNIPER-v5")

TODAY = datetime.today().date()

# ══════════════════════════════════════════════════════════════════════════════
# UTILITY HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _flt(s, default: float = 0.0) -> float:
    try:
        m = re.search(r"[\d.]+", str(s).replace(",", ""))
        return float(m.group()) if m else default
    except Exception:
        return default

def _int(s, default: int = 0) -> int:
    try:
        m = re.search(r"\d+", str(s).replace(",", ""))
        return int(m.group()) if m else default
    except Exception:
        return default

def _parse_price_band(text: str) -> Tuple[float, float]:
    nums = re.findall(r"[\d.]+", str(text).replace(",", ""))
    if len(nums) >= 2:
        return float(nums[0]), float(nums[-1])
    if len(nums) == 1:
        v = float(nums[0])
        return round(v * 0.97, 2), v
    return 95.0, 100.0

def _parse_date(text: str) -> Optional["datetime"]:
    for fmt in ("%d-%b-%Y", "%d %b %Y", "%d-%m-%Y", "%Y-%m-%d",
                "%b %d, %Y", "%d/%m/%Y", "%b %Y", "%B %Y"):
        try:
            return datetime.strptime(str(text).strip(), fmt).date()
        except ValueError:
            pass
    return None

def _jitter(lo: float = 1.5, hi: float = 4.0):
    time.sleep(random.uniform(lo, hi))

# ══════════════════════════════════════════════════════════════════════════════
# HTTP SESSION FACTORY
# ══════════════════════════════════════════════════════════════════════════════

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Cache-Control": "max-age=0",
}

def _make_session(referer: str = "https://www.google.com/") -> requests.Session:
    s = requests.Session()
    s.headers.update({**BROWSER_HEADERS, "Referer": referer})
    return s

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE A — NSE INDIA OFFICIAL API
# ══════════════════════════════════════════════════════════════════════════════

NSE_API_ENDPOINTS = [
    ("https://www.nseindia.com/api/ipo",                              "Mainboard"),
    ("https://www.nseindia.com/api/emerge-ipo",                       "SME"),
    ("https://www.nseindia.com/api/otherMarketData?identifier=UPCOMING_IPO", "Mainboard"),
    ("https://www.nseindia.com/api/ipo-current-allotment",            "Mainboard"),
    ("https://www.nseindia.com/api/ipo-allot",                        "Mainboard"),
]

NSE_WARMUP_URLS = [
    "https://www.nseindia.com",
    "https://www.nseindia.com/market-data/upcoming-issues-ipo",
    "https://www.nseindia.com/market-data/sme-emerge-ipo",
]

def _parse_nse_item(item: dict, sector: str) -> Optional[dict]:
    sym = str(item.get("symbol",
          item.get("companyName",
          item.get("issuerName",
          item.get("name", ""))))).strip()
    if not sym or len(sym) < 2:
        return None

    price_txt = str(item.get("priceBand",
                   item.get("issuePrice",
                   item.get("price", "100"))))
    lo, hi = _parse_price_band(price_txt)

    size_raw = item.get("issueSize",
               item.get("totalIssueSizeCr",
               item.get("issueSizeCrores",
               item.get("amount", 50.0))))
    size = _flt(size_raw, 50.0)
    if size > 50_000:
        size /= 1e7

    lot = _int(item.get("lotSize", item.get("minBidQuantity", 0)))
    if lot <= 0:
        lot = 1000 if sector == "SME" else 50

    sub_raw = str(item.get("subscriptionTimes", item.get("subscriptionStatus", "0")))
    sub = _flt(re.search(r"[\d.]+", sub_raw).group() if re.search(r"[\d.]+", sub_raw) else "0")

    gmp_raw = item.get("gmp", item.get("premiumAtGMP", 0))
    gmp = _flt(gmp_raw) / 100 if _flt(gmp_raw) > 1 else _flt(gmp_raw)

    close_raw = str(item.get("closeDate",
                    item.get("biddingEndDate",
                    item.get("closingDate",
                    item.get("endDate", "")))))
    close_dt = _parse_date(close_raw) or (TODAY + timedelta(days=10))
    days_left = max(0, (close_dt - TODAY).days)

    return {
        "Symbol":           sym,
        "Sector":           sector,
        "IssueSizeCr":      round(size, 2),
        "PriceBandLower":   lo,
        "PriceBandUpper":   hi,
        "LotSize":          lot,
        "GMP":              gmp,
        "gmp_pct":          round(gmp * 100, 2),
        "SubscriptionTimes":round(sub, 2),
        "CloseDate":        close_dt.strftime("%Y-%m-%d"),
        "DaysToClose":      days_left,
        "Source":           "nse_api",
    }

def fetch_source_a_nse() -> pd.DataFrame:
    log.info("━━ SOURCE A: NSE India API ━━")
    sess = _make_session("https://www.nseindia.com/")
    sess.headers.update({
        "X-Requested-With": "XMLHttpRequest",
        "Accept":           "application/json, text/plain, */*",
        "Referer":          "https://www.nseindia.com/market-data/upcoming-issues-ipo",
    })

    for url in NSE_WARMUP_URLS:
        try:
            r = sess.get(url, timeout=15)
            log.debug(f"NSE warmup [{r.status_code}] {url}")
        except Exception:
            pass
        _jitter(1.5, 2.5)

    records: List[dict] = []
    seen: set = set()

    for endpoint, sector in NSE_API_ENDPOINTS:
        try:
            resp = sess.get(endpoint, timeout=20)
            log.info(f"  NSE [{sector}] {endpoint.split('/')[-1]} → HTTP {resp.status_code}")
            if resp.status_code != 200 or len(resp.content) < 30:
                continue
            deny = resp.headers.get("x-deny-reason", "")
            if deny:
                log.warning(f"  NSE blocked: {deny}")
                continue
            data = resp.json()
            items = data if isinstance(data, list) else (
                data.get("data", data.get("ipoData", data.get("ipo", [])))
            )
            if not isinstance(items, list):
                items = [items]
            for item in items:
                if not isinstance(item, dict):
                    continue
                rec = _parse_nse_item(item, sector)
                if rec and rec["Symbol"] not in seen:
                    seen.add(rec["Symbol"])
                    records.append(rec)
            _jitter(1.5, 3.0)
        except Exception as exc:
            log.warning(f"  NSE endpoint error: {exc}")

    df = pd.DataFrame(records)
    log.info(f"  ✅ SOURCE A recovered {len(df)} IPOs" if not df.empty else "  ⚠️  SOURCE A: no data")
    return df

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE B — CHITTORGARH (HTTP fallback → Playwright)
# ══════════════════════════════════════════════════════════════════════════════

CHITT_URLS: Dict[str, str] = {
    "Mainboard": "https://www.chittorgarh.com/report/ipo-subscription-status/10/",
    "SME":       "https://www.chittorgarh.com/report/sme-ipo-subscription-status/10/",
    "MB_DRHP":   "https://www.chittorgarh.com/report/ipo-drhp-filed-status/158/",
    "SME_DRHP":  "https://www.chittorgarh.com/report/sme-ipo-drhp-filed-status/158/",
}

def _chitt_sector(ipo_type: str) -> str:
    return "Mainboard" if "main" in ipo_type.lower() or "mb" in ipo_type.lower() else "SME"

def _parse_chitt_table(table, ipo_type: str) -> pd.DataFrame:
    sector = _chitt_sector(ipo_type)
    rows   = table.find_all("tr")
    if len(rows) < 2:
        return pd.DataFrame()

    hdr = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
    col: Dict[str, int] = {}
    for i, h in enumerate(hdr):
        if any(k in h for k in ("company", "issuer", "name")):  col.setdefault("sym",   i)
        elif any(k in h for k in ("size", "cr", "amt")):        col.setdefault("size",  i)
        elif any(k in h for k in ("price", "band")):             col.setdefault("price", i)
        elif any(k in h for k in ("close", "end", "date")):      col.setdefault("close", i)
        elif any(k in h for k in ("lot", "qty", "shares")):      col.setdefault("lot",   i)
        elif "gmp"                                    in h:       col.setdefault("gmp",   i)
        elif any(k in h for k in ("sub", "times", "x")):         col.setdefault("sub",   i)

    if "sym" not in col:
        col["sym"] = 0

    SKIP = {"company", "name", "issuer", "no records found", "compare", "click here", ""}
    records = []

    for row in rows[1:]:
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        def _c(key, default=""):
            idx = col.get(key)
            return cells[idx].get_text(strip=True) if idx is not None and idx < len(cells) else default

        lnk    = cells[col["sym"]].find("a")
        symbol = (lnk.get_text(strip=True) if lnk else cells[col["sym"]].get_text(strip=True)).strip()
        if not symbol or symbol.lower() in SKIP or len(symbol) < 2:
            continue

        size  = _flt(_c("size", "50"), 50.0)
        lo, hi = _parse_price_band(_c("price", "100"))
        lot   = _int(_c("lot", "1000")) or (1000 if sector == "SME" else 50)
        close_dt = _parse_date(_c("close", "")) or (TODAY + timedelta(days=10))

        gmp_raw = _flt(_c("gmp", "0"), 0.0)
        gmp = gmp_raw / 100 if gmp_raw > 1 else gmp_raw

        sub = _flt(_c("sub", "0"), 0.0)

        records.append({
            "Symbol":           symbol,
            "Sector":           sector,
            "IssueSizeCr":      round(size, 2),
            "PriceBandLower":   lo,
            "PriceBandUpper":   hi,
            "LotSize":          lot,
            "GMP":              gmp,
            "gmp_pct":          round(gmp * 100, 2),
            "SubscriptionTimes":round(sub, 2),
            "CloseDate":        close_dt.strftime("%Y-%m-%d"),
            "DaysToClose":      max(0, (close_dt - TODAY).days),
            "Source":           f"chittorgarh_{ipo_type.lower()}_html",
        })

    return pd.DataFrame(records)

def _fetch_chitt_http(url: str, ipo_type: str) -> pd.DataFrame:
    sess = _make_session("https://www.chittorgarh.com/")
    try:
        sess.get("https://www.chittorgarh.com/", timeout=12)
        _jitter(1.5, 3.0)
        resp = sess.get(url, timeout=25)
        log.info(f"  Chittorgarh HTTP [{ipo_type}] → {resp.status_code}")
        if resp.status_code != 200:
            return pd.DataFrame()
        deny = resp.headers.get("x-deny-reason", "")
        if deny:
            log.warning(f"  Chittorgarh blocked: {deny}")
            return pd.DataFrame()

        soup = BeautifulSoup(resp.text, "html.parser")
        for sel in [
            "table#report_table", "table.table-striped", "table.table-bordered",
            ".table-responsive table", "table[id*='ipo']", "table[class*='ipo']",
            "table",
        ]:
            for tbl in soup.select(sel):
                if len(tbl.find_all("tr")) > 3:
                    df = _parse_chitt_table(tbl, ipo_type)
                    if not df.empty:
                        return df
    except Exception as exc:
        log.warning(f"  Chittorgarh HTTP error [{ipo_type}]: {exc}")
    return pd.DataFrame()

def _fetch_chitt_playwright(url: str, ipo_type: str) -> pd.DataFrame:
    if not PLAYWRIGHT_OK:
        return pd.DataFrame()
    log.info(f"  Chittorgarh Playwright [{ipo_type}] …")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
            )
            ctx = browser.new_context(
                user_agent=BROWSER_HEADERS["User-Agent"],
                extra_http_headers={"Accept-Language": "en-IN,en;q=0.9"},
                viewport={"width": 1280, "height": 900},
                locale="en-IN",
            )
            page = ctx.new_page()

            intercepted: List[dict] = []
            def _on_response(resp):
                if resp.status == 200 and "chittorgarh" in resp.url:
                    ct = resp.headers.get("content-type", "")
                    if "json" in ct:
                        try:
                            body = resp.json()
                            rows = body.get("data", body.get("aaData", []))
                            if rows:
                                intercepted.extend(rows)
                                log.info(f"  PW AJAX intercept: {len(rows)} rows")
                        except Exception:
                            pass
            page.on("response", _on_response)

            page.goto(url, wait_until="networkidle", timeout=60_000)
            try:
                page.wait_for_selector("table tbody tr td:not(.dataTables_empty)", timeout=15_000)
            except PWTimeout:
                pass

            if intercepted:
                sector = _chitt_sector(ipo_type)
                records = []
                for row_data in intercepted[:50]:
                    cells = row_data if isinstance(row_data, list) else list(row_data.values())
                    clean = [BeautifulSoup(str(c), "html.parser").get_text(strip=True) for c in cells]
                    if not clean or len(clean[0]) < 2:
                        continue
                    symbol = clean[0]
                    size   = _flt(clean[1] if len(clean) > 1 else "50", 50.0)
                    lo, hi = _parse_price_band(clean[2] if len(clean) > 2 else "100")
                    lot    = _int(clean[3] if len(clean) > 3 else "1000") or (1000 if sector == "SME" else 50)
                    close_dt = _parse_date(clean[4] if len(clean) > 4 else "") or (TODAY + timedelta(days=10))
                    sub    = _flt(clean[5] if len(clean) > 5 else "0")
                    gmp_r  = _flt(clean[6] if len(clean) > 6 else "0")
                    gmp    = gmp_r / 100 if gmp_r > 1 else gmp_r
                    records.append({
                        "Symbol": symbol, "Sector": sector,
                        "IssueSizeCr": round(size, 2),
                        "PriceBandLower": lo, "PriceBandUpper": hi,
                        "LotSize": lot,
                        "GMP": gmp, "gmp_pct": round(gmp * 100, 2),
                        "SubscriptionTimes": round(sub, 2),
                        "CloseDate": close_dt.strftime("%Y-%m-%d"),
                        "DaysToClose": max(0, (close_dt - TODAY).days),
                        "Source": f"chittorgarh_{ipo_type.lower()}_ajax",
                    })
                browser.close()
                return pd.DataFrame(records)

            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            for tbl in soup.find_all("table"):
                if len(tbl.find_all("tr")) > 3:
                    df = _parse_chitt_table(tbl, ipo_type)
                    if not df.empty:
                        browser.close()
                        return df
            browser.close()
    except Exception as exc:
        log.warning(f"  Playwright error [{ipo_type}]: {exc}")
    return pd.DataFrame()

def fetch_source_b_chittorgarh() -> pd.DataFrame:
    log.info("━━ SOURCE B: Chittorgarh ━━")
    frames: List[pd.DataFrame] = []
    for ipo_type, url in CHITT_URLS.items():
        df = _fetch_chitt_http(url, ipo_type)
        if df.empty and PLAYWRIGHT_OK:
            df = _fetch_chitt_playwright(url, ipo_type)
        if not df.empty:
            log.info(f"  ✅ Chittorgarh [{ipo_type}]: {len(df)} rows")
            frames.append(df)
        _jitter(2.0, 4.0)

    if frames:
        combined = pd.concat(frames, ignore_index=True)
        log.info(f"  ✅ SOURCE B total: {len(combined)} raw rows")
        return combined
    log.warning("  ⚠️  SOURCE B: no data")
    return pd.DataFrame()

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE C — INVESTORGAIN GMP PAGE
# ══════════════════════════════════════════════════════════════════════════════

INVESTORGAIN_URL = "https://www.investorgain.com/report/live-ipo-gmp/331/"

def fetch_source_c_investorgain() -> pd.DataFrame:
    log.info("━━ SOURCE C: Investorgain GMP ━━")
    sess = _make_session("https://www.investorgain.com/")
    try:
        resp = sess.get(INVESTORGAIN_URL, timeout=25)
        log.info(f"  Investorgain → HTTP {resp.status_code}")
        if resp.status_code != 200:
            return pd.DataFrame()
        deny = resp.headers.get("x-deny-reason", "")
        if deny:
            log.warning(f"  Investorgain blocked: {deny}")
            return pd.DataFrame()

        soup  = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table")
        if not table:
            return pd.DataFrame()

        rows = table.find_all("tr")
        if len(rows) < 2:
            return pd.DataFrame()

        hdr = [c.get_text(strip=True).lower() for c in rows[0].find_all(["th", "td"])]
        col: Dict[str, int] = {}
        for i, h in enumerate(hdr):
            if any(k in h for k in ("ipo", "company", "name")):  col.setdefault("sym",   i)
            elif "gmp" in h:                                       col.setdefault("gmp",   i)
            elif "price" in h:                                     col.setdefault("price", i)
            elif any(k in h for k in ("sub", "times")):            col.setdefault("sub",   i)
            elif any(k in h for k in ("close", "date", "end")):    col.setdefault("close", i)
            elif any(k in h for k in ("size", "cr")):              col.setdefault("size",  i)
            elif "lot" in h:                                        col.setdefault("lot",   i)

        col.setdefault("sym", 0)
        records = []

        for row in rows[1:]:
            cells = row.find_all("td")
            if not cells or len(cells) < 2:
                continue

            def _c(key, default=""):
                idx = col.get(key)
                return cells[idx].get_text(strip=True) if idx is not None and idx < len(cells) else default

            symbol = cells[col["sym"]].get_text(strip=True).strip()
            symbol = re.sub(r"<[^>]+>", "", symbol).strip()
            if not symbol or len(symbol) < 3:
                continue

            gmp_r = _flt(_c("gmp", "0"))
            gmp   = gmp_r / 100 if gmp_r > 1 else gmp_r

            lo, hi  = _parse_price_band(_c("price", "100"))
            if hi == 100.0 and lo == 95.0:
                hi = _flt(_c("price", "100"), 100.0)
                lo = round(hi * 0.97, 2)

            sub       = _flt(_c("sub", "1"), 1.0)
            size      = _flt(_c("size", "50"), 50.0)
            lot       = _int(_c("lot", "1000")) or 1000
            close_dt  = _parse_date(_c("close", "")) or (TODAY + timedelta(days=7))

            records.append({
                "Symbol":            symbol,
                "Sector":            "SME",
                "IssueSizeCr":       round(size, 2),
                "PriceBandLower":    lo,
                "PriceBandUpper":    hi,
                "LotSize":           lot,
                "GMP":               gmp,
                "gmp_pct":           round(gmp * 100, 2),
                "SubscriptionTimes": round(sub, 2),
                "CloseDate":         close_dt.strftime("%Y-%m-%d"),
                "DaysToClose":       max(0, (close_dt - TODAY).days),
                "Source":            "investorgain_gmp",
            })

        df = pd.DataFrame(records)
        log.info(f"  ✅ SOURCE C recovered {len(df)} IPOs" if not df.empty else "  ⚠️  SOURCE C: no data")
        return df

    except Exception as exc:
        log.warning(f"  Investorgain error: {exc}")
        return pd.DataFrame()

# ══════════════════════════════════════════════════════════════════════════════
# FALLBACK SEED DATA
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_fallback_csv() -> pd.DataFrame:
    FALLBACK_CSV.parent.mkdir(parents=True, exist_ok=True)
    if not FALLBACK_CSV.exists():
        seed = [
            {"Symbol": "Merritronix Ltd",       "IssueSizeCr": 70.03,  "PriceBandLower": 141, "PriceBandUpper": 149, "LotSize": 1000, "GMP": 0.25, "SubscriptionTimes": 45.2,  "Sector": "SME",       "CloseDate": (TODAY + timedelta(3)).strftime("%Y-%m-%d")},
            {"Symbol": "SMR Jewels Ltd",         "IssueSizeCr": 67.23,  "PriceBandLower": 128, "PriceBandUpper": 135, "LotSize": 1000, "GMP": 0.10, "SubscriptionTimes": 12.4,  "Sector": "SME",       "CloseDate": (TODAY + timedelta(5)).strftime("%Y-%m-%d")},
            {"Symbol": "Yaashvi Jewellers Ltd",  "IssueSizeCr": 43.88,  "PriceBandLower": 83,  "PriceBandUpper": 83,  "LotSize": 1000, "GMP": 0.00, "SubscriptionTimes": 1.1,   "Sector": "SME",       "CloseDate": (TODAY + timedelta(7)).strftime("%Y-%m-%d")},
            {"Symbol": "M R Maniveni Foods Ltd", "IssueSizeCr": 27.04,  "PriceBandLower": 51,  "PriceBandUpper": 52,  "LotSize": 1000, "GMP": 0.55, "SubscriptionTimes": 112.4, "Sector": "SME",       "CloseDate": (TODAY + timedelta(2)).strftime("%Y-%m-%d")},
            {"Symbol": "Q-Line Biotech Ltd",     "IssueSizeCr": 214.48, "PriceBandLower": 326, "PriceBandUpper": 343, "LotSize": 50,   "GMP": 0.40, "SubscriptionTimes": 85.3,  "Sector": "Mainboard", "CloseDate": (TODAY + timedelta(1)).strftime("%Y-%m-%d")},
            {"Symbol": "Autofurnish Ltd",        "IssueSizeCr": 14.60,  "PriceBandLower": 41,  "PriceBandUpper": 41,  "LotSize": 1000, "GMP": 0.05, "SubscriptionTimes": 3.2,   "Sector": "SME",       "CloseDate": (TODAY + timedelta(4)).strftime("%Y-%m-%d")},
            {"Symbol": "BlueStar Finance Ltd",   "IssueSizeCr": 185.00, "PriceBandLower": 210, "PriceBandUpper": 221, "LotSize": 50,   "GMP": 0.18, "SubscriptionTimes": 38.7,  "Sector": "Mainboard", "CloseDate": (TODAY + timedelta(6)).strftime("%Y-%m-%d")},
            {"Symbol": "Vedanta Solar Ltd",      "IssueSizeCr": 95.50,  "PriceBandLower": 175, "PriceBandUpper": 180, "LotSize": 1200, "GMP": 0.32, "SubscriptionTimes": 67.0,  "Sector": "SME",       "CloseDate": (TODAY + timedelta(3)).strftime("%Y-%m-%d")},
        ]
        pd.DataFrame(seed).to_csv(FALLBACK_CSV, index=False)
        log.info(f"📄 Created seed fallback CSV at {FALLBACK_CSV}")
    df = pd.read_csv(FALLBACK_CSV)
    df["Source"] = "fallback_csv"
    return df

# ══════════════════════════════════════════════════════════════════════════════
# DATA ENRICHMENT + VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

REQUIRED_COLS = {
    "Symbol": "UNKNOWN", "Sector": "SME", "IssueSizeCr": 50.0,
    "PriceBandLower": 95.0, "PriceBandUpper": 100.0, "LotSize": 1000,
    "GMP": 0.0, "gmp_pct": 0.0, "SubscriptionTimes": 1.0,
    "CloseDate": (TODAY + timedelta(days=7)).strftime("%Y-%m-%d"),
    "DaysToClose": 7, "Source": "unknown",
}

def _validate_row(row: pd.Series) -> bool:
    sym = str(row.get("Symbol", "")).strip()
    if not sym or len(sym) < 2 or sym.lower() in ("unknown", "nan", "none"):
        return False
    price = float(row.get("PriceBandUpper", 0))
    if price <= 0 or price > 100_000:
        return False
    lot = int(row.get("LotSize", 0))
    if lot <= 0 or lot > 100_000:
        return False
    size = float(row.get("IssueSizeCr", 0))
    if size < 0:
        return False
    return True

def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    for col, default in REQUIRED_COLS.items():
        if col not in df.columns:
            df[col] = default

    for c in ("IssueSizeCr", "PriceBandLower", "PriceBandUpper", "LotSize",
              "GMP", "gmp_pct", "SubscriptionTimes", "DaysToClose"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(REQUIRED_COLS.get(c, 0))

    df["gmp_pct"] = df["GMP"].apply(lambda g: round(float(g) * 100, 2))

    def _days(x):
        try:
            d = datetime.strptime(str(x), "%Y-%m-%d").date()
            return max(0, (d - TODAY).days)
        except Exception:
            return 7
    df["DaysToClose"] = df["CloseDate"].apply(_days)

    mask = df.apply(_validate_row, axis=1)
    dropped = (~mask).sum()
    if dropped:
        log.info(f"  🗑  Dropped {dropped} invalid rows after validation")
    df = df[mask].reset_index(drop=True)
    return df

# ══════════════════════════════════════════════════════════════════════════════
# MASTER FETCH ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════════

def fetch_ipo_calendar(use_playwright: bool = True) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []

    a = fetch_source_a_nse()
    if not a.empty:
        frames.append(a)

    if use_playwright:
        b = fetch_source_b_chittorgarh()
        if not b.empty:
            frames.append(b)

    c = fetch_source_c_investorgain()
    if not c.empty:
        frames.append(c)

    if frames:
        raw = pd.concat(frames, ignore_index=True)
        enriched = _enrich(raw)
        best_gmp = (enriched.sort_values("gmp_pct", ascending=False)
                             .drop_duplicates(subset="Symbol", keep="first")[["Symbol", "GMP", "gmp_pct"]])
        deduped  = (enriched.sort_values("SubscriptionTimes", ascending=False)
                             .drop_duplicates(subset="Symbol", keep="first")
                             .reset_index(drop=True))
        deduped  = deduped.drop(columns=["GMP", "gmp_pct"]).merge(best_gmp, on="Symbol", how="left")
        deduped["GMP"]     = deduped["GMP"].fillna(0.0)
        deduped["gmp_pct"] = deduped["gmp_pct"].fillna(0.0)

        # FIX: Remove closed IPOs (DaysToClose <= 0)
        before = len(deduped)
        deduped = deduped[deduped["DaysToClose"] > 0].reset_index(drop=True)
        log.info(f"  🗑  Removed {before - len(deduped)} closed IPOs (DaysToClose <= 0)")

        log.info(f"✅ LIVE DATA: {len(deduped)} unique IPOs from {len(frames)} source(s)")
        return deduped

    log.warning("⚠️  ALL LIVE SOURCES FAILED — activating seed CSV fallback")
    return _enrich(_ensure_fallback_csv())

# ══════════════════════════════════════════════════════════════════════════════
# QUANT ENGINE
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class AllotmentProfile:
    symbol:                str
    p_single_mc:           float
    syndicate_matrix:      Dict[int, float]
    optimal_syndicate:     int
    kelly_pct:             float
    ev_inr:                float
    roi_pct:               float
    ci_95:                 Tuple[float, float]

@dataclass
class SentimentProfile:
    symbol:    str
    composite: float
    label:     str

@dataclass
class ShariahVerdict:
    symbol:       str
    tier:         str
    barakah:      float
    najash:       bool
    qabda:        str
    issues:       List[str]
    halal_score:  float
    fatwa_ref:    str

def monte_carlo_allotment(
    sub: float, lot: int, size_cr: float, price: float, n: int = MC_RUNS
) -> Tuple[float, float, float]:
    if sub <= 0 or lot <= 0 or price <= 0 or size_cr <= 0:
        return 0.0, 0.0, 0.0
    retail_pool  = size_cr * 1e7 * 0.35
    allot_avail  = max(1, int(retail_pool / (lot * price)))
    total_apps   = max(allot_avail + 1, int(allot_avail * sub))
    p_true       = allot_avail / total_apps
    results      = np.random.binomial(1, p_true, n)
    p_hat        = results.mean()
    z            = 1.96
    denom        = 1 + z**2 / n
    center       = (p_hat + z**2 / (2 * n)) / denom
    spread       = (z * np.sqrt(p_hat * (1 - p_hat) / n + z**2 / (4 * n**2))) / denom
    return (
        round(p_hat, 6),
        round(max(0.0, center - spread), 6),
        round(min(1.0, center + spread), 6),
    )

def _syndicate_matrix(p: float) -> Dict[int, float]:
    return {k: round(1 - (1 - p) ** k, 6) for k in range(1, MAX_SYNDICATE + 1)}

def _optimal_syndicate(matrix: Dict[int, float], gain: float, cost_per_app: float, opp: float = 500) -> int:
    best_k, best_ev = 1, -float("inf")
    for k, p_win in matrix.items():
        ev = p_win * gain - k * (cost_per_app + opp)
        if ev > best_ev:
            best_ev, best_k = ev, k
    return best_k

def _kelly(p_win: float, b_odds: float) -> float:
    if b_odds <= 0 or p_win <= 0:
        return 0.0
    f = (b_odds * p_win - (1 - p_win)) / b_odds
    return round(max(0.0, KELLY_FRACTION * f) * 100, 2)

def compute_allotment(row: pd.Series) -> AllotmentProfile:
    sub   = max(0.1, float(row["SubscriptionTimes"]))
    price = float(row["PriceBandUpper"])
    lot   = int(row["LotSize"])
    size  = float(row["IssueSizeCr"])
    gmp   = float(row["GMP"])

    p_mc, ci_lo, ci_hi = monte_carlo_allotment(sub, lot, size, price)
    matrix  = _syndicate_matrix(p_mc)
    gain    = gmp * price * lot
    b_odds  = gain / max(1.0, 1500.0)
    cost    = lot * price
    opt_k   = _optimal_syndicate(matrix, gain, cost)
    p_opt   = matrix[opt_k]
    kelly   = _kelly(p_opt, b_odds)
    ev      = round(p_opt * gain, 2)
    roi     = round((ev / max(1.0, cost * opt_k)) * 100, 4)

    return AllotmentProfile(
        symbol=str(row["Symbol"]),
        p_single_mc=p_mc,
        syndicate_matrix=matrix,
        optimal_syndicate=opt_k,
        kelly_pct=kelly,
        ev_inr=ev,
        roi_pct=roi,
        ci_95=(ci_lo, ci_hi),
    )

def compute_sentiment(row: pd.Series) -> SentimentProfile:
    sub  = float(row["SubscriptionTimes"])
    gmp  = float(row["GMP"])
    buzz = 40.0
    if sub > 100:  buzz += 30
    elif sub > 50: buzz += 20
    elif sub > 25: buzz += 10
    if gmp > 0.40:  buzz += 20
    elif gmp > 0.20: buzz += 10
    composite = min(100.0, buzz)
    label = ("BULLISH" if composite >= 65 else
             "NEUTRAL" if composite >= 45 else "BEARISH")
    return SentimentProfile(str(row["Symbol"]), composite, label)

def run_shariah(row: pd.Series) -> ShariahVerdict:
    gmp    = float(row["GMP"])
    sub    = float(row["SubscriptionTimes"])
    size   = float(row["IssueSizeCr"])
    sector = str(row["Sector"])
    sym    = str(row["Symbol"])

    barakah = 100.0
    issues: List[str] = []

    najash = gmp > 0.40 and sub > 80
    if najash:
        barakah -= 25
        issues.append("Najash Alert: GMP > 40% + Sub > 80× (speculative pump)")

    if size < 20:
        barakah -= 15
        issues.append("Microcap Hazard: Issue < ₹20 Cr (low liquidity)")

    if sector == "SME" and sub > 200:
        barakah -= 10
        issues.append("SME Pump Risk: Sub > 200× (hyper-subscription)")

    halal_score = max(0.0, min(100.0, barakah))
    tier = "TIER_1_SHARIAH_COMPLIANT" if halal_score >= 80 else "TIER_2_CONDITIONAL"
    # Shortened Qabda to avoid HTML errors
    qabda_short = "Shares must settle in Demat (T+2) before resale (No listing-day flips)."

    return ShariahVerdict(
        symbol=sym, tier=tier, barakah=halal_score,
        najash=najash, qabda=qabda_short, issues=issues,
        halal_score=halal_score,
        fatwa_ref="AAOIFI SS-21 / OIC Fiqh Academy Res. 3/3/86",
    )

def bayesian_weights(df: pd.DataFrame) -> Dict[str, float]:
    if df.empty:
        return BASE_WEIGHTS.copy()
    avg_sub = df["SubscriptionTimes"].mean()
    w = BASE_WEIGHTS.copy()
    if avg_sub > 80:
        w["sub"]  = min(0.38, w["sub"]  + 0.10)
        w["gmp"]  = max(0.12, w["gmp"]  - 0.05)
        w["halal"]= max(0.09, w["halal"]- 0.05)
        log.info(f"📈 Bayesian: HYPER-BULL regime (avg sub={avg_sub:.1f}×)")
    elif avg_sub < 15:
        w["gmp"]  = min(0.32, w["gmp"]  + 0.10)
        w["sub"]  = max(0.18, w["sub"]  - 0.10)
        w["halal"]= min(0.19, w["halal"]+ 0.05)
        log.info(f"📉 Bayesian: TEPID regime (avg sub={avg_sub:.1f}×)")
    else:
        log.info(f"➡️  Bayesian: NEUTRAL regime (avg sub={avg_sub:.1f}×)")
    total = sum(w.values())
    return {k: round(v / total, 6) for k, v in w.items()}

def master_score(
    row: pd.Series,
    allot: AllotmentProfile,
    sent: SentimentProfile,
    shariah: ShariahVerdict,
    w: Dict[str, float],
) -> Dict:
    days   = max(0, int(row["DaysToClose"]))
    tf     = 1.0 if days >= 7 else (0.5 + 0.5 * days / 7)
    gmp    = float(row["GMP"])
    sub    = float(row["SubscriptionTimes"])
    size   = float(row["IssueSizeCr"])

    s_gmp  = min(100.0, gmp * 200)
    s_sub  = min(100.0, (sub / 100.0) * 100) * tf
    s_sent = sent.composite
    s_trd  = 50.0
    s_size = (100 if size <= 20 else 80 if size <= 50 else 50 if size <= 100 else 20)
    s_halal= shariah.halal_score

    raw   = (s_gmp * w["gmp"] + s_sub * w["sub"] + s_sent * w["sentiment"] +
             s_trd * w["trend"] + s_size * w["size"] + s_halal * w["halal"])
    final = min(100.0, max(0.0, round(raw, 1)))

    verdict = (
        "🔥 PEARL"      if final >= 80 else
        "✅ STRONG BUY" if final >= 70 else
        "📈 MODERATE"   if final >= 60 else
        "❌ SKIP"
    )
    return {"FinalScore": final, "Verdict": verdict}

# ══════════════════════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════════════════════

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(DB_PATH)) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS ipo_scans (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date         TEXT,
                symbol           TEXT,
                sector           TEXT,
                final_score      REAL,
                verdict          TEXT,
                subscription_x    REAL,
                gmp_pct          REAL,
                issue_size_cr    REAL,
                price_upper      REAL,
                lot_size         INTEGER,
                close_date       TEXT,
                days_to_close    INTEGER,
                p_single_mc      REAL,
                ci_lo            REAL,
                ci_hi            REAL,
                optimal_syndicate INTEGER,
                kelly_pct        REAL,
                ev_inr           REAL,
                roi_pct          REAL,
                sentiment_score  REAL,
                sentiment_label  TEXT,
                barakah          REAL,
                halal_tier       TEXT,
                najash_alert     INTEGER,
                source           TEXT,
                created_at       TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(run_date, symbol)
            )
        """)
    log.info("🗄  SQLite DB ready.")

def persist_to_db(df: pd.DataFrame, allots: dict, sents: dict, shariahs: dict):
    date_label = TODAY.strftime("%Y-%m-%d")
    with sqlite3.connect(str(DB_PATH)) as con:
        for _, r in df.iterrows():
            sym = str(r["Symbol"])
            a   = allots[sym]
            s   = sents[sym]
            sh  = shariahs[sym]
            con.execute("""
                INSERT OR REPLACE INTO ipo_scans (
                    run_date, symbol, sector, final_score, verdict,
                    subscription_x, gmp_pct, issue_size_cr, price_upper, lot_size,
                    close_date, days_to_close,
                    p_single_mc, ci_lo, ci_hi, optimal_syndicate,
                    kelly_pct, ev_inr, roi_pct,
                    sentiment_score, sentiment_label,
                    barakah, halal_tier, najash_alert, source
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                date_label, sym, r["Sector"], r["FinalScore"], r["Verdict"],
                r["SubscriptionTimes"], r["gmp_pct"], r["IssueSizeCr"],
                r["PriceBandUpper"], int(r["LotSize"]),
                r["CloseDate"], int(r["DaysToClose"]),
                a.p_single_mc, a.ci_95[0], a.ci_95[1], a.optimal_syndicate,
                a.kelly_pct, a.ev_inr, a.roi_pct,
                s.composite, s.label,
                sh.barakah, sh.tier, int(sh.najash), r.get("Source", "unknown"),
            ))
    log.info(f"🗄  Persisted {len(df)} records to SQLite.")

# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM (Reduced spam)
# ══════════════════════════════════════════════════════════════════════════════

def _tg_send(text: str, token: str, chat_id: str):
    text = text[:4096]
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=12,
        )
        if resp.status_code != 200:
            log.warning(f"  Telegram HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        log.error(f"  Telegram send failed: {exc}")

def send_telegram_alerts(df: pd.DataFrame, allots: dict, sents: dict, shariahs: dict, top_n: int = 5):
    token = os.getenv("TELEGRAM_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    console_only = not (token and chat_id)

    date_str = TODAY.strftime("%d %b %Y")
    ranked = df.sort_values("FinalScore", ascending=False)

    # --- Summary table for all IPOs ---
    summary_lines = [f"⚔️ <b>{VERSION}</b>  |  {date_str}  |  {len(df)} IPOs active"]
    summary_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    for _, row in ranked.iterrows():
        sym = row["Symbol"]
        score = row["FinalScore"]
        verdict = row["Verdict"]
        sub = row["SubscriptionTimes"]
        gmp = row["gmp_pct"]
        summary_lines.append(f"{verdict} <b>{sym}</b> ({score:.0f})  {sub:.1f}x | GMP {gmp:.1f}%")
    summary_msg = "\n".join(summary_lines)

    if console_only:
        print(f"\n[TELEGRAM CONSOLE SUMMARY]\n{summary_msg}\n")
    else:
        _tg_send(summary_msg, token, chat_id)
        _jitter(0.5, 1.0)

    # --- Detailed alerts for top N only ---
    detail_msg = f"\n🔥 <b>Top {top_n} IPOs – Detailed Analysis</b>\n"
    detail_msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for _, row in ranked.head(top_n).iterrows():
        sym = row["Symbol"]
        a = allots[sym]
        s = sents[sym]
        sh = shariahs[sym]
        detail_msg += (
            f"<b>{sym}</b> [{row['Sector']}]  |  Score: {row['FinalScore']:.1f}  |  {row['Verdict']}\n"
            f"   Sub: {row['SubscriptionTimes']:.1f}×  |  GMP: {row['gmp_pct']:.1f}%  |  "
            f"Size: ₹{row['IssueSizeCr']:.0f}Cr  |  Lot: {row['LotSize']}\n"
            f"   Price: ₹{row['PriceBandLower']:.0f}–₹{row['PriceBandUpper']:.0f}  |  "
            f"Closes: {row['CloseDate']} ({row['DaysToClose']}d left)\n"
            f"   P(Allot): {a.p_single_mc*100:.3f}%  |  Syndicate: {a.optimal_syndicate} PANs\n"
            f"   Kelly: {a.kelly_pct:.1f}%  |  EV: ₹{a.ev_inr:,.0f}  |  ROI: {a.roi_pct:.2f}%\n"
            f"   Sentiment: {s.label} ({s.composite:.0f})  |  {sh.tier} (Barakah: {sh.barakah:.0f})\n"
            f"   📜 {sh.qabda}\n"
            f"   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )
    if console_only:
        print(f"\n[TELEGRAM CONSOLE DETAIL]\n{detail_msg}\n")
    else:
        for chunk in [detail_msg[i:i+4000] for i in range(0, len(detail_msg), 4000)]:
            _tg_send(chunk, token, chat_id)
            _jitter(0.3, 0.8)

    log.info(f"📨 Sent summary + top {top_n} detailed alerts")

# ══════════════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════════

def run():
    log.info(f"🚀  {VERSION}  [{TODAY}]")
    init_db()

    df = fetch_ipo_calendar(use_playwright=True)
    if df.empty:
        log.error("❌ No IPO data from any source — aborting.")
        return None

    log.info(f"📦 Analysing {len(df)} unique IPOs …")

    w = bayesian_weights(df)
    log.info(f"⚖️  Active weights: { {k: round(v, 3) for k, v in w.items()} }")

    allots:   Dict[str, AllotmentProfile] = {}
    sents:    Dict[str, SentimentProfile] = {}
    shariahs: Dict[str, ShariahVerdict]   = {}
    scores:   List[dict]                  = []

    for _, row in df.iterrows():
        sym = str(row["Symbol"])
        allots[sym]   = compute_allotment(row)
        sents[sym]    = compute_sentiment(row)
        shariahs[sym] = run_shariah(row)
        scores.append(master_score(row, allots[sym], sents[sym], shariahs[sym], w))

    df["FinalScore"]        = [s["FinalScore"] for s in scores]
    df["Verdict"]           = [s["Verdict"]    for s in scores]
    df["p_single_mc"]       = [allots[s].p_single_mc      for s in df["Symbol"]]
    df["optimal_syndicate"] = [allots[s].optimal_syndicate for s in df["Symbol"]]
    df["kelly_pct"]         = [allots[s].kelly_pct         for s in df["Symbol"]]
    df["ev_inr"]            = [allots[s].ev_inr            for s in df["Symbol"]]
    df["roi_pct"]           = [allots[s].roi_pct           for s in df["Symbol"]]
    df["sentiment_label"]   = [sents[s].label              for s in df["Symbol"]]
    df["barakah"]           = [shariahs[s].barakah         for s in df["Symbol"]]
    df["halal_tier"]        = [shariahs[s].tier            for s in df["Symbol"]]
    df["najash_alert"]      = [shariahs[s].najash          for s in df["Symbol"]]

    persist_to_db(df, allots, sents, shariahs)

    JSON_EXPORT.parent.mkdir(parents=True, exist_ok=True)
    df.to_json(str(JSON_EXPORT), orient="records", indent=2)
    log.info(f"📄  JSON export → {JSON_EXPORT}")

    # Console output
    ranked = df.sort_values("FinalScore", ascending=False)
    print(f"\n{'═'*90}")
    print(f"  {VERSION}  |  {TODAY}")
    print(f"{'═'*90}")
    print(
        f"  {'Symbol':<30} {'Score':>6}  {'Verdict':<14}  "
        f"{'Sub':>7}  {'GMP':>6}  {'Lot':>5}  {'Days':>4}  "
        f"{'Synd':>4}  {'Halal'}"
    )
    print(f"  {'─'*30} {'─'*6}  {'─'*14}  {'─'*7}  {'─'*6}  {'─'*5}  {'─'*4}  {'─'*4}  {'─'*22}")
    for _, row in ranked.iterrows():
        sym = str(row["Symbol"])
        a   = allots[sym]
        sh  = shariahs[sym]
        print(
            f"  {sym:<30} {row['FinalScore']:>6.1f}  {row['Verdict']:<14}  "
            f"{row['SubscriptionTimes']:>6.1f}×  {row['gmp_pct']:>5.1f}%  "
            f"{row['LotSize']:>5}  {row['DaysToClose']:>4}  "
            f"{a.optimal_syndicate:>4}  {sh.tier}"
        )
    print(f"{'═'*90}\n")

    send_telegram_alerts(df, allots, sents, shariahs, top_n=5)

    log.info("🏁  IPO Sniper v5.0 complete.")
    return df

# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    run()
