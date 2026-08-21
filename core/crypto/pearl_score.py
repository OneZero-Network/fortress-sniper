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


def raw_liquidity_metric(coin_snapshot: Optional[dict]) -> Optional[float]:
    """The RAW turnover ratio (volume/market cap), before any squashing
    to 0-100. v3.4 exposes this separately so callers can rank it
    WITHIN A TIER (percentile) instead of against a fixed global
    formula — the global formula was found to saturate near 100 for
    almost any reasonably-liquid Large/Mid-cap coin, failing to
    discriminate 'ordinary for this tier' from 'unusual for this tier.'"""
    if not coin_snapshot:
        return None
    vol = coin_snapshot.get("volume_24h")
    mcap = coin_snapshot.get("market_cap")
    if not vol or not mcap or mcap <= 0:
        return None
    return vol / mcap


def raw_structure_metric(coin_snapshot: Optional[dict]) -> Optional[float]:
    """The RAW blended 7d/30d momentum, before squashing. Same
    tier-relative rationale as raw_liquidity_metric."""
    if not coin_snapshot:
        return None
    p7 = coin_snapshot.get("pct_7d")
    p30 = coin_snapshot.get("pct_30d")
    if p7 is None and p30 is None:
        return None
    return 0.6 * (p7 or 0.0) + 0.4 * (p30 or 0.0)


def percentile_rank(value: Optional[float], peer_values: list) -> Optional[float]:
    """Generic 0-100 percentile of value within peer_values (inclusive
    of itself). Requires at least 5 peers to produce a meaningful rank —
    below that, returns None rather than a rank among 2-3 coins that
    isn't statistically meaningful."""
    if value is None:
        return None
    valid_peers = [v for v in peer_values if v is not None]
    if len(valid_peers) < 5:
        return None
    rank = sum(1 for v in valid_peers if v < value)
    return round(100.0 * rank / len(valid_peers), 1)


def _liquidity_component(coin_snapshot: Optional[dict]) -> Optional[float]:
    """FALLBACK ONLY — used when no tier-peer context is available (e.g.
    watchlist pearls scored outside the tier funnel). The PREFERRED path
    is tier-relative percentile scoring — see raw_liquidity_metric() +
    percentile_rank(), wired in by the caller via
    compute_pearl_score()'s liquidity_score_override parameter."""
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
    """FALLBACK ONLY — see _liquidity_component's docstring, same
    rationale applies here."""
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


MIN_COMPONENTS_FOR_TIERING = 2  # need at least 2/5 components to enter tiering; below this = "insufficient evidence"


def classify_tier(discovery_score: Optional[float], components_available: list,
                   false_pearl_risk_pct: int) -> dict:
    """v2.9 — 4-tier classification, per explicit instruction: this does
    NOT change the underlying discovery_score math, only how results get
    bucketed and reported. The old binary INVESTIGATE/WATCH/AVOID status
    stays available for backward compatibility; this adds the richer
    diagnostic categories on top.

    Returns {"tier": str, "reject_reason": str|None} where tier is one
    of: PEARL, CANDIDATE, WATCH, FALSE_PEARL, or None (not surfaced —
    reject_reason explains why: MISSING_DATA or INSUFFICIENT_EVIDENCE)."""
    n_available = len(components_available)
    evidence_completeness_pct = round(100.0 * n_available / 5, 1)

    if false_pearl_risk_pct >= 70:
        return {"tier": "FALSE_PEARL", "reject_reason": None,
                "evidence_completeness_pct": evidence_completeness_pct}

    if n_available == 0:
        return {"tier": None, "reject_reason": "MISSING_DATA",
                "evidence_completeness_pct": evidence_completeness_pct}

    if n_available < MIN_COMPONENTS_FOR_TIERING:
        return {"tier": None, "reject_reason": "INSUFFICIENT_EVIDENCE",
                "evidence_completeness_pct": evidence_completeness_pct}

    if discovery_score is None:
        return {"tier": None, "reject_reason": "MISSING_DATA",
                "evidence_completeness_pct": evidence_completeness_pct}

    if discovery_score >= 80 and evidence_completeness_pct >= 60:
        tier = "PEARL"
    elif discovery_score >= 80:
        # HIGH-POTENTIAL: the score genuinely clears the Pearl bar, but
        # not enough of the evidence universe was available to call it a
        # Pearl outright. This is NOT a lowered threshold — the 80-point
        # bar is unchanged. It's a separate, explicit category for "would
        # be a Pearl if we had more data," so a strong candidate isn't
        # silently demoted to the same bucket as a merely-decent one.
        tier = "HIGH_POTENTIAL"
    elif discovery_score >= 60:
        tier = "CANDIDATE"
    elif discovery_score >= 45:
        tier = "WATCH"
    else:
        return {"tier": None, "reject_reason": "INSUFFICIENT_EVIDENCE",
                "evidence_completeness_pct": evidence_completeness_pct}

    return {"tier": tier, "reject_reason": None, "evidence_completeness_pct": evidence_completeness_pct}


def compute_false_pearl_risk_pct(risk: dict) -> int:
    severity = risk.get("severity", "UNCHECKED") if risk else "UNCHECKED"
    return _FALSE_PEARL_RISK_PCT.get(severity, 50)


