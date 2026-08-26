#!/usr/bin/env python3
"""
FORTRESS_CRYPTO — scripts/slipstream_replay_test.py
══════════════════════════════════════════════════════════════════════════════
v4.9.22 — The last-mile test. Per explicit distinction: "the proof
currently establishes only chain → event → parser. It does not yet
establish chain → Pearl candidate."

This re-fetches the SAME 10 independently-confirmed real PoolCreated
events already proven in v4.9.21, then runs each one through the
COMPLETE production pipeline — fetch_pair_data → viability → security
→ acceleration → Pre-Pearl scoring → lifecycle logging — using an
ISOLATED SQLite database (never touches the live production DB), and
reports EXACTLY where each one lands. If a pool disappears between
PoolCreated and scoring, this is where it will show up.
"""
from __future__ import annotations
import logging
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                     datefmt="%H:%M:%S")
log = logging.getLogger("fortress.crypto.slipstream_replay")

# Isolated DB — set BEFORE importing anything that reads FORTRESS_DB_PATH
_isolated_db = tempfile.NamedTemporaryFile(suffix="_slipstream_replay.db", delete=False).name
os.environ["FORTRESS_DB_PATH"] = _isolated_db
log.info(f"REPLAY MODE — isolated database: {_isolated_db} (never touches production data)")

from core.telegram import send as send_telegram
from core.db import init_crypto_tables, log_dex_lifecycle
from core.crypto import base_chain, dexscreener, risk_engine

KNOWN_CONFIRMED_BLOCKS = [50460214, 50444664, 50441483, 50440237, 50439278,
                          50439034, 50437665, 50423185, 50421092, 50405412]
BACKFILL_FROM = min(KNOWN_CONFIRMED_BLOCKS) - 1000
BACKFILL_TO = max(KNOWN_CONFIRMED_BLOCKS) + 1000
CHUNK_SIZE = 2000


def rediscover_known_pools() -> list:
    """Re-fetches the same 10 proven real events via the exact same
    backfill mechanism already verified in v4.9.21 — this is not new,
    unverified logic, it's reusing the proven path to get real
    addresses to replay."""
    all_pools = []
    from_block = BACKFILL_FROM
    while from_block < BACKFILL_TO:
        to_block = min(from_block + CHUNK_SIZE, BACKFILL_TO)
        fetch_result = base_chain.fetch_new_pool_events(
            from_block, to_block, base_chain.SLIPSTREAM_FACTORY_BASE, base_chain.SLIPSTREAM_POOL_CREATED_TOPIC)
        if fetch_result["ok"]:
            for entry in fetch_result["logs"]:
                parsed = base_chain.parse_aerodrome_slipstream_pool_created_log(entry)
                if parsed and parsed.get("pool_address") and parsed["block_number"] in KNOWN_CONFIRMED_BLOCKS:
                    all_pools.append(parsed)
        from_block = to_block
    return all_pools


def replay_one_pool(pool: dict) -> dict:
    """Runs ONE real chain-discovered pool through the exact same
    stages base_discovery_scan.py uses for live candidates, reporting
    exactly which stage it reached and why it stopped there."""
    result = {"pool_address": pool["pool_address"], "block": pool["block_number"], "stage_reached": None,
              "symbol": None, "detail": None}

    pair = dexscreener.fetch_pair_data(pool["token0"], chain="base")
    if not pair:
        pair = dexscreener.fetch_pair_data(pool["token1"], chain="base")
    if not pair:
        result["stage_reached"] = "FETCH_FAILED"
        result["detail"] = "no DexScreener data for either token — pool may be too obscure/untracked, or too old for current API state"
        return result

    base_token = pair.get("baseToken") or {}
    result["symbol"] = (base_token.get("symbol") or "?").upper()

    liq = dexscreener.apply_liquidity_filter(pair)
    if not liq["passes"]:
        result["stage_reached"] = "FILTERED_LIQUIDITY"
        result["detail"] = liq["reason"]
        return result

    act = dexscreener.apply_activity_filter(pair)
    if not act["passes"]:
        result["stage_reached"] = "FILTERED_ACTIVITY"
        result["detail"] = "; ".join(act["reasons"])
        return result

    security = dexscreener.check_dex_security(pair)
    if security["severity"] == "HIGH_RISK":
        result["stage_reached"] = "BLOCKED_SECURITY"
        result["detail"] = "; ".join(security["flags"])
        return result

    accel = dexscreener.compute_acceleration(pair)
    flow = dexscreener.compute_flow_signals(pair)
    age_hours = dexscreener.compute_pair_age_hours(pair)
    early_move = dexscreener.classify_dex_early_move({"passes": True}, flow, accel, age_hours, security)
    pre_pearl = dexscreener.compute_pre_pearl_score(
        age_hours, accel, flow, security, early_move.get("already_extended", False),
        (pair.get("liquidity") or {}).get("usd"), None)

    log_dex_lifecycle(
        pool["pool_address"], result["symbol"], "REPLAY_TEST", age_hours,
        (pair.get("liquidity") or {}).get("usd"), (pair.get("volume") or {}).get("h24"), flow.get("pct_24h"),
        pre_pearl["conditions"]["pair_new"], pre_pearl["conditions"]["liquidity_accel"],
        pre_pearl["conditions"]["volume_accel"], pre_pearl["conditions"]["tx_accel"],
        pre_pearl["conditions"]["buy_pressure"], pre_pearl["conditions"]["price_near_base"],
        early_move.get("already_extended", False), security["severity"],
        pre_pearl["score"], pre_pearl["classification"], pre_pearl["breakdown"])

    result["stage_reached"] = "SCORED"
    result["detail"] = f"{pre_pearl['score']}/90 -> {pre_pearl['classification']}"
    return result


def run() -> None:
    log.info("=== Slipstream Replay Test — chain event -> Pearl candidate, in isolation ===")
    init_crypto_tables()

    pools = rediscover_known_pools()
    log.info(f"Re-discovered {len(pools)}/{len(KNOWN_CONFIRMED_BLOCKS)} known pools via the proven backfill path")

    results = [replay_one_pool(p) for p in pools]

    by_stage: dict = {}
    for r in results:
        by_stage.setdefault(r["stage_reached"], []).append(r)

    lines = [f"🧪 <b>Slipstream Replay Test</b>",
             f"<i>Isolated database — production data untouched</i>\n",
             f"Re-discovered {len(pools)}/{len(KNOWN_CONFIRMED_BLOCKS)} known real pools, replayed through "
             f"the full production pipeline\n"]

    for stage, items in by_stage.items():
        lines.append(f"<b>{stage} ({len(items)})</b>")
        for r in items[:5]:
            lines.append(f"   {r['symbol'] or '?'} [{r['pool_address'][:10]}...] — {r['detail']}")
        lines.append("")

    reached_scoring = len(by_stage.get("SCORED", []))
    lines.append(f"<b>Verdict:</b> {reached_scoring}/{len(pools)} known real pools reached scoring. "
                f"{'This confirms chain-discovered pools DO reach the Pearl engine.' if reached_scoring > 0 else 'ZERO reached scoring — this pinpoints exactly where the pipeline drops real candidates.'}")

    message = "\n".join(lines)
    plain = message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
    log.info(plain)
    send_telegram(message)

    try:
        os.remove(_isolated_db)
    except OSError:
        pass


if __name__ == "__main__":
    run()
