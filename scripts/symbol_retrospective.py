#!/usr/bin/env python3
"""
FORTRESS_CRYPTO — scripts/symbol_retrospective.py
══════════════════════════════════════════════════════════════════════════════
v4.5 — Reconstructs the full observation history for one symbol (e.g.
PONS) from crypto_pearl_observations — every time Fortress saw it,
what score/tier/pearl_type it got, and how it resolved forward. This
does NOT change scoring; it's a read-only retrospective query.

Answers the specific test your mentor proposed: "would Fortress have
classified PONS as an Early Pearl 24 hours before the +80% move?" — by
showing exactly what was logged and when, in chronological order.

Usage: SYMBOL=PONS python scripts/symbol_retrospective.py
"""
from __future__ import annotations
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.telegram import send as send_telegram
from core.db import init_crypto_tables, get_conn

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                     datefmt="%H:%M:%S")
log = logging.getLogger("fortress.crypto.retrospective")

SYMBOL = os.getenv("SYMBOL", "PONS").upper()


def run() -> None:
    log.info(f"=== Retrospective: {SYMBOL} ===")
    init_crypto_tables()

    cols = ["id", "observed_at", "price_at_observation", "discovery_score", "evidence_label",
            "tier_at_discovery", "pearl_type_at_discovery", "why_it_surfaced",
            "invalidation_conditions", "lifecycle_state", "failure_reason",
            "return_24h_pct", "return_3d_pct", "return_7d_pct", "resolved_24h", "resolved_3d", "resolved_7d"]
    with get_conn() as con:
        rows = con.execute(
            f"SELECT {', '.join(cols)} FROM crypto_pearl_observations WHERE symbol = ? ORDER BY observed_at ASC",
            (SYMBOL,)
        ).fetchall()

    observations = [dict(zip(cols, r)) for r in rows]
    log.info(f"Found {len(observations)} observation(s) for {SYMBOL}")

    if not observations:
        message = (f"🔍 <b>Retrospective: {SYMBOL}</b>\n\n"
                   f"No observations found for {SYMBOL} in crypto_pearl_observations. This means "
                   f"either: (a) {SYMBOL} was never scanned by Fortress (not in the CoinGecko universe, "
                   f"or below the liquidity floor for its tier), or (b) it was scanned but never reached "
                   f"CANDIDATE tier or above, so no snapshot was ever logged. Either way, this is an "
                   f"honest 'we don't know' rather than a fabricated answer.")
        log.info(message.replace("<b>", "").replace("</b>", ""))
        send_telegram(message)
        return

    lines = [f"🔍 <b>Retrospective: {SYMBOL}</b> ({len(observations)} observation(s))\n"]
    for obs in observations:
        price = f"${obs['price_at_observation']:.6f}" if obs["price_at_observation"] else "n/a"
        lines.append(
            f"📅 {obs['observed_at']}\n"
            f"   Price: {price} | Discovery: {obs['discovery_score']} | "
            f"Tier: {obs['tier_at_discovery']} | Type: {obs['pearl_type_at_discovery'] or 'n/a'}\n"
            f"   Why it surfaced: {obs['why_it_surfaced']}\n"
            f"   Lifecycle: {obs['lifecycle_state']}"
            + (f" ({obs['failure_reason']})" if obs.get("failure_reason") else "")
        )
        if obs["resolved_24h"]:
            lines.append(f"   → 24h return: {obs['return_24h_pct']:+.1f}%")
        if obs["resolved_7d"]:
            lines.append(f"   → 7d return: {obs['return_7d_pct']:+.1f}%")
        lines.append("")

    # The specific test: was there an observation ~24h before the most
    # recent one, and what did it say?
    if len(observations) >= 2:
        first, last = observations[0], observations[-1]
        lines.append(f"<b>First vs most recent observation</b>\n"
                     f"First seen: {first['observed_at']} — Discovery {first['discovery_score']}, "
                     f"Type {first['pearl_type_at_discovery'] or 'n/a'}\n"
                     f"Most recent: {last['observed_at']} — Discovery {last['discovery_score']}, "
                     f"Type {last['pearl_type_at_discovery'] or 'n/a'}")
        if first["pearl_type_at_discovery"] == "💎 EARLY PEARL":
            lines.append(f"\n✅ {SYMBOL} WAS classified as an Early Pearl at its first appearance — "
                         f"this is exactly the kind of evidence that would support the discovery "
                         f"hypothesis if the subsequent price action confirms it.")

    message = "\n".join(lines)
    plain = message.replace("<b>", "").replace("</b>", "")
    log.info(plain)
    send_telegram(message)


if __name__ == "__main__":
    run()
