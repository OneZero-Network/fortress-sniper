#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║      IPO SNIPER v12.0 — FULL CODE (PATCHED)                                 ║
║                                                                              ║
║  PATCH NOTES (applied on top of v12.0 base):                                ║
║  FIX 1 — LLMTracker class: per-stage debug logging for every LLM call      ║
║  FIX 2 — fetch_company_description(): 6-source scraper + name-stub fallback ║
║  FIX 3 — _sector_pre_filter() + _pick_audit(): now searches description     ║
║           and company name, not just the "SME"/"Mainboard" sector field     ║
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
import html as html_lib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    PLAYWRIGHT_OK = True
except ImportError:
    PLAYWRIGHT_OK = False

try:
    from rapidfuzz import fuzz as _fuzz
    _RAPIDFUZZ_OK = True
except ImportError:
    _RAPIDFUZZ_OK = False

try:
    from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
    _TENACITY_OK = True
except ImportError:
    _TENACITY_OK = False


# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════

IPO_DB_PATH   = Path("data/ipo_sniper_v7.db")
FALLBACK_CSV  = Path("data/ipo_fallback_v7.csv")
JSON_EXPORT   = Path("data/ipo_latest_run.json")
VERSION       = "IPO-SNIPER-v12.0"
MC_RUNS       = 50_000
KELLY_FRACTION = 0.25
MAX_SYNDICATE  = 10
SEED           = 42

MAX_UPCOMING_DAYS     = 21
MAX_UPCOMING_TELEGRAM = 5
MAX_UPCOMING_TBD      = 2

np.random.seed(SEED)
random.seed(SEED)

NSE_BASE         = "https://www.nseindia.com"
NSE_API_URL      = "https://www.nseindia.com/api/getAllIpo"
NSE_UPCOMING_API = "https://www.nseindia.com/api/ipo-detail"

BASE_WEIGHTS: Dict[str, float] = {
    "gmp":       0.22,
    "sub":       0.28,
    "sentiment": 0.14,
    "trend":     0.12,
    "size":      0.10,
    "halal":     0.14,
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(message)s"
)
log   = logging.getLogger(VERSION)
TODAY = datetime.today().date()

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

# ── v12 model constants ───────────────────────────────────────────────────────
_ROUTER_FAST_MODEL           = "gpt-4o-mini"
_ROUTER_FLAGSHIP_MODEL       = "gpt-4o"
_ROUTER_CONFIDENCE_THRESHOLD = 80
_ADVISOR_MODEL               = "claude-sonnet-4-20250514"

# ── v12 halal weight policy bounds ───────────────────────────────────────────
_HALAL_WEIGHT_MIN  = 0.10
_HALAL_WEIGHT_MAX  = 0.15
_ADVISOR_MIN_SAMPLES = 5
_WEIGHT_KEYS = ("gmp", "sub", "sentiment", "trend", "size", "halal")

# ── Shariah verdict confidence gates ─────────────────────────────────────────
# HARAM requires EVIDENCE, not doubt. Any ruling below this confidence is
# downgraded to TIER_2_CONDITIONAL — a caution flag, never an outright block.
_HARAM_MIN_CONFIDENCE = 60

# Phrases in haram_reason / compliance_notes that signal the LLM is expressing
# uncertainty rather than issuing a genuine Shariah ruling.
# ANY match → downgrade to CONDITIONAL, never block.
_UNCERTAINTY_PHRASES = (
    "insufficient information",
    "unable to determine",
    "cannot determine",
    "not enough information",
    "no information available",
    "unclear",
    "lack of information",
    "preliminary audit suggests",   # hedged — not a ruling
    "may involve",                  # speculative — not a ruling
    "could involve",
    "might involve",
    "possibly impermissible",
    "cannot confirm",
    "further review required",
    "manual review",
    "further investigation",
    "more information needed",
    "limited information",
    "without more details",
    "no business description",
    "description unavailable",
)

# ── v12 sector pre‑filter sets (FIX 3: expanded with common Indian SME terms) ─
OBVIOUS_HALAL_SECTORS = {
    "it services", "software", "saas", "erp", "crm", "cloud computing",
    "healthcare", "hospital", "pharma", "biotech", "medical devices",
    "manufacturing", "auto components", "engineering", "capital goods",
    "education", "edtech", "school", "college",
    "agriculture", "agri inputs", "food processing",
    "logistics", "warehousing", "courier",
    "renewable energy", "solar", "wind", "power generation",
    "real estate development", "construction", "infrastructure",
    "textiles", "apparel", "retail",
    # common fragments seen in Indian SME IPO names / descriptions
    "infotech", "techno", "systems", "solutions", "services",
    "chemicals", "packaging", "printing", "cables", "wires",
    "steel", "iron", "cement", "ceramics", "pipes", "pumps",
    "hospital", "diagnostic", "clinic", "labs",
}
OBVIOUS_HARAM_SECTORS = {
    "bank", "banking", "nbfc", "microfinance", "housing finance",
    "insurance", "reinsurance", "asset management", "mutual fund",
    "alcohol", "brewery", "distillery", "liquor", "wine", "beer",
    "gambling", "casino", "lottery", "betting",
    "pork", "pig farming", "swine",
    "tobacco", "cigarette", "cigar", "pan masala",
    "adult entertainment", "pornography",
}


# ══════════════════════════════════════════════════════════════════════════════
# FIX 1 — LLMTracker (new class, placed right after CONFIG)
# ══════════════════════════════════════════════════════════════════════════════

class LLMTracker:
    """
    Per-run diagnostic tracker for every LLM pipeline stage.

    Stages (in order):
      DESC_FETCH   – web scraping for company description
      CACHE_HIT    – Shariah SQLite cache lookup
      PREFILTER    – sector keyword pre-filter
      RULE_AUDIT   – rule-based fallback
      OPENAI_MINI  – gpt-4o-mini structured-output call
      OPENAI_FULL  – gpt-4o escalated call
      CLAUDE       – Claude monthly advisor call
      FINAL        – resolved verdict

    Status: START / OK / FAIL / SKIP / WARN
    """

    _ICONS = {"OK": "✅", "FAIL": "❌", "SKIP": "⏭", "START": "▶", "WARN": "⚠️"}

    def __init__(self):
        self.events: List[dict] = []
        self._stage_start: Dict[str, float] = {}

    def start(self, company: str, stage: str, detail: str = ""):
        self._stage_start[f"{company}:{stage}"] = time.time()
        self._record(company, stage, "START", detail)

    def ok(self, company: str, stage: str, detail: str = ""):
        elapsed = self._elapsed(company, stage)
        self._record(company, stage, "OK", detail, elapsed)

    def fail(self, company: str, stage: str, reason: str):
        elapsed = self._elapsed(company, stage)
        self._record(company, stage, "FAIL", reason, elapsed)

    def skip(self, company: str, stage: str, reason: str = ""):
        self._record(company, stage, "SKIP", reason)

    def warn(self, company: str, stage: str, detail: str):
        self._record(company, stage, "WARN", detail)

    def dump_summary(self):
        if not self.events:
            return
        fails = [e for e in self.events if e["status"] == "FAIL"]
        warns = [e for e in self.events if e["status"] == "WARN"]
        skips = [e for e in self.events if e["status"] == "SKIP"]
        oks   = [e for e in self.events if e["status"] == "OK"]
        W = 78
        print(f"\n{'═' * W}")
        print(f"  🔬 LLM TRACKER SUMMARY  ·  {len(self.events)} events")
        print(f"{'═' * W}")
        print(f"  ✅ OK      : {len(oks)}")
        print(f"  ❌ FAIL    : {len(fails)}")
        print(f"  ⚠️  WARN   : {len(warns)}")
        print(f"  ⏭ SKIPPED : {len(skips)}")
        # Per-stage breakdown
        stages: Dict[str, Dict] = {}
        for e in self.events:
            k = e["stage"]
            stages.setdefault(k, {"ok": 0, "fail": 0, "skip": 0, "warn": 0})
            stages[k][e["status"].lower()] = stages[k].get(e["status"].lower(), 0) + 1
        print(f"\n  ── Per-stage breakdown ──────────────────────────────────")
        print(f"  {'Stage':<18} {'OK':>4} {'FAIL':>5} {'SKIP':>5} {'WARN':>5}")
        print(f"  {'─'*18} {'─'*4} {'─'*5} {'─'*5} {'─'*5}")
        for stg, cnt in sorted(stages.items()):
            flag = "  ← ❗" if cnt.get("fail", 0) > 0 else ""
            print(
                f"  {stg:<18} {cnt.get('ok',0):>4} {cnt.get('fail',0):>5} "
                f"{cnt.get('skip',0):>5} {cnt.get('warn',0):>5}{flag}"
            )
        if fails:
            print(f"\n  ── Failure detail ───────────────────────────────────────")
            for e in fails:
                print(f"  [{e['ts']}] {e['company']:<26} │ {e['stage']:<16} │ {e['detail'][:55]}")
        if warns:
            print(f"\n  ── Warnings ─────────────────────────────────────────────")
            for e in warns:
                print(f"  [{e['ts']}] {e['company']:<26} │ {e['stage']:<16} │ {e['detail'][:55]}")
        print(f"{'═' * W}\n")

    def reset(self):
        self.events.clear()
        self._stage_start.clear()

    def _elapsed(self, company: str, stage: str) -> float:
        t0 = self._stage_start.pop(f"{company}:{stage}", None)
        return round(time.time() - t0, 2) if t0 else 0.0

    def _record(self, company: str, stage: str, status: str,
                detail: str, elapsed: float = 0.0):
        icon = self._ICONS.get(status, "•")
        entry = {
            "ts":        datetime.now().strftime("%H:%M:%S.%f")[:12],
            "company":   company[:30],
            "stage":     stage,
            "status":    status,
            "detail":    detail[:140],
            "elapsed_s": elapsed,
        }
        self.events.append(entry)
        elapsed_str = f"  ({elapsed:.2f}s)" if elapsed else ""
        log.info(
            f"  [LLM-TRACK] {icon} {company[:24]:<24} │ "
            f"{stage:<16} │ {detail[:60]}{elapsed_str}"
        )


# Module-level singleton — used by all LLM functions below
llm_tracker = LLMTracker()


# ══════════════════════════════════════════════════════════════════════════════
# LEGACY HELPERS
# ══════════════════════════════════════════════════════════════════════════════

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

def _parse_date_legacy(text: str):
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

def _make_session(referer: str = "https://www.google.com/") -> requests.Session:
    s = requests.Session()
    s.headers.update({**BROWSER_HEADERS, "Referer": referer})
    return s

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


# ══════════════════════════════════════════════════════════════════════════════
# SCRAPER DATA LAYER — IPORecord + helpers
# ══════════════════════════════════════════════════════════════════════════════

class IPOStatus(str, Enum):
    OPEN     = "Open"
    UPCOMING = "Upcoming"
    CLOSED   = "Closed"
    LISTED   = "Listed"
    UNKNOWN  = "Unknown"

@dataclass
class IPORecord:
    name:           str
    sources:        list        = field(default_factory=list)
    open_date:      Optional[str] = None
    close_date:     Optional[str] = None
    listing_date:   Optional[str] = None
    issue_price:    Optional[str] = None
    lot_size:       Optional[str] = None
    gmp:            Optional[str] = None
    allotment_date: Optional[str] = None
    listing_price:  Optional[str] = None
    status:         IPOStatus     = IPOStatus.UNKNOWN
    _norm_key:      str           = field(default="", repr=False)

    def merge(self, other: "IPORecord") -> None:
        for src in other.sources:
            if src not in self.sources:
                self.sources.append(src)
        for attr in ("open_date", "close_date", "listing_date", "issue_price",
                     "lot_size", "gmp", "allotment_date", "listing_price"):
            if not getattr(self, attr) and getattr(other, attr):
                setattr(self, attr, getattr(other, attr))

    def to_dict(self) -> dict:
        from dataclasses import asdict
        d = asdict(self)
        d.pop("_norm_key", None)
        d["status"] = self.status.value
        return d

_DATE_FORMATS = [
    "%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%d-%m-%Y",
    "%d/%m/%Y", "%d %b", "%d %B", "%b %d %Y", "%B %d %Y", "%b %d, %Y",
]
_RANGE_RE = re.compile(
    r"(\d{1,2})\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+)(?:\s+(\d{4}))?",
    re.IGNORECASE,
)

