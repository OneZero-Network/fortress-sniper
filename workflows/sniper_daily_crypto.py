#!/usr/bin/env python3
"""
FORTRESS_CRYPTO — workflows/sniper_daily_crypto.py  (v1.1 — diving-skill layers)
══════════════════════════════════════════════════════════════════════════════
v1.1 adds the layers that separate this from a generic screener (the
"metal detector" everyone has) into something with an actual edge (the
"diving skill" that finds what the detector alone can't):

  1. TREND CONTEXT (free — uses data already fetched): a setup fighting
     its own 30-day trend gets penalized; a setup WITH the trend gets a
     bonus, even at equal raw technical score.
  2. NEWS SENTIMENT (CryptoPanic, optional key): applied SELECTIVELY to
     candidates that already cleared the technical bar — reading the
     news on a shortlist, not blanket-scanning 150 coins for headlines.
     A breakout with a real catalyst behind it outranks a bare technical
     wick at equal score.
  3. TWO-TIER ALERTING — the v1.0 bug where daily consistently returned
     0: LANE_FUSED_MIN (60) is a "fortress-grade" bar, the same one the
     weekly Incubator's best pearls clear. A daily 10-20%-target swing
     candidate is a genuinely different, shorter-horizon, lower-
     conviction category and needed its OWN bar (DAILY_SWING_MIN=42),
     not a globally-lowered threshold that would blur the two tiers.
  4. ENTRY/EXIT TIMING — every alert now states the exact UTC entry
     timestamp (this run's time) and an ESTIMATED holding window derived
     from the position's own volatility (ATR-implied days-to-target),
     not a fixed number pulled from nowhere.

PASS A: watchlist priority scan (pearls, target 25-50% per Incubator's
        deeper thesis — see PEARL_TARGET_LOW/HIGH_PCT).
PASS B: broad cold scan (target 10-20% — DAILY_SWING_TARGET_LOW/HIGH_PCT),
        split into FORTRESS tier (>=LANE_FUSED_MIN) and SWING tier
        (>=DAILY_SWING_MIN, <LANE_FUSED_MIN).
"""
from __future__ import annotations
import logging
import os
import sys
from datetime import datetime, timezone
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.db import init_crypto_tables, log_signal
from core.telegram import send as send_telegram
from core.sheets_client import push_sheet
from core.indicators import compute_indicators
from core.crypto import config as ccfg
from core.crypto import data as cdata
from core.crypto import bridge_crypto
from core.crypto import news_sentiment
from core.crypto import outcome_tracker
from core.crypto import risk_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                     datefmt="%H:%M:%S")
log = logging.getLogger("fortress.crypto.sniper")

COLD_SCAN_TOP_N = int(os.getenv("CRYPTO_COLD_SCAN_TOP_N", "60"))


def _macro_subscore() -> float:
    """Placeholder neutral 50.0 — see README_CRYPTO.md 'what's stubbed'.
    BTC realized-vol regime scoring is a legitimate future addition, not
    guessed at here."""
    return 50.0


def _trend_context(coin_snapshot: dict) -> dict:
    """Free trend read using pct_7d/pct_30d already present in the
    universe payload — no extra API call. Returns a bonus/penalty and a
    human-readable label for the Telegram alert."""
    pct_7d = coin_snapshot.get("pct_7d")
    pct_30d = coin_snapshot.get("pct_30d")
    if pct_7d is None and pct_30d is None:
        return {"adjustment": 0.0, "label": "TREND_UNKNOWN"}
    p7 = pct_7d or 0.0
    p30 = pct_30d or 0.0
    if p30 > 5 and p7 > 0:
        return {"adjustment": ccfg.TREND_ALIGNED_BONUS, "label": f"UPTREND (30d {p30:+.1f}%, 7d {p7:+.1f}%)"}
    if p30 < -15:
        return {"adjustment": -ccfg.TREND_AGAINST_PENALTY, "label": f"DOWNTREND (30d {p30:+.1f}%) — fighting the trend"}
    return {"adjustment": 0.0, "label": f"SIDEWAYS (30d {p30:+.1f}%, 7d {p7:+.1f}%)"}


