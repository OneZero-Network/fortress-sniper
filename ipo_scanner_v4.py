#!/usr/bin/env python3
"""
IPO Data Fetcher – with status detection & strong deduplication.
"""

import json
import re
import time
import logging
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Optional, List, Dict

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

CHROME_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}

# ──────────────────────────────────────────────────────────────────────────────
# Helper: date parsing & status calculation
# ──────────────────────────────────────────────────────────────────────────────
def parse_date(date_str: str) -> Optional[datetime]:
    """Parse various date formats (DD MMM YYYY, YYYY-MM-DD, DD-MM-YYYY)."""
    if not date_str or date_str.lower() in ("to be announced", "tba", ""):
        return None
    date_str = re.sub(r"[^\w\s-]", "", date_str).strip()
    for fmt in ("%d %b %Y", "%Y-%m-%d", "%d-%m-%Y", "%d %B %Y", "%b %d %Y"):
        try:
            return datetime.strptime(date_str, fmt)
        except:
            continue
    return None

def compute_status(ipo: dict, today: datetime = None) -> str:
    """Return: 'Open', 'Upcoming', 'Closed', 'Listed', or 'Unknown'."""
    if today is None:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    open_dt = parse_date(ipo.get("open_date", ""))
    close_dt = parse_date(ipo.get("close_date", ""))
    listing_dt = parse_date(ipo.get("listing_date", ""))

    # If listing date is in the past → Listed
    if listing_dt and listing_dt < today:
        return "Listed"
    # If close date is in the past and no listing date → Closed
    if close_dt and close_dt < today:
        return "Closed"
    # If open date is today or in the past, and close date future/open → Open
    if open_dt and open_dt <= today and (not close_dt or close_dt >= today):
        return "Open"
    # If open date is in the future → Upcoming
    if open_dt and open_dt > today:
        return "Upcoming"
    # Fallback: check if any date suggests upcoming
    if (open_dt or close_dt) and (not close_dt or close_dt > today):
        return "Upcoming"
    return "Unknown"

# ──────────────────────────────────────────────────────────────────────────────
# SOURCE A – Chittorgarh
# ──────────────────────────────────────────────────────────────────────────────
def fetch_chittorgarh() -> List[Dict]:
    log.info("━━ SOURCE A: Chittorgarh ━━")
    results = []
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows"})
        r = scraper.get("https://www.chittorgarh.com/ipo/ipo_dashboard.asp", headers=CHROME_HEADERS, timeout=20)
        if r.status_code != 200:
            return results
        soup = BeautifulSoup(r.text, "lxml")
        for table in soup.find_all("table", class_="table"):
            for row in table.find_all("tr")[1:]:
                cols = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cols) >= 4:
                    results.append({
                        "source": "Chittorgarh",
                        "name": cols[0],
                        "open_date": cols[1] if len(cols) > 1 else "",
                        "close_date": cols[2] if len(cols) > 2 else "",
                        "issue_price": cols[3] if len(cols) > 3 else "",
                        "lot_size": cols[4] if len(cols) > 4 else "",
                        "issue_size": cols[5] if len(cols) > 5 else "",
                    })
        log.info(f"  ✓ Chittorgarh: {len(results)} IPOs")
    except Exception as e:
        log.warning(f"  Chittorgarh error: {e}")
    return results

# ──────────────────────────────────────────────────────────────────────────────
# SOURCE B – Investorgain
# ──────────────────────────────────────────────────────────────────────────────
def fetch_investorgain() -> List[Dict]:
    log.info("━━ SOURCE B: Investorgain ━━")
    results = []
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows"}, delay=5)
        r = scraper.get("https://investorgain.com/report/live-ipo-gmp/331/", headers=CHROME_HEADERS, timeout=30)
        if r.status_code != 200:
            return results
        soup = BeautifulSoup(r.text, "lxml")
        table = soup.find("table", id=re.compile(r"ipo", re.I)) or soup.find("table")
        if not table:
            return results
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        for row in table.find_all("tr")[1:]:
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            if not cols:
                continue
            entry = {"source": "Investorgain", "name": cols[0]}
            for i, h in enumerate(headers):
                if i >= len(cols):
                    break
                if "open" in h:
                    entry["open_date"] = cols[i]
                elif "close" in h:
                    entry["close_date"] = cols[i]
                elif "gmp" in h:
                    entry["gmp"] = cols[i]
                elif "status" in h:
                    entry["status_raw"] = cols[i]
            results.append(entry)
        log.info(f"  ✓ Investorgain: {len(results)} IPOs")
    except Exception as e:
        log.warning(f"  Investorgain error: {e}")
    return results