def _scraper_parse_date(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    raw = raw.strip()
    if raw.lower() in ("tba", "to be announced", "n/a", "-", ""):
        return None
    m = _RANGE_RE.search(raw)
    if m:
        day, month_str = int(m.group(1)), m.group(3)
        year = int(m.group(4)) if m.group(4) else _infer_year(month_str, int(m.group(1)))
        for fmt in ("%d %b %Y", "%d %B %Y"):
            try:
                return datetime.strptime(f"{day} {month_str} {year}", fmt)
            except ValueError:
                continue
        return None
    _now = datetime.now()
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

def _compute_scraper_status(rec: IPORecord, today: Optional[datetime] = None) -> IPOStatus:
    if today is None:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    od = _scraper_parse_date(rec.open_date)
    cd = _scraper_parse_date(rec.close_date)
    ld = _scraper_parse_date(rec.listing_date)
    if ld and ld < today:
        return IPOStatus.LISTED
    if cd and cd < today:
        return IPOStatus.CLOSED
    if od and od <= today and (not cd or cd >= today):
        return IPOStatus.OPEN
    if od and od > today:
        return IPOStatus.UPCOMING
    if ld and ld > today:
        if not od and not cd:
            return IPOStatus.OPEN
        return IPOStatus.UPCOMING
    _no_dates = not od and not cd and not ld
    _has_price = bool(rec.issue_price and rec.issue_price.strip("₹ -"))
    if _no_dates and rec.listing_price:
        return IPOStatus.LISTED
    if _no_dates and _has_price and not rec.gmp:
        return IPOStatus.LISTED
    name_lower = rec.name.lower()
    if any(t in name_lower for t in ("sme ipo", "upcoming")):
        return IPOStatus.UPCOMING
    if "to be announced" in str(rec.open_date or "").lower():
        return IPOStatus.UPCOMING
    return IPOStatus.UNKNOWN

_NOISE_RE = re.compile(
    r"\b(limited|ltd|pvt|private|public|co\.?|inc|corp"
    r"|sme\s*ipo|\(sme\s*ipo\)|\(sme\)|sme"
    r"|india|ventures?|enterprise[s]?|solutions?|services?|technologies?|tech)\b",
    re.IGNORECASE,
)
_FUZZY_THRESHOLD = 88

def _normalise_name(name: str) -> str:
    if not name:
        return ""
    n = name.lower().strip()
    n = _NOISE_RE.sub(" ", n)
    n = re.sub(r"[^\w\s]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n

def _dates_conflict(a: IPORecord, b: IPORecord) -> bool:
    if not a.open_date or not b.open_date:
        return False
    oa = _scraper_parse_date(a.open_date)
    ob = _scraper_parse_date(b.open_date)
    return bool(oa and ob and abs((oa - ob).days) > 3)

def _same_ipo(a: IPORecord, b: IPORecord) -> bool:
    if not a._norm_key or not b._norm_key:
        return False
    if a._norm_key == b._norm_key:
        return not _dates_conflict(a, b)
    _da = set(t for t in a._norm_key.split() if t.isdigit())
    _db = set(t for t in b._norm_key.split() if t.isdigit())
    if _da and _db and _da != _db:
        return False
    if _RAPIDFUZZ_OK:
        pr = _fuzz.partial_ratio(a._norm_key, b._norm_key)
        if pr >= 95:
            return not _dates_conflict(a, b)
    la, lb = len(a._norm_key), len(b._norm_key)
    if la < 10 or lb < 10:
        return False
    if min(la, lb) / max(la, lb) < 0.65:
        return False
    if _RAPIDFUZZ_OK:
        ts = _fuzz.token_sort_ratio(a._norm_key, b._norm_key)
        if max(ts, pr) >= _FUZZY_THRESHOLD:
            return not _dates_conflict(a, b)
    return False

def _field_count(rec: IPORecord) -> int:
    return sum(1 for f in (rec.open_date, rec.close_date, rec.listing_date,
                           rec.issue_price, rec.lot_size, rec.gmp,
                           rec.listing_price) if f)

def deduplicate_records(records: list) -> list:
    seen = {}
    for item in records:
        key = (item.sources[0] if item.sources else "?", item._norm_key)
        if key not in seen or _field_count(item) > _field_count(seen[key]):
            seen[key] = item
    merged = []
    for item in seen.values():
        matched = False
        for existing in merged:
            if _same_ipo(existing, item):
                existing.merge(item)
                matched = True
                break
        if not matched:
            merged.append(item)
    return merged

_PURE_PRICE_RE = re.compile(r"^[₹\s]*[\d,]+\.?\d*\s*$")

def _is_price_string(s: Optional[str]) -> bool:
    if not s:
        return False
    return bool(_PURE_PRICE_RE.match(s.strip().replace(",", "")))

def _clean_name_scraper(raw: str) -> str:
    if not raw:
        return ""
    raw = re.sub(r"\s+", " ", raw).strip()
    raw = re.sub(r"\s*\([^)]*\)\s*$", "", raw, flags=re.DOTALL)
    raw = re.sub(r"\s+", " ", raw).strip()
    raw = re.sub(r"\d{1,2}\s*[-–]\s*\d{1,2}\s+[A-Za-z]+(\s+\d{4})?$", "", raw).strip()
    return raw

def _clean_price_scraper(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    raw = raw.strip().lstrip("₹Rs. ")
    return f"₹{raw}" if raw else None

def _make_ipo_record(source: str, name: str, **kwargs) -> Optional[IPORecord]:
    name = _clean_name_scraper(name)
    if not name or len(name) < 3:
        return None
    if _is_price_string(name):
        return None
    rec             = IPORecord(name=name, sources=[source])
    rec.open_date   = kwargs.get("open_date") or None
    rec.close_date  = kwargs.get("close_date") or None
    rec.issue_price = _clean_price_scraper(kwargs.get("issue_price"))
    rec.lot_size    = kwargs.get("lot_size") or None
    rec.gmp         = kwargs.get("gmp") or None
    rec._norm_key   = _normalise_name(name)
    raw_listing     = kwargs.get("listing_date") or None
    if raw_listing:
        if _is_price_string(raw_listing):
            rec.listing_price = raw_listing
        elif _scraper_parse_date(raw_listing) is not None:
            rec.listing_date = raw_listing
    return rec


# ══════════════════════════════════════════════════════════════════════════════
# GENERIC TABLE PARSERS
# ══════════════════════════════════════════════════════════════════════════════

def _parse_tables_scraper(soup, source: str) -> list:
    records = []
    for table in soup.find_all("table"):
        ths = table.find_all("th")
        headers = [re.sub(r"\s+", " ", th.get_text()).strip().lower() for th in ths]
        if not any(kw in " ".join(headers) for kw in ["ipo","company","open","price","lot","name"]):
            continue
        col = {}
        for i, h in enumerate(headers):
            if ("company" in h or "name" in h or "ipo" in h) and "name" not in col:
                col["name"] = i
            elif "open" in h and "open" not in col:
                col["open"] = i
            elif "close" in h and "close" not in col:
                col["close"] = i
            elif "price" in h and "price" not in col:
                col["price"] = i
            elif "lot" in h and "lot" not in col:
                col["lot"] = i
            elif "gmp" in h and "gmp" not in col:
                col["gmp"] = i
            elif "list" in h and "listing" not in col:
                col["listing"] = i
        col.setdefault("name", 0)
        for row in table.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if not cells or len(cells) <= col["name"]:
                continue
            def _c(k):
                idx = col.get(k, -1)
                return cells[idx] if 0 <= idx < len(cells) else None
            raw_listing = _c("listing")
            rec = _make_ipo_record(source, _c("name") or "",
                                    open_date=_c("open"), close_date=_c("close"),
                                    issue_price=_c("price"), lot_size=_c("lot"),
                                    gmp=_c("gmp"), listing_date=raw_listing)
            if rec:
                records.append(rec)
    return records

def _parse_td_header_tables(soup, source: str) -> list:
    records = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 3:
            continue
        hdr_cells = rows[0].find_all(["th", "td"])
        headers = [re.sub(r"\s+", " ", c.get_text()).strip().lower() for c in hdr_cells]
        if not any(kw in " ".join(headers) for kw in ["company","ipo","open","price","name"]):
            continue
        col = {}
        for i, h in enumerate(headers):
            if ("company" in h or "name" in h or "ipo" in h) and "name" not in col:
                col["name"] = i
            elif "open" in h and "open" not in col:
                col["open"] = i
            elif "close" in h and "close" not in col:
                col["close"] = i
            elif "price" in h and "price" not in col:
                col["price"] = i
            elif "lot" in h and "lot" not in col:
                col["lot"] = i
            elif "gmp" in h and "gmp" not in col:
                col["gmp"] = i
            elif "list" in h and "listing" not in col:
                col["listing"] = i
        col.setdefault("name", 0)
        for row in rows[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if not cells or len(cells) <= col["name"]:
                continue
            def _c(k):
                idx = col.get(k, -1)
                return cells[idx] if 0 <= idx < len(cells) else None
            rec = _make_ipo_record(source, _c("name") or "",
                                    open_date=_c("open"), close_date=_c("close"),
                                    issue_price=_c("price"), lot_size=_c("lot"),
                                    gmp=_c("gmp"), listing_date=_c("listing"))
            if rec:
                records.append(rec)
    return records


# ══════════════════════════════════════════════════════════════════════════════
# INVESTORGAIN TABLE PARSER
# ══════════════════════════════════════════════════════════════════════════════

_IG_EXCHANGE_RE = re.compile(
    r"(NSE\s*SME|BSE\s*SME|NSE|BSE|IPOL?)"
    r"\s*"
    r"(L@[\d,]+\.?\d*"
    r"|@[\d,]+\.?\d*"
    r"|[OCU](?:\s*Allotted)?"
    r"|Allotted"
    r")?",
    re.IGNORECASE,
)
_IG_DATE_RE = re.compile(
    r"(\d{1,2})-(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)",
    re.IGNORECASE,
)
_IG_GMP_RE  = re.compile(r"GMP:\s*([\-\d.]+)", re.IGNORECASE)
_IG_GMP_AMT = re.compile(r"^[^\d]*(\d+\.?\d*)")

def _ig_parse_name_cell(raw: str) -> Tuple[str, Optional[str], Optional[str]]:
    matches = list(_IG_EXCHANGE_RE.finditer(raw))
    if not matches:
        return raw.strip(), None, None
    m = matches[-1]
    clean_name = raw[:m.start()].strip()
    status_raw = (m.group(2) or "").strip()
    if "@" in status_raw:
        price = status_raw[status_raw.index("@") + 1:]
        return clean_name, "L", price
    status_code = status_raw[0].upper() if status_raw else None
    return clean_name, status_code, None

def _ig_parse_date_cell(raw: str) -> Tuple[Optional[str], Optional[str]]:
    if not raw:
        return None, None
    dm = _IG_DATE_RE.search(raw)
    if not dm:
        return None, None
    day, mon = dm.group(1), dm.group(2)
    year = _infer_year(mon, int(day))
    date_str = f"{int(day):02d} {mon.capitalize()} {year}"
    gm = _IG_GMP_RE.search(raw)
    gmp = gm.group(1) if gm else None
    return date_str, gmp

def _ig_extract_gmp_amount(raw: str) -> Optional[str]:
    if not raw or raw.strip() in ("--", "₹--", "-"):
        return None
    m = _IG_GMP_AMT.match(raw.strip())
    if m:
        val = m.group(1)
        return val if float(val) > 0 else None
    return None

def _parse_investorgain_table(table) -> list:
    records = []
    ths = table.find_all("th")
    headers = [re.sub(r"\s+", " ", th.get_text()).strip().lower() for th in ths]
    if not headers:
        first_tr = table.find("tr")
        if first_tr:
            headers = [re.sub(r"\s+", " ", td.get_text()).strip().lower()
                       for td in first_tr.find_all(["th", "td"])]
    col = {}
    for i, h in enumerate(headers):
        if ("ipo" in h or "company" in h or "name" in h) and "name" not in col:
            col["name"] = i
        elif "price" in h and "price" not in col:
            col["price"] = i
        elif "open" in h and "open" not in col:
            col["open"] = i
        elif "close" in h and "close" not in col:
            col["close"] = i
        elif "gmp" in h and "gmp" not in col:
            col["gmp"] = i
    col.setdefault("name", 0)
    col.setdefault("gmp",  1)
    col.setdefault("open", 2)
    col.setdefault("close", 3)
    start_row = 1 if ths else 2
    for row in table.find_all("tr")[start_row:]:
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if not cells or len(cells) < 2:
            continue
        if "no data" in (cells[0] or "").lower():
            continue
        raw_name = cells[col["name"]] if col["name"] < len(cells) else ""
        if not raw_name:
            continue
        clean_name, status_code, list_price = _ig_parse_name_cell(raw_name)
        raw_gmp  = cells[col["gmp"]]  if col.get("gmp", 1)  < len(cells) else ""
        raw_open = cells[col["open"]] if col["open"] < len(cells) else ""
        raw_cls  = cells[col["close"]] if col["close"] < len(cells) else ""
        gmp_col  = _ig_extract_gmp_amount(raw_gmp)
        od, gmp_od = _ig_parse_date_cell(raw_open)
        cd, gmp_cd = _ig_parse_date_cell(raw_cls)
        final_gmp  = gmp_col or gmp_cd or gmp_od
        issue_price = None
        if "price" in col:
            issue_price = cells[col["price"]] if col["price"] < len(cells) else None
        rec = _make_ipo_record("Investorgain", clean_name,
                               open_date=od, close_date=cd,
                               issue_price=issue_price,
                               gmp=f"₹{final_gmp}" if final_gmp else None,
                               listing_date=list_price)
        if rec:
            records.append(rec)
    return records


# ══════════════════════════════════════════════════════════════════════════════
# PLAYWRIGHT HELPERS
# ══════════════════════════════════════════════════════════════════════════════

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

def _pw_get_html(url: str, wait_ms: int = 4000,
                 selector: str = "table, .table, [class*=table]") -> Optional[str]:
    if not PLAYWRIGHT_OK:
        return None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage",
                      "--disable-blink-features=AutomationControlled"]
            )
            ctx  = browser.new_context(user_agent=random.choice(_USER_AGENTS), locale="en-IN")
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            try:
                page.wait_for_selector(selector, timeout=12_000)
            except Exception:
                pass
            page.wait_for_timeout(wait_ms)
            html = page.content()
            browser.close()
            return html
    except Exception as exc:
        log.warning(f"  PW [{url}]: {exc}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE FETCHERS
# ══════════════════════════════════════════════════════════════════════════════

_SCREENER_URLS = [
    "https://www.screener.in/ipo/recent/",
    "https://www.screener.in/ipo/",
]

def _fetch_screener() -> list:
    log.info("━━ SOURCE A: Screener.in ━━")
    for url in _SCREENER_URLS:
        html = _pw_get_html(url, wait_ms=3000)
        if not html:
            continue
        soup = BeautifulSoup(html, "lxml")
        recs = _parse_tables_scraper(soup, "Screener")
        if not recs:
            recs = _parse_td_header_tables(soup, "Screener")
        if recs:
            log.info(f"  ✓ Screener: {len(recs)} records")
            return recs
    log.warning("  ⚠ Screener: 0 records")
    return []

def _fetch_investorgain_new() -> list:
    log.info("━━ SOURCE B: Investorgain ━━")
    url = "https://investorgain.com/report/live-ipo-gmp/331/"
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows"}, delay=3)
        r = scraper.get(url, timeout=30)
        if r.status_code == 200 and not r.headers.get("x-deny-reason"):
            soup  = BeautifulSoup(r.text, "lxml")
            table = (soup.find("table", id=re.compile(r"ipo", re.I)) or soup.find("table"))
            if table:
                recs = _parse_investorgain_table(table)
                if recs:
                    log.info(f"  ✓ Investorgain (cloudscraper): {len(recs)}")
                    return recs
    except Exception as exc:
        log.warning(f"  Investorgain cloudscraper: {exc}")

    html = _pw_get_html(url, wait_ms=5000, selector="table")
    if html:
        soup  = BeautifulSoup(html, "lxml")
        table = (soup.find("table", id=re.compile(r"ipo", re.I)) or soup.find("table"))
        if table:
            recs = _parse_investorgain_table(table)
            if recs:
                log.info(f"  ✓ Investorgain (playwright): {len(recs)}")
                return recs
    log.warning("  ⚠ Investorgain: 0 records")
    return []

def _fetch_groww() -> list:
    log.info("━━ SOURCE C: Groww ━━")
    if not PLAYWRIGHT_OK:
        return []
    captured = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            ctx  = browser.new_context(user_agent=random.choice(_USER_AGENTS),
                                        viewport={"width": 1366, "height": 768})
            page = ctx.new_page()

            def _on_resp(resp):
                if any(kw in resp.url for kw in ("/ipos", "/ipo/detail", "charter/v3", "ipo/list")):
                    try:
                        captured.append(resp.json())
                    except Exception:
                        pass

            page.on("response", _on_resp)
            page.goto("https://groww.in/ipo", wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(8_000)
            html = page.content()
            browser.close()

        recs = []
        for body in captured:
            recs.extend(_parse_groww_json(body))
        if not recs:
            soup = BeautifulSoup(html, "lxml")
            recs = _parse_tables_scraper(soup, "Groww")
        log.info(f"  ✓ Groww: {len(recs)} records")
        return recs
    except Exception as exc:
        log.warning(f"  Groww error: {exc}")
        return []

def _parse_groww_json(data) -> list:
    out = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            if not any(k in item for k in ("ipoName", "companyName", "name")):
                continue
            rec = _make_ipo_record(
                "Groww",
                name         = item.get("ipoName") or item.get("companyName") or item.get("name", ""),
                open_date    = item.get("openDate") or item.get("startDate"),
                close_date   = item.get("closeDate") or item.get("endDate"),
                issue_price  = item.get("issuePrice") or item.get("priceRange"),
                lot_size     = str(item["lotSize"]) if item.get("lotSize") else item.get("minOrderQty"),
                gmp          = item.get("gmp") or item.get("greyMarketPremium"),
                listing_date = item.get("listingDate"),
            )
            if rec:
                out.append(rec)
    elif isinstance(data, dict):
        for key in ("data", "ipos", "ipoList", "upcoming", "open", "result", "items"):
            if key in data:
                out.extend(_parse_groww_json(data[key]))
    return out

def _fetch_indiatrade() -> list:
    log.info("━━ SOURCE D: IndiaTrade ━━")
    url = "https://ipo.indiratrade.com/Home"
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows"})
        r = scraper.get(url, timeout=20)
        if r.status_code == 200 and len(r.text) > 2000:
            soup = BeautifulSoup(r.text, "lxml")
            recs = _parse_tables_scraper(soup, "IndiaTrade")
            if recs:
                log.info(f"  ✓ IndiaTrade (cloudscraper): {len(recs)}")
                return recs
    except Exception as exc:
        log.warning(f"  IndiaTrade cloudscraper: {exc}")

    html = _pw_get_html(url, wait_ms=5000)
    if html:
        soup = BeautifulSoup(html, "lxml")
        recs = _parse_tables_scraper(soup, "IndiaTrade")
        if recs:
            log.info(f"  ✓ IndiaTrade (playwright): {len(recs)}")
            return recs
    log.warning("  ⚠ IndiaTrade: 0 records")
    return []


# ══════════════════════════════════════════════════════════════════════════════
# BRIDGE: IPORecord list → DataFrame
# ══════════════════════════════════════════════════════════════════════════════

def _ipo_records_to_df(records: list, source_label: str = "") -> pd.DataFrame:
    today_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = []
    for rec in records:
        status = _compute_scraper_status(rec, today_dt)
        rec.status = status

        lo, hi   = _parse_price_band(rec.issue_price or "")
        lot_size = _int(rec.lot_size or "0") or 50

        gmp_raw = rec.gmp or ""
        gmp_num = _flt(gmp_raw, 0.0)
        if gmp_num > 0 and hi > 0:
            gmp_frac = gmp_num / hi
            gmp_pct  = gmp_frac * 100
        else:
            gmp_frac = gmp_num / 100 if gmp_num > 1 else gmp_num
            gmp_pct  = gmp_frac * 100

        od  = _parse_date_legacy(rec.open_date or "")
        cd  = _parse_date_legacy(rec.close_date or "")
        ld  = _parse_date_legacy(rec.listing_date or "")
        date_fallback = (cd is None)

        if cd is None:
            days = 20 if status == IPOStatus.UPCOMING else 0
            effective_cd = TODAY
        else:
            days = (cd - TODAY).days
            effective_cd = cd

        if lot_size >= 1000:
            sector = "SME"
        elif hi > 0 and hi < 150:
            sector = "SME"
        else:
            sector = "Mainboard"

        src_str = ", ".join(rec.sources) if rec.sources else source_label

        rows.append({
            "Symbol":            rec.name,
            "Sector":            sector,
            "IssueSizeCr":       50.0,
            "PriceBandLower":    lo,
            "PriceBandUpper":    hi,
            "LotSize":           lot_size,
            "GMP":               round(gmp_frac, 4),
            "gmp_pct":           round(gmp_pct, 2),
            "SubscriptionTimes": 0.0,
            "CloseDate":         effective_cd.strftime("%Y-%m-%d") if effective_cd else "TBD",
            "OpenDate":          od.strftime("%Y-%m-%d") if od else "",
            "ListingDate":       ld.strftime("%Y-%m-%d") if ld else (rec.listing_date or ""),
            "DaysToClose":       days,
            "IsUpcoming":        status == IPOStatus.UPCOMING,
            "ScrStatus":         status.value,
            "_date_fallback":    date_fallback,
            "Source":            src_str,
            "_gmp_inr":          gmp_num if gmp_num > 0 else None,
        })
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE E — NSE JSON API
# ══════════════════════════════════════════════════════════════════════════════

def fetch_source_e_nse() -> pd.DataFrame:
    log.info("━━ SOURCE E: NSE India ━━")
    sess = _make_session("https://www.nseindia.com/market-data/all-upcoming-issues-ipo")
    sess.headers.update({
        "Accept":           "application/json, text/plain, */*",
        "Accept-Language":  "en-IN,en;q=0.9",
        "Accept-Encoding":  "gzip, deflate",
        "Referer":          "https://www.nseindia.com/market-data/all-upcoming-issues-ipo",
        "X-Requested-With": "XMLHttpRequest",
    })

    try:
        sess.get(NSE_BASE, timeout=20, headers={"Connection": "close"})
        _jitter(1.5, 2.5)
    except Exception as exc:
        log.warning(f"  NSE warmup (non-fatal): {exc}")

    def _parse_nse(data) -> pd.DataFrame:
        records = []
        if isinstance(data, list):
            data = {"Current": data}
        for section_key, is_upcoming in [("Current", False), ("Forthcoming", True)]:
            for item in data.get(section_key, []):
                if not isinstance(item, dict):
                    continue
                sym = str(item.get("companyName", item.get("symbol", ""))).strip()
                if not sym or len(sym) < 2:
                    continue
                sub_type = str(item.get("subType", "MAIN")).upper()
                sector   = "SME" if "SME" in sub_type or "EMERGE" in sub_type else "Mainboard"
                lo, hi   = _parse_price_band(str(item.get("priceBand", item.get("issuePrice", "0"))))
                size     = _flt(item.get("issueSize", 50.0), 50.0)
                if size > 50_000:
                    size /= 1e7
                lot = _int(item.get("minBidQuantity", item.get("lotSize", 0))) or 50
                sub_raw = str(item.get("subscriptionStatus", "0"))
                sub = _flt(re.search(r"[\d.]+", sub_raw).group()
                           if re.search(r"[\d.]+", sub_raw) else "0")
                cd  = _parse_date_legacy(str(item.get("closeDate", item.get("biddingEndDate", ""))))
                od  = _parse_date_legacy(str(item.get("openDate", item.get("biddingStartDate", ""))))
                date_fallback = (cd is None)
                if cd is None:
                    days = 20 if is_upcoming else 7
                    eff_cd = TODAY + timedelta(days=7)
                else:
                    days, eff_cd = (cd - TODAY).days, cd
                if not is_upcoming:
                    is_live, conf = _confirm_live_status(od, eff_cd, sub, date_fallback, "")
                    if not is_live:
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
                    "CloseDate":         eff_cd.strftime("%Y-%m-%d"),
                    "OpenDate":          od.strftime("%Y-%m-%d") if od else "",
                    "ListingDate":       "",
                    "DaysToClose":       days,
                    "IsUpcoming":        is_upcoming,
                    "ScrStatus":         "Upcoming" if is_upcoming else "Open",
                    "_date_fallback":    date_fallback,
                    "Source":            "nse_json",
                    "_gmp_inr":          None,
                })
        return pd.DataFrame(records)

    for endpoint in [NSE_API_URL, NSE_UPCOMING_API]:
        try:
            r = sess.get(endpoint, timeout=20)
            if r.status_code == 200 and not r.headers.get("x-deny-reason"):
                df = _parse_nse(r.json())
                if not df.empty:
                    log.info(f"  ✓ NSE: {len(df)} rows")
                    return df
        except Exception as exc:
            log.warning(f"  NSE {endpoint}: {exc}")
        _jitter(1.5, 2.5)

    log.warning("  ⚠ NSE: no data")
    return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# VALIDATION + ENRICHMENT
# ══════════════════════════════════════════════════════════════════════════════

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
    "ListingDate":       "",
    "DaysToClose":       7,
    "IsUpcoming":        False,
    "ScrStatus":         "Unknown",
    "_date_fallback":    False,
    "Source":            "unknown",
    "_gmp_inr":          None,
}

def _validate_row(row: pd.Series) -> Tuple[bool, str]:
    sym = str(row.get("Symbol", "")).strip()
    if not sym or len(sym) < 2 or sym.lower() in ("unknown", "nan", "none", ""):
        return False, "invalid_symbol"
    price       = float(row.get("PriceBandUpper", 0))
    is_upcoming = bool(row.get("IsUpcoming", False))
    if is_upcoming:
        if price > 200_000:
            return False, f"price_out_of_range:{price}"
    else:
        if price <= 0:
            return False, "live_price_zero"
        if price > 200_000:
            return False, f"price_out_of_range:{price}"
    lot = int(row.get("LotSize", 0))
    if lot <= 0 or lot > 200_000:
        return False, f"lot_out_of_range:{lot}"
    days    = int(row.get("DaysToClose", 0))
    date_fb = bool(row.get("_date_fallback", False))
    sub     = float(row.get("SubscriptionTimes", 0))
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
    if "IsUpcoming" not in df.columns:
        df["IsUpcoming"] = False
    if "_date_fallback" not in df.columns:
        df["_date_fallback"] = False
    df["gmp_pct"] = df["GMP"].apply(lambda g: round(float(g) * 100, 2))

    def _days(x):
        if str(x).upper() == "TBD":
            return 20
        d = _parse_date_legacy(str(x))
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
        log.info(f"  🗑 Dropped {dropped} invalid/closed rows")
    return pd.DataFrame(valid_rows).reset_index(drop=True) if valid_rows else pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# MASTER FETCH ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════════

def fetch_unified_calendar() -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    today_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    import concurrent.futures
    all_records: list = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        f_screener = executor.submit(_fetch_screener)
        f_ig       = executor.submit(_fetch_investorgain_new)
        f_groww    = executor.submit(_fetch_groww)
        f_india    = executor.submit(_fetch_indiatrade)
        for future in (f_screener, f_ig, f_groww, f_india):
            try:
                all_records.extend(future.result())
            except Exception as _exc:
                log.warning(f"  Parallel fetch error: {_exc}")

    log.info(f"Raw IPO records before dedup: {len(all_records)}")
    deduped_records = deduplicate_records(all_records)
    log.info(f"After dedup: {len(deduped_records)} unique IPOs")

    for rec in deduped_records:
        rec.status = _compute_scraper_status(rec, today_dt)

    scraper_df = _ipo_records_to_df(deduped_records)
    if not scraper_df.empty:
        frames.append(scraper_df)
        log.info(f"✅ Scraper layer: {len(scraper_df)} rows")

    nse_df = fetch_source_e_nse()
    if not nse_df.empty:
        frames.append(nse_df)

    if not frames:
        log.warning("⚠️ ALL SOURCES FAILED")
        return pd.DataFrame()

    raw      = pd.concat(frames, ignore_index=True)
    enriched = _enrich(raw)
    if enriched.empty:
        log.warning("All rows dropped by validation")
        return pd.DataFrame()

    best_gmp = (enriched[enriched["gmp_pct"] > 0]
                .sort_values("gmp_pct", ascending=False)
                .drop_duplicates("Symbol", keep="first")
                [["Symbol", "GMP", "gmp_pct"]])

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

    live_df       = deduped[~deduped["IsUpcoming"]].copy()
    upcoming_all  = deduped[deduped["IsUpcoming"]].copy()
    upcoming_tbd  = upcoming_all[upcoming_all["CloseDate"] == "TBD"]
    upcoming_real = upcoming_all[upcoming_all["CloseDate"] != "TBD"].sort_values("DaysToClose")
    upcoming_capped = pd.concat([
        upcoming_real.head(MAX_UPCOMING_TELEGRAM),
        upcoming_tbd.head(MAX_UPCOMING_TBD),
    ], ignore_index=True)
    deduped = pd.concat([live_df, upcoming_capped], ignore_index=True)

    log.info(f"✅ Final: {len(deduped)} IPOs  "
             f"({int((~deduped['IsUpcoming']).sum())} live, "
             f"{int(deduped['IsUpcoming'].sum())} upcoming)")
    return deduped


# ══════════════════════════════════════════════════════════════════════════════
# BAYESIAN WEIGHTS
# ══════════════════════════════════════════════════════════════════════════════

def bayesian_weight_update(df: pd.DataFrame) -> Dict[str, float]:
    w    = BASE_WEIGHTS.copy()
    live = df[~df["IsUpcoming"]] if "IsUpcoming" in df.columns else df
    avg_sub = live["SubscriptionTimes"].mean() if not live.empty else 1.0
    if avg_sub > 80:
        w["sub"]   = min(0.38, w["sub"]   + 0.10)
        w["gmp"]   = max(0.12, w["gmp"]   - 0.05)
        w["halal"] = max(0.09, w["halal"] - 0.05)
    elif avg_sub < 15:
        w["gmp"]   = min(0.32, w["gmp"]   + 0.10)
        w["sub"]   = max(0.18, w["sub"]   - 0.10)
        w["halal"] = min(0.19, w["halal"] + 0.05)
    total = sum(w.values())
    return {k: round(v / total, 6) for k, v in w.items()}


# ══════════════════════════════════════════════════════════════════════════════
# QUANT ENGINE
# ══════════════════════════════════════════════════════════════════════════════

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
    llm_confidence:  int  = 0
    llm_reason:      str  = ""
    llm_method:      str  = ""

def monte_carlo_allotment(sub, lot, size_cr, price, n=MC_RUNS):
    if sub <= 0 or lot <= 0 or price <= 0 or size_cr <= 0:
        return 0.0, 0.0, 0.0
    retail  = size_cr * 1e7 * 0.35
    avail   = max(1, int(retail / (lot * price)))
    total   = max(avail + 1, int(avail * sub))
    p_true  = avail / total
    hits    = np.random.binomial(1, p_true, n)
    p_hat   = hits.mean()
    z, denom = 1.96, 1 + 1.96**2 / n
    center  = (p_hat + 1.96**2 / (2 * n)) / denom
    spread  = (1.96 * math.sqrt(p_hat * (1 - p_hat) / n + 1.96**2 / (4 * n**2))) / denom
    return round(p_hat, 6), max(0.0, round(center - spread, 6)), min(1.0, round(center + spread, 6))

def compute_allotment(row: pd.Series) -> AllotmentProfile:
    sub   = max(0.1, float(row["SubscriptionTimes"]))
    price = float(row["PriceBandUpper"]) or 100.0
    lot   = int(row["LotSize"])
    size  = float(row["IssueSizeCr"])
    gmp   = float(row["GMP"])
    p_mc, ci_lo, ci_hi = monte_carlo_allotment(sub, lot, size, price)
    matrix  = {k: round(1 - (1 - p_mc) ** k, 6) for k in range(1, MAX_SYNDICATE + 1)}
    gain    = gmp * price * lot
    cost    = lot * price
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


# ══════════════════════════════════════════════════════════════════════════════
# v12 STRUCTURED OUTPUT SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

_SHARIAH_SO_SCHEMA: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "shariah_verdict",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "is_compliant":     {"type": "boolean"},
                "tier": {
                    "type": "string",
                    "enum": ["TIER_1_COMPLIANT", "TIER_2_CONDITIONAL", "HARAM_CORE_BUSINESS"],
                },
                "haram_reason":     {"type": ["string", "null"]},
                "compliance_notes": {"type": "string"},
                "confidence":       {"type": "integer"},
            },
            "required": ["is_compliant", "tier", "haram_reason", "compliance_notes", "confidence"],
            "additionalProperties": False,
        },
    },
}

