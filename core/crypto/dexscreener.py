"""
FORTRESS_CRYPTO — core/crypto/dexscreener.py
══════════════════════════════════════════════════════════════════════════════
v4.5 — Base DEX Discovery v1. A SECOND candidate source alongside the
existing CoinGecko/liquid-asset universe, per the explicit architecture:
"Base should be a new source of candidates, not a new scoring system."
DEX candidates found here are adapted into the SAME coin_snapshot shape
the existing scanner already produces, then flow through the unchanged
pearl_score.compute_pearl_score() — no parallel scoring logic.

LICENSING: DexScreener's API terms explicitly permit both commercial and
non-commercial use (docs.dexscreener.com/api/api-terms-and-conditions).
The one restriction is building something whose PRIMARY PURPOSE competes
directly with DexScreener's own product (a token/pair explorer).
Fortress's primary purpose is a multi-source Pearl detection system —
DEX data is one input among several (CoinGecko, whale, news), not a
pair-browsing product. This is a plain reading of the current terms,
not legal advice — worth a final check before any public commercial
launch, but the discovery-source use case here is squarely the kind of
integration the terms describe as permitted.

DELIBERATELY NOT USING DexScreener's own "Trending Score" — per explicit
instruction, that would mean outsourcing discovery judgment to another
ranking algorithm, and their own docs note boost activity can inflate
visibility as a confounder, not organic demand. This module uses the
underlying raw data (liquidity, volume, transactions, buy/sell flow,
price-change windows) directly.

THE FUNNEL (5 stages, matching the explicit architecture):
  1. Discovery  — fetch_boosted_base_tokens() + fetch_pair_data()
  2. Viability   — apply_viability_filters()
  3. Momentum    — compute_flow_signals()
  4. False-Pearl — NOT YET IMPLEMENTED (see honest gap note below)
  5. Pearl engine — adapt_to_coin_snapshot() hands off to the existing,
     unchanged pearl_score.compute_pearl_score()

HONEST GAP, stated directly: Stage 4 (honeypot / mint-authority /
holder-concentration checks) is NOT built in this pass. The existing
risk_engine.py's False-Pearl check is built around CoinGecko-known
coins with GoPlus-style checks tied to a coin_id — arbitrary DEX pair
addresses need a different, not-yet-built integration. Per this gap,
DEX candidates are surfaced under a SEPARATE 🧭 BASE RADAR label,
explicitly marked as not yet having passed a false-pearl check —
never labeled PEARL CANDIDATE or fed into the tier system until that
gap is closed.
"""
from __future__ import annotations
import logging
import time
from typing import Optional, List

import requests

log = logging.getLogger("fortress.crypto.dexscreener")

DEXSCREENER_BASE = "https://api.dexscreener.com"
_last_call_ts = [0.0]

# Stage 2 — viability floors. Deliberately conservative for a brand-new
# discovery source with no false-pearl protection yet.
MIN_LIQUIDITY_USD = 50_000
MIN_VOLUME_24H_USD = 50_000
MIN_TXNS_24H = 100


def _throttle() -> None:
    elapsed = time.monotonic() - _last_call_ts[0]
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)
    _last_call_ts[0] = time.monotonic()


def _get(path: str) -> Optional[dict]:
    _throttle()
    try:
        resp = requests.get(f"{DEXSCREENER_BASE}{path}", timeout=15)
        if resp.status_code == 200:
            return resp.json()
        log.warning(f"DexScreener {resp.status_code} for {path}")
        return None
    except Exception as e:
        log.warning(f"DexScreener request error ({path}): {e}")
        return None


def compute_pair_age_hours(pair: dict) -> Optional[float]:
    """v4.6 — fresh-pair detection. pairCreatedAt is epoch milliseconds.
    Answers the actual question your mentor's architecture needs: is
    this genuinely early (a few hours old) or already well-established
    (weeks old, just now getting boosted)?"""
    created_at_ms = pair.get("pairCreatedAt")
    if not created_at_ms:
        return None
    age_seconds = time.time() - (created_at_ms / 1000.0)
    return round(age_seconds / 3600.0, 1)


