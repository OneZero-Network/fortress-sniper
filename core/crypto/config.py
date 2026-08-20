"""
FORTRESS_CRYPTO — core/crypto/config.py
══════════════════════════════════════════════════════════════════════════════
Crypto-specific tunables. Deliberately a SEPARATE config module from
core/config.py, not a merge — see README_CRYPTO.md for the reasoning.
Reuses core.config for anything asset-class-agnostic (Telegram, Sheets,
Anthropic keys, Kelly sizing philosophy) via `from .. import config as
equity_config` where genuinely shared.
"""
from __future__ import annotations
import os


def _bool(key: str, default: str) -> bool:
    return os.getenv(key, default).strip().lower() in ("1", "true", "yes", "on")


def _float(key: str, default: str) -> float:
    return float(os.getenv(key, default))


def _int(key: str, default: str) -> int:
    return int(os.getenv(key, default))


VERSION = "FORTRESS_CRYPTO v1.0 — Radar→Ignition→Execution (crypto horizon)"

# ══════════════════════════════════════════════════════════════════════════
# SECRETS — all optional at import time, all free-tier by default
# ══════════════════════════════════════════════════════════════════════════
# CoinGecko free tier needs no key for basic endpoints; a Demo API key
# raises the rate limit meaningfully if you register one (still free).
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")
COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# Binance public market-data endpoints need no key/auth at all.
BINANCE_BASE = os.getenv("BINANCE_BASE", "https://api.binance.com")

# Free-tier block explorer keys (used ONLY for EVM on-chain whale/holder
# concentration signal — Ethereum/BSC/Polygon). Each is optional; missing
# key -> that chain's on-chain leg is skipped for that token, fail-safe,
# not faked.
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")
BSCSCAN_API_KEY = os.getenv("BSCSCAN_API_KEY", "")
POLYGONSCAN_API_KEY = os.getenv("POLYGONSCAN_API_KEY", "")

# ══════════════════════════════════════════════════════════════════════════
# UNIVERSE
# ══════════════════════════════════════════════════════════════════════════
# DELIBERATE CHOICE (per your input): Top 200 by market cap. Broad enough
# to surface overlooked mid-caps ("pearls"), narrow enough that liquidity
# is real and wash-trading/manipulation risk on the scan universe stays
# bounded. Free CoinGecko rate limits also make Top 500+ impractical on a
# weekly/daily free-tier cadence without heavy caching.
UNIVERSE_TOP_N = _int("CRYPTO_UNIVERSE_TOP_N", "200")

# Liquidity / junk filters — analogue of MIN_TURNOVER_LAKHS/MIN_PRICE.
MIN_24H_VOLUME_USD = _float("CRYPTO_MIN_24H_VOLUME_USD", "3000000")   # $3M/day floor
MIN_MARKET_CAP_USD = _float("CRYPTO_MIN_MARKET_CAP_USD", "20000000")  # $20M floor — below this, wash-trading risk spikes
MAX_CANDIDATES = _int("CRYPTO_MAX_CANDIDATES", "200")

# Stablecoins / wrapped-asset noise — these are not "stocks", exclude from
# both incubation and ignition scans (mirrors the ETF-ban concept).
_STABLE_EXACT_SYMBOLS = {
    "USDT", "USDC", "DAI", "BUSD", "TUSD", "USDP", "USDD", "FDUSD", "PYUSD",
    "GUSD", "FRAX", "USDE", "LUSD", "USTC",
}
_WRAPPED_PREFIXES = ("WBTC", "WETH", "WBNB", "WSTETH", "STETH", "CBETH", "RETH")


def is_stable_or_wrapped(symbol: str) -> bool:
    sym = symbol.upper().strip()
    if sym in _STABLE_EXACT_SYMBOLS:
        return True
    if sym.startswith(_WRAPPED_PREFIXES):
        return True
    return False


