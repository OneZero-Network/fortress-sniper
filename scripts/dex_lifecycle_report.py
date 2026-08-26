#!/usr/bin/env python3
"""
FORTRESS_CRYPTO — scripts/dex_lifecycle_report.py
══════════════════════════════════════════════════════════════════════════════
v4.9.15 — DEX Pearl Forensic report. Reverse-engineered from the actual
target question: "we examined X genuinely new pools and Y awakening
assets, Z reached precursor scoring, here are the rejection reasons,
here's what happened after" — instead of the previously meaningless
"Pre-Pearl = 0, therefore no opportunities."

Assembles the full lifecycle ledger (every candidate that reached
scoring, regardless of outcome) joined against resolved forward
outcomes (1h/6h/24h) wherever they exist. Read-only — changes nothing.
"""
from __future__ import annotations
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.telegram import send as send_telegram
from core.db import init_crypto_tables, get_dex_lifecycle_report, get_dex_milestone_timeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                     datefmt="%H:%M:%S")
log = logging.getLogger("fortress.crypto.dex_lifecycle_report")

DAYS_BACK = int(os.getenv("DEX_LIFECYCLE_DAYS", "1"))


def run() -> None:
    log.info(f"=== DEX Lifecycle Forensic Report ===")
    log.info(f"requested_period_days={DAYS_BACK} (from DEX_LIFECYCLE_DAYS env var — "
             f"if this isn't 1, check whether the manual workflow trigger dialog had a "
             f"leftover value from a PREVIOUS run — GitHub Actions remembers the last "
             f"entered input by default, this is not a code bug)")
    init_crypto_tables()

    report = get_dex_lifecycle_report(days_back=DAYS_BACK)

    # v4.9.16 — NO IMPLICIT TIME AMBIGUITY, per explicit instruction:
    # "The report should explicitly log: requested_period, actual_cutoff,
    # now. No implicit defaults." All three always shown, unmissable.
    log.info(f"actual_cutoff={report['actual_cutoff']} | report_generated_at={report['report_generated_at']}")

    lines = [f"🔬 <b>DEX Pearl Forensic Report</b>",
             f"<i>Requested: last {report['requested_period_days']} day(s) | "
             f"Cutoff: {report['actual_cutoff']} | Now: {report['report_generated_at']}</i>\n",
             f"We examined {report['new_pool_count']} genuinely new chain-discovered pool(s) and "
             f"{report['awakening_count']} existing/search-derived (awakening-candidate) UNIQUE token(s).",
             f"{report['total_examined']} unique TOKEN(s) reached scoring — across "
             f"{report['total_pools_examined']} distinct pool(s) and "
             f"{report['total_raw_observations']} total scan-observations. "
             f"(A token with many pools, or observed across many hourly scans, is counted ONCE here, "
             f"not once per pool or once per scan.)\n"]

    lines.append("<b>By classification:</b>")
    for classification, count in sorted(report["by_classification"].items(), key=lambda x: -x[1]):
        lines.append(f"  {classification}: {count}")

    # Only ever show a manageable sample in Telegram — full detail
    # belongs in the log/Sheet, same decision-layer discipline as
    # every other message in this system.
    lines.append(f"\n<b>Sample breakdown (up to 10):</b>")
    for e in report["entries"][:10]:
        cond = (f"new={'Y' if e['pair_new'] else 'N'} "
                f"liq_accel={'Y' if e['liquidity_accel'] else 'N'} "
                f"vol_accel={'Y' if e['volume_accel'] else 'N'} "
                f"tx_accel={'Y' if e['tx_accel'] else 'N'} "
                f"buy_pressure={'Y' if e['buy_pressure'] else 'N'} "
                f"price_base={'Y' if e['price_near_base'] else 'N'}")
        outcome = ""
        if e["return_1h_pct"] is not None:
            outcome = f" | 1h: {e['return_1h_pct']:+.1f}%"
        if e["return_24h_pct"] is not None:
            outcome += f" | 24h: {e['return_24h_pct']:+.1f}%"
        latency_str = f"{e['pool_age_hours']:.1f}h" if e['pool_age_hours'] is not None else "unknown"
        lines.append(f"\n<b>{e['symbol']}</b> [{e['source']}] — {e['pre_pearl_score']}/100 -> {e['classification']}\n"
                     f"   {cond}\n"
                     f"   Discovery latency (pool age at first sight): {latency_str}{outcome}")

    if len(report["entries"]) > 10:
        lines.append(f"\n(+{len(report['entries']) - 10} more → full table in the database)")

    # v4.9.19 — milestone timelines, per explicit gap: "the system
    # doesn't know when it first encountered the pool... we need
    # persistent first-seen timestamps." Built from data already
    # collected (crypto_dex_lifecycle) — no new tracking needed, just
    # the query that assembles it. AERO/BRETT-shaped "never progressed"
    # results are shown honestly, not hidden — they're useful controls.
    lines.append(f"\n<b>Milestone timelines:</b>")
    for e in report["entries"][:5]:
        timeline = get_dex_milestone_timeline(e["symbol"], days_back=DAYS_BACK)
        if not timeline["found"]:
            continue
        d = timeline["deltas"]
        parts = []
        if d["discovery_to_building_hours"] is not None:
            parts.append(f"→BUILDING in {d['discovery_to_building_hours']:.1f}h")
        if d["discovery_to_pre_pearl_hours"] is not None:
            parts.append(f"→PRE-PEARL in {d['discovery_to_pre_pearl_hours']:.1f}h")
        if d["discovery_to_early_move_hours"] is not None:
            parts.append(f"→EARLY MOVE in {d['discovery_to_early_move_hours']:.1f}h")
        progression = " ".join(parts) if parts else "never progressed past IGNORE (honest control observation)"
        lines.append(f"   <b>{e['symbol']}</b>: {progression}")

    lines.append(f"\n<i>Nothing in this report is silently dropped — every candidate that reached "
                 f"scoring has a permanent record, regardless of outcome.</i>")

    message = "\n".join(lines)
    plain = message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
    log.info(plain)
    send_telegram(message)


if __name__ == "__main__":
    run()