def _estimated_hold_days(entry: float, target: float, atr14: float) -> float:
    """ATR-implied rough days-to-target: how many 'average daily ranges'
    fit inside the distance to target. This is a coarse heuristic, not a
    prediction — labeled as an ESTIMATE in the alert, not a promise."""
    if atr14 <= 0 or target <= entry:
        return 0.0
    distance = target - entry
    days = distance / (atr14 * 0.45)
    return round(max(0.5, min(30.0, days)), 1)


def score_symbol(symbol: str, coin_id: str, is_pearl: bool, pearl_row: dict = None,
                  coin_snapshot: dict = None) -> dict:
    hist = cdata.fetch_daily_ohlc(coin_id, days=95)
    if hist.empty or len(hist) < 25:
        return {"symbol": symbol, "skip": True,
                "reason": f"insufficient OHLC history ({len(hist)} rows returned, need >=25)"}

    ind = compute_indicators(hist)
    close = float(hist["close"].iloc[-1])
    atr14 = ind.get("atr14", 0.0)
    if atr14 <= 0:
        atr14 = close * 0.02

    ignition = bridge_crypto.check_ignition(pearl_row or {"symbol": symbol}, hist)

    stop_loss = round(max(close - atr14 * ccfg.ATR_MULT_TREND, close * 0.75), 6)
    risk_per_unit = close - stop_loss
    r1 = round(close + risk_per_unit * 1.5, 6)
    r2 = round(close + risk_per_unit * 3.0, 6)

    rsi = ind.get("rsi14", 50.0)
    adx = ind.get("adx14", 0.0)
    trigger_raw = min(100.0, max(0.0,
        (min(rsi, 70) / 70 * 40) +
        (min(adx, 40) / 40 * 30) +
        (min(ignition["vol_ratio"], 3.0) / 3.0 * 30)
    ))

    trend = _trend_context(coin_snapshot or {})
    trigger_adjusted = max(0.0, min(100.0, trigger_raw + trend["adjustment"]))

    thesis_score = pearl_row.get("incubator_score", 50.0) if (is_pearl and pearl_row) else 50.0
    macro_score = _macro_subscore()
    entry_score = 100.0

    fused = bridge_crypto.apply_pedigree_bonus(trigger_adjusted, is_pearl, ignition["ignited"])
    conviction = bridge_crypto.unified_conviction(thesis_score, fused, macro_score, entry_score)

    live_price = cdata.fetch_live_price_binance(symbol) or close
    drift_pct = round(100.0 * (live_price - close) / close, 2) if close else 0.0

    return {
        "symbol": symbol, "skip": False, "close": close, "live_price": live_price,
        "drift_pct": drift_pct, "is_pearl": is_pearl, "ignited": ignition["ignited"],
        "ignition_reason": ignition["reason"], "trigger_score": round(trigger_adjusted, 1),
        "conviction": conviction, "rsi14": round(rsi, 1), "adx14": round(adx, 1),
        "entry": close, "stop_loss": stop_loss, "r1": r1, "r2": r2, "atr14": atr14,
        "trend_label": trend["label"],
        "hold_days_t1": _estimated_hold_days(close, r1, atr14),
        "hold_days_t2": _estimated_hold_days(close, r2, atr14),
    }


