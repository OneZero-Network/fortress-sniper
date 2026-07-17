"""
FORTRESS_UNIFIED — core/config.py
══════════════════════════════════════════════════════════════════════════════
Single source of truth for every tunable constant across all three
entrypoints (sniper, incubator, pine-sync). Pine Script itself can't read
this file (TradingView sandboxes scripts), but the *values* here are the
canonical reference — when you change a threshold, change it here first,
then mirror it into the .pine inputs by hand. A comment marks every constant
that has a Pine-side twin so the two never drift silently.

BUG FIXES BAKED IN (see review notes):
  - KELLY_DOUBLE_BUG: old incubator/sniper code did shares * kelly_mult * 2.
    That silently doubled position size relative to the ATR risk model
    whenever Kelly had insufficient history (kelly_mult defaults to 1.0 with
    <6 trades) — i.e. duplicated risk exactly when there's no track record
    to justify it. Fixed here: kelly_mult is applied ONCE, and defaults to
    a conservative 0.5 (half-Kelly) rather than 1.0 until there's real data.
  - ETF_BAN_SUBSTRING_BUG: 'BHARAT' matched BHARATFORG/BHARATGEAR,
    'GILT'/'LIQUID' had similar collision risk. Fixed with a wordlist that
    requires exact-token or suffix match, not raw substring.
"""
from __future__ import annotations
import os


def _bool(key: str, default: str) -> bool:
    return os.getenv(key, default).strip().lower() in ("1", "true", "yes", "on")


def _float(key: str, default: str) -> float:
    return float(os.getenv(key, default))


def _int(key: str, default: str) -> int:
    return int(os.getenv(key, default))


# ══════════════════════════════════════════════════════════════════════════
# IDENTITY
# ══════════════════════════════════════════════════════════════════════════
VERSION = "FORTRESS_UNIFIED v1.0 — Radar→Ignition→Execution"
BUILD_DATE = "2026-07-17"

# ══════════════════════════════════════════════════════════════════════════
# SECRETS (all optional at import time — checked via preflight, not asserted)
# ══════════════════════════════════════════════════════════════════════════
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MINI_MODEL = os.getenv("OPENAI_MINI_MODEL", "gpt-4o-mini")
OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

# Anthropic — used ONLY for the Monday consolidated review (weekly learning
# loop). Not used for Shariah audits, narrative generation, or any per-trade
# decision — those stay on OpenAI as before, unchanged, to avoid touching a
# working pipeline. See core/weekly_review.py.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON", "")

SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY", "")
ADDON_FINANCE_API_KEY = os.getenv("ADDON_FINANCE_API_KEY", "")

REQUIRED_SECRETS = {
    "OPENAI_API_KEY": OPENAI_API_KEY,
    "TELEGRAM_TOKEN": TELEGRAM_TOKEN,
    "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
    "GOOGLE_SHEET_ID": GOOGLE_SHEET_ID,
    "GOOGLE_CREDS_JSON": GOOGLE_CREDS_JSON,
}
OPTIONAL_SECRETS = {
    "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
    "SCRAPERAPI_KEY": SCRAPERAPI_KEY,
    "ADDON_FINANCE_API_KEY": ADDON_FINANCE_API_KEY,
}

# ══════════════════════════════════════════════════════════════════════════
# ACCOUNT / RISK
# ══════════════════════════════════════════════════════════════════════════
ACCOUNT_EQUITY = _float("ACCOUNT_EQUITY", "500000")     # Pine: i_account_cap
ACCOUNT_RISK_PCT = _float("ACCOUNT_RISK_PCT", "0.015")  # Pine: i_risk_pct/100
MAX_POS_PCT = _float("MAX_POS_PCT", "0.10")             # Pine: i_max_pos_pct/100

# ── Kelly sizing — FIXED. Applied once, never doubled. ──────────────────────
KELLY_MIN_CLOSED_TRADES = _int("KELLY_MIN_CLOSED_TRADES", "20")   # was 5/6 — too low to trust
KELLY_DEFAULT_MULT = _float("KELLY_DEFAULT_MULT", "0.5")          # half-Kelly until proven, NOT 1.0
KELLY_FLOOR = _float("KELLY_FLOOR", "0.10")
KELLY_CEILING = _float("KELLY_CEILING", "0.50")


def kelly_adjusted_size(shares: int, kelly_mult: float) -> int:
    """FIXED: apply multiplier once. Old code did `* kelly_mult * 2`."""
    return max(1, int(shares * max(KELLY_FLOOR, min(KELLY_CEILING, kelly_mult))))


