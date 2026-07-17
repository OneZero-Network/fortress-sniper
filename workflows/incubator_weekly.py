#!/usr/bin/env python3
"""
FORTRESS_UNIFIED — workflows/incubator_weekly.py  (v1.1 — full port)
══════════════════════════════════════════════════════════════════════════════
Fixes from the first live run's crash
(`ValueError: cannot convert float NaN to integer` at the rubble gate):

  1. NaN-SAFE MATH — yfinance history can carry NaN highs/lows; np.max()
     propagates NaN, and `NaN <= 0` is False so the old guard passed it
     straight into int(). Every aggregate is now nanmax/nanmin +
     np.isfinite-guarded, AND fetch_history itself now drops NaN OHLC rows
     at the source.
  2. PER-SYMBOL ISOLATION — one bad symbol logs an EXCEPTION reject row
     (same vocabulary as your legacy REJECTS_LOG) and the run continues.
     A 2,300-symbol weekly run must never die on symbol #7.
  3. REJECTS_LOG restored — every rejection [date, symbol, gate, reason]
     is pushed, so Monday's Claude review analyses THIS system's gates,
     not last year's legacy data.
  4. EPS acceleration + revenue quality gates ported (yfinance quarterly
     statements — GHA-friendly). EPS shrinking = hard reject; missing
     data = pass-with-flag, never punished.
  5. Sector/profile grounding — pearls now carry a real yfinance sector +
     the Shariah L3 audit gets an actual business summary.
"""
from __future__ import annotations
import logging
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import config, preflight_secrets
from core.db import init_db
from core.nse_data import load_bhavcopy, fetch_weekly_history
from core.shariah import full_audit, ticker_veto
from core.fundamentals import eps_acceleration, revenue_quality, get_company_profile
from core.bridge import upsert_pearl, expire_stale_pearls
from core.telegram import send as send_telegram
from core.sheets_client import push_sheet, read_sheet

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                     datefmt="%H:%M:%S")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.ERROR)
log = logging.getLogger("fortress.incubator")


def _nan_safe(x: float, default: float = 0.0) -> float:
    try:
        v = float(x)
        return v if np.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def check_rubble_gate(weekly: pd.DataFrame, close: float) -> Tuple[bool, dict]:
    """NaN-safe rubble gate — the exact function that crashed in prod."""
    details = {"high_52w": 0.0, "low_52w": 0.0, "discount_pct": 0.0,
               "box_weeks": 0, "box_width_pct": 0.0, "ma200": 0.0,
               "score": 0, "reason": ""}
    if weekly.empty or len(weekly) < 20:
        details["reason"] = f"insufficient data: {len(weekly)} weeks"
        return False, details

    high_w = pd.to_numeric(weekly["high"], errors="coerce").values
    low_w = pd.to_numeric(weekly["low"], errors="coerce").values
    close_w = pd.to_numeric(weekly["close"], errors="coerce").values

    high_52w = _nan_safe(np.nanmax(high_w))
    low_52w = _nan_safe(np.nanmin(low_w))
    if high_52w <= 0 or not np.isfinite(close) or close <= 0:
        details["reason"] = "invalid 52W high or close (NaN-guard)"
        return False, details

    discount_pct = (high_52w - close) / high_52w
    if not np.isfinite(discount_pct):
        details["reason"] = "discount NaN (guard)"
        return False, details

    details.update(high_52w=round(high_52w, 2), low_52w=round(low_52w, 2),
                    discount_pct=round(discount_pct * 100, 1))
    if discount_pct < config.RUBBLE_DISCOUNT_MIN:
        details["reason"] = f"only {discount_pct*100:.1f}% below 52W high"
        return False, details
    if low_52w > 0 and close < low_52w * 1.05:
        details["reason"] = "too close to 52W low (falling knife)"
        return False, details

    cs = pd.Series(close_w).dropna()
    ma_period = min(40, len(cs))
    ma200 = _nan_safe(cs.rolling(ma_period).mean().iloc[-1]) if len(cs) >= ma_period else 0.0
    details["ma200"] = round(ma200, 2)

    box_weeks = 0
    for lb in range(min(40, len(close_w)), 3, -1):
        bh = _nan_safe(np.nanmax(high_w[-lb:]))
        bl = _nan_safe(np.nanmin(low_w[-lb:]))
        if bl > 0 and bh > 0 and (bh / bl - 1) <= config.STAGE1_BOX_WIDTH_MAX:
            box_weeks = lb
            break
    details["box_weeks"] = box_weeks
    if box_weeks > 0:
        bw = _nan_safe(np.nanmax(high_w[-box_weeks:])) / max(_nan_safe(np.nanmin(low_w[-box_weeks:]), 1e-9), 1e-9) - 1
        details["box_width_pct"] = round(_nan_safe(bw, 99.0) * 100, 1)
    else:
        details["box_width_pct"] = 99.0

    score = min(30, int(_nan_safe(discount_pct) * 100))
    score += 10 if box_weeks >= 8 else 5 if box_weeks >= 4 else 0
    if details["box_width_pct"] < 25:
        score += 10
    details["score"] = min(50, score)
    details["reason"] = f"Rubble OK {discount_pct*100:.1f}% below high, box={box_weeks}w"
    return True, details


