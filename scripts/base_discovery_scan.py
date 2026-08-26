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
from core.db import init_crypto_tables, log_dex_first_seen, get_dex_lead_time_vs_coingecko, log_dex_stage, get_dex_graduations, get_dex_unchanged_streak, get_dex_chain_cursor, set_dex_chain_cursor, get_dex_prior_liquidity, get_dex_chain_cursor_v2, set_dex_chain_cursor_v2, log_dex_lifecycle, get_hours_since_last_chain_discovery
from core.crypto import dexscreener
from core.crypto import dex_flywheel
from core.crypto import pearl_score
from core.crypto import base_chain

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
    any_chain_source_failed = False

    # ── v4.9.8/v4.9.13 — CHAIN_EVENT sources, first and highest priority.
    # Reads PoolCreated-shaped events directly off Base — genuinely new
    # pairs, zero search/curation bias. Now covers BOTH Uniswap V3 AND
    # Aerodrome (Base's largest DEX by volume, previously an
    # acknowledged gap), each with its OWN independent cursor so a
    # failure or slow period on one never affects the other.
    for dex_name in base_chain.DEX_REGISTRY:
        chain_cursor = get_dex_chain_cursor_v2(dex_name)
        chain_result = base_chain.discover_new_pools(dex_name, chain_cursor)
        chain_status = chain_result["status"]
        if chain_status == "RPC_ERROR":
            any_chain_source_failed = True
        new_pools = chain_result["new_pools"]
        source_label = f"CHAIN_EVENT_{dex_name.upper()}"
        log.info(f"Source {source_label}: status={chain_status}, cursor={chain_cursor} -> "
                 f"{chain_result['new_cursor']}, new_pools_found={len(new_pools)}")
        source_diagnostics.append({"source": source_label, "http_status": None,
                                   "raw_item_count": len(new_pools), "base_item_count": len(new_pools),
                                   "status": chain_status,
                                   "error": f"Base RPC eth_getLogs failed for {dex_name} — see log" if chain_status == "RPC_ERROR" else None})
        # discover_new_pools() guarantees new_cursor == the input cursor
        # unchanged whenever status is RPC_ERROR — safe to call
        # unconditionally, verified directly.
        set_dex_chain_cursor_v2(dex_name, chain_result["new_cursor"])
        # v4.9.14 CRITICAL FIX, found by tracing a real discovered pool
        # end-to-end: this used to try token0 first, falling back to
        # token1 only if token0 had no data. WHICHEVER token happens to
        # be well-known (WETH, USDC, etc.) will ALWAYS have data, so
        # that fallback never triggers — the genuinely new counterpart
        # token is silently never looked up. Confirmed directly: a real
        # Aerodrome discovery scored as "WETH" (10/90, IGNORE) instead
        # of its actual new pairing, because WETH was token0 in that
        # specific pool. Fixed: explicitly identify and skip known
        # quote/base currencies, use the OTHER side — that's the
        # genuinely new token, which is the whole point of this source.
        for pool in new_pools:
            known_quote_tokens = {
                "0x4200000000000000000000000000000000000006",  # WETH (Base)
                "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",  # USDC (Base)
                "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca",  # USDbC (Base)
                "0x50c5725949a6f0c72e6c4a641f24049a917db0cb",  # DAI (Base)
                "0x2ae3f1ec7f1f5012cfeab0185bfc7aa3cf0dec22",  # cbETH (Base)
            }
            t0_lower = pool["token0"].lower()
            t1_lower = pool["token1"].lower()
            if t0_lower in known_quote_tokens and t1_lower not in known_quote_tokens:
                new_token_address = pool["token1"]
            elif t1_lower in known_quote_tokens and t0_lower not in known_quote_tokens:
                new_token_address = pool["token0"]
            else:
                # neither or both are known quote tokens — genuinely
                # ambiguous, default to token0 rather than guess further
                new_token_address = pool["token0"]

            pair = dexscreener.fetch_pair_data(new_token_address, chain="base")
            if not pair:
                # fall back to the other side only if the identified
                # "new" token has no DexScreener data at all
                fallback_address = pool["token1"] if new_token_address == pool["token0"] else pool["token0"]
                pair = dexscreener.fetch_pair_data(fallback_address, chain="base")
            if pair:
                pair["_source"] = source_label
                all_pairs.append(pair)

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

    top_boosted_diag = dexscreener.fetch_top_boosted_base_tokens_diagnostic(limit=30)
    source_diagnostics.append(top_boosted_diag)
    log.info(f"Source TOP_BOOSTED: status={top_boosted_diag['status']}, "
             f"raw={top_boosted_diag['raw_item_count']}, base={top_boosted_diag['base_item_count']}")
    for t in top_boosted_diag["items"]:
        addr = t.get("tokenAddress")
        if not addr:
            continue
        pair = dexscreener.fetch_pair_data(addr, chain="base")
        if pair:
            pair["_source"] = "TOP_BOOSTED"
            all_pairs.append(pair)

    search_diag = dexscreener.fetch_search_base_pairs_diagnostic()
    source_diagnostics.append(search_diag)
    log.info(f"Source SEARCH: status={search_diag['status']}, "
             f"raw={search_diag['raw_item_count']}, base={search_diag['base_item_count']}, "
             f"per_query={search_diag.get('per_query')}")
    all_pairs.extend(search_diag["items"])

    deduped = dexscreener.dedupe_pairs_by_address(all_pairs)
    log.info(f"Total pairs discovered: {len(all_pairs)}, unique after dedup: {len(deduped)}")
    return {"pairs": deduped, "raw_total": len(all_pairs), "source_diagnostics": source_diagnostics,
            "chain_status": "RPC_ERROR" if any_chain_source_failed else "OK"}


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
    log.info("=== Base DEX Discovery v4.9.5 (Pre-Pearl active, log-only diagnostics) ===")
    init_crypto_tables()

    flywheel_result = dex_flywheel.resolve_matured_dex_pairs()
    log.info(f"DEX flywheel: {flywheel_result}")

    universe = _gather_universe()
    all_pairs = universe["pairs"]
    source_diagnostics = universe["source_diagnostics"]
    chain_status = universe["chain_status"]
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
    new_pool_count = 0  # v4.9.14 — genuinely NEW pools from chain-event sources specifically
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
        early_move = dexscreener.classify_dex_early_move(
            {"passes": True}, flow, accel, age_hours, security)
        pair["_early_move"] = early_move

        if pair_address and symbol:
            was_new = log_dex_first_seen(
                pair_address, symbol, "base", float(pair.get("priceUsd") or 0), liq_usd, vol_usd,
                txns_24h.get("buys"), txns_24h.get("sells"), age_hours,
                accel.get("vol_accel_ratio"), flow["flow_label"], security["severity"],
                is_early_move=early_move["is_early_move"])
            if was_new:
                new_detections += 1
                if (pair.get("_source") or "").startswith("CHAIN_EVENT"):
                    new_pool_count += 1

        if security["severity"] == "HIGH_RISK":
            blocked.append({"pair": pair, "security": security})
        else:
            after_security.append(pair)

    early_moves = []
    pre_pearl_candidates = []
    building_candidates = []
    other_candidates = []

    for pair in after_security:
        flow = dexscreener.compute_flow_signals(pair)
        accel = dexscreener.compute_acceleration(pair)
        age_hours = dexscreener.compute_pair_age_hours(pair)
        snapshot = dexscreener.adapt_to_coin_snapshot(pair)
        liquidity_usd = (pair.get("liquidity") or {}).get("usd")

        pair_address = pair.get("pairAddress")
        symbol = snapshot["symbol"]
        early_move = pair["_early_move"]
        security = pair["_security"]

        # ── v4.7.6 — stage classification + per-scan logging for EVERY
        # candidate, not just Early Moves.
        stage_result = dexscreener.classify_dex_stage(early_move, security)
        unchanged_streak = 0
        prior_liquidity = get_dex_prior_liquidity(pair_address) if pair_address else None
        if pair_address:
            log_dex_stage(pair_address, symbol, stage_result["stage"],
                          stage_result["conditions_met"], flow.get("pct_24h"), liquidity_usd=liquidity_usd)
            unchanged_streak = get_dex_unchanged_streak(pair_address, stage_result["stage"], stage_result["conditions_met"])

        # ── v4.9.3 (OLD, all-or-nothing) — kept only for direct
        # side-by-side comparison during the transition to the weighted
        # score below. NOT used for classification anymore.
        precursor = dexscreener.compute_dex_precursor(
            age_hours, accel, flow, security, early_move.get("already_extended", False))

        # ── v4.9.12 — REPLACES the all-or-nothing convergence gate,
        # per explicit diagnosis: 6 simultaneous AND conditions made
        # firing statistically near-impossible even for genuine
        # precursor behavior. This is now the PRIMARY classification.
        pre_pearl = dexscreener.compute_pre_pearl_score(
            age_hours, accel, flow, security, early_move.get("already_extended", False),
            liquidity_usd, prior_liquidity)

        # v4.9.18 — PRICE LAG + NEW/AWAKENING, per the broader discovery
        # architecture mandate. Log-only for now, per explicit "don't add
        # another Telegram section" instruction — these are new signals
        # to observe and evaluate on their own merit before they earn a
        # place in the score or the message.
        price_lag = dexscreener.compute_activity_price_lag(accel, flow)
        had_prior = prior_liquidity is not None
        new_or_awakening = dexscreener.classify_new_vs_awakening(age_hours, had_prior)

        # v4.9.15 — permanent lifecycle record for EVERY candidate that
        # reaches scoring, regardless of final disposition. This is
        # what makes "nothing disappeared silently" a provable claim.
        if pair_address:
            log_dex_lifecycle(
                pair_address, symbol, pair.get("_source", "?"), age_hours, liquidity_usd,
                (pair.get("volume") or {}).get("h24"), flow.get("pct_24h"),
                pre_pearl["conditions"]["pair_new"], pre_pearl["conditions"]["liquidity_accel"],
                pre_pearl["conditions"]["volume_accel"], pre_pearl["conditions"]["tx_accel"],
                pre_pearl["conditions"]["buy_pressure"], pre_pearl["conditions"]["price_near_base"],
                early_move.get("already_extended", False), security.get("severity"),
                pre_pearl["score"], pre_pearl["classification"], pre_pearl["breakdown"])

        # Forensic logging for EVERY candidate, at INFO level (the fix
        # for the invisible-diagnostic bug) — shows both old and new
        # classification side by side, so the transition itself is
        # auditable, not just asserted.
        log.info(f"{symbol}: OLD gate={'PASS' if precursor['is_pre_pearl'] else 'FAIL'} "
                 f"(signals met: {precursor.get('signals_met')}) | NEW score={pre_pearl['score']}/90 "
                 f"-> {pre_pearl['classification']} | {pre_pearl['breakdown']} | "
                 f"category={new_or_awakening['category']} | price_lag={price_lag['label']} "
                 f"({price_lag.get('detail')})")

        scored = pearl_score.compute_pearl_score(
            symbol, snapshot, None, None, {"severity": "UNCHECKED"}, None)

        entry = {"snapshot": snapshot, "source": pair.get("_source", "?"), "scored": scored,
                 "early_move": early_move, "stage": stage_result, "precursor": precursor,
                 "pre_pearl": pre_pearl, "pair_address": pair_address, "pct_24h": flow.get("pct_24h"),
                 "flow_label": flow.get("flow_label"), "unchanged_streak": unchanged_streak}
        # ── v4.9.12 — bucketing now driven by the weighted score, not
        # the old all-or-nothing gate. EARLY_MOVE still uses its own
        # price-confirmed definition (a distinct, later-stage signal);
        # everything else is now PRE_PEARL/BUILDING/WATCH by score.
        if early_move["is_early_move"]:
            early_moves.append(entry)
        elif pre_pearl["classification"] == "🟢 PRE-PEARL":
            pre_pearl_candidates.append(entry)
        elif pre_pearl["classification"] == "🟡 BUILDING":
            building_candidates.append(entry)
        else:
            other_candidates.append(entry)

    log.info(f"Funnel (log only, not sent to Telegram): discovered={len(all_pairs)}, "
             f"unique_tokens={unique_tokens}, after_liquidity={len(after_liquidity)}, "
             f"after_activity={len(after_activity)}, after_security={len(after_security)}, "
             f"blocked={len(blocked)}, early_moves={len(early_moves)}, pre_pearl={len(pre_pearl_candidates)}, "
             f"new_detections={new_detections}")
    log.info(f"Source coverage (log only): " + " | ".join(_source_diagnostic_line(d) for d in source_diagnostics))

    # ── v4.7.4 — TELEGRAM IS NOW THE DECISION LAYER, not the diagnostics
    # dump. Per explicit instruction: "If a number doesn't change what
    # the user should understand or do, it doesn't belong in Telegram."
    # All funnel/source numbers above are logged for the Sheet/engineering
    # record — Telegram gets outcome, not metrics.
    lines = []
    today = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%b %d").upper()

    # ── v4.9.21 — DISCOVERY HEALTH, rebuilt per explicit format:
    # "SEARCH must never masquerade as discovery" — split into CHAIN
    # (genuinely new) vs SEARCH (existing/monitoring), each labeled
    # distinctly, plus a per-source LIVE/STALE heartbeat so a broken
    # source is visible immediately instead of inferred from identical
    # messages days apart.
    chain_diag = {d["source"]: d for d in source_diagnostics if d["source"].startswith("CHAIN_EVENT")}
    search_pool_count = len(all_pairs) - new_pool_count
    any_chain_broken = any(d["status"] == "RPC_ERROR" for d in chain_diag.values())
    hours_since_chain_discovery = get_hours_since_last_chain_discovery()

    lines.append(f"🧭 <b>DEX DISCOVERY HEALTH — {today}</b>\n")
    lines.append(f"<b>Chain coverage</b>")
    for dex_label, diag in chain_diag.items():
        short_name = dex_label.replace("CHAIN_EVENT_", "").title()
        if diag["status"] == "RPC_ERROR":
            heartbeat = "🔴 BROKEN — RPC failed, cursor not advancing, this run is not trustworthy"
        elif diag["status"] in ("OK", "OK_ZERO_RESULTS"):
            heartbeat = "🟢 LIVE/QUIET — queried successfully"
        else:
            heartbeat = f"🟡 {diag['status']}"
        lines.append(f"   {short_name}: {heartbeat} — {diag['base_item_count']} new pool(s)")

    # v4.9.22 — the 3-state classification, per explicit spec: LIVE/QUIET
    # (nothing happened, machine is fine) vs BROKEN (this run isn't
    # trustworthy) vs STARVED (machine works but production coverage is
    # dominated by old/search pools for an extended stretch).
    if any_chain_broken:
        overall_status = "🔴 BROKEN — at least one chain source failed this run"
    elif hours_since_chain_discovery is None:
        overall_status = "🟡 STARVED — no chain-discovered candidate has EVER been logged yet"
    elif hours_since_chain_discovery >= 24:
        overall_status = f"🟡 STARVED — {hours_since_chain_discovery:.0f}h since last chain-discovered candidate"
    else:
        overall_status = f"🟢 LIVE/QUIET — last chain-discovered candidate {hours_since_chain_discovery:.1f}h ago"
    lines.append(f"\n<b>Discovery status:</b> {overall_status}")

    lines.append(f"\n<b>CHAIN NEW</b>: {new_pool_count} pool(s), {unique_tokens if new_pool_count else 0} token(s)")
    lines.append(f"<b>SEARCH / EXISTING</b>: {search_pool_count} pool(s) monitored (NOT counted as new discovery)")
    lines.append(f"\nPassed security: {len(after_security)} | Blocked: {len(blocked)}")
    lines.append(f"Pre-Pearls: {len(pre_pearl_candidates)} | Early Moves: {len(early_moves)}\n")

    # ── v4.9.9 — the explicit product-principle fix: "No Early Move"
    # must NEVER be conflated with "discovery itself failed." These are
    # completely different states, and the difference matters more than
    # any scoring feature. If the highest-priority discovery source
    # (chain-native, zero search bias) failed this run, say so plainly
    # BEFORE any result claim — a "No Early Move" conclusion drawn while
    # the newest, least-biased source couldn't even run is not a
    # trustworthy conclusion.
    if chain_status == "RPC_ERROR":
        lines.append(f"🔴 <b>DISCOVERY DEGRADED — {today}</b>")
        lines.append(f"Chain-native discovery (CHAIN_EVENT) failed this run — Base RPC eth_getLogs "
                     f"request was rejected. The results below rely ONLY on DexScreener sources "
                     f"(search/boosted/profiled), which are known to be narrower and more name-biased. "
                     f"Treat any 'no opportunity' conclusion below with that caveat in mind.\n")

    # ── v4.9.3 — DEX PRE-PEARL, shown FIRST when present. This is
    # deliberately the earliest, most valuable signal: genuine multi-
    # signal activity convergence on a brand-new, not-yet-moved pair —
    # before price acceleration itself, which is what BUILDING/EARLY_MOVE
    # both require. "How much did the asset move AFTER Fortress first
    # detected this" is exactly the measurement the flywheel now tracks.
    if pre_pearl_candidates:
        unique_pp: dict = {}
        for c in pre_pearl_candidates:
            sym = c["snapshot"]["symbol"]
            unique_pp.setdefault(sym, []).append(c)
        deduped_pp = [max(pools, key=lambda c: len(c["precursor"]["signals_met"])) for sym, pools in unique_pp.items()]
        deduped_pp.sort(key=lambda c: -len(c["precursor"]["signals_met"]))

        lines.append(f"🟡 <b>PRE-PEARL — {today}</b>")
        lines.append(f"<i>Activity accelerating on a new pair, price hasn't caught up yet. "
                     f"This is the earliest signal the DEX lens produces.</i>\n")
        for c in deduped_pp[:5]:
            snap = c["snapshot"]
            signals = ", ".join(c["precursor"]["signals_met"])
            lines.append(f"<b>{snap['symbol']}</b> — {signals}\n"
                         f"Status: Watching for confirmation\n")

    if early_moves:
        lines.append(f"💎 <b>BASE EARLY DISCOVERY — {today}</b>\n")
        for e in early_moves[:5]:
            snap = e["snapshot"]
            lead = get_dex_lead_time_vs_coingecko(snap["symbol"])
            lead_note = f"\n{lead['detail']}" if lead.get("available") else ""
            lines.append(f"<b>{snap['symbol']}</b>\n"
                         f"🟢 EARLY MOVE DETECTED\n"
                         f"Why now: accelerating volume + buying pressure + fresh activity{lead_note}\n"
                         f"Status: Investigate\n"
                         f"Evidence: Level 0 — unvalidated\n"
                         f"Next: Outcome tracking 1h → 6h → 24h\n")
    else:
        # ── BUILDING candidates take priority for display — they're
        # genuinely closer to qualifying (2+ conditions met) than
        # anything in "other_candidates" (0-1 conditions). Dedupe by
        # symbol same as before.
        unique_building: dict = {}
        for c in building_candidates:
            sym = c["snapshot"]["symbol"]
            unique_building.setdefault(sym, []).append(c)
        deduped_building = []
        for sym, pools in unique_building.items():
            best = max(pools, key=lambda c: c["stage"]["conditions_met"])
            deduped_building.append(best)
        deduped_building.sort(key=lambda c: (-c["stage"]["conditions_met"], -(c.get("pct_24h") or 0)))

        # ── v4.9.7 fix: "where is visibility of symbol name 15, what
        # does it mean?" — the header was counting RAW pool-level
        # candidates (many pools per token), while only unique SYMBOLS
        # ever get named below. 15 pools can genuinely mean 3 unique
        # tokens after dedup — the header must say the number that
        # matches what's actually nameable, computed BEFORE printing
        # anything, from BOTH branches, so it's always accurate.
        unique_others: dict = {}
        for c in other_candidates:
            if c["early_move"].get("already_extended"):
                continue
            sym = c["snapshot"]["symbol"]
            unique_others.setdefault(sym, []).append(c)
        deduped_others = [max(pools, key=lambda c: c["snapshot"].get("market_cap") or 0)
                          for sym, pools in unique_others.items()]
        deduped_others.sort(key=lambda c: (len(c["early_move"]["reasons_missing"]), -(c.get("pct_24h") or 0)))

        # v4.9.14 fix: the header count previously excluded pre_pearl_candidates
        # entirely — a real pre-Pearl hit would show "0 unique tokens" here,
        # exactly the confusing case just found in production (GENUINELYNEW
        # reached Pre-Pearl but the header still said 0).
        display_unique_count = len(deduped_building) if deduped_building else len(deduped_others)
        total_unique_this_scan = display_unique_count + len(pre_pearl_candidates)

        lines.append(f"🧭 <b>BASE DEX RADAR — {today}</b>\n")
        lines.append(f"Result: No Early Move confirmed today.")
        # v4.9.14 terminology fix, per explicit instruction: "88 DEX
        # pairs scanned" reads like 88 opportunities searched — it isn't.
        lines.append(f"{new_pool_count} new pool(s) discovered + {len(all_pairs) - new_pool_count} "
                     f"existing/search pool(s) monitored → {total_unique_this_scan} unique token(s) "
                     f"passed safety + activity screening.\n")
        lines.append(f"🟡 {display_unique_count} being monitored")
        lines.append(f"🟢 0 security blocks" if not blocked else f"🔴 {len(blocked)} security block(s)")
        lines.append(f"🟡 {len(pre_pearl_candidates)} Pre-Pearl")
        lines.append(f"⚡ 0 Early Moves")

        if deduped_building:
            fresh_building = [c for c in deduped_building if c["unchanged_streak"] < 3]
            stale_building = [c for c in deduped_building if c["unchanged_streak"] >= 3]

            if fresh_building:
                lines.append(f"\n🟡 <b>BUILDING ({len(fresh_building)})</b> — real partial confirmation, not yet full convergence")
                for c in fresh_building[:3]:
                    snap = c["snapshot"]
                    pct = f"{c['pct_24h']:+.1f}%/24h" if c.get("pct_24h") is not None else "n/a"
                    missing = c["early_move"]["reasons_missing"][0] if c["early_move"]["reasons_missing"] else "unconfirmed"
                    lines.append(f"• <b>{snap['symbol']}</b> — {pct} — {c['stage']['conditions_met']}/6 conditions, "
                                 f"missing: {missing}")
            # ── v4.9.1 fix: "on each hourly run it's giving the same
            # outcome" — a candidate unchanged for 3+ consecutive scans
            # provides zero new information (its structural blocker, like
            # pool age, cannot resolve on its own). Named once, not
            # repeated with full detail every hour.
            if stale_building:
                stale_names = ", ".join(c["snapshot"]["symbol"] for c in stale_building[:5])
                lines.append(f"\n⏸️ <b>Unchanged {stale_building[0]['unchanged_streak']}+ scans "
                             f"({len(stale_building)})</b>: {stale_names} — no new signal, still logged")
            if not fresh_building and not stale_building:
                lines.append(f"\n(no building candidates this scan)")
        else:
            # ── v4.9.2 fix: this fallback branch was NEVER given the
            # unchanged-streak suppression built in v4.9.1 — AERO/BRETT/
            # TOSHI land HERE (0-1 conditions met), not in the BUILDING
            # branch, which is exactly why the earlier fix had zero
            # effect in production. Same fresh/stale split, applied here.
            fresh_others = [c for c in deduped_others if c["unchanged_streak"] < 3]
            stale_others = [c for c in deduped_others if c["unchanged_streak"] >= 3]

            if fresh_others:
                lines.append(f"\nClosest developing signals:")
                for c in fresh_others[:3]:
                    snap = c["snapshot"]
                    pct = f"{c['pct_24h']:+.1f}%/24h" if c.get("pct_24h") is not None else "n/a"
                    reason = c["early_move"]["reasons_missing"][0] if c["early_move"]["reasons_missing"] else "not yet confirmed"
                    lines.append(f"• <b>{snap['symbol']}</b> — {pct} — {reason}")
            if stale_others:
                stale_names = ", ".join(c["snapshot"]["symbol"] for c in stale_others[:5])
                lines.append(f"\n⏸️ <b>Unchanged {stale_others[0]['unchanged_streak']}+ scans "
                             f"({len(stale_others)})</b>: {stale_names} — no new signal, still logged")
            if not fresh_others and not stale_others:
                lines.append(f"\n(no candidates this scan)")

        # ── Graduations — pairs that were BUILDING at some point and
        # LATER showed EARLY_MOVE. Direct evidence about whether BUILDING
        # is a real precursor signal, not just noise.
        graduations = get_dex_graduations(days_back=7)
        if graduations:
            lines.append(f"\n📈 <b>Graduated this week ({len(graduations)})</b> — was BUILDING, later confirmed EARLY_MOVE")
            for g in graduations[:3]:
                lines.append(f"• {g['symbol']} — first flagged {g['first_building_at']}")

        lines.append(f"\nStatus: Monitoring for acceleration.")

    # ── Outcome resolutions — the 5-state vocabulary, per explicit spec.
    # v4.9.11 fix: resolutions are per PAIR ADDRESS, not per symbol — a
    # token with 7+ pools (like AERO) can have several pools resolve at
    # the same horizon in the same run, previously printing as N near-
    # identical entries with no indication they're different pools of
    # the same token. Aggregated by (symbol, horizon) — same collapsing
    # discipline already used for BUILDING/closest-signals sections.
    resolutions = flywheel_result.get("resolutions", [])
    if resolutions:
        grouped: dict = {}
        for r in resolutions:
            key = (r["symbol"], r["horizon"])
            grouped.setdefault(key, []).append(r)

        lines.append(f"\n🧪 <b>BASE OUTCOME{'S' if len(grouped) > 1 else ''}</b>")
        for (symbol, horizon), group in list(grouped.items())[:5]:
            if len(group) == 1:
                r = group[0]
                lines.append(f"\n<b>{symbol}</b>\n"
                             f"{horizon.upper()} RESULT: {r['outcome']['status']}\n"
                             f"{r['return_pct']:+.1f}% from first detection\n"
                             f"Verdict: {r['outcome']['verdict']}")
            else:
                returns = [r["return_pct"] for r in group]
                avg_return = sum(returns) / len(returns)
                statuses = set(r["outcome"]["status"] for r in group)
                status_str = group[0]["outcome"]["status"] if len(statuses) == 1 else "⚠️ MIXED"
                verdict = group[0]["outcome"]["verdict"] if len(statuses) == 1 else \
                    "Pools of this token showed different outcomes — see Sheet for per-pool detail."
                lines.append(f"\n<b>{symbol}</b> ({len(group)} pools)\n"
                             f"{horizon.upper()} RESULT: {status_str}\n"
                             f"Avg {avg_return:+.1f}% (range {min(returns):+.1f}% to {max(returns):+.1f}%) "
                             f"from first detection\n"
                             f"Verdict: {verdict}")

    lines.append(f"\n<i>Full diagnostics (funnel counts, source coverage, raw data) → GitHub Actions log.</i>")

    message = "\n".join(lines)
    plain = message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
    log.info(plain)
    send_telegram(message)


if __name__ == "__main__":
    run()