# ══════════════════════════════════════════════════════════════════════════
# ON-CHAIN SCOPE — EVM-only, honest about the gap (per your input)
# ══════════════════════════════════════════════════════════════════════════
# Free-tier block explorers only give useful top-holder-concentration data
# for EVM chains we have a key for. Solana/Cosmos/etc. are OUT OF SCOPE for
# v1's on-chain leg — those tokens still get scored on price/volume factors,
# just with on_chain_score neutral(50)/None rather than fabricated.
ONCHAIN_ENABLED = _bool("CRYPTO_ONCHAIN_ENABLED", "true")
ONCHAIN_SUPPORTED_CHAINS = ("ethereum", "binance-smart-chain", "polygon-pos")
ONCHAIN_TOP_HOLDER_WHALE_PCT = _float("CRYPTO_ONCHAIN_WHALE_PCT", "5.0")  # single wallet holding >5% = flagged
ONCHAIN_TOP10_CONCENTRATION_WARN_PCT = _float("CRYPTO_TOP10_CONC_WARN_PCT", "40.0")

# ══════════════════════════════════════════════════════════════════════════
# CADENCE — DELIBERATELY faster than NSE's weekly/daily split
# ══════════════════════════════════════════════════════════════════════════
# Crypto's realized volatility and 24/7 trading make a strict weekly-only
# incubation cycle too slow to catch or avoid moves that happen mid-week.
# Incubator (pearl-finding) still runs weekly by default — the "quietly
# accumulating, undervalued" thesis is inherently a slower-moving signal —
# but ignition-checking runs DAILY (config below), same cadence philosophy
# as the equity version, not hourly: hourly scanning on free-tier rate
# limits isn't reliable, and chasing every intraday wick defeats the
# "ignition off a real base" thesis this whole system is built on.
INCUBATOR_CADENCE = os.getenv("CRYPTO_INCUBATOR_CADENCE", "weekly")
IGNITION_CADENCE = os.getenv("CRYPTO_IGNITION_CADENCE", "daily")

# ══════════════════════════════════════════════════════════════════════════
# RISK / SIZING — re-derived for crypto, NOT copied from equity Kelly config
# ══════════════════════════════════════════════════════════════════════════
# Crypto realized vol is routinely 3-6x NSE mid-cap vol, and 70-90%
# drawdowns are a normal historical occurrence for assets that later
# recovered — not the tail event equity Kelly sizing assumes. Half-Kelly
# on equity-calibrated confidence would still be dangerously oversized
# here. Defaults are deliberately more conservative than core.config's.
ACCOUNT_RISK_PCT = _float("CRYPTO_ACCOUNT_RISK_PCT", "0.0075")   # half the equity default (0.015)
MAX_POS_PCT = _float("CRYPTO_MAX_POS_PCT", "0.05")               # half the equity default (0.10)
KELLY_MIN_CLOSED_TRADES = _int("CRYPTO_KELLY_MIN_CLOSED_TRADES", "30")  # more evidence required than equity's 20
KELLY_DEFAULT_MULT = _float("CRYPTO_KELLY_DEFAULT_MULT", "0.35")  # quarter-to-third Kelly, not half
KELLY_FLOOR = _float("CRYPTO_KELLY_FLOOR", "0.05")
KELLY_CEILING = _float("CRYPTO_KELLY_CEILING", "0.35")

ATR_PERIOD = _int("CRYPTO_ATR_PERIOD", "14")
ATR_MULT_TREND = _float("CRYPTO_ATR_MULT_TREND", "2.0")    # wider than equity's 1.5 — crypto whipsaws more
ATR_MULT_CHOP = _float("CRYPTO_ATR_MULT_CHOP", "2.75")
ATR_MULT_BUNKER = _float("CRYPTO_ATR_MULT_BUNKER", "3.5")

# ══════════════════════════════════════════════════════════════════════════
# IGNITION DETECTION — same box-breakout+volume concept, crypto-tuned
# ══════════════════════════════════════════════════════════════════════════
IGNITION_BOX_BREAKOUT_PCT = _float("CRYPTO_IGNITION_BOX_BREAKOUT_PCT", "0.035")  # 3.5% vs equity's 2% — crypto noise floor is higher
IGNITION_VOL_MULT = _float("CRYPTO_IGNITION_VOL_MULT", "2.2")                    # higher bar than equity's 1.8x
IGNITION_MA50_RECLAIM = _bool("CRYPTO_IGNITION_MA50_RECLAIM", "true")

