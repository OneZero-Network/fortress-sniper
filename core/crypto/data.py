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
        try:
            resp = _session.get(url, params=params, headers=headers, timeout=20)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                wait = 2 ** (attempt + 2)
                log.warning(f"CoinGecko 429, backing off {wait}s ({path})")
                time.sleep(wait)
                continue
            log.warning(f"CoinGecko {resp.status_code} for {path}: {resp.text[:200]}")
            return None
        except Exception as e:
            log.warning(f"CoinGecko request error ({path}): {e}")
            time.sleep(1.5)
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
    top_n = top_n or ccfg.UNIVERSE_TOP_N
    out: List[dict] = []
    per_page = 250  # CoinGecko max per page
    pages_needed = (top_n // per_page) + 1
    for page in range(1, pages_needed + 1):
        data = _cg_get("/coins/markets", {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": per_page,
            "page": page,
            "sparkline": "false",
            "price_change_percentage": "24h,7d,30d",
        })
        if not data:
            log.warning(f"fetch_universe: page {page} failed, stopping cascade here")
            break
        out.extend(data)
        if len(data) < per_page:
            break
    out = out[:top_n]

    filtered = []
    for c in out:
        sym = (c.get("symbol") or "").upper()
        if ccfg.is_stable_or_wrapped(sym):
            continue
        vol = c.get("total_volume") or 0
        mcap = c.get("market_cap") or 0
        if vol < ccfg.MIN_24H_VOLUME_USD or mcap < ccfg.MIN_MARKET_CAP_USD:
            continue
        filtered.append({
            "id": c.get("id"),
            "symbol": sym,
            "name": c.get("name"),
            "market_cap": mcap,
            "market_cap_rank": c.get("market_cap_rank"),
            "volume_24h": vol,
            "price": c.get("current_price"),
            "pct_24h": c.get("price_change_percentage_24h_in_currency"),
            "pct_7d": c.get("price_change_percentage_7d_in_currency"),
            "pct_30d": c.get("price_change_percentage_30d_in_currency"),
            "ath": c.get("ath"),
            "ath_change_pct": c.get("ath_change_percentage"),
        })
    log.info(f"fetch_universe: {len(filtered)}/{len(out)} coins pass liquidity+non-stable filters")
    return filtered


def fetch_coin_details(coin_id: str) -> dict:
    """SINGLE /coins/{id} call returning BOTH categories and platform
    contract addresses. This replaces what used to be two separate
    functions (fetch_coin_categories + fetch_platforms) each hitting the
    same endpoint independently — that duplication was a real bug: it
    doubled CoinGecko call volume for zero benefit and was a direct
    contributor to the 429-throttling seen in production runs. Always
    call this ONCE per coin and reuse both fields from the result."""
    data = _cg_get(f"/coins/{coin_id}", {
        "localization": "false", "tickers": "false", "market_data": "false",
        "community_data": "false", "developer_data": "false",
    })
    if not data:
        return {"categories": None, "platforms": {}}
    return {
        "categories": [c.lower() for c in (data.get("categories") or []) if c],
        "platforms": {k: v for k, v in (data.get("platforms") or {}).items() if v},
    }


# Kept as thin wrappers for any external caller still using the old names —
# but internal workflow code now calls fetch_coin_details() once instead.
def fetch_coin_categories(coin_id: str) -> List[str]:
    d = fetch_coin_details(coin_id)
    return d["categories"] or []


def fetch_platforms(coin_id: str) -> Dict[str, str]:
    return fetch_coin_details(coin_id)["platforms"]


def fetch_daily_ohlc(coin_id: str, days: int = 90) -> pd.DataFrame:
    """Daily OHLC history for indicators/factor model. CoinGecko's OHLC
    endpoint returns coarser candles for longer windows automatically;
    volume is pulled separately from market_chart since /ohlc omits it."""
    ohlc = _cg_get(f"/coins/{coin_id}/ohlc", {"vs_currency": "usd", "days": days})
    if not ohlc:
        return pd.DataFrame()
    df = pd.DataFrame(ohlc, columns=["ts", "open", "high", "low", "close"])
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["ts"], unit="ms")

    chart = _cg_get(f"/coins/{coin_id}/market_chart", {
        "vs_currency": "usd", "days": days, "interval": "daily",
    })
    if chart and chart.get("total_volumes"):
        vol_df = pd.DataFrame(chart["total_volumes"], columns=["ts", "volume"])
        vol_df["date"] = pd.to_datetime(vol_df["ts"], unit="ms").dt.floor("D")
        df["date_floor"] = df["date"].dt.floor("D")
        df = df.merge(vol_df[["date", "volume"]], left_on="date_floor",
                       right_on="date", how="left", suffixes=("", "_v"))
        df["volume"] = df["volume"].fillna(0)
    else:
        df["volume"] = 0.0

    df = df[["date", "open", "high", "low", "close", "volume"]].sort_values("date")
    df = df.reset_index(drop=True)
    return df


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