# ──────────────────────────────────────────────────────────────────────────────
# SOURCE C – NSE (try curl_cffi first, then fallback)
# ──────────────────────────────────────────────────────────────────────────────
def fetch_nse() -> List[Dict]:
    log.info("━━ SOURCE C: NSE (curl_cffi + fallback) ━━")
    results = []
    # Try using curl_cffi (better TLS fingerprint)
    try:
        from curl_cffi import requests as curl_requests
        session = curl_requests.Session(impersonate="chrome124")
        # Warmup
        session.get("https://www.nseindia.com", headers=CHROME_HEADERS, timeout=15)
        time.sleep(1)
        session.get("https://www.nseindia.com/market-data/all-upcoming-issues-ipo", headers=CHROME_HEADERS, timeout=15)
        time.sleep(1)
        resp = session.get("https://www.nseindia.com/api/ipo-current-allotment", headers=CHROME_HEADERS, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            results = _parse_nse_json(data)
            log.info(f"  ✓ NSE (curl_cffi): {len(results)} IPOs")
            return results
    except ImportError:
        log.info("  curl_cffi not installed, skipping NSE advanced.")
    except Exception as e:
        log.warning(f"  NSE curl_cffi error: {e}")

    # Fallback to Playwright with HTTP/1.1
    try:
        from playwright.sync_api import sync_playwright
        captured = []
        def handle_response(response):
            if "nseindia.com/api" in response.url and response.status == 200:
                try:
                    captured.append(response.json())
                except:
                    pass
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--disable-http2", "--no-sandbox"])
            ctx = browser.new_context(user_agent=CHROME_HEADERS["User-Agent"])
            page = ctx.new_page()
            page.on("response", handle_response)
            page.goto("https://www.nseindia.com/market-data/all-upcoming-issues-ipo", wait_until="commit", timeout=30000)
            time.sleep(5)
            browser.close()
        for data in captured:
            results.extend(_parse_nse_json(data))
        log.info(f"  ✓ NSE (Playwright): {len(results)} IPOs")
    except Exception as e:
        log.warning(f"  NSE fallback error: {e}")
    return results

def _parse_nse_json(data) -> List[Dict]:
    items = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                items.append({
                    "source": "NSE",
                    "name": item.get("companyName") or item.get("symbol", ""),
                    "open_date": item.get("openDate") or item.get("bidStartDate", ""),
                    "close_date": item.get("closeDate") or item.get("bidEndDate", ""),
                    "issue_price": item.get("issuePrice", ""),
                    "listing_date": item.get("listingDate", ""),
                })
    elif isinstance(data, dict):
        for key in ["data", "ipoData", "upcomingIPO", "currentIPO", "allIpo"]:
            if key in data:
                return _parse_nse_json(data[key])
    return items

# ──────────────────────────────────────────────────────────────────────────────
# SOURCE D – Screener.in
# ──────────────────────────────────────────────────────────────────────────────
def fetch_screener() -> List[Dict]:
    log.info("━━ SOURCE D: Screener.in ━━")
    results = []
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_context(user_agent=CHROME_HEADERS["User-Agent"]).new_page()
            page.goto("https://www.screener.in/ipo/recent/", wait_until="domcontentloaded", timeout=25000)
            page.wait_for_selector("table", timeout=10000)
            html = page.content()
            browser.close()
        soup = BeautifulSoup(html, "lxml")
        results = _parse_generic_ipo_tables(soup, source="Screener")
        log.info(f"  ✓ Screener: {len(results)} IPOs")
    except Exception as e:
        log.warning(f"  Screener error: {e}")
    return results

# ──────────────────────────────────────────────────────────────────────────────
# SOURCE E – Groww (API intercept)
# ──────────────────────────────────────────────────────────────────────────────
def fetch_groww() -> List[Dict]:
    log.info("━━ SOURCE E: Groww (API intercept) ━━")
    results = []
    try:
        from playwright.sync_api import sync_playwright
        captured = []
        def handle_response(response):
            url = response.url
            if any(kw in url for kw in ["/ipos", "/ipo/detail", "charter/v3", "ipo/list"]):
                try:
                    body = response.json()
                    captured.append(body)
                    log.info(f"  Groww intercepted: {url}")
                except:
                    pass
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            ctx = browser.new_context(user_agent=CHROME_HEADERS["User-Agent"], viewport={"width": 1366, "height": 768})
            page = ctx.new_page()
            page.on("response", handle_response)
            page.goto("https://groww.in/ipo", wait_until="domcontentloaded", timeout=30000)
            time.sleep(8)
            browser.close()
        for body in captured:
            results.extend(_parse_groww_json(body))
        if not results:
            results = _fetch_generic_playwright("https://groww.in/ipo", "Groww", wait_ms=8000)
        log.info(f"  ✓ Groww: {len(results)} IPOs")
    except Exception as e:
        log.warning(f"  Groww error: {e}")
    return results

def _parse_groww_json(data) -> List[Dict]:
    items = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and any(k in item for k in ("ipoName", "companyName", "name")):
                items.append({
                    "source": "Groww",
                    "name": item.get("ipoName") or item.get("companyName") or item.get("name", ""),
                    "open_date": item.get("openDate") or item.get("startDate", ""),
                    "close_date": item.get("closeDate") or item.get("endDate", ""),
                    "issue_price": item.get("issuePrice") or item.get("priceRange", ""),
                    "lot_size": item.get("lotSize") or item.get("minOrderQty", ""),
                    "gmp": item.get("gmp") or item.get("greyMarketPremium", ""),
                    "listing_date": item.get("listingDate", ""),
                })
    elif isinstance(data, dict):
        for key in ["data", "ipos", "ipoList", "upcoming", "open", "result"]:
            if key in data:
                items.extend(_parse_groww_json(data[key]))
    return items

# ──────────────────────────────────────────────────────────────────────────────
# SOURCE F – IndiaTrade (fix duplicate rows)
# ──────────────────────────────────────────────────────────────────────────────
def fetch_indiatrade() -> List[Dict]:
    log.info("━━ SOURCE F: IndiaTrade ━━")
    results = []
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows"})
        r = scraper.get("https://ipo.indiratrade.com/Home", headers=CHROME_HEADERS, timeout=20)
        if r.status_code == 200 and len(r.text) > 2000:
            soup = BeautifulSoup(r.text, "lxml")
            # IndiaTrade often repeats the same IPO in multiple rows – use a set to dedup
            seen = set()
            for row in soup.select("table tr"):
                cols = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cols) >= 2:
                    name = cols[0]
                    # Remove trailing " (SME IPO)" etc for dedup key
                    clean_name = re.sub(r"\s*\(?SME\s+IPO\)?\s*", "", name, flags=re.I).strip()
                    if clean_name and clean_name not in seen:
                        seen.add(clean_name)
                        entry = {"source": "IndiaTrade", "name": name}
                        for i, col in enumerate(cols[1:], start=1):
                            col_lower = col.lower()
                            if "price" in col_lower or "₹" in col:
                                entry["issue_price"] = col
                            elif "lot" in col_lower:
                                entry["lot_size"] = col
                            elif "open" in col_lower:
                                entry["open_date"] = col
                            elif "close" in col_lower:
                                entry["close_date"] = col
                            elif "gmp" in col_lower:
                                entry["gmp"] = col
                        results.append(entry)
        if not results:
            results = _fetch_generic_playwright("https://ipo.indiratrade.com/Home", "IndiaTrade", wait_ms=5000)
        log.info(f"  ✓ IndiaTrade: {len(results)} IPOs")
    except Exception as e:
        log.warning(f"  IndiaTrade error: {e}")
    return results

