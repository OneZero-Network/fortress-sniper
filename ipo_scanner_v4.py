#!/usr/bin/env python3
"""
IPO SNIPER v4.0 – PRODUCTION EDITION
Uses the working fetch engine (NSE API + Playwright) from the standalone test.
"""

import os
import re
import math
import time
import random
import logging
import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup

# Playwright (must be installed)
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# ═══════════════════════════════════════════════════════════
# GLOBAL CONFIGURATION
# ═══════════════════════════════════════════════════════════
IPO_DB_PATH = Path("data/ipo_sniper_v4.db")
FALLBACK_CSV = Path("data/ipo_fallback.csv")
VERSION = "IPO-SNIPER-v4.0-PRODUCTION-FIXED"
MONTE_CARLO_RUNS = 50_000
KELLY_FRACTION = 0.25
MAX_SYNDICATE = 10
SEED = 42
np.random.seed(SEED)

BASE_WEIGHTS = {
    "gmp": 0.22, "sub": 0.28, "sentiment": 0.18,
    "trend": 0.10, "size": 0.08, "halal": 0.14,
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
log = logging.getLogger("IPO-SNIPER-v4")

# ═══════════════════════════════════════════════════════════
# WORKING FETCH ENGINE (copied from your standalone test)
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
    for url in [
        "https://www.nseindia.com",
        "https://www.nseindia.com/market-data/upcoming-issues-ipo",
    ]:
        try:
            sess.get(url, timeout=15)
        except Exception:
            pass
        _jitter(1.5, 2.5)

def _parse_nse_ipo_row(r: dict, sector: str) -> Optional[dict]:
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
    price_text = str(r.get("priceBand", r.get("issuePrice", r.get("price", "100"))))
    prices = re.findall(r"[\d.]+", price_text)
    price_lower = _f(prices[0], 95.0) if prices else 95.0
    price_upper = _f(prices[-1], 100.0) if prices else 100.0
    size = _f(r.get("issueSize", r.get("totalIssueSizeCr", r.get("issueSizeCrores", 50.0))), 50.0)
    if size > 50000:
        size /= 1e7
    lot = _i(r.get("lotSize", r.get("minBidQuantity", 1 if sector == "SME" else 1)))
    if lot <= 0:
        lot = 1000 if sector == "SME" else 50
    sub_text = str(r.get("subscriptionTimes", r.get("subscriptionStatus", "0")))
    sub = _f(re.search(r"[\d.]+", sub_text).group() if re.search(r"[\d.]+", sub_text) else "0", 0.0)
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
        "Symbol": symbol, "Sector": sector,
        "IssueSizeCr": round(size, 2),
        "PriceBandLower": price_lower, "PriceBandUpper": price_upper,
        "LotSize": lot,
        "GMP": 0.0, "gmp_pct": 0.0,
        "SubscriptionTimes": round(sub, 2),
        "CloseDate": close_date.strftime("%Y-%m-%d"),
        "DaysToClose": days_to_close,
        "Source": "nse_api",
    }

def fetch_nse_ipo_api() -> pd.DataFrame:
    sess = _make_session()
    _nse_warmup(sess)
    all_rows = []
    seen_symbols = set()
    endpoints = [
        "https://www.nseindia.com/api/ipo",
        "https://www.nseindia.com/api/emerge-ipo",
        "https://www.nseindia.com/api/otherMarketData?identifier=UPCOMING_IPO",
        "https://www.nseindia.com/api/ipo-current-allotment",
    ]
    for endpoint in endpoints:
        try:
            resp = sess.get(endpoint, timeout=20,
                            headers={"Referer": "https://www.nseindia.com/market-data/upcoming-issues-ipo",
                                     "X-Requested-With": "XMLHttpRequest"})
            if resp.status_code != 200 or len(resp.content) < 20:
                continue
            data = resp.json()
            items = data if isinstance(data, list) else data.get("data", [])
            for item in items:
                sector = "SME" if "emerge" in endpoint else "Mainboard"
                rec = _parse_nse_ipo_row(item, sector)
                if rec and rec["Symbol"] not in seen_symbols:
                    seen_symbols.add(rec["Symbol"])
                    all_rows.append(rec)
            _jitter(1.5, 3.0)
        except Exception as exc:
            log.warning(f"NSE endpoint failed: {exc}")
    if all_rows:
        log.info(f"NSE API: {len(all_rows)} IPOs")
        return pd.DataFrame(all_rows)
    return pd.DataFrame()

