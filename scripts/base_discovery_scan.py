#!/usr/bin/env python3
"""
FORTRESS_CRYPTO — scripts/base_discovery_scan.py
══════════════════════════════════════════════════════════════════════════════
v4.7.2 — Base Discovery Coverage Audit. Adds full per-source
diagnostics (BOOSTED/PROFILED/SEARCH: HTTP status, raw item count
before the chain filter, Base-filtered count) so "zero results" can be
correctly attributed to either SOURCE UNAVAILABLE (request failed) or
ZERO_RESULTS (request succeeded, genuinely returned no Base matches) —
these are different states and were being silently conflated before.

Also fixes a real UX bug: candidates that pass every filter but don't
reach full EARLY MOVE convergence were previously shown only as a bare
count with no symbol name — now individually listed with which specific
conditions they're missing.

Search strategy changed from generic cross-chain terms (WETH/USDC) to
Base-native tokens (AERO/BRETT/DEGEN/TOSHI) — a documented-behavior-
based hypothesis (DexScreener's search caps at 30 results and ranks by
relevance across ALL chains, so generic terms likely get dominated by
Ethereum mainnet before any Base result survives), not a blind tune.
The new diagnostics will confirm or refute this on the next real run.

Boosted tokens remain a separate, labeled source rather than the whole
universe. Ordering: discovery → security → activity → Pearl. NOT
discovery → Pearl → security afterward.
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


def _gather_universe() -> dict:
    """Combines all discovery sources into one deduplicated pair list,
    returning the full per-source diagnostic breakdown alongside it —
    per v4.7.2's explicit requirement: distinguish SOURCE UNAVAILABLE
    from ZERO RESULTS, don't silently collapse either into 'no
    opportunities.'"""
    all_pairs = []
    source_diagnostics = []

    boosted_diag = dexscreener.fetch_boosted_base_tokens_diagnostic(limit=30)
    source_diagnostics.append(boosted_diag)
    log.info(f"Source BOOSTED: status={boosted_diag['status']}, "
             f"raw={boosted_diag['raw_item_count']}, base={boosted_diag['base_item_count']}")
    for t in boosted_diag["items"]:
        addr = t.get("tokenAddress")
        if not addr:
            continue
        pair = dexscreener.fetch_pair_data(addr, chain="base")
        if pair:
            pair["_source"] = "BOOSTED"
            all_pairs.append(pair)

    profiled_diag = dexscreener.fetch_profiled_base_tokens_diagnostic(limit=30)
    source_diagnostics.append(profiled_diag)
    log.info(f"Source PROFILED: status={profiled_diag['status']}, "
             f"raw={profiled_diag['raw_item_count']}, base={profiled_diag['base_item_count']}")
    for t in profiled_diag["items"]:
        addr = t.get("tokenAddress")
        if not addr:
            continue
        pair = dexscreener.fetch_pair_data(addr, chain="base")
        if pair:
            pair["_source"] = "PROFILED"
            all_pairs.append(pair)

    search_diag = dexscreener.fetch_search_base_pairs_diagnostic()
    source_diagnostics.append(search_diag)
    log.info(f"Source SEARCH: status={search_diag['status']}, "
             f"raw={search_diag['raw_item_count']}, base={search_diag['base_item_count']}, "
             f"per_query={search_diag.get('per_query')}")
    all_pairs.extend(search_diag["items"])

    deduped = dexscreener.dedupe_pairs_by_address(all_pairs)
    log.info(f"Total pairs discovered: {len(all_pairs)}, unique after dedup: {len(deduped)}")
    return {"pairs": deduped, "raw_total": len(all_pairs), "source_diagnostics": source_diagnostics}


def _source_diagnostic_line(diag: dict) -> str:
    if diag["source"] == "SEARCH":
        query_lines = "; ".join(
            f"{q['query']}: {q['status']} (raw={q['raw_count']}, base={q['base_count']})"
            for q in diag.get("per_query", []))
        return f"SEARCH — {diag['status']} | base={diag['base_item_count']} | {query_lines}"
    return (f"{diag['source']} — {diag['status']} | HTTP {diag.get('http_status')} | "
            f"raw={diag['raw_item_count']} | base={diag['base_item_count']}"
            + (f" | {diag['error']}" if diag.get("error") else ""))


