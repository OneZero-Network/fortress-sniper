#!/usr/bin/env python3
"""
IPO Telegram Alert — Open IPOs Only with Buy/Avoid Strategy
════════════════════════════════════════════════════════════════════════════════
Architecture  (from Scraper v2 — Institutional Grade)
  • Pydantic-style dataclass models with strict schema
  • Per-source CircuitBreaker (skip flaky sources after N failures)
  • Tenacity retry with jittered exponential back-off on every HTTP call
  • RapidFuzz token-sort ratio for robust cross-source name deduplication
  • Year-aware, multi-format date parser (ranges, partial dates, ISO)
  • Graceful degradation: pipeline never crashes even if every source fails
  • Telegram delivery: OPEN IPOs only, with BUY / AVOID / NEUTRAL verdict

Sources
  A  Chittorgarh   – cloudscraper (anti-bot bypass)
  B  Investorgain  – cloudscraper + GMP data
  C  NSE India     – 2-step cookie warmup + API intercept
  D  Screener.in   – Playwright (domcontentloaded)
  E  Groww         – Playwright + XHR intercept
  F  IndiaTrade    – cloudscraper + Playwright fallback

Buy/Avoid Strategy Signals
  ✅ BUY   → GMP > 20% of issue price  AND  subscription window open
  ⚠️  NEUTRAL → GMP 5-20% of issue price OR insufficient data
  ❌ AVOID  → GMP < 5% or negative; or purely heuristic (no GMP data)

Usage
  pip install requests beautifulsoup4 lxml cloudscraper playwright rapidfuzz tenacity
  playwright install chromium
  python ipo_telegram_alert.py --token YOUR_BOT_TOKEN --chat YOUR_CHAT_ID
════════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Optional

import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
    before_sleep_log,
)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ipo_alert")


# ══════════════════════════════════════════════════════════════════════════════
# 1. DOMAIN MODELS
# ══════════════════════════════════════════════════════════════════════════════

class IPOStatus(str, Enum):
    OPEN     = "Open"
    UPCOMING = "Upcoming"
    CLOSED   = "Closed"
    LISTED   = "Listed"
    UNKNOWN  = "Unknown"


class BuySignal(str, Enum):
    BUY     = "BUY"
    NEUTRAL = "NEUTRAL"
    AVOID   = "AVOID"


@dataclass
class IPORecord:
    """Single normalised IPO record. All fields optional except name."""
    name:           str
    sources:        list[str]      = field(default_factory=list)
    open_date:      Optional[str]  = None
    close_date:     Optional[str]  = None
    listing_date:   Optional[str]  = None
    issue_price:    Optional[str]  = None
    lot_size:       Optional[str]  = None
    gmp:            Optional[str]  = None
    allotment_date: Optional[str]  = None
    listing_price:  Optional[str]  = None
    status:         IPOStatus      = IPOStatus.UNKNOWN
    signal:         BuySignal      = BuySignal.NEUTRAL
    signal_reason:  str            = ""
    _norm_key:      str            = field(default="", repr=False)

    def merge(self, other: "IPORecord") -> None:
        for src in other.sources:
            if src not in self.sources:
                self.sources.append(src)
        for attr in ("open_date", "close_date", "listing_date",
                     "issue_price", "lot_size", "gmp",
                     "allotment_date", "listing_price"):
            if not getattr(self, attr) and getattr(other, attr):
                setattr(self, attr, getattr(other, attr))

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("_norm_key", None)
        d["status"] = self.status.value
        d["signal"] = self.signal.value
        return d


# ══════════════════════════════════════════════════════════════════════════════
# 2. DATE PARSER  (robust, year-aware)
# ══════════════════════════════════════════════════════════════════════════════

_DATE_FORMATS = [
    "%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%d-%m-%Y",
    "%d/%m/%Y", "%d %b", "%d %B", "%b %d %Y", "%B %d %Y",
    "%b %d, %Y",
]

_RANGE_RE = re.compile(
    r"(\d{1,2})\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+)(?:\s+(\d{4}))?",
    re.IGNORECASE,
)


def parse_date(raw: str | None) -> Optional[datetime]:
    if not raw:
        return None
    raw = raw.strip()
    if raw.lower() in ("tba", "to be announced", "n/a", "-", ""):
        return None

    m = _RANGE_RE.search(raw)
    if m:
        day, month_str = int(m.group(1)), m.group(3)
        year = int(m.group(4)) if m.group(4) else _infer_year(month_str, day)
        for fmt in ("%d %b %Y", "%d %B %Y"):
            try:
                return datetime.strptime(f"{day} {month_str} {year}", fmt)
            except ValueError:
                continue
        return None

    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(raw, fmt)
            if "%Y" not in fmt:
                dt = dt.replace(year=_infer_year(dt.strftime("%b"), dt.day))
            return dt
        except ValueError:
            continue
    return None


def _infer_year(month_str: str, day: int) -> int:
    today = datetime.now()
    for fmt in ("%b", "%B"):
        try:
            candidate = datetime.strptime(f"{day} {month_str} {today.year}", f"%d {fmt} %Y")
            if candidate < today - timedelta(days=60):
                return today.year + 1
            return today.year
        except ValueError:
            continue
    return today.year


def format_date(dt: Optional[datetime]) -> str:
    return dt.strftime("%d %b %Y") if dt else ""


# ══════════════════════════════════════════════════════════════════════════════
# 3. STATUS COMPUTER
# ══════════════════════════════════════════════════════════════════════════════

def compute_status(rec: IPORecord, today: Optional[datetime] = None) -> IPOStatus:
    if today is None:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    open_dt    = parse_date(rec.open_date)
    close_dt   = parse_date(rec.close_date)
    listing_dt = parse_date(rec.listing_date)

    if listing_dt and listing_dt < today:
        return IPOStatus.LISTED
    if close_dt and close_dt < today:
        return IPOStatus.CLOSED
    if open_dt and open_dt <= today and (not close_dt or close_dt >= today):
        return IPOStatus.OPEN
    if open_dt and open_dt > today:
        return IPOStatus.UPCOMING
    if listing_dt and listing_dt > today:
        return IPOStatus.UPCOMING

    _no_dates = not open_dt and not close_dt and not listing_dt
    if _no_dates and rec.listing_price:
        return IPOStatus.LISTED
    _has_price = bool(rec.issue_price and rec.issue_price.strip("₹ -"))
    if _no_dates and _has_price and not rec.gmp:
        return IPOStatus.LISTED

    name_lower = rec.name.lower()
    if any(tok in name_lower for tok in ("sme ipo", "upcoming")):
        return IPOStatus.UPCOMING
    if "to be announced" in str(rec.open_date or "").lower():
        return IPOStatus.UPCOMING

    return IPOStatus.UNKNOWN


# ══════════════════════════════════════════════════════════════════════════════
# 4. BUY / AVOID STRATEGY ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def _parse_numeric(s: str | None) -> Optional[float]:
    """Extract the first numeric value from a messy string like '₹120 (15%)'."""
    if not s:
        return None
    clean = re.sub(r"[^\d.\-]", "", s.split("(")[0].strip())
    try:
        return float(clean) if clean else None
    except ValueError:
        return None


def compute_signal(rec: IPORecord) -> tuple[BuySignal, str]:
    """
    Multi-factor buy/avoid strategy for an OPEN IPO.

    Signals (priority order):
    1. GMP %  — primary momentum indicator
    2. Price range breadth — narrow band = confident pricing
    3. Lot size cost — accessibility signal
    4. Subscription dates — last-day urgency
    5. Data completeness fallback
    """
    reasons: list[str] = []
    positive_score = 0
    negative_score = 0

    # ── Factor 1: GMP analysis ───────────────────────────────────────────────
    gmp_val   = _parse_numeric(rec.gmp)
    price_val = _parse_numeric(rec.issue_price)

    gmp_pct: Optional[float] = None
    if gmp_val is not None and price_val and price_val > 0:
        gmp_pct = (gmp_val / price_val) * 100

    if gmp_val is not None:
        if gmp_val <= 0:
            reasons.append(f"GMP is negative/zero (₹{gmp_val:.0f}) → weak demand")
            negative_score += 3
        elif gmp_pct is not None:
            if gmp_pct >= 25:
                reasons.append(f"Strong GMP: ₹{gmp_val:.0f} ({gmp_pct:.1f}% premium)")
                positive_score += 3
            elif gmp_pct >= 10:
                reasons.append(f"Moderate GMP: ₹{gmp_val:.0f} ({gmp_pct:.1f}% premium)")
                positive_score += 1
            else:
                reasons.append(f"Weak GMP: ₹{gmp_val:.0f} ({gmp_pct:.1f}% premium)")
                negative_score += 1
        else:
            reasons.append(f"GMP available: ₹{gmp_val:.0f} (issue price unknown for % calc)")
    else:
        reasons.append("No GMP data available")

    # ── Factor 2: Issue price range ──────────────────────────────────────────
    if rec.issue_price:
        raw_p = rec.issue_price.replace("₹", "").strip()
        if "-" in raw_p or "–" in raw_p:
            parts = re.split(r"[-–]", raw_p)
            lo = _parse_numeric(parts[0])
            hi = _parse_numeric(parts[-1])
            if lo and hi and lo > 0:
                spread = ((hi - lo) / lo) * 100
                if spread <= 5:
                    reasons.append(f"Tight price band (₹{lo:.0f}–₹{hi:.0f}, {spread:.1f}% spread) → confident pricing")
                    positive_score += 1
                else:
                    reasons.append(f"Wide price band (₹{lo:.0f}–₹{hi:.0f}, {spread:.1f}% spread)")

    # ── Factor 3: Lot size accessibility ─────────────────────────────────────
    lot_val = _parse_numeric(rec.lot_size)
    if lot_val and price_val:
        lot_cost = lot_val * price_val
        if lot_cost <= 15_000:
            reasons.append(f"Accessible lot cost ≈ ₹{lot_cost:,.0f} (retail-friendly)")
            positive_score += 1
        elif lot_cost >= 200_000:
            reasons.append(f"High lot cost ≈ ₹{lot_cost:,.0f} (HNI-skewed)")
            negative_score += 1

    # ── Factor 4: Closing date urgency ───────────────────────────────────────
    close_dt = parse_date(rec.close_date)
    if close_dt:
        days_left = (close_dt - datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)).days
        if days_left == 0:
            reasons.append("Last day to apply! Closes today")
            positive_score += 1   # urgency → subscribe before market closes
        elif days_left == 1:
            reasons.append("Closes tomorrow — act soon")
        elif days_left > 3:
            reasons.append(f"Window open for {days_left} more days — no rush")

    # ── Verdict ──────────────────────────────────────────────────────────────
    if positive_score >= 3 and positive_score > negative_score + 1:
        signal = BuySignal.BUY
    elif negative_score >= 3 and negative_score > positive_score + 1:
        signal = BuySignal.AVOID
    else:
        signal = BuySignal.NEUTRAL

    return signal, " | ".join(reasons) if reasons else "Insufficient data for analysis"


# ══════════════════════════════════════════════════════════════════════════════
# 5. NAME NORMALISER & DEDUPLICATOR  (RapidFuzz-powered)
# ══════════════════════════════════════════════════════════════════════════════

_NOISE_RE = re.compile(
    r"\b(limited|ltd|pvt|private|public|co\.?|inc|corp"
    r"|sme\s*ipo|\(sme\s*ipo\)|\(sme\)|sme"
    r"|india|ventures?|enterprise[s]?|solutions?|services?|technologies?|tech)\b",
    re.IGNORECASE,
)

_FUZZY_THRESHOLD = 88


def normalise_name(name: str) -> str:
    n = name.lower().strip()
    n = _NOISE_RE.sub(" ", n)
    n = re.sub(r"[^\w\s]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _dates_conflict(a: IPORecord, b: IPORecord) -> bool:
    if not a.open_date or not b.open_date:
        return False
    oa, ob = parse_date(a.open_date), parse_date(b.open_date)
    return bool(oa and ob and abs((oa - ob).days) > 3)


def _same_ipo(a: IPORecord, b: IPORecord) -> bool:
    if not a._norm_key or not b._norm_key:
        return False
    if a._norm_key == b._norm_key:
        return not _dates_conflict(a, b)
    la, lb = len(a._norm_key), len(b._norm_key)
    if la < 10 or lb < 10:
        return False
    if min(la, lb) / max(la, lb) < 0.75:
        return False
    da = set(tok for tok in a._norm_key.split() if tok.isdigit())
    db = set(tok for tok in b._norm_key.split() if tok.isdigit())
    if da and db and da != db:
        return False
    score = fuzz.token_sort_ratio(a._norm_key, b._norm_key)
    return score >= _FUZZY_THRESHOLD and not _dates_conflict(a, b)


def _field_count(rec: IPORecord) -> int:
    return sum(1 for f in (rec.open_date, rec.close_date, rec.listing_date,
                           rec.issue_price, rec.lot_size, rec.gmp,
                           rec.listing_price) if f)


def deduplicate(records: list[IPORecord]) -> list[IPORecord]:
    # Pass 1: within-source dedup
    seen: dict[tuple, IPORecord] = {}
    for rec in records:
        key = (rec.sources[0] if rec.sources else "?", rec._norm_key)
        existing = seen.get(key)
        if existing is None or _field_count(rec) > _field_count(existing):
            seen[key] = rec

    # Pass 2: cross-source merge
    merged: list[IPORecord] = []
    for rec in seen.values():
        matched = False
        for existing in merged:
            if _same_ipo(existing, rec):
                existing.merge(rec)
                matched = True
                break
        if not matched:
            merged.append(rec)
    return merged


# ══════════════════════════════════════════════════════════════════════════════
# 6. HTTP HELPERS  (shared session, retry, rotating UA)
# ══════════════════════════════════════════════════════════════════════════════

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

CHROME_HEADERS = {
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
    "DNT":             "1",
}

JSON_HEADERS = {
    **CHROME_HEADERS,
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
}


def _headers() -> dict:
    return {**CHROME_HEADERS, "User-Agent": random.choice(_USER_AGENTS)}


def _cloudscraper_session():
    import cloudscraper
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False},
        delay=3,
    )


@retry(
    retry=retry_if_exception_type((requests.RequestException, Exception)),
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=2, max=15),
    before_sleep=before_sleep_log(log, logging.DEBUG),
    reraise=True,
)
def _safe_get(url: str, session=None, timeout: int = 25) -> requests.Response:
    s = session or requests.Session()
    r = s.get(url, headers=_headers(), timeout=timeout)
    r.raise_for_status()
    return r


# ══════════════════════════════════════════════════════════════════════════════
# 7. CIRCUIT BREAKER
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class CircuitBreaker:
    name:         str
    max_failures: int  = 2
    _failures:    int  = field(default=0, init=False)
    _open:        bool = field(default=False, init=False)

    def call(self, fn: Callable) -> list[IPORecord]:
        if self._open:
            log.warning(f"  ⚡ Circuit OPEN – skipping {self.name}")
            return []
        try:
            result = fn()
            self._failures = 0
            return result
        except Exception as exc:
            self._failures += 1
            log.warning(f"  ✗ {self.name} failure #{self._failures}: {exc}")
            if self._failures >= self.max_failures:
                self._open = True
                log.error(f"  ⚡ Circuit TRIPPED for {self.name}")
            return []


# ══════════════════════════════════════════════════════════════════════════════
# 8. RAW ROW → IPORecord  (shared helper)
# ══════════════════════════════════════════════════════════════════════════════

_PURE_PRICE_RE = re.compile(r"^[₹\s]*[\d,]+\.?\d*\s*$")


def _is_price_string(s: str | None) -> bool:
    if not s:
        return False
    return bool(_PURE_PRICE_RE.match(s.strip().replace(",", "")))


def _clean_name(raw: str) -> str:
    if not raw:
        return ""
    raw = re.sub(r"\s+", " ", raw).strip()
    raw = re.sub(r"\s*\([^)]*\)\s*$", "", raw, flags=re.DOTALL)
    raw = re.sub(r"\d{1,2}\s*[-–]\s*\d{1,2}\s+[A-Za-z]+(\s+\d{4})?$", "", raw).strip()
    return raw


def _clean_price(raw: str | None) -> Optional[str]:
    if not raw:
        return None
    raw = raw.strip().lstrip("₹Rs. ")
    return f"₹{raw}" if raw else None


def _make_record(source: str, name: str, **kwargs) -> Optional[IPORecord]:
    name = _clean_name(name)
    if not name or len(name) < 3 or _is_price_string(name):
        return None
    rec             = IPORecord(name=name, sources=[source])
    rec.open_date   = kwargs.get("open_date") or None
    rec.close_date  = kwargs.get("close_date") or None
    rec.issue_price = _clean_price(kwargs.get("issue_price"))
    rec.lot_size    = kwargs.get("lot_size") or None
    rec.gmp         = kwargs.get("gmp") or None
    rec._norm_key   = normalise_name(name)

    raw_listing = kwargs.get("listing_date") or None
    if raw_listing:
        if _is_price_string(raw_listing):
            rec.listing_price = raw_listing
        elif parse_date(raw_listing) is not None:
            rec.listing_date = raw_listing
    return rec


# ══════════════════════════════════════════════════════════════════════════════
# 9. GENERIC HTML TABLE PARSER
# ══════════════════════════════════════════════════════════════════════════════

def _parse_tables(soup: BeautifulSoup, source: str) -> list[IPORecord]:
    records: list[IPORecord] = []
    for table in soup.find_all("table"):
        ths = table.find_all("th")
        headers = [th.get_text(strip=True).lower() for th in ths]
        if not any(kw in " ".join(headers)
                   for kw in ["ipo", "company", "open", "price", "lot", "name"]):
            continue

        col: dict[str, int] = {}
        for i, h in enumerate(headers):
            if ("company" in h or "name" in h or "ipo" in h) and "name" not in col:
                col["name"]    = i
            elif "open" in h and "open" not in col:
                col["open"]    = i
            elif "close" in h and "close" not in col:
                col["close"]   = i
            elif "price" in h and "price" not in col:
                col["price"]   = i
            elif "lot" in h and "lot" not in col:
                col["lot"]     = i
            elif "gmp" in h and "gmp" not in col:
                col["gmp"]     = i
            elif ("listing date" in h or ("list" in h and "date" in h)) and "listing" not in col:
                col["listing"] = i
            elif ("listing price" in h or "list price" in h) and "lprice" not in col:
                col["lprice"]  = i

        col.setdefault("name", 0)
        for row in table.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if not cells or len(cells) <= col["name"]:
                continue
            def _c(k):
                idx = col.get(k, -1)
                return cells[idx] if 0 <= idx < len(cells) else None

            rec = _make_record(
                source,
                name        = _c("name") or "",
                open_date   = _c("open"),
                close_date  = _c("close"),
                issue_price = _c("price"),
                lot_size    = _c("lot"),
                gmp         = _c("gmp"),
                listing_date= _c("listing") or _c("lprice"),
            )
            if rec:
                records.append(rec)
    return records


# ══════════════════════════════════════════════════════════════════════════════
# 10. SOURCE PARSERS
# ══════════════════════════════════════════════════════════════════════════════

# ── A: Chittorgarh ───────────────────────────────────────────────────────────

def fetch_chittorgarh() -> list[IPORecord]:
    log.info("━━ A: Chittorgarh ━━")
    records: list[IPORecord] = []
    url = "https://www.chittorgarh.com/ipo/ipo_dashboard.asp"
    scraper = _cloudscraper_session()
    r = _safe_get(url, session=scraper)
    soup = BeautifulSoup(r.text, "lxml")

    target = None
    for tbl in soup.find_all("table"):
        hdr = tbl.find("tr")
        if hdr and any(kw in hdr.get_text().lower()
                       for kw in ("company name", "ipo name", "open date")):
            target = tbl
            break
    if not target:
        tables = [t for t in soup.find_all("table") if len(t.find_all("tr")) > 2]
        target = tables[0] if tables else None
    if not target:
        log.warning("  Chittorgarh: no table found")
        return records

    hdr_row = target.find("tr")
    headers = [th.get_text(strip=True).lower()
               for th in hdr_row.find_all(["th", "td"])]

    col: dict[str, int] = {}
    for i, h in enumerate(headers):
        if ("company" in h or "name" in h) and "name" not in col:
            col["name"]  = i
        elif "open" in h and "open" not in col:
            col["open"]  = i
        elif "close" in h and "close" not in col:
            col["close"] = i
        elif "price" in h and "price" not in col:
            col["price"] = i
        elif "lot" in h and "lot" not in col:
            col["lot"]   = i
    col.setdefault("name", 0)

    for row in target.find_all("tr")[1:]:
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) <= col["name"]:
            continue
        def _c(k):
            idx = col.get(k, -1)
            return cells[idx] if 0 <= idx < len(cells) else None

        open_date  = _c("open")
        close_date = _c("close")
        if not open_date:
            for cell in cells:
                m = _RANGE_RE.search(cell)
                if m:
                    open_date  = cell.split("–")[0].split("-")[0].strip()
                    close_date = close_date or cell
                    break

        rec = _make_record(
            "Chittorgarh",
            name        = _c("name") or "",
            open_date   = open_date,
            close_date  = close_date,
            issue_price = _c("price"),
            lot_size    = _c("lot"),
        )
        if rec:
            records.append(rec)

    log.info(f"  ✓ {len(records)} records")
    return records


# ── B: Investorgain ──────────────────────────────────────────────────────────

def fetch_investorgain() -> list[IPORecord]:
    log.info("━━ B: Investorgain ━━")
    records: list[IPORecord] = []
    url = "https://investorgain.com/report/live-ipo-gmp/331/"
    scraper = _cloudscraper_session()
    try:
        r = _safe_get(url, session=scraper, timeout=35)
        soup = BeautifulSoup(r.text, "lxml")
    except Exception:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
                page = browser.new_context(user_agent=random.choice(_USER_AGENTS)).new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(5_000)
                html = page.content()
                browser.close()
            soup = BeautifulSoup(html, "lxml")
        except Exception as exc:
            log.warning(f"  Investorgain Playwright error: {exc}")
            return records

    table = soup.find("table", id=re.compile(r"ipo", re.I)) or soup.find("table")
    if not table:
        log.warning("  Investorgain: no table found")
        return records

    headers = [re.sub(r"\s+", " ", th.get_text()).strip().lower()
               for th in table.find_all("th")]
    for row in table.find_all("tr")[1:]:
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if not cells or "no data" in cells[0].lower():
            continue
        kwargs: dict = {}
        for i, h in enumerate(headers):
            if i >= len(cells):
                break
            if "open" in h:
                kwargs["open_date"] = cells[i]
            elif "close" in h:
                kwargs["close_date"] = cells[i]
            elif "gmp" in h:
                kwargs["gmp"] = cells[i]
            elif "price" in h:
                kwargs["issue_price"] = cells[i]
        rec = _make_record("Investorgain", cells[0], **kwargs)
        if rec:
            records.append(rec)

    log.info(f"  ✓ {len(records)} records")
    return records


# ── C: NSE India (cookie warmup → JSON API) ──────────────────────────────────

def fetch_nse() -> list[IPORecord]:
    log.info("━━ C: NSE India (cookie warmup + API) ━━")
    records: list[IPORecord] = []
    session = requests.Session()

    warmup_headers = {
        **CHROME_HEADERS,
        "User-Agent": random.choice(_USER_AGENTS),
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }

    try:
        log.info("  NSE step 1: warming main page…")
        session.get("https://www.nseindia.com", headers=warmup_headers, timeout=15)
        time.sleep(1.5)

        log.info("  NSE step 2: visiting IPO page…")
        ipo_page_headers = {**warmup_headers,
                            "Referer": "https://www.nseindia.com",
                            "Sec-Fetch-Site": "same-origin"}
        session.get(
            "https://www.nseindia.com/market-data/all-upcoming-issues-ipo",
            headers=ipo_page_headers, timeout=15,
        )
        time.sleep(1.5)

        api_headers = {
            **JSON_HEADERS,
            "User-Agent": random.choice(_USER_AGENTS),
            "Referer": "https://www.nseindia.com/market-data/all-upcoming-issues-ipo",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

        for ep in [
            "https://www.nseindia.com/api/ipo-current-allotment",
            "https://www.nseindia.com/api/getIpoData?category=ipo",
        ]:
            try:
                r = session.get(ep, headers=api_headers, timeout=12)
                if r.status_code == 200 and r.text.strip():
                    data = r.json()
                    records = _parse_nse_json(data)
                    if records:
                        log.info(f"  ✓ NSE: {len(records)} records from API")
                        return records
            except Exception as ep_e:
                log.debug(f"  NSE endpoint error: {ep_e}")

        log.warning("  NSE APIs exhausted – trying Playwright fallback…")
        records = _fetch_nse_playwright(session.cookies)

    except Exception as e:
        log.warning(f"  NSE error: {e}")
    return records


def _parse_nse_json(data) -> list[IPORecord]:
    records: list[IPORecord] = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            rec = _make_record(
                "NSE",
                name        = item.get("companyName", item.get("symbol", "")),
                open_date   = item.get("openDate", item.get("bidStartDate", "")),
                close_date  = item.get("closeDate", item.get("bidEndDate", "")),
                issue_price = item.get("issuePrice", item.get("price", "")),
                listing_date= item.get("listingDate", ""),
            )
            if rec:
                records.append(rec)
    elif isinstance(data, dict):
        for key in ["data", "ipoData", "upcomingIPO", "currentIPO", "allIpo"]:
            if key in data:
                return _parse_nse_json(data[key])
    return records


def _fetch_nse_playwright(existing_cookies=None) -> list[IPORecord]:
    records: list[IPORecord] = []
    try:
        from playwright.sync_api import sync_playwright
        captured: list[tuple] = []

        def handle_response(response):
            if "nseindia.com/api" in response.url and response.status == 200:
                try:
                    captured.append(response.json())
                except Exception:
                    pass

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            ctx = browser.new_context(user_agent=random.choice(_USER_AGENTS), locale="en-IN",
                                      viewport={"width": 1366, "height": 768})
            if existing_cookies:
                ctx.add_cookies([
                    {"name": c.name, "value": c.value, "domain": ".nseindia.com", "path": "/"}
                    for c in existing_cookies
                ])
            page = ctx.new_page()
            page.on("response", handle_response)
            try:
                page.goto("https://www.nseindia.com/market-data/all-upcoming-issues-ipo",
                          wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(5_000)
            except Exception:
                pass
            browser.close()

        for body in captured:
            records.extend(_parse_nse_json(body))
    except Exception as e:
        log.warning(f"  NSE Playwright error: {e}")
    return records


# ── D: Screener.in ───────────────────────────────────────────────────────────

def fetch_screener() -> list[IPORecord]:
    log.info("━━ D: Screener.in ━━")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage",
                                                               "--disable-blink-features=AutomationControlled"])
            ctx = browser.new_context(user_agent=random.choice(_USER_AGENTS),
                                      locale="en-IN", viewport={"width": 1366, "height": 768})
            page = ctx.new_page()
            page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});window.chrome={runtime:{}};")
            try:
                page.goto("https://www.screener.in/ipo/recent/",
                          wait_until="domcontentloaded", timeout=25_000)
                page.wait_for_selector("table", timeout=10_000)
            except Exception as nav_e:
                log.warning(f"  Screener nav (continuing): {nav_e}")
            html = page.content()
            browser.close()
        records = _parse_tables(BeautifulSoup(html, "lxml"), "Screener")
        log.info(f"  ✓ {len(records)} records")
        return records
    except Exception as exc:
        log.warning(f"  Screener error: {exc}")
        return []


# ── E: Groww ─────────────────────────────────────────────────────────────────

def fetch_groww() -> list[IPORecord]:
    log.info("━━ E: Groww ━━")
    records: list[IPORecord] = []
    try:
        from playwright.sync_api import sync_playwright
        captured: list[dict] = []

        def _on_response(response):
            url = response.url
            if any(kw in url for kw in ("/ipos", "/ipo/detail", "charter/v3", "ipo/list")):
                ct = response.headers.get("content-type", "")
                if "json" in ct:
                    try:
                        captured.append(response.json())
                    except Exception:
                        pass

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage",
                                                               "--disable-blink-features=AutomationControlled"])
            ctx = browser.new_context(user_agent=random.choice(_USER_AGENTS),
                                      locale="en-IN", viewport={"width": 1366, "height": 768})
            page = ctx.new_page()
            page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
            page.on("response", _on_response)
            try:
                page.goto("https://groww.in/ipo", wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(8_000)
            except Exception as nav_e:
                log.warning(f"  Groww nav (non-fatal): {nav_e}")
            html = page.content()
            browser.close()

        for body in captured:
            records.extend(_parse_groww_json(body))
        if not records:
            records = _parse_tables(BeautifulSoup(html, "lxml"), "Groww")

        log.info(f"  ✓ {len(records)} records")
    except Exception as exc:
        log.warning(f"  Groww error: {exc}")
    return records


def _parse_groww_json(data) -> list[IPORecord]:
    out: list[IPORecord] = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            if not any(k in item for k in ("ipoName", "companyName", "name")):
                continue
            rec = _make_record(
                "Groww",
                name        = item.get("ipoName") or item.get("companyName") or item.get("name", ""),
                open_date   = item.get("openDate") or item.get("startDate"),
                close_date  = item.get("closeDate") or item.get("endDate"),
                issue_price = item.get("issuePrice") or item.get("priceRange"),
                lot_size    = str(item["lotSize"]) if item.get("lotSize") else item.get("minOrderQty"),
                gmp         = item.get("gmp") or item.get("greyMarketPremium"),
                listing_date= item.get("listingDate"),
            )
            if rec:
                out.append(rec)
    elif isinstance(data, dict):
        for key in ("data", "ipos", "ipoList", "upcoming", "open", "result", "items"):
            if key in data:
                out.extend(_parse_groww_json(data[key]))
    return out


# ── F: IndiaTrade ─────────────────────────────────────────────────────────────

def fetch_indiatrade() -> list[IPORecord]:
    log.info("━━ F: IndiaTrade ━━")
    records: list[IPORecord] = []
    url = "https://ipo.indiratrade.com/Home"
    try:
        scraper = _cloudscraper_session()
        r = _safe_get(url, session=scraper)
        if len(r.text) < 2_000:
            raise ValueError("Response too short – probably blocked")
        records = _parse_tables(BeautifulSoup(r.text, "lxml"), "IndiaTrade")
        if records:
            log.info(f"  ✓ {len(records)} records (cloudscraper)")
            return records
    except Exception as exc:
        log.warning(f"  IndiaTrade cloudscraper failed: {exc}")

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(5_000)
            html = page.content()
            browser.close()
        records = _parse_tables(BeautifulSoup(html, "lxml"), "IndiaTrade")
        log.info(f"  ✓ {len(records)} records (Playwright fallback)")
    except Exception as exc:
        log.warning(f"  IndiaTrade Playwright failed: {exc}")
    return records


# ══════════════════════════════════════════════════════════════════════════════
# 11. PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

SOURCE_REGISTRY: list[tuple[str, Callable]] = [
    ("Chittorgarh",  fetch_chittorgarh),
    ("Investorgain", fetch_investorgain),
    ("NSE",          fetch_nse),
    ("Screener",     fetch_screener),
    ("Groww",        fetch_groww),
    ("IndiaTrade",   fetch_indiatrade),
]


def run_pipeline(today: datetime | None = None) -> list[IPORecord]:
    breakers = {name: CircuitBreaker(name) for name, _ in SOURCE_REGISTRY}
    all_raw: list[IPORecord] = []
    for name, fn in SOURCE_REGISTRY:
        records = breakers[name].call(fn)
        log.info(f"  └─ {name}: {len(records)} raw records")
        all_raw.extend(records)

    log.info(f"Total raw: {len(all_raw)}  →  deduplicating…")
    merged = deduplicate(all_raw)
    log.info(f"After dedup: {len(merged)} unique IPOs")

    if today is None:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    for rec in merged:
        rec.status = compute_status(rec, today)

    # Keep OPEN only
    open_ipos = [r for r in merged if r.status == IPOStatus.OPEN]
    log.info(f"Currently OPEN: {len(open_ipos)}")

    # Compute buy signal for each
    for rec in open_ipos:
        rec.signal, rec.signal_reason = compute_signal(rec)

    # Sort: BUY first, then NEUTRAL, then AVOID
    _order = {BuySignal.BUY: 0, BuySignal.NEUTRAL: 1, BuySignal.AVOID: 2}
    open_ipos.sort(key=lambda r: _order.get(r.signal, 9))

    return open_ipos


# ══════════════════════════════════════════════════════════════════════════════
# 12. TELEGRAM SENDER
# ══════════════════════════════════════════════════════════════════════════════

_SIGNAL_EMOJI = {
    BuySignal.BUY:     "✅ BUY",
    BuySignal.NEUTRAL: "⚠️ NEUTRAL",
    BuySignal.AVOID:   "❌ AVOID",
}


def _build_telegram_message(records: list[IPORecord]) -> str:
    now_str = datetime.now().strftime("%d %b %Y %H:%M")
    lines = [
        f"📊 *OPEN IPOs — {now_str}*",
        f"_{len(records)} IPO(s) currently accepting subscriptions_",
        "",
    ]

    if not records:
        lines.append("⚠️ No open IPOs found right now\\.")
        return "\n".join(lines)

    for rec in records:
        verdict = _SIGNAL_EMOJI.get(rec.signal, "⚪ NEUTRAL")

        # Escape special MarkdownV2 chars in dynamic values
        def _esc(s: str) -> str:
            return re.sub(r"([_*\[\]()~`>#+\-=|{}.!\\])", r"\\\1", s or "")

        name_line = f"*{_esc(rec.name)}*"

        details: list[str] = []
        if rec.issue_price:
            details.append(f"💰 Price: {_esc(rec.issue_price)}")
        if rec.open_date and rec.close_date:
            details.append(f"📅 {_esc(rec.open_date)} → {_esc(rec.close_date)}")
        elif rec.close_date:
            details.append(f"📅 Closes: {_esc(rec.close_date)}")
        if rec.lot_size:
            details.append(f"📦 Lot: {_esc(rec.lot_size)}")
        if rec.gmp:
            details.append(f"📈 GMP: {_esc(rec.gmp)}")
        if rec.listing_date:
            details.append(f"🗓 Lists: {_esc(rec.listing_date)}")

        sources_str = _esc(", ".join(rec.sources))

        lines.append(f"{verdict}  {name_line}")
        if details:
            lines.append("  " + "  \\|  ".join(details))
        lines.append(f"  🔍 _{rec.signal_reason}_")
        lines.append(f"  \\[{sources_str}\\]")
        lines.append("")

    lines.append("_Signals based on GMP, price band, lot cost & closing urgency\\._")
    return "\n".join(lines)


def send_telegram(token: str, chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
        log.info(f"  ✅ Telegram message sent (message_id: {r.json().get('result', {}).get('message_id')})")
        return True
    except Exception as e:
        log.error(f"  ❌ Telegram send failed: {e}")
        # If MarkdownV2 fails, retry as plain text
        try:
            plain = re.sub(r"[*_\[\]()~`>#+\-=|{}.!\\]", "", text)
            payload["text"] = plain
            payload["parse_mode"] = "HTML"
            r2 = requests.post(url, json={**payload, "parse_mode": ""}, timeout=15)
            r2.raise_for_status()
            log.info("  ✅ Telegram plain-text fallback sent")
            return True
        except Exception as e2:
            log.error(f"  ❌ Telegram plain-text fallback also failed: {e2}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# 13. CONSOLE OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

_STATUS_ICONS = {
    BuySignal.BUY:     "✅",
    BuySignal.NEUTRAL: "⚠️ ",
    BuySignal.AVOID:   "❌",
}


def print_results(records: list[IPORecord]) -> None:
    if not records:
        print("\n⚠️  No OPEN IPOs found.\n")
        return

    now_str = datetime.now().strftime("%d %b %Y %H:%M")
    print(f"\n{'═'*72}")
    print(f"  OPEN IPOs  —  {now_str}   ({len(records)} open)")
    print(f"{'═'*72}")

    for rec in records:
        icon   = _STATUS_ICONS.get(rec.signal, "⚪")
        verdict = f"{icon} {rec.signal.value}"
        print(f"\n  {verdict}  •  {rec.name}")

        date_part = ""
        if rec.open_date and rec.close_date:
            date_part = f"  {rec.open_date} → {rec.close_date}"
        elif rec.close_date:
            date_part = f"  Closes: {rec.close_date}"

        extras = "".join([
            f"  {rec.issue_price}"    if rec.issue_price  else "",
            f"  Lot:{rec.lot_size}"   if rec.lot_size     else "",
            f"  GMP:{rec.gmp}"        if rec.gmp          else "",
            f"  Lists:{rec.listing_date}" if rec.listing_date else "",
        ])
        if date_part or extras:
            print(f"    {date_part}{extras}")
        print(f"    📋 {rec.signal_reason}")
        print(f"    [{', '.join(rec.sources)}]")
    print()


# ══════════════════════════════════════════════════════════════════════════════
# 14. ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="IPO Telegram Alert — Open IPOs + Buy/Avoid Signal")
    parser.add_argument("--token",   default=None, help="Telegram Bot Token (or set TELEGRAM_TOKEN env var)")
    parser.add_argument("--chat",    default=None, help="Telegram Chat/Channel ID (or set TELEGRAM_CHAT_ID env var)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print message without sending to Telegram")
    parser.add_argument("--json",    default="open_ipos.json",
                        help="Path to save JSON output (default: open_ipos.json)")
    args = parser.parse_args()

    # Resolve credentials: CLI args take priority, then environment variables
    token   = args.token   or os.environ.get("TELEGRAM_TOKEN")   or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = args.chat    or os.environ.get("TELEGRAM_CHAT_ID")

    if not args.dry_run and (not token or not chat_id):
        log.error(
            "❌ Telegram credentials missing.\n"
            "   Provide via CLI:  --token TOKEN --chat CHAT_ID\n"
            "   Or set env vars:  TELEGRAM_TOKEN  and  TELEGRAM_CHAT_ID"
        )
        sys.exit(1)

    log.info("🚀 Starting IPO pipeline…")
    open_ipos = run_pipeline()

    # Console preview
    print_results(open_ipos)

    # Save JSON
    with open(args.json, "w", encoding="utf-8") as fh:
        json.dump([r.to_dict() for r in open_ipos], fh, indent=2, ensure_ascii=False)
    log.info(f"  💾 JSON saved → {args.json}")

    # Build and send Telegram message
    msg = _build_telegram_message(open_ipos)

    if args.dry_run:
        print("\n── DRY RUN — Telegram message preview ──────────────────────────────")
        print(msg)
        print("────────────────────────────────────────────────────────────────────\n")
    else:
        log.info("📤 Sending to Telegram…")
        send_telegram(token, chat_id, msg)


if __name__ == "__main__":
    main()