_ADVISOR_SO_SCHEMA: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "weight_adjustment",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "gmp":       {"type": "number"},
                "sub":       {"type": "number"},
                "sentiment": {"type": "number"},
                "trend":     {"type": "number"},
                "size":      {"type": "number"},
                "halal":     {"type": "number"},
                "reasoning": {"type": "string"},
                "regime": {
                    "type": "string",
                    "enum": ["BEAR", "NEUTRAL", "BULL"],
                },
            },
            "required": ["gmp", "sub", "sentiment", "trend", "size", "halal", "reasoning", "regime"],
            "additionalProperties": False,
        },
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# v12 RULE-BASED AUDIT (debt/equity + revenue mix)
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_debt_equity_from_screener(symbol: str) -> Optional[float]:
    slug = re.sub(r"[^a-z0-9]+", "-", symbol.lower()).strip("-")
    url = f"https://www.screener.in/company/{slug}/"
    try:
        sess = _make_session()
        r = sess.get(url, timeout=10)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "lxml")
        rows = soup.select("section#ratios table tbody tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 2 and "Debt to equity" in cols[0].text:
                de_text = cols[1].text.strip()
                m = re.search(r"[\d.]+", de_text)
                if m:
                    return float(m.group())
        return None
    except Exception:
        return None

def _rule_based_audit(symbol: str, sector: str, description: str) -> dict:
    sector_low = sector.lower()
    for kw in OBVIOUS_HARAM_SECTORS:
        if kw in sector_low or kw in description.lower():
            return {
                "is_compliant": False,
                "tier": "HARAM_CORE_BUSINESS",
                "haram_reason": f"Sector/description matches haram keyword: '{kw}'",
                "compliance_notes": "Rule‑based blocking.",
                "confidence": 80,
                "_method": "rule_haram"
            }
    for kw in OBVIOUS_HALAL_SECTORS:
        if kw in sector_low or kw in description.lower():
            return {
                "is_compliant": True,
                "tier": "TIER_1_COMPLIANT",
                "haram_reason": None,
                "compliance_notes": "Obvious halal sector (rule‑based).",
                "confidence": 85,
                "_method": "rule_halal"
            }
    de = _fetch_debt_equity_from_screener(symbol)
    if de is not None:
        if de > 0.33:
            return {
                "is_compliant": False,
                "tier": "HARAM_CORE_BUSINESS",
                "haram_reason": f"Debt/Equity ratio = {de:.2f} ( > 0.33 )",
                "compliance_notes": "Excessive interest‑bearing debt.",
                "confidence": 70,
                "_method": "rule_debt"
            }
        elif de > 0.2:
            return {
                "is_compliant": True,
                "tier": "TIER_2_CONDITIONAL",
                "haram_reason": None,
                "compliance_notes": f"Debt/Equity = {de:.2f} (near limit). Further analysis needed.",
                "confidence": 60,
                "_method": "rule_debt"
            }
    return {
        "is_compliant": True,
        "tier": "TIER_2_CONDITIONAL",
        "haram_reason": None,
        "compliance_notes": "Rule‑based audit could not determine; treat as conditional.",
        "confidence": 30,
        "_method": "rule_unknown"
    }


# ══════════════════════════════════════════════════════════════════════════════
# SHARIAH ENGINE — audit cache + company description scraper
# ══════════════════════════════════════════════════════════════════════════════

HARAM_SECTORS: set = {
    "bank", "banking", "finance", "financial", "nbfc",
    "microfinance", "moneylending", "insurance", "reinsurance",
    "brewery", "distillery", "liquor", "alcohol", "wine", "spirits",
    "casino", "gambling", "lottery",
    "pork", "pig", "swine",
    "tobacco", "cigarette", "cigar",
    "adult entertainment", "pornography",
}

_SHARIAH_SYSTEM_PROMPT = """You are an expert Islamic finance auditor following strict traditional \
Hanafi jurisprudence as codified by Ala Hazrat Ahmad Raza Khan Barelvi and contemporary scholars \
including Mufti Taqi Usmani and Mufti Salman Azhari.

Your task: analyse a company's core business model and determine whether investing in its IPO is \
permissible (Halal) or forbidden (Haram).

SCREENING CRITERIA (apply in order):

1. RIBA (Interest) — Is the PRIMARY revenue from: conventional banking, lending, NBFCs, \
microfinance, shadow banking, factoring, or any interest-bearing financial product? If yes → HARAM.

2. MAYSIR / GHARAR — Is the core business: casinos, online/offline gambling, lotteries, \
conventional insurance/reinsurance, speculative derivatives trading? If yes → HARAM.

3. HARAM COMMODITIES — Does the company primarily produce/distribute/sell: alcohol, pork/pork \
products, tobacco, weapons of mass destruction, adult entertainment/pornography? If yes → HARAM.

4. MIXED BUT PREDOMINANTLY HARAM — If >50% of revenue derives from above categories even if \
alongside permissible activities → HARAM.

5. GREY ZONE — If the business is permissible in principle but has significant interest-bearing \
debt (debt/equity > 33%) or substantial impermissible income (>5% of revenue) → flag as \
CONDITIONAL, not HARAM.

IMPORTANT: A fintech that provides payments, logistics software, e-commerce, SaaS, \
manufacturing, healthcare, education, agriculture, or real estate development is generally \
COMPLIANT unless it directly earns from interest or forbidden commodities.

Set confidence to 0–100 reflecting your certainty given the description quality."""

# ── SQLite audit cache ────────────────────────────────────────────────────────
_AUDIT_CACHE_PATH = Path("data/shariah_audit_cache.db")

def _init_audit_cache():
    _AUDIT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(_AUDIT_CACHE_PATH)) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS shariah_cache (
                symbol         TEXT PRIMARY KEY,
                is_compliant   INTEGER,
                tier           TEXT,
                haram_reason   TEXT,
                notes          TEXT,
                confidence     INTEGER,
                description    TEXT,
                cached_at      TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

def _cache_get(symbol: str) -> Optional[dict]:
    try:
        with sqlite3.connect(str(_AUDIT_CACHE_PATH)) as con:
            row = con.execute(
                "SELECT is_compliant,tier,haram_reason,notes,confidence,cached_at "
                "FROM shariah_cache WHERE symbol=?", (symbol,)
            ).fetchone()
        if not row:
            return None
        cached_at = datetime.fromisoformat(row[5])
        if (datetime.utcnow() - cached_at).days > 7:
            return None
        return {
            "is_compliant": bool(row[0]), "tier": row[1],
            "haram_reason": row[2], "compliance_notes": row[3],
            "confidence": row[4],
        }
    except Exception:
        return None

def _cache_set(symbol: str, result: dict, description: str):
    try:
        with sqlite3.connect(str(_AUDIT_CACHE_PATH)) as con:
            con.execute("""
                INSERT OR REPLACE INTO shariah_cache
                    (symbol,is_compliant,tier,haram_reason,notes,confidence,description,cached_at)
                VALUES (?,?,?,?,?,?,?,?)
            """, (
                symbol, int(result.get("is_compliant", True)),
                result.get("tier", "TIER_2_CONDITIONAL"),
                result.get("haram_reason"), result.get("compliance_notes", ""),
                result.get("confidence", 0), description[:2000],
                datetime.utcnow().isoformat(),
            ))
    except Exception as exc:
        log.warning(f"  Audit cache write failed: {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# FIX 2 — fetch_company_description() (FULL REPLACEMENT)
# Multi-source scraper with 6 fallback URLs + name-derived stub as last resort
# ══════════════════════════════════════════════════════════════════════════════

_DESC_CACHE: Dict[str, str] = {}


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _extract_desc_text(soup: BeautifulSoup, min_len: int = 40) -> str:
    """Surgically extract the business model, ignoring website boilerplate."""
    
    # 1. Destroy generic noise before searching
    for bad in soup.find_all(['nav', 'footer', 'script', 'style', 'noscript', 'header', 'aside']):
        bad.decompose()

    # 2. Chittorgarh-Specific Golden Target
    # Chittorgarh usually starts their descriptions with "Incorporated in..." or "Founded in..."
    for p in soup.find_all("p"):
        text = p.get_text(" ", strip=True)
        if "incorporated in" in text.lower() or "founded in" in text.lower():
            # Grab this paragraph and the next two
            siblings = p.find_next_siblings("p", limit=2)
            combined = text + " " + " ".join(s.get_text(" ", strip=True) for s in siblings)
            if len(combined) >= min_len:
                return combined

    # 3. Generic Fallbacks for other sites
    for tag, attrs in [
        ("div",     {"itemprop": "articleBody"}),
        ("div",     {"class": re.compile(r"company-profile|about-company|desc", re.I)}),
        ("section", {"id":    re.compile(r"about|overview|business", re.I)}),
        ("p",       {}), 
    ]:
        blocks = soup.find_all(tag, attrs)[:3]
        text   = " ".join(b.get_text(" ", strip=True) for b in blocks)
        text   = re.sub(r"\s+", " ", text).strip()
        
        # Filter out generic 300-char site disclaimers
        if len(text) >= min_len and "India's No 1" not in text and "cookie" not in text.lower():
            return text

    return ""
    
def _name_based_stub(company_name: str) -> str:
    """
    Construct a minimal ~90-char description from the company name alone.
    Passes the 60-char gate; LLM will return low confidence → rule fallback.
    """
    clean = re.sub(
        r"\b(limited|ltd|pvt|private|public|co\.?|inc|corp|ipo|sme)\b",
        "", company_name, flags=re.IGNORECASE,
    ).strip(" ,-")
    return (
        f"{clean} is a company seeking to raise capital through an IPO listed on "
        f"the Indian stock exchange. Full business details are currently unavailable; "
        f"apply manual Shariah review before investing."
    )


def _is_antibot_page(html: str, status_code: int) -> bool:
    """
    Detect Cloudflare / anti-bot interstitials that return 200 but are useless.
    Triggers on: 403/429 status, or telltale HTML phrases.
    """
    if status_code in (403, 429, 503):
        return True
    lower = html.lower()
    triggers = (
        "just a moment",            # Cloudflare 'checking your browser'
        "cloudflare",               # Cloudflare branding
        "enable javascript",        # JS gate
        "ddos-guard",               # DDoS-Guard
        "please wait",              # Generic spinner
        "access denied",
        "403 forbidden",
        "captcha",
    )
    return any(t in lower for t in triggers)


def fetch_company_description(company_name: str) -> str:
    """
    FIX 2 (upgraded): Cloudflare-piercing description fetcher.

    Fetch strategy per URL (3-tier):
      Tier A — cloudscraper  (stealth TLS fingerprint, bypasses most CF rules)
      Tier B — Playwright    (full headless browser, defeats JS challenges)
      Tier C — name-based stub (last resort; low-confidence flag sent to tracker)

    Sources tried in order:
      1. Chittorgarh IPO page      (most detailed Indian IPO descriptions)
      2. Screener.in company page  (good for listed/pre-IPO financials)
      3. Moneycontrol IPO page     (large editorial coverage)
      4. Economic Times IPO page   (good sector + revenue summaries)
      5. NSE company info page     (official but JS-heavy → PW handles it)
      6. BSE stock page            (fallback official source)
    """
    if company_name in _DESC_CACHE:
        return _DESC_CACHE[company_name]

    slug        = _slugify(company_name)
    slug_nodash = slug.replace("-", "")
    slug_upper  = company_name.strip().upper().replace(" ", "")[:15]

    sources = [
        ("chittorgarh",  f"https://www.chittorgarh.com/ipo/{slug}-ipo/"),
        ("screener",     f"https://www.screener.in/company/{slug_nodash}/"),
        ("moneycontrol", f"https://www.moneycontrol.com/ipo/{slug}-ipo/"),
        ("et_ipo",       f"https://economictimes.indiatimes.com/markets/ipos/fpos/{slug}-ipo"),
        ("nse",          f"https://www.nseindia.com/get-quotes/equity?symbol={slug_upper}"),
        ("bse",          f"https://www.bseindia.com/stock-share-price/{slug}/{slug_upper}/"),
    ]

    # ── Build cloudscraper once (reuse across all URLs this call) ─────────────
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False},
            delay=2,
        )
        _have_cs = True
    except ImportError:
        scraper   = None
        _have_cs  = False
        log.debug("  [desc] cloudscraper not installed — will use requests+playwright only")

    llm_tracker.start(company_name, "DESC_FETCH", f"trying {len(sources)} sources")

    for label, url in sources:
        html: Optional[str] = None

        # ── Tier A: cloudscraper ──────────────────────────────────────────────
        if _have_cs and scraper is not None:
            try:
                resp  = scraper.get(url, timeout=12)
                deny  = resp.headers.get("x-deny-reason", "")
                if deny:
                    log.debug(f"  [desc:{label}] egress deny={deny!r} — skip")
                    continue
                if not _is_antibot_page(resp.text, resp.status_code):
                    html = resp.text
                    log.debug(f"  [desc:{label}] cloudscraper OK  status={resp.status_code}")
                else:
                    log.debug(
                        f"  [desc:{label}] anti-bot detected (status={resp.status_code}) "
                        f"→ escalating to Playwright"
                    )
            except requests.exceptions.ConnectionError:
                log.debug(f"  [desc:{label}] CS connection blocked by egress proxy")
                continue
            except Exception as exc:
                log.debug(f"  [desc:{label}] CS error: {exc}")

        # ── Tier B: Playwright (when cloudscraper failed or triggered anti-bot) ─
        if html is None and PLAYWRIGHT_OK:
            log.debug(f"  [desc:{label}] deploying Playwright for {url}")
            llm_tracker.warn(
                company_name, "DESC_FETCH",
                f"{label}: CS blocked → Playwright fallback"
            )
            html = _pw_get_html(url, wait_ms=4000, selector="p, div, article")

        # ── Tier A fallback: plain requests if neither CS nor PW available ────
        if html is None and not _have_cs and not PLAYWRIGHT_OK:
            try:
                r    = requests.get(url, timeout=8, headers={
                    "User-Agent": random.choice(_USER_AGENTS),
                    "Accept-Language": "en-IN,en;q=0.9",
                    "Referer": "https://www.google.com/",
                })
                if r.status_code == 200 and not _is_antibot_page(r.text, r.status_code):
                    html = r.text
            except Exception:
                pass

        if not html:
            log.debug(f"  [desc:{label}] all tiers returned nothing — next source")
            continue

        # ── Parse whatever HTML we got ────────────────────────────────────────
        soup = BeautifulSoup(html, "lxml")
        text = _extract_desc_text(soup, min_len=40)
        if text:
            result = text[:3000]
            _DESC_CACHE[company_name] = result
            llm_tracker.ok(
                company_name, "DESC_FETCH",
                f"source={label}  len={len(result)}"
            )
            log.debug(f"  [desc:{label}] {company_name}: {len(result)} chars ✓")
            return result

        log.debug(f"  [desc:{label}] HTML fetched but no usable text extracted")

    # ── Tier C: name-based stub (guaranteed non-empty, flags low confidence) ──
    stub = _name_based_stub(company_name)
    _DESC_CACHE[company_name] = stub
    llm_tracker.warn(
        company_name, "DESC_FETCH",
        f"all {len(sources)} sources failed — name stub ({len(stub)} chars). "
        f"LLM will assign low confidence → rule-based fallback will activate."
    )
    log.warning(
        f"  [desc] {company_name}: all {len(sources)} sources failed "
        f"(cloudscraper={'yes' if _have_cs else 'no'}, "
        f"playwright={'yes' if PLAYWRIGHT_OK else 'no'}) "
        f"— using name stub"
    )
    return stub