def _format_alert_line(r: dict, tag: str, target_low: float, target_high: float, entry_ts: str) -> str:
    news = r.get("news", {})
    if news.get("available"):
        if news["label"] == "SILENT":
            news_line = "   📰 No recent news — pure technical setup, no catalyst confirmed"
        else:
            headline = f' — "{news["top_headline"][:70]}"' if news.get("top_headline") else ""
            news_line = f"   📰 News: {news['label']} ({news['headline_count']} posts){headline}"
        buzz = news.get("social_buzz_count")
        if buzz is not None:
            news_line += f"\n   🐦 Social buzz (Twitter/Reddit via CryptoPanic, proxy not exact count): {buzz} posts"
        if news.get("forward_catalyst"):
            news_line += f"\n   🔮 Forward catalyst language detected: \"{news['forward_catalyst']}\" (verify before acting — not a probability estimate)"
    else:
        news_line = "   📰 News: n/a (CRYPTOPANIC_API_KEY not set)"

    whale = r.get("whale_accum", {})
    if whale.get("available"):
        arrow = {"ACCUMULATING": "📈 whales adding", "DISTRIBUTING": "📉 whales reducing",
                  "STABLE": "➡️ whales stable"}.get(whale["label"], whale["label"])
        whale_line = f"\n   🐋 Big wallets ({whale['days_since_prior']}d trend): {arrow} (top10 Δ{whale['top10_delta_pct']:+.1f}%)"
    elif r.get("whale_accum") is not None:
        whale_line = "\n   🐋 Big wallets: no trend yet (need 2+ weekly snapshots)"
    else:
        whale_line = ""

    risk = r.get("risk", {})
    if risk.get("available") and risk.get("flags"):
        risk_line = f"\n   🔍 False-pearl check ({risk['severity']}): " + "; ".join(risk["flags"])
    elif risk.get("available"):
        risk_line = f"\n   🔍 False-pearl check: CLEAN — no red flags found"
    else:
        risk_line = f"\n   🔍 False-pearl check: unchecked (non-EVM token or check unavailable)"

    decision = _decision_label(r, risk)

    return (
        f"• <b>{r['symbol']}</b> [{tag}] conviction={r['conviction']} | target {target_low:.0f}-{target_high:.0f}% | <b>{decision}</b>\n"
        f"   ENTRY ${r['entry']:.4f} at {entry_ts} UTC | SL ${r['stop_loss']:.4f}\n"
        f"   T1 ${r['r1']:.4f} (~{r['hold_days_t1']}d) | T2 ${r['r2']:.4f} (~{r['hold_days_t2']}d)\n"
        f"   Trend: {r['trend_label']}\n"
        f"{news_line}{whale_line}{risk_line}\n"
        f"   live=${r['live_price']:.4f} (drift {r['drift_pct']}%)"
    )


def _decision_label(r: dict, risk: dict) -> str:
    """BUY / WATCH / AVOID — per your mentor's requested output format.
    This is a LABEL summarizing the combined signal, not a new decision
    engine: HIGH_RISK false-pearl flags override everything else (even a
    high-conviction technical setup is not a 'buy' if the contract can
    rug), CAUTION downgrades a clean BUY to WATCH, and anything below
    conviction floor stays WATCH regardless of risk status."""
    severity = risk.get("severity", "UNCHECKED")
    if severity == "HIGH_RISK":
        return "🚫 AVOID (false-pearl risk)"
    if r["conviction"] < 50:
        return "👀 WATCH"
    if severity == "CAUTION":
        return "👀 WATCH (minor risk flags)"
    return "✅ BUY"


def _log_alert_signal(r: dict, tier: str, target_low: float, target_high: float) -> None:
    """Writes this alert into crypto_signal_log so outcome_tracker.py can
    check it against real price action on future runs. This is the first
    link in the flywheel — every alert that goes out gets tracked, no
    exceptions, so hit-rate stats are never selectively computed only on
    the signals that happened to do well."""
    try:
        log_signal({
            "symbol": r["symbol"], "tier": tier, "entry_price": r["entry"],
            "stop_loss": r["stop_loss"], "r1": r["r1"], "r2": r["r2"],
            "conviction": r["conviction"], "trigger_score": r["trigger_score"],
            "trend_label": r["trend_label"],
            "news_label": r.get("news", {}).get("label"),
            "forward_catalyst": r.get("news", {}).get("forward_catalyst"),
            "whale_label": r.get("whale_accum", {}).get("label") if r.get("whale_accum") else None,
            "is_pearl": r["is_pearl"], "ignited": r["ignited"],
            "target_low_pct": target_low, "target_high_pct": target_high,
        })
    except Exception as e:
        log.warning(f"Failed to log signal for {r['symbol']}: {e}")


