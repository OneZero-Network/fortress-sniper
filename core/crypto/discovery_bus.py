"""
FORTRESS_CRYPTO — core/crypto/discovery_bus.py
══════════════════════════════════════════════════════════════════════════════
v4.9.18 — Universal Discovery Bus. Per explicit architectural mandate:
"No single source is allowed to define the universe... every source
should emit the same object... then the rest of your machine doesn't
care where it came from."

This is what prevents the exact dead end already hit twice: build
Uniswap V3 → works → build Aerodrome → works → need Slipstream → have
to rebuild the pipeline again. With a universal shape, adding ANY new
source (Slipstream, another AMM, a new DexScreener feed) means writing
one small adapter function, never touching the aggregation/dedup/
scoring logic downstream.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class DiscoveryEvent:
    """The one shape every discovery source must produce. Nothing
    downstream (dedup, NEW/AWAKENING classification, Pre-Pearl scoring)
    is allowed to know or care which specific source produced this."""
    chain: str
    dex: str                    # "uniswap_v3" | "aerodrome" | "aerodrome_slipstream" | "dexscreener_search" | ...
    source: str                 # human-readable source label for display, e.g. "CHAIN_EVENT_AERODROME"
    pool_address: str
    token_address: str          # the NON-quote token — the actual candidate
    token_symbol: str
    quote_token_address: Optional[str] = None
    block_number: Optional[int] = None
    discovered_at: Optional[str] = None
    pair_age_hours: Optional[float] = None
    liquidity_usd: Optional[float] = None
    volume_24h_usd: Optional[float] = None
    pct_24h: Optional[float] = None
    raw_pair_data: Optional[dict] = None  # the original source payload, kept for scoring/security checks


def from_chain_event_pool(pool: dict, pair_data: dict, dex_name: str, source_label: str) -> Optional[DiscoveryEvent]:
    """Adapter: a chain-event-discovered pool (from base_chain.discover_new_pools)
    + its fetched DexScreener pair data -> a DiscoveryEvent."""
    if not pair_data:
        return None
    base_token = pair_data.get("baseToken") or {}
    return DiscoveryEvent(
        chain="base", dex=dex_name, source=source_label,
        pool_address=pool.get("pool_address") or pair_data.get("pairAddress"),
        token_address=base_token.get("address"),
        token_symbol=(base_token.get("symbol") or "").upper(),
        block_number=pool.get("block_number"),
        liquidity_usd=(pair_data.get("liquidity") or {}).get("usd"),
        volume_24h_usd=(pair_data.get("volume") or {}).get("h24"),
        pct_24h=(pair_data.get("priceChange") or {}).get("h24"),
        raw_pair_data=pair_data,
    )


def from_dexscreener_pair(pair_data: dict, source_label: str) -> Optional[DiscoveryEvent]:
    """Adapter: a DexScreener-sourced pair (search/boosted/profiled/top_boosted)
    -> a DiscoveryEvent. Same universal shape, different origin."""
    if not pair_data:
        return None
    base_token = pair_data.get("baseToken") or {}
    return DiscoveryEvent(
        chain="base", dex="dexscreener", source=source_label,
        pool_address=pair_data.get("pairAddress"),
        token_address=base_token.get("address"),
        token_symbol=(base_token.get("symbol") or "").upper(),
        liquidity_usd=(pair_data.get("liquidity") or {}).get("usd"),
        volume_24h_usd=(pair_data.get("volume") or {}).get("h24"),
        pct_24h=(pair_data.get("priceChange") or {}).get("h24"),
        raw_pair_data=pair_data,
    )


@dataclass
class AggregatedToken:
    """v4.9.18 — cross-source aggregation, per explicit instruction:
    'You don't want TOKEN A / TOKEN A / TOKEN A. You want TOKEN A,
    Sources: Aerodrome, Slipstream, DexScreener, Pools: 3.' The same
    token appearing on multiple sources/pools is a STRONGER signal, not
    three separate candidates."""
    token_address: str
    token_symbol: str
    sources: List[str] = field(default_factory=list)
    pool_addresses: List[str] = field(default_factory=list)
    events: List[DiscoveryEvent] = field(default_factory=list)
    first_discovered_at: Optional[str] = None

    @property
    def pool_count(self) -> int:
        return len(set(self.pool_addresses))

    @property
    def source_count(self) -> int:
        return len(set(self.sources))

    @property
    def best_event(self) -> DiscoveryEvent:
        """The representative event for scoring — highest liquidity,
        since that's the most informative/reliable single reading."""
        return max(self.events, key=lambda e: e.liquidity_usd or 0)


def aggregate_by_token(events: List[DiscoveryEvent]) -> List[AggregatedToken]:
    """v4.9.18 — the actual cross-source dedup. Groups by TOKEN ADDRESS
    (not symbol — symbols can collide across different real tokens;
    address is the only genuinely unique identifier), regardless of
    which source or pool found it."""
    by_token: dict = {}
    for e in events:
        if not e.token_address:
            continue
        key = e.token_address.lower()
        if key not in by_token:
            by_token[key] = AggregatedToken(token_address=e.token_address, token_symbol=e.token_symbol)
        agg = by_token[key]
        agg.sources.append(e.source)
        if e.pool_address:
            agg.pool_addresses.append(e.pool_address)
        agg.events.append(e)
    return list(by_token.values())
