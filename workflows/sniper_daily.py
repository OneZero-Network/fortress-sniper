#!/usr/bin/env python3
"""
FORTRESS_UNIFIED — workflows/sniper_daily.py  (v1.1 — full port)
══════════════════════════════════════════════════════════════════════════════
Daily pipeline, now fully wired (no stubs):

  0. evaluate_open_outcomes()   — resolve matured picks FIRST, so today's
                                  Kelly + meta-labeler learn from them.
  1. Macro regime               — NSE → yfinance → cache → CHOP fallback.
  2. Kelly multiplier           — from real closed outcomes (≥20 required).
  3. PASS A: pearl watchlist    — full intel always (small N): history,
                                  order flow, target intel, ignition,
                                  pedigree bonus.
  4. PASS B phase 1 (cheap)     — 400-candidate math gates: fortress,
                                  apex, REAL Bayes, fused, FIXED confidence.
                                  No NSE intel here (heist-after-gate,
                                  reversing the v8.2 regression).
  5. PASS B phase 2 (survivors) — target intel + alt-data tender match +
                                  Shariah full audit (grounded in yfinance
                                  company profiles) + pledge gate.
  6. RS percentile              — 63-day return rank across the preloaded
                                  universe; conviction rerank lanes.
  7. Meta-labeler veto          — only with ≥30 resolved training rows.
  8. Winners                    — record_pick + record_meta_label (closes
                                  the loop the Monday review audits),
                                  Kelly-sized shares, Sheets, Telegram
                                  (with the Kelly multiplier actually
                                  printed — fixing the legacy '?' bug).
"""
from __future__ import annotations
import logging
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import config, preflight_secrets
from core.db import init_db
from core.nse_data import load_bhavcopy, fetch_history, get_last_trading_day
from core.macro import fetch_macro_regime, macro_subscore_0_100
from core.scoring import (fortress_score, apex_composite, fused_score,
                           compute_confidence_score)
from core.bayes import bayes_win_probability
from core.order_flow import compute_eod_order_flow
from core.target_intel import fetch_target_intel, fetch_fii_dii, pledge_gate_ok
from core.alt_data import match_company_to_tenders
from core.fundamentals import get_company_profile
from core.shariah import ticker_veto, full_audit
from core.meta_labeler import meta_labeler_veto, compute_kelly_multiplier, record_meta_label
from core.outcomes import evaluate_open_outcomes, record_pick
from core.bridge import (load_active_watchlist, check_ignition, mark_ignited,
                          apply_pedigree_bonus, unified_conviction)
from core.telegram import send as send_telegram
from core.sheets_client import push_sheet, read_sheet

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                     datefmt="%H:%M:%S")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.ERROR)
log = logging.getLogger("fortress.sniper")


# ══════════════════════════════════════════════════════════════════════════
# PHASE-1 SCORING (cheap math gates — no per-symbol NSE intel)
# ══════════════════════════════════════════════════════════════════════════

def score_phase1(sym: str, close: float, hist: Optional[pd.DataFrame],
                  macro: Dict, fii_score: int, is_pearl: bool = False,
                  pearl_row: Dict = None, deep_intel: bool = False) -> Dict:
    if hist is None or hist.empty or len(hist) < 20 or close <= 0:
        return {}
    vetoed, _ = ticker_veto(sym)
    if vetoed:
        return {}

    # Order flow: NSE delivery attempted only for pearls (small N) or when
    # the circuit is closed anyway; cold scan phase-1 uses the free
    # volume-proxy tier so 400 candidates never hammer NSE.
    order_flow = compute_eod_order_flow(sym, hist, close, try_nse=deep_intel)

    sector = (pearl_row or {}).get("sector", "") or ""
    fort = fortress_score(sym, close, hist, sector, macro, order_flow,
                           fii_score=fii_score)
    if not fort or fort.get("fort_pts", 0) < 45:
        return {}

    apex_d = apex_composite(fort, macro)
    bayes_pct = bayes_win_probability(fort, macro, order_flow)
    fused = fused_score(fort, apex_d, bayes_pct)

    ignition = {"ignited": False, "reason": ""}
    if is_pearl and pearl_row is not None:
        ignition = check_ignition(pearl_row, hist)
        if ignition["ignited"] and pearl_row.get("status") != "IGNITED":
            mark_ignited(sym, close)

    fused_adj = apply_pedigree_bonus(fused, is_pearl=is_pearl,
                                      ignited=ignition["ignited"])
    if fused_adj < config.APEX_MIN_SCORE:
        return {}

    conf = compute_confidence_score(fort["fort_pts"], apex_d["apex_comp"],
                                     bayes_pct, fort["whale_score"],
                                     fort["rsi14"], fort["adx14"],
                                     whale_available=fort["whale_available"])
    if conf < config.CONFIDENCE_MIN:
        return {}

    thesis = (pearl_row or {}).get("incubator_score", 50.0) if is_pearl else 50.0
    conviction = unified_conviction(min(100.0, float(thesis)), fused_adj,
                                     macro_subscore_0_100(macro), 100.0)
    return {**fort, "apex_comp": apex_d["apex_comp"], "fused": fused_adj,
            "bayes_pct": bayes_pct, "confidence_score": conf,
            "conviction_score": conviction, "is_pearl": is_pearl,
            "ignited": ignition["ignited"],
            "ignition_reason": ignition.get("reason", ""),
            "vix_val": macro.get("vix_val", 0)}


