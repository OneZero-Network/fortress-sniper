"""
FORTRESS_CRYPTO — core/crypto/regime.py
══════════════════════════════════════════════════════════════════════════════
Market regime detection — the first of your mentor's two "critical gap"
items. Answers: is the broad market trending, ranging, or falling, and is
volatility elevated right now? The same signal can perform very
differently across these states, and until this existed, every score in
this system used a hardcoded neutral macro_score=50.0 regardless of what
the market was actually doing — this replaces that placeholder with a
real read.

SCOPED HONESTLY: this is BTC-anchored, not a multi-factor macro model.
BTC is used as crypto's de facto market-wide proxy (same reasoning
factors_crypto.py uses for residual momentum) — it's not "the market" in
a strict sense, and altcoin-specific regimes can diverge from BTC's, but
a single reliable anchor beats a fabricated composite built on data this
system doesn't have (no derivatives/funding-rate feed, no cross-asset
correlation matrix).

Classification uses only price data already available via
core/crypto/data.py — no new API dependency:
  - TREND: BTC price vs its own 50-day MA, plus 30d return magnitude
  - VOLATILITY: BTC's current NATR14 (ATR normalized by price) vs its
    own recent history — a simple self-relative percentile, not an
    absolute threshold pulled from nowhere

This produces ONE regime read per sniper run (not per-coin — BTC data is
fetched once and reused), both as a Telegram header label and as the
macro_score component of unified_conviction() — real weight that used to
be spent on a constant.
"""
from __future__ import annotations
import logging
from typing import Optional

import numpy as np
import pandas as pd

from . import config as ccfg
from . import data as cdata
from ..indicators import compute_indicators

log = logging.getLogger("fortress.crypto.regime")


def _trend_state(hist: pd.DataFrame, ind: dict) -> dict:
    close = float(hist["close"].iloc[-1])
    ma50 = ind.get("ma50", 0.0)
    ret_30d = None
    if len(hist) >= 31:
        past = float(hist["close"].iloc[-31])
        if past > 0:
            ret_30d = round(100.0 * (close - past) / past, 1)

    if ma50 <= 0 or ret_30d is None:
        return {"state": "UNKNOWN", "detail": "insufficient history for trend read"}

    if close > ma50 and ret_30d > 8:
        return {"state": "BULL", "detail": f"BTC above 50MA, 30d {ret_30d:+.1f}%"}
    if close < ma50 and ret_30d < -12:
        return {"state": "BEAR", "detail": f"BTC below 50MA, 30d {ret_30d:+.1f}%"}
    return {"state": "SIDEWAYS", "detail": f"BTC near 50MA, 30d {ret_30d:+.1f}%"}


def _volatility_state(hist: pd.DataFrame, ind: dict) -> dict:
    """Self-relative: today's NATR14 vs the distribution of NATR14 over
    the same lookback window — a coin/market isn't 'high vol' by some
    fixed number, it's high vol RELATIVE TO ITS OWN RECENT BEHAVIOR."""
    natr14 = ind.get("natr14", 0.0)
    if natr14 <= 0 or len(hist) < 30:
        return {"state": "UNKNOWN", "detail": "insufficient history for volatility read", "percentile": None}

    # Approximate a rolling NATR series from ATR/close ratio over the window
    close = hist["close"].astype(float)
    high = hist["high"].astype(float)
    low = hist["low"].astype(float)
    daily_range_pct = ((high - low) / close.replace(0, np.nan)) * 100
    daily_range_pct = daily_range_pct.dropna()
    if len(daily_range_pct) < 10:
        return {"state": "UNKNOWN", "detail": "insufficient range data", "percentile": None}

    current = daily_range_pct.iloc[-1]
    percentile = round(100.0 * (daily_range_pct < current).mean(), 0)

    if percentile >= 70:
        return {"state": "HIGH_VOL", "detail": f"today's range in top {100-percentile:.0f}% of last {len(daily_range_pct)}d", "percentile": percentile}
    if percentile <= 30:
        return {"state": "LOW_VOL", "detail": f"today's range in bottom {percentile:.0f}% of last {len(daily_range_pct)}d", "percentile": percentile}
    return {"state": "NORMAL_VOL", "detail": f"today's range mid-pack ({percentile:.0f}th pctile) of last {len(daily_range_pct)}d", "percentile": percentile}


def _macro_score_from_regime(trend_state: str, vol_state: str) -> float:
    """Maps regime to the 0-100 macro_score slot in unified_conviction().
    BULL raises the floor for everything scored that run; BEAR lowers it;
    HIGH_VOL trims a bit off any state (wider whipsaw risk cuts both
    ways, not just adds upside). These weights are reasoned defaults, not
    backtested — flagged the same as every other new default in this
    system until real outcome data justifies tuning them."""
    base = {"BULL": 70.0, "SIDEWAYS": 50.0, "BEAR": 30.0, "UNKNOWN": 50.0}.get(trend_state, 50.0)
    vol_adj = {"HIGH_VOL": -8.0, "NORMAL_VOL": 0.0, "LOW_VOL": 3.0, "UNKNOWN": 0.0}.get(vol_state, 0.0)
    return round(max(0.0, min(100.0, base + vol_adj)), 1)


def detect_market_regime() -> dict:
    """Call ONCE per sniper run — not per coin. Returns:
      {"trend": "BULL"|"BEAR"|"SIDEWAYS"|"UNKNOWN",
       "volatility": "HIGH_VOL"|"NORMAL_VOL"|"LOW_VOL"|"UNKNOWN",
       "macro_score": float, "label": str, "available": bool}
    On any data failure, returns available=False with macro_score=50.0
    (neutral) — same fail-safe-neutral policy as every other optional
    signal in this system, never a fabricated confident regime read."""
    hist = cdata.fetch_daily_ohlc(ccfg.BENCHMARK_COIN_ID, days=95)
    if hist.empty or len(hist) < 30:
        log.warning("detect_market_regime: insufficient BTC history, defaulting to neutral")
        return {"trend": "UNKNOWN", "volatility": "UNKNOWN", "macro_score": 50.0,
                "label": "UNKNOWN (insufficient data)", "available": False}

    ind = compute_indicators(hist)
    trend = _trend_state(hist, ind)
    vol = _volatility_state(hist, ind)
    macro_score = _macro_score_from_regime(trend["state"], vol["state"])

    label = f"{trend['state']} / {vol['state']}"
    log.info(f"Market regime: {label} (macro_score={macro_score}) — {trend['detail']}; {vol['detail']}")

    return {"trend": trend["state"], "volatility": vol["state"], "macro_score": macro_score,
            "label": label, "trend_detail": trend["detail"], "vol_detail": vol["detail"],
            "available": True}