# --- Chittorgarh helpers ---
CHITTORGARH_URLS = {
    "SME": "https://www.chittorgarh.com/report/upcoming-ipos-drhp-filed/158/?cat=sme",
    "Mainboard": "https://www.chittorgarh.com/report/upcoming-ipos-drhp-filed/158/",
    "Open_SME": "https://www.chittorgarh.com/report/sme-ipo-subscription-status/10/",
    "Open_Main": "https://www.chittorgarh.com/report/ipo-subscription-status/10/",
}

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

def _parse_chittorgarh_ajax_rows(rows: list, ipo_type: str) -> pd.DataFrame:
    today = datetime.today().date()
    sector = "Mainboard" if ipo_type in ("Mainboard", "Open_Main") else "SME"
    records = []
    for row in rows:
        cells = row if isinstance(row, list) else list(row.values())
        if not cells:
            continue
        clean = [BeautifulSoup(str(c), "html.parser").get_text(strip=True) for c in cells]
        if not clean[0] or len(clean[0]) < 2:
            continue
        symbol = clean[0]
        size = float(re.search(r"[\d.]+", clean[1]).group()) if len(clean) > 1 and re.search(r"[\d.]+", clean[1]) else 50.0
        price = _extract_price_band(clean[2] if len(clean) > 2 else "100")
        lot = int(re.search(r"\d+", clean[3]).group()) if len(clean) > 3 and re.search(r"\d+", clean[3]) else (1000 if sector=="SME" else 50)
        close = _parse_date(clean[4] if len(clean) > 4 else "", today + timedelta(days=10))
        sub = float(re.search(r"[\d.]+", clean[5]).group()) if len(clean) > 5 and re.search(r"[\d.]+", clean[5]) else 0.0
        gmp = float(re.search(r"[\d.]+", clean[6]).group()) / 100 if len(clean) > 6 and re.search(r"[\d.]+", clean[6]) else 0.0
        records.append({
            "Symbol": symbol, "Sector": sector, "IssueSizeCr": round(size, 2),
            "PriceBandLower": price[0], "PriceBandUpper": price[1],
            "LotSize": lot, "GMP": gmp, "gmp_pct": round(gmp*100,2),
            "SubscriptionTimes": round(sub, 2),
            "CloseDate": close.strftime("%Y-%m-%d"),
            "DaysToClose": max(0, (close - today).days),
            "Source": "chittorgarh_ajax",
        })
    return pd.DataFrame(records)

def _parse_chittorgarh_html_table(table, ipo_type: str) -> pd.DataFrame:
    today = datetime.today().date()
    sector = "Mainboard" if "main" in ipo_type.lower() else "SME"
    rows = table.find_all("tr")
    if len(rows) < 2:
        return pd.DataFrame()
    headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th","td"])]
    col = {}
    for i, h in enumerate(headers):
        if any(k in h for k in ("company","issuer","name")): col["sym"] = i
        elif any(k in h for k in ("size","cr","amt")): col["size"] = i
        elif any(k in h for k in ("price","band")): col["price"] = i
        elif any(k in h for k in ("close","end","date")): col["close"] = i
        elif any(k in h for k in ("lot","qty")): col["lot"] = i
        elif "gmp" in h: col["gmp"] = i
        elif any(k in h for k in ("sub","times")): col["sub"] = i
    if "sym" not in col:
        return pd.DataFrame()
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
            return cells[i].get_text(strip=True) if i is not None and i < len(cells) else default
        size = float(re.search(r"[\d.]+", _cell("size","50")).group()) if re.search(r"[\d.]+", _cell("size","50")) else 50.0
        price = _extract_price_band(_cell("price","100"))
        lot = int(re.search(r"\d+", _cell("lot","1000")).group()) if re.search(r"\d+", _cell("lot","1000")) else (1000 if sector=="SME" else 50)
        close = _parse_date(_cell("close",""), today + timedelta(days=10))
        gmp_t = _cell("gmp","0")
        gmp = 0.0
        if gmp_t and re.search(r"[\d.]+", gmp_t):
            gmp_raw = float(re.search(r"[\d.]+", gmp_t).group())
            gmp = gmp_raw / 100 if gmp_raw > 1 else gmp_raw
        sub_t = _cell("sub","0")
        sub = float(re.search(r"[\d.]+", sub_t).group()) if sub_t and re.search(r"[\d.]+", sub_t) else 0.0
        records.append({
            "Symbol": symbol, "Sector": sector, "IssueSizeCr": round(size, 2),
            "PriceBandLower": price[0], "PriceBandUpper": price[1],
            "LotSize": lot, "GMP": gmp, "gmp_pct": round(gmp*100,2),
            "SubscriptionTimes": round(sub, 2),
            "CloseDate": close.strftime("%Y-%m-%d"),
            "DaysToClose": max(0, (close - today).days),
            "Source": "chittorgarh_html",
        })
    return pd.DataFrame(records)