def run() -> None:
    log.info("=== Base DEX Discovery v4.7.2 (coverage audit) ===")
    init_crypto_tables()

    flywheel_result = dex_flywheel.resolve_matured_dex_pairs()
    log.info(f"DEX flywheel: {flywheel_result}")

    universe = _gather_universe()
    all_pairs = universe["pairs"]
    source_diagnostics = universe["source_diagnostics"]
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

        pair_address = pair.get("pairAddress")
        symbol = snapshot["symbol"]

        scored = pearl_score.compute_pearl_score(
            symbol, snapshot, None, None, {"severity": "UNCHECKED"}, None)
        early_move = dexscreener.classify_dex_early_move(
            {"passes": True}, flow, accel, age_hours, security)

        entry = {"snapshot": snapshot, "source": pair.get("_source", "?"), "scored": scored,
                 "early_move": early_move, "pair_address": pair_address,
                 "pct_24h": flow.get("pct_24h"), "flow_label": flow.get("flow_label")}
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

    lines.append("<b>Source coverage</b>")
    for diag in source_diagnostics:
        lines.append(_source_diagnostic_line(diag))
    lines.append("")

    if early_moves:
        lines.append(f"🚨 <b>DEX EARLY MOVE ({len(early_moves)})</b>")
        for e in early_moves[:5]:
            snap = e["snapshot"]
            lead = get_dex_lead_time_vs_coingecko(snap["symbol"])
            lead_note = f" | {lead['detail']}" if lead.get("available") else ""
            lines.append(f"<b>{snap['symbol']}</b> [{e['source']}]{lead_note}\n"
                         f"   Fresh DEX activity + accelerating volume + strong buy imbalance\n"
                         f"   <i>Not a buy signal.</i>")

    # ── FIX: candidates that passed everything but aren't full EARLY MOVE
    # convergence must still be NAMED — a count with no symbol is useless.
    # ALSO FIX: the same token often has many DEX pools (AERO alone showed
    # 8 near-identical entries from 8 different pools) — collapse to ONE
    # line per unique symbol, keeping the highest-liquidity pool as the
    # representative, and note the pool count so nothing is hidden.
    if other_candidates:
        by_symbol: dict = {}
        for c in other_candidates:
            sym = c["snapshot"]["symbol"]
            by_symbol.setdefault(sym, []).append(c)

        collapsed = []
        for sym, pools in by_symbol.items():
            best = max(pools, key=lambda c: c["snapshot"].get("market_cap") or 0)
            best["_pool_count"] = len(pools)
            collapsed.append(best)

        lines.append(f"\n👀 <b>Passed security, not yet an early move ({len(collapsed)} unique token(s), "
                     f"{len(other_candidates)} pool(s) total)</b>")
        for c in collapsed[:8]:
            snap = c["snapshot"]
            missing = ", ".join(c["early_move"]["reasons_missing"][:2])
            pct = f"{c['pct_24h']:+.1f}%/24h" if c.get("pct_24h") is not None else ""
            pool_note = f" ({c['_pool_count']} pools)" if c["_pool_count"] > 1 else ""
            lines.append(f"   <b>{snap['symbol']}</b> [{c['source']}]{pool_note} {pct} — missing: {missing}")

    if not early_moves and not other_candidates:
        lines.append(f"No candidates passed the funnel this scan. That's a legitimate outcome for a "
                     f"single hourly snapshot — not evidence Base lacks opportunities.")

    lines.append(f"\n<i>Ordering: discovery → security → activity → Pearl engine. "
                 f"{len(blocked)} blocked by security before ever reaching scoring.</i>")

    message = "\n".join(lines)
    plain = message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
    log.info(plain)
    send_telegram(message)


if __name__ == "__main__":
    run()
