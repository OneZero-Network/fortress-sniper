#!/usr/bin/env python3
"""
FORTRESS_CRYPTO — workflows/sniper_daily_crypto.py
══════════════════════════════════════════════════════════════════════════════
Crypto analogue of workflows/sniper_daily.py. Runs on IGNITION_CADENCE
(daily, per core/crypto/config.py — deliberately NOT hourly: free-tier
rate limits make sub-daily scanning unreliable, and this system is built
around 'ignition off a real base', not chasing intraday wicks).

PASS A: watchlist priority scan — every ACTIVE/IGNITED crypto pearl gets
        a full ignition check regardless of today's volume rank, same
        "a pearl doesn't need to be liquid-ranked to deserve attention"
        philosophy as equity.
PASS B: broad cold scan — Top-N universe, technical-only (no Incubator
        thesis), for candidates showing a strong ignition-style setup
        with no prior pearl pedigree.
Both passes feed bridge_crypto.apply_pedigree_bonus() and
bridge_crypto.unified_conviction() before alerting.

RISK NOTE carried over honestly from the build conversation: Kelly sizing
and ATR stops here use core/crypto/config.py's crypto-specific (more
conservative) constants, NOT the equity core/config.py ones — see that
module's docstring for why equity-calibrated sizing would be dangerously
oversized for crypto's tail risk.
"""
from __future__ import annotations
import logging
import os
import sys
from datetime import datetime
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.db import init_crypto_tables
from core.telegram import send as send_telegram
from core.sheets_client import push_sheet
from core.indicators import compute_indicators
from core.crypto import config as ccfg
from core.crypto import data as cdata
from core.crypto import bridge_crypto

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                     datefmt="%H:%M:%S")
log = logging.getLogger("fortress.crypto.sniper")

COLD_SCAN_TOP_N = int(os.getenv("CRYPTO_COLD_SCAN_TOP_N", "60"))  # smaller than incubator's 200 — daily cost budget
THIN_MARGIN_WARN_PCT = float(os.getenv("CRYPTO_THIN_MARGIN_WARN_PCT", "3.0"))


def _macro_subscore() -> float:
    """Crude crypto macro proxy: BTC dominance/trend stand-in. Kept
    intentionally simple (neutral 50.0) for v1 rather than porting
    core/macro.py's VIX-based regime logic wholesale — NSE's VIX-driven
    regime model has no clean crypto equivalent yet (BTC's own realized
    vol could serve this role but needs its own calibration, flagged as
    a future addition rather than guessed at here)."""
    return 50.0


def score_symbol(symbol: str, coin_id: str, is_pearl: bool, pearl_row: dict = None) -> dict:
    hist = cdata.fetch_daily_ohlc(coin_id, days=90)
    if hist.empty or len(hist) < 25:
        return {"symbol": symbol, "skip": True, "reason": "insufficient OHLC history"}

    ind = compute_indicators(hist)
    close = float(hist["close"].iloc[-1])

    ignition = bridge_crypto.check_ignition(pearl_row or {"symbol": symbol}, hist)

    # trigger_score: simple technical composite 0-100 from RSI/ADX/vol-ratio
    # (equity's fortress_score/apex_composite are far more elaborate;
    # legacy 14-node Bayesian engine and whale/order-flow scoring are NOT
    # ported here yet — see README_CRYPTO.md "what's stubbed").
    rsi = ind.get("rsi14", 50.0)
    adx = ind.get("adx14", 0.0)
    trigger_raw = min(100.0, max(0.0,
        (min(rsi, 70) / 70 * 40) +
        (min(adx, 40) / 40 * 30) +
        (min(ignition["vol_ratio"], 3.0) / 3.0 * 30)
    ))

    thesis_score = pearl_row.get("incubator_score", 50.0) if (is_pearl and pearl_row) else 50.0
    macro_score = _macro_subscore()
    entry_score = 100.0  # no Pine-side context in this v1 crypto port

    fused = bridge_crypto.apply_pedigree_bonus(trigger_raw, is_pearl, ignition["ignited"])
    conviction = bridge_crypto.unified_conviction(thesis_score, fused, macro_score, entry_score)

    live_price = cdata.fetch_live_price_binance(symbol) or close
    drift_pct = round(100.0 * (live_price - close) / close, 2) if close else 0.0

    return {
        "symbol": symbol, "skip": False, "close": close, "live_price": live_price,
        "drift_pct": drift_pct, "is_pearl": is_pearl, "ignited": ignition["ignited"],
        "ignition_reason": ignition["reason"], "trigger_score": round(trigger_raw, 1),
        "conviction": conviction, "rsi14": round(rsi, 1), "adx14": round(adx, 1),
    }