def compute_pearl_priority_score(discovery_score: Optional[float], emergence_score: Optional[float],
                                  trend_change: dict, breakout: dict, ecosystem_trend: dict) -> Optional[float]:
    """v3.7 — Pearl Priority Score. RANKING-ONLY, not a scoring-authority
    replacement: discovery_score remains the sole basis for PEARL/
    HIGH_POTENTIAL/CANDIDATE/WATCH tier classification (see
    classify_tier() above) — that boundary is deliberate, per
    evidence.py's no-shortcuts rule. This score exists ONLY to answer
    'given everything shortlisted today, which 5 are worth looking at
    FIRST' — a display/ordering concept, never a gate.

    Weighting: discovery_score (50%) + emergence_score (30%) dominate,
    with small bonuses/penalties (up to +/-10 combined) for trend
    reversal, breakout, and sector outperformance — informational
    tie-breakers, not primary drivers."""
    if discovery_score is None:
        return None

    base = discovery_score * 0.5 + (emergence_score or 50.0) * 0.3
    # emergence defaults to neutral 50 in the blend (not excluded) since
    # this is a RANKING score where every candidate needs a comparable
    # number — unlike discovery_score, which correctly excludes missing
    # components from its own weighted average
    remaining_weight = 20.0
    bonus = 0.0

    if trend_change.get("label") == "REVERSAL_BULLISH":
        bonus += 6
    elif trend_change.get("label") == "REVERSAL_BEARISH":
        bonus -= 6

    if breakout.get("label") == "BREAKOUT":
        bonus += 6

    if ecosystem_trend.get("label") == "ABOVE_SECTOR":
        bonus += 5
    elif ecosystem_trend.get("label") == "BELOW_SECTOR":
        bonus -= 5

    final = base + min(remaining_weight, max(-remaining_weight, bonus))
    return round(max(0.0, min(100.0, final)), 1)


def compute_emergence_score(velocity: Optional[dict], relative_anomaly: Optional[dict]) -> Optional[float]:
    """v3.6 — Emergence score. Separate from discovery_score on purpose:
    measures RATE OF CHANGE and how unusual that change is relative to
    peers, not 'is this a good asset overall.' A coin can have a modest
    discovery_score but a very high Emergence score (something is
    rapidly changing, worth watching even if the broader picture isn't
    complete yet) — or the reverse (a solid, stable discovery_score with
    low Emergence, nothing acutely happening right now).

    Zero extra API calls — built entirely from velocity (v3.0) and
    relative_anomaly (v3.3) data already computed for the same
    candidate. Returns None if neither input is available, rather than
    a fabricated middle value."""
    parts = []
    weights = []

    if velocity:
        vol_ratio = velocity.get("volume_ratio")
        if vol_ratio is not None:
            # 1x (normal) -> 0, 5x+ -> 100, squashed
            vol_score = max(0.0, min(100.0, (vol_ratio - 1.0) * 25.0))
            parts.append(vol_score)
            weights.append(0.4)
        accel = velocity.get("price_acceleration_pct")
        if accel is not None:
            # abs(accel) since deceleration is ALSO an emergence signal
            # (something changing direction sharply), not just accel-up
            accel_score = max(0.0, min(100.0, abs(accel) * 2.5))
            parts.append(accel_score)
            weights.append(0.3)

    if relative_anomaly and relative_anomaly.get("available"):
        vol_pct = relative_anomaly.get("volume_percentile")
        if vol_pct is not None:
            parts.append(vol_pct)
            weights.append(0.3)

    if not parts:
        return None
    total_w = sum(weights)
    return round(sum(p * w for p, w in zip(parts, weights)) / total_w, 1)


def compute_pearl_score(symbol: str, coin_snapshot: Optional[dict], whale_accum: Optional[dict],
                         news: Optional[dict], risk: dict, onchain_quality: Optional[float],
                         liquidity_score_override: Optional[float] = None,
                         structure_score_override: Optional[float] = None) -> dict:
    """Returns the full Pearl candidate record: discovery_score, per-
    component breakdown, false_pearl_risk_pct, status, reasons_why,
    invalidation_conditions. Components with no data are EXCLUDED from
    the weighted average (not defaulted), and reported as 'n/a' rather
    than silently treated as neutral.

    v3.4: liquidity_score_override/structure_score_override let the
    caller supply TIER-RELATIVE PERCENTILE scores (computed across the
    candidate's own universe_tier peers, using raw_liquidity_metric() +
    percentile_rank()) instead of the old global absolute formula. This
    is the preferred path — the absolute formula was found to saturate
    near 100 for almost any reasonably-liquid Large/Mid-cap coin,
    failing to discriminate ordinary from unusual. When no override is
    given (no tier-peer context available, e.g. a watchlist pearl scored
    outside the funnel), falls back to the old absolute formula."""
    components = {
        "whale": _whale_component(whale_accum),
        "news": _news_component(news),
        "liquidity": liquidity_score_override if liquidity_score_override is not None else _liquidity_component(coin_snapshot),
        "structure": structure_score_override if structure_score_override is not None else _structure_component(coin_snapshot),
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
    tier_result = classify_tier(discovery_score, list(available.keys()), false_pearl_risk_pct)

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
        "evidence_completeness_pct": tier_result["evidence_completeness_pct"],
        "tier": tier_result["tier"], "reject_reason": tier_result["reject_reason"],
        "false_pearl_risk_pct": false_pearl_risk_pct, "status": status,
        "reasons_why": reasons, "invalidation_conditions": invalidators,
    }