def compute_acceleration(pair: dict) -> dict:
    """v4.6 — volume and transaction ACCELERATION using DexScreener's own
    multi-window fields (m5/h1/h6/h24) — the same 'is this speeding up or
    just elevated' philosophy as the existing velocity engine, but built
    fresh here since DEX pairs don't have the daily OHLC history that
    engine relies on. Compares the most recent short window's RATE
    against the longer window's average rate — if 1h volume is running
    hotter than the 24h average would predict, that's genuine
    acceleration, not just 'volume happens to be high today.'"""
    vol = pair.get("volume") or {}
    txns = pair.get("txns") or {}

    vol_h1 = vol.get("h1") or 0
    vol_h24 = vol.get("h24") or 0
    expected_h1_if_steady = vol_h24 / 24.0 if vol_h24 else 0
    vol_accel_ratio = round(vol_h1 / expected_h1_if_steady, 2) if expected_h1_if_steady > 0 else None

    txns_h1 = ((txns.get("h1") or {}).get("buys") or 0) + ((txns.get("h1") or {}).get("sells") or 0)
    txns_h24 = ((txns.get("h24") or {}).get("buys") or 0) + ((txns.get("h24") or {}).get("sells") or 0)
    expected_h1_txns_if_steady = txns_h24 / 24.0 if txns_h24 else 0
    txn_accel_ratio = round(txns_h1 / expected_h1_txns_if_steady, 2) if expected_h1_txns_if_steady > 0 else None

    label = "NONE"
    if vol_accel_ratio is not None:
        if vol_accel_ratio >= 3:
            label = "ACCELERATING"
        elif vol_accel_ratio <= 0.3:
            label = "DECELERATING"
        else:
            label = "STEADY"

    return {"vol_accel_ratio": vol_accel_ratio, "txn_accel_ratio": txn_accel_ratio, "label": label}


def check_dex_security(pair: dict) -> dict:
    """v4.6 — REAL security gate, closing the gap left open in v4.5.
    Reuses risk_engine.assess_false_pearl_risk() directly — GoPlus
    natively covers Base (chain_id 8453, added to risk_engine.py's
    _CHAIN_ID_MAP), and DexScreener's baseToken.address IS the contract
    address GoPlus needs. No parallel security-checking logic built —
    same tested infrastructure the CoinGecko-sourced candidates use."""
    from . import risk_engine
    base_token = pair.get("baseToken") or {}
    address = base_token.get("address")
    if not address:
        return {"available": False, "flags": [], "severity": "UNCHECKED",
                "detail": "no contract address in pair data"}
    return risk_engine.assess_false_pearl_risk({"base": address})


def fetch_boosted_base_tokens(limit: int = 30) -> List[dict]:
    """Stage 1a — discovery seed. Uses the token-boosts endpoint (surfaces
    recently-active/promoted tokens across chains) filtered to Base.
    NOTE: boost activity itself is explicitly NOT used as a signal (see
    module docstring) — this is only used to generate a candidate LIST
    to then fetch real pair data for, same way the CoinGecko scanner
    uses market-cap rank purely to generate a candidate list."""
    data = _get("/token-boosts/latest/v1")
    if not data:
        return []
    tokens = data if isinstance(data, list) else data.get("tokens", [])
    base_tokens = [t for t in tokens if t.get("chainId") == "base"]
    return base_tokens[:limit]


def fetch_pair_data(token_address: str, chain: str = "base") -> Optional[dict]:
    """Stage 1b — for a candidate token address, fetch its actual pair
    data (liquidity, volume, txns, price-change windows). If a token has
    multiple pairs, returns the one with the highest liquidity."""
    data = _get(f"/latest/dex/tokens/{token_address}")
    if not data:
        return None
    pairs = data.get("pairs") or []
    base_pairs = [p for p in pairs if p.get("chainId") == chain]
    if not base_pairs:
        return None
    return max(base_pairs, key=lambda p: (p.get("liquidity") or {}).get("usd", 0) or 0)