PEARL_PEDIGREE_BONUS = _float("CRYPTO_PEARL_PEDIGREE_BONUS", "12.0")
PEARL_IGNITION_BONUS = _float("CRYPTO_PEARL_IGNITION_BONUS", "8.0")
PEARL_WATCHLIST_TTL_DAYS = _int("CRYPTO_PEARL_WATCHLIST_TTL_DAYS", "45")  # shorter than equity's 90 — crypto theses go stale faster

# ══════════════════════════════════════════════════════════════════════════
# CONVICTION SCALE — same 0-100 unified philosophy as equity bridge.py
# ══════════════════════════════════════════════════════════════════════════
CONVICTION_W_THESIS = _float("CRYPTO_CONVICTION_W_THESIS", "25.0")   # slightly lower than equity's 30 — crypto fundamentals are weaker signal
CONVICTION_W_TRIGGER = _float("CRYPTO_CONVICTION_W_TRIGGER", "45.0")  # slightly higher — technical/flow trigger matters more here
CONVICTION_W_MACRO = _float("CRYPTO_CONVICTION_W_MACRO", "20.0")
CONVICTION_W_ENTRY = _float("CRYPTO_CONVICTION_W_ENTRY", "10.0")

LANE_FORTRESS_MIN = _int("CRYPTO_LANE_FORTRESS_MIN", "100")
LANE_APEX_MIN = _int("CRYPTO_LANE_APEX_MIN", "55")
LANE_FUSED_MIN = _int("CRYPTO_LANE_FUSED_MIN", "60")

# ══════════════════════════════════════════════════════════════════════════
# COMPOSITE FACTOR MODEL — momentum + "value" analogue + on-chain quality
# ══════════════════════════════════════════════════════════════════════════
# Value has NO clean crypto analogue (no earnings/book value for most
# tokens). We substitute inverse-NVT (Network Value to Transactions —
# market_cap / on-chain or reported transfer volume; a lower NVT means
# the network is doing more economic work per dollar of valuation, the
# closest crypto equivalent of "cheap"). Where NVT is unavailable, this
# leg degrades to neutral 0.0, same fail-safe-neutral policy as equity
# factors.py — never silently substituted with a fabricated number.
FACTOR_ZSCORE_ENABLED = _bool("CRYPTO_FACTOR_ZSCORE_ENABLED", "true")
FACTOR_W_MOMENTUM = _float("CRYPTO_FACTOR_W_MOMENTUM", "0.45")
FACTOR_W_VALUE_NVT = _float("CRYPTO_FACTOR_W_VALUE_NVT", "0.20")
FACTOR_W_ONCHAIN_QUALITY = _float("CRYPTO_FACTOR_W_ONCHAIN_QUALITY", "0.35")  # replaces equity's ROE-based quality leg
FACTOR_MIN_UNIVERSE_N = _int("CRYPTO_FACTOR_MIN_UNIVERSE_N", "30")
MOMENTUM_LOOKBACK_DAYS = _int("CRYPTO_MOMENTUM_LOOKBACK_DAYS", "30")  # shorter than equity's 63 — crypto trends move faster
BENCHMARK_COIN_ID = os.getenv("CRYPTO_BENCHMARK_COIN_ID", "bitcoin")  # residual momentum vs BTC, not vs an index

# ══════════════════════════════════════════════════════════════════════════
# SHARIAH (CRYPTO) — see core/crypto/shariah_crypto.py for full reasoning.
# This is a documented POSITION among genuine scholarly disagreement, not
# a settled ruling. All of it is config-gated so you can change your mind
# without touching code.
# ══════════════════════════════════════════════════════════════════════════
SHARIAH_FAIL_SAFE = True  # same non-negotiable policy as equity: unknown -> reject

