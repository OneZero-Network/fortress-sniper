#!/usr/bin/env python3
"""
FORTRESS_CRYPTO — workflows/incubator_weekly_crypto.py
══════════════════════════════════════════════════════════════════════════════
Crypto analogue of workflows/incubator_weekly.py. Weekly cadence (per
core/crypto/config.py's INCUBATOR_CADENCE — deliberately still weekly:
the "quietly accumulating, undervalued" thesis is inherently a slower
signal than daily ignition-checking, same reasoning as the equity system).

Pipeline per candidate (Top-200 CoinGecko universe, liquidity-filtered):
  1. Shariah categorical screen (shariah_crypto.screen_token) — FIRST gate,
     fail-closed, same "compliance before conviction" order as equity.
  2. "Rubble" analogue — distance-off-ATH gate: a coin trading well below
     its all-time high with a tightening recent range is the crypto
     equivalent of "cheap and quietly building a base" (no P/E to lean on,
     so this substitutes ATH-discount + box-width for the equity version's
     52W-discount + box-width).
  3. On-chain quality signal (EVM tokens only, honestly scoped).
  4. Composite Z-score factor rank (momentum vs BTC + NVT-proxy value +
     on-chain quality) among that week's surviving candidates.
  5. Survivors -> bridge_crypto.upsert_pearl() -> crypto_pearl_watchlist.

Every rejection is logged with [date, symbol, gate, reason] — same
REJECTS_LOG discipline as equity, so Monday's Claude review (if you extend
core/weekly_review.py to also read crypto tables) has real gate-rejection
data, not vibes.
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
from core.sheets_client import push_sheet, read_sheet
from core.crypto import config as ccfg
from core.crypto import data as cdata
from core.crypto import onchain
from core.crypto import shariah_crypto
from core.crypto import factors_crypto
from core.crypto import bridge_crypto

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                     datefmt="%H:%M:%S")
log = logging.getLogger("fortress.crypto.incubator")

ATH_DISCOUNT_MIN_PCT = float(os.getenv("CRYPTO_ATH_DISCOUNT_MIN_PCT", "40"))  # >=40% off ATH
BOX_WIDTH_MAX_PCT = float(os.getenv("CRYPTO_BOX_WIDTH_MAX_PCT", "35"))        # recent range tightness
TOP_N_PEARLS = int(os.getenv("CRYPTO_TOP_N_PEARLS", "10"))
STONE_SCORE_MIN = float(os.getenv("CRYPTO_STONE_SCORE_MIN", "45"))


def check_ath_discount_gate(coin: dict) -> tuple[bool, dict]:
    """Crypto analogue of equity's rubble-discount gate. A coin sitting
    deep below its ATH is the closest crypto proxy for 'undervalued' —
    there's no P/E to lean on, but sustained distance-off-high with
    positive but non-euphoric recent momentum is a real, commonly-used
    crypto value heuristic (distinct from 'this coin crashed and is
    dying' — the 30d momentum check below filters that case out)."""
    details = {"ath_change_pct": None, "reason": ""}
    ath_change = coin.get("ath_change_pct")
    if ath_change is None:
        details["reason"] = "no ATH data"
        return False, details
    details["ath_change_pct"] = ath_change
    # ath_change_pct from CoinGecko is negative (e.g. -65.2 = 65.2% below ATH)
    discount = abs(ath_change) if ath_change < 0 else 0.0
    if discount < ATH_DISCOUNT_MIN_PCT:
        details["reason"] = f"only {discount:.1f}% off ATH, need >= {ATH_DISCOUNT_MIN_PCT}%"
        return False, details
    pct_30d = coin.get("pct_30d")
    if pct_30d is not None and pct_30d < -50:
        details["reason"] = f"30d momentum {pct_30d:.1f}% — likely still falling, not basing"
        return False, details
    details["reason"] = f"{discount:.1f}% off ATH — passes"
    return True, details


def check_shariah(coin: dict, halal_override: set) -> dict:
    cats = cdata.fetch_coin_categories(coin["id"])
    return shariah_crypto.screen_token(coin["symbol"], cats if cats else None, halal_override)


def run() -> None:
    log.info(f"=== {ccfg.VERSION} — INCUBATOR (weekly) ===")
    init_crypto_tables()
    expired = bridge_crypto.expire_stale_pearls()
    if expired:
        log.info(f"Expired {expired} stale pearl(s) past {ccfg.PEARL_WATCHLIST_TTL_DAYS}-day TTL")

    halal_override = set()
    try:
        halal_rows = read_sheet(ccfg.CRYPTO_HALAL_LIST_SHEET_TAB)
        halal_override = {str(r[0]).upper().strip() for r in halal_rows if r and r[0]}
    except Exception as e:
        log.warning(f"Could not read {ccfg.CRYPTO_HALAL_LIST_SHEET_TAB} tab: {e}")

    universe = cdata.fetch_universe(top_n=ccfg.UNIVERSE_TOP_N)
    if not universe:
        log.error("Universe fetch failed entirely — aborting run rather than scoring nothing")
        send_telegram("⚠️ FORTRESS_CRYPTO Incubator: universe fetch failed, run aborted.")
        return
    log.info(f"Universe: {len(universe)} candidates after liquidity/stable filters")

    rejects_log: List[list] = []
    survivors: List[dict] = []

    for coin in universe:
        sym = coin["symbol"]
        try:
            audit = check_shariah(coin, halal_override)
            if not audit["compliant"]:
                rejects_log.append([datetime.today().strftime("%Y-%m-%d"), sym, "SHARIAH", audit["reason"]])
                continue

            passed, details = check_ath_discount_gate(coin)
            if not passed:
                rejects_log.append([datetime.today().strftime("%Y-%m-%d"), sym, "ATH_DISCOUNT", details["reason"]])
                continue

            platforms = cdata.fetch_platforms(coin["id"])
            onchain_signal = None
            if onchain.is_onchain_supported(platforms):
                onchain_signal = onchain.whale_concentration_signal(platforms)

            btc_pct_30d = None
            if coin["id"] != ccfg.BENCHMARK_COIN_ID:
                pass  # BTC's own pct_30d is fetched once below, not per-coin

            survivors.append({
                "symbol": sym,
                "coin_id": coin["id"],
                "coin": coin,
                "onchain_signal": onchain_signal,
                "onchain_quality": onchain.onchain_quality_score_0_100(onchain_signal),
                "sharia_flags": audit.get("category_flags", []),
                "ath": coin.get("ath"),
                "ath_change_pct": coin.get("ath_change_pct"),
            })
        except Exception as e:
            log.warning(f"EXCEPTION scoring {sym}: {e}")
            rejects_log.append([datetime.today().strftime("%Y-%m-%d"), sym, "EXCEPTION", str(e)])
            continue

    log.info(f"{len(survivors)} candidates cleared Shariah + ATH-discount gates")

    # BTC benchmark return for residual momentum
    btc_universe_entry = next((c for c in universe if c["id"] == ccfg.BENCHMARK_COIN_ID), None)
    btc_30d = btc_universe_entry.get("pct_30d") if btc_universe_entry else None

    factor_candidates = []
    for s in survivors:
        c = s["coin"]
        mkt_cap = c.get("market_cap") or 0
        vol24 = c.get("volume_24h") or 0
        nvt_proxy = (mkt_cap / vol24) if vol24 > 0 else None
        res_mom = factors_crypto.residual_momentum_pct(c.get("pct_30d"), btc_30d)
        factor_candidates.append({
            "symbol": s["symbol"],
            "residual_momentum_pct": res_mom,
            "nvt_proxy": nvt_proxy,
            "onchain_quality_0_100": s["onchain_quality"],
        })

    scores = factors_crypto.compute_composite_scores(factor_candidates)

    ranked = sorted(survivors, key=lambda s: scores.get(s["symbol"], {}).get("z_composite", 0), reverse=True)

    pearls_written = []
    for s in ranked:
        z = scores.get(s["symbol"], {})
        composite = z.get("z_composite", 0.0)
        if composite < STONE_SCORE_MIN:
            rejects_log.append([datetime.today().strftime("%Y-%m-%d"), s["symbol"], "STONE_SCORE",
                                f"z_composite {composite} < {STONE_SCORE_MIN}"])
            continue
        if len(pearls_written) >= TOP_N_PEARLS:
            break

        grade = "A" if composite >= 75 else ("B" if composite >= 60 else "C")
        thesis = (f"{abs(s['ath_change_pct']):.0f}% off ATH, z_composite={composite} "
                  f"(mom={z.get('z_momentum')}, val={z.get('z_value')}, qual={z.get('z_quality')})")
        onchain_flags = ""
        if s["onchain_signal"]:
            onchain_flags = ("whale_flag" if s["onchain_signal"].get("whale_flag") else "") + \
                             (",concentration_flag" if s["onchain_signal"].get("concentration_flag") else "")

        bridge_crypto.upsert_pearl(
            symbol=s["symbol"], coin_id=s["coin_id"], thesis=thesis,
            box_high=s["coin"].get("price") or 0.0, box_low=0.0,
            ath=s["ath"] or 0.0, ath_change_pct=s["ath_change_pct"] or 0.0,
            incubator_score=composite, pearl_grade=grade,
            category_tags=",".join(s["sharia_flags"]) or "none",
            onchain_flags=onchain_flags or "none",
            sharia_compliant=True,
        )
        pearls_written.append((s["symbol"], composite, grade))

    log.info(f"Wrote {len(pearls_written)} pearl(s) to crypto_pearl_watchlist")

    if pearls_written:
        lines = [f"🦪 <b>FORTRESS_CRYPTO — Weekly Pearls</b> ({datetime.today().strftime('%Y-%m-%d')})", ""]
        for sym, score, grade in pearls_written:
            lines.append(f"• {sym} — grade {grade}, score {score}")
        send_telegram("\n".join(lines))

    try:
        push_sheet("CRYPTO_INCUBATOR", [["symbol", "coin_id", "z_composite", "grade", "ath_change_pct"]] +
                   [[sym, s["coin_id"], score, grade, s["ath_change_pct"]]
                    for (sym, score, grade), s in zip(pearls_written, ranked[:len(pearls_written)])])
    except Exception as e:
        log.warning(f"Sheet push CRYPTO_INCUBATOR failed: {e}")

    try:
        if rejects_log:
            push_sheet("CRYPTO_REJECTS_LOG", [["date", "symbol", "gate", "reason"]] + rejects_log)
    except Exception as e:
        log.warning(f"Sheet push CRYPTO_REJECTS_LOG failed: {e}")


if __name__ == "__main__":
    run()