def apply_viability_filters(pair: dict) -> dict:
    """Stage 2 — reject: low liquidity, low volume, too few transactions.
    Returns {"passes": bool, "reasons": [...]} — reasons list is always
    populated (even on pass, showing what was checked), never a bare
    True/False with no explanation."""
    liquidity = (pair.get("liquidity") or {}).get("usd") or 0
    volume_24h = (pair.get("volume") or {}).get("h24") or 0
    txns_24h_data = (pair.get("txns") or {}).get("h24") or {}
    txns_24h = (txns_24h_data.get("buys") or 0) + (txns_24h_data.get("sells") or 0)

    reasons = []
    if liquidity < MIN_LIQUIDITY_USD:
        reasons.append(f"liquidity ${liquidity:,.0f} below ${MIN_LIQUIDITY_USD:,} floor")
    if volume_24h < MIN_VOLUME_24H_USD:
        reasons.append(f"24h volume ${volume_24h:,.0f} below ${MIN_VOLUME_24H_USD:,} floor")
    if txns_24h < MIN_TXNS_24H:
        reasons.append(f"{txns_24h} txns/24h below {MIN_TXNS_24H} floor")

    return {"passes": len(reasons) == 0, "reasons": reasons or ["passes all viability floors"],
            "liquidity_usd": liquidity, "volume_24h_usd": volume_24h, "txns_24h": txns_24h}


def compute_flow_signals(pair: dict) -> dict:
    """Stage 3 — momentum/flow, using ONLY data DexScreener actually
    provides (no historical baseline exists for brand-new pairs, so this
    uses the multi-window price-change fields DexScreener already
    returns, same acceleration philosophy as the existing velocity
    engine). Buy/sell imbalance is genuinely new information the main
    CoinGecko scanner never had access to."""
    txns_24h = (pair.get("txns") or {}).get("h24") or {}
    buys = txns_24h.get("buys") or 0
    sells = txns_24h.get("sells") or 0
    total = buys + sells
    buy_ratio = round(buys / total, 3) if total > 0 else None

    price_change = pair.get("priceChange") or {}
    pct_1h = price_change.get("h1")
    pct_6h = price_change.get("h6")
    pct_24h = price_change.get("h24")

    flow_label = "NONE"
    if buy_ratio is not None:
        if buy_ratio >= 0.65:
            flow_label = "STRONG_BUY_PRESSURE"
        elif buy_ratio <= 0.35:
            flow_label = "STRONG_SELL_PRESSURE"
        else:
            flow_label = "BALANCED"

    return {"buy_ratio": buy_ratio, "buys": buys, "sells": sells, "flow_label": flow_label,
            "pct_1h": pct_1h, "pct_6h": pct_6h, "pct_24h": pct_24h}


def adapt_to_coin_snapshot(pair: dict) -> dict:
    """Adapts a DexScreener pair into the SAME coin_snapshot shape the
    existing CoinGecko scanner produces — this is what lets DEX
    candidates flow through the UNCHANGED pearl_score.compute_pearl_score()
    instead of needing parallel scoring logic. Fields DexScreener can't
    provide (pct_7d, pct_30d — pairs are often too new to have that
    history) are correctly left None, gracefully excluded by the
    existing 'don't fabricate missing components' design."""
    base_token = pair.get("baseToken") or {}
    liquidity = (pair.get("liquidity") or {}).get("usd") or 0
    volume_24h = (pair.get("volume") or {}).get("h24") or 0
    price_change = pair.get("priceChange") or {}
    return {
        "id": None,  # no CoinGecko id — DEX-native
        "symbol": (base_token.get("symbol") or "").upper(),
        "name": base_token.get("name"),
        "market_cap": pair.get("fdv") or pair.get("marketCap") or 0,
        "market_cap_rank": None,
        "volume_24h": volume_24h,
        "price": float(pair.get("priceUsd") or 0),
        "pct_24h": price_change.get("h24"),
        "pct_7d": None,   # honestly unavailable for most DEX pairs — not fabricated
        "pct_30d": None,  # honestly unavailable for most DEX pairs — not fabricated
        "pair_address": pair.get("pairAddress"),
        "dex_id": pair.get("dexId"),
        "pair_created_at": pair.get("pairCreatedAt"),
    }