def fetch_chittorgarh_playwright(url: str, ipo_type: str) -> pd.DataFrame:
    if not PLAYWRIGHT_AVAILABLE:
        log.warning("Playwright not installed – skipping")
        return pd.DataFrame()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage"])
            page = browser.new_page(user_agent=_HEADERS["User-Agent"],
                                    extra_http_headers={"Accept-Language": "en-IN,en;q=0.9"})
            intercepted_data = []
            def intercept(response):
                if response.status == 200 and "chittorgarh" in response.url:
                    ct = response.headers.get("content-type","")
                    if "json" in ct or "javascript" in ct:
                        try:
                            body = response.json()
                            rows = body.get("data", body.get("aaData", []))
                            if rows:
                                log.info(f"Playwright intercepted AJAX: {len(rows)} rows from {response.url}")
                                intercepted_data.extend(rows)
                        except Exception:
                            pass
            page.on("response", intercept)
            page.goto(url, wait_until="networkidle", timeout=60000)
            try:
                page.wait_for_selector("table tbody tr td:not(.dataTables_empty)", timeout=15000)
            except Exception:
                pass
            if intercepted_data:
                df = _parse_chittorgarh_ajax_rows(intercepted_data, ipo_type)
                browser.close()
                return df
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            for table in soup.find_all("table"):
                if len(table.find_all("tr")) > 3:
                    df = _parse_chittorgarh_html_table(table, ipo_type)
                    if not df.empty:
                        browser.close()
                        log.info(f"Playwright HTML parse: {len(df)} rows")
                        return df
            browser.close()
    except Exception as e:
        log.warning(f"Playwright error: {e}")
    return pd.DataFrame()

def fetch_chittorgarh_ajax(url: str, ipo_type: str) -> pd.DataFrame:
    sess = _make_session()
    try:
        sess.get(url, timeout=15)
        _jitter(1,2)
    except Exception:
        pass
    post_data = {"draw":"1","start":"0","length":"200","search[value]":"","search[regex]":"false"}
    ajax_candidates = [
        url.rstrip("/") + "?ajax=1",
        url.rstrip("/") + "?draw=1",
        "https://www.chittorgarh.com/ajax/ipo_list.php",
        "https://www.chittorgarh.com/ajax/getIPOList.php",
    ]
    for ajax_url in ajax_candidates:
        try:
            resp = sess.post(ajax_url, data=post_data, timeout=15,
                             headers={"X-Requested-With": "XMLHttpRequest", "Referer": url})
            if resp.status_code == 200 and len(resp.content) > 100:
                deny = resp.headers.get('x-deny-reason', 'none')
                if deny != 'none':
                    continue
                try:
                    data = resp.json()
                    rows_raw = data.get("data", data.get("aaData", []))
                    if rows_raw:
                        log.info(f"AJAX hit: {len(rows_raw)} rows from {ajax_url}")
                        return _parse_chittorgarh_ajax_rows(rows_raw, ipo_type)
                except json.JSONDecodeError:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    table = soup.find("table")
                    if table:
                        return _parse_chittorgarh_html_table(table, ipo_type)
        except Exception:
            pass
    return pd.DataFrame()

