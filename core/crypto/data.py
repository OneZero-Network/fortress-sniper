"""
FORTRESS_CRYPTO — core/crypto/data.py
══════════════════════════════════════════════════════════════════════════════
Data cascade for crypto, analogue of core/nse_data.py. Two free sources,
each doing the job it's actually good at (not a single do-everything call):

  1. CoinGecko  — universe listing (top-N by market cap), market cap,
                   24h volume, price, category tags (used by the Shariah
                   screen to detect gambling/staking/lending categories),
                   and daily OHLC history for factor/technical scoring.
  2. Binance    — live/near-real-time price for the ignition check and
                   scripts/check_entry-equivalent staleness guard. Public
                   market-data endpoints, no key/auth required. Coverage
                   limited to Binance-listed pairs (most liquid caps).

Both sources are FREE-TIER and rate-limited. This module caches within a
single run (in-memory) and backs off on 429s. Nothing here fabricates data
on failure — every function returns None/empty rather than a guessed value,
matching the fail-safe-on-missing-data philosophy of the equity pipeline's
fundamentals.py.
"""
from __future__ import annotations
import logging
import time
from typing import Dict, List, Optional

import pandas as pd
import requests

from . import config as ccfg

log = logging.getLogger("fortress.crypto.data")

_session = requests.Session()
_session.headers.update({"User-Agent": "fortress-crypto/1.0"})

# ══════════════════════════════════════════════════════════════════════════
# GLOBAL RATE LIMITER — this is the actual fix for the 429-storm seen in
# production logs. The free CoinGecko public tier allows roughly 10-30
# calls/min; without a key, retry-on-429 backoff alone still means every
# call queues behind a growing backlog once you're scanning ~200 coins.
# A single enforced minimum gap between ANY two CoinGecko calls (regardless
# of success/failure) keeps the run under the limit proactively instead of
# discovering it reactively coin-by-coin. With a free Demo key this gap can
# be much shorter (COINGECKO_MIN_INTERVAL_SEC env var), since the key tier
# has a materially higher ceiling.
# ══════════════════════════════════════════════════════════════════════════
import os as _os
_MIN_INTERVAL = float(_os.getenv(
    "COINGECKO_MIN_INTERVAL_SEC",
    "2.5" if not ccfg.COINGECKO_API_KEY else "1.0",
))
_last_call_ts = [0.0]

# ══════════════════════════════════════════════════════════════════════════
# v3.3 — API BUDGET + PER-RUN CACHE
# ══════════════════════════════════════════════════════════════════════════
# API BUDGET: a hard ceiling on total CoinGecko calls per run. Expanding
# from ~60 to ~110 candidates roughly doubles call volume — this makes
# that cost VISIBLE and BOUNDED rather than hoping the throttle alone
# keeps things sane. When the budget is hit mid-run, the caller (see
# workflows/sniper_daily_crypto.py) stops scoring further candidates
# gracefully and reports exactly how many were skipped — never a crash,
# never fabricated data for the ones that didn't get checked.
API_CALL_BUDGET = int(_os.getenv("CRYPTO_API_CALL_BUDGET", "500"))
_call_count = [0]
_rate_limited_this_run = [False]


def get_api_call_count() -> int:
    return _call_count[0]


def budget_remaining() -> int:
    return max(0, API_CALL_BUDGET - _call_count[0])


def budget_exhausted() -> bool:
    return _call_count[0] >= API_CALL_BUDGET


def was_rate_limited_this_run() -> bool:
    """True if any call hit a 429 this run — surfaced in the diagnostic
    report so 'fewer results than expected' can be attributed correctly
    to provider throttling rather than silently blamed on the scoring
    model."""
    return _rate_limited_this_run[0]


def reset_run_state() -> None:
    """Call once at the start of a run if you need a clean slate
    (mainly useful for tests) — normal production runs are one-shot
    processes so this rarely needs calling."""
    _call_count[0] = 0
    _rate_limited_this_run[0] = False
    _platform_cache.clear()
    _ohlc_cache.clear()
    _coin_details_cache.clear()