# ══════════════════════════════════════════════════════════════════════════
# PHASE-2 ENRICHMENT (survivors only — intel, catalysts, Shariah, pledge)
# ══════════════════════════════════════════════════════════════════════════

def enrich_phase2(r: Dict) -> Optional[Dict]:
    sym = r["symbol"]
    profile = get_company_profile(sym)

    audit = full_audit(sym, company_name=profile["name"],
                        industry=profile["industry"] or profile["sector"],
                        biz_profile=profile["summary"])
    if not audit["compliant"]:
        log.info(f"  GATE SHARIAH  | {sym:14s} | {audit['reason'][:70]}")
        return None
    r["halal_tier"] = audit["layer"]
    if profile["sector"] and not r.get("sector"):
        r["sector"] = profile["sector"]

    intel = fetch_target_intel(sym)
    if not pledge_gate_ok(intel["pledge_pct"]):
        log.info(f"  GATE PLEDGE   | {sym:14s} | pledge={intel['pledge_pct']:.0f}%")
        return None

    tender = match_company_to_tenders(sym, profile["name"])
    r["catalyst"] = bool(intel["catalyst"] or tender["tender_match"]
                          or intel["insider_total_cr"] >= 1.0)
    r["catalyst_note"] = (intel["catalyst_headline"] or tender["tender_title"]
                           or (f"Insider ₹{intel['insider_total_cr']}Cr"
                               if intel["insider_total_cr"] >= 1.0 else ""))[:120]
    r["insider_cr"] = intel["insider_total_cr"]
    r["pledge_pct"] = intel["pledge_pct"]

    if r["catalyst"]:
        r["conviction_score"] = round(min(100.0, r["conviction_score"] + 4.0), 1)
    return r


def add_rs_percentile(survivors: List[Dict], hist_cache: Dict) -> None:
    """63-day return percentile of each survivor vs the whole preloaded
    universe (not just survivors — the broad base is the point of RS)."""
    universe_rets = []
    for sym, h in hist_cache.items():
        if h is not None and len(h) > config.RS_LOOKBACK_DAYS:
            c = h["close"].astype(float)
            c0, c1 = float(c.iloc[-config.RS_LOOKBACK_DAYS]), float(c.iloc[-1])
            if c0 > 0:
                universe_rets.append((sym, (c1 - c0) / c0))
    if not universe_rets:
        for r in survivors:
            r["rs_pct"] = 50.0
        return
    rets_only = sorted(v for _, v in universe_rets)
    ret_map = dict(universe_rets)
    n = len(rets_only)
    for r in survivors:
        ret = ret_map.get(r["symbol"])
        if ret is None:
            r["rs_pct"] = 50.0
            continue
        below = sum(1 for v in rets_only if v < ret)
        r["rs_pct"] = round(below / n * 100, 1)


def conviction_rerank(survivors: List[Dict]) -> List[Dict]:
    """Legacy lane logic, lean: top lane requires RS ≥ floor AND
    (catalyst OR RS ≥ catalyst-exempt floor). Ineligible aren't dropped —
    they rank behind all eligibles."""
    if not config.CONVICTION_RERANK:
        return sorted(survivors, key=lambda r: r["conviction_score"], reverse=True)
    eligible, demoted = [], []
    for r in survivors:
        rs = r.get("rs_pct", 50.0)
        ok = rs >= config.CONV_RS_MIN_PCT and \
             (r.get("catalyst") or rs >= config.CONV_RS_CATALYST_FLOOR
              or not config.CONV_REQUIRE_CATALYST or r.get("ignited"))
        (eligible if ok else demoted).append(r)
    key = lambda r: r["conviction_score"]
    return sorted(eligible, key=key, reverse=True) + sorted(demoted, key=key, reverse=True)


# ══════════════════════════════════════════════════════════════════════════
# PASSES
# ══════════════════════════════════════════════════════════════════════════