def check_sponge_volume(weekly: pd.DataFrame) -> Tuple[bool, dict]:
    details = {"dry_up_weeks": 0, "sponge_weeks": 0, "score": 0, "reason": ""}
    if weekly.empty or len(weekly) < 10:
        details.update(score=5, reason="insufficient weekly data")
        return True, details
    close_w = pd.to_numeric(weekly["close"], errors="coerce").values
    vol_w = pd.to_numeric(weekly["volume"], errors="coerce").values
    mask = np.isfinite(close_w) & np.isfinite(vol_w)
    close_w, vol_w = close_w[mask], vol_w[mask]
    if len(close_w) < 10:
        details.update(score=5, reason="insufficient finite data")
        return True, details

    lookback = min(20, len(close_w))
    close_r, vol_r = close_w[-lookback:], vol_w[-lookback:]
    avg_vol = _nan_safe(vol_r.mean())
    if avg_vol <= 0:
        details.update(score=5, reason="avg volume = 0")
        return True, details

    red = close_r[1:] < close_r[:-1]
    green = ~red
    dry_ratio = _nan_safe(vol_r[1:][red].mean() / avg_vol, 1.0) if red.any() else 1.0
    dry_up = int((vol_r[1:][red] < avg_vol * config.SPONGE_DRY_VOL_PCT).sum())
    sponge = int((vol_r[1:][green] > avg_vol * config.SPONGE_WET_VOL_PCT).sum())
    details.update(dry_up_weeks=dry_up, sponge_weeks=sponge)

    if dry_ratio > config.SPONGE_DRY_VOL_PCT and sponge == 0:
        details["reason"] = f"no sponge: dry={dry_ratio:.2f} sponge={sponge}w"
        return False, details
    score = (10 if dry_up >= 3 else 5 if dry_up >= 1 else 0) + \
            (20 if sponge >= 2 else 12 if sponge >= 1 else 0) + \
            (5 if dry_ratio < 0.50 else 0)
    details["score"] = score
    details["reason"] = f"Sponge OK dry={dry_up}w sponge={sponge}w"
    return True, details


def score_stone(symbol: str, close: float) -> Dict:
    """Full gate cascade for one symbol. Returns either a survivor dict or
    a reject dict {reject_gate, reject_reason}. Raises nothing critical —
    caller still wraps with try/except for absolute isolation."""
    if close <= 0 or close < config.MIN_PRICE or close > config.MAX_PRICE:
        return {"reject_gate": "PRICE_BAND", "reject_reason": f"close={close}"}
    vetoed, vreason = ticker_veto(symbol)
    if vetoed:
        return {"reject_gate": "TICKER_VETO", "reject_reason": vreason}

    weekly = fetch_weekly_history(symbol, weeks=52)
    if weekly.empty or len(weekly) < 13:
        return {"reject_gate": "NO_WEEKLY_DATA", "reject_reason": f"{len(weekly)}w"}

    g1_ok, g1 = check_rubble_gate(weekly, close)
    if not g1_ok:
        return {"reject_gate": "RUBBLE_FAIL", "reject_reason": g1["reason"]}

    g3_ok, g3 = check_sponge_volume(weekly)
    if not g3_ok:
        return {"reject_gate": "SPONGE_FAIL", "reject_reason": g3["reason"]}

    eps = eps_acceleration(symbol)
    if eps["reject"]:
        return {"reject_gate": "EPS_FAIL",
                "reject_reason": f"shrinking g1={eps['g1']}% g2={eps['g2']}%"}

    rq = revenue_quality(symbol)
    math_score = g1["score"] + g3["score"] + eps["score"] + rq["score"]
    if math_score < config.STONE_SCORE_MIN:
        return {"reject_gate": "SCORE_LOW",
                "reject_reason": f"math={math_score} < {config.STONE_SCORE_MIN}"}

    flags = [f for f in ([eps["flag"]] + rq["flags"]) if f]
    return {"symbol": symbol, "close": close, "math_score": math_score,
            "g1": g1, "g3": g3, "eps": eps, "quality_flags": "|".join(flags)}