# Per-run in-memory cache — keyed by coin_id, cleared naturally each
# fresh process run. If platform data for HYPE was already fetched once
# (by the whale check), the risk check, velocity engine, and anything
# else needing it reuse the SAME result instead of calling again.
_platform_cache: Dict[str, dict] = {}
_ohlc_cache: Dict[str, "pd.DataFrame"] = {}
_coin_details_cache: Dict[str, dict] = {}


def _throttle() -> None:
    elapsed = time.monotonic() - _last_call_ts[0]
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_call_ts[0] = time.monotonic()


def _cg_get(path: str, params: Optional[dict] = None, retries: int = 3) -> Optional[dict]:
    params = dict(params or {})
    headers = {}
    if ccfg.COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = ccfg.COINGECKO_API_KEY
    url = f"{ccfg.COINGECKO_BASE}{path}"
    for attempt in range(retries):
        _throttle()
        _call_count[0] += 1
        try:
            resp = _session.get(url, params=params, headers=headers, timeout=20)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                _rate_limited_this_run[0] = True
                wait = 2 ** (attempt + 2)
                log.warning(f"CoinGecko 429, backing off {wait}s ({path})")
                time.sleep(wait)
                continue
            log.warning(f"CoinGecko {resp.status_code} for {path}: {resp.text[:200]}")
            return None
        except Exception as e:
            log.warning(f"CoinGecko request error ({path}): {e}")
            time.sleep(1.5)
    _rate_limited_this_run[0] = True  # exhausted all retries — likely still rate-limited
    return None


