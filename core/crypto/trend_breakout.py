"""
FORTRESS_CRYPTO — core/crypto/trend_breakout.py
══════════════════════════════════════════════════════════════════════════════
v3.7 — Trend Change + Breakout Engine. Two NEW, independently-built
descriptive signals — explicitly NOT a revival of the rejected technical
trigger (RSI/ADX/volume) or its box-breakout logic in core/indicators.py.
That module is tied to a formally-rejected scoring authority and must
never be reused for anything with scoring weight (see evidence.py).
These are fresh, minimal implementations built for this purpose.

TREND CHANGE — zero extra API calls, uses coin_snapshot fields already
in hand (pct_7d, pct_30d). Detects a SIGN CHANGE (was falling over 30d,
now rising over 7d — or the reverse) versus simple continuation.

BREAKOUT — reuses the SAME cached OHLC fetch already made for the
velocity engine (v3.3's caching means this costs ZERO additional API
calls despite being a "second" fetch_daily_ohlc call for the same coin).
Checks whether today's close exceeds the prior 20-day high — a simple,
independently-built breakout flag, not shared code with the rejected
trigger's box_high_20 logic.

Both are Level 0 / observation-only, same as velocity, divergence, and
relative_anomaly — informational context on a candidate, never a
scoring-authority input beyond the explicitly-labeled Pearl Priority
Score (see pearl_score.py's compute_pearl_priority_score, which is a
RANKING concept, not the discovery_score/tier authority).
"""
from __future__ import annotations
import logging
from typing import Optional

from . import data as cdata

log = logging.getLogger("fortress.crypto.trend_breakout")


def detect_trend_change(coin_snapshot: Optional[dict]) -> dict:
    """Zero extra calls. Compares the SIGN of 7d momentum against 30d
    momentum to distinguish a genuine reversal from continuation."""
    if not coin_snapshot:
        return {"available": False, "label": "NONE"}
    p7 = coin_snapshot.get("pct_7d")
    p30 = coin_snapshot.get("pct_30d")
    if p7 is None or p30 is None:
        return {"available": False, "label": "NONE"}

    if p30 < -5 and p7 > 3:
        return {"available": True, "label": "REVERSAL_BULLISH",
                "detail": f"was falling over 30d ({p30:+.1f}%), now rising over 7d ({p7:+.1f}%)"}
    if p30 > 5 and p7 < -3:
        return {"available": True, "label": "REVERSAL_BEARISH",
                "detail": f"was rising over 30d ({p30:+.1f}%), now falling over 7d ({p7:+.1f}%)"}
    if p30 > 0 and p7 > 0:
        return {"available": True, "label": "CONTINUATION_UP", "detail": f"steady uptrend ({p30:+.1f}% / {p7:+.1f}%)"}
    if p30 < 0 and p7 < 0:
        return {"available": True, "label": "CONTINUATION_DOWN", "detail": f"steady downtrend ({p30:+.1f}% / {p7:+.1f}%)"}
    return {"available": True, "label": "FLAT", "detail": f"no clear trend ({p30:+.1f}% / {p7:+.1f}%)"}


def compute_ecosystem_trend(coin_own_pct_7d: Optional[float], sector_peer_pct_7d: list) -> dict:
    """v3.7 — how is this coin doing relative to its OWN category/sector
    average, using data already gathered for the shortlist this run (see
    workflows/sniper_daily_crypto.py's category-grouping pre-pass) — no
    extra API calls beyond the category lookup itself (which is now
    cached, see data.py's fetch_coin_categories fix). Requires at least
    3 sector peers to compute a meaningful average."""
    if coin_own_pct_7d is None:
        return {"available": False, "label": "NONE"}
    valid_peers = [p for p in sector_peer_pct_7d if p is not None]
    if len(valid_peers) < 3:
        return {"available": False, "label": "NONE", "detail": "insufficient sector peer sample"}

    sector_avg = sum(valid_peers) / len(valid_peers)
    delta = coin_own_pct_7d - sector_avg

    if delta > 10:
        return {"available": True, "label": "ABOVE_SECTOR", "sector_avg_pct_7d": round(sector_avg, 1),
                "detail": f"outperforming its sector average by {delta:+.1f}pp ({coin_own_pct_7d:+.1f}% vs sector {sector_avg:+.1f}%)"}
    if delta < -10:
        return {"available": True, "label": "BELOW_SECTOR", "sector_avg_pct_7d": round(sector_avg, 1),
                "detail": f"underperforming its sector average by {delta:+.1f}pp ({coin_own_pct_7d:+.1f}% vs sector {sector_avg:+.1f}%)"}
    return {"available": True, "label": "IN_LINE_WITH_SECTOR", "sector_avg_pct_7d": round(sector_avg, 1),
            "detail": f"roughly tracking its sector average ({coin_own_pct_7d:+.1f}% vs sector {sector_avg:+.1f}%)"}
    """Reuses the cached OHLC fetch (v3.3) — costs zero additional API
    calls if velocity already fetched this coin's history this run.
    Checks today's close against the prior 20-day high, EXCLUDING today
    (so a coin can't 'break out' against its own current price)."""
    try:
        hist = cdata.fetch_daily_ohlc(coin_id, days=30)
    except Exception as e:
        log.debug(f"breakout check OHLC fetch failed for {coin_id}: {e}")
        return {"available": False, "label": "NONE"}

    if hist is None or hist.empty or len(hist) < 21:
        return {"available": False, "label": "NONE"}

    close_today = float(hist["close"].iloc[-1])
    prior_20d_high = float(hist["high"].iloc[-21:-1].max())

    if prior_20d_high <= 0:
        return {"available": False, "label": "NONE"}

    if close_today > prior_20d_high:
        pct_above = round(100.0 * (close_today - prior_20d_high) / prior_20d_high, 2)
        return {"available": True, "label": "BREAKOUT", "pct_above_20d_high": pct_above,
                "detail": f"closed {pct_above:+.1f}% above its prior 20-day high"}
    return {"available": True, "label": "NO_BREAKOUT", "pct_above_20d_high": None,
            "detail": "trading within its recent 20-day range"}
