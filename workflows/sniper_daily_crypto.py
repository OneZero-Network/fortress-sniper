#!/usr/bin/env python3
"""
FORTRESS_CRYPTO — workflows/sniper_daily_crypto.py  (v2.7 — Pearl Detection Machine)
══════════════════════════════════════════════════════════════════════════════
PRODUCT REDEFINITION, per explicit mandate: Fortress does not predict the
market. It finds assets showing an unusual, evidence-backed combination
of positive signals, filters out obvious contract-level traps, explains
exactly why each candidate surfaced, and states what would invalidate
the thesis. Research (regime v2, W1/N1, F1, backtesting) continues in
parallel via scripts/*.py and can PROMOTE a layer into higher authority
here later — see core/crypto/evidence.py for the promotion mechanism.

WHAT CHANGED FROM THE OLD SNIPER: the RSI/ADX/volume "trigger" and
regime v1 are REJECTED (core/crypto/evidence.py) and have been REMOVED
from this file entirely — not down-weighted, removed. Discovery now
comes from core/crypto/pearl_score.py: whale accumulation, news
sentiment, liquidity health, descriptive price structure, and on-chain
concentration health. False-Pearl risk (contract security) can veto a
candidate outright regardless of how good everything else looks.

OUTPUT: every candidate is labeled "🔎 PEARL CANDIDATE — INVESTIGATE",
"👀 WATCH", or "🚫 AVOID (false-pearl risk)" — never BUY. That's
structurally enforced in pearl_score.py, not just a convention here.

The Evidence Level banner (currently Level 0 across every contributing
layer — see evidence.py) appears at the top of every message. This is
not a footnote; it's the single most important piece of context for
deciding how much to trust anything below it.
"""
from __future__ import annotations
import logging
import os
import sys
from datetime import datetime, timezone
from typing import List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.db import init_crypto_tables, save_pearl_observation
from core.telegram import send as send_telegram
from core.sheets_client import push_sheet
from core.crypto import config as ccfg
from core.crypto import data as cdata
from core.crypto import bridge_crypto
from core.crypto import news_sentiment
from core.crypto import onchain
from core.crypto import risk_engine
from core.crypto import regime as regime_module
from core.crypto import evidence
from core.crypto import pearl_score
from core.crypto import pearl_flywheel
from core.crypto import velocity_divergence

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                     datefmt="%H:%M:%S")
log = logging.getLogger("fortress.crypto.pearl_finder")

COLD_SCAN_TOP_N = int(os.getenv("CRYPTO_COLD_SCAN_TOP_N", "60"))


def _score_candidate(symbol: str, coin_id: str, coin_snapshot: Optional[dict],
                      is_watchlist_pearl: bool, pearl_thesis: Optional[str] = None,
                      liquidity_score_override: Optional[float] = None,
                      structure_score_override: Optional[float] = None) -> Optional[dict]:
    """Fetches whale/news/risk/on-chain signals for one candidate and
    runs them through pearl_score.compute_pearl_score(). Returns None on
    total failure (never a fabricated result)."""
    try:
        platforms = cdata.fetch_platforms(coin_id)
    except Exception as e:
        log.debug(f"platform fetch failed for {symbol}: {e}")
        platforms = {}

    whale_accum = None
    onchain_quality = None
    if onchain.is_onchain_supported(platforms):
        try:
            signal = onchain.whale_concentration_signal(platforms)
            whale_accum = onchain.whale_accumulation_delta(symbol, signal)
            onchain_quality = onchain.onchain_quality_score_0_100(signal)
        except Exception as e:
            log.debug(f"onchain check failed for {symbol}: {e}")

    news = None
    try:
        news = news_sentiment.sentiment_summary(symbol)
    except Exception as e:
        log.debug(f"news check failed for {symbol}: {e}")

    try:
        risk = risk_engine.assess_false_pearl_risk(platforms)
    except Exception as e:
        log.debug(f"risk check failed for {symbol}: {e}")
        risk = {"severity": "UNCHECKED"}

    result = pearl_score.compute_pearl_score(symbol, coin_snapshot, whale_accum, news, risk, onchain_quality,
                                              liquidity_score_override=liquidity_score_override,
                                              structure_score_override=structure_score_override)
    result["is_watchlist_pearl"] = is_watchlist_pearl
    result["pearl_thesis"] = pearl_thesis
    result["news"] = news
    result["whale_accum"] = whale_accum
    result["risk"] = risk
    result["_pct_7d"] = coin_snapshot.get("pct_7d") if coin_snapshot else None
    return result


