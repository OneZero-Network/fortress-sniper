"""
FORTRESS_CRYPTO — core/crypto/regime_v2.py
══════════════════════════════════════════════════════════════════════════════
Phase B — regime engine rebuild, per explicit mandate:

  "Don't optimize it against trading profitability. That's extremely
   important. The question should simply be: Can this engine correctly
   describe the market state?"

v1 (core/crypto/regime.py) failed calibration: its BULL/NORMAL_VOL calls
were followed by BTC actually rising only 0% (discovery) and 36.4%
(validation) of the time — Regime Audit v1 proved the label didn't mean
what it claimed. v1 is NOT modified or removed (it's quarantined, still
computed/logged for comparison) — this is a genuinely separate, second
attempt, built with more factors and tested the same honest way before
it's trusted with anything.

FIVE FACTORS, each computed with NO LOOKAHEAD (only data up to the
current day, same discipline as backtest.py):

  1. TREND     — BTC price vs its own 100-day MA (longer than v1's
                 50-day, less reactive to short noise)
  2. MOMENTUM  — blended 7d/30d/90d returns, weighted toward recent
  3. VOLATILITY — today's daily range vs its own trailing distribution
                  (self-relative, same concept as v1, reimplemented
                  independently here rather than importing v1's function,
                  so v2's calibration is not silently coupled to v1's
                  potentially-flawed implementation details)
  4. BREADTH   — fraction of a basket of major-cap coins with positive
                 30-day trailing return, at the SAME point in time — "is
                 the whole market participating, or just BTC"
  5. LIQUIDITY — BTC's own volume today vs its trailing 20-day average
                 (a market-wide liquidity PROXY, not true aggregate
                 market volume — stated honestly, computing genuine
                 market-wide volume would need historical volume for
                 every tracked coin, a much larger fetch)

Combined into a single 0-100 composite score and a 3-state descriptive
label (FAVORABLE / NEUTRAL / UNFAVORABLE) — simpler than v1's 9-cell
BULL/BEAR/SIDEWAYS x HIGH/NORMAL/LOW grid, chosen deliberately because a
simpler label is easier to calibrate honestly with the sample sizes this
system can realistically gather.

THIS MODULE IS NOT WIRED INTO ANY LIVE SCORING PATH. It stays
research-only until scripts/calibrate_regime_v2.py demonstrates it
actually describes the market better than v1 did.
"""
from __future__ import annotations
import logging
from typing import List, Optional

import numpy as np
import pandas as pd

log = logging.getLogger("fortress.crypto.regime_v2")


def _trend_factor(hist: pd.DataFrame) -> Optional[float]:
    """0-100: how far above/below its own 100-day MA, squashed. Returns
    None if insufficient history (< 100 rows) rather than a guessed
    midpoint — the caller must treat None as 'this factor unavailable',
    not as neutral 50."""
    if len(hist) < 100:
        return None
    close = hist["close"].astype(float)
    ma100 = close.rolling(100).mean().iloc[-1]
    current = close.iloc[-1]
    if ma100 <= 0:
        return None
    pct_above = (current - ma100) / ma100 * 100.0
    # squash: +20% above MA100 -> ~100, -20% below -> ~0, linear between
    return round(max(0.0, min(100.0, 50.0 + pct_above * 2.5)), 1)


def _momentum_factor(hist: pd.DataFrame) -> Optional[float]:
    """0-100: blended 7d/30d/90d returns, weighted 50/30/20 toward
    recent. None if insufficient history for the longest window."""
    close = hist["close"].astype(float)
    if len(close) < 91:
        return None
    ret_7d = (close.iloc[-1] - close.iloc[-8]) / close.iloc[-8] * 100.0
    ret_30d = (close.iloc[-1] - close.iloc[-31]) / close.iloc[-31] * 100.0
    ret_90d = (close.iloc[-1] - close.iloc[-91]) / close.iloc[-91] * 100.0
    blended = 0.5 * ret_7d + 0.3 * ret_30d + 0.2 * ret_90d
    return round(max(0.0, min(100.0, 50.0 + blended * 1.5)), 1)