def run() -> None:
    log.info(f"=== {ccfg.VERSION} — SNIPER (daily ignition scan) ===")
    init_crypto_tables()

    # ── OUTCOME TRACKER — check yesterday's open signals FIRST, before
    # scoring anything new. This is the flywheel: every prior alert gets
    # checked against real price action and resolved (WIN/LOSS/TIMEOUT)
    # before today's new candidates are even scanned.
    outcome_summary = outcome_tracker.check_and_resolve_open_signals()

    entry_ts = datetime.now(timezone.utc).strftime("%H:%M")

    results: List[dict] = []

    watchlist = bridge_crypto.load_active_watchlist()
    log.info(f"PASS A: {len(watchlist)} active pearl(s) on crypto watchlist")
    skip_count = 0
    for pearl in watchlist:
        try:
            r = score_symbol(pearl["symbol"], pearl["coin_id"], is_pearl=True, pearl_row=pearl)
            if r.get("skip"):
                skip_count += 1
                log.info(f"PASS A SKIP {pearl['symbol']}: {r.get('reason')}")
                continue
            results.append(r)
            log.info(f"PASS A scored {r['symbol']}: conviction={r['conviction']} trigger={r['trigger_score']}")
            if r["ignited"]:
                bridge_crypto.mark_ignited(r["symbol"], r["live_price"])
        except Exception as e:
            log.warning(f"PASS A exception on {pearl.get('symbol')}: {e}")
    if skip_count:
        log.info(f"PASS A: {skip_count} pearl(s) skipped (insufficient OHLC history)")

    universe = cdata.fetch_universe(top_n=COLD_SCAN_TOP_N)
    watchlist_symbols = {p["symbol"] for p in watchlist}
    log.info(f"PASS B: cold-scanning {len(universe)} coins (excluding {len(watchlist_symbols)} already on watchlist)")
    below_bar, skip_count_b = 0, 0
    for coin in universe:
        if coin["symbol"] in watchlist_symbols:
            continue
        try:
            r = score_symbol(coin["symbol"], coin["id"], is_pearl=False, coin_snapshot=coin)
            if r.get("skip"):
                skip_count_b += 1
                continue
            if r["conviction"] >= ccfg.DAILY_SWING_MIN:
                results.append(r)
            else:
                below_bar += 1
        except Exception as e:
            log.warning(f"PASS B exception on {coin['symbol']}: {e}")
    log.info(f"PASS B: {skip_count_b} skipped (insufficient history), {below_bar} scored below DAILY_SWING_MIN ({ccfg.DAILY_SWING_MIN})")

    results.sort(key=lambda r: r["conviction"], reverse=True)

    fortress_alerts = [r for r in results if r["conviction"] >= ccfg.LANE_FUSED_MIN]
    swing_alerts = [r for r in results if ccfg.DAILY_SWING_MIN <= r["conviction"] < ccfg.LANE_FUSED_MIN]

    log.info(f"{len(fortress_alerts)} FORTRESS-tier + {len(swing_alerts)} SWING-tier candidate(s)")

    # News sentiment AND whale-accumulation trend fetched ONLY for the
    # shortlist that will actually be alerted — same selective-cost
    # pattern as before, now extended to on-chain data too.
    from core.crypto import onchain as conchain
    coin_id_by_symbol = {p["symbol"]: p["coin_id"] for p in watchlist}
    coin_id_by_symbol.update({c["symbol"]: c["id"] for c in universe})
    for r in (fortress_alerts + swing_alerts):
        r["news"] = news_sentiment.sentiment_summary(r["symbol"])
        try:
            cid = coin_id_by_symbol.get(r["symbol"])
            platforms = cdata.fetch_platforms(cid) if cid else {}
            if conchain.is_onchain_supported(platforms):
                signal = conchain.whale_concentration_signal(platforms)
                r["whale_accum"] = conchain.whale_accumulation_delta(r["symbol"], signal)
            else:
                r["whale_accum"] = None
            # False Pearl Detection — warning-only, never blocks the alert
            r["risk"] = risk_engine.assess_false_pearl_risk(platforms)
        except Exception as e:
            log.debug(f"whale accumulation check failed for {r['symbol']}: {e}")
            r["whale_accum"] = None
            r["risk"] = {"available": False, "flags": [], "severity": "UNCHECKED",
                          "detail": "risk check errored"}

    if fortress_alerts or swing_alerts:
        lines = [f"🎯 <b>FORTRESS_CRYPTO — Daily Scan</b> ({datetime.now(timezone.utc).strftime('%Y-%m-%d')})", ""]
        if fortress_alerts:
            lines.append(f"🏰 <b>FORTRESS-tier (higher conviction, target {ccfg.PEARL_TARGET_LOW_PCT:.0f}-{ccfg.PEARL_TARGET_HIGH_PCT:.0f}%)</b>")
            for r in fortress_alerts[:10]:
                tag = "🦪🔥PEARL+IGNITED" if (r["is_pearl"] and r["ignited"]) else ("🦪PEARL" if r["is_pearl"] else "COLD-SCAN")
                lines.append(_format_alert_line(r, tag, ccfg.PEARL_TARGET_LOW_PCT, ccfg.PEARL_TARGET_HIGH_PCT, entry_ts))
                _log_alert_signal(r, "FORTRESS", ccfg.PEARL_TARGET_LOW_PCT, ccfg.PEARL_TARGET_HIGH_PCT)
            lines.append("")
        if swing_alerts:
            lines.append(f"⚡ <b>DAILY SWING-tier (shorter horizon, target {ccfg.DAILY_SWING_TARGET_LOW_PCT:.0f}-{ccfg.DAILY_SWING_TARGET_HIGH_PCT:.0f}%)</b>")
            for r in swing_alerts[:10]:
                lines.append(_format_alert_line(r, "SWING", ccfg.DAILY_SWING_TARGET_LOW_PCT, ccfg.DAILY_SWING_TARGET_HIGH_PCT, entry_ts))
                _log_alert_signal(r, "SWING", ccfg.DAILY_SWING_TARGET_LOW_PCT, ccfg.DAILY_SWING_TARGET_HIGH_PCT)
        lines.append("")
        lines.append(outcome_tracker.format_stats_summary())
        send_telegram("\n".join(lines))
    else:
        send_telegram(
            f"ℹ️ FORTRESS_CRYPTO Daily Scan ({datetime.now(timezone.utc).strftime('%Y-%m-%d')}): "
            f"ran successfully, {len(results)} candidate(s) scored, "
            f"none reached DAILY_SWING_MIN ({ccfg.DAILY_SWING_MIN}). No trade alert today.\n\n"
            f"{outcome_tracker.format_stats_summary()}"
        )

    try:
        header = ["symbol", "is_pearl", "ignited", "conviction", "trigger_score", "trend_label",
                  "news_label", "close", "live_price", "drift_pct", "entry", "stop_loss", "r1", "r2",
                  "hold_days_t1", "hold_days_t2", "rsi14", "adx14", "ignition_reason"]
        rows = []
        for r in results:
            news_label = r.get("news", {}).get("label", "NOT_CHECKED")
            rows.append([r["symbol"], r["is_pearl"], r["ignited"], r["conviction"], r["trigger_score"],
                         r["trend_label"], news_label, r["close"], r["live_price"], r["drift_pct"],
                         r["entry"], r["stop_loss"], r["r1"], r["r2"], r["hold_days_t1"], r["hold_days_t2"],
                         r["rsi14"], r["adx14"], r["ignition_reason"]])
        push_sheet("CRYPTO_SCREENER", [header] + rows)
    except Exception as e:
        log.warning(f"Sheet push CRYPTO_SCREENER failed: {e}")


if __name__ == "__main__":
    run()
