#!/usr/bin/env python3
"""
FORTRESS_CRYPTO — scripts/pearl_metrics_report.py
══════════════════════════════════════════════════════════════════════════════
v3.1 — Weekly rollup report. Compares two data periods (default:
FREE_BASELINE vs whatever CRYPTO_DATA_PERIOD_LABEL is set to during an
active experiment) and reports the exact metric table specified, plus
the quality check that matters most: does a higher tier actually
resolve better forward, or is it just relabeling.

Run this manually whenever you want a rollup — it's a report generator,
not a job that changes anything.
"""
from __future__ import annotations
import logging
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.telegram import send as send_telegram
from core.db import get_daily_metrics_by_period, get_pearl_quality_by_tier

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                     datefmt="%H:%M:%S")
log = logging.getLogger("fortress.crypto.pearl_metrics_report")

BASELINE_LABEL = os.getenv("CRYPTO_BASELINE_LABEL", "FREE_BASELINE")
COMPARISON_LABEL = os.getenv("CRYPTO_COMPARISON_LABEL", "")  # empty = baseline-only report


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return round(float(np.mean(vals)), 2) if vals else None


def _rollup(rows: list) -> dict:
    if not rows:
        return {"n_days": 0}
    return {
        "n_days": len(rows),
        "avg_completeness": _avg([r["avg_completeness_pct"] for r in rows]),
        "median_completeness": _avg([r["median_completeness_pct"] for r in rows]),
        "high_potential_per_day": _avg([r["high_potential_count"] for r in rows]),
        "pearls_per_day": _avg([r["pearl_count"] for r in rows]),
        "false_pearls_per_day": _avg([r["false_pearl_count"] for r in rows]),
        "assets_evaluated_per_day": _avg([r["entered_scorer"] for r in rows]),
        "missing_data_rate_pct": _avg([100.0 * r["missing_data_rejection_count"] / r["assets_scanned"]
                                        if r["assets_scanned"] else None for r in rows]),
        "avg_discovery_score": _avg([r["avg_discovery_score"] for r in rows]),
    }


def _fmt_row(label: str, baseline_val, comparison_val=None) -> str:
    b = f"{baseline_val}" if baseline_val is not None else "—"
    if comparison_val is not None or COMPARISON_LABEL:
        c = f"{comparison_val}" if comparison_val is not None else "—"
        return f"{label}: {b} → {c}"
    return f"{label}: {b}"


def run() -> None:
    log.info(f"=== Pearl Metrics Weekly Rollup: {BASELINE_LABEL}" +
             (f" vs {COMPARISON_LABEL}" if COMPARISON_LABEL else " (baseline only)") + " ===")

    baseline_rows = get_daily_metrics_by_period(BASELINE_LABEL)
    baseline = _rollup(baseline_rows)
    log.info(f"Baseline ({BASELINE_LABEL}): {baseline}")

    comparison = None
    if COMPARISON_LABEL:
        comparison_rows = get_daily_metrics_by_period(COMPARISON_LABEL)
        comparison = _rollup(comparison_rows)
        log.info(f"Comparison ({COMPARISON_LABEL}): {comparison}")

    quality = get_pearl_quality_by_tier()
    log.info(f"Pearl quality by tier: {quality}")

    lines = [f"📊 <b>Pearl Metrics Weekly Rollup</b>"]
    if comparison:
        lines.append(f"<i>{BASELINE_LABEL} ({baseline['n_days']} days) vs {COMPARISON_LABEL} ({comparison['n_days']} days)</i>\n")
    else:
        lines.append(f"<i>{BASELINE_LABEL} — {baseline['n_days']} day(s) tracked so far</i>\n")

    if baseline["n_days"] == 0:
        lines.append("No days tracked yet for this period label.")
    else:
        c = comparison or {}
        lines.append(_fmt_row("Avg completeness", baseline.get("avg_completeness"), c.get("avg_completeness")))
        lines.append(_fmt_row("Median completeness", baseline.get("median_completeness"), c.get("median_completeness")))
        lines.append(_fmt_row("High-Potential/day", baseline.get("high_potential_per_day"), c.get("high_potential_per_day")))
        lines.append(_fmt_row("Pearls/day", baseline.get("pearls_per_day"), c.get("pearls_per_day")))
        lines.append(_fmt_row("False Pearls/day", baseline.get("false_pearls_per_day"), c.get("false_pearls_per_day")))
        lines.append(_fmt_row("Assets evaluated/day", baseline.get("assets_evaluated_per_day"), c.get("assets_evaluated_per_day")))
        lines.append(_fmt_row("Missing-data rate", baseline.get("missing_data_rate_pct"), c.get("missing_data_rate_pct")))
        lines.append(_fmt_row("Avg discovery score", baseline.get("avg_discovery_score"), c.get("avg_discovery_score")))

    lines.append("\n<b>Pearl Quality by Tier</b> (does a higher tier actually resolve better?)")
    if not quality:
        lines.append("   No resolved observations with a recorded tier yet.")
    else:
        for tier in ("PEARL", "HIGH_POTENTIAL", "CANDIDATE", "WATCH"):
            q = quality.get(tier)
            if not q:
                continue
            r24 = f"{q['avg_return_24h']:+.1f}%" if q["avg_return_24h"] is not None else "n/a"
            r3d = f"{q['avg_return_3d']:+.1f}%" if q["avg_return_3d"] is not None else "n/a"
            r7d = f"{q['avg_return_7d']:+.1f}%" if q["avg_return_7d"] is not None else "n/a"
            lines.append(f"   {tier} (n={q['n']}, {q['invalidated_count']} invalidated): "
                         f"24h {r24} | 3d {r3d} | 7d {r7d}")

    message = "\n".join(lines)
    plain = message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
    log.info(plain)
    send_telegram(message)


if __name__ == "__main__":
    run()
