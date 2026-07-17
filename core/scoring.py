"""
FORTRESS_UNIFIED — core/scoring.py
══════════════════════════════════════════════════════════════════════════════
The Sniper-side scoring math (Fortress 200-pt, APEX composite, Bayesian win
probability, confidence score), extracted so both Sniper and the ignition
detector can call the same functions. Logic preserved from sniper_v7/v8.2
with the v8.2 base_forming fix intact (VCP/VDU no longer halved for
base-forming setups — that was making the gate mathematically impossible).
"""
from __future__ import annotations
import logging
from typing import Dict, Tuple

import numpy as np
import pandas as pd

from . import config
from .indicators import compute_indicators

log = logging.getLogger("fortress.scoring")

UPTREND_MA_SLACK = 0.02
SECTOR_ATR_MULT = {"IT": 1.0, "PHARMA": 1.1, "BANKING": 0.9, "FMCG": 0.9,
                    "METAL": 1.3, "REALTY": 1.4, "AUTO": 1.1}


def check_uptrend_gate(close: float, ind: dict) -> Tuple[bool, str]:
    """Softened accumulation gate. FULL_UPTREND / BASE_FORMING both pass;
    only DOWNTREND hard-rejects. base_forming is informational, not
    penalised (v8.2 fix — the //2 penalty made VCP gates unreachable)."""
    ma50, ma200 = ind.get("ma50", 0.0), ind.get("ma200", 0.0)
    if ma50 <= 0:
        return True, "base_forming (ma50 unavailable)"
    if close <= ma50:
        return False, f"price {close:.0f} <= 50MA {ma50:.0f} — downtrend"
    if ma200 > 0 and ma50 >= ma200 * (1.0 - UPTREND_MA_SLACK):
        return True, "uptrend"
    tier = f"50MA {ma50:.0f} below 200MA {ma200:.0f}" if ma200 > 0 else "< 200 bars"
    return True, f"base_forming ({tier})"


def atr_dynamic_stop(close: float, atr14: float, sector: str, atr_mult: float) -> float:
    if atr14 <= 0:
        atr14 = close * 0.02
    sect_mult = SECTOR_ATR_MULT.get(sector.upper(), 1.0)
    stop = close - atr14 * atr_mult * sect_mult
    return round(max(stop, close * 0.85), 2)


def atr_position_size(equity: float, risk_pct: float, entry: float, stop: float) -> int:
    risk_amt = equity * risk_pct
    risk_per_share = entry - stop
    if risk_per_share <= 0:
        return 0
    return max(1, int(risk_amt / risk_per_share))


