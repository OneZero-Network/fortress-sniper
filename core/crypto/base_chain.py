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

# Uniswap V3 Factory — deployed via deterministic CREATE2 with the SAME
# address across nearly all EVM chains (Ethereum, Base, Arbitrum,
# Optimism, Polygon), which is why this specific value is so widely and
# consistently cited across Uniswap's own documentation and integration
# guides.
#
# v4.9.10 CRITICAL FIX: the previous hardcoded value was 39 hex
# characters — ALSO one short of the required 40 (20 bytes) — a second
# silent truncation, caught only because the new self-check assertion
# below fired immediately at import time instead of failing silently
# downstream. UNLIKE the topic hash, a contract address cannot be
# independently computed — it's a fact about what's actually deployed
# on-chain. This corrected value has the right length and matches the
# well-known canonical cross-chain address, but has NOT been verified
# against a live Base RPC or block explorer from this sandbox (no
# external network access here). Recommend a final check against
# basescan.org before treating this as fully confirmed.
UNISWAP_V3_FACTORY_BASE = "0x1F98431c8aD98523631AE4a59f267346ea31F984"

# keccak256("PoolCreated(address,address,uint24,int24,address)") —
# the standard Uniswap V3 PoolCreated event topic, identical across all
# chains (derived from the event signature, not the contract address).
#
# v4.9.13 CRITICAL FIX: the previous hardcoded value was 63 hex
# characters — ONE SHORT of the required 64 (32 bytes) — a silent
# truncation, not a formatting issue. This is almost certainly the real
# cause of every "Invalid variadic value... did not match any variant"
# error seen in production: a malformed-length hash cannot deserialize
# as a valid topic hash under any shape. RECOMPUTED here with an actual
# keccak256 implementation (pycryptodome), not recalled from memory —
# verified programmatically to be exactly 64 hex characters.
POOL_CREATED_TOPIC = "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118"

# ── v4.9.13 — AERODROME, per explicit "mandatory" instruction. Base's
# largest DEX by volume, previously an acknowledged, stated gap.
# Aerodrome is a Solidly/Velodrome-fork AMM — its base PoolFactory emits
# a DIFFERENT event shape than Uniswap V3: three INDEXED params
# (token0, token1, stable) rather than two, with the pool address as
# the FIRST word of data (not the last). This is not a copy-paste of
# the Uniswap V3 logic — it needs its own parser.
#
# CONFIDENCE LEVEL, stated honestly and DIFFERENTLY for each constant:
# - AERODROME_POOL_CREATED_TOPIC: HIGH confidence — independently
#   computed via keccak256 against the literal signature string
#   "PoolCreated(address,address,bool,address,uint256)", verified to be
#   exactly 64 hex characters, same rigor as the Uniswap V3 topic.
# - AERODROME_FACTORY_BASE: LOWER confidence than the Uniswap V3
#   factory address. Unlike Uniswap V3 (deployed via CREATE2 with an
#   identical address across many chains, which gave that constant an
#   independent cross-check), Aerodrome's factory is Base-specific —
#   there's no "same address everywhere" fact to lean on. This value
#   has the correct LENGTH (verified) but has NOT been confirmed
#   against BaseScan or Aerodrome's own docs from this sandbox (no
#   external network access). Verify this specific constant first if
#   Aerodrome discovery fails.
AERODROME_FACTORY_BASE = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
AERODROME_POOL_CREATED_TOPIC = "0x2128d88d14c80cb081c1252a5acff7a264671bf199ce226b53788fb26065005e"

# Self-check: fail LOUD and immediately at import time if any hardcoded
# constant is ever malformed again, rather than producing a cryptic
# downstream RPC error hours later. This is the exact class of bug that
# caused v4.9.9's fix attempt to still fail.
assert len(POOL_CREATED_TOPIC) == 66, \
    f"POOL_CREATED_TOPIC must be exactly 66 chars (0x + 64 hex), got {len(POOL_CREATED_TOPIC)}"
assert len(UNISWAP_V3_FACTORY_BASE) == 42, \
    f"UNISWAP_V3_FACTORY_BASE must be exactly 42 chars (0x + 40 hex), got {len(UNISWAP_V3_FACTORY_BASE)}"
assert len(AERODROME_POOL_CREATED_TOPIC) == 66, \
    f"AERODROME_POOL_CREATED_TOPIC must be exactly 66 chars, got {len(AERODROME_POOL_CREATED_TOPIC)}"
assert len(AERODROME_FACTORY_BASE) == 42, \
    f"AERODROME_FACTORY_BASE must be exactly 42 chars, got {len(AERODROME_FACTORY_BASE)}"

# ── v4.9.20 — SLIPSTREAM, verified with FOUR corroborating signals (not
# one bare label, unlike the two prior mistakes in this build):
#   1. BaseScan's verified source explicitly names this "CLFactory"
#      (not "CLPool" — confirmed the actual factory, not a pool template)
#   2. Its ABI contains exactly PoolCreated(address,address,int24,address)
#   3. Its constructor arguments reference poolImplementation =
#      0xeC8E5342B19977B4eF8892e02D8DAEcfa1315831 — the EXACT CLPool
#      address found in the prior (failed) verification attempt, meaning
#      both independently-found pieces are internally consistent
#   4. Confirmed genuine "Create Pool" activity as recent as 4 hours
#      before this was written — this factory is actively creating pools
SLIPSTREAM_FACTORY_BASE = "0x5e7BB104d84c7CB9B682AaC2F3d509f5F406809A"

