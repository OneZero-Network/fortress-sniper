#!/usr/bin/env python3
"""
FORTRESS_UNIFIED — workflows/sniper_daily.py
══════════════════════════════════════════════════════════════════════════════
Daily entrypoint (GHA: schedule ~cron '30 10 * * 1-5' IST after EOD data
settles). Two passes:

  PASS A — PEARL WATCHLIST (priority, always runs first, small N):
    Every ACTIVE/IGNITED symbol from core.bridge.load_active_watchlist()
    gets the full deep pipeline regardless of today's bhavcopy liquidity
    rank. This is the fix for "Incubator finds pearls and nobody watches
    them" — previously the two systems didn't talk at all.
    Ignition is checked; pedigree + ignition bonus applied to fused score;
    ignited pearls get marked and telegram-alerted with priority framing.

  PASS B — COLD SCAN (broad market, existing sniper_v7 behavior):
    Bhavcopy-ranked top MAX_CANDIDATES, same gates as before, heist-after-
    gate (restored — v8.2's heist-before-gate hammered NSE for all ~400
    candidates; heist only makes sense for the handful that already
    cleared the math gates).

Both passes feed into ONE combined results list, ONE lane selection, ONE
outcome/meta-label table — no more split brains.
"""
from __future__ import annotations
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import config, preflight_secrets
from core.db import init_db, get_conn
from core.nse_data import load_bhavcopy, fetch_history, get_last_trading_day
from core.macro import fetch_macro_regime, macro_subscore_0_100
from core.scoring import fortress_score, apex_composite, fused_score, compute_confidence_score
from core.shariah import full_audit
from core.bridge import (load_active_watchlist, check_ignition, mark_ignited,
                          apply_pedigree_bonus, unified_conviction)
from core.telegram import send as send_telegram
from core.sheets_client import push_sheet, read_sheet

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                     datefmt="%H:%M:%S")
log = logging.getLogger("fortress.sniper")


def _dummy_order_flow() -> dict:
    """Placeholder order-flow dict where NSE delivery/whale data isn't
    fetched in this trimmed build step — real deployment wires
    compute_eod_order_flow() from the legacy sniper module here."""
    return {"whale_score": 0, "vol_ratio": 1.0, "at_vpoc_support": False,
            "whale_flag": False, "vpoc": 0, "delivery_pct": 0}


def score_symbol(sym: str, close: float, hist, macro: dict,
                  is_pearl: bool = False, pearl_row: dict = None) -> dict:
    """Shared scoring path for both watchlist and cold-scan symbols."""
    if hist is None or hist.empty or len(hist) < 20:
        return {}

    order_flow = _dummy_order_flow()
    sector = (pearl_row or {}).get("sector", "UNKNOWN")

    fort = fortress_score(sym, close, hist, sector, macro, order_flow)
    if not fort or fort.get("fort_pts", 0) < 45:
        return {}

    # Shariah — single fail-safe engine
    audit = full_audit(sym, industry=sector)
    if not audit["compliant"]:
        log.info(f"  GATE SHARIAH  | {sym:14s} | {audit['reason']}")
        return {}

    apex_d = apex_composite(fort, macro)
    bayes_pct = 55.0  # placeholder — legacy bayes_win_probability() wired in full build
    fused = fused_score(fort, apex_d, bayes_pct)

    ignition = {"ignited": False}
    if is_pearl:
        ignition = check_ignition(pearl_row, hist)
        if ignition["ignited"]:
            mark_ignited(sym, close)

    fused_adjusted = apply_pedigree_bonus(fused, is_pearl=is_pearl, ignited=ignition["ignited"])

    if fused_adjusted < config.APEX_MIN_SCORE:
        return {}

    conf = compute_confidence_score(fort["fort_pts"], apex_d["apex_comp"], bayes_pct,
                                     fort["whale_score"], fort["rsi14"], fort["adx14"])
    if conf < config.CONFIDENCE_MIN:
        return {}

    thesis_score = (pearl_row or {}).get("incubator_score", 50.0) if is_pearl else 50.0
    conviction = unified_conviction(
        thesis_score_0_100=min(100.0, thesis_score),
        trigger_score_0_100=fused_adjusted,
        macro_score_0_100=macro_subscore_0_100(macro),
        entry_score_0_100=100.0,  # Pine hasn't seen this yet at scan time
    )

    return {
        **fort, "apex_comp": apex_d["apex_comp"], "fused": fused_adjusted,
        "bayes_pct": bayes_pct, "confidence_score": conf,
        "conviction_score": conviction,
        "is_pearl": is_pearl, "ignited": ignition["ignited"],
        "ignition_reason": ignition.get("reason", ""),
        "halal_tier": audit["layer"],
    }


def run_pearl_pass(macro: dict) -> List[dict]:
    """PASS A — priority scan of the pearl watchlist."""
    watchlist = load_active_watchlist()
    log.info(f"Pearl pass: {len(watchlist)} active/ignited pearls to check")
    results = []
    for pearl in watchlist:
        sym = pearl["symbol"]
        hist = fetch_history(sym, days=300)
        if hist.empty:
            continue
        close = float(hist["close"].iloc[-1])
        r = score_symbol(sym, close, hist, macro, is_pearl=True, pearl_row=pearl)
        if r:
            r["source"] = "PEARL_WATCHLIST"
            results.append(r)
            tag = "🔥 IGNITED" if r["ignited"] else "👁 watching"
            log.info(f"  {tag} {sym:12s} | conviction={r['conviction_score']} | fused={r['fused']}")
    return results