# ──────────────────────────────────────────────────────────────────────────────
# Generic table parser and Playwright helper
# ──────────────────────────────────────────────────────────────────────────────
def _parse_generic_ipo_tables(soup: BeautifulSoup, source: str) -> List[Dict]:
    results = []
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if not any(kw in " ".join(headers) for kw in ["ipo", "company", "open", "price", "lot"]):
            continue
        for row in table.find_all("tr")[1:]:
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            if not cols or not cols[0]:
                continue
            entry = {"source": source, "name": cols[0]}
            for i, h in enumerate(headers):
                if i >= len(cols):
                    break
                if "open" in h:
                    entry["open_date"] = cols[i]
                elif "close" in h:
                    entry["close_date"] = cols[i]
                elif "price" in h:
                    entry["issue_price"] = cols[i]
                elif "lot" in h:
                    entry["lot_size"] = cols[i]
                elif "gmp" in h:
                    entry["gmp"] = cols[i]
                elif "list" in h:
                    entry["listing_date"] = cols[i]
            results.append(entry)
    return results

def _fetch_generic_playwright(url: str, source: str, wait_ms: int = 5000) -> List[Dict]:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(wait_ms)
            html = page.content()
            browser.close()
        soup = BeautifulSoup(html, "lxml")
        return _parse_generic_ipo_tables(soup, source=source)
    except Exception as e:
        log.warning(f"  Generic PW [{source}] error: {e}")
        return []

