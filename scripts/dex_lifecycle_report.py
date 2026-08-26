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
from core.db import init_crypto_tables, get_dex_lifecycle_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                     datefmt="%H:%M:%S")
log = logging.getLogger("fortress.crypto.dex_lifecycle_report")

DAYS_BACK = int(os.getenv("DEX_LIFECYCLE_DAYS", "1"))


def run() -> None:
    log.info(f"=== DEX Lifecycle Forensic Report — last {DAYS_BACK} day(s) ===")
    init_crypto_tables()

    report = get_dex_lifecycle_report(days_back=DAYS_BACK)

    lines = [f"🔬 <b>DEX Pearl Forensic Report</b>",
             f"<i>Period: last {DAYS_BACK} day(s)</i>\n",
             f"We examined {report['new_pool_count']} genuinely new chain-discovered pool(s) and "
             f"{report['awakening_count']} existing/search-derived (awakening-candidate) pool(s).",
             f"{report['total_examined']} total reached scoring.\n"]

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
        lines.append(f"\n<b>{e['symbol']}</b> [{e['source']}] — {e['pre_pearl_score']}/90 -> {e['classification']}\n"
                     f"   {cond}\n"
                     f"   Discovery latency (pool age at first sight): {latency_str}{outcome}")

    if len(report["entries"]) > 10:
        lines.append(f"\n(+{len(report['entries']) - 10} more → full table in the database)")

    lines.append(f"\n<i>Nothing in this report is silently dropped — every candidate that reached "
                 f"scoring has a permanent record, regardless of outcome.</i>")

    message = "\n".join(lines)
    plain = message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
    log.info(plain)
    send_telegram(message)


if __name__ == "__main__":
    run()