# ══════════════════════════════════════════════════════════════════════════════
# FIX 3 — _sector_pre_filter() (FULL REPLACEMENT)
# Now receives description + company_name, not just the "SME"/"Mainboard" field
# ══════════════════════════════════════════════════════════════════════════════

def _sector_pre_filter(
    sector:       str,
    description:  str = "",
    company_name: str = "",
) -> Optional[Tuple[str, dict]]:
    """
    FIX 3: Builds a search corpus from ALL three inputs so keyword matching
    works even when sector is just "SME" or "Mainboard".
    """
    corpus = " ".join([
        sector.lower(),
        description.lower()[:600],
        company_name.lower(),
    ])

    # Haram has priority
    for kw in OBVIOUS_HARAM_SECTORS:
        if kw in corpus:
            return ("HARAM", {
                "is_compliant":     False,
                "tier":             "HARAM_CORE_BUSINESS",
                "haram_reason":     f"Matched haram keyword: '{kw}'",
                "compliance_notes": "Pre‑filter blocked (keyword in name/description/sector).",
                "confidence":       90,
                "_method":          "prefilter_haram",
            })

    for kw in OBVIOUS_HALAL_SECTORS:
        if kw in corpus:
            return ("HALAL", {
                "is_compliant":     True,
                "tier":             "TIER_1_COMPLIANT",
                "haram_reason":     None,
                "compliance_notes": f"Pre‑filter: halal keyword '{kw}' matched.",
                "confidence":       88,
                "_method":          "prefilter_halal",
            })

    return None  # ambiguous → proceed to LLM