def run() -> None:
    log.info(f"=== {ccfg.VERSION} — SNIPER (daily ignition scan) ===")
    init_crypto_tables()

    results: List[dict] = []

    # ── PASS A: watchlist priority scan ──────────────────────────────
    watchlist = bridge_crypto.load_active_watchlist()
    log.info(f"PASS A: {len(watchlist)} active pearl(s) on crypto watchlist")
    for pearl in watchlist:
        try:
            r = score_symbol(pearl["symbol"], pearl["coin_id"], is_pearl=True, pearl_row=pearl)
            if not r.get("skip"):
                results.append(r)
                if r["ignited"]:
                    bridge_crypto.mark_ignited(r["symbol"], r["live_price"])
        except Exception as e:
            log.warning(f"PASS A exception on {pearl.get('symbol')}: {e}")

    # ── PASS B: broad cold scan ───────────────────────────────────────
    universe = cdata.fetch_universe(top_n=COLD_SCAN_TOP_N)
    watchlist_symbols = {p["symbol"] for p in watchlist}
    log.info(f"PASS B: cold-scanning {len(universe)} coins (excluding {len(watchlist_symbols)} already on watchlist)")
    for coin in universe:
        if coin["symbol"] in watchlist_symbols:
            continue
        try:
            r = score_symbol(coin["symbol"], coin["id"], is_pearl=False)
            if not r.get("skip") and r["conviction"] >= ccfg.LANE_APEX_MIN:
                results.append(r)
        except Exception as e:
            log.warning(f"PASS B exception on {coin['symbol']}: {e}")

    results.sort(key=lambda r: r["conviction"], reverse=True)

    alerts = [r for r in results if r["conviction"] >= ccfg.LANE_FUSED_MIN]
    log.info(f"{len(alerts)} candidate(s) at/above LANE_FUSED_MIN ({ccfg.LANE_FUSED_MIN})")

    if alerts:
        lines = [f"🎯 <b>FORTRESS_CRYPTO — Daily Ignition Scan</b> ({datetime.today().strftime('%Y-%m-%d')})", ""]
        for r in alerts[:15]:
            tag = "🦪🔥PEARL+IGNITED" if (r["is_pearl"] and r["ignited"]) else ("🦪PEARL" if r["is_pearl"] else "COLD-SCAN")
            thin = ""
            lines.append(f"• {r['symbol']} [{tag}] conviction={r['conviction']} "
                         f"price=${r['live_price']:.4f} drift={r['drift_pct']}% {thin}")
        send_telegram("\n".join(lines))

    try:
        header = ["symbol", "is_pearl", "ignited", "conviction", "trigger_score",
                  "close", "live_price", "drift_pct", "rsi14", "adx14", "ignition_reason"]
        rows = [[r["symbol"], r["is_pearl"], r["ignited"], r["conviction"], r["trigger_score"],
                 r["close"], r["live_price"], r["drift_pct"], r["rsi14"], r["adx14"], r["ignition_reason"]]
                for r in results]
        push_sheet("CRYPTO_SCREENER", [header] + rows)
    except Exception as e:
        log.warning(f"Sheet push CRYPTO_SCREENER failed: {e}")


if __name__ == "__main__":
    run()
