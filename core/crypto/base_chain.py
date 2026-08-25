"""
FORTRESS_CRYPTO — core/crypto/base_chain.py
══════════════════════════════════════════════════════════════════════════════
v4.9.8 — TRUE Base Universe Discovery. Per explicit diagnosis: the
existing SEARCH source (AERO/BRETT/DEGEN/TOSHI/MOONWELL/SEAMLESS/EXTRA)
contributed 88 of 89 pairs in the most recent run — the machine was
asking "what does a curated feed return for these 7 names," not "what
new pairs actually appeared on Base." This module answers the second
question directly, by reading pool-creation events straight off the
Base blockchain — zero search bias, zero curation, genuinely new pairs
the instant they're created.

MECHANISM: Uniswap V3's Base factory contract emits a `PoolCreated`
event every time a new pool is deployed. Polling `eth_getLogs` for this
event, incrementally from the last-scanned block, surfaces every new
Base pool with no dependency on a token name being searched for.

HONEST CAVEAT, stated directly: the sandbox this was built in cannot
reach external RPC endpoints (same network-allowlist block as every
other external API used in this project — confirmed directly, not
assumed). The constants below (factory address, event topic) are the
standard, widely-documented Uniswap V3 values, but this module has NOT
been exercised against a live RPC response. The first real run is the
actual test — if it silently returns zero results, verify these two
constants against Base's official docs or BaseScan before assuming the
code itself is broken.

SCOPE: this covers Uniswap V3 pools only. Aerodrome (Base's largest
DEX by volume) uses a different factory/event structure and is NOT
covered here — a real, stated gap, not hidden. Uniswap V3 alone still
represents substantial genuine coverage and is the cleanest single
integration to start with.
"""
from __future__ import annotations
import logging
import time
from typing import List, Optional

import requests

log = logging.getLogger("fortress.crypto.base_chain")

BASE_RPC_URL = "https://mainnet.base.org"

# Uniswap V3 Factory on Base — documented, standard address.
# VERIFY against basescan.org/address/... before trusting in production;
# this sandbox cannot confirm it against a live chain.
UNISWAP_V3_FACTORY_BASE = "0x33128a8fC17869897dcE68Ed026d694621f6FDf"

# keccak256("PoolCreated(address,address,uint24,int24,address)") — the
# standard Uniswap V3 PoolCreated event topic, identical across all
# chains (derived from the event signature, not the contract address).
POOL_CREATED_TOPIC = "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7e5"

_MIN_INTERVAL = 0.5
_last_call_ts = [0.0]


def _throttle() -> None:
    elapsed = time.monotonic() - _last_call_ts[0]
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_call_ts[0] = time.monotonic()


def _rpc_call(method: str, params: list) -> Optional[dict]:
    _throttle()
    try:
        resp = requests.post(BASE_RPC_URL, json={"jsonrpc": "2.0", "method": method, "params": params, "id": 1},
                             timeout=20)
        if resp.status_code != 200:
            log.warning(f"Base RPC {resp.status_code} for {method}")
            return None
        data = resp.json()
        if "error" in data:
            log.warning(f"Base RPC error for {method}: {data['error']}")
            return None
        return data.get("result")
    except Exception as e:
        log.warning(f"Base RPC request error ({method}): {e}")
        return None


def get_current_block() -> Optional[int]:
    result = _rpc_call("eth_blockNumber", [])
    if result is None:
        return None
    try:
        return int(result, 16)
    except (ValueError, TypeError):
        log.warning(f"Unexpected eth_blockNumber response: {result}")
        return None


def fetch_new_pool_events(from_block: int, to_block: int) -> dict:
    """Fetch PoolCreated events in [from_block, to_block]. Returns
    {"logs": [...] or None, "ok": bool} — the None/empty-list distinction
    is preserved explicitly here (v4.9.8's bug: converting a failed call
    into an empty list made 'RPC failed' indistinguishable from 'RPC
    succeeded with zero events').

    v4.9.9 FIX: address now sent as an array (['0x...'], not a bare
    string) and lowercased. The production error — 'Invalid variadic
    value or array type: data did not match any variant of untagged
    enum Variadic' — is a Rust/Alloy-style deserialization error
    consistent with Base's node expecting the address field in its
    array-typed form. This is a well-reasoned fix based on the actual
    error text, NOT confirmed against a live response (this sandbox
    cannot reach external RPC endpoints, same constraint as every other
    external API in this project). The next real run is the actual
    test — if CHAIN_EVENT still errors, the improved logging below will
    show the exact new error message to diagnose further."""
    from_hex = hex(from_block)
    to_hex = hex(to_block)
    result = _rpc_call("eth_getLogs", [{
        "fromBlock": from_hex, "toBlock": to_hex,
        "address": [UNISWAP_V3_FACTORY_BASE.lower()],
        "topics": [POOL_CREATED_TOPIC],
    }])
    if result is None:
        return {"logs": None, "ok": False}
    return {"logs": result, "ok": True}