# ══════════════════════════════════════════════════════════════════════════════
# SHARIAH ENGINE — audit_business_with_router (instrumented with LLMTracker)
# ══════════════════════════════════════════════════════════════════════════════

def _router_pending(reason: str) -> dict:
    return {
        "is_compliant":     True,
        "tier":             "TIER_2_CONDITIONAL",
        "haram_reason":     None,
        "compliance_notes": reason,
        "confidence":       0,
        "_method":          "pending",
    }

def audit_business_with_router(
    company_name: str,
    description:  str,
    _shariah_system_prompt: str = "",
) -> dict:
    """
    v12 primary Shariah auditor — OpenAI Structured Outputs with LLMTracker.
    Falls back to rule-based audit if LLM is unavailable or both tiers fail.
    """
    # ── Cache lookup ──────────────────────────────────────────────────────────
    llm_tracker.start(company_name, "CACHE_HIT")
    cached = _cache_get(company_name)
    if cached:
        cached["_method"] = "cache"
        llm_tracker.ok(
            company_name, "CACHE_HIT",
            f"conf={cached.get('confidence',0)}%  tier={cached.get('tier','?')}"
        )
        return cached
    llm_tracker.skip(company_name, "CACHE_HIT", "no valid cache entry")

    # ── Description quality gate ──────────────────────────────────────────────
    if not description or len(description) < 60:
        llm_tracker.warn(
            company_name, "OPENAI_MINI",
            f"description too short ({len(description)} chars) → rule fallback"
        )
        result = _rule_based_audit(company_name, "", description)
        result["_method"] = "rule_short_desc"
        return result

    # ── API key check ─────────────────────────────────────────────────────────
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        llm_tracker.fail(
            company_name, "OPENAI_MINI",
            "OPENAI_API_KEY not set — set it in your shell/.env"
        )
        log.warning("  [router] OPENAI_API_KEY not set — using rule‑based audit")
        return _rule_based_audit(company_name, "", description)

    try:
        import openai
    except ImportError:
        llm_tracker.fail(company_name, "OPENAI_MINI", "openai package not installed: pip install openai")
        return _rule_based_audit(company_name, "", description)

    client        = openai.OpenAI(api_key=api_key)
    system_prompt = _shariah_system_prompt or _SHARIAH_SYSTEM_PROMPT
    user_msg      = (
        f"Company name: {company_name}\n\n"
        f"Business description:\n{description[:2500]}"
    )

    # ── TIER 1: gpt-4o-mini ───────────────────────────────────────────────────
    mini_result: Optional[dict] = None
    llm_tracker.start(company_name, "OPENAI_MINI", f"desc_len={len(description)}")
    try:
        resp = client.chat.completions.create(
            model           = _ROUTER_FAST_MODEL,
            messages        = [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_msg},
            ],
            temperature     = 0.0,
            response_format = _SHARIAH_SO_SCHEMA,
            timeout         = 10,
        )
        mini_result = json.loads(resp.choices[0].message.content)
        conf        = int(mini_result.get("confidence", 0))

        if conf >= _ROUTER_CONFIDENCE_THRESHOLD:
            mini_result["_method"] = f"llm-{_ROUTER_FAST_MODEL}"
            _cache_set(company_name, mini_result, description)
            llm_tracker.ok(
                company_name, "OPENAI_MINI",
                f"{'HALAL' if mini_result['is_compliant'] else 'HARAM'}  conf={conf}%"
            )
            log.info(
                f"  [router] {company_name}: "
                f"{'✅ HALAL' if mini_result['is_compliant'] else '🚫 HARAM'} "
                f"via mini  conf={conf}%"
            )
            return mini_result

        llm_tracker.warn(
            company_name, "OPENAI_MINI",
            f"conf={conf}% < {_ROUTER_CONFIDENCE_THRESHOLD}% → escalating to gpt-4o"
        )
        log.info(
            f"  [router] {company_name}: mini conf={conf}% < "
            f"{_ROUTER_CONFIDENCE_THRESHOLD}% → escalating"
        )

    except Exception as exc:
        # Catch specific openai errors if openai is installed, else generic
        exc_name = type(exc).__name__
        if "Timeout" in exc_name:
            llm_tracker.fail(company_name, "OPENAI_MINI", f"timeout (10s)")
        elif "RateLimit" in exc_name:
            llm_tracker.fail(company_name, "OPENAI_MINI", "rate-limit hit")
        elif "Authentication" in exc_name:
            llm_tracker.fail(company_name, "OPENAI_MINI", "invalid API key — check OPENAI_API_KEY")
            log.error("  [router] OpenAI AuthenticationError — OPENAI_API_KEY wrong/expired")
            return _rule_based_audit(company_name, "", description)
        else:
            llm_tracker.fail(company_name, "OPENAI_MINI", f"{exc_name}: {str(exc)[:60]}")
        log.warning(f"  [router] {company_name}: mini failed ({exc}) → escalating")

    # ── TIER 2: gpt-4o ────────────────────────────────────────────────────────
    escalation_note = ""
    if mini_result:
        escalation_note = (
            f"\n\nPreliminary audit: tier='{mini_result.get('tier')}' "
            f"confidence={mini_result.get('confidence')}%. "
            f"Please give a more thorough analysis."
        )

    llm_tracker.start(company_name, "OPENAI_FULL", "escalated from mini")
    try:
        resp = client.chat.completions.create(
            model           = _ROUTER_FLAGSHIP_MODEL,
            messages        = [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_msg + escalation_note},
            ],
            temperature     = 0.0,
            response_format = _SHARIAH_SO_SCHEMA,
            timeout         = 20,
        )
        result = json.loads(resp.choices[0].message.content)
        result["_method"] = f"llm-{_ROUTER_FLAGSHIP_MODEL}-escalated"
        _cache_set(company_name, result, description)
        llm_tracker.ok(
            company_name, "OPENAI_FULL",
            f"{'HALAL' if result['is_compliant'] else 'HARAM'}  conf={result.get('confidence','?')}%"
        )
        log.info(
            f"  [router] {company_name}: "
            f"{'✅ HALAL' if result['is_compliant'] else '🚫 HARAM'} "
            f"via flagship  conf={result.get('confidence','?')}%"
        )
        return result

    except Exception as exc:
        exc_name = type(exc).__name__
        if "Timeout" in exc_name:
            llm_tracker.fail(company_name, "OPENAI_FULL", "timeout (20s)")
        elif "RateLimit" in exc_name:
            llm_tracker.fail(company_name, "OPENAI_FULL", "rate-limit hit")
        elif "Authentication" in exc_name:
            llm_tracker.fail(company_name, "OPENAI_FULL", "invalid API key")
        else:
            llm_tracker.fail(company_name, "OPENAI_FULL", f"{exc_name}: {str(exc)[:60]}")
        log.error(f"  [router] {company_name}: both tiers failed — {exc}")

    # ── Hard fallback ─────────────────────────────────────────────────────────
    rule_result = _rule_based_audit(company_name, "", description)
    rule_result["_method"] = "fallback_rule"
    llm_tracker.warn(
        company_name, "FINAL",
        "both OpenAI tiers failed — rule-based fallback applied"
    )
    return rule_result


# ══════════════════════════════════════════════════════════════════════════════
# FIX 3 — _pick_audit() (FULL REPLACEMENT)
# Passes description + company_name into pre-filter so keyword matching works
# ══════════════════════════════════════════════════════════════════════════════

def _pick_audit(company_name: str, description: str, sector: str) -> dict:
    """
    FIX 3: passes description AND company_name to _sector_pre_filter so that
    matching works against real text, not just "SME"/"Mainboard".

    Dispatch order:
      1. Sector pre-filter  (description + name + sector field)
      2. LLM router         (OpenAI primary)
      3. Rule-based audit   (automatic fallback)
    """
    llm_tracker.start(company_name, "PREFILTER", f"sector='{sector}'")
    pre = _sector_pre_filter(sector, description, company_name)
    if pre is not None:
        decision, result = pre
        llm_tracker.ok(
            company_name, "PREFILTER",
            f"{decision}  kw matched  conf={result['confidence']}%"
        )
        log.info(
            f"  [prefilter] {company_name}: {decision} "
            f"(conf={result['confidence']}%  method={result['_method']})"
        )
        return result

    llm_tracker.skip(company_name, "PREFILTER", "no keyword match → LLM")
    return audit_business_with_router(company_name, description)


# ══════════════════════════════════════════════════════════════════════════════
# SHARIAH ENGINE — keyword guard + master run_shariah()
# ══════════════════════════════════════════════════════════════════════════════

def _keyword_haram_check(sym: str, sector: str, description: str) -> Optional[str]:
    combined = (sym + " " + sector + " " + description).lower()
    for kw in HARAM_SECTORS:
        if kw in combined:
            return f"Keyword match: '{kw}' — likely impermissible core business."
    return None

