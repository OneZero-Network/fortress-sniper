"""
FORTRESS_CRYPTO — core/crypto/multi_universe.py
══════════════════════════════════════════════════════════════════════════════
v3.2 — Multi-Universe Scanner. Expands discovery from a single ~60-coin
universe to three tiers (Large/Mid/Emerging), while staying honest about
the real cost of doing that: full per-coin enrichment (whale/news/risk
checks, each API-throttled) does not scale to thousands of coins in a
single run.

THE FUNNEL, matching the shape your mentor's own diagram described:
  1. FETCH each tier cheaply (one paginated CoinGecko call per tier,
     already-available snapshot fields only — no per-coin API calls yet)
  2. PRE-FILTER using ONLY data already in the snapshot (volume/mcap
     ratio, 7d/30d momentum) — cheap, no extra calls, cuts each tier
     down to a bounded shortlist
  3. Only the shortlist proceeds to the EXPENSIVE full scoring pass
     (whale/news/risk/velocity) in the calling workflow

RELATIVE RANKING: after full scoring, each candidate also gets a
within-tier percentile — "top 8% of Emerging-tier candidates today" is a
different, more honest claim than comparing a $2M market-cap coin's raw
discovery_score directly against a $500M large-cap's, per the explicit
instruction not to compare a microcap against BTC-scale assets directly.

OUT OF SCOPE (stated directly, not silently skipped): new-listings and
DEX/new-token universes need a different data source than CoinGecko's
markets endpoint — flagged as a real follow-up.
"""
from __future__ import annotations
import logging
from typing import List

from . import config as ccfg
from . import data as cdata

log = logging.getLogger("fortress.crypto.multi_universe")


def _cheap_prefilter_score(coin: dict) -> float:
    """Uses ONLY fields already in the universe snapshot — no extra API
    calls. Rewards unusual volume relative to market cap (liquidity
    health) and meaningful recent momentum (something is actually
    changing), the same 'cheap signal' philosophy as pearl_score.py's
    liquidity/structure components, reused here purely as a triage tool
    to decide who's worth the expensive checks — NOT as the final score."""
    vol = coin.get("volume_24h") or 0
    mcap = coin.get("market_cap") or 1
    turnover_ratio = vol / mcap if mcap > 0 else 0
    pct_7d = abs(coin.get("pct_7d") or 0)
    pct_30d = abs(coin.get("pct_30d") or 0)
    return turnover_ratio * 100 + pct_7d * 2 + pct_30d * 0.5


def fetch_multi_universe_shortlist() -> List[dict]:
    """Returns a combined, bounded shortlist across all configured
    tiers, each candidate tagged with its tier label — ready for the
    calling workflow to run expensive per-coin enrichment on. This is
    the ONLY function most callers need."""
    shortlist: List[dict] = []

    for tier_name, tier_cfg in ccfg.UNIVERSE_TIERS.items():
        log.info(f"Fetching tier {tier_name} (rank {tier_cfg['min_rank']}-{tier_cfg['max_rank']})...")
        coins = cdata.fetch_universe_tier(
            tier_cfg["min_rank"], tier_cfg["max_rank"],
            tier_cfg["min_volume_usd"], tier_cfg["min_market_cap_usd"],
        )
        log.info(f"  {len(coins)} coins passed tier {tier_name}'s liquidity floor")

        max_deep = tier_cfg["max_deep_scored"]
        prefilter_pool_size = max_deep * ccfg.PREFILTER_TOP_N_MULTIPLIER
        coins_ranked = sorted(coins, key=_cheap_prefilter_score, reverse=True)[:prefilter_pool_size]

        # within the pre-filter pool, keep only max_deep for actual deep
        # scoring — this is the real funnel step
        for_deep_scoring = coins_ranked[:max_deep]
        log.info(f"  {len(for_deep_scoring)}/{len(coins)} coins in {tier_name} proceed to full scoring")

        for c in for_deep_scoring:
            c["universe_tier"] = tier_name
        shortlist.extend(for_deep_scoring)

    log.info(f"Multi-universe shortlist: {len(shortlist)} total candidates across {len(ccfg.UNIVERSE_TIERS)} tiers")
    return shortlist


def compute_within_tier_ranking(scored_candidates: List[dict]) -> None:
    """Mutates each candidate dict in place, adding 'tier_rank' and
    'tier_percentile' — computed from discovery_score WITHIN the same
    universe_tier only, never across tiers. A candidate list must
    already have 'universe_tier' and 'discovery_score' set."""
    by_tier: dict = {}
    for c in scored_candidates:
        tier = c.get("universe_tier", "UNKNOWN")
        by_tier.setdefault(tier, []).append(c)

    for tier, group in by_tier.items():
        scored = [c for c in group if c.get("discovery_score") is not None]
        scored.sort(key=lambda c: c["discovery_score"], reverse=True)
        n = len(scored)
        for i, c in enumerate(scored):
            c["tier_rank"] = i + 1
            c["tier_size"] = n
            c["tier_percentile"] = round(100.0 * (n - i) / n, 1) if n > 0 else None
        for c in group:
            if c.get("discovery_score") is None:
                c["tier_rank"] = None
                c["tier_size"] = len(group)
                c["tier_percentile"] = None
