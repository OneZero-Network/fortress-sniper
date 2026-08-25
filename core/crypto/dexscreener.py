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


def _get_with_diagnostics(path: str) -> dict:
    """v4.7.2 — same request as _get(), but ALWAYS returns full
    diagnostic info regardless of outcome, per explicit instruction:
    'SEARCH SOURCE UNAVAILABLE / ZERO RESULTS' must be distinguishable
    states, not both silently collapsed to an empty list."""
    _throttle()
    try:
        resp = requests.get(f"{DEXSCREENER_BASE}{path}", timeout=15)
        result = {"http_status": resp.status_code, "response_size_bytes": len(resp.content),
                  "data": None, "error": None}
        if resp.status_code == 200:
            try:
                result["data"] = resp.json()
            except Exception as e:
                result["error"] = f"JSON parse failure: {e}"
        else:
            result["error"] = f"HTTP {resp.status_code}"
        return result
    except Exception as e:
        return {"http_status": None, "response_size_bytes": 0, "data": None,
                "error": f"request exception: {e}"}


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


def classify_dex_outcome(return_pct: Optional[float], was_early_move: bool, horizon: str) -> dict:
    """v4.7.4 — the standardized 5-state outcome vocabulary, per explicit
    instruction. This is a REPORTING classification only — it never
    feeds back into scoring or the early-move definition itself. The
    key distinction: an asset that moved a lot but was NEVER classified
    as an early move at discovery gets 'NO EDGE,' not 'FAILED' — no
    early-detection thesis was ever made for it, so there's nothing to
    fail."""
    if return_pct is None:
        return {"status": "⚫ INSUFFICIENT DATA", "verdict": "Not enough time has passed to judge yet."}

    if was_early_move:
        if return_pct >= 15:
            return {"status": "🟢 SUCCESS", "verdict": "Early detection held."}
        if return_pct <= -10:
            return {"status": "🔴 FAILED", "verdict": "Initial acceleration reversed."}
        if horizon in ("1h", "6h"):
            return {"status": "🟡 DEVELOPING", "verdict": "Thesis still alive, insufficient time to judge."}
        return {"status": "⚪ NO EDGE", "verdict": "Move did not meaningfully expand after detection."}
    else:
        return {"status": "⚪ NO EDGE",
                "verdict": "Move did not provide meaningful early advantage — detection was never called early."}


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


def fetch_boosted_base_tokens_diagnostic(limit: int = 30) -> dict:
    """v4.7.2 — Coverage Audit. Returns full diagnostics, not just a
    filtered list: how many items the API returned in total (across ALL
    chains), how many survived the Base filter, HTTP status, and any
    parse failures — so 'zero results' can be attributed to the right
    cause instead of silently treated as 'no Base opportunities.'"""
    result = _get_with_diagnostics("/token-boosts/latest/v1")
    data = result["data"]
    if data is None:
        return {"source": "BOOSTED", "http_status": result["http_status"],
                "response_size_bytes": result["response_size_bytes"],
                "raw_item_count": 0, "base_item_count": 0, "items": [],
                "status": "UNAVAILABLE", "error": result["error"]}

    tokens = data if isinstance(data, list) else data.get("tokens", [])
    base_tokens = [t for t in tokens if t.get("chainId") == "base"]
    for t in base_tokens:
        t["_source"] = "BOOSTED"
    return {"source": "BOOSTED", "http_status": result["http_status"],
            "response_size_bytes": result["response_size_bytes"],
            "raw_item_count": len(tokens), "base_item_count": len(base_tokens),
            "items": base_tokens[:limit],
            "status": "ZERO_RESULTS" if len(base_tokens) == 0 and len(tokens) > 0 else "OK",
            "error": None}


def fetch_profiled_base_tokens_diagnostic(limit: int = 30) -> dict:
    """v4.7.2 — same diagnostic treatment as the boosted source."""
    result = _get_with_diagnostics("/token-profiles/latest/v1")
    data = result["data"]
    if data is None:
        return {"source": "PROFILED", "http_status": result["http_status"],
                "response_size_bytes": result["response_size_bytes"],
                "raw_item_count": 0, "base_item_count": 0, "items": [],
                "status": "UNAVAILABLE", "error": result["error"]}

    tokens = data if isinstance(data, list) else data.get("tokens", [])
    base_tokens = [t for t in tokens if t.get("chainId") == "base"]
    for t in base_tokens:
        t["_source"] = "PROFILED"
    return {"source": "PROFILED", "http_status": result["http_status"],
            "response_size_bytes": result["response_size_bytes"],
            "raw_item_count": len(tokens), "base_item_count": len(base_tokens),
            "items": base_tokens[:limit],
            "status": "ZERO_RESULTS" if len(base_tokens) == 0 and len(tokens) > 0 else "OK",
            "error": None}