def run_shariah(row: pd.Series, company_description: str = "") -> ShariahVerdict:
    """
    4-tier Shariah compliance check:
      Tier 0 – Sector pre-filter (obvious halal/haram via description + name)
      Tier 1 – LLM audit (OpenAI primary)
      Tier 2 – Keyword guard (safety net)
      Tier 3 – Market behaviour (Najash, Gharar, SME Hyper-pump)
    """
    gmp, sub, size, sector, sym = (
        float(row["GMP"]), float(row["SubscriptionTimes"]),
        float(row["IssueSizeCr"]), str(row["Sector"]), str(row["Symbol"])
    )
    barakah = 100.0
    issues: List[str] = []

    # ── TIER 0 & 1: Pre-filter / LLM ─────────────────────────────────────────
    desc = company_description or fetch_company_description(sym)
    llm  = _pick_audit(sym, desc, sector)

    method     = llm.get("_method", "pending")
    llm_conf   = int(llm.get("confidence", 0))
    llm_reason = llm.get("haram_reason") or llm.get("compliance_notes", "")

    # ── HARAM confidence gate + uncertainty detector ──────────────────────────
    # A genuine Shariah HARAM ruling requires EVIDENCE, not speculation.
    # Two conditions must BOTH be true to block:
    #   1. LLM said is_compliant=False
    #   2. Confidence >= _HARAM_MIN_CONFIDENCE  (≥60%)
    #   3. The reason does NOT contain uncertainty language
    #
    # If either condition fails, downgrade to TIER_2_CONDITIONAL (caution)
    # instead of a hard block — consistent with the principle of Ihtiyat
    # (precaution without injustice).
    if not llm.get("is_compliant", True):
        reason_str   = llm.get("haram_reason", "") or llm.get("compliance_notes", "")
        reason_lower = reason_str.lower()

        # Check whether the LLM is expressing doubt rather than a ruling
        _uncertain = any(phrase in reason_lower for phrase in _UNCERTAINTY_PHRASES)

        if llm_conf >= _HARAM_MIN_CONFIDENCE and not _uncertain:
            # ── Genuine high-confidence HARAM ruling ─────────────────────────
            issues.append(f"Audit: {reason_str}")
            qabda = "N/A — Investment not permissible per Shariah audit."
            llm_tracker.ok(
                sym, "FINAL",
                f"HARAM  conf={llm_conf}%  method={method}"
            )
            return ShariahVerdict(
                sym, "HARAM_CORE_BUSINESS", 0.0, False, qabda, issues,
                llm_confidence=llm_conf, llm_reason=reason_str, llm_method=method,
            )
        else:
            # ── Low-confidence or uncertain "HARAM" → downgrade to CONDITIONAL ─
            _why = (
                f"low confidence ({llm_conf}%)"
                if not _uncertain else
                f"uncertain language detected in reason"
            )
            downgrade_note = (
                f"LLM flagged concerns but {_why} — "
                f"treating as CONDITIONAL, not HARAM. Manual review advised."
            )
            issues.append(f"⚠️ Audit Downgraded: {downgrade_note}")
            if reason_str:
                issues.append(f"   LLM note: {reason_str[:160]}")
            barakah -= 20   # significant penalty, but not a full block
            llm_tracker.warn(
                sym, "FINAL",
                f"HARAM downgraded → CONDITIONAL  conf={llm_conf}%  uncertain={_uncertain}"
            )
            log.warning(
                f"  [shariah] {sym}: HARAM downgraded to CONDITIONAL "
                f"(conf={llm_conf}%  uncertain={_uncertain})"
            )

    # ── TIER 2: KEYWORD GUARD ─────────────────────────────────────────────────
    kw_reason = _keyword_haram_check(sym, sector, desc)
    if kw_reason:
        issues.append(f"Keyword Guard: {kw_reason}")
        qabda = "N/A — Investment not permissible (keyword screen)."
        llm_tracker.warn(sym, "FINAL", f"HARAM via keyword guard")
        return ShariahVerdict(
            sym, "HARAM_CORE_BUSINESS", 0.0, False, qabda, issues,
            llm_confidence=llm_conf, llm_reason=kw_reason, llm_method="keyword",
        )

    llm_tier = llm.get("tier", "TIER_2_CONDITIONAL")
    if llm_tier == "TIER_2_CONDITIONAL" and llm_conf >= 60:
        barakah -= 10
        issues.append(f"LLM: Conditional — {llm.get('compliance_notes','grey-zone flag')}")

    if method in ("pending", "rule_unknown") or llm_conf < 40:
        barakah -= 5
        issues.append("Shariah audit uncertain — apply caution.")

    # ── TIER 3: MARKET BEHAVIOUR ──────────────────────────────────────────────
    najash = gmp > 0.40 and sub > 80
    if najash:
        barakah -= 25
        issues.append("Najash Alert: GMP>40% + Sub>80× (artificial pump signal)")
    if size < 20:
        barakah -= 15
        issues.append("Microcap Hazard (<₹20 Cr) — High Gharar/manipulation risk")
    if sector == "SME" and sub > 200:
        barakah -= 10
        issues.append("SME Hyper-Pump (Sub>200×) — speculative frenzy")

    final_barakah = max(0.0, barakah)
    if llm_conf >= 70 and llm_tier == "TIER_1_COMPLIANT":
        tier = "TIER_1_COMPLIANT" if final_barakah >= 75 else "TIER_2_CONDITIONAL"
    else:
        tier = "TIER_1_COMPLIANT" if final_barakah >= 80 else "TIER_2_CONDITIONAL"

    qabda = ("QABDA: Hold until T+2 Demat settlement before resale. "
             "Listing-day flips = Gharar (OIC Fiqh Res. 3/3/86).")
    llm_tracker.ok(sym, "FINAL", f"{tier}  barakah={final_barakah:.0f}  method={method}")
    return ShariahVerdict(
        sym, tier, final_barakah, najash, qabda, issues,
        llm_confidence=llm_conf, llm_reason=llm_reason, llm_method=method,
    )


# ══════════════════════════════════════════════════════════════════════════════
# v12 — MARKET MOOD FILTER
# ══════════════════════════════════════════════════════════════════════════════

def get_market_regime() -> Tuple[str, float]:
    try:
        url = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050"
        sess = _make_session("https://www.nseindia.com")
        sess.headers.update({
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/",
        })
        sess.get(NSE_BASE, timeout=10)
        r = sess.get(url, timeout=10)
        if r.status_code == 200:
            data     = r.json()
            current  = float(data["data"][0]["lastPrice"])
            drawdown = 0.0
            regime   = "NEUTRAL" if drawdown <= 5 else "BEAR" if drawdown <= 10 else "CRASH"
            log.info(f"📉 Market Regime: {regime} (drawdown={drawdown:.1f}%)")
            return regime, drawdown
    except Exception as e:
        log.warning(f"  Market regime fetch failed: {e}")
    return "NEUTRAL", 0.0

def apply_market_mood_penalty(score: float) -> float:
    regime, dd = get_market_regime()
    if regime == "CRASH":
        penalty = 0.6
        log.info(f"  🛑 CRASH mode: applying {int((1-penalty)*100)}% score penalty")
        return round(score * penalty, 1)
    elif regime == "BEAR":
        penalty = 0.85
        log.info(f"  🐻 BEAR mode: applying {int((1-penalty)*100)}% penalty")
        return round(score * penalty, 1)
    return score


# ══════════════════════════════════════════════════════════════════════════════
# MASTER SCORE
# ══════════════════════════════════════════════════════════════════════════════

def _sector_avg_sub(df: pd.DataFrame, sector: str) -> float:
    if df is None or df.empty or "Sector" not in df.columns:
        return 1.0
    if "SubscriptionTimes" not in df.columns:
        return 1.0
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
    gmp_pct     = gmp * 100
    s_gmp       = min(100.0, gmp_pct * 1.5)
    s_sub       = min(100.0, sub) * tf
    sub_pts     = 30 if sub > 50 else 20 if sub > 25 else 10 if sub > 10 else 0
    gmp_pts     = 30 if gmp > 0.40 else 20 if gmp > 0.20 else 10 if gmp > 0.05 else 0
    days_pts    = 20 if days >= 3 else 10 if days >= 1 else 0
    s_sent      = min(100.0, sub_pts + gmp_pts + days_pts)
    if df_context is not None and not df_context.empty:
        sector_avg = _sector_avg_sub(df_context, sector)
        s_trd      = min(100.0, 50.0 * sub / max(1.0, sector_avg))
    else:
        s_trd = 50.0
    if size <= 0:      s_size = 10
    elif size <= 20:   s_size = 20
    elif size <= 50:   s_size = 40
    elif size <= 500:  s_size = 80
    elif size <= 2000: s_size = 90
    else:              s_size = 50
    s_hal = shariah.barakah_index
    raw   = (s_gmp * w["gmp"] + s_sub * w["sub"] + s_sent * w["sentiment"] +
             s_trd * w["trend"] + s_size * w["size"] + s_hal * w["halal"])
    final = min(100.0, max(0.0, round(raw, 1)))
    final = apply_market_mood_penalty(final)
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


# ══════════════════════════════════════════════════════════════════════════════
# v12 — AUTOMATED BACKTESTER
# ══════════════════════════════════════════════════════════════════════════════

def run_backtest(days_lookback: int = 180) -> None:
    log.info("📊 Running automated backtest (last %d days)...", days_lookback)
    try:
        with sqlite3.connect(str(IPO_DB_PATH)) as con:
            outcomes = pd.read_sql(f"""
                SELECT symbol, issue_price, lot_size,
                       predicted_gmp_pct, predicted_ev_inr,
                       day1_listing_price, day1_gain_pct,
                       t2_closing_price, halal_gain_pct, halal_profit_inr,
                       verdict_was, final_score_was, listed_date
                FROM ipo_outcomes
                WHERE listed_date >= date('now', '-{days_lookback} days')
                  AND t2_closing_price IS NOT NULL
                ORDER BY listed_date DESC
            """, con)
    except Exception as e:
        log.error(f"Backtest DB read failed: {e}")
        return

    if outcomes.empty:
        log.warning("No T+2 outcomes available for backtest.")
        return

    current_weights = BASE_WEIGHTS.copy()
    try:
        with sqlite3.connect(str(IPO_DB_PATH)) as con:
            last = con.execute(
                "SELECT new_weights FROM weight_history ORDER BY changed_at DESC LIMIT 1"
            ).fetchone()
            if last:
                current_weights = json.loads(last[0])
    except Exception:
        pass

    log.info(f"Using weights: {current_weights}")
    total_profit = total_capital = 0.0
    wins = losses = skipped = 0
    results = []

    for _, row in outcomes.iterrows():
        sym        = row["symbol"]
        t2_gain    = row["halal_gain_pct"]
        profit_inr = row["halal_profit_inr"] if not pd.isna(row["halal_profit_inr"]) else 0.0
        score_was  = row["final_score_was"]  if not pd.isna(row["final_score_was"])  else 0.0
        verdict_was = row["verdict_was"]     if not pd.isna(row["verdict_was"])      else ""

        if score_was >= 70:
            capital_at_risk = row["issue_price"] * row["lot_size"]
            total_capital  += capital_at_risk
            total_profit   += profit_inr
            wins   += 1 if t2_gain > 0 else 0
            losses += 1 if t2_gain <= 0 else 0
            results.append({
                "Symbol": sym, "Listed": row["listed_date"],
                "Score": score_was, "Verdict": verdict_was,
                "T2 Gain %": round(t2_gain, 2), "Profit ₹": round(profit_inr, 2),
            })
        else:
            skipped += 1

    total_trades = wins + losses
    win_rate = (wins / total_trades * 100) if total_trades else 0
    roi      = (total_profit / total_capital * 100) if total_capital else 0

    print("\n" + "═" * 80)
    print(f"📈 BACKTEST REPORT — Last {days_lookback} days")
    print("═" * 80)
    print(f"Trades taken (score≥70): {total_trades}")
    print(f"  Wins:  {wins}")
    print(f"  Losses:{losses}")
    print(f"  Win rate:              {win_rate:.1f}%")
    print(f"  Total profit:          ₹{total_profit:,.0f}")
    print(f"  Total capital deployed: ₹{total_capital:,.0f}")
    print(f"  ROI (capital weighted): {roi:.1f}%")
    print(f"  Skipped (score<70):    {skipped}")
    print("\nTop 5 best trades:")
    for t in sorted(results, key=lambda x: x["Profit ₹"], reverse=True)[:5]:
        print(f"  {t['Symbol']:<20} Score: {t['Score']:.0f}  Gain: {t['T2 Gain %']:+.1f}%  Profit: ₹{t['Profit ₹']:,.0f}")
    print("═" * 80)


# ══════════════════════════════════════════════════════════════════════════════
# v12 — MONTHLY ADVISOR (Claude primary, OpenAI fallback)
# ══════════════════════════════════════════════════════════════════════════════

def _persist_weight_change(old_weights, new_weights, reasoning, stats):
    try:
        with sqlite3.connect(str(IPO_DB_PATH)) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS weight_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    changed_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                    old_weights TEXT,
                    new_weights TEXT,
                    reasoning   TEXT,
                    regime      TEXT,
                    n_samples   INTEGER,
                    mae_pp      REAL,
                    gmp_bias_pp REAL
                )
            """)
            con.execute("""
                INSERT INTO weight_history
                    (old_weights, new_weights, reasoning, regime,
                     n_samples, mae_pp, gmp_bias_pp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                json.dumps(old_weights), json.dumps(new_weights),
                reasoning, stats.get("detected_regime", "NEUTRAL"),
                stats.get("n_samples", 0), stats.get("mae_pp", 0.0),
                stats.get("gmp_bias_pp", 0.0),
            ))
    except Exception as exc:
        log.warning(f"  _persist_weight_change: {exc}")

