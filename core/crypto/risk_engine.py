"""
FORTRESS_CRYPTO — core/crypto/risk_engine.py
══════════════════════════════════════════════════════════════════════════════
FALSE PEARL DETECTION — directly answers your mentor's worked example:
a token can look bullish (volume +300%, price +40%, social +800%) while
the contract itself tells a different story (mint authority live, thin
liquidity, top wallets moving to exchanges, unlock imminent). This module
reads that second story.

Uses GoPlus Security's free public Token Security API (no key required:
https://api.gopluslabs.io/api/v1/token_security/{chain_id}). EVM chains
ONLY (Ethereum/BSC/Polygon) — same honest scope as core/crypto/onchain.py,
because that's what free-tier contract security data actually covers.
Non-EVM tokens get risk=None (neutral — not silently treated as safe).

BUILT AS WARNING-ONLY, NOT A VETO (per explicit choice) — flags surface
in every alert so a human makes the final call. This module never removes
a candidate from the alert list; it only adds information to it.

Checks performed (each mapped to your mentor's example):
  - is_mintable            -> "contract owner can mint" more supply
  - is_honeypot            -> can't sell after buying (fatal, not cosmetic)
  - buy_tax / sell_tax     -> hidden fee structure that erodes any edge
  - lp_holder_count/locked -> "liquidity only $Xk" / can be pulled
  - owner_change_balance   -> owner can arbitrarily alter holder balances
  - is_open_source         -> unverified contracts hide all of the above
"""
from __future__ import annotations
import logging
import time
from typing import Dict, Optional

import requests

log = logging.getLogger("fortress.crypto.risk")

_session = requests.Session()
_GOPLUS_BASE = "https://api.gopluslabs.io/api/v1/token_security"
_CHAIN_ID_MAP = {"ethereum": "1", "binance-smart-chain": "56", "polygon-pos": "137", "base": "8453"}

_last_call_ts = [0.0]
_MIN_INTERVAL = 1.0  # GoPlus free tier is generous but still finite


def _throttle() -> None:
    elapsed = time.monotonic() - _last_call_ts[0]
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_call_ts[0] = time.monotonic()


def fetch_token_security(platforms: Dict[str, str]) -> Optional[dict]:
    """Returns None if no supported EVM chain/contract found, or on
    failure — fail-safe: caller must treat None as 'unchecked', never as
    'confirmed safe'. Checks chains in the same priority order as
    onchain.py for consistency."""
    for chain, chain_id in _CHAIN_ID_MAP.items():
        addr = platforms.get(chain)
        if not addr:
            continue
        _throttle()
        try:
            resp = _session.get(f"{_GOPLUS_BASE}/{chain_id}",
                                 params={"contract_addresses": addr}, timeout=15)
            if resp.status_code != 200:
                continue
            data = resp.json()
            result = (data.get("result") or {}).get(addr.lower())
            if not result:
                continue
            return {"chain": chain, "raw": result}
        except Exception as e:
            log.debug(f"GoPlus fetch error ({chain}): {e}")
            continue
    return None


def _pct(v) -> Optional[float]:
    try:
        return round(float(v) * 100, 1) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def assess_false_pearl_risk(platforms: Dict[str, str]) -> dict:
    """
    Returns:
      {"available": bool, "flags": [str, ...], "severity": "CLEAN"|"CAUTION"|"HIGH_RISK",
       "buy_tax_pct": float|None, "sell_tax_pct": float|None,
       "lp_locked_pct": float|None, "detail": str}

    severity is informational, NOT a veto (warning-only, per explicit
    choice) — "HIGH_RISK" still gets alerted, just loudly labeled.
    """
    security = fetch_token_security(platforms)
    if security is None:
        return {"available": False, "flags": [], "severity": "UNCHECKED",
                "buy_tax_pct": None, "sell_tax_pct": None, "lp_locked_pct": None,
                "detail": "No EVM contract found or GoPlus check failed — unverified, not confirmed safe"}

    r = security["raw"]
    flags = []

    if r.get("is_mintable") == "1":
        flags.append("⚠️ MINTABLE — owner can create new supply")
    if r.get("is_honeypot") == "1":
        flags.append("🚨 HONEYPOT — buyers may be unable to sell")
    if r.get("owner_change_balance") == "1":
        flags.append("⚠️ owner can arbitrarily change holder balances")
    if r.get("is_open_source") == "0":
        flags.append("⚠️ contract source unverified")
    if r.get("cannot_sell_all") == "1":
        flags.append("⚠️ cannot sell full balance in one transaction")

    buy_tax = _pct(r.get("buy_tax"))
    sell_tax = _pct(r.get("sell_tax"))
    if buy_tax is not None and buy_tax > 10:
        flags.append(f"⚠️ high buy tax ({buy_tax}%)")
    if sell_tax is not None and sell_tax > 10:
        flags.append(f"⚠️ high sell tax ({sell_tax}%)")

    lp_locked_pct = None
    lp_holders = r.get("lp_holders") or []
    total_lp = sum(float(h.get("percent", 0)) for h in lp_holders) if lp_holders else 0
    locked_lp = sum(float(h.get("percent", 0)) for h in lp_holders
                     if h.get("is_locked") == 1) if lp_holders else 0
    if lp_holders:
        lp_locked_pct = round(100.0 * locked_lp / total_lp, 1) if total_lp > 0 else 0.0
        if lp_locked_pct < 50:
            flags.append(f"⚠️ only {lp_locked_pct}% of liquidity locked")

    if r.get("is_honeypot") == "1" or (buy_tax and buy_tax > 25) or (sell_tax and sell_tax > 25):
        severity = "HIGH_RISK"
    elif flags:
        severity = "CAUTION"
    else:
        severity = "CLEAN"

    return {"available": True, "flags": flags, "severity": severity,
            "buy_tax_pct": buy_tax, "sell_tax_pct": sell_tax,
            "lp_locked_pct": lp_locked_pct,
            "detail": f"{len(flags)} flag(s) on {security['chain']}" if flags else "no red flags found"}
