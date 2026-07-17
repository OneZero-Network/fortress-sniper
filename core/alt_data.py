"""
FORTRESS_UNIFIED — core/alt_data.py
══════════════════════════════════════════════════════════════════════════════
Lean port of the alt-data layer (CPP tenders via ScraperAPI). Honest
scoping note: the legacy version paired ScraperAPI with OpenAI-embedding
semantic vectors. This port keeps the fetch + a keyword/company-name token
match (which caught most legacy hits anyway); the embedding upgrade slots
into match_company_to_tenders() later without changing callers. Fully
flag-gated: no SCRAPERAPI_KEY or ALT_DATA_ENABLED=false → instant empty,
zero cost. Fetched once per run, matched per survivor.
"""
from __future__ import annotations
import logging
import re
from typing import Dict, List

import requests

from . import config

log = logging.getLogger("fortress.alt_data")

_TENDER_CACHE: List[str] = []
_FETCHED = False

_GENERIC = {"LIMITED", "LTD", "INDIA", "INDUSTRIES", "COMPANY", "CORP",
            "CORPORATION", "PRIVATE", "PVT", "THE", "AND"}


def fetch_cpp_tenders(max_rows: int = 150) -> List[str]:
    """One fetch per process of recent CPPP tender titles via ScraperAPI."""
    global _TENDER_CACHE, _FETCHED
    if _FETCHED:
        return _TENDER_CACHE
    _FETCHED = True
    if not (config.ALT_DATA_ENABLED and config.SCRAPERAPI_KEY):
        return []
    try:
        resp = requests.get(
            "https://api.scraperapi.com/",
            params={"api_key": config.SCRAPERAPI_KEY,
                    "url": "https://etenders.gov.in/eprocure/app?page=FrontEndLatestActiveTenders&service=page"},
            timeout=45,
        )
        if resp.status_code == 200:
            # Tender titles sit in table cells; strip tags, keep plausible rows.
            cells = re.findall(r"<td[^>]*>(.*?)</td>", resp.text, re.S | re.I)
            titles = []
            for c in cells:
                txt = re.sub(r"<[^>]+>", " ", c)
                txt = re.sub(r"\s+", " ", txt).strip()
                if 25 <= len(txt) <= 300 and not txt.isdigit():
                    titles.append(txt.upper())
            _TENDER_CACHE = titles[:max_rows]
            log.info(f"Alt-data: {len(_TENDER_CACHE)} tender titles cached")
    except Exception as e:
        log.debug(f"fetch_cpp_tenders: {e}")
    return _TENDER_CACHE


def match_company_to_tenders(symbol: str, company_name: str) -> Dict:
    """Token match: any distinctive (≥5 char, non-generic) company-name
    token appearing in a tender title = potential catalyst."""
    out = {"tender_match": False, "tender_title": ""}
    tenders = fetch_cpp_tenders()
    if not tenders:
        return out
    tokens = {t for t in re.split(r"[^A-Z0-9]+", (company_name or symbol).upper())
              if len(t) >= 5 and t not in _GENERIC}
    if not tokens:
        return out
    for title in tenders:
        if any(tok in title for tok in tokens):
            out["tender_match"] = True
            out["tender_title"] = title[:120]
            break
    return out