def _format_candidate_short(c: dict) -> str:
    """Compact one-line format — symbol, score, Emergence (if computed),
    status. No component breakdown, no reasons/invalidation text — that
    detail still exists in the run log's FULL DETAIL section and the
    Sheets export, this is just what goes into the everyday Telegram
    message so it's actually scannable."""
    score = f"{c['discovery_score']:.0f}" if c["discovery_score"] is not None else "n/a"
    emergence = c.get("emergence_score")
    emg_tag = f" 🔥{emergence:.0f}" if emergence is not None else ""
    status_short = c["status"].split(" — ")[0] if c.get("status") else "?"
    tier_tag = f"[{c.get('universe_tier', '')}]" if c.get("universe_tier") not in (None, "WATCHLIST") else ""
    return f"{c['symbol']} {tier_tag} — {score}/100{emg_tag} — {status_short}"


def _format_candidate(c: dict) -> str:
    comps = c["components"]

    def _fmt_comp(name, emoji, label):
        v = comps.get(name)
        if v is None:
            return f"   {emoji} {label}: n/a"
        tier = "STRONG" if v >= 70 else "MODERATE" if v >= 50 else "WEAK"
        return f"   {emoji} {label}: {tier} ({v:.0f}/100)"

    lines = [
        (f"<b>{c['symbol']}</b> [{c.get('universe_tier', 'UNKNOWN')}] — Discovery Score {c['discovery_score']}/100 "
         f"(Evidence Completeness: {c['evidence_completeness_pct']}%)"
         + (f" — top {c['tier_percentile']}% of {c.get('universe_tier')}" if c.get("tier_percentile") else "")
         ) if c["discovery_score"] is not None
        else f"<b>{c['symbol']}</b> [{c.get('universe_tier', 'UNKNOWN')}] — Discovery Score n/a",
        _fmt_comp("whale", "🐋", "Whale activity"),
        _fmt_comp("news", "📰", "News/catalyst"),
        _fmt_comp("liquidity", "💧", "Liquidity"),
        _fmt_comp("structure", "📈", "Price structure"),
        _fmt_comp("onchain", "🔗", "On-chain health"),
        f"   🛡️ Contract risk: {c['false_pearl_risk_pct']}% false-pearl probability",
    ]
    if c["reasons_why"]:
        lines.append(f"   Why it surfaced: {'; '.join(c['reasons_why'])}")
    lines.append(f"   Would be invalidated by: {'; '.join(c['invalidation_conditions'])}")

    vel = c.get("velocity")
    div = c.get("divergence")
    if vel:
        vel_bits = []
        if vel.get("volume_label"):
            vel_bits.append(f"volume {vel['volume_label']} ({vel['volume_ratio']}x 7d avg)")
        if vel.get("acceleration_label"):
            vel_bits.append(f"momentum {vel['acceleration_label']} ({vel['price_acceleration_pct']:+.1f}pp)")
        if vel_bits:
            lines.append(f"   ⚡ Velocity (Level 0, observation only): {'; '.join(vel_bits)}")
    if div and div.get("available") and div.get("label") != "ALIGNED":
        emoji = "🧩" if div["label"] == "BULLISH_DIVERGENCE" else "⚠️"
        lines.append(f"   {emoji} Divergence (Level 0, observation only): {div['detail']}")

    ra = c.get("relative_anomaly")
    if ra and ra.get("available"):
        lines.append(f"   🧭 Relative to peers (Level 0, observation only): {ra['label']}")
    if c.get("pearl_thesis"):
        lines.append(f"   Incubator thesis: {c['pearl_thesis']}")
    lines.append(f"   Status: <b>{c['status']}</b>")
    return "\n".join(lines)


