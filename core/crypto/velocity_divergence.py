"""
FORTRESS_CRYPTO — core/crypto/velocity_divergence.py
══════════════════════════════════════════════════════════════════════════════
v3.0 — Change & Divergence Engine. Per explicit instruction: start with
ONE lens (velocity + divergence), use data already available, add it as
a Level 0 OBSERVATION layer — it does NOT feed into pearl_score's
discovery_score or affect ranking/tier classification in any way. This
is purely additional context shown alongside a candidate, exactly like
whale/news/risk are shown but with its own honest evidence status.

Per core/crypto/evidence.py's pattern: this starts unvalidated. If the
Pearl Flywheel later shows high-velocity/divergence assets consistently
outperform, THIS earns a higher evidence level and can be promoted into
actual scoring — not before.

VELOCITY — "what's changing, not what's the current value":
  - volume_ratio: today's volume vs trailing 7-day average
  - price_acceleration: is the 7-day return itself accelerating or
    decelerating vs the prior 7-day window (a second-derivative read,
    not just "is price up")

DIVERGENCE — "do the signals agree or disagree":
  - Compares price direction against whale behavior (the only other
    directional signal reliably available). A coin whose price is
    FALLING while whales are ACCUMULATING is flagged as a possible
    bullish divergence (worth attention, not a claim it will pan out).
    The reverse (price surging while whales DISTRIBUTE) is flagged as a
    possible false-pearl warning sign — informational, does NOT feed
    the false_pearl_risk_pct number itself (that stays contract-security
    based, per the existing, separately-scoped False Pearl layer).

HONEST SCOPE: divergence here only checks price vs whale, since that's
the only other genuinely directional signal this system has. News
sentiment and liquidity trend are NOT yet part of divergence — adding
them is a natural extension once this lens itself proves useful, not
before.
"""
from __future__ import annotations
import logging
from typing import Optional

import numpy as np
import pandas as pd

from . import data as cdata

log = logging.getLogger("fortress.crypto.velocity")


def compute_velocity(hist: pd.DataFrame) -> Optional[dict]:
    """Returns {"volume_ratio": float, "volume_label": str,
    "price_acceleration_pct": float, "acceleration_label": str} or None
    if insufficient history. volume_ratio > 1 means today's volume is
    above its own 7-day average — NOT compared to any absolute
    threshold, purely self-relative, same philosophy as the volatility
    percentile check elsewhere in this system."""
    if hist is None or hist.empty or len(hist) < 15:
        return None

    volume = hist["volume"].astype(float)
    today_vol = volume.iloc[-1]
    avg_vol_7d = volume.iloc[-8:-1].mean()
    volume_ratio = round(today_vol / avg_vol_7d, 2) if avg_vol_7d > 0 else None

    close = hist["close"].astype(float)
    if len(close) < 15:
        price_accel_pct = None
    else:
        ret_recent_7d = (close.iloc[-1] - close.iloc[-8]) / close.iloc[-8] * 100.0
        ret_prior_7d = (close.iloc[-8] - close.iloc[-15]) / close.iloc[-15] * 100.0
        price_accel_pct = round(ret_recent_7d - ret_prior_7d, 2)

    if volume_ratio is None and price_accel_pct is None:
        return None

    volume_label = None
    if volume_ratio is not None:
        if volume_ratio >= 2.5:
            volume_label = "SURGING"
        elif volume_ratio >= 1.5:
            volume_label = "ELEVATED"
        elif volume_ratio <= 0.5:
            volume_label = "DRYING_UP"
        else:
            volume_label = "NORMAL"

    accel_label = None
    if price_accel_pct is not None:
        if price_accel_pct >= 10:
            accel_label = "ACCELERATING_UP"
        elif price_accel_pct <= -10:
            accel_label = "DECELERATING"
        else:
            accel_label = "STEADY"

    return {"volume_ratio": volume_ratio, "volume_label": volume_label,
            "price_acceleration_pct": price_accel_pct, "acceleration_label": accel_label}


def compute_divergence(recent_price_return_pct: Optional[float], whale_accum: Optional[dict]) -> dict:
    """Compares price direction against whale accumulation direction —
    the only two genuinely directional signals available. Returns
    {"available": bool, "label": str, "detail": str}. label is one of:
    BULLISH_DIVERGENCE (price down, whales accumulating — worth
    attention), BEARISH_DIVERGENCE (price up strongly, whales
    distributing — possible false-pearl warning), ALIGNED (both agree),
    NONE (not enough signal to compare)."""
    if recent_price_return_pct is None or not whale_accum or not whale_accum.get("available"):
        return {"available": False, "label": "NONE", "detail": "insufficient signal to compare"}

    whale_label = whale_accum.get("label")
    price_falling = recent_price_return_pct < -3
    price_surging = recent_price_return_pct > 15

    if price_falling and whale_label == "ACCUMULATING":
        return {"available": True, "label": "BULLISH_DIVERGENCE",
                "detail": f"price down {recent_price_return_pct:+.1f}% while whales are accumulating — worth attention"}
    if price_surging and whale_label == "DISTRIBUTING":
        return {"available": True, "label": "BEARISH_DIVERGENCE",
                "detail": f"price up {recent_price_return_pct:+.1f}% while whales are distributing — possible false-pearl warning sign"}
    if whale_label in ("ACCUMULATING", "DISTRIBUTING"):
        return {"available": True, "label": "ALIGNED",
                "detail": "price and whale behavior are moving in the same direction, no divergence detected"}
    return {"available": True, "label": "ALIGNED", "detail": "whale behavior stable, no divergence signal"}


def get_velocity_and_divergence(coin_id: str, recent_price_return_pct: Optional[float],
                                 whale_accum: Optional[dict]) -> dict:
    """Convenience wrapper: fetches OHLC once, computes both velocity and
    divergence. Adds ONE extra API call per candidate (the OHLC fetch) —
    this is the real cost of this lens, stated plainly since it's not
    free. Returns a dict with both sub-results, never fabricated."""
    try:
        hist = cdata.fetch_daily_ohlc(coin_id, days=30)
    except Exception as e:
        log.debug(f"velocity OHLC fetch failed for {coin_id}: {e}")
        hist = None

    velocity = compute_velocity(hist) if hist is not None else None
    divergence = compute_divergence(recent_price_return_pct, whale_accum)

    return {"velocity": velocity, "divergence": divergence}