def _ensure_fallback_csv() -> pd.DataFrame:
    FALLBACK_CSV.parent.mkdir(parents=True, exist_ok=True)
    if not FALLBACK_CSV.exists():
        today = datetime.today()
        seed = [
            {"Symbol":"Merritronix Ltd","IssueSizeCr":70.03,"PriceBandLower":141,"PriceBandUpper":149,"LotSize":1000,"GMP":0.25,"SubscriptionTimes":45.2,"Sector":"SME","CloseDate":(today+timedelta(3)).strftime("%Y-%m-%d")},
            {"Symbol":"SMR Jewels Ltd","IssueSizeCr":67.23,"PriceBandLower":128,"PriceBandUpper":135,"LotSize":1000,"GMP":0.10,"SubscriptionTimes":12.4,"Sector":"SME","CloseDate":(today+timedelta(5)).strftime("%Y-%m-%d")},
            {"Symbol":"Q-Line Biotech Ltd","IssueSizeCr":214.48,"PriceBandLower":326,"PriceBandUpper":343,"LotSize":50,"GMP":0.40,"SubscriptionTimes":85.3,"Sector":"Mainboard","CloseDate":(today+timedelta(1)).strftime("%Y-%m-%d")},
        ]
        pd.DataFrame(seed).to_csv(FALLBACK_CSV, index=False)
        log.info(f"Created fallback CSV with {len(seed)} IPOs")
    return pd.read_csv(FALLBACK_CSV)

def _enrich_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    today = datetime.today().date()
    defaults = {
        "Symbol":"UNKNOWN","Sector":"SME","IssueSizeCr":50.0,
        "PriceBandLower":95.0,"PriceBandUpper":100.0,"LotSize":1000,
        "GMP":0.0,"gmp_pct":0.0,"SubscriptionTimes":1.0,
        "CloseDate":(today+timedelta(7)).strftime("%Y-%m-%d"),
        "DaysToClose":7,"Source":"unknown",
    }
    for col, val in defaults.items():
        if col not in df.columns:
            df[col] = val
    df["gmp_pct"] = df["GMP"].apply(lambda g: round(float(g)*100,2))
    df["DaysToClose"] = df["CloseDate"].apply(lambda x: max(0, (datetime.strptime(str(x),"%Y-%m-%d").date()-today).days))
    df = df[df["Symbol"].astype(str).str.strip().ne("") & (df["Symbol"].astype(str).str.lower()!="unknown")]
    return df.reset_index(drop=True)

def fetch_ipo_calendar(use_playwright: bool = True) -> pd.DataFrame:
    frames = []
    # A: NSE
    log.info("Strategy A: NSE API")
    nse_df = fetch_nse_ipo_api()
    if not nse_df.empty:
        frames.append(nse_df)
    # B: Chittorgarh
    log.info("Strategy B: Chittorgarh")
    for ipo_type, url in CHITTORGARH_URLS.items():
        log.info(f"  {ipo_type}...")
        ajax_df = fetch_chittorgarh_ajax(url, ipo_type)
        if not ajax_df.empty:
            frames.append(ajax_df)
            continue
        if use_playwright:
            pw_df = fetch_chittorgarh_playwright(url, ipo_type)
            if not pw_df.empty:
                frames.append(pw_df)
        _jitter(1,2)
    if frames:
        combined = pd.concat(frames, ignore_index=True)
        combined = combined.sort_values("SubscriptionTimes", ascending=False).drop_duplicates(subset="Symbol", keep="first").reset_index(drop=True)
        log.info(f"✅ Live fetch: {len(combined)} IPOs")
        return _enrich_dataframe(combined)
    log.warning("No live data – using fallback CSV")
    return _enrich_dataframe(_ensure_fallback_csv())

# ═══════════════════════════════════════════════════════════
# QUANT ENGINE (same as before)
# ═══════════════════════════════════════════════════════════