def run_pearl_pass(macro: Dict, fii_score: int, hist_cache: Dict) -> List[Dict]:
    watchlist = load_active_watchlist()
    log.info(f"Pearl pass: {len(watchlist)} active/ignited pearls")
    results = []
    for pearl in watchlist:
        sym = pearl["symbol"]
        try:
            hist = fetch_history(sym, days=300)
            if hist.empty:
                continue
            hist_cache[sym] = hist
            close = float(hist["close"].iloc[-1])
            r = score_phase1(sym, close, hist, macro, fii_score,
                              is_pearl=True, pearl_row=pearl, deep_intel=True)
            if r:
                r["source"] = "PEARL_WATCHLIST"
                results.append(r)
                tag = "🔥 IGNITED" if r["ignited"] else "👁 watching"
                log.info(f"  {tag} {sym:12s} conv={r['conviction_score']} fused={r['fused']}")
        except Exception as e:
            log.debug(f"pearl {sym}: {e}")
    return results


def run_cold_scan(macro: Dict, fii_score: int, hist_cache: Dict) -> List[Dict]:
    bhav, bhav_src = load_bhavcopy()
    if bhav.empty:
        log.error("Cold scan: bhavcopy empty on all tiers")
        return []
    cands = bhav[(bhav["close"] >= config.MIN_PRICE) & (bhav["close"] <= config.MAX_PRICE) &
                 (bhav["turnover_lakhs"] >= config.MIN_TURNOVER_LAKHS)].head(config.MAX_CANDIDATES)
    log.info(f"Cold scan: {len(cands)}/{len(bhav)} candidates (src={bhav_src})")

    lock = threading.Lock()

    def _preload(sym):
        try:
            h = fetch_history(sym, days=300)
            if not h.empty:
                with lock:
                    hist_cache[sym] = h
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=12) as ex:
        list(ex.map(_preload, cands["symbol"].tolist()))
    log.info(f"Cold scan: history for {len(hist_cache)} symbols")

    results = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(score_phase1, row["symbol"], float(row["close"]),
                          hist_cache.get(row["symbol"]), macro, fii_score): row["symbol"]
                for _, row in cands.iterrows()}
        for fut in as_completed(futs):
            try:
                r = fut.result(timeout=45)
                if r:
                    r["source"] = "COLD_SCAN"
                    results.append(r)
            except Exception as e:
                log.debug(f"{futs[fut]}: {e}")
    log.info(f"Cold scan phase 1: {len(results)} passed math gates")
    return results


# ══════════════════════════════════════════════════════════════════════════
# OUTPUT
# ══════════════════════════════════════════════════════════════════════════

def push_results_to_sheets(winners: List[Dict], date_label: str) -> None:
    header = ["Date", "Symbol", "Source", "Conviction", "Fused", "FortPts", "ApexComp",
              "BayesPct", "Confidence", "RS%", "Catalyst", "IsPearl", "Ignited",
              "Grade", "Close", "StopLoss", "R1", "R2", "R3", "Shares",
              "Delivery%", "HalalTier", "Story"]
    rows = [header]
    for w in winners:
        rows.append([date_label, w["symbol"], w["source"], w["conviction_score"],
                     w["fused"], w["fort_pts"], w["apex_comp"], w["bayes_pct"],
                     w["confidence_score"], w.get("rs_pct", ""),
                     "YES" if w.get("catalyst") else "",
                     "YES" if w["is_pearl"] else "", "YES" if w["ignited"] else "",
                     w["grade"], w["close"], w["stop_loss"], w["r1"], w["r2"], w["r3"],
                     w["kelly_shares"], w.get("delivery_pct", -1),
                     w.get("halal_tier", ""), w["story"][:150]])
    existing = read_sheet("SCREENER")
    if existing and len(existing) > 1:
        body = [r for r in existing[1:] if not (r and r[0] == date_label)]
        rows = [header] + body + rows[1:]
    push_sheet("SCREENER", rows)