def parse_pool_created_log(log_entry: dict) -> Optional[dict]:
    """Decodes a raw PoolCreated log into {token0, token1, pool_address,
    block_number}. token0/token1 are in topics[1]/topics[2] (indexed
    params, left-padded to 32 bytes — take the last 20 bytes/40 hex
    chars for the actual address). pool_address is in the data field
    (non-indexed, the last param in the event signature)."""
    try:
        topics = log_entry.get("topics", [])
        if len(topics) < 3:
            return None
        token0 = "0x" + topics[1][-40:]
        token1 = "0x" + topics[2][-40:]
        data = log_entry.get("data", "")
        # data = fee(32 bytes) + tickSpacing(32 bytes) + pool_address(32 bytes)
        # pool address is the last 32-byte word, last 20 bytes of that
        pool_address = "0x" + data[-40:] if len(data) >= 40 else None
        block_number = int(log_entry.get("blockNumber", "0x0"), 16)
        return {"token0": token0, "token1": token1, "pool_address": pool_address, "block_number": block_number}
    except Exception as e:
        log.warning(f"Failed to parse PoolCreated log: {e} — raw: {log_entry}")
        return None


def discover_new_base_pools(cursor_block: Optional[int], max_blocks_per_call: int = 2000,
                             lookback_blocks_if_no_cursor: int = 5000) -> dict:
    """v4.9.9 — REWRITTEN error handling, per explicit requirement: RPC
    failure must produce a status that is NEVER 'OK', and the cursor
    must NEVER advance on failure. Three distinct, honest states:
    RPC_ERROR (request failed — cursor does NOT advance, so the same
    blocks get retried next run), OK_ZERO_RESULTS (request succeeded,
    genuinely zero new pools), OK (request succeeded, pools found)."""
    current_block = get_current_block()
    if current_block is None:
        log.warning("Base chain scan: eth_blockNumber failed — RPC unreachable")
        return {"new_pools": [], "new_cursor": cursor_block, "status": "RPC_ERROR"}

    from_block = cursor_block if cursor_block is not None else max(0, current_block - lookback_blocks_if_no_cursor)
    if from_block >= current_block:
        log.info(f"Base chain scan: from_block={from_block} >= current_block={current_block}, nothing new yet")
        return {"new_pools": [], "new_cursor": current_block, "status": "OK_ZERO_RESULTS"}

    to_block = min(current_block, from_block + max_blocks_per_call)
    log.info(f"Base chain scan: from_block={from_block}, to_block={to_block}, current_block={current_block}")
    fetch_result = fetch_new_pool_events(from_block, to_block)

    if not fetch_result["ok"]:
        # ── v4.9.9 fix: RPC failure must NEVER be reported as OK, and
        # the cursor must NEVER advance — the caller must retry these
        # exact same blocks next run, not silently skip past them.
        log.warning(f"Base chain scan FAILED: blocks {from_block}-{to_block}, eth_getLogs request failed")
        return {"new_pools": [], "new_cursor": cursor_block, "status": "RPC_ERROR"}

    raw_logs = fetch_result["logs"]
    new_pools = []
    for entry in raw_logs:
        parsed = parse_pool_created_log(entry)
        if parsed and parsed.get("pool_address"):
            new_pools.append(parsed)

    log.info(f"Base chain scan OK: blocks {from_block}-{to_block}, {len(raw_logs)} raw log(s), "
             f"{len(new_pools)} parsed pool(s)")
    return {"new_pools": new_pools, "new_cursor": to_block,
            "status": "OK" if new_pools else "OK_ZERO_RESULTS"}
