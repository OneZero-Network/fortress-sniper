"""
FORTRESS_CRYPTO — core/crypto/pearl_score.py
══════════════════════════════════════════════════════════════════════════════
The Pearl Detection Machine's scoring engine. Per explicit product
redefinition: Fortress does not predict the market. It finds unusual
combinations of positive signals, filters out obvious traps, explains
why a candidate surfaced, and states what would invalidate the thesis.

WHAT THIS DELIBERATELY EXCLUDES: the technical core (RSI/ADX/volume
trigger) and regime v1 are REJECTED (see core/crypto/evidence.py) and
NEVER contribute to this score — not at low weight, not as a tiebreaker,
not anywhere. Including a rejected signal "just a little" is how
rejected hypotheses quietly sneak back into production.

FIVE COMPONENTS, each 0-100, each excluded from the composite (not
defaulted to neutral) when data is unavailable:
  1. WHALE      — accumulation/distribution signal (core/crypto/onchain.py)
  2. NEWS       — sentiment + forward-catalyst language (news_sentiment.py)
  3. LIQUIDITY  — 24h volume relative to market cap (health, not prediction)
  4. STRUCTURE  — price momentum (7d/30d), framed DESCRIPTIVELY
                  ("something is moving") not predictively
  5. ON-CHAIN   — holder concentration health (onchain_quality_score)

FALSE-PEARL RISK is computed separately and can VETO a high discovery
score entirely — a Pearl candidate with HIGH_RISK contract flags is
never surfaced as investigate-worthy, regardless of how good the other
five components look.

STATUS OUTPUT: only ever "PEARL CANDIDATE — INVESTIGATE", "WATCH", or
"AVOID (false-pearl risk)". Never "BUY". This is enforced structurally
(the function has no code path that returns anything else), not just by
convention.
"""
from __future__ import annotations
from typing import Optional

from . import config as ccfg


_FALSE_PEARL_RISK_PCT = {"CLEAN": 8, "CAUTION": 40, "HIGH_RISK": 88, "UNCHECKED": 50}


def _whale_component(whale_accum: Optional[dict]) -> Optional[float]:
    if not whale_accum or not whale_accum.get("available"):
        return None
    label = whale_accum.get("label")
    if label == "ACCUMULATING":
        # scale with magnitude of the delta, capped
        delta = abs(whale_accum.get("top10_delta_pct", 0) or 0)
        return round(min(100.0, 60.0 + delta * 3), 1)
    if label == "DISTRIBUTING":
        return 15.0
    return 50.0  # STABLE


def _news_component(news: Optional[dict]) -> Optional[float]:
    if not news or not news.get("available"):
        return None
    label = news.get("label")
    base = {"BULLISH": 75.0, "MIXED": 50.0, "NEUTRAL": 50.0, "BEARISH": 15.0, "SILENT": 40.0}.get(label, 40.0)
    if news.get("forward_catalyst"):
        base = min(100.0, base + 15.0)
    return round(base, 1)


def _liquidity_component(coin_snapshot: Optional[dict]) -> Optional[float]:
    if not coin_snapshot:
        return None
    vol = coin_snapshot.get("volume_24h")
    mcap = coin_snapshot.get("market_cap")
    if not vol or not mcap or mcap <= 0:
        return None
    ratio = vol / mcap  # daily turnover — higher generally = healthier liquidity
    # 2% turnover -> ~50, 10%+ -> ~100, <0.5% -> low
    score = 25.0 + ratio * 100.0 * 7.5
    return round(max(0.0, min(100.0, score)), 1)


def _structure_component(coin_snapshot: Optional[dict]) -> Optional[float]:
    """DESCRIPTIVE momentum read — 'is price structure improving,' not a
    predictive claim. Deliberately simple (unlike the rejected technical
    trigger's RSI/ADX combination)."""
    if not coin_snapshot:
        return None
    p7 = coin_snapshot.get("pct_7d")
    p30 = coin_snapshot.get("pct_30d")
    if p7 is None and p30 is None:
        return None
    p7 = p7 or 0.0
    p30 = p30 or 0.0
    blended = 0.6 * p7 + 0.4 * p30
    return round(max(0.0, min(100.0, 50.0 + blended * 1.2)), 1)


def _onchain_component(onchain_quality: Optional[float]) -> Optional[float]:
    return onchain_quality  # already 0-100 from onchain.onchain_quality_score_0_100


def compute_false_pearl_risk_pct(risk: dict) -> int:
    severity = risk.get("severity", "UNCHECKED") if risk else "UNCHECKED"
    return _FALSE_PEARL_RISK_PCT.get(severity, 50)


def compute_pearl_score(symbol: str, coin_snapshot: Optional[dict], whale_accum: Optional[dict],
                         news: Optional[dict], risk: dict, onchain_quality: Optional[float]) -> dict:
    """Returns the full Pearl candidate record: discovery_score, per-
    component breakdown, false_pearl_risk_pct, status, reasons_why,
    invalidation_conditions. Components with no data are EXCLUDED from
    the weighted average (not defaulted), and reported as 'n/a' rather
    than silently treated as neutral."""
    components = {
        "whale": _whale_component(whale_accum),
        "news": _news_component(news),
        "liquidity": _liquidity_component(coin_snapshot),
        "structure": _structure_component(coin_snapshot),
        "onchain": _onchain_component(onchain_quality),
    }
    weights = {"whale": 0.25, "news": 0.20, "liquidity": 0.15, "structure": 0.20, "onchain": 0.20}

    available = {k: v for k, v in components.items() if v is not None}
    if available:
        total_w = sum(weights[k] for k in available)
        discovery_score = round(sum(components[k] * weights[k] for k in available) / total_w, 1)
    else:
        discovery_score = None

    false_pearl_risk_pct = compute_false_pearl_risk_pct(risk)

    # ── STATUS — structurally cannot return BUY; only these three ──────
    if false_pearl_risk_pct >= 70:
        status = "🚫 AVOID (false-pearl risk)"
    elif discovery_score is not None and discovery_score >= 65:
        status = "🔎 PEARL CANDIDATE — INVESTIGATE"
    elif discovery_score is not None and discovery_score >= 45:
        status = "👀 WATCH"
    else:
        status = None  # not surfaced at all — too little signal to be worth showing

    # ── reasons it surfaced (only from components that actually scored well) ──
    reasons = []
    invalidators = []
    if components["whale"] and components["whale"] >= 65:
        reasons.append("unusual whale accumulation")
        invalidators.append("whale distribution (accumulation reversing)")
    if components["news"] and components["news"] >= 65:
        reasons.append("positive news sentiment" + (" with a forward catalyst" if news and news.get("forward_catalyst") else ""))
        invalidators.append("catalyst reversal or sentiment turning bearish")
    if components["liquidity"] and components["liquidity"] >= 65:
        reasons.append("healthy, expanding liquidity")
        invalidators.append("liquidity contraction")
    if components["structure"] and components["structure"] >= 65:
        reasons.append("improving price structure")
        invalidators.append("momentum reversal")
    if components["onchain"] and components["onchain"] >= 65:
        reasons.append("healthy holder distribution (low concentration)")
        invalidators.append("holder concentration increasing sharply")
    invalidators.append("broad market-wide risk-off (see regime context, observational only)")

    return {
        "symbol": symbol, "discovery_score": discovery_score, "components": components,
        "components_available": list(available.keys()),
        "false_pearl_risk_pct": false_pearl_risk_pct, "status": status,
        "reasons_why": reasons, "invalidation_conditions": invalidators,
    }