# ══════════════════════════════════════════════════════════════════════════
# UNIVERSE / SCREENING GATES
# ══════════════════════════════════════════════════════════════════════════
MIN_TURNOVER_LAKHS = _float("MIN_TURNOVER_LAKHS", "50")
MIN_PRICE = _float("MIN_PRICE", "20")
MAX_PRICE = _float("MAX_PRICE", "10000")
MAX_CANDIDATES = _int("MAX_CANDIDATES", "400")

# ETF / index-fund ban — FIXED to avoid substring collisions
# (old list had 'BHARAT' and 'GILT'/'LIQUID' as raw substrings, which nuked
# real stocks like BHARATFORG / BHARATGEAR). Now exact-token match against
# the symbol split on non-alnum, plus safe suffix checks.
_ETF_EXACT_TOKENS = {
    "ETF", "BEES", "NIFTYBEES", "JUNIORBEES", "LIQUIDBEES", "GOLDBEES",
    "GSEC", "GILT", "BOND", "LIQUIDCASE", "CPSE", "MAFSETF",
}
_ETF_SAFE_SUFFIXES = ("ETF", "BEES")


def is_etf_or_index(symbol: str) -> bool:
    sym = symbol.upper().strip()
    if sym in _ETF_EXACT_TOKENS:
        return True
    if sym.endswith(_ETF_SAFE_SUFFIXES):
        return True
    # NIFTY as a whole-token prefix only (NIFTYBEES, NIFTY50EQ etc.), not
    # a name that merely contains it — but there are few legitimate NSE
    # equity tickers starting with NIFTY, so prefix match is safe here.
    if sym.startswith("NIFTY") and any(t in sym for t in ("BEES", "ETF", "CASE")):
        return True
    return False


# ══════════════════════════════════════════════════════════════════════════
# MACRO REGIME
# ══════════════════════════════════════════════════════════════════════════
ATR_PERIOD = _int("ATR_PERIOD", "14")
ATR_MULT_TREND = _float("ATR_MULT_TREND", "1.5")
ATR_MULT_CHOP = _float("ATR_MULT_CHOP", "2.0")
ATR_MULT_BUNKER = _float("ATR_MULT_BUNKER", "2.5")
VIX_TREND_MAX = _float("VIX_TREND_MAX", "15")     # Pine: i_vix_chop
VIX_CHOP_MAX = _float("VIX_CHOP_MAX", "22")       # Pine: i_vix_level
NIFTY_MASSACRE_PCT = _float("NIFTY_MASSACRE_PCT", "-3.0")  # Pine: i_massacre

# ══════════════════════════════════════════════════════════════════════════
# WHALE / ORDER FLOW
# ══════════════════════════════════════════════════════════════════════════
WHALE_DELIVERY_PCT = _float("WHALE_DELIVERY_PCT", "65")
WHALE_VOL_MULT = _float("WHALE_VOL_MULT", "1.5")

# ══════════════════════════════════════════════════════════════════════════
# ALT-DATA / LLM GATES
# ══════════════════════════════════════════════════════════════════════════
ALT_DATA_ENABLED = _bool("ALT_DATA_ENABLED", "true")
ALT_DATA_MATCH_SIM = _float("ALT_DATA_MATCH_SIM", "0.72")

# ══════════════════════════════════════════════════════════════════════════
# CONVICTION / LANE THRESHOLDS (Sniper)
# ══════════════════════════════════════════════════════════════════════════
CONVICTION_RERANK = _bool("CONVICTION_RERANK", "true")
CONV_REQUIRE_CATALYST = _bool("CONV_REQUIRE_CATALYST", "true")
CONV_RS_CATALYST_FLOOR = _float("CONV_RS_CATALYST_FLOOR", "85")
CONV_RS_MIN_PCT = _float("CONV_RS_MIN_PCT", "70")
CONV_LANE_FORTRESS_MIN = _int("CONV_LANE_FORTRESS_MIN", "120")
CONV_LANE_APEX_MIN = _int("CONV_LANE_APEX_MIN", "60")
CONV_LANE_FUSED_MIN = _int("CONV_LANE_FUSED_MIN", "70")

LANE_FORTRESS_MIN = _int("LANE_FORTRESS_MIN", "100")
LANE_APEX_MIN = _int("LANE_APEX_MIN", "55")
LANE_FUSED_MIN = _int("LANE_FUSED_MIN", "60")

APEX_MIN_SCORE = _int("APEX_MIN_SCORE", "48")
APEX_TOP_N = _int("APEX_TOP_N", "5")
CONFIDENCE_MIN = _float("CONFIDENCE_MIN", "0.35")
CONFIDENCE_STD_MAX = _float("CONFIDENCE_STD_MAX", "0.30")

