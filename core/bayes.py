"""
FORTRESS_UNIFIED — core/bayes.py
══════════════════════════════════════════════════════════════════════════════
Port of the legacy naive-Bayes win-probability engine (Pine v12.3's 9-node
posterior / sniper's bayes_win_probability), replacing the 55.0 placeholder
constant in sniper_daily.

Pure math, no network. Each node contributes a likelihood ratio
P(evidence|win)/P(evidence|loss); posterior odds = prior odds × ∏LR.
LRs are the legacy hand-tuned values — deliberately modest (1.2–1.6×) so
no single node dominates, and the output is clamped to [5, 95] because a
naive-Bayes over correlated evidence overstates certainty at the extremes.
"""
from __future__ import annotations
import logging
from typing import Dict

log = logging.getLogger("fortress.bayes")

PRIOR_WIN = 0.45  # base rate for a gate-passing breakout candidate


def bayes_win_probability(fortress: Dict, macro: Dict, order_flow: Dict) -> float:
    """Returns win probability as a percentage in [5, 95]."""
    if not fortress:
        return 50.0
    try:
        odds = PRIOR_WIN / (1.0 - PRIOR_WIN)

        # Node 1 — uptrend structure
        odds *= 1.6 / 1.0 if fortress.get("uptrend_ok") else 0.7 / 1.0

        # Node 2 — VCP coil (volatility contraction)
        natr14, natr100 = fortress.get("natr14", 0), fortress.get("natr100", 0)
        if natr14 > 0 and natr100 > 0:
            ratio = natr14 / natr100
            odds *= 1.5 if ratio < 0.65 else 1.2 if ratio < 0.80 else 0.9

        # Node 3 — RSI band
        rsi = fortress.get("rsi14", 50)
        odds *= 1.3 if 45 <= rsi <= 65 else 1.05 if 35 <= rsi < 45 else \
                0.85 if rsi > 75 else 1.0

        # Node 4 — trend strength
        adx = fortress.get("adx14", 0)
        odds *= 1.4 if adx >= 25 else 1.15 if adx >= 20 else 0.9

        # Node 5 — whale accumulation
        if order_flow.get("whale_flag"):
            odds *= 1.5
        elif order_flow.get("whale_available") and order_flow.get("whale_score", 0) == 0:
            odds *= 0.9

        # Node 6 — delivery quality (only when actually known)
        dp = order_flow.get("delivery_pct", -1)
        if dp >= 65:
            odds *= 1.4
        elif 0 <= dp < 30:
            odds *= 0.85

        # Node 7 — macro regime
        odds *= {"TREND": 1.5, "CHOP": 1.0, "BUNKER": 0.7,
                 "PANIC": 0.5, "MASSACRE": 0.4}.get(macro.get("macro_state", "CHOP"), 1.0)

        # Node 8 — 52W-high proximity (breakouts near highs carry through)
        hi52, close = fortress.get("hi52", 0), fortress.get("close", 0)
        if hi52 > 0 and close > 0:
            pct_from_h = (hi52 - close) / hi52 * 100
            odds *= 1.3 if pct_from_h <= 5 else 1.15 if pct_from_h <= 10 else \
                    0.9 if pct_from_h > 30 else 1.0

        # Node 9 — MFI (money-flow, not overheated)
        mfi = fortress.get("mfi", 50)
        odds *= 1.2 if 40 <= mfi <= 65 else 0.9 if mfi > 80 else 1.0

        # Node 10 — VPOC support (price accepted at high-volume node)
        if order_flow.get("at_vpoc_support"):
            odds *= 1.25

        p = odds / (1.0 + odds)
        return round(max(5.0, min(95.0, p * 100)), 1)
    except Exception as e:
        log.debug(f"bayes_win_probability: {e}")
        return 50.0
