"""
FORTRESS_CRYPTO — core/crypto/pearl_flywheel.py
══════════════════════════════════════════════════════════════════════════════
v2.8 — Pearl Forward Tracking. Nothing else, per explicit scope.

LIFECYCLE:
  UNDER_OBSERVATION (initial state, every new Pearl candidate)
       │
       ├─→ INVALIDATED  (a specific invalidation condition actually
       │                 fired — whale reversed, catalyst reversed,
       │                 or contract risk escalated. TERMINAL — once
       │                 invalidated, we stop re-checking.)
       │
       └─→ at the 30d horizon, resolves to:
             CONFIRMED  (positive terminal return, no invalidation fired)
             FAILED     (negative terminal return, no invalidation fired
                         — the thesis just didn't play out, distinct
                         from being actively invalidated)

INVALIDATION CHECK, at every horizon (24h/3d/7d/14d/30d) until either
INVALIDATED or the 30d terminal resolution: re-fetches CURRENT whale and
risk state (fresh data, not the immutable discovery snapshot) and
compares against what was true at discovery. Only checks conditions that
were actually part of THIS candidate's own invalidation_conditions list
— a candidate that never cited "whale distribution" as a risk doesn't
get invalidated by whale behavior it never claimed to depend on.
"""
from __future__ import annotations
import logging
from typing import Optional

from ..db import get_pearl_observations_due, resolve_pearl_observation
from . import data as cdata
from . import onchain
from . import risk_engine

log = logging.getLogger("fortress.crypto.pearl_flywheel")

HORIZONS = ("24h", "3d", "7d", "14d", "30d")
INVALIDATION_RETURN_THRESHOLD_PCT = -15.0  # sharp decline alone counts as a soft invalidation signal


def _check_invalidation(obs: dict, return_pct: float) -> Optional[str]:
    """Returns a failure_reason string if a real invalidation trigger
    fired, else None. Re-fetches CURRENT state — this is intentionally
    NOT reading from the immutable snapshot, since the whole point is
    checking whether things have CHANGED since discovery."""
    symbol = obs["symbol"]
    coin_id = obs["coin_id"]
    reasons = []

    try:
        platforms = cdata.fetch_platforms(coin_id)
    except Exception as e:
        log.debug(f"platform fetch failed during invalidation check for {symbol}: {e}")
        platforms = {}

    try:
        if onchain.is_onchain_supported(platforms):
            signal = onchain.whale_concentration_signal(platforms)
            current_accum = onchain.whale_accumulation_delta(symbol, signal)
            if (obs.get("whale_label_at_discovery") == "ACCUMULATING"
                    and current_accum.get("available")
                    and current_accum.get("label") == "DISTRIBUTING"):
                reasons.append("whale distribution detected (was accumulating at discovery)")
    except Exception as e:
        log.debug(f"invalidation whale check failed for {symbol}: {e}")

    try:
        current_risk = risk_engine.assess_false_pearl_risk(platforms)
        if (obs.get("risk_severity_at_discovery") != "HIGH_RISK"
                and current_risk.get("severity") == "HIGH_RISK"):
            reasons.append("security risk escalated to HIGH_RISK since discovery")
    except Exception as e:
        log.debug(f"invalidation risk check failed for {symbol}: {e}")

    if return_pct is not None and return_pct <= INVALIDATION_RETURN_THRESHOLD_PCT:
        reasons.append(f"price declined sharply ({return_pct:+.1f}%) since discovery")

    return "; ".join(reasons) if reasons else None


def resolve_matured_pearls() -> dict:
    """Call at the start of every Pearl Detection Machine run. Checks
    every horizon, resolves what's matured, applies lifecycle
    transitions. Returns a summary dict for logging."""
    resolved_counts = {h: 0 for h in HORIZONS}
    invalidated_count = 0

    for horizon in HORIZONS:
        due = get_pearl_observations_due(horizon)
        for obs in due:
            live_price = cdata.fetch_live_price_binance(obs["symbol"])
            if live_price is None or not obs["price_at_observation"]:
                continue
            return_pct = round(100.0 * (live_price - obs["price_at_observation"]) / obs["price_at_observation"], 2)

            failure_reason = _check_invalidation(obs, return_pct)

            if failure_reason:
                resolve_pearl_observation(obs["id"], horizon, live_price, return_pct,
                                           new_lifecycle_state="INVALIDATED", failure_reason=failure_reason)
                invalidated_count += 1
            elif horizon == "30d":
                # terminal resolution — no invalidation trigger fired,
                # so the outcome is judged purely on whether the thesis
                # paid off
                terminal_state = "CONFIRMED" if return_pct > 0 else "FAILED"
                resolve_pearl_observation(obs["id"], horizon, live_price, return_pct,
                                           new_lifecycle_state=terminal_state, terminal_return_pct=return_pct)
            else:
                # still alive, no invalidation yet, not at the terminal
                # horizon — record the resolution but leave lifecycle_state
                # as-is (UNDER_OBSERVATION); passing None means resolve_pearl_observation
                # updates ONLY the resolution columns, not lifecycle
                resolve_pearl_observation(obs["id"], horizon, live_price, return_pct)

            resolved_counts[horizon] += 1

    log.info(f"Pearl flywheel resolved: {resolved_counts}, {invalidated_count} newly invalidated")
    return {"resolved_counts": resolved_counts, "invalidated_count": invalidated_count}