# ══════════════════════════════════════════════════════════════════════════
# PLEDGE / QUALITY GATES
# ══════════════════════════════════════════════════════════════════════════
PLEDGE_GATE_ENABLED = _bool("PLEDGE_GATE_ENABLED", "true")
PLEDGE_GATE_MAX_PCT = _float("PLEDGE_GATE_MAX_PCT", "50.0")

QUALITY_GATE_ENABLED = _bool("QUALITY_GATE_ENABLED", "true")
QUALITY_OCF_PAT_MIN = _float("QUALITY_OCF_PAT_MIN", "0.7")
QUALITY_ROCE_MIN_PCT = _float("QUALITY_ROCE_MIN_PCT", "12.0")
QUALITY_DEBTOR_MAX = _float("QUALITY_DEBTOR_MAX", "0.25")

# ══════════════════════════════════════════════════════════════════════════
# SECTOR VELOCITY
# ══════════════════════════════════════════════════════════════════════════
SECTOR_VELOCITY_ENABLED = _bool("SECTOR_VELOCITY_ENABLED", "true")
SECTOR_VELOCITY_PENALTY = _float("SECTOR_VELOCITY_PENALTY", "10.0")

# ══════════════════════════════════════════════════════════════════════════
# INCUBATOR — RUBBLE / EPS / SPONGE GATES
# ══════════════════════════════════════════════════════════════════════════
RUBBLE_DISCOUNT_MIN = _float("RUBBLE_DISCOUNT_MIN", "0.30")
STAGE1_BOX_WIDTH_MAX = _float("STAGE1_BOX_WIDTH_MAX", "0.35")
EPS_ACCEL_PCT_MIN = _float("EPS_ACCEL_PCT_MIN", "0.25")
SPONGE_DRY_VOL_PCT = _float("SPONGE_DRY_VOL_PCT", "0.60")
SPONGE_WET_VOL_PCT = _float("SPONGE_WET_VOL_PCT", "1.50")
STONE_SCORE_MIN = _int("STONE_SCORE_MIN", "45")
TOP_N_STONES = _int("TOP_N_STONES", "10")

INDEX_ALPHA_ENABLED = _bool("INDEX_ALPHA_ENABLED", "true")
INDEX_ALPHA_UNIVERSE_N = _int("INDEX_ALPHA_UNIVERSE_N", "300")
BLOCK_DEAL_ENABLED = _bool("BLOCK_DEAL_ENABLED", "true")

# ══════════════════════════════════════════════════════════════════════════
# ★ THE BRIDGE — PEARL WATCHLIST / IGNITION DETECTION ★
# This is the new unified logic that did not exist in any of the 3 originals.
# ══════════════════════════════════════════════════════════════════════════

# How long a symbol stays on the active watchlist after Incubator adds it,
# before it's considered stale and dropped (unless Incubator re-confirms it).
PEARL_WATCHLIST_TTL_DAYS = _int("PEARL_WATCHLIST_TTL_DAYS", "90")

# Ignition detection — the technical signature that says "the pearl is moving"
IGNITION_BOX_BREAKOUT_PCT = _float("IGNITION_BOX_BREAKOUT_PCT", "0.02")   # close > box_high * 1.02
IGNITION_VOL_MULT = _float("IGNITION_VOL_MULT", "1.8")                    # vol >= 1.8x ADV20
IGNITION_MA50_RECLAIM = _bool("IGNITION_MA50_RECLAIM", "true")            # close > MA50 required

# Pedigree bonus — added to a Sniper candidate's fused score IF it is on the
# pearl watchlist AND shows ignition. This is the "value base + momentum
# trigger" compounding effect: a pearl that ignites should outrank a cold
# scan hit at the same raw fused score.
PEARL_PEDIGREE_BONUS = _float("PEARL_PEDIGREE_BONUS", "12.0")
PEARL_IGNITION_BONUS = _float("PEARL_IGNITION_BONUS", "8.0")
# Total possible bonus = 20 pts on a 0-100 fused scale — meaningful but
# capped so a stale/no-ignition pearl can't outrank a genuinely strong
# cold-scan signal on pedigree alone.

# ══════════════════════════════════════════════════════════════════════════
# UNIFIED CONVICTION SCALE (0-100) — replaces 3 incompatible scoring systems
# ══════════════════════════════════════════════════════════════════════════
# thesis(Incubator, 30) + trigger(Sniper, 40) + macro(shared, 20) + entry(Pine, 10)
CONVICTION_W_THESIS = _float("CONVICTION_W_THESIS", "30.0")
CONVICTION_W_TRIGGER = _float("CONVICTION_W_TRIGGER", "40.0")
CONVICTION_W_MACRO = _float("CONVICTION_W_MACRO", "20.0")
CONVICTION_W_ENTRY = _float("CONVICTION_W_ENTRY", "10.0")