def _tally_diagnostic(c: Optional[dict], diag: dict) -> None:
    """Updates the pipeline diagnostic counters for one candidate,
    whatever happened to it — this is what makes the bottleneck visible
    instead of candidates silently vanishing."""
    if c is None:
        diag["rejected_missing_data"] += 1
        return
    diag["usable"] += 1
    n_avail = len(c.get("components_available", []))
    if n_avail == 0:
        diag["rejected_missing_data"] += 1
        return
    diag["entered_scorer"] += 1

    score = c.get("discovery_score")
    if score is not None:
        if score >= 90:
            diag["score_90plus"] += 1
        elif score >= 80:
            diag["score_80_89"] += 1
        elif score >= 70:
            diag["score_70_79"] += 1
        elif score >= 60:
            diag["score_60_69"] += 1

    tier = c.get("tier")
    reject = c.get("reject_reason")
    if tier == "PEARL":
        diag["final_pearl"] += 1
    elif tier == "HIGH_POTENTIAL":
        diag["final_high_potential"] += 1
    elif tier == "CANDIDATE":
        diag["final_candidate"] += 1
    elif tier == "WATCH":
        diag["final_watch"] += 1
    elif tier == "FALSE_PEARL":
        diag["final_false_pearl"] += 1
        diag["rejected_false_pearl"] += 1
    elif reject == "INSUFFICIENT_EVIDENCE":
        diag["rejected_insufficient_evidence"] += 1
    elif reject == "MISSING_DATA":
        diag["rejected_missing_data"] += 1


