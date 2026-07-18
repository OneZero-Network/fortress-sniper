"""
FORTRESS_UNIFIED — core/factors.py
══════════════════════════════════════════════════════════════════════════════
Method 1 from your friends' notes: the Composite Z-Score factor model.
Merges Momentum, Value, and Quality into one master score instead of
running them as separate, uncoordinated strategies.

IMPORTANT — what makes a Z-score meaningful here:
A Z-score only means something relative to a distribution. We do NOT have
a stable, long-run per-stock history of "this stock's typical P/E" to
compare against (that needs years of clean fundamental history most
symbols don't have via free data sources). So this is a CROSS-SECTIONAL
Z-score: every candidate is scored relative to the OTHER candidates in
the SAME day's scan universe. "Is this stock cheaper than its peers in
today's scan, in Z-score units" — not "is this stock cheap vs its own
10-year history." This is the honest, robust version given the data we
actually have, and it's also what most factor-investing literature
actually means by cross-sectional factor scoring.

Three legs:
  Momentum (Z_mom)  : 63-day residual return (stock return minus NIFTY
                       return over the same window — "idiosyncratic"
                       strength, not just beta to the index). Falls back
                       to raw return if NIFTY data is unavailable.
  Value (Z_val)      : inverse P/E (cheaper = higher Z), falls back to
                       inverse P/B if P/E is unavailable/negative.
  Quality (Z_qual)   : ROE %.

Any leg with insufficient cross-sectional data (too many None values)
degrades to a neutral 0.0 contribution for the affected stocks rather
than crashing or silently dropping — see compute_composite_zscores().

Requires config.FACTOR_MIN_UNIVERSE_N candidates minimum, else Z-scores
are statistically unstable and the function returns neutral 50.0 scores
for everyone with a flag explaining why.
"""
from __future__ import annotations
import logging
from typing import Dict, List, Optional

import numpy as np

from . import config

log = logging.getLogger("fortress.factors")


def _safe_zscores(values: List[Optional[float]]) -> List[float]:
    """Z-score a list with Nones. Nones get 0.0 (neutral) after scoring
    the valid values — they neither help nor hurt a candidate whose data
    is simply missing, which is the fail-safe-neutral policy for a
    STATISTICAL factor (as opposed to a compliance gate, which fails
    closed/reject instead)."""
    valid = [v for v in values if v is not None and np.isfinite(v)]
    if len(valid) < 2:
        return [0.0] * len(values)
    mu, sd = float(np.mean(valid)), float(np.std(valid))
    if sd == 0:
        return [0.0] * len(values)
    return [round((v - mu) / sd, 3) if (v is not None and np.isfinite(v)) else 0.0
            for v in values]


def compute_residual_momentum(stock_returns: Dict[str, float],
                               index_return_63d: Optional[float]) -> Dict[str, float]:
    """
    stock_returns: {symbol: 63-day raw return (fraction, e.g. 0.15 = +15%)}
    index_return_63d: NIFTY 500 (or NIFTY 50) return over the same window.
    Returns {symbol: residual_return} = stock_return - index_return.
    If index_return_63d is None, residual = raw return (documented
    degradation, not silent).
    """
    idx_ret = index_return_63d if index_return_63d is not None else 0.0
    return {sym: round(ret - idx_ret, 4) for sym, ret in stock_returns.items()}


def compute_composite_zscores(candidates: List[Dict]) -> List[Dict]:
    """
    candidates: list of dicts, each MUST have a 'symbol' key and SHOULD have:
      - 'residual_return'  (float, from compute_residual_momentum)
      - 'pe_ratio'          (float or None)
      - 'pb_ratio'          (float or None, used if pe_ratio is None/<=0)
      - 'roe_pct'           (float or None)

    Returns the same list with 'z_momentum', 'z_value', 'z_quality',
    'z_composite' added to each dict (mutates and returns candidates).

    z_composite = w_mom*Z_mom + w_val*Z_val + w_qual*Z_qual
    then rescaled to a 0-100 "factor_score_0_100" for easy blending into
    the unified conviction score (via a sigmoid-free min-max clip at
    ±3 std devs, since raw Z-scores are unbounded).
    """
    if not config.FACTOR_ZSCORE_ENABLED:
        for c in candidates:
            c.update(z_momentum=0.0, z_value=0.0, z_quality=0.0,
                     z_composite=0.0, factor_score_0_100=50.0,
                     factor_note="factor model disabled")
        return candidates

    n = len(candidates)
    if n < config.FACTOR_MIN_UNIVERSE_N:
        for c in candidates:
            c.update(z_momentum=0.0, z_value=0.0, z_quality=0.0,
                     z_composite=0.0, factor_score_0_100=50.0,
                     factor_note=f"universe too small (n={n} < {config.FACTOR_MIN_UNIVERSE_N}) — neutral")
        return candidates

    mom_raw = [c.get("residual_return") for c in candidates]

    # Value: inverse P/E (cheaper -> higher raw value), fallback to inverse P/B
    val_raw = []
    for c in candidates:
        pe = c.get("pe_ratio")
        pb = c.get("pb_ratio")
        if pe is not None and pe > 0:
            val_raw.append(1.0 / pe)
        elif pb is not None and pb > 0:
            val_raw.append(1.0 / pb)
        else:
            val_raw.append(None)

    qual_raw = [c.get("roe_pct") for c in candidates]

    z_mom = _safe_zscores(mom_raw)
    z_val = _safe_zscores(val_raw)
    z_qual = _safe_zscores(qual_raw)

    w_mom, w_val, w_qual = (config.FACTOR_W_MOMENTUM, config.FACTOR_W_VALUE,
                            config.FACTOR_W_QUALITY)
    w_total = w_mom + w_val + w_qual or 1.0

    for c, zm, zv, zq in zip(candidates, z_mom, z_val, z_qual):
        composite = (w_mom * zm + w_val * zv + w_qual * zq) / w_total
        # Clip at +/-3 std devs (covers >99% of a normal-ish distribution),
        # then min-max to 0-100 for blending with other 0-100 scores.
        clipped = max(-3.0, min(3.0, composite))
        score_0_100 = round((clipped + 3.0) / 6.0 * 100, 1)
        missing = []
        if c.get("residual_return") is None:
            missing.append("momentum")
        if c.get("pe_ratio") is None and c.get("pb_ratio") is None:
            missing.append("value")
        if c.get("roe_pct") is None:
            missing.append("quality")
        note = f"missing: {','.join(missing)}" if missing else "complete"
        c.update(z_momentum=zm, z_value=zv, z_quality=zq,
                 z_composite=round(composite, 3),
                 factor_score_0_100=score_0_100, factor_note=note)
    return candidates
