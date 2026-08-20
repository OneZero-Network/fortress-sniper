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
        f"<b>{c['symbol']}</b> — Discovery Score {c['discovery_score']}/100" if c["discovery_score"] is not None
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
    if c.get("pearl_thesis"):
        lines.append(f"   Incubator thesis: {c['pearl_thesis']}")
    lines.append(f"   Status: <b>{c['status']}</b>")
    return "\n".join(lines)


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

    candidates: List[dict] = []

    for pearl in watchlist:
        c = _score_candidate(pearl["symbol"], pearl["coin_id"], coin_snapshot=None,
                              is_watchlist_pearl=True, pearl_thesis=pearl.get("thesis"))
        if c and c["status"] is not None:
            candidates.append(c)

    universe = cdata.fetch_universe(top_n=COLD_SCAN_TOP_N)
    watchlist_symbols = {p["symbol"] for p in watchlist}
    coin_id_by_symbol = {p["symbol"]: p["coin_id"] for p in watchlist}
    coin_id_by_symbol.update({c["symbol"]: c["id"] for c in universe})
    log.info(f"Cold scan: {len(universe)} coins (excluding {len(watchlist_symbols)} already on watchlist)")

    for coin in universe:
        if coin["symbol"] in watchlist_symbols:
            continue
        c = _score_candidate(coin["symbol"], coin["id"], coin_snapshot=coin, is_watchlist_pearl=False)
        if c and c["status"] is not None:
            candidates.append(c)

    candidates.sort(key=lambda c: c["discovery_score"] or 0, reverse=True)

    pearl_candidates = [c for c in candidates if "INVESTIGATE" in (c["status"] or "")]
    watch_candidates = [c for c in candidates if c["status"] == "👀 WATCH"]
    avoid_candidates = [c for c in candidates if "AVOID" in (c["status"] or "")]

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

    header = (
        f"🔎 <b>FORTRESS_CRYPTO — Pearl Detection Machine</b> ({datetime.now(timezone.utc).strftime('%Y-%m-%d')})\n\n"
        f"📊 <b>Evidence Level: {ev['label']}</b>\n"
        f"<i>Every score below is built from unvalidated (Level 0) observation signals — "
        f"whale activity, news, liquidity, price structure, on-chain health. This means: "
        f"'deserves attention,' NOT 'will make money.' No layer here has been proven predictive yet — "
        f"research continues in parallel (see the Research Tools workflow).</i>\n\n"
        f"🌐 Market regime (context only — this layer is REJECTED, not used in scoring): {regime['label']}\n"
        f"{fw_line}\n"
    )

    if pearl_candidates or watch_candidates or avoid_candidates:
        lines = [header]
        if pearl_candidates:
            lines.append(f"\n━━━ 🔎 PEARL CANDIDATES ({len(pearl_candidates)}) ━━━\n")
            for c in pearl_candidates[:10]:
                lines.append(_format_candidate(c))
                lines.append("")
        if watch_candidates:
            lines.append(f"\n━━━ 👀 WATCH ({len(watch_candidates)}) ━━━")
            for c in watch_candidates[:8]:
                lines.append(f"   {c['symbol']}: {c['discovery_score']}/100, false-pearl risk {c['false_pearl_risk_pct']}%")
        if avoid_candidates:
            lines.append(f"\n━━━ 🚫 AVOID — false-pearl risk ({len(avoid_candidates)}) ━━━")
            for c in avoid_candidates[:8]:
                lines.append(f"   {c['symbol']}: {c['false_pearl_risk_pct']}% false-pearl risk (score would've been {c['discovery_score']})")
        message = "\n".join(lines)
    else:
        message = header + "\nNo candidates surfaced enough evidence today. That's a legitimate outcome, not a failure — this ran successfully and found nothing worth your attention right now."

    plain = message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
    log.info(plain)
    send_telegram(message)

    try:
        header_row = ["symbol", "is_watchlist_pearl", "discovery_score", "whale", "news", "liquidity",
                      "structure", "onchain", "false_pearl_risk_pct", "status", "reasons_why"]
        rows = [[c["symbol"], c["is_watchlist_pearl"], c["discovery_score"],
                 c["components"].get("whale"), c["components"].get("news"), c["components"].get("liquidity"),
                 c["components"].get("structure"), c["components"].get("onchain"),
                 c["false_pearl_risk_pct"], c["status"], "; ".join(c["reasons_why"])]
                for c in candidates]
        push_sheet("CRYPTO_PEARL_CANDIDATES", [header_row] + rows)
    except Exception as e:
        log.warning(f"Sheet push CRYPTO_PEARL_CANDIDATES failed: {e}")


if __name__ == "__main__":
    run()
