"""
FORTRESS_UNIFIED — core/bridge.py
══════════════════════════════════════════════════════════════════════════════
THE BRIDGE. This is the module that didn't exist in any of the three
original products — it's the reason "hybrid sync" is more than just shared
plumbing.

Flow:
  1. Incubator (weekly) finds a pearl -> upsert_pearl() writes it to the
     `pearl_watchlist` table with its thesis, box levels, and grade.
  2. Sniper (daily) starts each run by calling load_active_watchlist() and
     scores EVERY watchlist symbol through its full deep pipeline
     regardless of whether it appears in that day's bhavcopy top-N —
     a pearl doesn't need to be liquid-ranked to deserve daily attention.
  3. For each watchlist symbol, check_ignition() looks for the technical
     signature that says "this pearl is moving now": box breakout + volume
     surge + (optional) 50MA reclaim.
  4. apply_pedigree_bonus() adds points to that symbol's fused score IF it
     has pedigree (on the watchlist) and/or shows ignition — so a pearl
     that ignites naturally outranks an equal-scoring cold-scan hit.
  5. If ignition fires, mark_ignited() flips its status so it isn't
     endlessly re-alerted, and Pine sync export includes it as a priority
     level set.

Also home to the ONE unified 0-100 conviction score described in the plan:
   conviction = thesis(30) + trigger(40) + macro(20) + entry(10)
This replaces Sniper's fort_pts/apex_comp/fused/bayes_pct/confidence_score
and Incubator's math_score/total_score as the number that actually drives
sizing and alerting. The legacy per-system scores are still computed and
stored (useful for the meta-labeler's feature vector) but conviction_score
is the one number a human should look at.
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from . import config
from .db import get_conn
from .indicators import compute_indicators

log = logging.getLogger("fortress.bridge")


# ══════════════════════════════════════════════════════════════════════════
# WRITER SIDE — called from Incubator after a stone clears all gates
# ══════════════════════════════════════════════════════════════════════════

def upsert_pearl(symbol: str, thesis: str, g1: dict, incubator_score: float,
                  pearl_grade: str, sector: str, quality_flags: str,
                  sharia_compliant: bool) -> None:
    """Write/refresh a pearl on the watchlist. Called once per Incubator
    survivor per weekly run. `last_confirmed` resets the staleness clock —
    a pearl Incubator keeps re-finding stays fresh indefinitely."""
    today = datetime.today().strftime("%Y-%m-%d")
    sym = symbol.upper()
    try:
        with get_conn(write=True) as con:
            existing = con.execute(
                "SELECT added_date FROM pearl_watchlist WHERE symbol = ?", (sym,)
            ).fetchone()
            added_date = existing[0] if existing else today
            con.execute("""
                INSERT INTO pearl_watchlist
                    (symbol, added_date, last_confirmed, thesis, box_high, box_low,
                     high_52w, low_52w, ma200, incubator_score, pearl_grade, sector,
                     quality_flags, sharia_compliant, status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'ACTIVE')
                ON CONFLICT(symbol) DO UPDATE SET
                    last_confirmed=excluded.last_confirmed,
                    thesis=excluded.thesis,
                    box_high=excluded.box_high, box_low=excluded.box_low,
                    high_52w=excluded.high_52w, low_52w=excluded.low_52w,
                    ma200=excluded.ma200, incubator_score=excluded.incubator_score,
                    pearl_grade=excluded.pearl_grade, sector=excluded.sector,
                    quality_flags=excluded.quality_flags,
                    sharia_compliant=excluded.sharia_compliant,
                    status = CASE WHEN pearl_watchlist.status = 'IGNITED'
                                  THEN pearl_watchlist.status ELSE 'ACTIVE' END
            """, (sym, added_date, today, thesis,
                  g1.get("box_width_pct", 0), g1.get("low_52w", 0),
                  g1.get("high_52w", 0), g1.get("low_52w", 0),
                  g1.get("ma200", 0), incubator_score, pearl_grade, sector,
                  quality_flags, int(sharia_compliant)))
        log.info(f"Pearl watchlist: upserted {sym} ({pearl_grade}, score={incubator_score})")
    except Exception as e:
        log.warning(f"upsert_pearl {sym}: {e}")


def expire_stale_pearls() -> int:
    """Drop pearls Incubator hasn't re-confirmed within TTL. Run at the
    start of each Incubator weekly cycle. Returns count expired."""
    cutoff = (datetime.today() - timedelta(days=config.PEARL_WATCHLIST_TTL_DAYS)).strftime("%Y-%m-%d")
    try:
        with get_conn(write=True) as con:
            cur = con.execute(
                "UPDATE pearl_watchlist SET status='STALE' "
                "WHERE status='ACTIVE' AND last_confirmed < ?", (cutoff,)
            )
            return cur.rowcount
    except Exception as e:
        log.warning(f"expire_stale_pearls: {e}")
        return 0


# ══════════════════════════════════════════════════════════════════════════
# READER SIDE — called from Sniper at the start of each daily run
# ══════════════════════════════════════════════════════════════════════════

def load_active_watchlist() -> List[dict]:
    """Every ACTIVE or already-IGNITED pearl. Sniper scores all of these
    through the full deep pipeline every day, independent of bhavcopy
    liquidity ranking."""
    try:
        with get_conn() as con:
            con.row_factory = None
            cols = ["symbol", "added_date", "last_confirmed", "thesis", "box_high",
                    "box_low", "high_52w", "low_52w", "ma200", "incubator_score",
                    "pearl_grade", "sector", "quality_flags", "sharia_compliant",
                    "status", "ignited_date", "ignited_price"]
            rows = con.execute(
                f"SELECT {', '.join(cols)} FROM pearl_watchlist "
                "WHERE status IN ('ACTIVE', 'IGNITED')"
            ).fetchall()
            return [dict(zip(cols, r)) for r in rows]
    except Exception as e:
        log.warning(f"load_active_watchlist: {e}")
        return []


def mark_ignited(symbol: str, price: float) -> None:
    today = datetime.today().strftime("%Y-%m-%d")
    try:
        with get_conn(write=True) as con:
            con.execute(
                "UPDATE pearl_watchlist SET status='IGNITED', ignited_date=?, "
                "ignited_price=? WHERE symbol=?",
                (today, price, symbol.upper()),
            )
        log.info(f"🔥 IGNITION: {symbol} marked ignited at ₹{price:.2f}")
    except Exception as e:
        log.warning(f"mark_ignited {symbol}: {e}")


# ══════════════════════════════════════════════════════════════════════════
# IGNITION DETECTION
# ══════════════════════════════════════════════════════════════════════════

def check_ignition(pearl: dict, hist: pd.DataFrame) -> Dict:
    """
    The technical signature that says "this pearl is moving now":
      1. Close breaks above its consolidation box high by IGNITION_BOX_BREAKOUT_PCT
      2. Volume >= IGNITION_VOL_MULT x 20-day average volume
      3. (optional, on by default) Close reclaims the 50-day MA

    box_high here is the pearl's own recent 20-bar box (from indicators),
    NOT the stale box_high captured when Incubator first found it weeks
    ago — the market moves between weekly Incubator runs, so ignition must
    be judged against current structure.
    """
    result = {"ignited": False, "reason": "", "box_high": 0.0, "vol_ratio": 0.0}
    if hist.empty or len(hist) < 25:
        result["reason"] = "insufficient history"
        return result

    ind = compute_indicators(hist)
    close = float(hist["close"].iloc[-1])
    box_high = ind.get("box_high_20", 0.0)
    adv20 = float(hist["volume"].tail(20).mean()) if "volume" in hist.columns else 0.0
    vol_today = float(hist["volume"].iloc[-1]) if "volume" in hist.columns else 0.0
    vol_ratio = (vol_today / adv20) if adv20 > 0 else 0.0

    breakout = box_high > 0 and close > box_high * (1.0 + config.IGNITION_BOX_BREAKOUT_PCT)
    vol_ok = vol_ratio >= config.IGNITION_VOL_MULT
    ma50_ok = True
    if config.IGNITION_MA50_RECLAIM:
        ma50 = ind.get("ma50", 0.0)
        ma50_ok = ma50 <= 0 or close > ma50   # if MA50 unavailable, don't block

    result["box_high"] = box_high
    result["vol_ratio"] = round(vol_ratio, 2)

    if breakout and vol_ok and ma50_ok:
        result["ignited"] = True
        result["reason"] = (f"box breakout {close:.2f} > {box_high:.2f}*"
                            f"{1+config.IGNITION_BOX_BREAKOUT_PCT:.2f} | "
                            f"vol {vol_ratio:.1f}x | MA50 {'✓' if ma50_ok else 'n/a'}")
    else:
        missing = []
        if not breakout:
            missing.append("no box breakout")
        if not vol_ok:
            missing.append(f"vol {vol_ratio:.1f}x < {config.IGNITION_VOL_MULT}x")
        if not ma50_ok:
            missing.append("below MA50")
        result["reason"] = " | ".join(missing)

    return result


def apply_pedigree_bonus(fused_score: float, is_pearl: bool, ignited: bool) -> float:
    """
    Add pedigree/ignition bonus to a raw fused score. Capped additively at
    PEARL_PEDIGREE_BONUS + PEARL_IGNITION_BONUS so a stale pearl with no
    ignition can't out-rank a strong cold-scan signal on pedigree alone —
    it only gets the smaller pedigree component, not the full bonus.
    """
    bonus = 0.0
    if is_pearl:
        bonus += config.PEARL_PEDIGREE_BONUS
    if ignited:
        bonus += config.PEARL_IGNITION_BONUS
    return round(min(100.0, fused_score + bonus), 1)


# ══════════════════════════════════════════════════════════════════════════
# UNIFIED CONVICTION SCALE (0-100)
# ══════════════════════════════════════════════════════════════════════════

def unified_conviction(thesis_score_0_100: float, trigger_score_0_100: float,
                        macro_score_0_100: float, entry_score_0_100: float) -> float:
    """
    conviction = thesis(30) + trigger(40) + macro(20) + entry(10)

    thesis_score  : Incubator's math_score/insider audit, normalised 0-100.
                    For a cold-scan (non-pearl) symbol with no Incubator
                    thesis, pass 50.0 (neutral) — see sniper_bridge helper.
    trigger_score : Sniper's fused score (fort_pts/apex/bayes composite),
                    already 0-100.
    macro_score   : from core.macro.macro_subscore_0_100().
    entry_score   : Pine-side entry-context score (limit-zone validity,
                    fog state, trail status) — 100 if no Pine context
                    available (i.e. scoring happens before Pine ever sees it).
    """
    w = config
    total = (thesis_score_0_100 * w.CONVICTION_W_THESIS +
             trigger_score_0_100 * w.CONVICTION_W_TRIGGER +
             macro_score_0_100 * w.CONVICTION_W_MACRO +
             entry_score_0_100 * w.CONVICTION_W_ENTRY) / 100.0
    return round(max(0.0, min(100.0, total)), 1)
