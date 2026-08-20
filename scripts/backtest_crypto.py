#!/usr/bin/env python3
"""
FORTRESS_CRYPTO — scripts/backtest_crypto.py  (v2 — experiment matrix)
══════════════════════════════════════════════════════════════════════════════
Manual/on-demand backtest runner. Rebuilt per your mentor's explicit
push-back: a single backtest number can't distinguish "bad signal" (A)
from "bad regime interaction" (B) from "bad exit math" (C) from "no edge
at all" (D). This runs an actual experiment matrix instead of one config:

  VARIANTS:
    1. Technical-only,        1.5R/3R exit
    2. Technical + Regime,    1.5R/3R exit   <- what was reported before
    3. Technical + Regime,    1R/2R exit     (tighter, faster resolution)
    4. Technical + Regime,    2R/4R exit     (wider, more room)

  For variant 2 specifically, also reports:
    - Regime-conditioned breakdown (does this only work in BULL/LOW_VOL?)
    - False-Pearl ablation (does excluding currently-HIGH_RISK-flagged
      coins improve the numbers? — an approximation, see caveat below)

Every number is cost-adjusted (net of fee+slippage estimate) as well as
raw, reported side by side — per the explicit warning that a zero-cost
backtest manufactures fake edge.

HONEST CAVEAT on False-Pearl ablation: this applies TODAY's risk_engine
check to each backtested coin as a whole-coin filter, not a true
per-signal-in-time historical check (GoPlus doesn't serve historical
contract state). A coin currently flagged HIGH_RISK is excluded from
its entire trade history in this variant — that's a real but imperfect
approximation, not equivalent to knowing what the risk state was on
each historical signal date.
"""
from __future__ import annotations
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.telegram import send as send_telegram
from core.crypto import config as ccfg
from core.crypto import data as cdata
from core.crypto import backtest
from core.crypto import risk_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                     datefmt="%H:%M:%S")
log = logging.getLogger("fortress.crypto.backtest_runner")

BACKTEST_UNIVERSE_N = int(os.getenv("CRYPTO_BACKTEST_UNIVERSE_N", "30"))
BACKTEST_DAYS = int(os.getenv("CRYPTO_BACKTEST_DAYS", "240"))


def _fmt_stats(stats: dict, label: str) -> str:
    if stats["sample_size"] == 0:
        return f"   {label}: no signals generated"
    warn = " ⚠️ small sample" if stats["low_sample_warning"] else ""
    hit = f"{stats['hit_rate_pct']}%" if stats["hit_rate_pct"] is not None else "n/a"
    raw = f"{stats['avg_pnl_pct_raw']:+.2f}%" if stats["avg_pnl_pct_raw"] is not None else "n/a"
    net = f"{stats['avg_pnl_pct_net']:+.2f}%" if stats["avg_pnl_pct_net"] is not None else "n/a"
    return f"   {label}: n={stats['sample_size']}, hit rate {hit}, avg raw {raw}, avg NET (after costs) {net}{warn}"