def run() -> List[dict]:
    log.info("=" * 70)
    log.info(f"  {config.VERSION} — INCUBATOR WEEKLY (v1.1 full)")
    log.info("=" * 70)
    init_db()
    preflight_secrets()

    expired = expire_stale_pearls()
    log.info(f"Expired {expired} stale pearls (TTL={config.PEARL_WATCHLIST_TTL_DAYS}d)")

    date_label = datetime.today().strftime("%Y-%m-%d")
    bhav, bhav_src = load_bhavcopy()
    if bhav.empty:
        send_telegram(f"❌ <b>Incubator — {date_label}</b>\nUniverse unavailable on all tiers.")
        return []

    cands = bhav[bhav["turnover_lakhs"] >= config.MIN_TURNOVER_LAKHS].copy()
    log.info(f"Candidates after turnover gate: {len(cands)} (src={bhav_src})")

    survivors, rejects, exceptions = [], [], 0
    for _, row in cands.iterrows():
        sym = str(row["symbol"]).upper()
        try:
            res = score_stone(sym, _nan_safe(row["close"]))
            if "reject_gate" in res:
                rejects.append([date_label, sym, res["reject_gate"],
                                str(res.get("reject_reason", ""))[:90]])
            else:
                survivors.append(res)
        except Exception as e:
            exceptions += 1
            rejects.append([date_label, sym, "EXCEPTION", str(e)[:90]])
            log.debug(f"EXCEPTION {sym}: {e}")

    survivors.sort(key=lambda x: x["math_score"], reverse=True)
    top = survivors[:25]
    log.info(f"Stage 1: {len(survivors)} survivors ({exceptions} exceptions isolated) "
             f"→ top {len(top)} to Shariah")

    pearls = []
    for item in top:
        sym = item["symbol"]
        try:
            profile = get_company_profile(sym)
            audit = full_audit(sym, company_name=profile["name"],
                                industry=profile["industry"] or profile["sector"],
                                biz_profile=profile["summary"])
            if not audit["compliant"]:
                rejects.append([date_label, sym, "SHARIAH", audit["reason"][:90]])
                log.info(f"  SHARIAH VETO | {sym} | {audit['reason'][:60]}")
                continue
            thesis = (f"Rubble {item['g1']['discount_pct']}% below 52W high | "
                      f"box {item['g1']['box_weeks']}w | sponge {item['g3']['sponge_weeks']}w"
                      + (f" | EPS accel {item['eps']['g1']}%" if item["eps"]["accel"] else "")
                      + f" | score {item['math_score']}")
            upsert_pearl(sym, thesis, item["g1"], float(item["math_score"]),
                          pearl_grade="PEARL", sector=profile["sector"] or "Unknown",
                          quality_flags=item["quality_flags"], sharia_compliant=True)
            pearls.append({**item, "thesis": thesis, "sector": profile["sector"]})
            log.info(f"  💎 PEARL {sym} score={item['math_score']} "
                     f"[{item['quality_flags'] or 'no flags'}]")
        except Exception as e:
            rejects.append([date_label, sym, "EXCEPTION", str(e)[:90]])
            log.debug(f"EXCEPTION shariah-stage {sym}: {e}")

    # ── REJECTS_LOG: keep this run's rows + last ~2000 historical ────────
    try:
        header = ["Date", "Symbol", "Gate", "Reason"]
        existing = read_sheet("REJECTS_LOG")
        old_rows = [r for r in existing[1:] if r and r[0] != date_label] if len(existing) > 1 else []
        push_sheet("REJECTS_LOG", [header] + old_rows[-2000:] + rejects)
        log.info(f"REJECTS_LOG: {len(rejects)} rows for {date_label}")
    except Exception as e:
        log.warning(f"REJECTS_LOG push: {e}")

    if pearls:
        header = ["Date", "Symbol", "Sector", "MathScore", "Discount%", "BoxWeeks",
                  "SpongeWeeks", "EPSg1%", "QualityFlags", "Thesis"]
        rows = [[date_label, p["symbol"], p.get("sector", ""), p["math_score"],
                 p["g1"]["discount_pct"], p["g1"]["box_weeks"], p["g3"]["sponge_weeks"],
                 p["eps"]["g1"], p["quality_flags"], p["thesis"]] for p in pearls]
        existing = read_sheet("INCUBATOR")
        old = existing[1:] if len(existing) > 1 else []
        push_sheet("INCUBATOR", [header] + old + rows)

    gate_counts: Dict[str, int] = {}
    for r in rejects:
        gate_counts[r[2]] = gate_counts.get(r[2], 0) + 1
    gate_line = " | ".join(f"{g}:{n}" for g, n in
                            sorted(gate_counts.items(), key=lambda kv: -kv[1])[:5])

    lines = [f"🕴️ <b>Incubator Weekly — {date_label}</b>",
             f"Scanned {len(cands)} | Survivors {len(survivors)} | Pearls {len(pearls)}",
             f"Gates: {gate_line}", ""]
    for p in pearls[:10]:
        lines.append(f"💎 <b>{p['symbol']}</b> ({p.get('sector','?')[:14]}) "
                     f"score={p['math_score']}")
    send_telegram("\n".join(lines))
    log.info(f"✅ Incubator complete | {len(pearls)} pearls on watchlist")
    return pearls


if __name__ == "__main__":
    run()
