"""
FORTRESS_UNIFIED — core/macro_commentary.py
══════════════════════════════════════════════════════════════════════════════
Explicitly NOT a prediction engine. Your friends' notes described "predict
sector rotation from tariffs/dollar index/war" — an LLM cannot reliably
predict market moves from headlines, and treating its guess as a trading
signal is how systems quietly take on unverified, unbacktested risk.

What this module actually does: asks an LLM to produce a labeled OPINION
("sector X may see tailwind/headwind given Y, confidence: low/med/high")
and applies a SMALL, HARD-CAPPED nudge to conviction_score — logged in a
dedicated column so it is always distinguishable from the technical/
fundamental score, and easy to strip out entirely if you decide it's not
earning its keep (which requires the same outcomes-based evidence any
other factor would need before you'd trust it more).

The bonus is 0 unless the LLM states a confidence at or above
MACRO_COMMENTARY_MIN_CONFIDENCE — a hedge-y or uncertain answer earns no
adjustment at all, by design.
"""
from __future__ import annotations
import json
import logging
import re
import time
from datetime import datetime
from typing import Dict, Optional

from . import config
from .llm_client import call_openai

log = logging.getLogger("fortress.macro_commentary")

_CACHE: Optional[Dict] = None
_CACHE_TS = 0.0
_CACHE_TTL = 6 * 3600  # refresh a few times a day at most — this is context, not a tick-by-tick signal


SECTOR_MAP = {
    "IT": ["INFY", "TCS", "WIPRO", "HCLTECH", "TECHM"],
    "PHARMA": ["SUNPHARMA", "DRREDDY", "CIPLA", "LUPIN"],
    "METAL": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL"],
    "ENERGY": ["ONGC", "RELIANCE", "IOC", "BPCL"],
    "BANKING": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK"],
    "AUTO": ["MARUTI", "TATAMOTORS", "M&M", "BAJAJ-AUTO"],
}


def _fetch_commentary() -> Dict:
    """One LLM call per cache window, not per-symbol — this is a market-wide
    opinion, not a per-stock one. Returns {sector: {bias, confidence, note}}."""
    global _CACHE, _CACHE_TS
    now = time.time()
    if _CACHE is not None and (now - _CACHE_TS) < _CACHE_TTL:
        return _CACHE

    if not config.MACRO_COMMENTARY_ENABLED or not config.OPENAI_API_KEY:
        _CACHE, _CACHE_TS = {}, now
        return {}

    today = datetime.today().strftime("%Y-%m-%d")
    prompt = f"""You are a macro strategist giving a SECTOR-LEVEL OPINION for Indian equity
markets on {today}. This is explicitly a qualitative judgment call, not a
prediction — you must be honest about low confidence when the picture is unclear.

Consider prevailing macro conditions you're aware of (global trade/tariff
posture, USD strength/DXY trend, geopolitical tension, crude oil, rate
expectations) as of your knowledge — you do not have live news access, so
reason from structural relationships (e.g. "a stronger dollar typically
pressures IT-services margins less than import-heavy sectors" or "elevated
crude typically pressures OMCs and aviation, helps upstream energy").

For each of these sectors — IT, PHARMA, METAL, ENERGY, BANKING, AUTO — give:
  - bias: "tailwind", "headwind", or "neutral"
  - confidence: "low", "medium", or "high" (be honest — most days should be
    low/medium; reserve "high" for structurally clear relationships only)
  - note: one short sentence reasoning

Respond ONLY as JSON (no markdown):
{{"IT": {{"bias": "...", "confidence": "...", "note": "..."}},
  "PHARMA": {{...}}, "METAL": {{...}}, "ENERGY": {{...}},
  "BANKING": {{...}}, "AUTO": {{...}}}}"""

    raw = call_openai(prompt, max_tokens=500, prompt_type="macro_commentary")
    if not raw:
        log.info("Macro commentary: LLM call failed — no bonus applied this cycle")
        _CACHE, _CACHE_TS = {}, now
        return {}
    try:
        parsed = json.loads(re.sub(r"```json|```", "", raw).strip())
        _CACHE, _CACHE_TS = parsed, now
        log.info(f"Macro commentary refreshed: {parsed}")
        return parsed
    except Exception as e:
        log.warning(f"Macro commentary parse error: {e} — no bonus applied this cycle")
        _CACHE, _CACHE_TS = {}, now
        return {}


def _sector_for_symbol(symbol: str) -> Optional[str]:
    sym = symbol.upper()
    for sector, syms in SECTOR_MAP.items():
        if sym in syms:
            return sector
    return None


def macro_commentary_bonus(symbol: str, sector_hint: str = "") -> Dict:
    """
    Returns {bonus: float, sector: str, bias: str, confidence: str, note: str}.
    bonus is ALWAYS in [-MACRO_COMMENTARY_MAX_BONUS, +MACRO_COMMENTARY_MAX_BONUS],
    and is 0.0 whenever: the feature is disabled, the LLM call failed, the
    sector can't be identified, or confidence is below the configured floor.
    This is deliberately conservative — see module docstring.
    """
    out = {"bonus": 0.0, "sector": "", "bias": "neutral", "confidence": "n/a", "note": ""}
    if not config.MACRO_COMMENTARY_ENABLED:
        return out

    sector = _sector_for_symbol(symbol) or (sector_hint.upper() if sector_hint else None)
    if not sector:
        out["note"] = "sector not mapped — no commentary applied"
        return out

    commentary = _fetch_commentary()
    entry = commentary.get(sector)
    if not entry:
        out.update(sector=sector, note=f"no commentary available for {sector}")
        return out

    conf_map = {"low": 0.3, "medium": 0.6, "high": 0.9}
    conf_val = conf_map.get(str(entry.get("confidence", "low")).lower(), 0.3)
    bias = str(entry.get("bias", "neutral")).lower()

    out.update(sector=sector, bias=bias, confidence=entry.get("confidence", "low"),
               note=str(entry.get("note", ""))[:150])

    if conf_val < config.MACRO_COMMENTARY_MIN_CONFIDENCE:
        out["note"] += " (below confidence floor — no bonus)"
        return out

    direction = {"tailwind": 1, "headwind": -1, "neutral": 0}.get(bias, 0)
    out["bonus"] = round(direction * conf_val * config.MACRO_COMMENTARY_MAX_BONUS, 2)
    return out