def fetch_top_boosted_base_tokens_diagnostic(limit: int = 30) -> dict:
    """v4.9.4 — Discovery source D: /token-boosts/top/v1, ranked by TOTAL
    boost spend rather than chronological recency (/latest/v1) — a
    genuinely different slice of the cross-chain boost feed, not a
    duplicate. Still curated/biased (same honest limitation as BOOSTED/
    PROFILED), but adds real additional candidates beyond the same 4
    search anchors."""
    result = _get_with_diagnostics("/token-boosts/top/v1")
    data = result["data"]
    if data is None:
        return {"source": "TOP_BOOSTED", "http_status": result["http_status"],
                "response_size_bytes": result["response_size_bytes"],
                "raw_item_count": 0, "base_item_count": 0, "items": [],
                "status": "UNAVAILABLE", "error": result["error"]}

    tokens = data if isinstance(data, list) else data.get("tokens", [])
    base_tokens = [t for t in tokens if t.get("chainId") == "base"]
    for t in base_tokens:
        t["_source"] = "TOP_BOOSTED"
    return {"source": "TOP_BOOSTED", "http_status": result["http_status"],
            "response_size_bytes": result["response_size_bytes"],
            "raw_item_count": len(tokens), "base_item_count": len(base_tokens),
            "items": base_tokens[:limit],
            "status": "ZERO_RESULTS" if len(base_tokens) == 0 and len(tokens) > 0 else "OK",
            "error": None}


def fetch_search_base_pairs_diagnostic(query_terms: List[str] = None) -> dict:
    """v4.7.2 — Coverage Audit, and a reasoned strategy change.

    CONFIRMED (via DexScreener's own documented behavior, checked
    directly, not guessed): the search endpoint is HARD-CAPPED at ~30
    results and RELEVANCE-RANKED ACROSS EVERY CHAIN DexScreener indexes.
    A generic query like 'WETH' matches an enormous number of pairs on
    Ethereum mainnet alone — it is entirely plausible that all 30 top-
    ranked results for a generic query are non-Base, meaning the search
    genuinely returns pairs, just none on the chain we filter for
    afterward. That is DIFFERENT from the request failing.

    FIX ATTEMPTED (a hypothesis, not a blind tune): querying Base-native
    token tickers (AERO — Aerodrome, Base's flagship DEX; BRETT, DEGEN,
    TOSHI — well-known Base-ecosystem tokens) instead of generic
    cross-chain terms, since these tokens are predominantly or
    exclusively traded on Base, biasing the relevance ranking toward
    Base results before the chain filter even runs. The NEW per-query
    raw/base counts in this diagnostic will directly confirm or refute
    whether this actually helps, on the very next run.

    v4.9.4: added MOONWELL, SEAMLESS, EXTRA — genuinely different Base
    DeFi projects (not more memecoins from the same original 4), to at
    least diversify WHICH known tokens get searched. Still fundamentally
    name-biased — this does NOT solve unknown-token discovery, it only
    slightly widens the KNOWN-token net. Flagged honestly, not
    oversold as a fix for the structural search limitation."""
    query_terms = query_terms or ["AERO", "BRETT", "DEGEN", "TOSHI", "MOONWELL", "SEAMLESS", "EXTRA"]
    all_pairs = []
    per_query = []
    for term in query_terms:
        result = _get_with_diagnostics(f"/latest/dex/search?q={term}")
        data = result["data"]
        if data is None:
            per_query.append({"query": term, "http_status": result["http_status"],
                              "raw_count": 0, "base_count": 0, "status": "UNAVAILABLE",
                              "error": result["error"]})
            continue
        pairs = data.get("pairs") or []
        base_pairs = [p for p in pairs if p.get("chainId") == "base"]
        for p in base_pairs:
            p["_source"] = "SEARCH"
        all_pairs.extend(base_pairs)
        per_query.append({"query": term, "http_status": result["http_status"],
                          "raw_count": len(pairs), "base_count": len(base_pairs),
                          "status": "ZERO_RESULTS" if len(base_pairs) == 0 and len(pairs) > 0 else "OK",
                          "error": None})

    total_raw = sum(q["raw_count"] for q in per_query)
    return {"source": "SEARCH", "per_query": per_query,
            "raw_item_count": total_raw, "base_item_count": len(all_pairs),
            "items": all_pairs,
            "status": "ZERO_RESULTS" if len(all_pairs) == 0 and total_raw > 0 else
                      ("UNAVAILABLE" if total_raw == 0 else "OK")}


