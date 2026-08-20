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
                      is_watchlist_pearl: bool, pearl_thesis: Optional[str] = None) -> Optional[dict]:
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

    result = pearl_score.compute_pearl_score(symbol, coin_snapshot, whale_accum, news, risk, onchain_quality)
    result["is_watchlist_pearl"] = is_watchlist_pearl
    result["pearl_thesis"] = pearl_thesis
    result["news"] = news
    result["whale_accum"] = whale_accum
    result["risk"] = risk
    result["_pct_7d"] = coin_snapshot.get("pct_7d") if coin_snapshot else None
    return result


def _format_candidate(c: dict) -> str:
    comps = c["components"]

    def _fmt_comp(name, emoji, label):
        v = comps.get(name)
        if v is None:
            return f"   {emoji} {label}: n/a"
        tier = "STRONG" if v >= 70 else "MODERATE" if v >= 50 else "WEAK"
        return f"   {emoji} {label}: {tier} ({v:.0f}/100)"

    lines = [
        (f"<b>{c['symbol']}</b> — Discovery Score {c['discovery_score']}/100 "
         f"(Evidence Completeness: {c['evidence_completeness_pct']}%)") if c["discovery_score"] is not None
        else f"<b>{c['symbol']}</b> — Discovery Score n/a",
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

    universe = cdata.fetch_universe(top_n=COLD_SCAN_TOP_N)
    watchlist_symbols = {p["symbol"] for p in watchlist}
    coin_id_by_symbol = {p["symbol"]: p["coin_id"] for p in watchlist}
    coin_id_by_symbol.update({c["symbol"]: c["id"] for c in universe})
    log.info(f"Cold scan: {len(universe)} coins (excluding {len(watchlist_symbols)} already on watchlist)")

    # ── v2.9 PIPELINE DIAGNOSTIC — tracks every candidate through every
    # stage, including ones the old code silently dropped. Per explicit
    # instruction: this instruments the pipeline to find where it's
    # bottlenecking, WITHOUT changing the underlying discovery_score math
    # or any threshold.
    universe_size = len(watchlist) + len(universe) - len(watchlist_symbols & {c["symbol"] for c in universe})
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

    for coin in universe:
        if coin["symbol"] in watchlist_symbols:
            continue
        diag["scanned"] += 1
        c = _score_candidate(coin["symbol"], coin["id"], coin_snapshot=coin, is_watchlist_pearl=False)
        _tally_diagnostic(c, diag)
        if c:
            all_scored.append(c)

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

    from core.db import get_pearl_flywheel_stats
    fw_stats = get_pearl_flywheel_stats()
    fw_line = ("📊 Track record so far: " + ", ".join(f"{k}={v}" for k, v in sorted(fw_stats.items()))
               if fw_stats else "📊 Track record: no resolved observations yet — flywheel just started")

    diagnostic_block = (
        f"🔬 <b>PEARL PIPELINE DIAGNOSTIC</b> — {datetime.now(timezone.utc).strftime('%d %b')}\n"
        f"Universe: {diag['universe']} | Scanned: {diag['scanned']} | Usable: {diag['usable']} | "
        f"Entered scorer: {diag['entered_scorer']}\n"
        f"Rejected — missing data: {diag['rejected_missing_data']} | "
        f"false pearl: {diag['rejected_false_pearl']} | "
        f"insufficient evidence: {diag['rejected_insufficient_evidence']}\n"
        f"Score distribution — 90+: {diag['score_90plus']} | 80-89: {diag['score_80_89']} | "
        f"70-79: {diag['score_70_79']} | 60-69: {diag['score_60_69']}\n"
        f"Final — ⭐ Pearls: {diag['final_pearl']} | 🔎 High-Potential: {diag['final_high_potential']} | "
        f"Candidates: {diag['final_candidate']} | 👀 Watch: {diag['final_watch']} | 🚫 False Pearls: {diag['final_false_pearl']}\n"
    )

    header = (
        f"🔎 <b>FORTRESS_CRYPTO — Pearl Detection Machine</b> ({datetime.now(timezone.utc).strftime('%Y-%m-%d')})\n\n"
        f"📊 <b>Evidence Level: {ev['label']}</b>\n"
        f"<i>Every score below is built from unvalidated (Level 0) observation signals — "
        f"whale activity, news, liquidity, price structure, on-chain health. This means: "
        f"'deserves attention,' NOT 'will make money.' No layer here has been proven predictive yet — "
        f"research continues in parallel (see the Research Tools workflow).</i>\n\n"
        f"🌐 Market regime (context only — this layer is REJECTED, not used in scoring): {regime['label']}\n"
        f"{fw_line}\n\n"
        f"{diagnostic_block}"
    )

    if pearl_tier or high_potential_tier or candidate_tier or watch_candidates or avoid_candidates:
        lines = [header]
        if pearl_tier:
            lines.append(f"\n━━━ ⭐ PEARLS ({len(pearl_tier)}) ━━━\n")
            for c in pearl_tier[:10]:
                lines.append(_format_candidate(c))
                lines.append("")
        if high_potential_tier:
            lines.append(f"\n━━━ 🔎 HIGH-POTENTIAL ({len(high_potential_tier)}) — score clears 80, but evidence coverage is incomplete ━━━\n")
            for c in high_potential_tier[:10]:
                missing = [n for n in ("whale", "news", "liquidity", "structure", "onchain")
                           if n not in c.get("components_available", [])]
                lines.append(f"<b>{c['symbol']}</b> — Score {c['discovery_score']}/100 "
                             f"(Evidence completeness {c['evidence_completeness_pct']}%)\n"
                             f"   Missing: {', '.join(missing) if missing else 'none'}\n"
                             f"   Status: insufficient evidence for Pearl — worth a manual look")
                lines.append("")
        if candidate_tier:
            lines.append(f"\n━━━ 🔎 CANDIDATES ({len(candidate_tier)}) — interesting but incomplete evidence ━━━\n")
            for c in candidate_tier[:10]:
                lines.append(_format_candidate(c))
                lines.append("")
        if watch_candidates:
            lines.append(f"\n━━━ 👀 WATCH ({len(watch_candidates)}) ━━━")
            for c in watch_candidates[:8]:
                lines.append(f"   {c['symbol']}: {c['discovery_score']}/100, evidence completeness {c['evidence_completeness_pct']}%, false-pearl risk {c['false_pearl_risk_pct']}%")
        if avoid_candidates:
            lines.append(f"\n━━━ 🚫 FALSE PEARLS ({len(avoid_candidates)}) ━━━")
            for c in avoid_candidates[:8]:
                lines.append(f"   {c['symbol']}: {c['false_pearl_risk_pct']}% false-pearl risk (score would've been {c['discovery_score']})")
        message = "\n".join(lines)
    else:
        message = header + "\nNo candidates surfaced enough evidence today. That's a legitimate outcome, not a failure — this ran successfully and found nothing worth your attention right now."

    plain = message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
    log.info(plain)
    send_telegram(message)

    try:
        header_row = ["symbol", "is_watchlist_pearl", "discovery_score", "evidence_completeness_pct", "tier",
                      "whale", "news", "liquidity", "structure", "onchain",
                      "false_pearl_risk_pct", "status", "reasons_why"]
        rows = [[c["symbol"], c["is_watchlist_pearl"], c["discovery_score"], c["evidence_completeness_pct"], c["tier"],
                 c["components"].get("whale"), c["components"].get("news"), c["components"].get("liquidity"),
                 c["components"].get("structure"), c["components"].get("onchain"),
                 c["false_pearl_risk_pct"], c["status"], "; ".join(c["reasons_why"])]
                for c in all_scored]
        push_sheet("CRYPTO_PEARL_CANDIDATES", [header_row] + rows)
    except Exception as e:
        log.warning(f"Sheet push CRYPTO_PEARL_CANDIDATES failed: {e}")


if __name__ == "__main__":
    run()
