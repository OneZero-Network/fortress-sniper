#!/usr/bin/env python3
"""
FORTRESS_CRYPTO — scripts/backtest_v5.py
══════════════════════════════════════════════════════════════════════════════
V5 — REGIME-GATED TECHNICAL CORE. A falsification test, not an
optimization exercise, per explicit mandate:

  "V5 is not an optimization exercise. It is a falsification test of the
   hypothesis that the existing technical signal has conditional
   predictive edge specifically in BULL/NORMAL_VOL environments. Freeze
   the discovered rules, evaluate them on unseen data, compare against
   random regime-matched entries and BTC/regime benchmarks, include
   realistic costs, and report the complete return distribution and risk
   metrics. Do not tune V5 after observing the test set."

FROZEN RULES (do not alter — see core/crypto/backtest.py's V5 docstring):
  ENTRY: V1 technical trigger AND regime == BULL/NORMAL_VOL
  EXIT:  1.5R/3R, 21-day timeout (same as every other variant)
  COSTS: same ROUND_TRIP_COST_PCT

STRUCTURE:
  1. DISCOVERY period (first half of fetched history) — reproduces the
     +1.35% result already observed. If it doesn't reproduce here,
     there's an implementation discrepancy, not a real finding.
  2. VALIDATION period (second half, never used to derive the BULL/
     NORMAL_VOL hypothesis) — the real test. No parameter changes are
     made between discovery and validation.
  3. V5-Control — random regime-matched entries (same regime, no
     technical trigger) — tests whether V5 beats "just being long during
     a healthy bull market," not merely whether it's profitable.
  4. Leave-one-coin-out — checks whether the result depends on one
     coin's idiosyncratic performance.
  5. BTC-relative return — absolute return isn't enough; is this beating
     the market it's priced in?

TARGET_REGIME_LABEL is read from the prior backtest's finding
(BULL/NORMAL_VOL) — hardcoded here deliberately, this experiment is
frozen and should not silently re-discover a different "best" regime
from this run's own data.
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                     datefmt="%H:%M:%S")
log = logging.getLogger("fortress.crypto.backtest_v5")

TARGET_REGIME_LABEL = "BULL/NORMAL_VOL"   # FROZEN — the discovered hypothesis, not re-derived
BACKTEST_UNIVERSE_N = int(os.getenv("CRYPTO_BACKTEST_UNIVERSE_N", "30"))
TOTAL_DAYS = int(os.getenv("CRYPTO_V5_TOTAL_DAYS", "480"))   # discovery + validation combined
DISCOVERY_DAYS = TOTAL_DAYS // 2


def _fmt_extended(stats: dict, label: str) -> str:
    if not stats.get("available"):
        return f"<b>{label}</b>: no signals generated"
    pf = f"{stats['profit_factor']}" if stats['profit_factor'] is not None else "n/a"
    sharpe = f"{stats['sharpe_per_trade']}" if stats['sharpe_per_trade'] is not None else "n/a"
    sortino = f"{stats['sortino_per_trade']}" if stats['sortino_per_trade'] is not None else "n/a"
    btc_rel = f"{stats['btc_relative_avg_pct']:+.2f}%" if stats['btc_relative_avg_pct'] is not None else "n/a"
    warn = " ⚠️ n<30, low sample" if stats["low_sample_warning"] else ""
    return (
        f"<b>{label}</b>{warn}\n"
        f"   n={stats['n']}, hit rate {stats['hit_rate_pct']}%\n"
        f"   gross avg {stats['gross_avg_pct']:+.2f}% | net avg {stats['net_avg_pct']:+.2f}% | median {stats['net_median_pct']:+.2f}%\n"
        f"   avg winner {stats['avg_winner_pct']}% | avg loser {stats['avg_loser_pct']}%\n"
        f"   profit factor {pf} | max drawdown {stats['max_drawdown_pct']}% | longest losing streak {stats['longest_losing_streak']}\n"
        f"   Sharpe(per-trade) {sharpe} | Sortino(per-trade) {sortino}\n"
        f"   avg exposure {stats['avg_exposure_days']}d | vs BTC same-period: {btc_rel}"
    )


def _run_period(coin_histories: dict, btc_hist_full, start_idx: int, end_idx: int, label: str) -> dict:
    """Runs V5 + V5-Control on a specific slice of the fetched history
    (discovery = first half, validation = second half). Returns raw
    trade lists so leave-one-coin-out can be computed downstream."""
    v5_trades = []
    control_candidates = []

    for symbol, (coin, hist) in coin_histories.items():
        hist_slice = hist.iloc[start_idx:end_idx].reset_index(drop=True)
        btc_slice = btc_hist_full.iloc[start_idx:end_idx].reset_index(drop=True) if btc_hist_full is not None else None
        if len(hist_slice) < 60:
            continue

        v5_trades.extend(backtest.backtest_coin_regime_gated(
            symbol, hist_slice, btc_slice, TARGET_REGIME_LABEL, ccfg.LANE_FUSED_MIN))
        control_candidates.extend(backtest.sample_regime_matched_control(
            symbol, hist_slice, btc_slice, TARGET_REGIME_LABEL))

    # Match control sample size to V5's sample size (random subsample,
    # without replacement) so the comparison is apples-to-apples, not
    # "34 signals vs. 400 candidates."
    import random
    random.seed(42)  # fixed seed — reproducible, not cherry-picked per run
    n_target = len(v5_trades)
    control_sample = (random.sample(control_candidates, n_target)
                       if len(control_candidates) >= n_target else control_candidates)

    v5_stats = backtest.compute_extended_stats(v5_trades, btc_hist_full)
    control_stats = backtest.compute_extended_stats(control_sample, btc_hist_full)

    log.info(f"[{label}] V5: {v5_stats}")
    log.info(f"[{label}] V5-Control: {control_stats}")

    return {"v5_trades": v5_trades, "v5_stats": v5_stats, "control_stats": control_stats}


def run() -> None:
    log.info(f"=== V5 Falsification Test — Regime-Gated ({TARGET_REGIME_LABEL}) — FROZEN RULES ===")
    log.info(f"Universe: top {BACKTEST_UNIVERSE_N} coins, {TOTAL_DAYS} total days "
             f"({DISCOVERY_DAYS} discovery + {TOTAL_DAYS - DISCOVERY_DAYS} validation)")

    universe = cdata.fetch_universe(top_n=BACKTEST_UNIVERSE_N)
    if not universe:
        log.error("Universe fetch failed — aborting")
        return

    btc_hist_full = cdata.fetch_daily_ohlc(ccfg.BENCHMARK_COIN_ID, days=TOTAL_DAYS)
    if btc_hist_full.empty:
        log.error("BTC history unavailable — cannot compute regime gate, aborting")
        return

    coin_histories = {}
    for i, coin in enumerate(universe):
        log.info(f"[{i+1}/{len(universe)}] Fetching {coin['symbol']}...")
        hist = cdata.fetch_daily_ohlc(coin["id"], days=TOTAL_DAYS)
        if hist.empty or len(hist) < 120:
            log.info(f"  skip: insufficient history ({len(hist)} rows, need >=120 for split)")
            continue
        coin_histories[coin["symbol"]] = (coin, hist)

    log.info(f"{len(coin_histories)} coins with sufficient history for discovery+validation split")

    discovery = _run_period(coin_histories, btc_hist_full, 0, DISCOVERY_DAYS, "DISCOVERY")
    validation = _run_period(coin_histories, btc_hist_full, DISCOVERY_DAYS, TOTAL_DAYS, "VALIDATION")

    # Leave-one-coin-out on the DISCOVERY period's V5 trades (where the
    # hypothesis was originally found) — checks if it's one coin's
    # idiosyncratic run driving the result.
    loco = backtest.leave_one_coin_out(discovery["v5_trades"], btc_hist_full)
    loco_lines = "\n".join(
        f"   without {sym}: n={s['n']}, net avg {s['net_avg_pct']:+.2f}%" if s.get("available") else f"   without {sym}: n=0"
        for sym, s in sorted(loco.items())
    )

    message = (
        f"🧪 <b>V5 FALSIFICATION TEST — Regime-Gated Technical Core (FROZEN RULES)</b>\n"
        f"<i>Gate: entry requires technical trigger AND regime=={TARGET_REGIME_LABEL}. "
        f"No parameter tuning between discovery and validation.</i>\n\n"
        f"═══ DISCOVERY PERIOD (first {DISCOVERY_DAYS}d — where the hypothesis was found) ═══\n"
        f"{_fmt_extended(discovery['v5_stats'], 'V5 (regime-gated)')}\n\n"
        f"{_fmt_extended(discovery['control_stats'], 'V5-Control (random, same regime)')}\n\n"
        f"═══ VALIDATION PERIOD (next {TOTAL_DAYS - DISCOVERY_DAYS}d — UNSEEN, no tuning) ═══\n"
        f"{_fmt_extended(validation['v5_stats'], 'V5 (regime-gated)')}\n\n"
        f"{_fmt_extended(validation['control_stats'], 'V5-Control (random, same regime)')}\n\n"
        f"═══ LEAVE-ONE-COIN-OUT (discovery period) ═══\n"
        f"{loco_lines if loco_lines else '   insufficient coins for this check'}\n"
    )
    plain = message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
    log.info(plain)
    send_telegram(message)


if __name__ == "__main__":
    run()