def run_monthly_strategy_advisor(base_weights: dict, days_lookback: int = 30) -> dict:
    try:
        with sqlite3.connect(str(IPO_DB_PATH)) as con:
            df = pd.read_sql(f"""
                SELECT symbol, predicted_gmp_pct, halal_gain_pct,
                       error_margin_pct, verdict_was, final_score_was, halal_profit_inr
                FROM ipo_outcomes
                WHERE t2_date >= date('now', '-{days_lookback} days')
                  AND halal_gain_pct IS NOT NULL
            """, con)
    except Exception as exc:
        log.warning(f"  [advisor] DB read failed: {exc}")
        return base_weights

    n = len(df)
    if n < _ADVISOR_MIN_SAMPLES:
        log.info(f"  [advisor] Only {n} T+2-complete outcomes — skipping.")
        return base_weights

    mae        = float(df["error_margin_pct"].mean())
    gmp_bias   = float((df["predicted_gmp_pct"] - df["halal_gain_pct"]).mean())
    avg_profit = float(df["halal_profit_inr"].mean())
    win_rate   = float((df["halal_gain_pct"] > 0).mean() * 100)
    buy_rows   = df[df["verdict_was"].str.contains("STRONG BUY|PEARL", na=False)]
    buy_win    = float((buy_rows["halal_gain_pct"] > 0).mean() * 100) if len(buy_rows) else 0.0
    regime     = "BEAR" if win_rate < 40 else "BULL" if win_rate > 75 else "NEUTRAL"

    stats_summary = {
        "n_samples": n, "lookback_days": days_lookback,
        "mae_pp": round(mae, 2), "gmp_bias_pp": round(gmp_bias, 2),
        "avg_halal_profit_inr": round(avg_profit, 2),
        "overall_win_rate": round(win_rate, 1),
        "strong_buy_win_rate": round(buy_win, 1),
        "detected_regime": regime,
        "sample_outcomes": df.head(15).to_dict(orient="records"),
    }

    log.info(
        f"  [advisor] {n} T+2 outcomes  MAE={mae:.1f}pp  "
        f"bias={gmp_bias:+.1f}pp  WinRate={win_rate:.0f}%  Regime={regime}"
    )

    prompt = f"""You are a quantitative portfolio analyst reviewing an IPO scoring model.
All performance metrics are based on T+2 settlement prices (Shariah-compliant Qabda).

CURRENT SCORING WEIGHTS:
{json.dumps(base_weights, indent=2)}

LAST {days_lookback}-DAY T+2 OUTCOME STATISTICS:
{json.dumps(stats_summary, indent=2)}

MANDATORY REGIME RULES:
  BEAR (win_rate < 40%): sub MUST be >= 0.40, gmp MUST be <= 0.15
  BULL (win_rate > 75%): gmp may be up to 0.30, sub minimum 0.22
  NEUTRAL: fine-tune only.

FINE-TUNING RULES:
  1. gmp_bias_pp > 5  → reduce gmp by 0.03-0.06
  2. gmp_bias_pp < -5 → increase gmp by up to 0.04
  3. strong_buy_win_rate < 60% → increase sub weight
  4. mae_pp > 20 → flatten toward equal (0.167 each)
  5. halal MUST stay between {_HALAL_WEIGHT_MIN} and {_HALAL_WEIGHT_MAX}
  6. Max change per weight per run: ±0.06
  7. All 6 weights must sum to exactly 1.0

Respond ONLY with JSON matching the schema."""

    # ── Try Claude first ──────────────────────────────────────────────────────
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if api_key:
        llm_tracker.start("ADVISOR", "CLAUDE", f"model={_ADVISOR_MODEL}")
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key":         api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":       _ADVISOR_MODEL,
                    "max_tokens":  800,
                    "temperature": 0,
                    "system":      prompt,
                    "messages":    [{"role": "user", "content": "Generate adjusted weights."}],
                },
                timeout=30,
            )
            if resp.status_code == 200:
                raw_text    = resp.json()["content"][0]["text"].strip()
                json_match  = re.search(r"\{.*\}", raw_text, re.DOTALL)
                if json_match:
                    parsed      = json.loads(json_match.group())
                    reasoning   = parsed.pop("reasoning", "(none)")
                    detected    = parsed.pop("regime", regime)
                    new_weights = {k: float(parsed.get(k, base_weights[k])) for k in _WEIGHT_KEYS}
                    new_weights["halal"] = max(_HALAL_WEIGHT_MIN, min(_HALAL_WEIGHT_MAX, new_weights["halal"]))
                    if detected == "BEAR":
                        new_weights["sub"] = max(0.40, new_weights["sub"])
                        new_weights["gmp"] = min(0.15, new_weights["gmp"])
                    elif detected == "BULL":
                        new_weights["gmp"] = min(0.30, new_weights["gmp"])
                        new_weights["sub"] = max(0.22, new_weights["sub"])
                    s = sum(new_weights.values())
                    new_weights = {k: round(v / s, 6) for k, v in new_weights.items()}
                    _persist_weight_change(base_weights, new_weights, reasoning, stats_summary)
                    llm_tracker.ok("ADVISOR", "CLAUDE", f"regime={detected}  weights updated")
                    log.info(f"  [advisor] Claude → New weights: {new_weights}")
                    return new_weights
            else:
                llm_tracker.fail("ADVISOR", "CLAUDE", f"HTTP {resp.status_code}")
        except Exception as e:
            llm_tracker.fail("ADVISOR", "CLAUDE", str(e)[:60])
            log.warning(f"  [advisor] Claude failed: {e} — falling back to OpenAI")

    # ── Fallback to OpenAI ────────────────────────────────────────────────────
    openai_key = os.getenv("OPENAI_API_KEY", "")
    if not openai_key:
        llm_tracker.fail("ADVISOR", "OPENAI", "no API key for advisor")
        log.warning("  [advisor] No API key — weights unchanged")
        return base_weights

    try:
        import openai
        client = openai.OpenAI(api_key=openai_key)
        llm_tracker.start("ADVISOR", "OPENAI", "OpenAI advisor fallback")
        resp = client.chat.completions.create(
            model           = "gpt-4o",
            messages        = [{"role": "user", "content": prompt}],
            temperature     = 0.0,
            response_format = _ADVISOR_SO_SCHEMA,
            timeout         = 30,
        )
        parsed      = json.loads(resp.choices[0].message.content)
        reasoning   = parsed.pop("reasoning", "(none)")
        detected    = parsed.pop("regime", regime)
        new_weights = {k: float(parsed.get(k, base_weights[k])) for k in _WEIGHT_KEYS}
        new_weights["halal"] = max(_HALAL_WEIGHT_MIN, min(_HALAL_WEIGHT_MAX, new_weights["halal"]))
        if detected == "BEAR":
            new_weights["sub"] = max(0.40, new_weights["sub"])
            new_weights["gmp"] = min(0.15, new_weights["gmp"])
        elif detected == "BULL":
            new_weights["gmp"] = min(0.30, new_weights["gmp"])
            new_weights["sub"] = max(0.22, new_weights["sub"])
        s = sum(new_weights.values())
        new_weights = {k: round(v / s, 6) for k, v in new_weights.items()}
        _persist_weight_change(base_weights, new_weights, reasoning, stats_summary)
        llm_tracker.ok("ADVISOR", "OPENAI", f"regime={detected}")
        log.info(f"  [advisor] OpenAI fallback → New weights: {new_weights}")
        return new_weights
    except Exception as exc:
        llm_tracker.fail("ADVISOR", "OPENAI", str(exc)[:60])
        log.error(f"  [advisor] Advisor failed: {exc}")
        return base_weights


# ══════════════════════════════════════════════════════════════════════════════
# T+2 OUTCOME CAPTURE
# ══════════════════════════════════════════════════════════════════════════════