# Thin backward-compatible wrappers — return just the item list, for any
# caller that doesn't need the full diagnostic.
def fetch_boosted_base_tokens(limit: int = 30) -> List[dict]:
    return fetch_boosted_base_tokens_diagnostic(limit)["items"]


def fetch_profiled_base_tokens(limit: int = 30) -> List[dict]:
    return fetch_profiled_base_tokens_diagnostic(limit)["items"]


def fetch_search_base_pairs(query_terms: List[str] = None) -> List[dict]:
    return fetch_search_base_pairs_diagnostic(query_terms)["items"]


def dedupe_pairs_by_address(pairs: List[dict]) -> List[dict]:
    """Multiple discovery sources can surface the SAME pair — dedupe by
    pairAddress, keeping the first-seen source tag (source attribution
    matters for later measuring which discovery channel is actually
    valuable, per the roadmap's 'keep boosted as a separate label')."""
    seen = {}
    for p in pairs:
        addr = p.get("pairAddress")
        if addr and addr not in seen:
            seen[addr] = p
    return list(seen.values())


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


def apply_liquidity_filter(pair: dict) -> dict:
    """Stage 2a — liquidity floor only, split out from the combined
    viability check so the discovery funnel can report each stage's
    survivor count separately, per explicit request."""
    liquidity = (pair.get("liquidity") or {}).get("usd") or 0
    passes = liquidity >= MIN_LIQUIDITY_USD
    return {"passes": passes, "liquidity_usd": liquidity,
            "reason": "passes liquidity floor" if passes else f"liquidity ${liquidity:,.0f} below ${MIN_LIQUIDITY_USD:,} floor"}


def apply_activity_filter(pair: dict) -> dict:
    """Stage 2b — volume + transaction floors only, split out from the
    combined viability check for the same funnel-reporting reason."""
    volume_24h = (pair.get("volume") or {}).get("h24") or 0
    txns_24h_data = (pair.get("txns") or {}).get("h24") or {}
    txns_24h = (txns_24h_data.get("buys") or 0) + (txns_24h_data.get("sells") or 0)
    reasons = []
    if volume_24h < MIN_VOLUME_24H_USD:
        reasons.append(f"24h volume ${volume_24h:,.0f} below ${MIN_VOLUME_24H_USD:,} floor")
    if txns_24h < MIN_TXNS_24H:
        reasons.append(f"{txns_24h} txns/24h below {MIN_TXNS_24H} floor")
    return {"passes": len(reasons) == 0, "volume_24h_usd": volume_24h, "txns_24h": txns_24h,
            "reasons": reasons or ["passes activity floor"]}


def apply_viability_filters(pair: dict) -> dict:
    """Combined liquidity + activity check — kept for any caller that
    wants the single combined pass/fail (e.g. dex_flywheel.py's
    resolution path doesn't need the split funnel detail)."""
    liq = apply_liquidity_filter(pair)
    act = apply_activity_filter(pair)
    reasons = ([] if liq["passes"] else [liq["reason"]]) + (act["reasons"] if not act["passes"] else [])
    return {"passes": liq["passes"] and act["passes"], "reasons": reasons or ["passes all viability floors"],
            "liquidity_usd": liq["liquidity_usd"], "volume_24h_usd": act["volume_24h_usd"], "txns_24h": act["txns_24h"]}


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


