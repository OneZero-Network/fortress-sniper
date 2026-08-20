#!/usr/bin/env python3
"""
FORTRESS_CRYPTO — scripts/regime_audit_v1.py
══════════════════════════════════════════════════════════════════════════════
Regime Audit v1. NOT V6 — this does not tune the strategy. It audits
whether the V5 result can be trusted at all, per explicit instruction:
"Audit the regime classifier + backtest mechanics + return distribution
first. If those survive scrutiny, THEN we'll have a much cleaner basis
for designing the next experiment."

Three audits, run against V5's own generated trades (discovery +
validation, same frozen rules — this reuses backtest_coin_regime_gated
unchanged, it does not regenerate trades differently):

  1. BACKTEST MECHANICS — is the -96%/-76% drawdown a real portfolio
     risk figure, or a methodology artifact? Reports BOTH the naive
     arithmetic-sum number (what was originally shown) and a risk-
     adjusted compounded equity curve at fixed fractional position
     sizing (ACCOUNT_RISK_PCT, the same value already used for live
     sizing — not invented for this audit).

  2. REGIME CLASSIFIER CALIBRATION — for every entry the classifier
     called BULL/NORMAL_VOL, did BTC's own price actually rise over
     that trade's holding window? This is a PARTIAL audit (favorable
     calls only) — a full confusion matrix would need equal scrutiny of
     days the classifier called UNFAVORABLE too, which is a larger
     build not attempted here, flagged rather than silently implied.

  3. DISTRIBUTION / TOP-WINNER-REMOVAL — is the validation period's
     +0.93% average broad-based or a few lucky outliers carrying it?
     Removes the top 1/2/5 winning trades and recomputes.

No parameter tuning happens anywhere in this script — it observes and
reports on trades V5 already generated under its frozen rules.
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
log = logging.getLogger("fortress.crypto.regime_audit")

TARGET_REGIME_LABEL = "BULL/NORMAL_VOL"
BACKTEST_UNIVERSE_N = int(os.getenv("CRYPTO_BACKTEST_UNIVERSE_N", "30"))
TOTAL_DAYS = min(int(os.getenv("CRYPTO_V5_TOTAL_DAYS", "360")), 364)
DISCOVERY_DAYS = TOTAL_DAYS // 2


def _fmt_drawdown_audit(dd: dict, label: str) -> str:
    if not dd.get("available"):
        return f"<b>{label}</b>: {dd.get('reason', 'unavailable')}"
    return (
        f"<b>{label}</b> (n={dd['n_trades']})\n"
        f"   Naive arithmetic-sum drawdown: {dd['naive_arithmetic_max_dd_pct']}% "
        f"(⚠️ {dd['naive_method_caveat']})\n"
        f"   Risk-adjusted drawdown ({dd['risk_adjusted_assumption']}): "
        f"{dd['risk_adjusted_max_dd_pct']}%\n"
        f"   Risk-adjusted cumulative account return: {dd['risk_adjusted_final_return_pct']:+.2f}%"
    )


def _fmt_regime_audit(ra: dict, label: str) -> str:
    if not ra.get("available"):
        return f"<b>{label}</b>: {ra.get('reason', 'unavailable')}"
    return (
        f"<b>{label}</b> (n={ra['n']})\n"
        f"   BTC actually rose over the holding window: {ra['pct_where_btc_actually_rose']}% of the time\n"
        f"   Avg BTC forward return: {ra['avg_btc_forward_return_pct']:+.2f}% | Median: {ra['median_btc_forward_return_pct']:+.2f}%\n"
        f"   <i>{ra['interpretation']}</i>"
    )


def _fmt_winner_removal(wr: dict, label: str) -> str:
    if not wr.get("available"):
        return f"<b>{label}</b>: no data"
    lines = [f"<b>{label}</b>: baseline avg {wr['baseline_avg_pct']:+.2f}% (n={wr['baseline_n']})"]
    for k, res in sorted(wr["after_removal"].items()):
        if res is None:
            lines.append(f"   remove top {k}: not enough trades")
            continue
        removed = ", ".join(f"{r:+.1f}%" for r in res["top_removed_returns"])
        lines.append(f"   remove top {k} ({removed}): avg becomes {res['avg_pct']:+.2f}% (n={res['n_remaining']})")
    return "\n".join(lines)


def run() -> None:
    log.info("=== Regime Audit v1 — auditing V5's own trades, no tuning ===")

    universe = cdata.fetch_universe(top_n=BACKTEST_UNIVERSE_N)
    if not universe:
        log.error("Universe fetch failed — aborting")
        return

    btc_hist_full = cdata.fetch_daily_ohlc(ccfg.BENCHMARK_COIN_ID, days=TOTAL_DAYS)
    if btc_hist_full.empty:
        log.error("BTC history unavailable — aborting")
        return

    coin_histories = {}
    for i, coin in enumerate(universe):
        hist = cdata.fetch_daily_ohlc(coin["id"], days=TOTAL_DAYS)
        if hist.empty or len(hist) < 120:
            continue
        coin_histories[coin["symbol"]] = hist
    log.info(f"{len(coin_histories)} coins with sufficient history")

    def gen_trades(start_idx, end_idx):
        trades = []
        for symbol, hist in coin_histories.items():
            hist_slice = hist.iloc[start_idx:end_idx].reset_index(drop=True)
            btc_slice = btc_hist_full.iloc[start_idx:end_idx].reset_index(drop=True)
            if len(hist_slice) < 60:
                continue
            trades.extend(backtest.backtest_coin_regime_gated(
                symbol, hist_slice, btc_slice, TARGET_REGIME_LABEL, ccfg.LANE_FUSED_MIN))
        return trades

    discovery_trades = gen_trades(0, DISCOVERY_DAYS)
    validation_trades = gen_trades(DISCOVERY_DAYS, TOTAL_DAYS)
    log.info(f"Discovery: {len(discovery_trades)} trades | Validation: {len(validation_trades)} trades")

    # ── Audit 1: backtest mechanics / drawdown ──────────────────────────
    dd_discovery = backtest.compute_risk_adjusted_drawdown(discovery_trades)
    dd_validation = backtest.compute_risk_adjusted_drawdown(validation_trades)
    log.info(f"Drawdown audit [discovery]: {dd_discovery}")
    log.info(f"Drawdown audit [validation]: {dd_validation}")

    # ── Audit 2: regime classifier calibration ───────────────────────────
    # BTC slices for the audit need to align with the FULL history (not
    # the period-local slice) since holding periods can extend past a
    # trade's own entry slice boundary — use full BTC history with
    # entry_idx offsets adjusted to the full-series index.
    for t in discovery_trades:
        t["entry_idx"] = t["entry_idx"]  # already relative to discovery slice, offset 0 — matches btc_hist_full[0:DISCOVERY_DAYS] region
    ra_discovery = backtest.regime_classifier_audit(discovery_trades, btc_hist_full.iloc[0:DISCOVERY_DAYS].reset_index(drop=True))
    # validation trades' entry_idx is relative to the validation slice (0-based within that slice);
    # re-index against the validation-region BTC slice consistently
    ra_validation = backtest.regime_classifier_audit(validation_trades, btc_hist_full.iloc[DISCOVERY_DAYS:TOTAL_DAYS].reset_index(drop=True))
    log.info(f"Regime audit [discovery]: {ra_discovery}")
    log.info(f"Regime audit [validation]: {ra_validation}")

    # ── Audit 3: distribution / top-winner removal ───────────────────────
    wr_discovery = backtest.top_winner_removal_analysis(discovery_trades)
    wr_validation = backtest.top_winner_removal_analysis(validation_trades)
    log.info(f"Winner-removal [discovery]: {wr_discovery}")
    log.info(f"Winner-removal [validation]: {wr_validation}")

    message = (
        f"🔬 <b>Regime Audit v1 — auditing V5's mechanics, NOT a new strategy test</b>\n\n"
        f"═══ 1. BACKTEST MECHANICS (drawdown reality check) ═══\n"
        f"{_fmt_drawdown_audit(dd_discovery, 'Discovery period')}\n\n"
        f"{_fmt_drawdown_audit(dd_validation, 'Validation period')}\n\n"
        f"═══ 2. REGIME CLASSIFIER CALIBRATION ═══\n"
        f"{_fmt_regime_audit(ra_discovery, 'Discovery period')}\n\n"
        f"{_fmt_regime_audit(ra_validation, 'Validation period')}\n\n"
        f"═══ 3. DISTRIBUTION / TOP-WINNER REMOVAL ═══\n"
        f"{_fmt_winner_removal(wr_discovery, 'Discovery period')}\n\n"
        f"{_fmt_winner_removal(wr_validation, 'Validation period')}"
    )
    plain = message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
    log.info(plain)
    send_telegram(message)


if __name__ == "__main__":
    run()
