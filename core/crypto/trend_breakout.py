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


def detect_breakout(coin_id: str) -> dict:
    """Reuses the cached OHLC fetch (v3.3) — costs zero additional API
    calls if velocity already fetched this coin's history this run.
    Checks today's close against the prior 20-day high, EXCLUDING today
    (so a coin can't 'break out' against its own current price).

    v3.9.1 HOTFIX: this function's 'def' line was accidentally deleted
    during a v3.7 edit that inserted compute_ecosystem_trend() above it —
    the function body survived as orphaned dead code with no header,
    meaning every call to trend_breakout.detect_breakout() raised
    AttributeError (function doesn't exist), silently caught by the
    calling code's try/except and defaulted to label='NONE' every time.
    That is the CONFIRMED root cause of breakout showing +0.0 for every
    single Top-5 candidate across at least two production runs — not a
    market-conditions coincidence, a real bug. Restored here, along with
    ALWAYS-computed distance-to-high/low (requested explicitly, even
    when no breakout fires) and a volume-persistence check.
    """
    try:
        hist = cdata.fetch_daily_ohlc(coin_id, days=30)
    except Exception as e:
        log.debug(f"breakout check OHLC fetch failed for {coin_id}: {e}")
        return {"available": False, "label": "NONE"}

    if hist is None or hist.empty or len(hist) < 21:
        return {"available": False, "label": "NONE"}

    close_today = float(hist["close"].iloc[-1])
    prior_20d_high = float(hist["high"].iloc[-21:-1].max())
    prior_20d_low = float(hist["low"].iloc[-21:-1].min())

    if prior_20d_high <= 0:
        return {"available": False, "label": "NONE"}

    # ALWAYS computed now, not just when a breakout fires — per explicit
    # request: "even if the current breakout score is zero, explicitly
    # report distance from recent high/low."
    dist_from_high_pct = round(100.0 * (close_today - prior_20d_high) / prior_20d_high, 2)
    dist_from_low_pct = round(100.0 * (close_today - prior_20d_low) / prior_20d_low, 2)

    # Volume persistence: is today's elevated volume the FIRST elevated
    # day, or has it been elevated for several consecutive days already?
    # This distinguishes a fresh spike from an established, multi-day move.
    volume = hist["volume"].astype(float)
    avg_vol_30d = volume.iloc[:-1].mean() if len(volume) > 1 else None
    consecutive_elevated_days = 0
    if avg_vol_30d and avg_vol_30d > 0:
        for v in reversed(volume.tolist()):
            if v > avg_vol_30d * 1.5:
                consecutive_elevated_days += 1
            else:
                break

    result = {
        "available": True,
        "current_price": close_today,
        "prior_20d_high_raw": prior_20d_high,
        "prior_20d_low_raw": prior_20d_low,
        "diff_from_high_usd": round(close_today - prior_20d_high, 8),
        "dist_from_20d_high_pct": dist_from_high_pct,
        "dist_from_20d_low_pct": dist_from_low_pct,
        "consecutive_elevated_volume_days": consecutive_elevated_days,
        "ohlc_rows_used": len(hist),
    }

    if close_today > prior_20d_high:
        result.update({"label": "BREAKOUT", "pct_above_20d_high": dist_from_high_pct,
                        "detail": f"closed {dist_from_high_pct:+.1f}% above its prior 20-day high"})
    else:
        result.update({"label": "NO_BREAKOUT", "pct_above_20d_high": None,
                        "detail": (f"trading within its recent 20-day range "
                                    f"({dist_from_high_pct:+.1f}% from the high, {dist_from_low_pct:+.1f}% from the low"
                                    f"{f', volume elevated {consecutive_elevated_days}d running' if consecutive_elevated_days >= 2 else ''})")})
    return result