def classify_dex_early_move(viability: dict, flow: dict, accel: dict, pair_age_hours: Optional[float],
                             security: dict, max_pair_age_hours: float = 72.0) -> dict:
    """v4.7 — 🚨 DEX EARLY MOVE. A STRICTER, all-conditions-must-converge
    classification, per explicit instruction: 'don't make every Base
    token appear in Telegram.' Requires ALL of: fresh pair, sufficient
    liquidity (already gated by viability), accelerating volume,
    accelerating transactions, buy pressure, meaningful price
    acceleration, and clean security. Missing even one condition means
    NOT an early move — still logged/tracked, just not surfaced
    prominently."""
    reasons_met = []
    reasons_missing = []

    is_fresh = pair_age_hours is not None and pair_age_hours <= max_pair_age_hours
    (reasons_met if is_fresh else reasons_missing).append("fresh pair" if is_fresh else "pair not fresh enough")

    vol_accelerating = accel.get("label") == "ACCELERATING"
    (reasons_met if vol_accelerating else reasons_missing).append(
        "volume accelerating" if vol_accelerating else "volume not accelerating")

    txn_accelerating = accel.get("txn_accel_ratio") is not None and accel["txn_accel_ratio"] >= 2.0
    (reasons_met if txn_accelerating else reasons_missing).append(
        "transactions accelerating" if txn_accelerating else "transactions not accelerating")

    buy_pressure = flow.get("flow_label") == "STRONG_BUY_PRESSURE"
    (reasons_met if buy_pressure else reasons_missing).append(
        "strong buy pressure" if buy_pressure else "no strong buy pressure")

    price_accelerating = flow.get("pct_1h") is not None and flow["pct_1h"] >= 3.0
    (reasons_met if price_accelerating else reasons_missing).append(
        "price accelerating" if price_accelerating else "price not accelerating")

    security_clean = security.get("severity") == "CLEAN"
    (reasons_met if security_clean else reasons_missing).append(
        "security clean" if security_clean else "security not confirmed clean")

    all_converge = viability["passes"] and is_fresh and vol_accelerating and txn_accelerating and buy_pressure and price_accelerating and security_clean
    return {"is_early_move": all_converge, "reasons_met": reasons_met, "reasons_missing": reasons_missing}


def classify_base_radar_status(viability: dict, flow: dict, security: dict, pair_age_hours: Optional[float]) -> dict:
    """v4.6 — the 🧭 BASE RADAR classification, now with a REAL security
    gate (v4.5 left this as an explicit unclosed gap; v4.6 closes it by
    reusing risk_engine's GoPlus integration). HIGH_RISK still surfaces
    (warning-only philosophy, consistent with the main CoinGecko path)
    but is now loudly labeled instead of silently absent."""
    if not viability["passes"]:
        return {"label": "🚫 FILTERED", "detail": "; ".join(viability["reasons"])}

    detail_parts = [f"buy/sell flow: {flow['flow_label']}"]
    if flow.get("pct_24h") is not None:
        detail_parts.append(f"{flow['pct_24h']:+.1f}% / 24h")
    if pair_age_hours is not None:
        detail_parts.append(f"pair age: {pair_age_hours:.0f}h")

    if security["severity"] == "HIGH_RISK":
        return {"label": "🚫 HIGH RISK", "detail": "; ".join(security["flags"]),
                "security_checked": True}

    label = "🧭 BASE RADAR"
    caveat = None
    if security["severity"] == "UNCHECKED":
        caveat = "security check unavailable for this token — unverified, not confirmed safe"
    elif security["severity"] == "CAUTION":
        detail_parts.append(f"⚠️ {len(security['flags'])} security flag(s)")

    result = {"label": label, "detail": "; ".join(detail_parts), "security_checked": security["available"]}
    if caveat:
        result["caveat"] = caveat
    return result
