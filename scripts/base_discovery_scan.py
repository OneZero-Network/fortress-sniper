#!/usr/bin/env python3
"""
FORTRESS_CRYPTO — scripts/base_discovery_scan.py
══════════════════════════════════════════════════════════════════════════════
v4.7 — DEX Outcome + Early-Detection Engine. Resolves matured first-seen
pairs first (same discipline as the Pearl flywheel), then scans for new
candidates, captures the FULL first-seen snapshot (per explicit
instruction — "we need to know exactly what Fortress knew at the moment
of discovery"), and only surfaces 🚨 DEX EARLY MOVE prominently when ALL
convergence conditions are met — everything else stays logged/tracked
without flooding Telegram.
"""
from __future__ import annotations
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.telegram import send as send_telegram
from core.db import init_crypto_tables, log_dex_first_seen, get_dex_lead_time_vs_coingecko
from core.crypto import dexscreener
from core.crypto import dex_flywheel
from core.crypto import pearl_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                     datefmt="%H:%M:%S")
log = logging.getLogger("fortress.crypto.base_discovery")


def run() -> None:
    log.info("=== Base DEX Discovery v4.7 ===")
    init_crypto_tables()

    flywheel_result = dex_flywheel.resolve_matured_dex_pairs()
    log.info(f"DEX flywheel: {flywheel_result}")

    seed_tokens = dexscreener.fetch_boosted_base_tokens(limit=30)
    log.info(f"Discovery seed: {len(seed_tokens)} boosted Base token(s)")

    early_moves = []
    other_candidates = []
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
            continue

        flow = dexscreener.compute_flow_signals(pair)
        accel = dexscreener.compute_acceleration(pair)
        age_hours = dexscreener.compute_pair_age_hours(pair)
        security = dexscreener.check_dex_security(pair)
        snapshot = dexscreener.adapt_to_coin_snapshot(pair)
        status = dexscreener.classify_base_radar_status(viability, flow, security, age_hours)

        pair_address = pair.get("pairAddress")
        symbol = snapshot["symbol"]
        txns_24h = (pair.get("txns") or {}).get("h24") or {}

        if pair_address:
            was_new = log_dex_first_seen(
                pair_address, symbol, "base", snapshot["price"], viability["liquidity_usd"],
                viability["volume_24h_usd"], txns_24h.get("buys"), txns_24h.get("sells"),
                age_hours, accel.get("vol_accel_ratio"), flow["flow_label"], security["severity"])
            if was_new:
                new_detections += 1

        if status["label"] == "🚫 HIGH RISK":
            blocked.append({"snapshot": snapshot, "status": status})
            continue

        scored = pearl_score.compute_pearl_score(
            symbol, snapshot, None, None, {"severity": "UNCHECKED"}, None)
        early_move = dexscreener.classify_dex_early_move(viability, flow, accel, age_hours, security)

        entry = {"snapshot": snapshot, "flow": flow, "accel": accel, "age_hours": age_hours,
                 "status": status, "scored": scored, "early_move": early_move, "pair_address": pair_address}
        if early_move["is_early_move"]:
            early_moves.append(entry)
        else:
            other_candidates.append(entry)

    log.info(f"Early moves: {len(early_moves)}, other candidates: {len(other_candidates)}, "
             f"blocked: {len(blocked)}, filtered: {filtered_out}, new detections: {new_detections}")

    if not early_moves and not other_candidates and not blocked:
        message = (f"🧭 <b>Base DEX Discovery</b>\n\n"
                   f"Scanned {len(seed_tokens)} boosted Base token(s), 0 passed viability filters. "
                   f"Legitimate outcome — ran successfully, found nothing worth surfacing today.")
        log.info(message.replace("<b>", "").replace("</b>", ""))
        send_telegram(message)
        return

    lines = [f"🧭 <b>Base DEX Discovery</b>"]

    if early_moves:
        lines.append(f"\n🚨 <b>DEX EARLY MOVE ({len(early_moves)})</b> — all convergence conditions met")
        for e in early_moves[:5]:
            snap = e["snapshot"]
            lead = get_dex_lead_time_vs_coingecko(snap["symbol"])
            lead_note = f"\n   {lead['detail']}" if lead.get("available") else ""
            lines.append(
                f"<b>{snap['symbol']}</b>\n"
                f"   Fresh DEX activity + accelerating volume + strong buy imbalance\n"
                f"   Security: {e['status']['detail'].split(';')[0] if 'flags' not in e['status'] else 'checked'}\n"
                f"   Evidence: incomplete | First seen: this scan{lead_note}\n"
                f"   <i>Not a buy signal.</i>\n"
            )

    lines.append(f"\n<i>Scanned {len(seed_tokens)} | Early moves: {len(early_moves)} | "
                 f"Other candidates: {len(other_candidates)} (tracked, not surfaced) | "
                 f"Blocked (security): {len(blocked)} | New detections: {new_detections}</i>")

    if blocked:
        lines.append(f"\n🚫 <b>Blocked ({len(blocked)})</b> — security check failed")
        for b in blocked[:3]:
            lines.append(f"   {b['snapshot']['symbol']}: {b['status']['detail']}")

    message = "\n".join(lines)
    plain = message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
    log.info(plain)
    send_telegram(message)


if __name__ == "__main__":
    run()
