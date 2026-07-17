"""
FORTRESS_UNIFIED — core/shariah.py
══════════════════════════════════════════════════════════════════════════════
ONE Shariah compliance engine, used by Sniper and Incubator alike.

BUG FIX: the old Incubator's dynamic_shariah_audit() failed OPEN on an LLM
parse error — "Passed fallback (AI parse error)" returned True. The old
Sniper's halal checks failed CLOSED — HALAL_LIST sheet down meant reject
everything. Two different philosophies guarding the same compliance gate
is a bug, not a design choice. This module fails CLOSED (reject) in every
degraded case:
    - HALAL_LIST sheet unavailable      -> reject
    - OpenAI unavailable                -> reject (was: pass in incubator)
    - LLM response fails to parse       -> reject (was: pass in incubator)
    - LLM call times out / raises       -> reject
The only way a symbol passes is an explicit, successfully-parsed compliant
verdict, or a hit on the sheet's clean-sector list.
"""
from __future__ import annotations
import json
import logging
import re
import time
from typing import Tuple

from . import config
from .sheets_client import read_sheet
from .llm_client import call_openai

log = logging.getLogger("fortress.shariah")

_HALAL_LIST_CACHE = None
_HALAL_CACHE_TS = 0.0
_HALAL_CACHE_TTL = 1800


def _get_halal_list() -> list:
    global _HALAL_LIST_CACHE, _HALAL_CACHE_TS
    now = time.time()
    if _HALAL_LIST_CACHE is not None and (now - _HALAL_CACHE_TS) < _HALAL_CACHE_TTL:
        return _HALAL_LIST_CACHE
    rows = read_sheet("HALAL_LIST")
    _HALAL_LIST_CACHE = rows or []
    _HALAL_CACHE_TS = now
    return _HALAL_LIST_CACHE


def ticker_veto(symbol: str) -> Tuple[bool, str]:
    """Layer 1: instant, free, ticker-keyword hard veto. (vetoed, reason)"""
    sym = symbol.upper()
    for kw in config.HARAM_TICKER_KEYWORDS:
        if kw in sym:
            return True, f"Haram ticker keyword '{kw}'"
    return False, ""


def sheet_check(symbol: str) -> Tuple[bool, str]:
    """
    Layer 2: live check against HALAL_LIST sheet.
    Returns (compliant, reason). FAIL-SAFE: sheet unavailable -> not compliant.
    """
    sym = symbol.upper()
    raw = _get_halal_list()
    if not raw or len(raw) < 2:
        return False, "HALAL_LIST unavailable — fail-safe reject"
    for row in raw[1:]:
        if not row or str(row[0]).strip().upper() != sym:
            continue
        sector = str(row[2]).strip().upper() if len(row) > 2 else ""
        industry = str(row[3]).strip().upper() if len(row) > 3 else ""
        if any(h in sector or h in industry for h in config.HARAM_SECTOR_TERMS):
            return False, f"Sector/industry flagged: {sector} | {industry}"
        return True, "Found in HALAL_LIST, sector clean"
    return False, "Not in HALAL_LIST — fail-safe reject"


def llm_business_audit(symbol: str, company_name: str, industry: str,
                        biz_profile: str) -> Tuple[bool, str]:
    """
    Layer 3: LLM audits a GROUNDED business profile (never a blind ticker
    guess — the profile must come from real data upstream).
    FAIL-SAFE: any failure to get a parseable, explicit "compliant: true"
    verdict results in rejection. This is the direct fix for the old
    incubator bug where a parse error passed the stock through.
    """
    if not config.OPENAI_API_KEY:
        return False, "OpenAI unavailable — fail-safe reject"

    prompt = f"""You are an Islamic finance compliance auditor verifying a stock for an investment fund.
Company: {company_name} (Ticker: {symbol}, NSE India)
Industry: {industry}
Business Profile: {biz_profile}

Task: Determine if this company's PRIMARY business model is itself haram.

Prohibited: Conventional Banking, Insurance, NBFCs, Financial Lending, Brokerage/Securities,
Alcohol production/distribution, Tobacco, Gambling, Pork, Adult entertainment, Defense/Weapons.

STRICT RULES:
1. Judge ONLY the company's own primary business — not their customers.
2. Do NOT speculate. Only reject for EXPLICITLY prohibited activity.
3. Manufacturing, IT, pharma, FMCG, solar, construction materials, logistics, transport,
   textiles, pipes, footwear, chemicals = HALAL unless they make prohibited goods.
4. Hotels: only reject if explicitly operating bars/casinos as core revenue.
5. BPO/services: reject ONLY if the company itself provides financial lending/banking services.

Respond ONLY in this JSON format (no markdown):
{{
  "is_compliant": true,
  "primary_business": "one sentence",
  "reason": "if non-compliant, cite the EXPLICIT haram activity. If compliant write NONE"
}}"""

    raw = call_openai(prompt, max_tokens=180)
    if not raw:
        return False, "LLM call failed — fail-safe reject"
    try:
        parsed = json.loads(re.sub(r"```json|```", "", raw).strip())
        compliant = bool(parsed.get("is_compliant", False))
        reason = str(parsed.get("reason", "NONE"))
        biz = str(parsed.get("primary_business", "unknown"))
        if not compliant:
            return False, f"AI audit: {reason} ({biz})"
        return True, f"AI audit passed: {biz}"
    except Exception as e:
        # THIS is the exact branch that used to fail OPEN in the old
        # incubator. Now it fails closed, matching sniper's philosophy.
        log.warning(f"Shariah LLM parse error for {symbol}: {e} — fail-safe reject")
        return False, "LLM parse error — fail-safe reject"


def full_audit(symbol: str, company_name: str = "", industry: str = "",
               biz_profile: str = "") -> dict:
    """
    Full 3-layer audit used by both entrypoints. Returns a dict (not just
    a bool) so callers can log/store the reasoning for the training archive.
    """
    result = {"symbol": symbol.upper(), "compliant": False, "layer": "L1", "reason": ""}

    vetoed, reason = ticker_veto(symbol)
    if vetoed:
        result.update(layer="L1", reason=reason)
        return result

    sheet_ok, sheet_reason = sheet_check(symbol)
    if sheet_ok:
        result.update(compliant=True, layer="L2", reason=sheet_reason)
        return result

    # Sheet didn't confirm — try grounded LLM audit if we have a profile.
    if biz_profile or industry:
        llm_ok, llm_reason = llm_business_audit(symbol, company_name or symbol,
                                                  industry or "Unknown",
                                                  biz_profile or "Not available")
        result.update(compliant=llm_ok, layer="L3", reason=llm_reason)
        return result

    # No sheet hit and no profile to ground an LLM check — fail-safe reject.
    result.update(compliant=False, layer="L2", reason=sheet_reason)
    return result