# keccak256("PoolCreated(address,address,int24,address)") — computed
# independently via keccak256, THEN cross-checked against the literal
# byte sequence embedded in the verified contract's own deployed
# bytecode (fetched from BaseScan) — confirmed an EXACT match. This is
# the strongest verification level in this entire build: not just
# "correct length," not just "matches a label," but confirmed present
# byte-for-byte in the real deployed contract code.
SLIPSTREAM_POOL_CREATED_TOPIC = "0xab0d57f0df537bb25e80245ef7748fa62353808c54d6e528a9dd20887aed9ac2"

assert len(SLIPSTREAM_POOL_CREATED_TOPIC) == 66, \
    f"SLIPSTREAM_POOL_CREATED_TOPIC must be exactly 66 chars, got {len(SLIPSTREAM_POOL_CREATED_TOPIC)}"
assert len(SLIPSTREAM_FACTORY_BASE) == 42, \
    f"SLIPSTREAM_FACTORY_BASE must be exactly 42 chars, got {len(SLIPSTREAM_FACTORY_BASE)}"

# ── DEX registry — parameterizes the generic discovery functions below
# so adding a third DEX later doesn't require duplicating the whole
# fetch/parse/discover pipeline again.
DEX_REGISTRY = {
    "uniswap_v3": {"factory": UNISWAP_V3_FACTORY_BASE, "topic": POOL_CREATED_TOPIC, "topic_count": 3,
                   "parser": "uniswap_v3"},
    "aerodrome": {"factory": AERODROME_FACTORY_BASE, "topic": AERODROME_POOL_CREATED_TOPIC, "topic_count": 4,
                  "parser": "aerodrome"},
    "aerodrome_slipstream": {"factory": SLIPSTREAM_FACTORY_BASE, "topic": SLIPSTREAM_POOL_CREATED_TOPIC,
                             "topic_count": 4, "parser": "aerodrome_slipstream"},
}

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


def fetch_new_pool_events(from_block: int, to_block: int, factory_address: str, topic: str) -> dict:
    """Fetch PoolCreated-shaped events in [from_block, to_block] for the
    given factory/topic. Returns {"logs": [...] or None, "ok": bool} —
    the None/empty-list distinction is preserved explicitly (v4.9.8's
    bug: converting a failed call into an empty list made 'RPC failed'
    indistinguishable from 'RPC succeeded with zero events').

    v4.9.13: generalized to accept factory/topic as parameters instead
    of hardcoding Uniswap V3's, so the same function serves any
    registered DEX."""
    from_hex = hex(from_block)
    to_hex = hex(to_block)
    result = _rpc_call("eth_getLogs", [{
        "fromBlock": from_hex, "toBlock": to_hex,
        "address": [factory_address.lower()],
        "topics": [topic],
    }])
    if result is None:
        return {"logs": None, "ok": False}
    return {"logs": result, "ok": True}


def parse_pool_created_log(log_entry: dict) -> Optional[dict]:
    """Decodes a raw Uniswap V3 PoolCreated log into {token0, token1,
    pool_address, block_number}. token0/token1 are in topics[1]/
    topics[2] (indexed params, left-padded to 32 bytes — take the last
    20 bytes/40 hex chars for the actual address). pool_address is in
    the data field (non-indexed, the LAST param in the event signature:
    fee, tickSpacing, pool — pool is the 3rd/last 32-byte word)."""
    try:
        topics = log_entry.get("topics", [])
        if len(topics) < 3:
            return None
        token0 = "0x" + topics[1][-40:]
        token1 = "0x" + topics[2][-40:]
        data = log_entry.get("data", "")
        pool_address = "0x" + data[-40:] if len(data) >= 40 else None
        block_number = int(log_entry.get("blockNumber", "0x0"), 16)
        return {"token0": token0, "token1": token1, "pool_address": pool_address, "block_number": block_number}
    except Exception as e:
        log.warning(f"Failed to parse Uniswap V3 PoolCreated log: {e} — raw: {log_entry}")
        return None


def parse_aerodrome_pool_created_log(log_entry: dict) -> Optional[dict]:
    """v4.9.13 — Decodes an Aerodrome PoolCreated log. DIFFERENT SHAPE
    from Uniswap V3: signature is
    `PoolCreated(address indexed token0, address indexed token1, bool
    indexed stable, address pool, uint256)` — THREE indexed params
    (token0, token1, stable), not two, so topics needs 4 entries
    (topic0 + 3 indexed). Critically, pool_address is the FIRST 32-byte
    word of data here (immediately after the indexed params), not the
    last as in Uniswap V3 — this is exactly the kind of structural
    difference that would silently corrupt results if the Uniswap V3
    parser were reused as-is."""
    try:
        topics = log_entry.get("topics", [])
        if len(topics) < 3:
            return None
        token0 = "0x" + topics[1][-40:]
        token1 = "0x" + topics[2][-40:]
        data = log_entry.get("data", "")
        # pool address is the FIRST 32-byte word (64 hex chars) of data
        pool_address = "0x" + data[24:64] if len(data) >= 64 else None
        block_number = int(log_entry.get("blockNumber", "0x0"), 16)
        return {"token0": token0, "token1": token1, "pool_address": pool_address, "block_number": block_number}
    except Exception as e:
        log.warning(f"Failed to parse Aerodrome PoolCreated log: {e} — raw: {log_entry}")
        return None


