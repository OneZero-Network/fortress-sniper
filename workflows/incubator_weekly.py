#!/usr/bin/env python3
"""
FORTRESS_UNIFIED — workflows/incubator_weekly.py
══════════════════════════════════════════════════════════════════════════════
Weekly entrypoint (GHA: cron '0 5 * * 1' IST Monday morning, before
weekly_review so the review can see this week's fresh pearls too — or
schedule it Sunday night if you want the review to cover a settled week;
see .github/workflows/ for the actual cron).

Stage 1 — Rubble + EPS + Sponge math gates (unchanged logic from
incubator_v1, now importing shared indicators/nse_data/db).
Stage 2 — Single Shariah engine (core.shariah), fail-safe everywhere —
this is where the old fail-OPEN bug is fixed.
Stage 3 — For every survivor: upsert_pearl() writes it to the bridge
watchlist so Sniper picks it up starting tomorrow.

Also calls expire_stale_pearls() first so pearls Incubator no longer
confirms age out of Sniper's daily priority pass automatically.
"""
from __future__ import annotations
import logging
import os
import sys
from datetime import datetime
from typing import List, Optional, Tuple

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import config, preflight_secrets
from core.db import init_db
from core.nse_data import load_bhavcopy, fetch_weekly_history
from core.shariah import full_audit
from core.bridge import upsert_pearl, expire_stale_pearls
from core.telegram import send as send_telegram
from core.sheets_client import push_sheet, read_sheet

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                     datefmt="%H:%M:%S")
log = logging.getLogger("fortress.incubator")


def check_rubble_gate(weekly: pd.DataFrame, close: float) -> Tuple[bool, dict]:
    details = {"high_52w": 0.0, "low_52w": 0.0, "discount_pct": 0.0,
               "box_weeks": 0, "box_width_pct": 0.0, "ma200": 0.0, "score": 0, "reason": ""}
    if weekly.empty or len(weekly) < 20:
        details["reason"] = f"insufficient data: {len(weekly)} weeks"
        return False, details

    high_w = weekly["high"].values.astype(float)
    low_w = weekly["low"].values.astype(float)
    close_w = weekly["close"].values.astype(float)
    high_52w, low_52w = float(high_w.max()), float(low_w.min())
    if high_52w <= 0:
        details["reason"] = "52W high = 0"
        return False, details

    discount_pct = (high_52w - close) / high_52w
    details.update(high_52w=round(high_52w, 2), low_52w=round(low_52w, 2),
                    discount_pct=round(discount_pct * 100, 1))

    if discount_pct < config.RUBBLE_DISCOUNT_MIN:
        details["reason"] = f"only {discount_pct*100:.1f}% below 52W high"
        return False, details
    if low_52w > 0 and close < low_52w * 1.05:
        details["reason"] = "too close to 52W low (falling knife)"
        return False, details

    ma_period = min(40, len(close_w))
    ma200 = float(pd.Series(close_w).rolling(ma_period).mean().iloc[-1])
    details["ma200"] = round(ma200, 2) if ma200 > 0 else 0.0

    box_weeks = 0
    for lb in range(min(40, len(close_w)), 0, -1):
        bh, bl = float(high_w[-lb:].max()), float(low_w[-lb:].min())
        if bl > 0 and (bh / bl - 1) <= config.STAGE1_BOX_WIDTH_MAX:
            box_weeks = lb
            break
    details["box_weeks"] = box_weeks
    details["box_width_pct"] = round(
        (high_w[-box_weeks:].max() / low_w[-box_weeks:].min() - 1) * 100 if box_weeks > 0 else 99, 1)

    score = min(30, int(discount_pct * 100))
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

    close_w = weekly["close"].values.astype(float)
    vol_w = weekly["volume"].values.astype(float)
    lookback = min(20, len(weekly))
    close_r, vol_r = close_w[-lookback:], vol_w[-lookback:]
    avg_vol = float(vol_r.mean())
    if avg_vol <= 0:
        details.update(score=5, reason="avg volume = 0")
        return True, details

    red_mask = close_r[1:] < close_r[:-1]
    green_mask = close_r[1:] >= close_r[:-1]
    dry_vol_ratio = float(vol_r[1:][red_mask].mean() / avg_vol) if red_mask.any() else 1.0
    dry_up_weeks = int((vol_r[1:][red_mask] < avg_vol * config.SPONGE_DRY_VOL_PCT).sum())
    sponge_weeks = int((vol_r[1:][green_mask] > avg_vol * config.SPONGE_WET_VOL_PCT).sum())
    details.update(dry_up_weeks=dry_up_weeks, sponge_weeks=sponge_weeks)

    if dry_vol_ratio > config.SPONGE_DRY_VOL_PCT and sponge_weeks == 0:
        details["reason"] = f"no sponge pattern: dry={dry_vol_ratio:.2f} sponge={sponge_weeks}w"
        return False, details

    score = (10 if dry_up_weeks >= 3 else 5 if dry_up_weeks >= 1 else 0)
    score += (20 if sponge_weeks >= 2 else 12 if sponge_weeks >= 1 else 0)
    score += 5 if dry_vol_ratio < 0.50 else 0
    details["score"] = score
    details["reason"] = f"Sponge OK dry={dry_up_weeks}w sponge={sponge_weeks}w"
    return True, details