def compute_dex_precursor(pair_age_hours: Optional[float], accel: dict, flow: dict,
                           security: dict, already_extended: bool,
                           new_pair_threshold_hours: float = 24.0) -> dict:
    """v4.9.3 — DEX Pre-Pearl Engine. Per explicit instruction: 'find the
    change in behavior BEFORE the price move,' not another price-based
    check. Deliberately does NOT require price acceleration — that's
    what distinguishes this from BUILDING/EARLY_MOVE, which both do.
    A pre-Pearl candidate is genuinely: very new pair + activity (txns/
    volume/buy-pressure) accelerating on MULTIPLE independent fronts +
    price hasn't caught up yet + security clean. If price has already
    moved, this is by definition too late to be a precursor — that's
    what already_extended blocks."""
    if security.get("severity") == "HIGH_RISK" or already_extended:
        return {"is_pre_pearl": False, "signals_met": [], "detail": "blocked" if security.get("severity") == "HIGH_RISK" else "already moved"}

    is_new = pair_age_hours is not None and pair_age_hours <= new_pair_threshold_hours
    if not is_new:
        return {"is_pre_pearl": False, "signals_met": [], "detail": "pair not new enough for pre-Pearl consideration"}

    signals = []
    if accel.get("label") == "ACCELERATING":
        signals.append("volume accelerating")
    if accel.get("txn_accel_ratio") is not None and accel["txn_accel_ratio"] >= 1.5:
        signals.append("transactions accelerating")
    if flow.get("flow_label") == "STRONG_BUY_PRESSURE":
        signals.append("buy pressure increasing")

    # Requires genuine convergence — 2+ of 3 activity signals, on top of
    # the already-checked new-pair + not-extended + security-clean gates
    is_pre_pearl = len(signals) >= 2
    return {"is_pre_pearl": is_pre_pearl, "signals_met": signals,
            "detail": f"{len(signals)}/3 activity signals converging on a new, not-yet-moved pair"}


def classify_dex_stage(early_move_result: dict, security: dict) -> dict:
    """v4.7.6 — 🟡 BUILDING state, per explicit instruction: the missing
    layer between WATCH and ⚡ EARLY MOVE. Reuses classify_dex_early_move's
    reasons_met/reasons_missing directly rather than re-implementing the
    condition checks — BUILDING means 2+ conditions genuinely met (real
    partial confirmation) but not the full convergence required for
    EARLY_MOVE. A security failure overrides everything — never BUILDING
    or EARLY_MOVE on a token that failed the security check.

    v4.7.8 FIX: 'already_extended' (price already moved 2x+, per
    classify_dex_early_move's independent magnitude check) now ALSO
    overrides BUILDING — a coin that's already up 885% isn't 'building'
    toward anything, that move already happened. Returns a distinct
    ALREADY_EXTENDED stage so it's still tracked/logged (never silently
    dropped), just never shown as a developing opportunity."""
    if security.get("severity") == "HIGH_RISK":
        return {"stage": "BLOCKED", "conditions_met": 0}
    if early_move_result.get("already_extended"):
        return {"stage": "ALREADY_EXTENDED", "conditions_met": len(early_move_result["reasons_met"])}
    if early_move_result["is_early_move"]:
        return {"stage": "EARLY_MOVE", "conditions_met": len(early_move_result["reasons_met"])}
    n_met = len(early_move_result["reasons_met"])
    if n_met >= 2:
        return {"stage": "BUILDING", "conditions_met": n_met}
    return {"stage": "NONE", "conditions_met": n_met}


def classify_dex_early_move(viability: dict, flow: dict, accel: dict, pair_age_hours: Optional[float],
                             security: dict, max_pair_age_hours: float = 72.0,
                             already_extended_threshold_pct: float = 100.0) -> dict:
    """v4.7 — 🚨 DEX EARLY MOVE. A STRICTER, all-conditions-must-converge
    classification, per explicit instruction: 'don't make every Base
    token appear in Telegram.' Requires ALL of: fresh pair, sufficient
    liquidity (already gated by viability), accelerating volume,
    accelerating transactions, buy pressure, meaningful price
    acceleration, and clean security. Missing even one condition means
    NOT an early move — still logged/tracked, just not surfaced
    prominently.

    v4.7.8 FIX: pool AGE and price MAGNITUDE are different things — a
    pool created 5 hours ago that's already +885% is 'fresh' by age but
    the move already happened. Added an INDEPENDENT check on pct_24h
    (default: already 2x+ = already_extended) that overrides
    is_early_move regardless of how fresh the pool itself is. 'Want the
    next 2-10x, not the past one' — this is that check."""
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

    pct_24h = flow.get("pct_24h")
    already_extended = pct_24h is not None and pct_24h >= already_extended_threshold_pct
    if already_extended:
        reasons_missing.append(f"already up {pct_24h:+.0f}% in 24h — this move already happened")

    all_converge = (viability["passes"] and is_fresh and vol_accelerating and txn_accelerating
                     and buy_pressure and price_accelerating and security_clean and not already_extended)
    return {"is_early_move": all_converge, "reasons_met": reasons_met, "reasons_missing": reasons_missing,
            "already_extended": already_extended}


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