def parse_aerodrome_slipstream_pool_created_log(log_entry: dict) -> Optional[dict]:
    """v4.9.20 — Decodes a Slipstream PoolCreated log. Confirmed ABI:
    PoolCreated(address indexed token0, address indexed token1,
    int24 indexed tickSpacing, address pool) — THREE indexed params
    like Aerodrome classic, but the third is tickSpacing (an int24),
    not a bool, so this needs its own parser rather than reusing
    Aerodrome classic's. Unlike Aerodrome classic (pool at data[0:32])
    or Uniswap V3 (pool at data[-32:]), here pool is the ONLY data word
    — data is a single 32-byte value, the address right-aligned within it."""
    try:
        topics = log_entry.get("topics", [])
        if len(topics) < 3:
            return None
        token0 = "0x" + topics[1][-40:]
        token1 = "0x" + topics[2][-40:]
        data = log_entry.get("data", "")
        pool_address = "0x" + data[-40:] if len(data) >= 40 else None
        block_number = int(log_entry.get("blockNumber", "0x0"), 16)
        return {"token0": token0, "token1": token1, "pool_address": pool_address, "block_number": block_number}
    except Exception as e:
        log.warning(f"Failed to parse Slipstream PoolCreated log: {e} — raw: {log_entry}")
        return None


def discover_new_pools(dex_name: str, cursor_block: Optional[int], max_blocks_per_call: int = 2000,
                        lookback_blocks_if_no_cursor: int = 5000) -> dict:
    """v4.9.13 — generalized discovery entrypoint, works for any DEX in
    DEX_REGISTRY. Three distinct, honest states, per explicit
    requirement: RPC_ERROR (request failed — cursor does NOT advance),
    OK_ZERO_RESULTS (request succeeded, genuinely zero new pools), OK
    (request succeeded, pools found)."""
    if dex_name not in DEX_REGISTRY:
        raise ValueError(f"Unknown DEX '{dex_name}' — must be one of {list(DEX_REGISTRY.keys())}")
    config = DEX_REGISTRY[dex_name]
    if config["parser"] == "uniswap_v3":
        parser = parse_pool_created_log
    elif config["parser"] == "aerodrome":
        parser = parse_aerodrome_pool_created_log
    else:
        parser = parse_aerodrome_slipstream_pool_created_log

    current_block = get_current_block()
    if current_block is None:
        log.warning(f"[{dex_name}] chain scan: eth_blockNumber failed — RPC unreachable")
        return {"new_pools": [], "new_cursor": cursor_block, "status": "RPC_ERROR"}

    from_block = cursor_block if cursor_block is not None else max(0, current_block - lookback_blocks_if_no_cursor)
    if from_block >= current_block:
        log.info(f"[{dex_name}] chain scan: from_block={from_block} >= current_block={current_block}, "
                 f"nothing new yet")
        return {"new_pools": [], "new_cursor": current_block, "status": "OK_ZERO_RESULTS"}

    to_block = min(current_block, from_block + max_blocks_per_call)
    log.info(f"[{dex_name}] chain scan: from_block={from_block}, to_block={to_block}, "
             f"current_block={current_block}")
    fetch_result = fetch_new_pool_events(from_block, to_block, config["factory"], config["topic"])

    if not fetch_result["ok"]:
        log.warning(f"[{dex_name}] chain scan FAILED: blocks {from_block}-{to_block}, eth_getLogs request failed")
        return {"new_pools": [], "new_cursor": cursor_block, "status": "RPC_ERROR"}

    raw_logs = fetch_result["logs"]
    new_pools = []
    for entry in raw_logs:
        parsed = parser(entry)
        if parsed and parsed.get("pool_address"):
            new_pools.append(parsed)

    log.info(f"[{dex_name}] chain scan OK: blocks {from_block}-{to_block}, {len(raw_logs)} raw log(s), "
             f"{len(new_pools)} parsed pool(s)")
    return {"new_pools": new_pools, "new_cursor": to_block,
            "status": "OK" if new_pools else "OK_ZERO_RESULTS"}


# ── Backward-compatible aliases — anything still calling the old,
# Uniswap-V3-only function names keeps working unchanged.
def discover_new_base_pools(cursor_block: Optional[int], max_blocks_per_call: int = 2000,
                             lookback_blocks_if_no_cursor: int = 5000) -> dict:
    return discover_new_pools("uniswap_v3", cursor_block, max_blocks_per_call, lookback_blocks_if_no_cursor)