# ══════════════════════════════════════════════════════════════════════════
# NSE SESSION / DATA CASCADE
# ══════════════════════════════════════════════════════════════════════════
# Tier order preserved from sniper_v7 (the more battle-tested implementation):
#   1. NSE archives (3-step CF session + Akamai + curl_cffi)
#   2. Addon Finance API (if key present)
#   3. Google Sheets BHAVCOPY tab (manual/previous-run extract)
#   4. yfinance small universe (last resort)
# This cascade is now shared by ALL THREE entrypoints via core/nse_data.py,
# so Incubator gets the same resilience Sniper had, instead of its own
# thinner NSE-first/hardcoded-fallback path.
NSE_SESSION_TTL = _int("NSE_SESSION_TTL", "300")

_NSE_HOLIDAYS_2025_2026 = {
    "2025-01-26", "2025-02-19", "2025-03-25", "2025-03-31",
    "2025-04-02", "2025-04-06", "2025-04-10", "2025-04-14",
    "2025-04-17", "2025-04-18", "2025-05-01", "2025-08-15",
    "2025-08-27", "2025-10-02", "2025-10-20", "2025-10-21",
    "2025-10-22", "2025-11-05", "2025-11-11", "2025-11-26", "2025-12-25",
    "2026-01-26", "2026-02-19", "2026-03-25", "2026-03-31",
    "2026-04-02", "2026-04-06", "2026-04-10", "2026-04-14",
    "2026-04-17", "2026-05-01", "2026-06-19", "2026-08-15",
    "2026-08-27", "2026-10-02", "2026-10-20", "2026-10-21",
    "2026-11-05", "2026-11-27", "2026-12-25",
}


def nse_holidays() -> set:
    return _NSE_HOLIDAYS_2025_2026


# ══════════════════════════════════════════════════════════════════════════
# SHARIAH — SINGLE ENGINE, FAIL-SAFE EVERYWHERE
# ══════════════════════════════════════════════════════════════════════════
# BUG FIX: old incubator's dynamic_shariah_audit() failed OPEN on LLM parse
# error ("Passed fallback (AI parse error)" -> True). Old sniper's
# halal_l1_veto()/halal_ai_screen() failed CLOSED (HALAL_LIST down -> reject
# everything). These are inconsistent philosophies for the same compliance
# gate. Fixed: fail-safe (reject) is now the ONLY behavior, everywhere,
# on any of: sheet unavailable, LLM unavailable, LLM parse error, timeout.
SHARIAH_FAIL_SAFE = True  # not overridable via env — this is a policy, not a tuning knob

HARAM_TICKER_KEYWORDS = (
    "BANK", "FINANCE", "INSURE", "CAPITAL", "CREDIT",
    "INVEST", "MUTUAL", "HOLDING", "NBFC", "LEASING",
)
HARAM_SECTOR_TERMS = (
    "BANK", "FINANCIAL", "INSURANCE", "NBFC", "BREWERY", "DISTILLERY",
    "TOBACCO", "CASINO", "GAMBLING", "LIQUOR", "ALCOHOL",
)

# ══════════════════════════════════════════════════════════════════════════
# v1.1 ADDITIONS — full port constants
# ══════════════════════════════════════════════════════════════════════════
OUTCOME_TIMEOUT_DAYS = _int("OUTCOME_TIMEOUT_DAYS", "20")
NSE_CIRCUIT_MAX_FAILS = _int("NSE_CIRCUIT_MAX_FAILS", "5")
CONFIDENCE_PENALTY_FLOOR = _float("CONFIDENCE_PENALTY_FLOOR", "0.25")
RS_LOOKBACK_DAYS = _int("RS_LOOKBACK_DAYS", "63")
META_MIN_TRAINING_ROWS = _int("META_MIN_TRAINING_ROWS", "30")
META_VETO_PWIN = _float("META_VETO_PWIN", "0.35")
INTEL_LOOKBACK_DAYS = _int("INTEL_LOOKBACK_DAYS", "90")
CATALYST_KEYWORDS = ("ORDER", "CONTRACT", "WIN", "ACQUISITION", "EXPANSION",
                     "CAPACITY", "APPROVAL", "PATENT", "LAUNCH", "PARTNERSHIP",
                     "BUYBACK", "PREFERENTIAL")
