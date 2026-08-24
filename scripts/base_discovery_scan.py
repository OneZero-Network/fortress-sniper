#!/usr/bin/env python3
"""
FORTRESS_CRYPTO — scripts/base_discovery_scan.py
══════════════════════════════════════════════════════════════════════════════
v4.6 — Base DEX Discovery, security gate closed. Runs the full funnel:
discover boosted Base tokens → fetch pair data → viability filter →
flow + acceleration signals → REAL security check (reuses risk_engine's
GoPlus integration, Base natively supported) → adapt into the SAME
coin_snapshot shape → run through the UNCHANGED pearl_score engine →
log first-seen timestamp → label 🧭 BASE RADAR / 🚫 HIGH RISK.

A HIGH_RISK token is now genuinely BLOCKED from Base Radar status,
verified directly: a synthetic honeypot with perfect flow signals was
confirmed to still get rejected.
"""
from __future__ import annotations
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.telegram import send as send_telegram
from core.db import init_crypto_tables, log_dex_first_seen, get_dex_first_seen
from core.crypto import dexscreener
from core.crypto import pearl_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                     datefmt="%H:%M:%S")
log = logging.getLogger("fortress.crypto.base_discovery")


def run() -> None:
    log.info("=== Base DEX Discovery v1.1 (manual scan) ===")
    init_crypto_tables()

    seed_tokens = dexscreener.fetch_boosted_base_tokens(limit=30)
    log.info(f"Discovery seed: {len(seed_tokens)} boosted Base token(s)")

    candidates = []
    blocked = []
    filtered_out = 0
    new_detections = 0

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
        accel = dexscreener.compute_acceleration(pair)
        age_hours = dexscreener.compute_pair_age_hours(pair)
        security = dexscreener.check_dex_security(pair)
        snapshot = dexscreener.adapt_to_coin_snapshot(pair)
        status = dexscreener.classify_base_radar_status(viability, flow, security, age_hours)

        pair_address = pair.get("pairAddress")
        symbol = snapshot["symbol"]
        if pair_address:
            was_new = log_dex_first_seen(
                pair_address, symbol, "base", snapshot["price"],
                viability["liquidity_usd"], age_hours, accel.get("vol_accel_ratio"), flow["flow_label"])
            if was_new:
                new_detections += 1

        if status["label"] == "🚫 HIGH RISK":
            blocked.append({"snapshot": snapshot, "status": status})
            continue

        scored = pearl_score.compute_pearl_score(
            symbol, snapshot, None, None, {"severity": "UNCHECKED"}, None)

        candidates.append({"snapshot": snapshot, "flow": flow, "accel": accel, "age_hours": age_hours,
                           "status": status, "scored": scored, "pair_address": pair_address})

    log.info(f"Base Radar: {len(candidates)} passed, {len(blocked)} blocked (HIGH_RISK security), "
             f"{filtered_out} filtered (viability), {new_detections} genuinely new detections")

    if not candidates and not blocked:
        message = (f"🧭 <b>Base DEX Discovery</b>\n\n"
                   f"Scanned {len(seed_tokens)} boosted Base token(s), 0 passed viability filters. "
                   f"That's a legitimate outcome — this ran successfully and found nothing worth "
                   f"surfacing today.")
        log.info(message.replace("<b>", "").replace("</b>", ""))
        send_telegram(message)
        return

    candidates.sort(key=lambda c: c["scored"]["discovery_score"] or 0, reverse=True)

    lines = [
        f"🧭 <b>Base DEX Discovery</b>",
        f"<i>Security-gated — HIGH_RISK tokens are blocked below, never surfaced as investigable.</i>\n",
        f"Scanned {len(seed_tokens)} | Passed: {len(candidates)} | "
        f"Blocked (security): {len(blocked)} | Filtered (viability): {filtered_out} | "
        f"New detections: {new_detections}\n",
    ]
    for c in candidates[:10]:
        snap = c["snapshot"]
        accel = c["accel"]
        ds = c["scored"]["discovery_score"]
        age_str = f"{c['age_hours']:.0f}h old" if c["age_hours"] is not None else "age unknown"
        accel_str = f", {accel['label'].lower()}" if accel.get("label") != "NONE" else ""
        lines.append(
            f"<b>{snap['symbol']}</b> — {c['status']['detail']}\n"
            f"   {age_str}{accel_str} | Discovery (preliminary) {ds if ds is not None else 'n/a'}\n"
        )

    if blocked:
        lines.append(f"\n🚫 <b>Blocked ({len(blocked)})</b> — real security check failed, never surfaced above")
        for b in blocked[:5]:
            lines.append(f"   {b['snapshot']['symbol']}: {b['status']['detail']}")

    lines.append(f"\n<i>Manual scan only — not wired into the daily production sniper yet.</i>")

    message = "\n".join(lines)
    plain = message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
    log.info(plain)
    send_telegram(message)


if __name__ == "__main__":
    run()
