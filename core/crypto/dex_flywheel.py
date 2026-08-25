"""
FORTRESS_CRYPTO — core/crypto/dex_flywheel.py
══════════════════════════════════════════════════════════════════════════════
v4.7 — DEX outcome resolution, mirroring the proven pearl_flywheel.py
pattern. Checks every horizon (1h/6h/24h/3d/7d), re-fetches CURRENT
DexScreener data for pairs due, computes return/liquidity-change/
volume-change/security-status-change, and updates the running max-
upside/max-drawdown high-water marks.
"""
from __future__ import annotations
import logging

from ..db import get_dex_pairs_due_for_resolution, resolve_dex_pair
from . import dexscreener

log = logging.getLogger("fortress.crypto.dex_flywheel")

HORIZONS = ("1h", "6h", "24h", "3d", "7d")


def resolve_matured_dex_pairs() -> dict:
    """Call at the start of every Base discovery run, before scoring
    anything new — same discipline as the Pearl flywheel.

    v4.7.4: now also returns a "resolutions" list with full detail
    (symbol, horizon, return_pct, was_early_move, outcome classification)
    for every pair resolved THIS run — this is what lets the caller
    build the outcome-focused Telegram message per the new decision-
    layer/evidence-layer separation, instead of resolving silently in
    the database with no visible output at all."""
    resolved_counts = {h: 0 for h in HORIZONS}
    resolutions = []

    for horizon in HORIZONS:
        due = get_dex_pairs_due_for_resolution(horizon)
        for record in due:
            pair_address = record["pair_address"]
            symbol = record["symbol"]
            was_early_move = bool(record.get("is_early_move_at_discovery"))
            try:
                # re-fetch by token address isn't directly available from
                # the first-seen record (we stored pair_address, not
                # token address) — fetch by searching the pair directly
                pair = dexscreener._get(f"/latest/dex/pairs/base/{pair_address}")
                pair_data = (pair.get("pairs") or [None])[0] if pair else None
            except Exception as e:
                log.debug(f"resolution fetch failed for {symbol} ({pair_address}): {e}")
                pair_data = None

            if not pair_data:
                log.debug(f"no current data for {symbol} ({pair_address}) at {horizon} — skipping this cycle")
                continue

            current_price = float(pair_data.get("priceUsd") or 0)
            if current_price <= 0 or not record["first_seen_price"]:
                continue
            return_pct = round(100.0 * (current_price - record["first_seen_price"]) / record["first_seen_price"], 2)

            liquidity_usd = (pair_data.get("liquidity") or {}).get("usd")
            volume_24h_usd = (pair_data.get("volume") or {}).get("h24")
            security = dexscreener.check_dex_security(pair_data)
            security_status = security.get("severity")

            resolve_dex_pair(pair_address, horizon, current_price, return_pct,
                              liquidity_usd=liquidity_usd, volume_24h_usd=volume_24h_usd,
                              security_status=security_status)
            resolved_counts[horizon] += 1

            outcome = dexscreener.classify_dex_outcome(return_pct, was_early_move, horizon)
            resolutions.append({"symbol": symbol, "horizon": horizon, "return_pct": return_pct,
                                "was_early_move": was_early_move, "outcome": outcome,
                                "max_upside_pct": record.get("max_upside_pct"),
                                "max_drawdown_pct": record.get("max_drawdown_pct")})

    log.info(f"DEX flywheel resolved: {resolved_counts}")
    return {"resolved_counts": resolved_counts, "resolutions": resolutions}