# Per your explicit choice: staking/PoS-yield tokens are rejected outright,
# not scored under a contested halal/haram staking policy.
SHARIAH_REJECT_STAKING_TOKENS = True

# Categorical exclusions — asset TYPE, not issuer financials (crypto has
# no balance sheet to run a debt-ratio screen against).
SHARIAH_REJECT_PRIVACY_COINS = _bool("CRYPTO_SHARIAH_REJECT_PRIVACY", "true")
SHARIAH_REJECT_GAMBLING_PREDICTION = _bool("CRYPTO_SHARIAH_REJECT_GAMBLING", "true")
SHARIAH_REJECT_LENDING_YIELD_TOKENS = _bool("CRYPTO_SHARIAH_REJECT_LENDING", "true")
SHARIAH_REJECT_ALGO_STABLECOINS = _bool("CRYPTO_SHARIAH_REJECT_ALGO_STABLE", "true")  # excess gharar per several boards' rulings

_PRIVACY_COIN_SYMBOLS = {"XMR", "ZEC", "DASH", "SCRT", "ROSE", "ARRR", "FIRO"}
_GAMBLING_PREDICTION_CATEGORY_TERMS = ("gambling", "casino", "prediction-market", "betting")
_STAKING_CATEGORY_TERMS = ("liquid-staking", "staking", "lsd", "liquid-staking-tokens")
_LENDING_CATEGORY_TERMS = ("lending-borrowing", "yield-farming", "yield-aggregator")

CRYPTOPANIC_API_KEY = os.getenv("CRYPTOPANIC_API_KEY", "")
CRYPTOPANIC_BASE = "https://cryptopanic.com/api/v1"
NEWS_SENTIMENT_ENABLED = _bool("CRYPTO_NEWS_SENTIMENT_ENABLED", "true")
NEWS_SENTIMENT_LOOKBACK_HOURS = _int("CRYPTO_NEWS_LOOKBACK_HOURS", "48")
# News sentiment is only fetched for candidates that ALREADY cleared the
# technical trigger threshold — not the whole universe. This is the
# "diving" layer applied selectively to what the "metal detector" already
# flagged, not a second blanket scan (keeps API call volume sane on free
# tiers and matches how a human analyst would actually work: scan broad,
# then read the news on the shortlist, not on all 200 coins).

CRYPTO_HALAL_LIST_SHEET_TAB = "CRYPTO_HALAL_LIST"  # seed manually, same pattern as HALAL_LIST tab

# ══════════════════════════════════════════════════════════════════════════
# DAILY SWING TIER — fix for daily consistently returning 0 candidates.
# LANE_FUSED_MIN=60 is calibrated for high-conviction "fortress" setups —
# the same bar as the weekly Incubator's best pearls. A daily 10-20%
# swing candidate is a genuinely different, lower-conviction, shorter-
# horizon category. Giving it its own lower bar is the correct fix, not
# lowering LANE_FUSED_MIN globally (which would blur the two tiers and
# let low-conviction noise through as if it were a "fortress" pick).
# ══════════════════════════════════════════════════════════════════════════
DAILY_SWING_MIN = _float("CRYPTO_DAILY_SWING_MIN", "42.0")
DAILY_SWING_TARGET_LOW_PCT = _float("CRYPTO_DAILY_SWING_TARGET_LOW_PCT", "10.0")
DAILY_SWING_TARGET_HIGH_PCT = _float("CRYPTO_DAILY_SWING_TARGET_HIGH_PCT", "20.0")
PEARL_TARGET_LOW_PCT = _float("CRYPTO_PEARL_TARGET_LOW_PCT", "25.0")
PEARL_TARGET_HIGH_PCT = _float("CRYPTO_PEARL_TARGET_HIGH_PCT", "50.0")