def send_alerts(winners: List[Dict], macro: Dict, date_label: str,
                 kelly_mult: float, kelly_stats: Dict, closed: List[Dict]) -> None:
    lines = [f"🎯 <b>FORTRESS_UNIFIED — {date_label}</b>",
             f"Regime: {macro['macro_state']} ({macro.get('source','')}) | "
             f"VIX {macro.get('vix_val', 0):.1f} | "
             f"Kelly ×{kelly_mult:.2f}"
             + (f" (n={kelly_stats.get('n')}, WR {kelly_stats.get('win_rate')}%)"
                if kelly_stats.get("win_rate") is not None else " (default)")]
    if closed:
        wins = sum(1 for c in closed if c["pnl_pct"] > 0)
        lines.append(f"📊 Closed today: {len(closed)} ({wins}W/{len(closed)-wins}L, "
                     f"avg {sum(c['pnl_pct'] for c in closed)/len(closed):+.1f}%)")
    lines.append("")
    if not winners:
        lines.append("No picks cleared all gates today.")
    for w in winners:
        badge = "🔥 IGNITED PEARL" if w["ignited"] else ("💎 pearl" if w["is_pearl"] else "")
        cat = " ⚡" if w.get("catalyst") else ""
        lines.append(f"<b>{w['symbol']}</b> {badge}{cat} — Conviction {w['conviction_score']}/100")
        lines.append(f"   {w['grade']} | Entry ₹{w['close']:.0f} | SL ₹{w['stop_loss']:.0f} | "
                     f"R1 ₹{w['r1']:.0f} | Size {w['kelly_shares']}sh | RS {w.get('rs_pct','—')}%")
        if w.get("catalyst_note"):
            lines.append(f"   ⚡ {w['catalyst_note'][:90]}")
        if w["ignited"]:
            lines.append(f"   🔥 {w['ignition_reason'][:90]}")
        lines.append("")
    send_telegram("\n".join(lines))


# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════

def run() -> List[Dict]:
    log.info("=" * 70)
    log.info(f"  {config.VERSION} — SNIPER DAILY (v1.1 full)")
    log.info("=" * 70)
    init_db()
    preflight_secrets()
    _, date_label = get_last_trading_day()

    closed = evaluate_open_outcomes()
    if closed:
        log.info(f"Outcomes: closed {len(closed)} matured picks")

    macro = fetch_macro_regime()
    if macro["macro_state"] == "MASSACRE":
        send_telegram(f"⚠️ <b>FORTRESS_UNIFIED — {date_label}</b>\n"
                       f"MASSACRE regime (VIX {macro['vix_val']:.1f}) — standing down.")
        return []

    kelly_mult, kelly_stats = compute_kelly_multiplier()
    log.info(f"Kelly multiplier: ×{kelly_mult:.2f} {kelly_stats}")
    fii = fetch_fii_dii()
    log.info(f"FII/DII: score={fii['fii_score']} net=₹{fii['fii_net_cr']:.0f}Cr ({fii['source']})")

    hist_cache: Dict[str, pd.DataFrame] = {}
    pearl_results = run_pearl_pass(macro, fii["fii_score"], hist_cache)
    cold_results = run_cold_scan(macro, fii["fii_score"], hist_cache)
    survivors = pearl_results + cold_results
    if not survivors:
        send_telegram(f"📋 <b>FORTRESS_UNIFIED — {date_label}</b>\n"
                       f"Regime {macro['macro_state']} | no candidates cleared math gates.")
        return []

    add_rs_percentile(survivors, hist_cache)

    # Phase 2 enrichment (heist-after-gate): intel + Shariah + pledge + tenders
    enriched = []
    for r in sorted(survivors, key=lambda x: x["conviction_score"], reverse=True)[:30]:
        try:
            er = enrich_phase2(r)
            if er:
                enriched.append(er)
        except Exception as e:
            log.debug(f"enrich {r['symbol']}: {e}")
    log.info(f"Phase 2: {len(enriched)} survived intel/Shariah/pledge gates")

    ranked = conviction_rerank(enriched)

    winners, vetoed = [], []
    for r in ranked:
        veto, p_win, n = meta_labeler_veto(r)
        r["meta_pwin"] = p_win
        if veto:
            vetoed.append((r["symbol"], p_win))
            continue
        winners.append(r)
        if len(winners) >= config.APEX_TOP_N and not any(
                x["ignited"] and x not in winners for x in ranked[len(winners):]):
            break
    # Always include ignited pearls even beyond top-N
    seen = {w["symbol"] for w in winners}
    for r in ranked:
        if r["ignited"] and r["symbol"] not in seen:
            winners.append(r)
            seen.add(r["symbol"])
    winners = winners[:config.APEX_TOP_N + 2]
    if vetoed:
        log.info(f"Meta-labeler vetoed: {vetoed}")

    for w in winners:
        w["kelly_shares"] = config.kelly_adjusted_size(w["shares"], kelly_mult)
        w["pearl_pedigree"] = int(w["is_pearl"])
        w["ignition_detected"] = int(w["ignited"])
        record_pick(w, date_label, w["source"])
        record_meta_label(w["symbol"], date_label, w)

    push_results_to_sheets(winners, date_label)
    send_alerts(winners, macro, date_label, kelly_mult, kelly_stats, closed)
    log.info(f"✅ Sniper complete | winners: {[w['symbol'] for w in winners]}")
    return winners


if __name__ == "__main__":
    run()