def run() -> None:
    log.info(f"=== {ccfg.VERSION} — PEARL DETECTION MACHINE ===")
    init_crypto_tables()

    # ── PEARL FLYWHEEL — resolve yesterday's (and older) observations
    # FIRST, before scoring anything new. Same discipline as the old
    # outcome_tracker: every prior Pearl gets checked against real price
    # action and specific invalidation triggers before today's scan runs.
    flywheel_summary = pearl_flywheel.resolve_matured_pearls()
    log.info(f"Pearl flywheel: {flywheel_summary}")

    ev = evidence.overall_evidence_level()
    log.info(f"Overall evidence level: {ev['label']}")

    # Regime is computed and shown as CONTEXT ONLY — it is a REJECTED
    # layer (v1) and does not contribute to any score. See evidence.py.
    regime = regime_module.detect_market_regime()
    log.info(f"Market regime (context only, REJECTED layer, not scored): {regime['label']}")

    watchlist = bridge_crypto.load_active_watchlist()
    log.info(f"Watchlist: {len(watchlist)} pearl(s) from Incubator")

    # ── v3.2 MULTI-UNIVERSE SCANNER — replaces the single ~60-coin flat
    # scan. Fetches Large/Mid/Emerging tiers, applies a cheap pre-filter
    # funnel (no extra API calls), and only the bounded shortlist that
    # survives proceeds to expensive per-coin scoring below.
    from core.crypto import multi_universe
    shortlist = multi_universe.fetch_multi_universe_shortlist()
    watchlist_symbols = {p["symbol"] for p in watchlist}
    coin_id_by_symbol = {p["symbol"]: p["coin_id"] for p in watchlist}
    coin_id_by_symbol.update({c["symbol"]: c["id"] for c in shortlist})
    tier_by_symbol = {c["symbol"]: c["universe_tier"] for c in shortlist}
    log.info(f"Multi-universe shortlist: {len(shortlist)} coins across "
             f"{len(set(tier_by_symbol.values()))} tiers (excluding {len(watchlist_symbols)} already on watchlist)")

    # ── v2.9 PIPELINE DIAGNOSTIC — tracks every candidate through every
    # stage, including ones the old code silently dropped. Per explicit
    # instruction: this instruments the pipeline to find where it's
    # bottlenecking, WITHOUT changing the underlying discovery_score math
    # or any threshold.
    universe_size = len(watchlist) + len(shortlist) - len(watchlist_symbols & {c["symbol"] for c in shortlist})
    diag = {"universe": universe_size, "scanned": 0, "usable": 0, "entered_scorer": 0,
            "rejected_missing_data": 0, "rejected_false_pearl": 0, "rejected_insufficient_evidence": 0,
            "score_90plus": 0, "score_80_89": 0, "score_70_79": 0, "score_60_69": 0,
            "final_pearl": 0, "final_high_potential": 0, "final_candidate": 0, "final_watch": 0, "final_false_pearl": 0}

    all_scored: List[dict] = []  # every candidate that got a discovery_score, regardless of tier

    for pearl in watchlist:
        diag["scanned"] += 1
        c = _score_candidate(pearl["symbol"], pearl["coin_id"], coin_snapshot=None,
                              is_watchlist_pearl=True, pearl_thesis=pearl.get("thesis"))
        _tally_diagnostic(c, diag)
        if c:
            all_scored.append(c)

    # ── v3.4 TIER-RELATIVE LIQUIDITY/STRUCTURE SCORING — pre-pass, zero
    # extra API calls (uses coin_snapshot data already fetched). Fixes a
    # real bug found in production: the old absolute formula saturated
    # near 100 for almost any reasonably-liquid Large/Mid-cap coin
    # (verified: AVAX/RED/MAGMA all showed identical 100/100 liquidity
    # despite genuinely different turnover ratios). Now each coin's
    # liquidity/structure score reflects where it actually sits among
    # its OWN tier's peers this run.
    from core.crypto import pearl_score as pscore
    raw_liq_by_tier: dict = {}
    raw_struct_by_tier: dict = {}
    for coin in shortlist:
        tier = coin["universe_tier"]
        raw_liq_by_tier.setdefault(tier, {})[coin["symbol"]] = pscore.raw_liquidity_metric(coin)
        raw_struct_by_tier.setdefault(tier, {})[coin["symbol"]] = pscore.raw_structure_metric(coin)

    liquidity_pct_by_symbol: dict = {}
    structure_pct_by_symbol: dict = {}
    for tier, raw_map in raw_liq_by_tier.items():
        peer_values = list(raw_map.values())
        for sym, raw_val in raw_map.items():
            liquidity_pct_by_symbol[sym] = pscore.percentile_rank(raw_val, peer_values)
    for tier, raw_map in raw_struct_by_tier.items():
        peer_values = list(raw_map.values())
        for sym, raw_val in raw_map.items():
            structure_pct_by_symbol[sym] = pscore.percentile_rank(raw_val, peer_values)

    skipped_budget = []
    for coin in shortlist:
        if coin["symbol"] in watchlist_symbols:
            continue
        # ── v3.3 API BUDGET — graceful stop, never a crash, never
        # fabricated data for candidates that don't get checked. Reports
        # exactly how many were skipped and why, in the coverage summary.
        if cdata.budget_exhausted():
            skipped_budget.append(coin["symbol"])
            continue
        diag["scanned"] += 1
        c = _score_candidate(coin["symbol"], coin["id"], coin_snapshot=coin, is_watchlist_pearl=False,
                              liquidity_score_override=liquidity_pct_by_symbol.get(coin["symbol"]),
                              structure_score_override=structure_pct_by_symbol.get(coin["symbol"]))
        _tally_diagnostic(c, diag)
        if c:
            c["universe_tier"] = coin["universe_tier"]
            all_scored.append(c)

    if skipped_budget:
        log.warning(f"API budget exhausted — skipped {len(skipped_budget)} candidate(s): {skipped_budget[:10]}"
                    f"{'...' if len(skipped_budget) > 10 else ''}")

    for c in all_scored:
        if "universe_tier" not in c:
            c["universe_tier"] = "WATCHLIST"  # incubator pearls aren't rank-tiered

    multi_universe.compute_within_tier_ranking(all_scored)

    all_scored.sort(key=lambda c: c["discovery_score"] or 0, reverse=True)

    pearl_tier = [c for c in all_scored if c.get("tier") == "PEARL"]
    high_potential_tier = [c for c in all_scored if c.get("tier") == "HIGH_POTENTIAL"]
    candidate_tier = [c for c in all_scored if c.get("tier") == "CANDIDATE"]
    watch_tier = [c for c in all_scored if c.get("tier") == "WATCH"]
    false_pearl_tier = [c for c in all_scored if c.get("tier") == "FALSE_PEARL"]

    # ── v3.0 Change & Divergence Engine — Level 0 observation layer,
    # computed SELECTIVELY only for the shortlist that will be displayed
    # (Pearl/High-Potential/Candidate), never for the full scanned
    # universe, since it costs one extra OHLC fetch per candidate.
    # PURELY ADDITIVE: does not touch discovery_score, tier, or ranking
    # anywhere — see core/crypto/velocity_divergence.py's module docstring.
    for c in pearl_tier + high_potential_tier + candidate_tier:
        coin_id = coin_id_by_symbol.get(c["symbol"])
        try:
            vd = velocity_divergence.get_velocity_and_divergence(
                coin_id, c.get("_pct_7d"), c.get("whale_accum"))
            c["velocity"] = vd["velocity"]
            c["divergence"] = vd["divergence"]
        except Exception as e:
            log.debug(f"velocity/divergence check failed for {c['symbol']}: {e}")
            c["velocity"] = None
            c["divergence"] = {"available": False, "label": "NONE", "detail": "check failed"}

    # ── v3.3 Relative/Peer Anomaly — zero extra API calls, reuses
    # velocity data already gathered above. Compares each shortlisted
    # candidate's volume/momentum change against ITS OWN universe_tier
    # peers, not the whole market.
    shortlisted = pearl_tier + high_potential_tier + candidate_tier
    velocities_by_tier: dict = {}
    for c in shortlisted:
        velocities_by_tier.setdefault(c.get("universe_tier", "UNKNOWN"), []).append(c.get("velocity"))
    for c in shortlisted:
        tier = c.get("universe_tier", "UNKNOWN")
        peers = [v for v in velocities_by_tier.get(tier, []) if v is not None]
        c["relative_anomaly"] = velocity_divergence.compute_relative_anomaly(c.get("velocity"), peers)
        c["emergence_score"] = pearl_score.compute_emergence_score(c.get("velocity"), c.get("relative_anomaly"))

    # keep the old grouping names for the rest of the message-building
    # code below — pearl+high-potential+candidate tiers all surface as
    # "investigate", HIGH_POTENTIAL is displayed in its own section below
    pearl_candidates = pearl_tier + high_potential_tier + candidate_tier
    watch_candidates = watch_tier
    avoid_candidates = false_pearl_tier

    log.info(f"Pipeline diagnostic: {diag}")

    # ── v3.1 MEASUREMENT SCAFFOLD — save today's row BEFORE anything
    # else, so a crash later in the run doesn't lose the day's baseline
    # data. Tag with CRYPTO_DATA_PERIOD_LABEL so you can mark which days
    # are 'FREE_BASELINE' vs a later paid-data experiment period.
    from core.db import save_daily_metrics
    completeness_values = [c["evidence_completeness_pct"] for c in all_scored
                            if c.get("evidence_completeness_pct") is not None and c.get("discovery_score") is not None]
    discovery_scores = [c["discovery_score"] for c in all_scored if c.get("discovery_score") is not None]
    top_pearl_score = max((c["discovery_score"] for c in pearl_tier), default=None)
    top_hp_score = max((c["discovery_score"] for c in high_potential_tier), default=None)

    def _median(vals):
        if not vals:
            return None
        s = sorted(vals)
        n = len(s)
        mid = n // 2
        return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2

    try:
        save_daily_metrics({
            "data_period_label": os.getenv("CRYPTO_DATA_PERIOD_LABEL", "FREE_BASELINE"),
            "assets_scanned": diag["scanned"], "entered_scorer": diag["entered_scorer"],
            "avg_completeness_pct": round(sum(completeness_values) / len(completeness_values), 1) if completeness_values else None,
            "median_completeness_pct": _median(completeness_values),
            "high_potential_count": diag["final_high_potential"], "pearl_count": diag["final_pearl"],
            "candidate_count": diag["final_candidate"], "watch_count": diag["final_watch"],
            "false_pearl_count": diag["final_false_pearl"],
            "missing_data_rejection_count": diag["rejected_missing_data"],
            "insufficient_evidence_count": diag["rejected_insufficient_evidence"],
            "top_pearl_score": top_pearl_score, "top_high_potential_score": top_hp_score,
            "avg_discovery_score": round(sum(discovery_scores) / len(discovery_scores), 1) if discovery_scores else None,
        })
        log.info("Daily metrics saved to crypto_daily_metrics")
    except Exception as e:
        log.warning(f"Failed to save daily metrics: {e}")

    # ── LOG immutable snapshots for every PEARL CANDIDATE and WATCH (not
    # AVOID — a rejected candidate has nothing to track forward). This
    # feeds the flywheel that answers "was the machine right."
    for c in pearl_candidates + watch_candidates:
        try:
            coin_id = coin_id_by_symbol.get(c["symbol"])
            live_price = cdata.fetch_live_price_binance(c["symbol"])
            if coin_id and live_price:
                save_pearl_observation({
                    "symbol": c["symbol"], "coin_id": coin_id, "price_at_observation": live_price,
                    "discovery_score": c["discovery_score"], "evidence_level": ev["level"],
                    "evidence_label": ev["label"],
                    "whale_score": c["components"].get("whale"),
                    "whale_label_at_discovery": (c.get("whale_accum") or {}).get("label"),
                    "news_score": c["components"].get("news"),
                    "news_label_at_discovery": (c.get("news") or {}).get("label"),
                    "liquidity_score": c["components"].get("liquidity"),
                    "structure_score": c["components"].get("structure"),
                    "onchain_score": c["components"].get("onchain"),
                    "false_pearl_risk_pct": c["false_pearl_risk_pct"],
                    "risk_severity_at_discovery": (c.get("risk") or {}).get("severity", "UNCHECKED"),
                    "status_at_discovery": c["status"],
                    "tier_at_discovery": c.get("tier"),
                    "why_it_surfaced": "; ".join(c["reasons_why"]),
                    "invalidation_conditions": "; ".join(c["invalidation_conditions"]),
                })
        except Exception as e:
            log.warning(f"Failed to log pearl observation for {c['symbol']}: {e}")

    log.info(f"{len(pearl_candidates)} PEARL CANDIDATE(s), {len(watch_candidates)} WATCH, "
             f"{len(avoid_candidates)} AVOID")

    coverage_note = (f" | ⚠️{len(skipped_budget)} budget-skipped" if skipped_budget else "")
    rate_limit_note = " | ⚠️rate-limited" if cdata.was_rate_limited_this_run() else ""
    diagnostic_block = (
        f"Scanned {diag['scanned']}, scored {diag['entered_scorer']}{coverage_note}{rate_limit_note} — "
        f"⭐{diag['final_pearl']} 🔎HP{diag['final_high_potential']} "
        f"Cand{diag['final_candidate']} 👀{diag['final_watch']} 🚫{diag['final_false_pearl']}\n"
    )

    header = (
        f"🔎 <b>FORTRESS_CRYPTO — Pearl Detection Machine</b> ({datetime.now(timezone.utc).strftime('%Y-%m-%d')})\n"
        f"📊 Evidence Level: {ev['label']} — deserves attention, NOT a buy/sell signal.\n"
        f"🌐 Regime (context only, not scored): {regime['label']}\n\n"
        f"{diagnostic_block}"
    )

    if pearl_tier or high_potential_tier or candidate_tier or watch_candidates or avoid_candidates:
        lines = [header]
        if pearl_tier:
            lines.append(f"\n⭐ <b>PEARLS ({len(pearl_tier)})</b>")
            for c in pearl_tier[:15]:
                lines.append(_format_candidate_short(c))
        if high_potential_tier:
            lines.append(f"\n🔎 <b>HIGH-POTENTIAL ({len(high_potential_tier)})</b> — score 80+, evidence incomplete")
            for c in high_potential_tier[:15]:
                score = f"{c['discovery_score']:.0f}" if c["discovery_score"] is not None else "n/a"
                emergence = c.get("emergence_score")
                emg_tag = f" 🔥{emergence:.0f}" if emergence is not None else ""
                lines.append(f"{c['symbol']} — {score}/100{emg_tag} — worth a manual look")
        if candidate_tier:
            lines.append(f"\n🔎 <b>CANDIDATES ({len(candidate_tier)})</b>")
            for c in candidate_tier[:15]:
                lines.append(_format_candidate_short(c))
        if watch_candidates:
            lines.append(f"\n👀 <b>WATCH ({len(watch_candidates)})</b>")
            for c in watch_candidates[:15]:
                lines.append(f"{c['symbol']} — {c['discovery_score']:.0f}/100")
        if avoid_candidates:
            lines.append(f"\n🚫 <b>FALSE PEARLS ({len(avoid_candidates)})</b> — high risk, do not investigate")
            for c in avoid_candidates[:15]:
                lines.append(f"{c['symbol']} — {c['false_pearl_risk_pct']}% false-pearl risk")
        lines.append(f"\n<i>Full detail (why each surfaced, component breakdown, velocity/divergence) "
                     f"is in the CRYPTO_PEARL_CANDIDATES sheet — this message is intentionally compact.</i>")
        message = "\n".join(lines)
    else:
        message = header + "\nNo candidates surfaced enough evidence today. That's a legitimate outcome, not a failure — this ran successfully and found nothing worth your attention right now."

    plain = message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
    log.info(plain)

    # ── FULL-DETAIL LOG (GitHub Actions log only, NOT Telegram) — the
    # compact message deliberately dropped component breakdowns to keep
    # Telegram readable, but that also silently removed the ability to
    # inspect WHY a top candidate scored what it did without opening the
    # Sheet. This restores that visibility in the run log, where it
    # belongs for debugging/inspection without re-bloating Telegram.
    log.info("=== FULL DETAIL: top candidates (log only, not sent to Telegram) ===")
    for c in (pearl_tier + high_potential_tier + candidate_tier)[:15]:
        log.info(f"--- {c['symbol']} ---")
        log.info(f"  discovery_score={c['discovery_score']}, evidence_completeness_pct={c['evidence_completeness_pct']}%, "
                 f"emergence_score={c.get('emergence_score')}, tier={c.get('tier')}, false_pearl_risk_pct={c['false_pearl_risk_pct']}")
        log.info(f"  components: {c['components']}")
        log.info(f"  components_available: {c['components_available']}")
        news_state = c.get("news") or {}
        log.info(f"  news: available={news_state.get('available')}, label={news_state.get('label')}, "
                 f"forward_catalyst={news_state.get('forward_catalyst')}")
        whale_state = c.get("whale_accum") or {}
        log.info(f"  whale: available={whale_state.get('available')}, label={whale_state.get('label')}")
        ra = c.get("relative_anomaly") or {}
        log.info(f"  relative_anomaly: {ra}")
        log.info(f"  reasons_why: {c['reasons_why']}")
        log.info(f"  invalidation_conditions: {c['invalidation_conditions']}")

    send_telegram(message)

    try:
        header_row = ["symbol", "is_watchlist_pearl", "discovery_score", "evidence_completeness_pct", "tier",
                      "emergence_score", "whale", "news", "liquidity", "structure", "onchain",
                      "false_pearl_risk_pct", "status", "reasons_why"]
        rows = [[c["symbol"], c["is_watchlist_pearl"], c["discovery_score"], c["evidence_completeness_pct"], c["tier"],
                 c.get("emergence_score"),
                 c["components"].get("whale"), c["components"].get("news"), c["components"].get("liquidity"),
                 c["components"].get("structure"), c["components"].get("onchain"),
                 c["false_pearl_risk_pct"], c["status"], "; ".join(c["reasons_why"])]
                for c in all_scored]
        push_sheet("CRYPTO_PEARL_CANDIDATES", [header_row] + rows)
    except Exception as e:
        log.warning(f"Sheet push CRYPTO_PEARL_CANDIDATES failed: {e}")


if __name__ == "__main__":
    run()
