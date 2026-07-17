"""
FORTRESS_UNIFIED — core/macro.py
══════════════════════════════════════════════════════════════════════════════
Single macro-regime detector (VIX + NIFTY + breadth), shared so Sniper,
Incubator, and the unified conviction score all agree on what "the market"
is doing right now instead of each computing it slightly differently.
"""
from __future__ import annotations
import logging
from typing import Optional

from . import config
from .nse_data import get_nse_session, NSE_HEADERS
from .db import get_conn

log = logging.getLogger("fortress.macro")

FALLBACK_CHOP = {
    "macro_state": "CHOP", "vix_val": 18.0, "nifty_chg": 0.0,
    "breadth_ok": True, "atr_mult": config.ATR_MULT_CHOP,
    "advance_ratio": 0.5, "source": "FALLBACK",
}


def _load_cached_macro() -> Optional[dict]:
    try:
        with get_conn() as con:
            con.execute("CREATE TABLE IF NOT EXISTS macro_cache "
                        "(id INTEGER PRIMARY KEY CHECK (id=1), macro_state TEXT, "
                        "vix_val REAL, nifty_chg REAL, breadth_ok INTEGER, "
                        "advance_ratio REAL, ts TEXT)")
            row = con.execute("SELECT macro_state, vix_val, nifty_chg, breadth_ok, "
                               "advance_ratio FROM macro_cache WHERE id=1").fetchone()
            if row:
                return {"macro_state": row[0], "vix_val": row[1], "nifty_chg": row[2],
                        "breadth_ok": bool(row[3]), "advance_ratio": row[4]}
    except Exception as e:
        log.debug(f"_load_cached_macro: {e}")
    return None


def _save_macro_cache(macro: dict) -> None:
    try:
        with get_conn(write=True) as con:
            con.execute("CREATE TABLE IF NOT EXISTS macro_cache "
                        "(id INTEGER PRIMARY KEY CHECK (id=1), macro_state TEXT, "
                        "vix_val REAL, nifty_chg REAL, breadth_ok INTEGER, "
                        "advance_ratio REAL, ts TEXT)")
            con.execute("INSERT OR REPLACE INTO macro_cache VALUES (1,?,?,?,?,?,datetime('now'))",
                        (macro["macro_state"], macro["vix_val"], macro["nifty_chg"],
                         int(macro["breadth_ok"]), macro["advance_ratio"]))
    except Exception as e:
        log.debug(f"_save_macro_cache: {e}")


def fetch_macro_regime() -> dict:
    """NSE-native macro regime: VIX + NIFTY chg + breadth. Falls back to
    cached/fallback CHOP on any failure — this is a shared read-only signal,
    not a compliance gate, so fail-safe here means 'assume caution', not
    'reject everything'."""
    try:
        sess = get_nse_session()
        hdrs = {**NSE_HEADERS, "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest"}

        resp = sess.get("https://www.nseindia.com/api/allIndices", headers=hdrs, timeout=12)
        if resp.status_code != 200:
            raise ValueError(f"allIndices HTTP {resp.status_code}")

        indices = resp.json().get("data", [])
        vix_val, nifty_chg = 18.0, 0.0
        for idx in indices:
            name = str(idx.get("index", "") or idx.get("indexSymbol", "")).upper()
            if "INDIA VIX" in name or name == "INDIAVIX":
                vix_val = float(idx.get("last", idx.get("lastPrice", 18.0)))
            if name in ("NIFTY 50", "NIFTY50"):
                nifty_chg = float(idx.get("percentChange", idx.get("pChange", 0.0)))

        advance_ratio, breadth_ok = 0.5, True
        try:
            resp2 = sess.get("https://www.nseindia.com/api/advance-decline", headers=hdrs, timeout=10)
            if resp2.status_code == 200:
                ad = resp2.json()
                adv = float(ad.get("advances", ad.get("advance", 0)))
                dec = float(ad.get("declines", ad.get("decline", 1)))
                total = adv + dec
                advance_ratio = adv / total if total > 0 else 0.5
                breadth_ok = advance_ratio >= 0.5
        except Exception as e:
            log.debug(f"advance-decline: {e}")

        if vix_val <= config.VIX_TREND_MAX and breadth_ok:
            state, atr_mult = "TREND", config.ATR_MULT_TREND
        elif vix_val <= config.VIX_CHOP_MAX:
            state, atr_mult = "CHOP", config.ATR_MULT_CHOP
        else:
            state, atr_mult = "BUNKER", config.ATR_MULT_BUNKER

        if vix_val > 30 and nifty_chg < -2.5:
            state, atr_mult = "MASSACRE", config.ATR_MULT_BUNKER * 1.3
        elif vix_val > 25 and nifty_chg < -1.5:
            state, atr_mult = "PANIC", config.ATR_MULT_BUNKER * 1.1

        macro = {"macro_state": state, "vix_val": round(vix_val, 2),
                 "nifty_chg": round(nifty_chg, 2), "breadth_ok": breadth_ok,
                 "atr_mult": atr_mult, "advance_ratio": round(advance_ratio, 3),
                 "source": "NSE_API"}
        _save_macro_cache(macro)
        log.info(f"Macro regime: {state} VIX={vix_val:.1f} NIFTY={nifty_chg:+.2f}% "
                 f"breadth={advance_ratio:.0%}")
        return macro
    except Exception as e:
        log.warning(f"fetch_macro_regime failed ({e}) — using cached/fallback")
        cached = _load_cached_macro()
        if cached:
            cached["atr_mult"] = {"TREND": config.ATR_MULT_TREND, "CHOP": config.ATR_MULT_CHOP,
                                   "BUNKER": config.ATR_MULT_BUNKER}.get(cached["macro_state"],
                                                                          config.ATR_MULT_CHOP)
            cached["source"] = "CACHED"
            return cached
        return FALLBACK_CHOP


def macro_subscore_0_100(macro: dict) -> float:
    """Maps macro state to a 0-100 sub-score for the unified conviction scale."""
    return {"TREND": 100.0, "CHOP": 60.0, "BUNKER": 30.0,
            "PANIC": 10.0, "MASSACRE": 0.0}.get(macro.get("macro_state", "CHOP"), 50.0)
