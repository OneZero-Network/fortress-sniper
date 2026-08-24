#!/usr/bin/env python3
"""
FORTRESS_CRYPTO — scripts/pearl_validation_report.py
══════════════════════════════════════════════════════════════════════════════
v4.4 — Pearl Validation Report. The deliverable explicitly requested:
"That report is far more valuable than another version number."

Run this manually whenever you want a fresh read — it changes nothing,
tunes nothing, only reports on what the (frozen) scoring has actually
produced and how it resolved.

HONEST SCOPE, stated directly: this report covers what's actually
buildable from data already being logged — Early Pearl / Emergence /
Momentum outcome buckets, Emergence→Early Pearl conversion, and radar
persistence. It does NOT include the Random/Volume/Momentum BASELINE
comparison your mentor also requested — that needs a separate forward-
collecting observer (recording what a naive random-5 or volume-top-5
selection would have returned over the same period), which does not
exist yet and cannot be reconstructed retroactively from data that was
never logged for the full unselected universe. Flagged as the next real
gap, not silently skipped.
"""
from __future__ import annotations
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.telegram import send as send_telegram
from core.db import (init_crypto_tables, get_pearl_type_outcomes, get_emergence_conversion_rate,
                      get_daily_metrics_by_period)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                     datefmt="%H:%M:%S")
log = logging.getLogger("fortress.crypto.validation_report")

DAYS_BACK = int(os.getenv("CRYPTO_VALIDATION_DAYS", "14"))
PERIOD_LABEL = os.getenv("CRYPTO_BASELINE_LABEL", "FREE_BASELINE")


def _fmt_pct(v) -> str:
    return f"{v}%" if v is not None else "n/a (no resolved data yet)"


def run() -> None:
    log.info(f"=== Pearl Validation Report — last {DAYS_BACK} days ===")
    init_crypto_tables()

    daily_rows = get_daily_metrics_by_period(PERIOD_LABEL)
    recent_days = daily_rows[-DAYS_BACK:] if len(daily_rows) > DAYS_BACK else daily_rows
    total_scanned = sum(r["assets_scanned"] or 0 for r in recent_days)

    outcomes = get_pearl_type_outcomes(DAYS_BACK)
    conversion = get_emergence_conversion_rate(DAYS_BACK)

    log.info(f"Days of daily_metrics available: {len(recent_days)}")
    log.info(f"Pearl type outcomes: {outcomes}")
    log.info(f"Emergence conversion: {conversion}")

    lines = [
        f"💎 <b>Fortress Pearl Validation Report</b>",
        f"<i>Period: last {DAYS_BACK} days ({len(recent_days)} day(s) of data available)</i>\n",
        f"Assets scanned (cumulative): {total_scanned}",
    ]

    lines.append("\n<b>Outcomes by discovery type</b>")
    for ptype in ("💎 EARLY PEARL", "⚡ EMERGENCE ALERT", "🚀 MOMENTUM BREAKOUT"):
        stats = outcomes.get(ptype)
        if not stats:
            lines.append(f"   {ptype}: no discoveries in this period yet")
            continue
        warn = " ⚠️ small sample" if stats["n_discovered"] < 10 else ""
        lines.append(
            f"   {ptype} (n={stats['n_discovered']}, {stats['n_resolved_7d']} resolved at 7d){warn}\n"
            f"      +20% within 7d: {_fmt_pct(stats['pct_hit_20'])} | "
            f"+10% within 7d: {_fmt_pct(stats['pct_hit_10'])}\n"
            f"      Thesis held: {_fmt_pct(stats['pct_held_thesis'])} | "
            f"Invalidated: {_fmt_pct(stats['pct_invalidated'])}"
        )

    lines.append(f"\n<b>Emergence → Early Pearl conversion</b>")
    if conversion["n_emergence_first_seen"] > 0:
        lines.append(f"   {conversion['n_converted']}/{conversion['n_emergence_first_seen']} "
                     f"Emergence Alerts later became an Early Pearl or High-Potential "
                     f"({_fmt_pct(conversion['conversion_rate_pct'])})")
    else:
        lines.append("   No Emergence Alerts logged yet in this period")

    lines.append(f"\n<b>⚠️ Known gap — no baseline comparison yet</b>\n"
                 f"This report does NOT yet compare Fortress's picks against a Random-5, "
                 f"Volume-Top-5, or simple-Momentum-5 baseline from the same universe — that "
                 f"needs a separate forward-collecting observer that does not exist yet. "
                 f"Without it, we cannot yet say whether these outcomes beat doing nothing "
                 f"clever at all.")

    lines.append(f"\n<i>Scoring remains frozen. This is a report, not a recommendation.</i>")

    message = "\n".join(lines)
    plain = message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
    log.info(plain)
    send_telegram(message)


if __name__ == "__main__":
    run()
