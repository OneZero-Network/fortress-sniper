#!/usr/bin/env python3
"""
FORTRESS_CRYPTO — scripts/base_discovery_scan.py
══════════════════════════════════════════════════════════════════════════════
v4.5 — Base DEX Discovery v1, manual-trigger scan. Runs the funnel:
discover boosted Base tokens → fetch pair data → viability filter →
flow signals → adapt into the SAME coin_snapshot shape → run through
the UNCHANGED pearl_score engine → label 🧭 BASE RADAR (never the main
Pearl hierarchy, since Stage 4 false-pearl checking isn't built yet).
"""
from __future__ import annotations
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.telegram import send as send_telegram
from core.crypto import dexscreener
from core.crypto import pearl_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                     datefmt="%H:%M:%S")
log = logging.getLogger("fortress.crypto.base_discovery")


def run() -> None:
    log.info("=== Base DEX Discovery v1 (manual scan) ===")

    seed_tokens = dexscreener.fetch_boosted_base_tokens(limit=30)
    log.info(f"Discovery seed: {len(seed_tokens)} boosted Base token(s)")

    candidates = []
    filtered_out = 0
    for token in seed_tokens:
        address = token.get("tokenAddress")
        if not address:
            continue
        pair = dexscreener.fetch_pair_data(address, chain="base")
        if not pair:
            continue

        viability = dexscreener.apply_viability_filters(pair)
        if not viability["passes"]:
            filtered_out += 1
            log.info(f"Filtered: {(pair.get('baseToken') or {}).get('symbol')} — {viability['reasons']}")
            continue

        flow = dexscreener.compute_flow_signals(pair)
        snapshot = dexscreener.adapt_to_coin_snapshot(pair)
        status = dexscreener.classify_base_radar_status(viability, flow)

        scored = pearl_score.compute_pearl_score(
            snapshot["symbol"], snapshot, None, None, {"severity": "UNCHECKED"}, None)

        candidates.append({"snapshot": snapshot, "flow": flow, "status": status, "scored": scored})

    log.info(f"Base Radar: {len(candidates)} candidate(s) passed viability, {filtered_out} filtered out")

    if not candidates:
        message = (f"🧭 <b>Base DEX Discovery v1</b>\n\n"
                   f"Scanned {len(seed_tokens)} boosted Base token(s), 0 passed viability filters "
                   f"(min ${dexscreener.MIN_LIQUIDITY_USD:,} liquidity, "
                   f"${dexscreener.MIN_VOLUME_24H_USD:,} 24h volume, {dexscreener.MIN_TXNS_24H} txns/24h). "
                   f"That's a legitimate outcome — this ran successfully and found nothing worth surfacing today.")
        log.info(message.replace("<b>", "").replace("</b>", ""))
        send_telegram(message)
        return

    candidates.sort(key=lambda c: c["scored"]["discovery_score"] or 0, reverse=True)

    lines = [
        f"🧭 <b>Base DEX Discovery v1</b>",
        f"<i>⚠️ Preliminary — no false-pearl check exists yet for DEX pairs. "
        f"These are NOT Pearl-hierarchy candidates.</i>\n",
        f"Scanned {len(seed_tokens)} boosted tokens, {len(candidates)} passed viability, {filtered_out} filtered out\n",
    ]
    for c in candidates[:10]:
        snap = c["snapshot"]
        flow = c["flow"]
        ds = c["scored"]["discovery_score"]
        lines.append(
            f"<b>{snap['symbol']}</b> — {c['status']['detail']}\n"
            f"   Liquidity ${snap['market_cap']:,.0f} FDV | Volume ${snap['volume_24h']:,.0f}/24h | "
            f"Discovery (preliminary) {ds if ds is not None else 'n/a'}\n"
        )

    lines.append(f"<i>Manual scan only — not wired into the daily production sniper "
                 f"until the false-pearl gap for DEX pairs is closed.</i>")

    message = "\n".join(lines)
    plain = message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
    log.info(plain)
    send_telegram(message)


if __name__ == "__main__":
    run()
