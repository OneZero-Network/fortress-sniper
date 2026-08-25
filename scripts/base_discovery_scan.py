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
from core.db import init_crypto_tables, log_dex_first_seen, get_dex_lead_time_vs_coingecko, log_dex_stage, get_dex_graduations
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

        if security["severity"] == "HIGH_RISK":
            blocked.append({"pair": pair, "security": security})
        else:
            after_security.append(pair)

    early_moves = []
    building_candidates = []
    other_candidates = []

    for pair in after_security:
        flow = dexscreener.compute_flow_signals(pair)
        snapshot = dexscreener.adapt_to_coin_snapshot(pair)

        pair_address = pair.get("pairAddress")
        symbol = snapshot["symbol"]
        early_move = pair["_early_move"]
        security = pair["_security"]

        # ── v4.7.6 — stage classification + per-scan logging for EVERY
        # candidate, not just Early Moves. This is the near-miss flywheel
        # your mentor asked for: BUILDINGCAT (+997%, 5/6 conditions met)
        # gets recorded as BUILDING instead of silently vanishing into
        # "other" — and the log entry lets a future scan detect if it
        # (or anything else) later graduates to EARLY_MOVE.
        stage_result = dexscreener.classify_dex_stage(early_move, security)
        if pair_address:
            log_dex_stage(pair_address, symbol, stage_result["stage"],
                          stage_result["conditions_met"], flow.get("pct_24h"))

        scored = pearl_score.compute_pearl_score(
            symbol, snapshot, None, None, {"severity": "UNCHECKED"}, None)

        entry = {"snapshot": snapshot, "source": pair.get("_source", "?"), "scored": scored,
                 "early_move": early_move, "stage": stage_result, "pair_address": pair_address,
                 "pct_24h": flow.get("pct_24h"), "flow_label": flow.get("flow_label")}
        if early_move["is_early_move"]:
            early_moves.append(entry)
        elif stage_result["stage"] == "BUILDING":
            building_candidates.append(entry)
        else:
            other_candidates.append(entry)

    log.info(f"Funnel (log only, not sent to Telegram): discovered={len(all_pairs)}, "
             f"unique_tokens={unique_tokens}, after_liquidity={len(after_liquidity)}, "
             f"after_activity={len(after_activity)}, after_security={len(after_security)}, "
             f"blocked={len(blocked)}, early_moves={len(early_moves)}, new_detections={new_detections}")
    log.info(f"Source coverage (log only): " + " | ".join(_source_diagnostic_line(d) for d in source_diagnostics))

    # ── v4.7.4 — TELEGRAM IS NOW THE DECISION LAYER, not the diagnostics
    # dump. Per explicit instruction: "If a number doesn't change what
    # the user should understand or do, it doesn't belong in Telegram."
    # All funnel/source numbers above are logged for the Sheet/engineering
    # record — Telegram gets outcome, not metrics.
    lines = []
    today = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%b %d").upper()

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

        total_monitored = len(building_candidates) + len(other_candidates)
        lines.append(f"🧭 <b>BASE DEX RADAR — {today}</b>\n")
        lines.append(f"Result: No Early Move confirmed today.")
        lines.append(f"{total_monitored} asset(s) passed safety + activity screening.\n")
        lines.append(f"🟡 {len(deduped_building)} building" if deduped_building else f"🟡 {total_monitored} being monitored")
        lines.append(f"🟢 0 security blocks" if not blocked else f"🔴 {len(blocked)} security block(s)")
        lines.append(f"⚡ 0 Early Moves")

        if deduped_building:
            lines.append(f"\n🟡 <b>BUILDING ({len(deduped_building)})</b> — real partial confirmation, not yet full convergence")
            for c in deduped_building[:3]:
                snap = c["snapshot"]
                pct = f"{c['pct_24h']:+.1f}%/24h" if c.get("pct_24h") is not None else "n/a"
                missing = c["early_move"]["reasons_missing"][0] if c["early_move"]["reasons_missing"] else "unconfirmed"
                lines.append(f"• <b>{snap['symbol']}</b> — {pct} — {c['stage']['conditions_met']}/6 conditions, "
                             f"missing: {missing}")
        else:
            unique_others: dict = {}
            for c in other_candidates:
                sym = c["snapshot"]["symbol"]
                unique_others.setdefault(sym, []).append(c)
            deduped_others = [max(pools, key=lambda c: c["snapshot"].get("market_cap") or 0)
                              for sym, pools in unique_others.items()]
            deduped_others.sort(key=lambda c: (len(c["early_move"]["reasons_missing"]), -(c.get("pct_24h") or 0)))
            if deduped_others:
                lines.append(f"\nClosest developing signals:")
                for c in deduped_others[:3]:
                    snap = c["snapshot"]
                    pct = f"{c['pct_24h']:+.1f}%/24h" if c.get("pct_24h") is not None else "n/a"
                    reason = c["early_move"]["reasons_missing"][0] if c["early_move"]["reasons_missing"] else "not yet confirmed"
                    lines.append(f"• <b>{snap['symbol']}</b> — {pct} — {reason}")

        # ── Graduations — pairs that were BUILDING at some point and
        # LATER showed EARLY_MOVE. Direct evidence about whether BUILDING
        # is a real precursor signal, not just noise.
        graduations = get_dex_graduations(days_back=7)
        if graduations:
            lines.append(f"\n📈 <b>Graduated this week ({len(graduations)})</b> — was BUILDING, later confirmed EARLY_MOVE")
            for g in graduations[:3]:
                lines.append(f"• {g['symbol']} — first flagged {g['first_building_at']}")

        lines.append(f"\nStatus: Monitoring for acceleration.")

    # ── Outcome resolutions — the 5-state vocabulary, per explicit spec ──
    resolutions = flywheel_result.get("resolutions", [])
    if resolutions:
        lines.append(f"\n🧪 <b>BASE OUTCOME{'S' if len(resolutions) > 1 else ''}</b>")
        for r in resolutions[:5]:
            lines.append(f"\n<b>{r['symbol']}</b>\n"
                         f"{r['horizon'].upper()} RESULT: {r['outcome']['status']}\n"
                         f"{r['return_pct']:+.1f}% from first detection\n"
                         f"Verdict: {r['outcome']['verdict']}")

    lines.append(f"\n<i>Full diagnostics (funnel counts, source coverage, raw data) → GitHub Actions log.</i>")

    message = "\n".join(lines)
    plain = message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
    log.info(plain)
    send_telegram(message)


if __name__ == "__main__":
    run()
