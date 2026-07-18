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


def debt_ratio_screen(symbol: str, ratios: dict) -> Tuple[bool, str]:
    """
    Layer 4: quantitative AAOIFI-style debt screen. This is the check your
    mentor's manual review caught missing — MTNL passed the old L1-L3
    checks (no haram keyword, no haram sector) despite ~₹31,944 Cr of debt
    and NPA-classified loans, because nothing in L1-L3 looks at a balance
    sheet at all.

    This is a SEPARATE compliance leg from business-model screening:
    interest-bearing debt above the threshold is itself considered
    non-compliant under standard Islamic finance screens (AAOIFI ~33% of
    assets), independent of what the company actually makes or sells.

    ratios must come from fundamentals.debt_and_quality_ratios(). Missing
    data (None) is NOT treated as a pass — it's treated as "screen
    inconclusive", and the caller (full_audit) decides whether an
    inconclusive debt screen should block a pick. Given your mentor's
    finding, the default policy is fail-safe: no debt data -> reject,
    matching the fail-closed philosophy used everywhere else in this file.
    """
    if not config.SHARIAH_DEBT_SCREEN_ENABLED:
        return True, "debt screen disabled"

    dta = ratios.get("debt_to_assets")
    dte = ratios.get("debt_to_equity")

    if dta is None and dte is None:
        return False, "no debt data available — fail-safe reject (debt screen inconclusive)"

    if dta is not None and dta > config.SHARIAH_MAX_DEBT_TO_ASSETS:
        return False, (f"Debt/Assets {dta:.0%} > {config.SHARIAH_MAX_DEBT_TO_ASSETS:.0%} "
                       f"AAOIFI threshold")
    if dte is not None and dte > config.SHARIAH_MAX_DEBT_TO_EQUITY:
        return False, (f"Debt/Equity {dte:.2f} > {config.SHARIAH_MAX_DEBT_TO_EQUITY:.2f} threshold")

    parts = []
    if dta is not None:
        parts.append(f"D/A={dta:.0%}")
    if dte is not None:
        parts.append(f"D/E={dte:.2f}")
    return True, f"Debt screen OK ({', '.join(parts)})"


def full_audit(symbol: str, company_name: str = "", industry: str = "",
               biz_profile: str = "", debt_ratios: dict = None) -> dict:
    """
    Full 4-layer audit used by both entrypoints. Returns a dict (not just
    a bool) so callers can log/store the reasoning for the training archive.

    debt_ratios: pass fundamentals.debt_and_quality_ratios(symbol) here to
    enable Layer 4. If omitted, Layer 4 is skipped entirely (backward
    compatible for callers that haven't fetched fundamentals yet) — this
    is different from "debt data unavailable", which fails closed. Skipping
    the layer is a caller choice; having the layer and finding no data is
    a fail-safe reject. Callers scoring real candidates for the watchlist
    should always pass debt_ratios.
    """
    result = {"symbol": symbol.upper(), "compliant": False, "layer": "L1", "reason": ""}

    vetoed, reason = ticker_veto(symbol)
    if vetoed:
        result.update(layer="L1", reason=reason)
        return result

    business_ok = False
    sheet_ok, sheet_reason = sheet_check(symbol)
    if sheet_ok:
        business_ok = True
        result.update(compliant=True, layer="L2", reason=sheet_reason)
    elif biz_profile or industry:
        llm_ok, llm_reason = llm_business_audit(symbol, company_name or symbol,
                                                  industry or "Unknown",
                                                  biz_profile or "Not available")
        business_ok = llm_ok
        result.update(compliant=llm_ok, layer="L3", reason=llm_reason)
    else:
        result.update(compliant=False, layer="L2", reason=sheet_reason)

    if not business_ok:
        return result

    # ── Layer 4: quantitative debt screen (only runs if ratios provided) ──
    if debt_ratios is not None:
        debt_ok, debt_reason = debt_ratio_screen(symbol, debt_ratios)
        if not debt_ok:
            result.update(compliant=False, layer="L4", reason=debt_reason)
            return result
        result["reason"] = f"{result['reason']} | {debt_reason}"

    return result
