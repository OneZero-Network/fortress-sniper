"""
FORTRESS_CRYPTO — core/crypto/shariah_crypto.py
══════════════════════════════════════════════════════════════════════════════
Crypto Shariah screen. THIS IS A DOCUMENTED POSITION AMONG GENUINE
SCHOLARLY DISAGREEMENT, not a settled ruling — unlike equity Shariah
screening (which has decades of standardized AAOIFI debt-ratio practice
to draw on), crypto halal/haram questions are actively contested among
qualified scholars, particularly on staking/PoS yield. Where the equity
engine (core/shariah.py) runs a quantitative debt/equity screen against
a balance sheet, crypto assets HAVE no balance sheet — most tokens have
no issuer, no equity, no debt. So this screen is necessarily categorical
(what TYPE of asset/mechanism is this) rather than ratio-based.

Per your explicit choices:
  - Staking / PoS-yield / liquid-staking-derivative tokens: REJECTED
    OUTRIGHT (SHARIAH_REJECT_STAKING_TOKENS=True). This sidesteps the
    contested "is staking riba" debate entirely by excluding the category,
    rather than picking a side in an unsettled scholarly disagreement.
  - Halal-list carried over as a Sheets tab (CRYPTO_HALAL_LIST), same
    override pattern as equity's HALAL_LIST — you can manually whitelist
    a specific token regardless of category flags if you've done your own
    research and disagree with the categorical screen.

FAIL-SAFE POLICY (same non-negotiable philosophy as core/shariah.py):
any degraded path — CoinGecko categories unavailable, timeout, parse
error, halal-list sheet unreachable — REJECTS. Never fails open.

Categorical rejects (config-gated, see core/crypto/config.py):
  1. Privacy coins (symbol-list based — CoinGecko doesn't reliably tag
     "privacy-coins" as a category for all of them, so this is a maintained
     symbol list, same pattern-limitation as equity's ticker-keyword layer).
  2. Gambling / prediction-market tokens (category-tag based).
  3. Staking / liquid-staking-derivative tokens (category-tag AND symbol
     list — deliberately redundant since this is your firmest instruction).
  4. Lending/yield-farming/yield-aggregator protocol tokens whose PRIMARY
     function is interest-bearing yield generation (category-tag based).
  5. Algorithmic/undercollateralized stablecoins (excess gharar per several
     Shariah boards' rulings on the 2022 Terra/UST-style collapse risk).
"""
from __future__ import annotations
import logging
from typing import List, Optional

from . import config as ccfg

log = logging.getLogger("fortress.crypto.shariah")


def screen_token(symbol: str, categories: Optional[List[str]],
                  halal_list_override: Optional[set] = None) -> dict:
    """
    Returns {"compliant": bool, "reason": str, "category_flags": [...]}.

    FAIL-SAFE: categories=None (fetch failed) -> reject, unless the symbol
    is on the manually-curated halal_list_override (mirrors equity's
    HALAL_LIST sheet acting as a trusted manual override of automated
    checks).
    """
    sym = symbol.upper().strip()

    if halal_list_override and sym in halal_list_override:
        return {"compliant": True, "reason": "manual halal-list override", "category_flags": []}

    if categories is None:
        return {"compliant": False, "reason": "category data unavailable — fail-safe reject",
                "category_flags": []}

    cats = [c.lower() for c in categories]
    flags = []

    if sym in ccfg._PRIVACY_COIN_SYMBOLS and ccfg.SHARIAH_REJECT_PRIVACY_COINS:
        flags.append("privacy_coin")

    if any(any(t in c for t in ccfg._GAMBLING_PREDICTION_CATEGORY_TERMS) for c in cats) \
            and ccfg.SHARIAH_REJECT_GAMBLING_PREDICTION:
        flags.append("gambling_or_prediction_market")

    if ccfg.SHARIAH_REJECT_STAKING_TOKENS and any(
            any(t in c for t in ccfg._STAKING_CATEGORY_TERMS) for c in cats):
        flags.append("staking_or_liquid_staking_derivative")

    if any(any(t in c for t in ccfg._LENDING_CATEGORY_TERMS) for c in cats) \
            and ccfg.SHARIAH_REJECT_LENDING_YIELD_TOKENS:
        flags.append("lending_or_yield_protocol_token")

    if ccfg.SHARIAH_REJECT_ALGO_STABLECOINS and "algorithmic-stablecoins" in cats:
        flags.append("algorithmic_stablecoin")

    if flags:
        return {"compliant": False, "reason": f"categorical reject: {', '.join(flags)}",
                "category_flags": flags}
    return {"compliant": True, "reason": "no categorical reject triggered", "category_flags": []}