def run() -> None:
    log.info(f"=== FORTRESS_CRYPTO Backtest Experiment Matrix (SIMULATED) ===")
    log.info(f"Universe: top {BACKTEST_UNIVERSE_N} coins, {BACKTEST_DAYS} days each")
    log.info(f"Transaction cost assumption: {backtest.ROUND_TRIP_COST_PCT:.2f}% round-trip (fees+slippage)")

    universe = cdata.fetch_universe(top_n=BACKTEST_UNIVERSE_N)
    if not universe:
        log.error("Universe fetch failed — aborting backtest")
        return

    log.info("Fetching BTC benchmark history...")
    btc_hist = cdata.fetch_daily_ohlc(ccfg.BENCHMARK_COIN_ID, days=BACKTEST_DAYS)
    if btc_hist.empty:
        log.warning("BTC history unavailable — regime variants will default neutral")
        btc_hist = None

    coin_histories = {}
    coin_risk_flags = {}
    for i, coin in enumerate(universe):
        log.info(f"[{i+1}/{len(universe)}] Fetching {coin['symbol']}...")
        hist = cdata.fetch_daily_ohlc(coin["id"], days=BACKTEST_DAYS)
        if hist.empty or len(hist) < 60:
            log.info(f"  skip: insufficient history ({len(hist)} rows)")
            continue
        coin_histories[coin["symbol"]] = (coin, hist)

        try:
            platforms = cdata.fetch_platforms(coin["id"])
            risk = risk_engine.assess_false_pearl_risk(platforms)
            coin_risk_flags[coin["symbol"]] = risk.get("severity", "UNCHECKED")
        except Exception as e:
            log.debug(f"risk check failed for {coin['symbol']}: {e}")
            coin_risk_flags[coin["symbol"]] = "UNCHECKED"

    log.info(f"{len(coin_histories)} coins with sufficient history")

    trades_v1 = []
    for symbol, (coin, hist) in coin_histories.items():
        trades_v1.extend(backtest.backtest_coin(symbol, hist, btc_hist, ccfg.LANE_FUSED_MIN,
                                                  include_regime=False, r1_mult=1.5, r2_mult=3.0))
    stats_v1 = backtest.summarize_backtest(trades_v1)
    log.info(f"V1 Technical-only 1.5R/3R: {stats_v1}")

    trades_v2 = []
    for symbol, (coin, hist) in coin_histories.items():
        trades_v2.extend(backtest.backtest_coin(symbol, hist, btc_hist, ccfg.LANE_FUSED_MIN,
                                                  include_regime=True, r1_mult=1.5, r2_mult=3.0))
    stats_v2 = backtest.summarize_backtest(trades_v2)
    log.info(f"V2 Technical+Regime 1.5R/3R (current live config): {stats_v2}")

    trades_v3 = []
    for symbol, (coin, hist) in coin_histories.items():
        trades_v3.extend(backtest.backtest_coin(symbol, hist, btc_hist, ccfg.LANE_FUSED_MIN,
                                                  include_regime=True, r1_mult=1.0, r2_mult=2.0))
    stats_v3 = backtest.summarize_backtest(trades_v3)
    log.info(f"V3 Technical+Regime 1R/2R: {stats_v3}")

    trades_v4 = []
    for symbol, (coin, hist) in coin_histories.items():
        trades_v4.extend(backtest.backtest_coin(symbol, hist, btc_hist, ccfg.LANE_FUSED_MIN,
                                                  include_regime=True, r1_mult=2.0, r2_mult=4.0))
    stats_v4 = backtest.summarize_backtest(trades_v4)
    log.info(f"V4 Technical+Regime 2R/4R: {stats_v4}")

    regime_breakdown = backtest.summarize_by_regime(trades_v2)
    log.info(f"Regime breakdown (V2): {regime_breakdown}")

    clean_symbols = {s for s, sev in coin_risk_flags.items() if sev != "HIGH_RISK"}
    trades_v2_clean = [t for t in trades_v2 if t["symbol"] in clean_symbols]
    stats_v2_clean = backtest.summarize_backtest(trades_v2_clean)
    excluded_count = len(coin_histories) - len(clean_symbols)
    log.info(f"False-Pearl ablation: excluded {excluded_count} HIGH_RISK-flagged coin(s), "
             f"remaining stats: {stats_v2_clean}")

    regime_lines = "\n".join(_fmt_stats(s, label) for label, s in sorted(regime_breakdown.items()))

    message = (
        f"🧪 <b>FORTRESS_CRYPTO Backtest Experiment Matrix — SIMULATED, NOT LIVE DATA</b>\n"
        f"<i>Technical core only can be replayed — news/whale timing/live risk-state cannot. "
        f"All returns shown RAW and NET of estimated {backtest.ROUND_TRIP_COST_PCT:.2f}% round-trip costs.</i>\n\n"
        f"<b>Entry/Exit Matrix</b> (isolating signal vs. regime vs. exit structure):\n"
        f"{_fmt_stats(stats_v1, 'V1 Technical-only, 1.5R/3R')}\n"
        f"{_fmt_stats(stats_v2, 'V2 Technical+Regime, 1.5R/3R (current live config)')}\n"
        f"{_fmt_stats(stats_v3, 'V3 Technical+Regime, 1R/2R (tighter)')}\n"
        f"{_fmt_stats(stats_v4, 'V4 Technical+Regime, 2R/4R (wider)')}\n\n"
        f"<b>Regime-conditioned breakdown (V2 config)</b> — does this only work in certain regimes?\n"
        f"{regime_lines}\n\n"
        f"<b>False-Pearl ablation (V2 config)</b> — approximate, current risk snapshot used as a "
        f"whole-coin filter, not true historical per-signal risk:\n"
        f"   Excluded {excluded_count}/{len(coin_histories)} coin(s) currently flagged HIGH_RISK\n"
        f"{_fmt_stats(stats_v2_clean, 'V2 minus HIGH_RISK coins')}"
    )
    plain = message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
    log.info(plain)
    send_telegram(message)


if __name__ == "__main__":
    run()
