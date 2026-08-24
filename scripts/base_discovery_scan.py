#!/usr/bin/env python3
"""
FORTRESS_CRYPTO — scripts/base_discovery_scan.py
══════════════════════════════════════════════════════════════════════════════
v4.7.1 — Base Universe Expansion. Fixes the finding from v4.7's first
real run: the discovery seed was ONE curated feed (token-boosts) and
returned exactly 1 token — too narrow to be a real "Base discovery"
experiment. Now combines THREE independent discovery sources (boosted,
profiled, search-based), deduplicates, and reports the FULL funnel so
the actual coverage question is answerable: pairs discovered → unique
tokens → after liquidity → after activity → after security →
early-move candidates.

Boosted tokens remain a separate, labeled source (per explicit
instruction) rather than the whole universe — this lets a later
analysis ask "which discovery channel actually finds good candidates,"
not just "did we find anything."

Ordering, per explicit instruction: discovery → security → activity →
Pearl. NOT discovery → Pearl → security afterward.
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


def _gather_universe() -> list:
    """Combines all discovery sources into one deduplicated pair list.
    Boost/profile sources return token stubs needing a fetch_pair_data
    follow-up; search returns full pair objects directly."""
    all_pairs = []

    boosted = dexscreener.fetch_boosted_base_tokens(limit=30)
    log.info(f"Source BOOSTED: {len(boosted)} token(s)")
    for t in boosted:
        addr = t.get("tokenAddress")
        if not addr:
            continue
        pair = dexscreener.fetch_pair_data(addr, chain="base")
        if pair:
            pair["_source"] = "BOOSTED"
            all_pairs.append(pair)

    profiled = dexscreener.fetch_profiled_base_tokens(limit=30)
    log.info(f"Source PROFILED: {len(profiled)} token(s)")
    for t in profiled:
        addr = t.get("tokenAddress")
        if not addr:
            continue
        pair = dexscreener.fetch_pair_data(addr, chain="base")
        if pair:
            pair["_source"] = "PROFILED"
            all_pairs.append(pair)

    search_pairs = dexscreener.fetch_search_base_pairs(["WETH", "USDC"])
    log.info(f"Source SEARCH: {len(search_pairs)} pair(s)")
    all_pairs.extend(search_pairs)

    deduped = dexscreener.dedupe_pairs_by_address(all_pairs)
    log.info(f"Total pairs discovered: {len(all_pairs)}, unique after dedup: {len(deduped)}")
    return deduped


def run() -> None:
    log.info("=== Base DEX Discovery v4.7.1 (multi-source universe) ===")
    init_crypto_tables()

    flywheel_result = dex_flywheel.resolve_matured_dex_pairs()
    log.info(f"DEX flywheel: {flywheel_result}")

    all_pairs = _gather_universe()
    unique_tokens = len(set(
        (p.get("baseToken") or {}).get("address") for p in all_pairs
        if (p.get("baseToken") or {}).get("address")))

    # ── funnel, exactly as requested: each stage's survivor count tracked ──
    after_liquidity = []
    for pair in all_pairs:
        if dexscreener.apply_liquidity_filter(pair)["passes"]:
            after_liquidity.append(pair)

    after_activity = []
    for pair in after_liquidity:
        if dexscreener.apply_activity_filter(pair)["passes"]:
            after_activity.append(pair)

    # ── security gate BEFORE momentum/Pearl scoring, per explicit ordering.
    # First-seen is logged for EVERY activity-surviving pair regardless of
    # security outcome (per v4.6's original intent: 'still want to know we
    # detected it, just not surface it as investigable') — only the
    # downstream Pearl scoring / EARLY MOVE classification is gated.
    after_security = []
    blocked = []
    new_detections = 0
    for pair in after_activity:
        security = dexscreener.check_dex_security(pair)
        pair["_security"] = security

        pair_address = pair.get("pairAddress")
        base_token = pair.get("baseToken") or {}
        symbol = (base_token.get("symbol") or "").upper()
        txns_24h = (pair.get("txns") or {}).get("h24") or {}
        liq_usd = (pair.get("liquidity") or {}).get("usd") or 0
        vol_usd = (pair.get("volume") or {}).get("h24") or 0
        accel = dexscreener.compute_acceleration(pair)
        flow = dexscreener.compute_flow_signals(pair)
        age_hours = dexscreener.compute_pair_age_hours(pair)

        if pair_address and symbol:
            was_new = log_dex_first_seen(
                pair_address, symbol, "base", float(pair.get("priceUsd") or 0), liq_usd, vol_usd,
                txns_24h.get("buys"), txns_24h.get("sells"), age_hours,
                accel.get("vol_accel_ratio"), flow["flow_label"], security["severity"])
            if was_new:
                new_detections += 1

        if security["severity"] == "HIGH_RISK":
            blocked.append({"pair": pair, "security": security})
        else:
            after_security.append(pair)

    early_moves = []
    other_candidates = []

    for pair in after_security:
        flow = dexscreener.compute_flow_signals(pair)
        accel = dexscreener.compute_acceleration(pair)
        age_hours = dexscreener.compute_pair_age_hours(pair)
        security = pair["_security"]
        snapshot = dexscreener.adapt_to_coin_snapshot(pair)
        status = dexscreener.classify_base_radar_status(
            {"passes": True, "reasons": []}, flow, security, age_hours)

        pair_address = pair.get("pairAddress")
        symbol = snapshot["symbol"]

        scored = pearl_score.compute_pearl_score(
            symbol, snapshot, None, None, {"severity": "UNCHECKED"}, None)
        early_move = dexscreener.classify_dex_early_move(
            {"passes": True}, flow, accel, age_hours, security)

        entry = {"snapshot": snapshot, "source": pair.get("_source", "?"), "scored": scored,
                 "early_move": early_move, "pair_address": pair_address}
        if early_move["is_early_move"]:
            early_moves.append(entry)
        else:
            other_candidates.append(entry)

    log.info(f"Funnel: discovered={len(all_pairs)}, unique_tokens={unique_tokens}, "
             f"after_liquidity={len(after_liquidity)}, after_activity={len(after_activity)}, "
             f"after_security={len(after_security)}, blocked={len(blocked)}, "
             f"early_moves={len(early_moves)}, new_detections={new_detections}")

    lines = [
        f"🧭 <b>Base DEX Discovery</b>\n",
        f"Pairs discovered: {len(all_pairs)}",
        f"Unique tokens: {unique_tokens}",
        f"After liquidity filter: {len(after_liquidity)}",
        f"After activity filter: {len(after_activity)}",
        f"After security filter: {len(after_security)} ({len(blocked)} blocked)",
        f"Early-move candidates: {len(early_moves)}",
        f"New detections: {new_detections}\n",
    ]

    if early_moves:
        lines.append(f"🚨 <b>DEX EARLY MOVE ({len(early_moves)})</b>")
        for e in early_moves[:5]:
            snap = e["snapshot"]
            lead = get_dex_lead_time_vs_coingecko(snap["symbol"])
            lead_note = f" | {lead['detail']}" if lead.get("available") else ""
            lines.append(f"<b>{snap['symbol']}</b> [{e['source']}]{lead_note}\n"
                         f"   Fresh DEX activity + accelerating volume + strong buy imbalance\n"
                         f"   <i>Not a buy signal.</i>")
    else:
        lines.append(f"No early-move candidates this scan. That's a legitimate outcome for a "
                     f"single hourly snapshot — not evidence Base lacks opportunities.")

    lines.append(f"\n<i>Ordering: discovery → security → activity → Pearl engine. "
                 f"{len(blocked)} blocked by security before ever reaching scoring.</i>")

    message = "\n".join(lines)
    plain = message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
    log.info(plain)
    send_telegram(message)


if __name__ == "__main__":
    run()