@dataclass
class AllotmentProfile:
    symbol: str
    p_single_monte_carlo: float
    syndicate_matrix: Dict[int, float]
    optimal_syndicate_size: int
    kelly_fraction_pct: float
    expected_value_inr: float
    roi_expected_pct: float
    confidence_interval_95: Tuple[float, float]

def monte_carlo_allotment(sub_times, lot_size, issue_size_cr, price_upper, n_sim=MONTE_CARLO_RUNS):
    if sub_times <= 0 or lot_size <= 0 or price_upper <= 0:
        return 0.0, 0.0, 0.0
    lot_val = lot_size * price_upper
    retail_pool = issue_size_cr * 1e7 * 0.35
    allot_avail = max(1, int(retail_pool / lot_val))
    total_app = max(allot_avail+1, int(allot_avail * sub_times))
    p_true = allot_avail / total_app
    results = np.random.binomial(1, p_true, n_sim)
    p_hat = results.mean()
    z = 1.96
    denom = 1 + z**2/n_sim
    center = (p_hat + z**2/(2*n_sim)) / denom
    spread = (z * np.sqrt(p_hat*(1-p_hat)/n_sim + z**2/(4*n_sim**2))) / denom
    return round(p_hat,6), max(0,round(center-spread,6)), min(1,round(center+spread,6))

def build_syndicate_matrix(p_single):
    return {k: round(1 - (1-p_single)**k,6) for k in range(1, MAX_SYNDICATE+1)}

def optimal_syndicate_by_ev(matrix, gain, cost_per_app, opp_cost=500):
    best_k, best_ev = 1, -float('inf')
    for k, p_win in matrix.items():
        ev = p_win * gain - k*(cost_per_app + opp_cost)
        if ev > best_ev:
            best_ev, best_k = ev, k
    return best_k

def kelly(p_win, b_odds):
    if b_odds <= 0 or p_win <= 0: return 0.0
    f = (b_odds * p_win - (1-p_win)) / b_odds
    return round(max(0, KELLY_FRACTION * f) * 100, 2)

def compute_allotment(row: pd.Series) -> AllotmentProfile:
    sym = row["Symbol"]
    sub = max(0.1, float(row["SubscriptionTimes"]))
    price = float(row["PriceBandUpper"])
    lot = int(row["LotSize"])
    issue = float(row["IssueSizeCr"])
    gmp = float(row["GMP"])
    p_mc, ci_lo, ci_hi = monte_carlo_allotment(sub, lot, issue, price)
    matrix = build_syndicate_matrix(p_mc)
    gain = gmp * price * lot
    b_odds = gain / max(1, 1500.0)
    cost = lot * price
    opt_k = optimal_syndicate_by_ev(matrix, gain, cost)
    p_opt = matrix[opt_k]
    kelly_pct = kelly(p_opt, b_odds)
    ev = round(p_opt * gain, 2)
    roi = round((ev / max(1, cost * opt_k)) * 100, 2)
    return AllotmentProfile(sym, p_mc, matrix, opt_k, kelly_pct, ev, roi, (ci_lo, ci_hi))

@dataclass
class SentimentProfile:
    symbol: str
    composite_sentiment: float
    sentiment_label: str

def get_sentiment(row: pd.Series) -> SentimentProfile:
    sub = row["SubscriptionTimes"]
    gmp = row["GMP"]
    buzz = 40.0
    if sub > 100: buzz += 30
    elif sub > 50: buzz += 20
    if gmp > 0.40: buzz += 20
    composite = min(100, buzz)
    label = "BULLISH" if composite >= 65 else "NEUTRAL" if composite >= 45 else "BEARISH"
    return SentimentProfile(row["Symbol"], composite, label)

@dataclass
class ShariahVerdict:
    symbol: str
    tier: str
    barakah_index: float
    najash_alert: bool
    qabda_mandate: str
    composite_halal_score: float