def _binance_get(path: str, params: Optional[dict] = None, retries: int = 3) -> Optional[dict]:
    url = f"{ccfg.BINANCE_BASE}{path}"
    for attempt in range(retries):
        try:
            resp = _session.get(url, params=params or {}, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                time.sleep(2 ** (attempt + 1))
                continue
            log.debug(f"Binance {resp.status_code} for {path}")
            return None
        except Exception as e:
            log.debug(f"Binance request error ({path}): {e}")
            time.sleep(1)
    return None


# ══════════════════════════════════════════════════════════════════════════
# UNIVERSE
# ══════════════════════════════════════════════════════════════════════════

def fetch_universe(top_n: int = None) -> List[dict]:
    """Top-N coins by market cap with price/volume/category snapshot.
    Analogue of nse_data.py's bhavcopy fetch. Filters stablecoins/wrapped
    assets and applies the liquidity floor before returning."""
    return fetch_universe_tier(1, top_n or ccfg.UNIVERSE_TOP_N,
                                min_volume_usd=ccfg.MIN_24H_VOLUME_USD,
                                min_market_cap_usd=ccfg.MIN_MARKET_CAP_USD)


def fetch_universe_tier(min_rank: int, max_rank: int, min_volume_usd: float,
                         min_market_cap_usd: float) -> List[dict]:
    """v3.2 — generalized rank-window fetch, powering the multi-universe
    scanner. min_rank/max_rank are 1-indexed market-cap rank bounds
    (e.g. 1-100 for Large cap, 500-2000 for Emerging). Liquidity floors
    are passed in per-tier rather than hardcoded — a Large-cap floor
    applied to an Emerging-tier coin would filter out the entire tier,
    so each tier needs its own honest threshold (see
    core/crypto/config.py's UNIVERSE_TIERS for the actual values used)."""
    out: List[dict] = []
    per_page = 250
    start_page = ((min_rank - 1) // per_page) + 1
    end_page = ((max_rank - 1) // per_page) + 1
    for page in range(start_page, end_page + 1):
        data = _cg_get("/coins/markets", {
            "vs_currency": "usd", "order": "market_cap_desc",
            "per_page": per_page, "page": page, "sparkline": "false",
            "price_change_percentage": "24h,7d,30d",
        })
        if not data:
            log.warning(f"fetch_universe_tier: page {page} failed, stopping cascade here")
            break
        out.extend(data)
        if len(data) < per_page:
            break

    filtered = []
    for c in out:
        rank = c.get("market_cap_rank")
        if rank is None or rank < min_rank or rank > max_rank:
            continue
        sym = (c.get("symbol") or "").upper()
        if ccfg.is_stable_or_wrapped(sym):
            continue
        vol = c.get("total_volume") or 0
        mcap = c.get("market_cap") or 0
        if vol < min_volume_usd or mcap < min_market_cap_usd:
            continue
        filtered.append({
            "id": c.get("id"), "symbol": sym, "name": c.get("name"),
            "market_cap": mcap, "market_cap_rank": rank, "volume_24h": vol,
            "price": c.get("current_price"),
            "pct_24h": c.get("price_change_percentage_24h_in_currency"),
            "pct_7d": c.get("price_change_percentage_7d_in_currency"),
            "pct_30d": c.get("price_change_percentage_30d_in_currency"),
            "ath": c.get("ath"), "ath_change_pct": c.get("ath_change_percentage"),
        })
    return filtered


def fetch_coin_details(coin_id: str) -> dict:
    """SINGLE /coins/{id} call returning BOTH categories and platform
    contract addresses. This replaces what used to be two separate
    functions (fetch_coin_categories + fetch_platforms) each hitting the
    same endpoint independently — that duplication was a real bug: it
    doubled CoinGecko call volume for zero benefit and was a direct
    contributor to the 429-throttling seen in production runs. Always
    call this ONCE per coin and reuse both fields from the result.

    v3.7 FIX: this function itself is now CACHED per run — previously
    only fetch_platforms() cached its result, but fetch_coin_categories()
    called this function fresh every time even for a coin whose
    platforms had already been fetched and cached. Caching HERE means
    both derived functions share one cached call, not two independent
    ones."""
    if coin_id in _coin_details_cache:
        return _coin_details_cache[coin_id]
    data = _cg_get(f"/coins/{coin_id}", {
        "localization": "false", "tickers": "false", "market_data": "false",
        "community_data": "false", "developer_data": "false",
    })
    if not data:
        result = {"categories": None, "platforms": {}}
    else:
        result = {
            "categories": [c.lower() for c in (data.get("categories") or []) if c],
            "platforms": {k: v for k, v in (data.get("platforms") or {}).items() if v},
        }
    _coin_details_cache[coin_id] = result
    return result


# Kept as thin wrappers for any external caller still using the old names —
# both now transparently share fetch_coin_details()'s cache.
def fetch_coin_categories(coin_id: str) -> List[str]:
    d = fetch_coin_details(coin_id)
    return d["categories"] or []


def fetch_platforms(coin_id: str) -> Dict[str, str]:
    """Thin wrapper over the now-cached fetch_coin_details() — kept for
    backward compatibility with existing call sites, but the actual
    caching happens one level down now."""
    return fetch_coin_details(coin_id)["platforms"]


def fetch_daily_ohlc(coin_id: str, days: int = 95) -> pd.DataFrame:
    """CACHED per run, keyed by (coin_id, days). Multiple lenses (V5
    backtest, velocity engine, regime detection) can request the same
    coin's OHLC in the same run — this avoids re-fetching identical
    data. See _fetch_daily_ohlc_uncached for the actual fetch logic and
    its full documentation."""
    cache_key = f"{coin_id}:{days}"
    if cache_key in _ohlc_cache:
        return _ohlc_cache[cache_key]
    result = _fetch_daily_ohlc_uncached(coin_id, days)
    _ohlc_cache[cache_key] = result
    return result


def _fetch_daily_ohlc_uncached(coin_id: str, days: int = 95) -> pd.DataFrame:
    """TRUE daily OHLCV series. This REPLACES a broken earlier approach
    that used CoinGecko's /ohlc endpoint directly — that endpoint
    auto-buckets into coarser candles as the requested window grows
    (roughly 4-day candles once days > 30 on the free tier), so a
    days=90 request was silently returning ~22 rows, just under this
    system's 25-row minimum. Production logs showed this failing on
    nearly every symbol, every run. Worse: on the rare coin that DID
    clear 25 rows, those were actually 4-day candles mislabeled as
    daily, meaning every ATR/RSI/ignition threshold tuned for daily
    bars was silently being computed on the wrong timeframe.

    FIX: build the daily series from /market_chart instead, which
    returns genuinely one data point per day once the requested window
    exceeds 90 days (documented CoinGecko free-tier behavior) — hence
    days=95 default, safely past that boundary.

    HONEST LIMITATION: /market_chart gives price + volume, not true
    intraday OHLC. Each day's open is approximated as the PRIOR day's
    close (so a day's candle reflects real direction: green if it
    closed above where it opened), and high/low are approximated as
    max/min(open, close) for that day — this loses true intraday
    wick/range information. It is a real trade-off, not free — anything
    depending on precise intraday high/low (box_high_20 in particular)
    is now an approximation of daily closes, not true daily ranges.
    Flagged here rather than silently presented as equivalent to real
    OHLC.
    """
    chart = _cg_get(f"/coins/{coin_id}/market_chart", {
        "vs_currency": "usd", "days": days, "interval": "daily",
    })
    if not chart or not chart.get("prices"):
        return pd.DataFrame()

    price_df = pd.DataFrame(chart["prices"], columns=["ts", "close"])
    price_df["date"] = pd.to_datetime(price_df["ts"], unit="ms").dt.floor("D")
    price_df = price_df.drop_duplicates(subset="date", keep="last").sort_values("date").reset_index(drop=True)

    if chart.get("total_volumes"):
        vol_df = pd.DataFrame(chart["total_volumes"], columns=["ts", "volume"])
        vol_df["date"] = pd.to_datetime(vol_df["ts"], unit="ms").dt.floor("D")
        vol_df = vol_df.drop_duplicates(subset="date", keep="last")
        price_df = price_df.merge(vol_df[["date", "volume"]], on="date", how="left")
        price_df["volume"] = price_df["volume"].fillna(0)
    else:
        price_df["volume"] = 0.0

    price_df["open"] = price_df["close"].shift(1).fillna(price_df["close"])
    price_df["high"] = price_df[["open", "close"]].max(axis=1)
    price_df["low"] = price_df[["open", "close"]].min(axis=1)

    return price_df[["date", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════
# BINANCE — live/intraday price for ignition + entry-staleness checks
# ══════════════════════════════════════════════════════════════════════════

def binance_symbol(base_symbol: str, quote: str = "USDT") -> str:
    return f"{base_symbol.upper()}{quote.upper()}"

def fetch_live_price_binance(base_symbol: str, quote: str = "USDT") -> Optional[float]:
    data = _binance_get("/api/v3/ticker/price", {"symbol": binance_symbol(base_symbol, quote)})
    if not data or "price" not in data:
        return None
    try:
        return float(data["price"])
    except (TypeError, ValueError):
        return None


def fetch_24h_stats_binance(base_symbol: str, quote: str = "USDT") -> Optional[dict]:
    data = _binance_get("/api/v3/ticker/24hr", {"symbol": binance_symbol(base_symbol, quote)})
    if not data:
        return None
    try:
        return {
            "last_price": float(data["lastPrice"]),
            "pct_change_24h": float(data["priceChangePercent"]),
            "high_24h": float(data["highPrice"]),
            "low_24h": float(data["lowPrice"]),
            "volume_24h_base": float(data["volume"]),
            "volume_24h_quote": float(data["quoteVolume"]),
        }
    except (KeyError, TypeError, ValueError):
        return None