def run_cold_scan(macro: dict) -> List[dict]:
    """PASS B — broad bhavcopy-ranked market scan (existing behavior)."""
    bhav, bhav_src = load_bhavcopy()
    if bhav.empty:
        log.error("Cold scan: bhavcopy empty on all tiers — skipping pass B")
        return []
    log.info(f"Cold scan: bhavcopy {len(bhav)} rows from {bhav_src}")

    cands = bhav[(bhav["close"] >= config.MIN_PRICE) & (bhav["close"] <= config.MAX_PRICE) &
                 (bhav["turnover_lakhs"] >= config.MIN_TURNOVER_LAKHS)].head(config.MAX_CANDIDATES)
    log.info(f"Cold scan: {len(cands)} candidates after price/liquidity filter")

    hist_cache: Dict[str, object] = {}
    hist_lock = threading.Lock()

    def _preload(sym):
        h = fetch_history(sym, days=300)
        if not h.empty:
            with hist_lock:
                hist_cache[sym] = h

    with ThreadPoolExecutor(max_workers=12) as ex:
        list(ex.map(_preload, cands["symbol"].tolist()))
    log.info(f"Cold scan: history preloaded for {len(hist_cache)}/{len(cands)} symbols")

    results = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(score_symbol, row["symbol"], row["close"],
                          hist_cache.get(row["symbol"]), macro, False, None): row["symbol"]
                for _, row in cands.iterrows()}
        for fut in as_completed(futs):
            sym = futs[fut]
            try:
                r = fut.result(timeout=30)
                if r:
                    r["source"] = "COLD_SCAN"
                    results.append(r)
            except Exception as e:
                log.debug(f"{sym}: {e}")
    log.info(f"Cold scan: {len(results)} passed all gates")
    return results


def select_winners(results: List[dict]) -> List[dict]:
    """Rank by unified conviction_score, take top APEX_TOP_N, but always
    keep any ignited pearl regardless of rank — an ignition event is
    actionable news, not just a high score."""
    if not results:
        return []
    ignited = [r for r in results if r.get("ignited")]
    ranked = sorted(results, key=lambda r: r["conviction_score"], reverse=True)
    top = ranked[:config.APEX_TOP_N]
    seen = {r["symbol"] for r in top}
    for r in ignited:
        if r["symbol"] not in seen:
            top.append(r)
            seen.add(r["symbol"])
    return top


def push_results_to_sheets(winners: List[dict], date_label: str) -> None:
    header = ["Date", "Symbol", "Source", "Conviction", "Fused", "FortPts", "ApexComp",
              "Confidence", "IsPearl", "Ignited", "Grade", "Close", "StopLoss",
              "R1", "R2", "R3", "Shares", "HalalTier", "Story"]
    rows = [header]
    for w in winners:
        rows.append([
            date_label, w["symbol"], w["source"], w["conviction_score"], w["fused"],
            w["fort_pts"], w["apex_comp"], w["confidence_score"],
            "YES" if w["is_pearl"] else "", "YES" if w["ignited"] else "",
            w["grade"], w["close"], w["stop_loss"], w["r1"], w["r2"], w["r3"],
            w["shares"], w["halal_tier"], w["story"],
        ])
    existing = read_sheet("SCREENER")
    if existing and len(existing) > 1:
        body = [r for r in existing[1:] if not (r and r[0] == date_label)]
        rows = [header] + body + rows[1:]
    push_sheet("SCREENER", rows)


def send_alerts(winners: List[dict], macro: dict, date_label: str) -> None:
    if not winners:
        send_telegram(f"📋 <b>FORTRESS_UNIFIED Sniper — {date_label}</b>\n"
                       f"Regime: {macro['macro_state']} | No picks cleared gates today.")
        return
    lines = [f"🎯 <b>FORTRESS_UNIFIED Sniper — {date_label}</b>",
             f"Regime: {macro['macro_state']} | VIX={macro.get('vix_val', 0):.1f}", ""]
    for w in winners:
        badge = "🔥 IGNITED PEARL" if w["ignited"] else ("💎 pearl (watching)" if w["is_pearl"] else "")
        lines.append(f"<b>{w['symbol']}</b> {badge} — Conviction {w['conviction_score']}/100")
        lines.append(f"   {w['grade']} | Entry ~₹{w['close']:.0f} | Stop ₹{w['stop_loss']:.0f} | "
                     f"R1 ₹{w['r1']:.0f}")
        if w["ignited"]:
            lines.append(f"   🔥 {w['ignition_reason']}")
        lines.append("")
    send_telegram("\n".join(lines))


def run() -> List[dict]:
    log.info("=" * 70)
    log.info(f"  {config.VERSION} — SNIPER DAILY")
    log.info("=" * 70)
    init_db()
    preflight_secrets()

    _, date_label = get_last_trading_day()
    macro = fetch_macro_regime()

    if macro["macro_state"] == "MASSACRE":
        log.warning("MASSACRE regime — skipping all scans (capital preservation)")
        send_telegram(f"⚠️ <b>FORTRESS_UNIFIED — {date_label}</b>\n"
                       f"MASSACRE regime (VIX={macro['vix_val']:.1f}) — no scan today.")
        return []

    pearl_results = run_pearl_pass(macro)
    cold_results = run_cold_scan(macro)
    all_results = pearl_results + cold_results

    if not all_results:
        send_telegram(f"📋 <b>FORTRESS_UNIFIED — {date_label}</b>\nNo candidates cleared gates.")
        return []

    winners = select_winners(all_results)
    push_results_to_sheets(winners, date_label)
    send_alerts(winners, macro, date_label)

    log.info(f"✅ Sniper daily complete | {len(winners)} winners | "
             f"{[w['symbol'] for w in winners]}")
    return winners


if __name__ == "__main__":
    run()