def run_shariah(row: pd.Series) -> ShariahVerdict:
    gmp = row["GMP"]
    sub = row["SubscriptionTimes"]
    size = row["IssueSizeCr"]
    barakah = 100.0
    najash = gmp > 0.40 and sub > 80
    if najash:
        barakah -= 25
    if size < 20:
        barakah -= 15
    halal = max(0, min(100, barakah))
    tier = "TIER_1_SHARIAH_COMPLIANT" if halal >= 80 else "TIER_2_CONDITIONAL"
    qabda = "MANDATORY QABDA: Shares must settle in Demat before resale (no listing-day flips)."
    return ShariahVerdict(row["Symbol"], tier, halal, najash, qabda, halal)

def bayesian_weight_update(df: pd.DataFrame) -> Dict[str, float]:
    if df.empty:
        return BASE_WEIGHTS.copy()
    avg_sub = df["SubscriptionTimes"].mean()
    w = BASE_WEIGHTS.copy()
    if avg_sub > 80:
        w["sub"] = min(0.38, w["sub"] + 0.10)
        w["gmp"] = max(0.12, w["gmp"] - 0.05)
    elif avg_sub < 15:
        w["gmp"] = min(0.32, w["gmp"] + 0.10)
        w["sub"] = max(0.18, w["sub"] - 0.10)
    total = sum(w.values())
    return {k: round(v/total, 6) for k,v in w.items()}

def compute_master_score(row, allot, sent, shariah, weights):
    days = max(0, row["DaysToClose"])
    time_factor = 1.0 if days >= 7 else (0.5 + 0.5*days/7)
    gmp = row["GMP"]
    sub = row["SubscriptionTimes"]
    size = row["IssueSizeCr"]
    s_gmp = min(100, gmp*200)
    s_sub = min(100, (sub/100.0)*100) * time_factor
    s_sent = sent.composite_sentiment
    s_trend = 50.0
    s_size = 100 if size <= 20 else 80 if size <= 50 else 50 if size <= 100 else 20
    s_halal = shariah.composite_halal_score
    raw = (s_gmp * weights["gmp"] + s_sub * weights["sub"] + s_sent * weights["sentiment"] +
           s_trend * weights["trend"] + s_size * weights["size"] + s_halal * weights["halal"])
    final = min(100, max(0, round(raw,1)))
    if final >= 80: verdict = "🔥 PEARL"
    elif final >= 70: verdict = "✅ STRONG BUY"
    elif final >= 60: verdict = "📈 MODERATE"
    else: verdict = "❌ SKIP"
    return {"FinalScore": final, "Verdict": verdict}

# ═══════════════════════════════════════════════════════════
# DATABASE & TELEGRAM
# ═══════════════════════════════════════════════════════════