def _volatility_factor(hist: pd.DataFrame) -> Optional[dict]:
    """Returns {'score_0_100': ..., 'state': 'HIGH'|'NORMAL'|'LOW'}.
    Self-relative percentile of today's daily range vs trailing history —
    reimplemented independently from v1's _volatility_state so v2's
    calibration doesn't silently inherit any v1 implementation quirk."""
    if len(hist) < 30:
        return None
    high = hist["high"].astype(float)
    low = hist["low"].astype(float)
    close = hist["close"].astype(float)
    daily_range_pct = ((high - low) / close.replace(0, np.nan)) * 100
    daily_range_pct = daily_range_pct.dropna()
    if len(daily_range_pct) < 20:
        return None
    current = daily_range_pct.iloc[-1]
    percentile = float((daily_range_pct < current).mean()) * 100.0
    if percentile >= 70:
        state = "HIGH"
    elif percentile <= 30:
        state = "LOW"
    else:
        state = "NORMAL"
    # score: HIGH_VOL is treated as a mild NEGATIVE for the composite
    # (more whipsaw risk), LOW_VOL mildly positive, NORMAL neutral
    score = {"LOW": 60.0, "NORMAL": 50.0, "HIGH": 35.0}[state]
    return {"score_0_100": score, "state": state, "percentile": round(percentile, 1)}


def _breadth_factor(basket_hists: List[pd.DataFrame]) -> Optional[float]:
    """0-100: % of the basket with positive 30-day trailing return, AT
    THE SAME implicit point in time as every hist passed in (caller's
    responsibility to slice consistently — no lookahead check happens
    inside this function, it trusts its inputs)."""
    valid_returns = []
    for h in basket_hists:
        close = h["close"].astype(float)
        if len(close) < 31 or close.iloc[-31] <= 0:
            continue
        ret_30d = (close.iloc[-1] - close.iloc[-31]) / close.iloc[-31] * 100.0
        valid_returns.append(ret_30d)
    if len(valid_returns) < 3:
        return None
    pct_positive = 100.0 * sum(1 for r in valid_returns if r > 0) / len(valid_returns)
    return round(pct_positive, 1)


def _liquidity_factor(hist: pd.DataFrame) -> Optional[float]:
    """0-100: today's volume vs trailing 20-day average, squashed.
    PROXY for market-wide liquidity via BTC's own volume trend — stated
    honestly, not a true aggregate-market volume measure."""
    if "volume" not in hist.columns or len(hist) < 21:
        return None
    vol = hist["volume"].astype(float)
    today_vol = vol.iloc[-1]
    avg_vol = vol.iloc[-21:-1].mean()
    if avg_vol <= 0:
        return None
    ratio = today_vol / avg_vol
    # ratio of 1.0 (average) -> 50, 2.0x -> ~75, 0.5x -> ~25
    return round(max(0.0, min(100.0, 50.0 + (ratio - 1.0) * 25.0)), 1)


def compute_regime_v2(btc_hist: pd.DataFrame, basket_hists: List[pd.DataFrame]) -> dict:
    """Composite regime read. Any factor unavailable (insufficient
    history) is excluded from the composite rather than defaulted to
    neutral — the composite is only computed from factors that actually
    have data, and 'factors_available' is reported so a thin-data read
    is never silently presented with the same confidence as a full one."""
    trend = _trend_factor(btc_hist)
    momentum = _momentum_factor(btc_hist)
    vol = _volatility_factor(btc_hist)
    breadth = _breadth_factor(basket_hists)
    liquidity = _liquidity_factor(btc_hist)

    weights = {"trend": 0.35, "momentum": 0.25, "volatility": 0.15, "breadth": 0.15, "liquidity": 0.10}
    values = {"trend": trend, "momentum": momentum,
              "volatility": vol["score_0_100"] if vol else None,
              "breadth": breadth, "liquidity": liquidity}

    available = {k: v for k, v in values.items() if v is not None}
    if not available:
        return {"available": False, "label": "UNKNOWN", "composite_score": None, "factors": values}

    total_weight = sum(weights[k] for k in available)
    composite = sum(values[k] * weights[k] for k in available) / total_weight
    composite = round(composite, 1)

    if composite >= 62:
        label = "FAVORABLE"
    elif composite <= 38:
        label = "UNFAVORABLE"
    else:
        label = "NEUTRAL"

    return {
        "available": True, "label": label, "composite_score": composite,
        "factors": values, "volatility_state": vol["state"] if vol else None,
        "factors_available": list(available.keys()),
    }