# ══════════════════════════════════════════════════════════════════════════
# NEWS SENTIMENT — the first "diving skill" layer, applied SELECTIVELY to
# candidates that already cleared the technical trigger threshold, not to
# the whole universe (matches how a human analyst actually works: scan
# broad first, then read the news on the shortlist). CryptoPanic free
# tier needs a free signup for an auth_token — without one this degrades
# to neutral (sentiment=None, never fabricated), same fail-safe-neutral
# philosophy as onchain.py and factors_crypto.py.
# ══════════════════════════════════════════════════════════════════════════
CRYPTOPANIC_API_KEY = os.getenv("CRYPTOPANIC_API_KEY", "")
CRYPTOPANIC_BASE = "https://cryptopanic.com/api/v1"
NEWS_SENTIMENT_ENABLED = _bool("CRYPTO_NEWS_SENTIMENT_ENABLED", "true")
NEWS_SENTIMENT_LOOKBACK_HOURS = _int("CRYPTO_NEWS_LOOKBACK_HOURS", "48")

# ══════════════════════════════════════════════════════════════════════════
# TREND CONTEXT — second "diving skill" layer: higher-timeframe trend
# confirmation using data already fetched (pct_7d/pct_30d from CoinGecko
# markets payload), no extra API calls. A coin ticking every technical
# box but fighting a hard downtrend on the 30d chart is a lower-quality
# signal than the same setup WITH the trend, even at equal trigger score.
# ══════════════════════════════════════════════════════════════════════════
TREND_ALIGNED_BONUS = _float("CRYPTO_TREND_ALIGNED_BONUS", "6.0")
TREND_AGAINST_PENALTY = _float("CRYPTO_TREND_AGAINST_PENALTY", "8.0")


# ══════════════════════════════════════════════════════════════════════════
# v3.2 — MULTI-UNIVERSE SCANNER
# ══════════════════════════════════════════════════════════════════════════
# Three tiers, each with its OWN liquidity floor — applying the Large-cap
# floor to Emerging-tier coins would filter out the entire tier (a rank
# 1500 coin legitimately has far less volume than a rank 20 coin, that's
# not a red flag at that rank). New-listings and DEX/new-token universes
# are explicitly OUT OF SCOPE here — they need a different data source
# (CoinGecko doesn't cleanly serve "new listings" free; DEX-native data
# needs something like DexScreener), flagged as a real follow-up, not
# silently dropped.
UNIVERSE_TIERS = {
    "LARGE_CAP": {
        "min_rank": 1, "max_rank": 100,
        "min_volume_usd": float(os.getenv("CRYPTO_LARGE_MIN_VOL", "3000000")),
        "min_market_cap_usd": float(os.getenv("CRYPTO_LARGE_MIN_MCAP", "500000000")),
        "max_deep_scored": int(os.getenv("CRYPTO_LARGE_MAX_DEEP", "40")),
    },
    "MID_CAP": {
        "min_rank": 101, "max_rank": 500,
        "min_volume_usd": float(os.getenv("CRYPTO_MID_MIN_VOL", "500000")),
        "min_market_cap_usd": float(os.getenv("CRYPTO_MID_MIN_MCAP", "20000000")),
        "max_deep_scored": int(os.getenv("CRYPTO_MID_MAX_DEEP", "40")),
    },
    "EMERGING": {
        "min_rank": 501, "max_rank": 2000,
        "min_volume_usd": float(os.getenv("CRYPTO_EMERGING_MIN_VOL", "100000")),
        "min_market_cap_usd": float(os.getenv("CRYPTO_EMERGING_MIN_MCAP", "2000000")),
        "max_deep_scored": int(os.getenv("CRYPTO_EMERGING_MAX_DEEP", "30")),
    },
}
# max_deep_scored caps how many candidates per tier proceed to the
# EXPENSIVE full scoring pass (whale/news/risk checks) — this is the
# funnel your mentor's own diagram described (2000 assets -> cheap
# filter -> hundreds -> expensive checks on the survivors only). Without
# this cap, scanning 2000 Emerging-tier coins with per-coin API calls
# would take hours, not minutes.
PREFILTER_TOP_N_MULTIPLIER = 3  # pre-filter keeps 3x max_deep_scored candidates by cheap score, before dedup