def init_db():
    IPO_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(IPO_DB_PATH)) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS ipo_analysis_v4 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date TEXT, symbol TEXT, final_score REAL, verdict TEXT,
                p_single_mc REAL, optimal_syndicate INTEGER, kelly_pct REAL,
                ev_inr REAL, roi_pct REAL,
                sentiment_composite REAL, sentiment_label TEXT,
                barakah_index REAL, shariah_tier TEXT, najash_alert INTEGER,
                source TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(run_date, symbol)
            )
        """)
    log.info("Database initialised.")

def send_telegram(msg: str):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print(f"\n[TELEGRAM CONSOLE]\n{msg}\n")
        return
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                      timeout=10)
    except Exception as e:
        log.error(f"Telegram error: {e}")

# ═══════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR
# ═══════════════════════════════════════════════════════════

def run_ipo_sniper_v4():
    log.info(f"🚀 Starting {VERSION}")
    init_db()
    df = fetch_ipo_calendar(use_playwright=True)   # use playwright as in working test
    if df.empty:
        log.error("No IPO data – aborting.")
        return

    weights = bayesian_weight_update(df)
    log.info(f"⚖️ Weights: {weights}")

    allotments = {}
    sentiments = {}
    shariahs = {}
    scores = []

    for _, row in df.iterrows():
        sym = row["Symbol"]
        allotments[sym] = compute_allotment(row)
        sentiments[sym] = get_sentiment(row)
        shariahs[sym] = run_shariah(row)
        sc = compute_master_score(row, allotments[sym], sentiments[sym], shariahs[sym], weights)
        scores.append(sc)

    df["FinalScore"] = [s["FinalScore"] for s in scores]
    df["Verdict"] = [s["Verdict"] for s in scores]
    df["p_single_mc"] = [allotments[s].p_single_monte_carlo for s in df["Symbol"]]
    df["optimal_syndicate"] = [allotments[s].optimal_syndicate_size for s in df["Symbol"]]
    df["kelly_pct"] = [allotments[s].kelly_fraction_pct for s in df["Symbol"]]
    df["ev_inr"] = [allotments[s].expected_value_inr for s in df["Symbol"]]
    df["roi_pct"] = [allotments[s].roi_expected_pct for s in df["Symbol"]]
    df["sentiment_label"] = [sentiments[s].sentiment_label for s in df["Symbol"]]
    df["barakah_index"] = [shariahs[s].barakah_index for s in df["Symbol"]]
    df["HalalTier"] = [shariahs[s].tier for s in df["Symbol"]]
    df["najash_alert"] = [shariahs[s].najash_alert for s in df["Symbol"]]

    date_label = datetime.today().strftime("%Y-%m-%d")
    with sqlite3.connect(str(IPO_DB_PATH)) as con:
        for _, r in df.iterrows():
            con.execute("""
                INSERT OR REPLACE INTO ipo_analysis_v4 (
                    run_date, symbol, final_score, verdict,
                    p_single_mc, optimal_syndicate, kelly_pct,
                    ev_inr, roi_pct, sentiment_composite, sentiment_label,
                    barakah_index, shariah_tier, najash_alert, source
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                date_label, r["Symbol"], r["FinalScore"], r["Verdict"],
                r["p_single_mc"], int(r["optimal_syndicate"]), r["kelly_pct"],
                r["ev_inr"], r["roi_pct"],
                sentiments[r["Symbol"]].composite_sentiment,
                r["sentiment_label"], r["barakah_index"],
                r["HalalTier"], int(r["najash_alert"]),
                r.get("Source", "unknown")
            ))

    # Console output
    print("\n" + "="*70)
    print(f"  {VERSION}  |  {date_label}")
    print("="*70)
    print(f"  {'Symbol':<28} {'Score':>6}  {'Verdict':<14}  {'Sub':>7}  {'GMP':>6}  {'Synd':>4}  {'Halal'}")
    print(f"  {'─'*28} {'─'*6}  {'─'*14}  {'─'*7}  {'─'*6}  {'─'*4}  {'─'*20}")

    for _, row in df.sort_values("FinalScore", ascending=False).iterrows():
        sym = row["Symbol"]
        a = allotments[sym]
        sh = shariahs[sym]
        print(f"  {sym:<28} {row['FinalScore']:>6.1f}  {row['Verdict']:<14}  "
              f"{row['SubscriptionTimes']:>6.1f}x  {row['gmp_pct']:>5.1f}%  "
              f"{a.optimal_syndicate_size:>4}  {sh.tier}")

    # Telegram alerts
    send_telegram(f"⚔️ <b>{VERSION}</b> | {date_label}\n📊 {len(df)} IPOs analysed\n━━━━━━━━━━━━━━━━━━━")
    for _, row in df.sort_values("FinalScore", ascending=False).iterrows():
        sym = row["Symbol"]
        a = allotments[sym]
        s = sentiments[sym]
        sh = shariahs[sym]
        msg = (
            f"<b>{sym}</b> ➜ {row['Verdict']} ({row['FinalScore']}/100)\n"
            f"   📊 Sub: {row['SubscriptionTimes']:.1f}x | GMP: {row['gmp_pct']:.1f}%\n"
            f"   🎲 {a.optimal_syndicate_size} PANs → P(allot)={a.p_single_monte_carlo*100:.3f}%\n"
            f"   💰 Kelly: {a.kelly_fraction_pct:.1f}% | EV: ₹{a.expected_value_inr:,.0f}\n"
            f"   🕌 {sh.tier} | {s.sentiment_label}\n"
            f"   📅 Closes: {row['DaysToClose']} days left"
        )
        send_telegram(msg)

    log.info("🏁 IPO Sniper v4 complete.")

if __name__ == "__main__":
    run_ipo_sniper_v4()