def capture_listing_outcome(
    symbol, issue_price, lot_size, predicted_gmp_pct,
    predicted_ev_inr, day1_listing_price,
    verdict_was="", final_score_was=0.0, listed_date="",
):
    day1_gain_pct = ((day1_listing_price - issue_price) / max(1.0, issue_price)) * 100
    listed_date   = listed_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        with sqlite3.connect(str(IPO_DB_PATH)) as con:
            con.execute("""
                INSERT OR REPLACE INTO ipo_outcomes (
                    symbol, issue_price, lot_size, predicted_gmp_pct, predicted_ev_inr,
                    day1_listing_price, day1_gain_pct, verdict_was, final_score_was, listed_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol, issue_price, lot_size, predicted_gmp_pct, predicted_ev_inr,
                day1_listing_price, round(day1_gain_pct, 4),
                verdict_was, final_score_was, listed_date,
            ))
        log.info(
            f"📒 Muhasabah Day-1: {symbol}  @ ₹{day1_listing_price:.0f}  "
            f"day1={day1_gain_pct:+.1f}%  (T+2 pending)"
        )
    except Exception as exc:
        log.warning(f"  capture_listing_outcome failed for {symbol}: {exc}")

def capture_t2_outcome(symbol: str, t2_closing_price: float, t2_date: str = ""):
    t2_date = t2_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        with sqlite3.connect(str(IPO_DB_PATH)) as con:
            row = con.execute(
                "SELECT issue_price, lot_size, predicted_gmp_pct FROM ipo_outcomes WHERE symbol=?",
                (symbol,)
            ).fetchone()
        if not row:
            log.warning(f"  capture_t2_outcome: {symbol} not found")
            return
        issue_price, lot_size, pred_gmp = float(row[0]), int(row[1]), float(row[2] or 0)
        halal_gain_pct = ((t2_closing_price - issue_price) / max(1.0, issue_price)) * 100
        halal_profit   = (t2_closing_price - issue_price) * lot_size
        error_margin   = abs(pred_gmp - halal_gain_pct)
        with sqlite3.connect(str(IPO_DB_PATH)) as con:
            con.execute("""
                UPDATE ipo_outcomes
                SET t2_closing_price=?, halal_gain_pct=?, halal_profit_inr=?,
                    error_margin_pct=?, t2_date=?
                WHERE symbol=?
            """, (t2_closing_price, round(halal_gain_pct, 4),
                  round(halal_profit, 2), round(error_margin, 4), t2_date, symbol))
        log.info(
            f"📒 Muhasabah T+2: {symbol}  @ ₹{t2_closing_price:.0f}  "
            f"halal_gain={halal_gain_pct:+.1f}%  profit=₹{halal_profit:,.0f}"
        )
    except Exception as exc:
        log.warning(f"  capture_t2_outcome failed for {symbol}: {exc}")

def _detect_and_capture_outcomes(current_df: pd.DataFrame) -> None:
    if current_df.empty:
        return
    try:
        with sqlite3.connect(str(IPO_DB_PATH)) as con:
            prev = pd.read_sql("""
                SELECT symbol, gmp_pct, ev_inr, verdict, final_score, price_upper, lot_size
                FROM ipo_scans
                WHERE is_upcoming = 0
                  AND scr_status NOT IN ('Listed', 'LISTED')
                ORDER BY run_date DESC
            """, con)
    except Exception as exc:
        log.debug(f"  _detect_and_capture_outcomes: {exc}")
        return
    if prev.empty:
        return
    scr_col    = current_df.get("ScrStatus", pd.Series(dtype=str))
    listed_now = current_df[scr_col.str.upper() == "LISTED"]
    for _, row in listed_now.iterrows():
        sym = str(row["Symbol"])
        if prev[prev["symbol"] == sym].empty:
            continue
        prev_row   = prev[prev["symbol"] == sym].iloc[0]
        raw_price  = row.get("ListingDate", "") or row.get("listing_price", "")
        m          = re.search(r"[\d.]+", str(raw_price).replace(",", ""))
        if not m:
            continue
        day1_price = float(m.group())
        if day1_price <= 0:
            continue
        issue_price = float(prev_row.get("price_upper", 0))
        if issue_price <= 0:
            continue
        capture_listing_outcome(
            symbol=sym, issue_price=issue_price,
            lot_size=int(prev_row.get("lot_size", 1)),
            predicted_gmp_pct=float(prev_row.get("gmp_pct", 0)),
            predicted_ev_inr=float(prev_row.get("ev_inr", 0)),
            day1_listing_price=day1_price,
            verdict_was=str(prev_row.get("verdict", "")),
            final_score_was=float(prev_row.get("final_score", 0)),
        )


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════════════════════

def _extend_init_db_for_v11(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS ipo_outcomes (
            symbol              TEXT PRIMARY KEY,
            issue_price         REAL,
            lot_size            INTEGER,
            predicted_gmp_pct   REAL,
            predicted_ev_inr    REAL,
            day1_listing_price  REAL,
            day1_gain_pct       REAL,
            t2_closing_price    REAL,
            halal_gain_pct      REAL,
            halal_profit_inr    REAL,
            error_margin_pct    REAL,
            verdict_was         TEXT,
            final_score_was     REAL,
            listed_date         TEXT,
            t2_date             TEXT,
            recorded_at         TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS weight_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            changed_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            old_weights TEXT,
            new_weights TEXT,
            reasoning   TEXT,
            regime      TEXT,
            n_samples   INTEGER,
            mae_pp      REAL,
            gmp_bias_pp REAL
        )
    """)

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
            )""")
        existing = {row[1] for row in con.execute("PRAGMA table_info(ipo_scans)")}
        for col_name, ddl in {
            "listing_date":   "ALTER TABLE ipo_scans ADD COLUMN listing_date TEXT DEFAULT ''",
            "scr_status":     "ALTER TABLE ipo_scans ADD COLUMN scr_status TEXT DEFAULT ''",
            "llm_confidence": "ALTER TABLE ipo_scans ADD COLUMN llm_confidence INTEGER DEFAULT 0",
            "llm_reason":     "ALTER TABLE ipo_scans ADD COLUMN llm_reason TEXT DEFAULT ''",
            "llm_method":     "ALTER TABLE ipo_scans ADD COLUMN llm_method TEXT DEFAULT ''",
        }.items():
            if col_name not in existing:
                con.execute(ddl)
        _extend_init_db_for_v11(con)
    log.info("🗄 DB ready (v12).")
    _init_audit_cache()

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
                    close_date, open_date, days_to_close, p_single_mc, ci_lo, ci_hi,
                    optimal_syndicate, kelly_pct, ev_inr, roi_pct,
                    barakah, halal_tier, najash_alert, source, date_fallback,
                    listing_date, scr_status, llm_confidence, llm_reason, llm_method
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                date_label, sym, r["Sector"], r["FinalScore"], r["Verdict"],
                int(r.get("IsUpcoming", False)),
                r["SubscriptionTimes"], r["gmp_pct"], r["IssueSizeCr"],
                r["PriceBandUpper"], int(r["LotSize"]),
                r["CloseDate"], r.get("OpenDate", ""), int(r["DaysToClose"]),
                a.p_single_mc, a.ci_95[0], a.ci_95[1], a.optimal_syndicate,
                a.kelly_pct, a.ev_inr, a.roi_pct,
                sh.barakah_index, sh.tier, int(sh.najash_alert),
                str(r.get("Source", "unknown")), int(r.get("_date_fallback", False)),
                str(r.get("ListingDate", "")), str(r.get("ScrStatus", "")),
                sh.llm_confidence, sh.llm_reason[:500] if sh.llm_reason else "",
                sh.llm_method,
            ))
    log.info(f"🗄 Persisted {len(df)} records.")


# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════════════════

_SEP = "━" * 20

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
                log.info(f"  TG 429 → wait {retry_after}s")
                time.sleep(retry_after + 1)
            else:
                log.warning(f"  TG {r.status_code}: {r.text[:80]}")
                return
        except Exception as exc:
            log.error(f"  TG error: {exc}")
            return

def _tg_clean(sym: str) -> str:
    sym = re.sub(
        r"(?<=[A-Za-z0-9.])(?:BSE|NSE)\s*(?:SME|EMERGE)[A-Z]{0,3}"
        r"(?:@[\d.]+\s*\([+-]?[\d.]+%\))?\s*$", "", sym
    ).strip()
    sym = re.sub(r"(?<=[A-Za-z0-9.])IPO[A-Z]?(?:@[\d.]+\s*\([+-]?[\d.]+%\))?\s*$", "", sym).strip()
    sym = re.sub(r"@[\d.,]+\s*\([+-]?[\d.%]+\)\s*$", "", sym).strip()
    return re.sub(r"\s+", " ", sym).strip() or "UNKNOWN"

def _verdict_action(verdict: str, score: float) -> str:
    if "PEARL"      in verdict: return "Exceptional across all signals. Apply maximum lots immediately."
    if "STRONG BUY" in verdict: return "Strong risk/reward. Apply full allocation."
    if "MODERATE"   in verdict: return "Decent opportunity. Apply 1–2 lots cautiously."
    if "UPCOMING"   in verdict: return "Mark calendar. Set alert for open date."
    return "Risk/reward not favourable. Skip this round."

def _format_price(lo: float, hi: float) -> str:
    if hi <= 0:        return "Price TBD"
    if lo <= 0 or lo == hi: return f"₹{hi:,.0f}"
    return f"₹{lo:,.0f} – ₹{hi:,.0f}"

def _format_days(days: int) -> str:
    if days == 0: return "⏰ Closing TODAY — apply now"
    if days == 1: return "⏰ 1 day left — apply today"
    return f"⏰ {days} days remaining"

def build_ipo_card(row: pd.Series, allot: AllotmentProfile, shariah: ShariahVerdict) -> str:
    sym      = html_lib.escape(_tg_clean(str(row["Symbol"])))
    score    = row["FinalScore"]
    verdict  = str(row["Verdict"])
    action   = _verdict_action(verdict, score)
    sector   = html_lib.escape(str(row.get("Sector", "?")))
    size_cr  = float(row.get("IssueSizeCr", 50.0))
    source   = html_lib.escape(str(row.get("Source", "")))
    hi       = float(row["PriceBandUpper"])
    lo       = float(row["PriceBandLower"])
    lot      = int(row["LotSize"])
    lot_cost = hi * lot if hi > 0 else 0
    price_str = _format_price(lo, hi)
    days     = int(row.get("DaysToClose", 0))
    days_part = _format_days(days)
    is_haram  = (shariah.tier == "HARAM_CORE_BUSINESS")

    if is_haram:
        sh_icon, sh_label = "🚫", "HARAM — Do Not Invest"
    elif "TIER_1" in shariah.tier:
        sh_icon, sh_label = "🟢", "Tier 1 Compliant"
    else:
        sh_icon, sh_label = "🟡", "Tier 2 Conditional"

    _method_badge = {
        "cache":            f"🤖 LLM Cached  ({shariah.llm_confidence}% confidence)",
        "keyword":          "⚙️ Keyword Screen",
        "pending":          "⏳ Audit Pending",
        "prefilter_halal":  "🟢 Pre‑filter (Halal)",
        "prefilter_haram":  "🔴 Pre‑filter (Haram)",
        "rule_halal":       "📜 Rule‑based (Halal)",
        "rule_haram":       "📜 Rule‑based (Haram)",
        "rule_debt":        "📜 Debt/Equity rule",
        "fallback_rule":    "⚙️ Fallback rule",
        "rule_short_desc":  "📜 Rule (short desc)",
    }.get(shariah.llm_method, "⏳ Unknown")

    if shariah.llm_method.startswith("llm-"):
        _method_badge = f"🤖 SO Router ({shariah.llm_confidence}% confidence)"

    if is_haram:
        reason = html_lib.escape(shariah.llm_reason or "Core business is impermissible.")
        return (
            f"🚫 <b>SHARIAH BLOCK — DO NOT APPLY</b>\n"
            f"<b>{sym}</b> · <code>{sector}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Ruling:</b> HARAM CORE BUSINESS\n"
            f"<b>Reason:</b> <i>{reason}</i>\n"
            f"<b>Audit:</b> {_method_badge}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Barakah: 0/100  ·  Score: {score:.0f}/100\n"
            f"Source: {source}"
        )

    em       = "🔥" if score >= 80 else "✅" if score >= 70 else "📈" if score >= 60 else "❌"
    gmp_inr  = row.get("_gmp_inr")
    gmp_pct  = float(row.get("gmp_pct", 0.0))
    gmp_text = (f"₹{float(gmp_inr):.0f} ({gmp_pct:.1f}%)" if gmp_inr and float(gmp_inr) > 0
                else (f"{gmp_pct:.1f}%" if gmp_pct > 0 else "Awaiting Data"))
    sub      = float(row.get("SubscriptionTimes", 0.0))
    sub_text = f"{sub:.1f}× overall" if sub > 0 else "Awaiting Live Tapes"

    if "SKIP" in verdict:
        return (
            f"{em} <b>IPO AVOID │ Score: {score:.0f}/100</b>\n"
            f"<b>{sym}</b> · <code>{sector}</code>\n────────────────────\n"
            f"<b>Action:</b> {html_lib.escape(action)}\n────────────────────\n"
            f"• Price: {price_str}  (Lot: {lot:,} shares)\n"
            f"• Capital: ₹{lot_cost:,.0f}\n"
            f"• Size: ₹{size_cr:.0f} Cr  ·  {days_part}\n"
            f"• Shariah: {sh_icon} {sh_label}  (Barakah {shariah.barakah_index:.0f}/100)\n"
            + (f"• {_method_badge}\n" if shariah.llm_confidence > 0 else "")
            + (f"• <i>🚨 " + " | ".join(html_lib.escape(i) for i in shariah.deferred_issues) + "</i>\n"
               if shariah.deferred_issues else "")
        )

    p_pct    = allot.p_single_mc * 100
    ci_lo_p  = allot.ci_95[0] * 100
    ci_hi_p  = allot.ci_95[1] * 100
    open_str  = str(row.get("OpenDate", ""))
    close_str = str(row.get("CloseDate", "TBD"))
    open_part = f"Open: {open_str}  →  " if open_str else ""
    llm_note  = ""
    if shariah.llm_reason and shariah.llm_confidence >= 60:
        llm_note = f"• <i>{html_lib.escape(shariah.llm_reason[:160])}</i>\n"

    return (
        f"{em} <b>IPO ANALYSIS │ Score: {score:.0f}/100</b>\n"
        f"<b>{sym}</b> · <code>{sector}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Verdict:</b> {html_lib.escape(verdict)}\n"
        f"<b>Action:</b> {html_lib.escape(action)}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"\n📊 <b>MARKET DEMAND</b>\n"
        f"• Subscription: <code>{sub_text}</code>\n"
        f"• Grey Market Premium: <code>{gmp_text}</code>\n"
        f"• Issue Size: ₹{size_cr:.0f} Cr\n"
        f"\n💳 <b>DEAL STRUCTURE</b>\n"
        f"• Bid Bracket: {price_str}\n"
        f"• Lot Size: {lot:,} shares\n"
        f"• Capital Required: <b>₹{lot_cost:,.0f}</b>\n"
        f"\n🎲 <b>QUANT RISK PROFILE (50,000 Monte Carlo runs)</b>\n"
        f"• Single PAN Probability: {p_pct:.2f}%  [95% CI: {ci_lo_p:.1f}–{ci_hi_p:.1f}%]\n"
        f"• Optimal Accounts: {allot.optimal_syndicate} PAN(s)\n"
        f"• Kelly Allocation: {allot.kelly_pct:.1f}%\n"
        f"• Math. Expectation (Not Guaranteed): <b>₹{allot.ev_inr:,.0f}</b>\n"
        f"\n🕌 <b>SHARIAH COMPLIANCE</b>\n"
        f"• Status: {sh_icon} {sh_label}  (Barakah: {shariah.barakah_index:.0f}/100)\n"
        f"• Audit: {_method_badge}\n"
        f"• <i>{html_lib.escape(shariah.qabda_mandate)}</i>\n"
        + llm_note
        + (
            # Downgraded HARAM issues get their own styled block so the reason is readable
            "".join(
                f"• ⚠️ <i>{html_lib.escape(i)}</i>\n"
                if i.startswith("⚠️ Audit Downgraded") else
                f"• 🚨 <i>{html_lib.escape(i)}</i>\n"
                for i in shariah.deferred_issues
            )
            if shariah.deferred_issues else ""
        )
        + f"\n📅 <b>TIMELINE</b>\n"
        f"• {open_part}{html_lib.escape(close_str)}\n"
        f"• {days_part}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Size: ₹{size_cr:.0f} Cr  ·  Source: {source}"
    )

def send_telegram_alerts(df: pd.DataFrame, allots: dict, shariahs: dict):
    token   = os.getenv("TELEGRAM_TOKEN",   "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    console = not (token and chat_id)
    if console:
        log.warning("TELEGRAM_TOKEN/CHAT_ID not set — printing to console.")

    open_df = df[
        (~df["IsUpcoming"]) &
        (df["DaysToClose"] >= 0) &
        (df["PriceBandUpper"] > 0)
    ].sort_values("FinalScore", ascending=False)

    log.info(f"📨 Telegram: {len(open_df)} OPEN IPOs → sending individual cards")

    if open_df.empty:
        msg = (f"⚔️ <b>{VERSION}</b>  [{TODAY.strftime('%d %b %Y')}]\n\n"
               f"No open IPOs found at this time.\nCheck back tomorrow.")
        if console:
            print(f"\n{'='*55}\n[NO OPEN IPOs]\n{msg}")
        else:
            _tg_send(msg, token, chat_id)
        return

    for _, row in open_df.iterrows():
        sym = str(row["Symbol"])
        a   = allots.get(sym, AllotmentProfile(
            symbol=sym, p_single_mc=0.0, syndicate_matrix={1: 0.0},
            optimal_syndicate=1, kelly_pct=0.0, ev_inr=0.0, roi_pct=0.0, ci_95=(0.0, 0.0)
        ))
        sh  = shariahs.get(sym, ShariahVerdict(
            sym, "TIER_2_CONDITIONAL", 70.0, False, "Standard QABDA mandate applies.", []
        ))
        card = build_ipo_card(row, a, sh)
        if console:
            print(f"\n{'─'*55}\n[TELEGRAM CARD]\n{card}\n")
        else:
            _tg_send(card, token, chat_id)
            time.sleep(2.5)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def run(backtest: bool = False):
    log.info(f"🚀  {VERSION}  [{TODAY}]")
    llm_tracker.reset()   # clear any state from previous runs in same process
    init_db()

    df = fetch_unified_calendar()
    if df.empty:
        log.error("❌ No IPO data — aborting.")
        return None

    _detect_and_capture_outcomes(df)

    df["IsUpcoming"] = df["IsUpcoming"].fillna(False).astype(bool)
    live_count = int((~df["IsUpcoming"]).sum())
    log.info(f"📦 Scoring {len(df)} IPOs  ({live_count} live, {len(df)-live_count} upcoming)")

    w = bayesian_weight_update(df)

    if TODAY.day == 1:
        log.info("📅 1st of month — running AI Strategy Advisor...")
        w = run_monthly_strategy_advisor(w, days_lookback=30)

    allots:   Dict[str, AllotmentProfile] = {}
    shariahs: Dict[str, ShariahVerdict]   = {}
    scores:   List[dict]                  = []

    for _, row in df.iterrows():
        sym           = str(row["Symbol"])
        allots[sym]   = compute_allotment(row)
        shariahs[sym] = run_shariah(row)
        scores.append(master_score(row, allots[sym], shariahs[sym], w, df_context=df))

    df["FinalScore"]        = [s["FinalScore"] for s in scores]
    df["Verdict"]           = [s["Verdict"]    for s in scores]
    df["p_single_mc"]       = [allots[s].p_single_mc       for s in df["Symbol"]]
    df["optimal_syndicate"] = [allots[s].optimal_syndicate  for s in df["Symbol"]]
    df["kelly_pct"]         = [allots[s].kelly_pct          for s in df["Symbol"]]
    df["ev_inr"]            = [allots[s].ev_inr             for s in df["Symbol"]]
    df["roi_pct"]           = [allots[s].roi_pct            for s in df["Symbol"]]
    df["barakah"]           = [shariahs[s].barakah_index    for s in df["Symbol"]]
    df["halal_tier"]        = [shariahs[s].tier             for s in df["Symbol"]]
    df["najash_alert"]      = [shariahs[s].najash_alert     for s in df["Symbol"]]
    df["llm_confidence"]    = [shariahs[s].llm_confidence   for s in df["Symbol"]]
    df["llm_method"]        = [shariahs[s].llm_method       for s in df["Symbol"]]

    haram_count   = (df["halal_tier"] == "HARAM_CORE_BUSINESS").sum()
    llm_count     = df["llm_method"].str.startswith("llm-").sum()
    cache_count   = (df["llm_method"] == "cache").sum()
    pending_count = (df["llm_method"] == "pending").sum()
    rule_count    = df["llm_method"].str.startswith("rule").sum()
    pre_count     = df["llm_method"].str.startswith("prefilter").sum()
    log.info(
        f"🕌 Shariah: {haram_count} HARAM  |  "
        f"LLM={llm_count}  Pre‑filter={pre_count}  Rule={rule_count}  "
        f"Cache={cache_count}  Pending={pending_count}"
    )

    persist_db(df, allots, shariahs)
    JSON_EXPORT.parent.mkdir(parents=True, exist_ok=True)
    df.to_json(str(JSON_EXPORT), orient="records", indent=2)
    log.info(f"📄 JSON → {JSON_EXPORT}")

    ranked = df.sort_values(["IsUpcoming", "FinalScore"], ascending=[True, False])
    W = 110
    print(f"\n{'═'*W}")
    print(f"  {VERSION}  |  {TODAY}")
    print(f"{'═'*W}")
    print(f"  {'Symbol':<32} {'Score':>5}  {'Verdict':<14}  "
          f"{'Sub':>6}  {'GMP':>6}  {'Days':>4}  {'Synd':>4}  "
          f"{'Status':<10}  {'Source':<22}")
    print(f"  {'─'*32} {'─'*5}  {'─'*14}  {'─'*6}  {'─'*6}  "
          f"{'─'*4}  {'─'*4}  {'─'*10}  {'─'*22}")
    for _, row in ranked.iterrows():
        sym    = str(row["Symbol"])
        a      = allots[sym]
        status = "UPCOMING" if row.get("IsUpcoming") else "LIVE"
        fb     = " *" if row.get("_date_fallback") else "  "
        print(
            f"  {sym:<32} {row['FinalScore']:>5.1f}  {row['Verdict']:<14}  "
            f"{row['SubscriptionTimes']:>5.1f}×  {row['gmp_pct']:>5.1f}%  "
            f"{row['DaysToClose']:>4}  {a.optimal_syndicate:>4}  "
            f"{status:<10}  {str(row.get('Source',''))[:22]}{fb}"
        )
    print(f"{'═'*W}")
    print(f"  * = date-fallback flag\n")

    send_telegram_alerts(df, allots, shariahs)

    if backtest:
        run_backtest()

    # ── FIX 1: dump LLM tracker summary at end of every run ──────────────────
    llm_tracker.dump_summary()
    llm_tracker.reset()   # clear for next run (important if run() is called in a loop/scheduler)

    log.info("🏁 Complete.")
    return df


if __name__ == "__main__":
    import sys
    run_backtest_flag = "--backtest" in sys.argv
    run(backtest=run_backtest_flag)
