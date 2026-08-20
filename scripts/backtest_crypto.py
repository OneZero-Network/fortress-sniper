#!/usr/bin/env python3
"""
FORTRESS_CRYPTO — scripts/backtest_crypto.py
══════════════════════════════════════════════════════════════════════════════
Manual/on-demand backtest runner. NOT part of the daily/weekly cron —
this is a heavier research tool (fetches ~240 days of history per coin),
run via GitHub Actions "workflow_dispatch" (manual trigger) or locally.

Every line of output is labeled SIMULATED. This is deliberate and
permanent — see core/crypto/backtest.py's module docstring for what this
can and cannot validate (technical core only; news/whale/risk layers
have no historical data to replay against).
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
log = logging.getLogger("fortress.crypto.backtest_runner")

BACKTEST_UNIVERSE_N = int(os.getenv("CRYPTO_BACKTEST_UNIVERSE_N", "30"))  # kept small — 1 API call/coin but real CPU cost
BACKTEST_DAYS = int(os.getenv("CRYPTO_BACKTEST_DAYS", "240"))


def run() -> None:
    log.info(f"=== FORTRESS_CRYPTO Backtest (SIMULATED — technical core only) ===")
    log.info(f"Universe: top {BACKTEST_UNIVERSE_N} coins, {BACKTEST_DAYS} days history each")

    universe = cdata.fetch_universe(top_n=BACKTEST_UNIVERSE_N)
    if not universe:
        log.error("Universe fetch failed — aborting backtest")
        return

    log.info("Fetching BTC benchmark history...")
    btc_hist = cdata.fetch_daily_ohlc(ccfg.BENCHMARK_COIN_ID, days=BACKTEST_DAYS)
    if btc_hist.empty:
        log.warning("BTC history unavailable — regime component will default neutral throughout")
        btc_hist = None

    all_trades_fortress = []
    all_trades_swing = []

    for i, coin in enumerate(universe):
        log.info(f"[{i+1}/{len(universe)}] Backtesting {coin['symbol']}...")
        hist = cdata.fetch_daily_ohlc(coin["id"], days=BACKTEST_DAYS)
        if hist.empty or len(hist) < 60:
            log.info(f"  skip: insufficient history ({len(hist)} rows)")
            continue

        fortress_trades = backtest.backtest_coin(coin["symbol"], hist, btc_hist, ccfg.LANE_FUSED_MIN)
        swing_trades = backtest.backtest_coin(coin["symbol"], hist, btc_hist, ccfg.DAILY_SWING_MIN)
        # swing_trades includes everything fortress_trades would too (lower
        # bar) — keep them as genuinely separate tiers by excluding
        # fortress-level signals from the swing bucket
        fortress_entry_dates = {(t["symbol"], t["entry_date"]) for t in fortress_trades}
        swing_only = [t for t in swing_trades if (t["symbol"], t["entry_date"]) not in fortress_entry_dates]

        all_trades_fortress.extend(fortress_trades)
        all_trades_swing.extend(swing_only)
        log.info(f"  {len(fortress_trades)} FORTRESS-level signal(s), {len(swing_only)} SWING-only signal(s)")

    fortress_stats = backtest.summarize_backtest(all_trades_fortress)
    swing_stats = backtest.summarize_backtest(all_trades_swing)

    log.info(f"FORTRESS (SIMULATED): {fortress_stats}")
    log.info(f"SWING (SIMULATED): {swing_stats}")

    def _fmt(stats, label):
        if stats["sample_size"] == 0:
            return f"   {label}: no signals generated in backtest window"
        warn = " ⚠️ small sample" if stats["low_sample_warning"] else ""
        hit = f"{stats['hit_rate_pct']}%" if stats["hit_rate_pct"] is not None else "n/a"
        avg = f"{stats['avg_pnl_pct']:+.1f}%" if stats["avg_pnl_pct"] is not None else "n/a"
        breakdown = stats.get("status_breakdown", {})
        bd_str = ", ".join(f"{k}:{v}" for k, v in breakdown.items() if v > 0)
        return f"   {label}: n={stats['sample_size']}, hit rate {hit}, avg return {avg}{warn}\n      ({bd_str})"

    message = (
        f"🧪 <b>FORTRESS_CRYPTO Backtest — SIMULATED, NOT LIVE DATA</b>\n"
        f"<i>Technical core only (trend+RSI/ADX/volume+regime). News/whale/risk "
        f"layers NOT included — no historical data exists for them. This is a "
        f"floor/sanity-check on the technical logic, not a live-performance prediction.</i>\n\n"
        f"Universe: top {BACKTEST_UNIVERSE_N} coins, {BACKTEST_DAYS}-day window\n\n"
        f"{_fmt(fortress_stats, 'FORTRESS-tier')}\n\n"
        f"{_fmt(swing_stats, 'SWING-tier')}"
    )
    log.info(message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", ""))
    send_telegram(message)


if __name__ == "__main__":
    run()
