#!/usr/bin/env python3
"""
FORTRESS_CRYPTO — scripts/experiment_w1_n1_observe.py
══════════════════════════════════════════════════════════════════════════════
W1 (whale) and N1 (news) — Phase C independent-layer experiments.

THE HONEST DATA WALL: unlike F1 (False-Pearl), there is NO historical
data to backtest whale accumulation or news sentiment against —
CryptoPanic doesn't serve historical posts on the free tier, and whale
snapshots only exist forward from when this system started storing them
(core/crypto/onchain.py's save_whale_snapshot). There is no way around
this except building the dataset going forward, one day at a time.

WHAT THIS SCRIPT DOES, every run (intended: DAILY, scheduled):
  1. RESOLVE — checks observations logged 7/14/21 days ago, fetches
     current price, computes the actual forward return, marks resolved.
  2. OBSERVE — for a BROAD universe (NOT gated by technical trigger —
     this is the critical difference from the sniper: W1/N1 need signal
     state recorded independent of any other layer, or the eventual
     correlation would be confounded by "coins the technical layer
     already liked").
  3. REPORT — once enough resolved observations exist, groups by
     whale_label / news_label and reports average forward return per
     group. EARLY RUNS WILL CORRECTLY REPORT 'insufficient data' — that
     is expected and honest, not a bug. This dataset takes real time to
     build; there is no way to accelerate it without fabricating history
     that doesn't exist.
"""
from __future__ import annotations
import logging
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.db import (init_crypto_tables, save_layer_observation, get_unresolved_observations,
                      resolve_layer_observation, get_resolved_observations)
from core.telegram import send as send_telegram
from core.crypto import config as ccfg
from core.crypto import data as cdata
from core.crypto import onchain
from core.crypto import news_sentiment

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                     datefmt="%H:%M:%S")
log = logging.getLogger("fortress.crypto.w1n1")

OBSERVE_UNIVERSE_N = int(os.getenv("CRYPTO_W1N1_UNIVERSE_N", "50"))
MIN_SAMPLE_FOR_REPORT = 20


def resolve_matured_observations() -> dict:
    counts = {"7d": 0, "14d": 0, "21d": 0}
    for horizon in ("7d", "14d", "21d"):
        pending = get_unresolved_observations(horizon)
        for obs in pending:
            live = cdata.fetch_live_price_binance(obs["symbol"])
            if live is None or not obs["price_at_observation"]:
                continue
            fwd_return = round(100.0 * (live - obs["price_at_observation"]) / obs["price_at_observation"], 2)
            resolve_layer_observation(obs["id"], horizon, fwd_return)
            counts[horizon] += 1
    return counts


def log_todays_observations(universe: list) -> int:
    logged = 0
    for coin in universe:
        symbol = coin["symbol"]
        price = coin.get("price")
        if not price:
            continue

        whale_label, whale_delta = None, None
        try:
            platforms = cdata.fetch_platforms(coin["id"])
            if onchain.is_onchain_supported(platforms):
                signal = onchain.whale_concentration_signal(platforms)
                accum = onchain.whale_accumulation_delta(symbol, signal)
                if accum.get("available"):
                    whale_label = accum["label"]
                    whale_delta = accum["top10_delta_pct"]
        except Exception as e:
            log.debug(f"whale check failed for {symbol}: {e}")

        news_label, news_score = None, None
        try:
            news = news_sentiment.sentiment_summary(symbol)
            if news.get("available"):
                news_label = news["label"]
                news_score = news.get("score")
        except Exception as e:
            log.debug(f"news check failed for {symbol}: {e}")

        save_layer_observation(symbol, coin["id"], price, whale_label, whale_delta, news_label, news_score)
        logged += 1
    return logged


def _group_report(rows: list, label_key: str, title: str) -> str:
    by_label = {}
    for r in rows:
        label = r.get(label_key)
        if label is None:
            continue
        by_label.setdefault(label, []).append(r["forward_return_pct"])

    if not by_label:
        return f"<b>{title}</b>: no resolved observations yet with a recorded {label_key}"

    lines = [f"<b>{title}</b>"]
    for label, returns in sorted(by_label.items()):
        n = len(returns)
        avg = round(float(np.mean(returns)), 2)
        warn = " ⚠️ insufficient sample" if n < MIN_SAMPLE_FOR_REPORT else ""
        lines.append(f"   {label}: n={n}, avg forward return {avg:+.2f}%{warn}")
    return "\n".join(lines)


def run() -> None:
    log.info("=== W1/N1 Observation Logger — building the dataset, not yet a conclusion ===")
    init_crypto_tables()

    resolved_counts = resolve_matured_observations()
    log.info(f"Resolved this run: {resolved_counts}")

    universe = cdata.fetch_universe(top_n=OBSERVE_UNIVERSE_N)
    if not universe:
        log.error("Universe fetch failed — skipping today's observation logging")
    else:
        logged = log_todays_observations(universe)
        log.info(f"Logged {logged} new observation(s) for today")

    resolved_7d = get_resolved_observations("7d")
    resolved_14d = get_resolved_observations("14d")
    resolved_21d = get_resolved_observations("21d")
    total_resolved = len(resolved_7d) + len(resolved_14d) + len(resolved_21d)

    log.info(f"Total resolved observations available: 7d={len(resolved_7d)}, "
             f"14d={len(resolved_14d)}, 21d={len(resolved_21d)}")

    if total_resolved < MIN_SAMPLE_FOR_REPORT:
        message = (
            f"🔬 <b>W1/N1 Observation Logger</b>\n"
            f"Still building the dataset — {total_resolved} resolved observation(s) so far "
            f"(need {MIN_SAMPLE_FOR_REPORT}+ per horizon for a meaningful report). "
            f"No historical whale/news data exists to backtest, so this accumulates in real time, "
            f"one day at a time. Check back in a few weeks."
        )
    else:
        message = (
            f"🔬 <b>W1/N1 Observation Report</b> — "
            f"NOT a backtest, this is real forward data accumulated day by day\n\n"
            f"═══ 7-day horizon ═══\n"
            f"{_group_report(resolved_7d, 'whale_label', 'W1 — by whale accumulation label')}\n\n"
            f"{_group_report(resolved_7d, 'news_label', 'N1 — by news sentiment label')}\n\n"
            f"═══ 14-day horizon ═══\n"
            f"{_group_report(resolved_14d, 'whale_label', 'W1 — by whale accumulation label')}\n\n"
            f"{_group_report(resolved_14d, 'news_label', 'N1 — by news sentiment label')}\n\n"
            f"═══ 21-day horizon ═══\n"
            f"{_group_report(resolved_21d, 'whale_label', 'W1 — by whale accumulation label')}\n\n"
            f"{_group_report(resolved_21d, 'news_label', 'N1 — by news sentiment label')}"
        )

    plain = message.replace("<b>", "").replace("</b>", "")
    log.info(plain)
    send_telegram(message)


if __name__ == "__main__":
    run()