# ──────────────────────────────────────────────────────────────────────────────
# Deduplication (strong, with status later)
# ──────────────────────────────────────────────────────────────────────────────
def normalise_name(name: str) -> str:
    if not name:
        return ""
    name = name.lower().strip()
    # Remove common legal suffixes and extra info
    name = re.sub(r"\b(limited|ltd|pvt|private|public|co\.?|inc|corp|sme ipo|\(sme ipo\)|\(sme\)|sme)", "", name)
    name = re.sub(r"[^\w\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name

def are_same_ipo(a: Dict, b: Dict) -> bool:
    name_a = normalise_name(a.get("name", ""))
    name_b = normalise_name(b.get("name", ""))
    if not name_a or not name_b:
        return False
    if name_a == name_b:
        return True
    # Fuzzy match > 0.85 and overlapping dates (if both have them)
    if SequenceMatcher(None, name_a, name_b).ratio() > 0.85:
        open_a = a.get("open_date", "")
        open_b = b.get("open_date", "")
        if open_a and open_b and open_a != open_b:
            return False
        return True
    return False

def deduplicate(all_results: List[Dict]) -> List[Dict]:
    # First, remove exact duplicates within same source (using normalised name)
    unique_by_source = {}
    for item in all_results:
        src = item["source"]
        norm = normalise_name(item.get("name", ""))
        key = (src, norm)
        if key not in unique_by_source or len(item) > len(unique_by_source[key]):
            unique_by_source[key] = item
    unique_list = list(unique_by_source.values())

    # Then merge across sources
    merged = []
    for item in unique_list:
        found = False
        for existing in merged:
            if are_same_ipo(existing, item):
                # Merge fields: prefer non-empty values
                existing["source"] = f"{existing.get('source','')}, {item.get('source','')}".strip(", ")
                for k, v in item.items():
                    if v and not existing.get(k):
                        existing[k] = v
                found = True
                break
        if not found:
            merged.append(item)
    return merged

# ──────────────────────────────────────────────────────────────────────────────
# Output with status
# ──────────────────────────────────────────────────────────────────────────────
def print_results(results: List[Dict]):
    if not results:
        print("\n⚠️  No IPO data collected.\n")
        return

    # Compute status for each IPO
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    for ipo in results:
        ipo["status"] = compute_status(ipo, today)

    # Group by status for better readability
    groups = {"Open": [], "Upcoming": [], "Closed": [], "Listed": [], "Unknown": []}
    for ipo in results:
        groups[ipo["status"]].append(ipo)

    print(f"\n{'═'*70}")
    print(f"  IPO DATA  —  fetched {datetime.now().strftime('%d %b %Y %H:%M')}")
    print(f"  Total unique IPOs: {len(results)}")
    print(f"{'═'*70}\n")

    for status, items in groups.items():
        if not items:
            continue
        print(f"  ◆ {status.upper()} ({len(items)})")
        print(f"  {'─'*66}")
        for ipo in items:
            name = ipo.get("name", "N/A")
            dates = ""
            if ipo.get("open_date") or ipo.get("close_date"):
                dates = f"  {ipo.get('open_date','')} → {ipo.get('close_date','')}"
            price = f"  ₹{ipo.get('issue_price','')}" if ipo.get("issue_price") else ""
            lot = f"  Lot:{ipo.get('lot_size','')}" if ipo.get("lot_size") else ""
            gmp = f"  GMP:{ipo.get('gmp','')}" if ipo.get("gmp") else ""
            listing = f"  Listing:{ipo.get('listing_date','')}" if ipo.get("listing_date") else ""
            src = f"  [{ipo.get('source','')}]"
            print(f"  • {name}")
            if any([dates, price, lot, gmp, listing]):
                print(f"    {dates}{price}{lot}{gmp}{listing}")
            print(f"    {src}")
        print()

def save_json(results: List[Dict], path: str = "ipo_data.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"  💾 Saved → {path}")

# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────
def main():
    all_results = []
    all_results += fetch_chittorgarh()
    all_results += fetch_investorgain()
    all_results += fetch_nse()
    all_results += fetch_screener()
    all_results += fetch_groww()
    all_results += fetch_indiatrade()

    merged = deduplicate(all_results)
    print_results(merged)
    save_json(merged)

if __name__ == "__main__":
    main()
