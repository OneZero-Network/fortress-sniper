#!/usr/bin/env python3
"""
FORTRESS_CRYPTO — scripts/dex_chain_discovery_only.py
══════════════════════════════════════════════════════════════════════════════
v4.9.23 — Discovery Recovery Mode, Phase 1. Per explicit instruction:
"Run a dedicated discovery job... NOT the entire Pearl pipeline. Just:
current block → factories → PoolCreated events → dedupe → store NEW
POOLS." This deliberately does NOT run security/activity/scoring — it
exists to answer exactly one question, fast and cheap: is a genuinely
new pool appearing anywhere on Base right now?

Meant to run frequently (every 10-15 min) via this same manual tool, or
wired into a scheduled job later once its output is trusted.
"""
from __future__ import annotations
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.telegram import send as send_telegram
from core.db import (init_crypto_tables, get_dex_chain_cursor_v2, set_dex_chain_cursor_v2,
                      get_hours_since_last_chain_discovery, log_dex_lifecycle)
from core.crypto import base_chain

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                     datefmt="%H:%M:%S")
log = logging.getLogger("fortress.crypto.dex_chain_discovery_only")


def run() -> None:
    log.info("=== DEX Chain Discovery Only (Phase 1 — no scoring, no security, just discovery) ===")
    init_crypto_tables()

    per_dex_results = {}
    all_new_pools = []
    any_broken = False

    for dex_name in base_chain.DEX_REGISTRY:
        cursor_before = get_dex_chain_cursor_v2(dex_name)
        result = base_chain.discover_new_pools(dex_name, cursor_before)
        set_dex_chain_cursor_v2(dex_name, result["new_cursor"])
        per_dex_results[dex_name] = {
            "status": result["status"], "count": len(result["new_pools"]),
            "cursor_before": cursor_before, "cursor_after": result["new_cursor"],
        }
        if result["status"] == "RPC_ERROR":
            any_broken = True
        for pool in result["new_pools"]:
            pool["_dex"] = dex_name
            all_new_pools.append(pool)
        log.info(f"[{dex_name}] {result['status']} — cursor {cursor_before} -> {result['new_cursor']} "
                 f"— {len(result['new_pools'])} new pool(s)")

    # dedupe across DEXes by pool_address, in case the same pool somehow
    # surfaces from more than one source (shouldn't normally happen for
    # chain-native discovery, but cheap to guard against)
    seen_addresses = set()
    unique_new_pools = []
    for p in all_new_pools:
        if p["pool_address"] not in seen_addresses:
            seen_addresses.add(p["pool_address"])
            unique_new_pools.append(p)

    for p in unique_new_pools:
        # persist immediately, minimal record — full scoring happens
        # later in the main pipeline, this job's only job is capture
        log_dex_lifecycle(
            p["pool_address"], "UNSCORED", f"CHAIN_EVENT_{p['_dex'].upper()}", None, None, None, None,
            False, False, False, False, False, False, False, "UNCHECKED", 0.0, "⚪ DISCOVERED_ONLY",
            [f"token0={p['token0']}", f"token1={p['token1']}", f"block={p['block_number']}"])

    hours_since_last = get_hours_since_last_chain_discovery()

    lines = [f"🧭 <b>BASE DISCOVERY (chain-only, Phase 1)</b>\n",
             f"New pools found: {len(unique_new_pools)}\n",
             f"<b>Chain:</b>"]
    for dex_name, r in per_dex_results.items():
        short = dex_name.replace("aerodrome_", "").replace("_", " ").title()
        status_icon = "🔴" if r["status"] == "RPC_ERROR" else "🟢"
        lines.append(f"   {short}: {status_icon} {r['count']}")

    lines.append(f"\nExisting pools: not scanned by this job (see main DEX radar)\n")

    if any_broken:
        health = "🔴 BROKEN — at least one chain source failed this run"
    elif hours_since_last is None:
        health = "🟡 STARVED — no chain-discovered candidate has EVER been logged yet"
    elif hours_since_last >= 24:
        health = f"🟡 STARVED — {hours_since_last:.0f}h since last chain-discovered candidate"
    else:
        health = f"🟢 LIVE/QUIET — last chain-discovered candidate {hours_since_last:.1f}h ago"
    lines.append(f"Discovery health: {health}\n")

    if unique_new_pools:
        lines.append(f"<b>🟢 NEW DISCOVERY{'IES' if len(unique_new_pools) > 1 else ''}:</b>")
        for p in unique_new_pools[:5]:
            lines.append(f"   [{p['_dex']}] pool {p['pool_address'][:12]}... "
                         f"token0={p['token0'][:10]}... token1={p['token1'][:10]}... "
                         f"block={p['block_number']}")
        lines.append(f"\n<i>Not yet scored — run the main DEX radar to security/activity/Pre-Pearl these.</i>")
    else:
        lines.append(f"Last genuinely NEW token: NONE this run")

    lines.append(f"\n<b>Cursors:</b>")
    for dex_name, r in per_dex_results.items():
        lines.append(f"   {dex_name}: {r['cursor_before']} → {r['cursor_after']}")

    message = "\n".join(lines)
    plain = message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
    log.info(plain)
    send_telegram(message)


if __name__ == "__main__":
    run()
