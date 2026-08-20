#!/usr/bin/env python3
"""
FORTRESS_CRYPTO — scripts/calibrate_regime_v2.py
══════════════════════════════════════════════════════════════════════════════
Phase B calibration test. NOT a trading experiment — this asks exactly
one question, per the explicit mandate: "Can this engine correctly
describe the market state?" Nothing here is optimized against FORTRESS
profitability; there is no strategy, no entries, no exits in this script.

METHOD, same discipline as backtest.py: walks forward day by day through
historical data, computing regime_v2's label using ONLY data up to and
including that day (no lookahead in the classification itself). THEN,
for audit purposes only (safe — we are evaluating the classifier's past
calibration, not trading on future data), checks what BTC's price
actually did over the following 21 days.

REPORTS, directly comparable to v1's known failure (Regime Audit v1):
  v1 baseline: BULL/NORMAL_VOL calls followed by BTC actually rising
               0% (discovery) / 36.4% (validation) of the time
  v2 target:   FAVORABLE calls should be followed by BTC rising
               meaningfully more than 50% of the time to be worth
               anything; UNFAVORABLE calls should be followed by BTC
               falling more than 50% of the time

If v2 doesn't clear a basic bar here, it does NOT get wired into
anything — same standard v1 failed to meet.
"""
from __future__ import annotations
import logging
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.telegram import send as send_telegram
from core.crypto import config as ccfg
from core.crypto import data as cdata
from core.crypto import regime_v2

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                     datefmt="%H:%M:%S")
log = logging.getLogger("fortress.crypto.calibrate_v2")

TOTAL_DAYS = min(int(os.getenv("CRYPTO_REGIME_V2_DAYS", "360")), 364)
FORWARD_WINDOW_DAYS = 21
# Basket for breadth — a fixed, small set of large, liquid coins, chosen
# for consistent multi-year data availability, NOT cherry-picked for
# calibration results. Frozen before running this script.
BREADTH_BASKET_IDS = ["ethereum", "binancecoin", "ripple", "solana", "cardano",
                       "dogecoin", "tron", "chainlink", "litecoin", "stellar"]


def run() -> None:
    log.info("=== Phase B — Regime v2 Calibration Test (descriptive accuracy ONLY, no trading) ===")
    log.info(f"Window: {TOTAL_DAYS} days, forward-check window: {FORWARD_WINDOW_DAYS} days")

    btc_hist = cdata.fetch_daily_ohlc("bitcoin", days=TOTAL_DAYS)
    if btc_hist.empty or len(btc_hist) < 150:
        log.error("BTC history unavailable or too short — aborting")
        return

    basket_hists = []
    for coin_id in BREADTH_BASKET_IDS:
        h = cdata.fetch_daily_ohlc(coin_id, days=TOTAL_DAYS)
        if not h.empty and len(h) >= 100:
            basket_hists.append(h)
        log.info(f"Basket fetch {coin_id}: {len(h)} rows")
    log.info(f"Breadth basket: {len(basket_hists)}/{len(BREADTH_BASKET_IDS)} coins with sufficient history")

    records = []
    start_t = 100  # need 100 days for the trend factor's MA100
    end_t = len(btc_hist) - FORWARD_WINDOW_DAYS - 1
    for t in range(start_t, end_t):
        btc_slice = btc_hist.iloc[:t + 1]
        basket_slices = [h.iloc[:t + 1] for h in basket_hists if len(h) > t]
        result = regime_v2.compute_regime_v2(btc_slice, basket_slices)
        if not result["available"]:
            continue

        btc_entry = float(btc_hist["close"].iloc[t])
        btc_fwd = float(btc_hist["close"].iloc[t + FORWARD_WINDOW_DAYS])
        fwd_return_pct = round(100.0 * (btc_fwd - btc_entry) / btc_entry, 2) if btc_entry > 0 else None
        if fwd_return_pct is None:
            continue

        records.append({
            "date": str(btc_hist["date"].iloc[t].date()), "label": result["label"],
            "composite_score": result["composite_score"], "fwd_return_pct": fwd_return_pct,
        })

    log.info(f"{len(records)} classified day(s) with a matched forward window")

    by_label = {}
    for r in records:
        by_label.setdefault(r["label"], []).append(r["fwd_return_pct"])

    log.info("=== v1 BASELINE (for direct comparison) ===")
    log.info("v1 discovery: BULL/NORMAL_VOL -> BTC rose 0% of the time, avg fwd return -6.03%")
    log.info("v1 validation: BULL/NORMAL_VOL -> BTC rose 36.4% of the time, avg fwd return -0.87%")

    lines = [
        "🔬 <b>Phase B — Regime v2 Calibration Test</b>",
        "<i>Descriptive accuracy ONLY — no trading logic, no optimization against profitability. "
        "Same audit method that caught v1's failure (0-36.4% accuracy).</i>", "",
        "<b>v1 baseline (for comparison):</b> BULL/NORMAL_VOL -> BTC rose only 0% (discovery) / "
        "36.4% (validation) of the time — clearly miscalibrated.", "",
    ]
    for label in ("FAVORABLE", "NEUTRAL", "UNFAVORABLE"):
        returns = by_label.get(label, [])
        if not returns:
            lines.append(f"<b>{label}</b>: no classified days")
            continue
        n = len(returns)
        pct_positive = round(100.0 * sum(1 for r in returns if r > 0) / n, 1)
        avg_ret = round(float(np.mean(returns)), 2)
        median_ret = round(float(np.median(returns)), 2)
        warn = " ⚠️ small sample" if n < 30 else ""
        expected_direction = "BTC should RISE after this" if label == "FAVORABLE" else (
            "BTC should FALL after this" if label == "UNFAVORABLE" else "no strong directional claim")
        lines.append(f"<b>{label}</b> (n={n}){warn} — {expected_direction}\n"
                     f"   BTC rose {pct_positive}% of the time | avg fwd return {avg_ret:+.2f}% | median {median_ret:+.2f}%")

    message = "\n".join(lines)
    plain = message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
    log.info(plain)
    send_telegram(message)


if __name__ == "__main__":
    run()
