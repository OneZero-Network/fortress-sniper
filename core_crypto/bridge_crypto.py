"""
FORTRESS_CRYPTO — core/crypto/bridge_crypto.py
══════════════════════════════════════════════════════════════════════════════
Crypto analogue of core/bridge.py. Same Incubator-writes / Sniper-reads
pattern, against crypto_pearl_watchlist instead of pearl_watchlist. Ignition
detection reuses core/indicators.py:compute_indicators() unchanged (it's
already generic OHLCV) but with crypto-tuned thresholds from
core/crypto/config.py (wider breakout %, higher volume multiple — crypto's
noise floor is higher than NSE mid-caps).
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta
from typing import Dict, List

import pandas as pd

from ..db import get_conn
from ..indicators import compute_indicators
from . import config as ccfg

log = logging.getLogger("fortress.crypto.bridge")


def upsert_pearl(symbol: str, coin_id: str, thesis: str, box_high: float, box_low: float,
                  ath: float, ath_change_pct: float, incubator_score: float,
                  pearl_grade: str, category_tags: str, onchain_flags: str,
                  sharia_compliant: bool) -> None:
    today = datetime.today().strftime("%Y-%m-%d")
    sym = symbol.upper()
    try:
        with get_conn(write=True) as con:
            existing = con.execute(
                "SELECT added_date FROM crypto_pearl_watchlist WHERE symbol = ?", (sym,)
            ).fetchone()
            added_date = existing[0] if existing else today
            con.execute("""
                INSERT INTO crypto_pearl_watchlist
                    (symbol, coin_id, added_date, last_confirmed, thesis, box_high, box_low,
                     ath, ath_change_pct, incubator_score, pearl_grade, category_tags,
                     onchain_flags, sharia_compliant, status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'ACTIVE')
                ON CONFLICT(symbol) DO UPDATE SET
                    coin_id=excluded.coin_id,
                    last_confirmed=excluded.last_confirmed,
                    thesis=excluded.thesis,
                    box_high=excluded.box_high, box_low=excluded.box_low,
                    ath=excluded.ath, ath_change_pct=excluded.ath_change_pct,
                    incubator_score=excluded.incubator_score, pearl_grade=excluded.pearl_grade,
                    category_tags=excluded.category_tags, onchain_flags=excluded.onchain_flags,
                    sharia_compliant=excluded.sharia_compliant,
                    status = CASE WHEN crypto_pearl_watchlist.status = 'IGNITED'
                                  THEN crypto_pearl_watchlist.status ELSE 'ACTIVE' END
            """, (sym, coin_id, added_date, today, thesis, box_high, box_low,
                  ath, ath_change_pct, incubator_score, pearl_grade, category_tags,
                  onchain_flags, int(sharia_compliant)))
        log.info(f"Crypto pearl watchlist: upserted {sym} ({pearl_grade}, score={incubator_score})")
    except Exception as e:
        log.warning(f"upsert_pearl {sym}: {e}")


def expire_stale_pearls() -> int:
    cutoff = (datetime.today() - timedelta(days=ccfg.PEARL_WATCHLIST_TTL_DAYS)).strftime("%Y-%m-%d")
    try:
        with get_conn(write=True) as con:
            cur = con.execute(
                "UPDATE crypto_pearl_watchlist SET status='STALE' "
                "WHERE status='ACTIVE' AND last_confirmed < ?", (cutoff,)
            )
            return cur.rowcount
    except Exception as e:
        log.warning(f"expire_stale_pearls: {e}")
        return 0


def load_active_watchlist() -> List[dict]:
    try:
        with get_conn() as con:
            cols = ["symbol", "coin_id", "added_date", "last_confirmed", "thesis",
                    "box_high", "box_low", "ath", "ath_change_pct", "incubator_score",
                    "pearl_grade", "category_tags", "onchain_flags", "sharia_compliant",
                    "status", "ignited_date", "ignited_price"]
            rows = con.execute(
                f"SELECT {', '.join(cols)} FROM crypto_pearl_watchlist "
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
                "UPDATE crypto_pearl_watchlist SET status='IGNITED', ignited_date=?, "
                "ignited_price=? WHERE symbol=?",
                (today, price, symbol.upper()),
            )
        log.info(f"🔥 CRYPTO IGNITION: {symbol} marked ignited at ${price:,.4f}")
    except Exception as e:
        log.warning(f"mark_ignited {symbol}: {e}")


def check_ignition(pearl: dict, hist: pd.DataFrame) -> Dict:
    """Same box-breakout + volume-surge + MA50-reclaim signature as equity,
    crypto-tuned thresholds (wider breakout %, higher volume multiple)."""
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

    breakout = box_high > 0 and close > box_high * (1.0 + ccfg.IGNITION_BOX_BREAKOUT_PCT)
    vol_ok = vol_ratio >= ccfg.IGNITION_VOL_MULT
    ma50_ok = True
    if ccfg.IGNITION_MA50_RECLAIM:
        ma50 = ind.get("ma50", 0.0)
        ma50_ok = ma50 <= 0 or close > ma50

    result["box_high"] = box_high
    result["vol_ratio"] = round(vol_ratio, 2)

    if breakout and vol_ok and ma50_ok:
        result["ignited"] = True
        result["reason"] = (f"box breakout {close:.4f} > {box_high:.4f}*"
                            f"{1+ccfg.IGNITION_BOX_BREAKOUT_PCT:.3f} | "
                            f"vol {vol_ratio:.1f}x | MA50 {'✓' if ma50_ok else 'n/a'}")
    else:
        missing = []
        if not breakout:
            missing.append("no box breakout")
        if not vol_ok:
            missing.append(f"vol {vol_ratio:.1f}x < {ccfg.IGNITION_VOL_MULT}x")
        if not ma50_ok:
            missing.append("below MA50")
        result["reason"] = " | ".join(missing)

    return result


def apply_pedigree_bonus(fused_score: float, is_pearl: bool, ignited: bool) -> float:
    bonus = 0.0
    if is_pearl:
        bonus += ccfg.PEARL_PEDIGREE_BONUS
    if ignited:
        bonus += ccfg.PEARL_IGNITION_BONUS
    return round(min(100.0, fused_score + bonus), 1)


def unified_conviction(thesis_score_0_100: float, trigger_score_0_100: float,
                        macro_score_0_100: float, entry_score_0_100: float) -> float:
    total = (thesis_score_0_100 * ccfg.CONVICTION_W_THESIS +
             trigger_score_0_100 * ccfg.CONVICTION_W_TRIGGER +
             macro_score_0_100 * ccfg.CONVICTION_W_MACRO +
             entry_score_0_100 * ccfg.CONVICTION_W_ENTRY) / 100.0
    return round(max(0.0, min(100.0, total)), 1)