def score_stone_math(symbol: str, close: float) -> Optional[dict]:
    if close <= 0 or close < config.MIN_PRICE or close > config.MAX_PRICE:
        return None
    weekly = fetch_weekly_history(symbol, weeks=52)
    if weekly.empty or len(weekly) < 13:
        return {"symbol": symbol, "reject_gate": "NO_WEEKLY_DATA", "math_score": 0}

    g1_ok, g1 = check_rubble_gate(weekly, close)
    if not g1_ok:
        return {"symbol": symbol, "reject_gate": "RUBBLE_FAIL", "reject_reason": g1["reason"], "math_score": 0}

    g3_ok, g3 = check_sponge_volume(weekly)
    if not g3_ok:
        return {"symbol": symbol, "reject_gate": "SPONGE_FAIL", "reject_reason": g3["reason"], "math_score": 0}

    math_score = g1["score"] + g3["score"]
    return {"symbol": symbol, "close": close, "math_score": math_score,
            "weekly": weekly, "g1": g1, "g3": g3}


def run() -> List[dict]:
    log.info("=" * 70)
    log.info(f"  {config.VERSION} — INCUBATOR WEEKLY")
    log.info("=" * 70)
    init_db()
    preflight_secrets()

    expired = expire_stale_pearls()
    log.info(f"Expired {expired} stale pearls (TTL={config.PEARL_WATCHLIST_TTL_DAYS}d)")

    date_label = datetime.today().strftime("%Y-%m-%d")
    bhav, bhav_src = load_bhavcopy()
    if bhav.empty:
        log.error("Universe empty on all tiers — aborting")
        send_telegram(f"❌ <b>Incubator Weekly — {date_label}</b>\nUniverse unavailable.")
        return []

    cands = bhav[bhav["turnover_lakhs"] >= config.MIN_TURNOVER_LAKHS].copy()
    log.info(f"Candidates after turnover gate: {len(cands)} (source={bhav_src})")

    survivors = []
    for _, row in cands.iterrows():
        sym = str(row["symbol"]).upper()
        result = score_stone_math(sym, float(row["close"]))
        if result and "reject_gate" not in result and result["math_score"] >= config.STONE_SCORE_MIN:
            survivors.append(result)

    survivors.sort(key=lambda x: x["math_score"], reverse=True)
    top25 = survivors[:25]
    log.info(f"Stage 1 complete: {len(top25)} survivors → Shariah audit")

    pearls = []
    for item in top25:
        sym = item["symbol"]
        audit = full_audit(sym, industry="Unknown")
        if not audit["compliant"]:
            log.info(f"  SHARIAH VETO | {sym} | {audit['reason']}")
            continue

        thesis = (f"Rubble {item['g1']['discount_pct']}% below 52W high | "
                 f"Sponge {item['g3']['sponge_weeks']}w | score={item['math_score']}")
        upsert_pearl(sym, thesis, item["g1"], item["math_score"],
                     pearl_grade="PEARL", sector="Unknown", quality_flags="",
                     sharia_compliant=True)
        pearls.append({**item, "thesis": thesis})
        log.info(f"  💎 PEARL {sym} | score={item['math_score']} → watchlist")

    if pearls:
        header = ["Date", "Symbol", "MathScore", "Discount%", "BoxWeeks", "SpongeWeeks", "Thesis"]
        rows = [header] + [[date_label, p["symbol"], p["math_score"], p["g1"]["discount_pct"],
                            p["g1"]["box_weeks"], p["g3"]["sponge_weeks"], p["thesis"]] for p in pearls]
        existing = read_sheet("INCUBATOR")
        if existing and len(existing) > 1:
            rows = [header] + existing[1:] + rows[1:]
        push_sheet("INCUBATOR", rows)

    lines = [f"🕴️ <b>Incubator Weekly — {date_label}</b>",
             f"Scanned {len(cands)} | Survivors {len(top25)} | Pearls {len(pearls)}", ""]
    for p in pearls[:10]:
        lines.append(f"💎 <b>{p['symbol']}</b> score={p['math_score']} — {p['thesis'][:80]}")
    send_telegram("\n".join(lines) if pearls else
                  f"🕴️ <b>Incubator Weekly — {date_label}</b>\nNo pearls surfaced this week.")

    log.info(f"✅ Incubator weekly complete | {len(pearls)} pearls added to watchlist")
    return pearls


if __name__ == "__main__":
    run()
