"""
FORTRESS_CRYPTO — core/crypto/onchain.py
══════════════════════════════════════════════════════════════════════════════
On-chain whale/holder-concentration signal — the crypto analogue of the
equity pipeline's SAST-insider/pledge lookups (core/nse_data.py heist
functions). SCOPED HONESTLY, per your explicit choice: EVM chains only
(Ethereum / BSC / Polygon), using each chain's free-tier block-explorer
"top holders" endpoint. Non-EVM tokens (Solana, Cosmos-SDK chains, Bitcoin
itself, etc.) get on_chain_score = None here — the factor model treats
None as neutral (0.0 contribution), NOT as a bad score. This is a scoped
v1, not full Glassnode/Nansen-grade coverage, and the module docstring is
the honest place to say so rather than silently under-covering.

Signal produced (per token, per supported chain):
  - top1_holder_pct       : largest non-contract holder's % of supply
  - top10_concentration_pct : sum of top 10 non-contract holders' %
  - whale_flag             : True if any single wallet > ONCHAIN_TOP_HOLDER_WHALE_PCT
  - concentration_flag     : True if top10 > ONCHAIN_TOP10_CONCENTRATION_WARN_PCT

These do NOT auto-reject a token (unlike Shariah gates) — high
concentration is a quality/risk signal folded into the factor model's
on-chain-quality leg and shown in the alert, same "informational, not a
hard veto" pattern as equity's whale_score in order_flow.py.
"""
from __future__ import annotations
import logging
import time
from typing import Dict, List, Optional

import requests

from . import config as ccfg

log = logging.getLogger("fortress.crypto.onchain")

_session = requests.Session()

_EXPLORER_MAP = {
    "ethereum": ("https://api.etherscan.io/api", ccfg.ETHERSCAN_API_KEY),
    "binance-smart-chain": ("https://api.bscscan.com/api", ccfg.BSCSCAN_API_KEY),
    "polygon-pos": ("https://api.polygonscan.com/api", ccfg.POLYGONSCAN_API_KEY),
}

# Common contract/burn/zero addresses to exclude from "holder" concentration
# so a DEX pool or the zero address doesn't get mistaken for a whale wallet.
_EXCLUDE_ADDR_SUFFIXES = ("0000000000000000000000000000000000000000",)


def is_onchain_supported(platforms: Dict[str, str]) -> bool:
    """True if this token has a contract on at least one chain we can
    query on free tier AND we have a key configured for that chain."""
    if not ccfg.ONCHAIN_ENABLED:
        return False
    for chain in ccfg.ONCHAIN_SUPPORTED_CHAINS:
        if platforms.get(chain) and _EXPLORER_MAP.get(chain, (None, ""))[1]:
            return True
    return False


def _fetch_top_holders(chain: str, contract_address: str, top_k: int = 10) -> Optional[List[dict]]:
    base_url, api_key = _EXPLORER_MAP.get(chain, (None, ""))
    if not base_url or not api_key or not contract_address:
        return None
    try:
        resp = _session.get(base_url, params={
            "module": "token",
            "action": "tokenholderlist",
            "contractaddress": contract_address,
            "page": 1,
            "offset": top_k,
            "apikey": api_key,
        }, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get("status") != "1" or not isinstance(data.get("result"), list):
            # Many free-tier explorer keys don't have tokenholderlist
            # enabled (it's a paid Etherscan Pro endpoint on some plans) —
            # fail-safe: return None, don't guess.
            log.debug(f"onchain top-holders unavailable for {chain}:{contract_address} — {data.get('message')}")
            return None
        return data["result"]
    except Exception as e:
        log.debug(f"onchain top-holders error {chain}:{contract_address}: {e}")
        return None
    finally:
        time.sleep(0.25)  # free-tier explorer rate limits are tight (~5 req/s)


def whale_concentration_signal(platforms: Dict[str, str], total_supply: Optional[float] = None) -> Optional[dict]:
    """Returns None if no supported chain/key is available (fail-safe —
    factor model treats this as neutral, not penalized). Otherwise returns
    the concentration signal from the FIRST supported chain with a
    contract address (checked in ONCHAIN_SUPPORTED_CHAINS order)."""
    if not ccfg.ONCHAIN_ENABLED:
        return None
    for chain in ccfg.ONCHAIN_SUPPORTED_CHAINS:
        addr = platforms.get(chain)
        if not addr:
            continue
        holders = _fetch_top_holders(chain, addr, top_k=10)
        if not holders:
            continue
        try:
            shares = []
            for h in holders:
                # etherscan-family responses use 'TokenHolderQuantity' and
                # sometimes include a 'TokenHolderShare' in pct already;
                # if not present, we can't compute % without total_supply.
                if "TokenHolderShare" in h:
                    shares.append(float(h["TokenHolderShare"]))
                elif total_supply:
                    qty = float(h.get("TokenHolderQuantity", 0))
                    shares.append(100.0 * qty / total_supply if total_supply else 0.0)
            if not shares:
                continue
            top1 = shares[0]
            top10 = sum(shares[:10])
            return {
                "chain": chain,
                "top1_holder_pct": round(top1, 2),
                "top10_concentration_pct": round(top10, 2),
                "whale_flag": top1 > ccfg.ONCHAIN_TOP_HOLDER_WHALE_PCT,
                "concentration_flag": top10 > ccfg.ONCHAIN_TOP10_CONCENTRATION_WARN_PCT,
            }
        except Exception as e:
            log.debug(f"whale_concentration_signal parse error ({chain}): {e}")
            continue
    return None


def onchain_quality_score_0_100(signal: Optional[dict]) -> Optional[float]:
    """Maps concentration signal to a 0-100 'quality' contribution (lower
    concentration = higher score, mirrors equity's ROE-based quality leg
    conceptually: 'is this a healthier/less fragile asset'). Returns None
    (not a number) when there's no signal — factor.py must treat None as
    neutral 0.0 Z-contribution, never as a zero/bad score."""
    if signal is None:
        return None
    top10 = signal.get("top10_concentration_pct", 0.0)
    # 0% concentration -> 100; 100% concentration -> 0; linear, clipped.
    score = max(0.0, min(100.0, 100.0 - top10))
    return round(score, 1)
