#!/usr/bin/env python3
"""
FORTRESS_CRYPTO — scripts/experiment_f1_false_pearl.py
══════════════════════════════════════════════════════════════════════════════
F1 — False-Pearl predictive test. Phase C, independent-layer experiment #1.

THE HONEST DATA LIMITATION, stated up front: GoPlus gives CURRENT
contract security state only — there's no historical risk-flag data to
replay against (same limitation as backtest.py's news/whale gap). So
this is NOT a true forward-predictive test ("did the risk flag AT THE
TIME predict what happened next"). It IS a legitimate CROSS-SECTIONAL
test: "do coins CURRENTLY flagged HIGH_RISK have a track record of worse
historical volatility, deeper drawdowns, and weaker returns than coins
CURRENTLY flagged CLEAN, over the same historical window." That's a
real, useful question — contract risk characteristics (mint authority,
tax structure, LP lock status) tend to be relatively stable properties
of a token, not something that flips week to week, so a current snapshot
correlating with past behavior is informative, just not the same claim
as true forward prediction. Labeled as such everywhere this is reported.

METHOD: for each coin in the universe, compute realized volatility
(daily return std) and max drawdown over the historical window, fetch
CURRENT risk severity, group by severity, compare.
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
from core.crypto import risk_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                     datefmt="%H:%M:%S")
log = logging.getLogger("fortress.crypto.f1")

UNIVERSE_N = int(os.getenv("CRYPTO_F1_UNIVERSE_N", "40"))
DAYS = int(os.getenv("CRYPTO_F1_DAYS", "240"))


def _realized_volatility_pct(hist) -> float:
    """Annualized-ish realized volatility of daily returns (std * sqrt(365)),
    a standard, simple measure — not claiming precision beyond that."""
    close = hist["close"].astype(float)
    daily_returns = close.pct_change().dropna()
    if len(daily_returns) < 10:
        return None
    return round(float(daily_returns.std() * np.sqrt(365) * 100), 2)


def _max_drawdown_pct(hist) -> float:
    close = hist["close"].astype(float).values
    running_max = np.maximum.accumulate(close)
    dd = (close - running_max) / running_max * 100.0
    return round(float(dd.min()), 2)


def _period_return_pct(hist) -> float:
    close = hist["close"].astype(float)
    if len(close) < 2 or close.iloc[0] <= 0:
        return None
    return round(100.0 * (close.iloc[-1] - close.iloc[0]) / close.iloc[0], 2)


def run() -> None:
    log.info("=== F1 — False-Pearl Cross-Sectional Test (NOT forward-predictive — see caveat) ===")
    log.info(f"Universe: top {UNIVERSE_N} coins, {DAYS}-day historical window")

    universe = cdata.fetch_universe(top_n=UNIVERSE_N)
    if not universe:
        log.error("Universe fetch failed — aborting")
        return

    by_severity = {}
    for i, coin in enumerate(universe):
        symbol = coin["symbol"]
        log.info(f"[{i+1}/{len(universe)}] {symbol}...")
        hist = cdata.fetch_daily_ohlc(coin["id"], days=DAYS)
        if hist.empty or len(hist) < 60:
            continue

        try:
            platforms = cdata.fetch_platforms(coin["id"])
            risk = risk_engine.assess_false_pearl_risk(platforms)
            severity = risk.get("severity", "UNCHECKED")
        except Exception as e:
            log.debug(f"risk check failed for {symbol}: {e}")
            severity = "UNCHECKED"

        vol = _realized_volatility_pct(hist)
        dd = _max_drawdown_pct(hist)
        ret = _period_return_pct(hist)
        if vol is None or ret is None:
            continue

        by_severity.setdefault(severity, []).append({
            "symbol": symbol, "volatility_pct": vol, "max_drawdown_pct": dd, "period_return_pct": ret,
        })

    log.info(f"Grouped: {[(k, len(v)) for k, v in by_severity.items()]}")

    lines = [
        "🛡️ <b>F1 — False-Pearl Cross-Sectional Test</b>",
        "<i>NOT forward-predictive (no historical risk-flag data exists). This compares "
        "coins CURRENTLY flagged by severity against their OWN historical volatility/drawdown/return "
        "over the same window — a legitimate but different claim than 'the flag predicted this.'</i>",
        "",
    ]
    for severity in ("CLEAN", "CAUTION", "HIGH_RISK", "UNCHECKED"):
        group = by_severity.get(severity, [])
        if not group:
            lines.append(f"<b>{severity}</b>: no coins in this group")
            continue
        n = len(group)
        avg_vol = round(float(np.mean([g["volatility_pct"] for g in group])), 1)
        avg_dd = round(float(np.mean([g["max_drawdown_pct"] for g in group])), 1)
        avg_ret = round(float(np.mean([g["period_return_pct"] for g in group])), 1)
        warn = " ⚠️ small sample" if n < 10 else ""
        lines.append(f"<b>{severity}</b> (n={n}){warn}: avg volatility {avg_vol}% | "
                     f"avg max drawdown {avg_dd}% | avg {DAYS}d return {avg_ret}%")

    message = "\n".join(lines)
    plain = message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
    log.info(plain)
    send_telegram(message)


if __name__ == "__main__":
    run()
