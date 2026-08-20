"""
FORTRESS_CRYPTO — core/crypto/factors_crypto.py
══════════════════════════════════════════════════════════════════════════════
Cross-sectional Composite Z-Score factor model, crypto analogue of
core/factors.py. Same statistical philosophy (Z-score against THIS scan's
universe, not a fabricated long-run per-token distribution), three legs
re-derived for what crypto data actually offers:

  Momentum (Z_mom)   : residual return over MOMENTUM_LOOKBACK_DAYS vs BTC
                        (not vs an index — BTC is crypto's de facto beta
                        anchor). Idiosyncratic strength, same concept as
                        equity's NIFTY-relative residual.
  "Value" (Z_val)     : inverse NVT ratio (market_cap / 24h on-chain-ish
                        volume proxy — CoinGecko doesn't expose true
                        on-chain transfer volume for most tokens, so this
                        uses reported trading volume as the denominator,
                        which is a WEAKER proxy than true NVT and is
                        labeled as such). Lower NVT = "more economic
                        activity per dollar of valuation" = cheaper.
  On-chain quality (Z_qual) : holder-concentration score from
                        core/crypto/onchain.py (lower concentration =
                        higher quality/less fragile). Replaces equity's
                        ROE — crypto has no ROE. Neutral (None -> 0.0) for
                        non-EVM tokens or tokens with no on-chain signal,
                        same fail-safe-neutral policy as equity factors.py.

Below FACTOR_MIN_UNIVERSE_N candidates, degrades to neutral 50.0 for
everyone (same threshold-guard as equity).
"""
from __future__ import annotations
import logging
from typing import Dict, List, Optional

import numpy as np

from . import config as ccfg

log = logging.getLogger("fortress.crypto.factors")


def _safe_zscores(values: List[Optional[float]]) -> List[float]:
    valid = [v for v in values if v is not None and np.isfinite(v)]
    if len(valid) < 2:
        return [0.0] * len(values)
    mu, sd = float(np.mean(valid)), float(np.std(valid))
    if sd == 0:
        return [0.0] * len(values)
    return [round((v - mu) / sd, 3) if (v is not None and np.isfinite(v)) else 0.0
            for v in values]


def _to_0_100(z: float) -> float:
    """Squash a Z-score (~-3..+3) into a 0-100 scale via a simple sigmoid-
    like clip, same approach equity factors.py uses for the final blend."""
    return round(max(0.0, min(100.0, 50.0 + z * 16.0)), 1)


def compute_composite_scores(candidates: List[dict]) -> Dict[str, dict]:
    """
    candidates: list of dicts, each needs:
      - 'symbol'
      - 'residual_momentum_pct' : float or None (return vs BTC over lookback)
      - 'nvt_proxy'             : float or None (market_cap / 24h volume; lower=better)
      - 'onchain_quality_0_100' : float or None (from onchain.onchain_quality_score_0_100)

    Returns {symbol: {"z_composite": float 0-100, "z_momentum": ..,
                       "z_value": .., "z_quality": .., "degraded": bool}}
    """
    n = len(candidates)
    if n < ccfg.FACTOR_MIN_UNIVERSE_N:
        log.info(f"factors_crypto: universe n={n} < {ccfg.FACTOR_MIN_UNIVERSE_N}, degrading to neutral 50.0 for all")
        return {c["symbol"]: {"z_composite": 50.0, "z_momentum": 0.0, "z_value": 0.0,
                               "z_quality": 0.0, "degraded": True} for c in candidates}

    mom_vals = [c.get("residual_momentum_pct") for c in candidates]
    # inverse NVT: lower NVT = cheaper = higher value score, so negate before Z
    nvt_vals = [(-c["nvt_proxy"] if c.get("nvt_proxy") not in (None, 0) else None)
                for c in candidates]
    qual_vals = [c.get("onchain_quality_0_100") for c in candidates]

    z_mom = _safe_zscores(mom_vals)
    z_val = _safe_zscores(nvt_vals)
    z_qual = _safe_zscores(qual_vals)

    out = {}
    for i, c in enumerate(candidates):
        composite_z = (ccfg.FACTOR_W_MOMENTUM * z_mom[i] +
                        ccfg.FACTOR_W_VALUE_NVT * z_val[i] +
                        ccfg.FACTOR_W_ONCHAIN_QUALITY * z_qual[i])
        out[c["symbol"]] = {
            "z_composite": _to_0_100(composite_z),
            "z_momentum": z_mom[i],
            "z_value": z_val[i],
            "z_quality": z_qual[i],
            "degraded": False,
        }
    return out


def residual_momentum_pct(coin_return_pct: Optional[float], btc_return_pct: Optional[float]) -> Optional[float]:
    """Idiosyncratic momentum = coin's own return minus BTC's return over
    the same window. Falls back to raw coin return if BTC data unavailable
    (mirrors equity's NIFTY-fallback behavior)."""
    if coin_return_pct is None:
        return None
    if btc_return_pct is None:
        return coin_return_pct
    return round(coin_return_pct - btc_return_pct, 3)