def fortress_score(symbol: str, close: float, hist: pd.DataFrame, sector: str,
                    macro: dict, order_flow: dict, fii_score: float = 15,
                    insider_bonus: dict = None, filing_bonus: dict = None) -> dict:
    """200-pt Fortress score. Returns {} if close <= 0."""
    if close <= 0:
        return {}
    ind = compute_indicators(hist)
    atr14, atr100 = ind["atr14"], ind["atr100"]
    natr14 = ind.get("natr14", atr14 / close if close > 0 else 0)
    natr100 = ind.get("natr100", atr100 / close if close > 0 else natr14)
    atr_mult = macro.get("atr_mult", config.ATR_MULT_CHOP)

    fort_pts = 0
    story_parts = []

    uptrend_ok, uptrend_reason = check_uptrend_gate(close, ind)
    if uptrend_ok:
        story_parts.append(uptrend_reason.split(" (")[0])

    hi52, lo52 = ind["hi52"], ind["lo52"]
    if hi52 > 0:
        pct_from_h = (hi52 - close) / hi52 * 100
        atr_tight = natr14 > 0 and natr100 > 0 and (natr14 / natr100) < 0.70
        w52 = (20 if atr_tight else 15) if pct_from_h <= 5 else \
              (12 if atr_tight else 8) if pct_from_h <= 10 else \
              (6 if pct_from_h <= 20 else 0)
        fort_pts += w52
        if w52 >= 12:
            story_parts.append(f"52W compression: {pct_from_h:.1f}% from high")

    vcp_score = 0
    if uptrend_ok and natr14 > 0 and natr100 > 0:
        ratio = natr14 / natr100
        vcp_score = 20 if ratio < 0.60 else 14 if ratio < 0.70 else 8 if ratio < 0.80 else 0
        if vcp_score:
            story_parts.append(f"VCP coil NATR={ratio:.2f}")
    fort_pts += vcp_score

    atrv = 0
    if ind["atr7"] > 0 and ind["atr50"] > 0:
        rate = (ind["atr7"] - ind["atr50"]) / ind["atr50"]
        atrv = 15 if rate > 0.50 else 10 if rate > 0.30 else 5 if rate > 0.10 else \
               (2 if ind["atr7"] < ind["atr50"] else 0)
    fort_pts += atrv

    vdu_score = 0
    if uptrend_ok and not hist.empty and len(hist) >= 20:
        recent_vol = float(hist["volume"].tail(5).mean())
        base_vol = float(hist["volume"].iloc[-21:-1].mean())
        if base_vol > 0:
            vdu_r = recent_vol / base_vol
            vdu_score = 15 if vdu_r < 0.40 else 10 if vdu_r < 0.60 else 5 if vdu_r < 0.80 else 0
    fort_pts += vdu_score

    fii_bonus = min(20, max(0, (int(fii_score) - 10) // 2))
    fort_pts += fii_bonus

    ins_bonus = 0
    if insider_bonus and insider_bonus.get("count", 0) > 0:
        ins_bonus = min(15, int(insider_bonus.get("total_cr", 0) * 2 + insider_bonus.get("count", 0) * 3))
        story_parts.append(f"Insider ₹{insider_bonus.get('total_cr',0):.0f}Cr")
    fort_pts += ins_bonus

    fil_bonus = 0
    if filing_bonus:
        if filing_bonus.get("score", 15) >= 20:
            fil_bonus = 15
        elif filing_bonus.get("score", 15) <= 8:
            fil_bonus = -10
    fort_pts += fil_bonus

    whale_score = float(order_flow.get("whale_score", 0))
    fort_pts += int(whale_score)

    vpoc = float(order_flow.get("vpoc", 0))
    vol_ratio = float(order_flow.get("vol_ratio", 1.0))
    at_vpoc = bool(order_flow.get("at_vpoc_support", False))
    vpoc_pts = 0
    if vpoc > 0 and close > 0:
        pct_from_vpoc = abs(close - vpoc) / close
        if at_vpoc:
            vpoc_pts += 25
        elif pct_from_vpoc < 0.05:
            vpoc_pts += 12
        if vol_ratio >= 2.0 and pct_from_vpoc < 0.05:
            vpoc_pts += 20
        elif vol_ratio >= 1.5 and pct_from_vpoc < 0.05:
            vpoc_pts += 10
        if at_vpoc and uptrend_ok and order_flow.get("whale_flag"):
            vpoc_pts += 15
        elif at_vpoc and uptrend_ok:
            vpoc_pts += 8
    fort_pts += min(vpoc_pts, 60)

    rsi14, adx14 = ind["rsi14"], ind["adx14"]
    if 50 <= rsi14 <= 70:
        fort_pts += 8
    elif rsi14 > 70:
        fort_pts += 4
    if adx14 >= 25:
        fort_pts += 8
    elif adx14 >= 20:
        fort_pts += 4

    stop_loss = atr_dynamic_stop(close, atr14, sector, atr_mult)
    risk = max(close - stop_loss, close * 0.03)
    shares = atr_position_size(config.ACCOUNT_EQUITY, config.ACCOUNT_RISK_PCT, close, stop_loss)

    fp = fort_pts
    grade = "APEX" if fp >= 160 else "PRISTINE" if fp >= 140 else \
            "GOOD" if fp >= 120 else "PROBE" if fp >= 100 else "WATCHLIST"

    return {
        "symbol": symbol.upper(), "sector": sector, "fort_pts": fort_pts, "grade": grade,
        "close": close, "stop_loss": stop_loss,
        "r1": round(close + risk * 1.5, 2), "r2": round(close + risk * 3.0, 2),
        "r3": round(close + risk * 5.0, 2), "shares": shares,
        "rsi14": rsi14, "adx14": adx14, "mfi": ind["mfi"], "atr14": round(atr14, 2),
        "natr14": ind["natr14"], "natr100": ind["natr100"],
        "whale_score": whale_score, "vol_ratio": vol_ratio, "at_vpoc": at_vpoc,
        "hi52": hi52, "lo52": lo52,
        "delivery_pct": float(order_flow.get("delivery_pct", -1.0)),
        "whale_available": bool(order_flow.get("whale_available", False)),
        "story": " | ".join(story_parts) if story_parts else f"Fortress {fort_pts}pts",
        "uptrend_ok": uptrend_ok, "uptrend_reason": uptrend_reason,
        "ma50": ind["ma50"], "ma200": ind["ma200"],
    }


def apex_composite(fortress: dict, macro: dict) -> dict:
    if not fortress or fortress.get("close", 0) <= 0:
        return {"apex_comp": 0.0}
    rsi, adx, mfi = fortress.get("rsi14", 50), fortress.get("adx14", 0), fortress.get("mfi", 50)
    ws, state, fp = fortress.get("whale_score", 0), macro.get("macro_state", "CHOP"), fortress.get("fort_pts", 0)

    scores = []
    mom = 20 if 45 <= rsi <= 65 else 12 if (35 <= rsi < 45 or 65 < rsi <= 72) else 6 if rsi > 72 else 0
    mom = min(20, mom + (8 if adx >= 25 else 4 if adx >= 18 else 0))
    scores.append(("momentum", mom, 20))

    vol_s = 15 if 40 <= mfi <= 65 else 10 if mfi < 40 else 0
    vol_s = min(20, vol_s + (5 if ws >= 20 else 0))
    scores.append(("volume", vol_s, 20))

    reg_s = {"TREND": 20, "CHOP": 12, "BUNKER": 6, "PANIC": 0, "MASSACRE": 0}.get(state, 10)
    if state == "TREND" and fp < 120:
        reg_s = 12
    scores.append(("regime", reg_s, 20))

    raw = sum(s for _, s, _ in scores)
    max_pts = sum(m for _, _, m in scores)
    apex = round(min(100, raw / max_pts * 100), 1) if max_pts > 0 else 0.0
    if state == "TREND" and adx >= 20:
        apex = round(min(100, apex * 1.08), 1)
    return {"apex_comp": apex}


def fused_score(fortress: dict, apex: dict, bayes_pct: float) -> float:
    fp_n = min(fortress.get("fort_pts", 0) / 200, 1.0) * 100
    apex_n = apex.get("apex_comp", 0)
    return round((fp_n * 0.4 + apex_n * 0.35 + bayes_pct * 0.25), 1)


def compute_confidence_score(fort_pts: float, apex_comp: float, bayes_pct: float,
                              whale_score: float, rsi14: float, adx14: float,
                              whale_available: bool = True) -> float:
    """Signal-agreement confidence. TWO FIXES from the first live run:
    1. whale_n is only included when whale data actually exists — the
       dummy stub's hardwired 0 inflated the std and zeroed EVERY
       candidate's confidence ("Cold scan: 0 passed all gates").
    2. The disagreement penalty is floored at CONFIDENCE_PENALTY_FLOOR so
       divergent-but-strong signal sets are dampened, never annihilated."""
    fort_n = min(fort_pts / 200, 1.0)
    apex_n = min(apex_comp / 100, 1.0)
    bayes_n = min(bayes_pct / 100, 1.0)
    rsi_n = 1.0 if 45 <= rsi14 <= 65 else 0.7 if (35 <= rsi14 < 45 or 65 < rsi14 <= 72) else \
            0.2 if rsi14 > 80 else 0.5
    adx_n = min(adx14 / 40, 1.0)
    sig = [fort_n, apex_n, bayes_n, rsi_n, adx_n]
    if whale_available:
        sig.append(min(whale_score / 30, 1.0))
    signals = np.array(sig)
    mean_s, std_s = float(signals.mean()), float(signals.std())
    penalty = max(config.CONFIDENCE_PENALTY_FLOOR, 1.0 - std_s / config.CONFIDENCE_STD_MAX)
    conf = mean_s * penalty
    return round(min(max(conf, 0.0), 1.0), 4)
