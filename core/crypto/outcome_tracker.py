"""
FORTRESS_CRYPTO — core/crypto/outcome_tracker.py
══════════════════════════════════════════════════════════════════════════════
The core of the "learn from failure" flywheel your mentor asked for:

    Signal → Prediction → Actual outcome → Why it failed → Market regime
    → Features responsible → Model update

This module is steps 2-4. Every OPEN signal (logged at alert time by
core/db.py:log_signal()) is checked here against CURRENT live price:

  - live price <= stop_loss           -> LOSS_STOP
  - live price >= r2                  -> WIN_T2 (full target)
  - live price >= r1                  -> WIN_T1 (partial target)
  - > SIGNAL_TIMEOUT_DAYS elapsed, none of the above -> TIMEOUT (neither
    won nor lost cleanly — this is itself useful signal: a setup that
    goes nowhere is informative, not just "no result")

On resolution, failure_reason is populated for LOSS_STOP/TIMEOUT using
whatever we can actually observe (trend flipped? news turned bearish?
nothing changed, just ranged?) — kept simple and honest rather than
inventing a cause we can't actually verify.

Step 6 "Model update" is DELIBERATELY NOT automated here — auto-adjusting
thresholds based on a small sample size is how systems overfit to noise.
signal_stats() surfaces the numbers (hit rate, sample size, avg return);
a human reviews them and decides whether a real config change is
warranted. That's a decision, not a formula, until sample sizes are much
larger than what a new system produces in its first weeks.
"""
from __future__ import annotations
import logging
from datetime import datetime

from ..db import get_open_signals, resolve_signal, signal_stats
from . import data as cdata

log = logging.getLogger("fortress.crypto.outcomes")

SIGNAL_TIMEOUT_DAYS = 21  # if neither stop nor target hit within 3 weeks, call it a TIMEOUT


def check_and_resolve_open_signals() -> dict:
    """Run at the START of every sniper daily run, before scoring new
    candidates — so today's alert reflects yesterday's resolved outcomes,
    not stale open positions. Returns a summary dict for logging/Telegram."""
    open_signals = get_open_signals()
    resolved = {"WIN_T1": 0, "WIN_T2": 0, "LOSS_STOP": 0, "TIMEOUT": 0}
    still_open = 0

    for sig in open_signals:
        try:
            live = cdata.fetch_live_price_binance(sig["symbol"])
            if live is None:
                still_open += 1
                continue

            created = datetime.strptime(sig["created_at"], "%Y-%m-%d %H:%M:%S")
            days_held = round((datetime.now() - created).total_seconds() / 86400, 2)
            entry = sig["entry_price"]

            if live <= sig["stop_loss"]:
                pnl = round(100.0 * (live - entry) / entry, 2)
                resolve_signal(sig["id"], "LOSS_STOP", live, pnl, days_held,
                                failure_reason=f"stop hit; trend was '{sig.get('trend_label')}', "
                                                f"news was '{sig.get('news_label')}' at signal time")
                resolved["LOSS_STOP"] += 1
            elif live >= sig["r2"]:
                pnl = round(100.0 * (live - entry) / entry, 2)
                resolve_signal(sig["id"], "WIN_T2", live, pnl, days_held)
                resolved["WIN_T2"] += 1
            elif live >= sig["r1"]:
                # Partial win — T1 reached. Left OPEN so T2 can still be
                # tracked, but this is worth knowing at a glance; caller
                # can inspect crypto_signal_log directly for T1-touched
                # rows if finer-grained tracking is wanted later.
                still_open += 1
            elif days_held > SIGNAL_TIMEOUT_DAYS:
                pnl = round(100.0 * (live - entry) / entry, 2)
                resolve_signal(sig["id"], "TIMEOUT", live, pnl, days_held,
                                failure_reason=f"neither stop nor target hit within {SIGNAL_TIMEOUT_DAYS}d — "
                                                f"setup went nowhere, not a clean win or loss")
                resolved["TIMEOUT"] += 1
            else:
                still_open += 1
        except Exception as e:
            log.warning(f"outcome check failed for signal {sig.get('id')} ({sig.get('symbol')}): {e}")
            still_open += 1

    total_resolved = sum(resolved.values())
    log.info(f"Outcome tracker: {total_resolved} signal(s) resolved "
             f"(WIN_T2={resolved['WIN_T2']}, WIN_T1_final=0, LOSS_STOP={resolved['LOSS_STOP']}, "
             f"TIMEOUT={resolved['TIMEOUT']}), {still_open} still open")
    return {"resolved": resolved, "still_open": still_open, "total_resolved": total_resolved}


def format_stats_summary(lookback_days: int = 30) -> str:
    """Human-readable block for the Telegram alert — the honest numbers
    behind any 'X% win rate' claim, with sample-size caveats front and
    center rather than buried."""
    stats = signal_stats(lookback_days)
    if not stats:
        return f"📊 No resolved signals in the last {lookback_days}d yet — flywheel is still collecting data."

    lines = [f"📊 <b>Track record (last {lookback_days}d)</b>"]
    for tier, s in stats.items():
        warn = " ⚠️ small sample, treat as noise" if s["low_sample_warning"] else ""
        hit = f"{s['hit_rate_pct']}%" if s["hit_rate_pct"] is not None else "n/a"
        avg = f"{s['avg_pnl_pct']:+.1f}%" if s["avg_pnl_pct"] is not None else "n/a"
        lines.append(f"   {tier}: n={s['sample_size']}, hit rate {hit}, avg return {avg}{warn}")
    return "\n".join(lines)
