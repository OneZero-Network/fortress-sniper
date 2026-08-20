"""
FORTRESS_CRYPTO — core/crypto/news_sentiment.py
══════════════════════════════════════════════════════════════════════════════
"Diving skill" layer #1. The universe scan (fetch_universe, factor model,
on-chain concentration) is the metal detector — it finds candidates
everyone with the same free data could find. This module is the part
that requires actually reading what's happening: is there a real news
catalyst behind the move, or is it a bare technical breakout with nothing
underneath it (which is far more likely to be a wash-trade pump or a
liquidity-thin wick)?

DELIBERATELY APPLIED SELECTIVELY — only to candidates that already
cleared the technical trigger threshold, never to the full 150-200 coin
universe. This mirrors how an actual analyst works (scan broad, then
read the news on the shortlist) and keeps CryptoPanic's free-tier call
budget sane.

CryptoPanic's free tier requires a free signup for an auth_token
(cryptopanic.com/developers/api). Without one, every function here
returns None (neutral), never a fabricated sentiment score — same
fail-safe-neutral philosophy as onchain.py and factors_crypto.py.

Sentiment scoring is intentionally simple and auditable: CryptoPanic
tags each post with a community vote type (positive/negative/important/
etc.) — this counts the balance over the lookback window rather than
running an opaque NLP model, so the Telegram alert can show the actual
headline count that produced the label, not a black-box number.
"""
from __future__ import annotations
import logging
import time
from typing import List, Optional

import requests

from . import config as ccfg

log = logging.getLogger("fortress.crypto.news")

_session = requests.Session()
_last_call_ts = [0.0]
_MIN_INTERVAL = 1.2  # CryptoPanic free tier is generous but still finite


def _throttle() -> None:
    elapsed = time.monotonic() - _last_call_ts[0]
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_call_ts[0] = time.monotonic()


def fetch_recent_news(symbol: str, lookback_hours: int = None) -> Optional[List[dict]]:
    """Returns None if disabled/no key/failure (fail-safe — caller must
    treat None as 'no signal', not as 'confirmed no news'). Returns [] if
    the API worked but genuinely found nothing in the window (a real,
    meaningful signal on its own — see sentiment_label below)."""
    if not ccfg.NEWS_SENTIMENT_ENABLED or not ccfg.CRYPTOPANIC_API_KEY:
        return None
    _throttle()
    try:
        resp = _session.get(f"{ccfg.CRYPTOPANIC_BASE}/posts/", params={
            "auth_token": ccfg.CRYPTOPANIC_API_KEY,
            "currencies": symbol.upper(),
            "public": "true",
            "kind": "news",
        }, timeout=15)
        if resp.status_code != 200:
            log.debug(f"CryptoPanic {resp.status_code} for {symbol}")
            return None
        data = resp.json()
        return data.get("results", [])
    except Exception as e:
        log.debug(f"CryptoPanic error for {symbol}: {e}")
        return None


_FORWARD_CATALYST_KEYWORDS = (
    "mainnet", "listing", "listed on", "upgrade", "hard fork", "airdrop",
    "unlock", "token unlock", "partnership", "integration", "launch",
    "etf", "approval", "halving", "acquisition", "roadmap", "testnet",
    "burn", "buyback",
)


def _detect_forward_catalyst(posts: List[dict]) -> Optional[str]:
    """Simple keyword scan over headlines for forward-looking catalyst
    language — 'future news strong chances' as an honest, auditable
    signal rather than a predictive model. Returns the FIRST matching
    headline's catalyst keyword, or None if nothing matched. This is
    pattern-matching on wording, not a claim about actual event
    probability — the Telegram alert labels it as such."""
    for p in posts:
        title = (p.get("title") or "").lower()
        for kw in _FORWARD_CATALYST_KEYWORDS:
            if kw in title:
                return kw
    return None


def sentiment_summary(symbol: str) -> dict:
    """
    Returns:
      {"available": bool, "label": str, "score": float|None,
       "headline_count": int, "top_headline": str|None,
       "forward_catalyst": str|None, "social_buzz_count": int|None}

    label is one of: "NO_SIGNAL" (module disabled/no key/fetch failed),
    "SILENT" (fetched fine, zero relevant news — informative on its own:
    a pure technical breakout with no catalyst is a weaker signal),
    "BULLISH", "BEARISH", "MIXED", "NEUTRAL".

    forward_catalyst: a matched keyword (e.g. "listing", "mainnet") if
    any recent headline used forward-looking catalyst language, else
    None. NOT a probability estimate — just flags that the language
    exists, so a human can go verify.

    social_buzz_count: total post volume across ALL CryptoPanic sources
    (news + media + social) in the lookback window — the honest
    substitute for raw Twitter/X mention counts (that API is no longer
    free). This is a volume proxy, not a genuine tweet count, and is
    labeled as such wherever it's surfaced.
    """
    posts = fetch_recent_news(symbol)
    if posts is None:
        return {"available": False, "label": "NO_SIGNAL", "score": None,
                "headline_count": 0, "top_headline": None,
                "forward_catalyst": None, "social_buzz_count": None}
    if len(posts) == 0:
        return {"available": True, "label": "SILENT", "score": 0.0,
                "headline_count": 0, "top_headline": None,
                "forward_catalyst": None, "social_buzz_count": 0}

    pos, neg = 0, 0
    for p in posts:
        votes = p.get("votes", {})
        pos += votes.get("positive", 0) + votes.get("liked", 0) + votes.get("important", 0)
        neg += votes.get("negative", 0) + votes.get("disliked", 0) + votes.get("toxic", 0)

    total = pos + neg
    score = round((pos - neg) / total, 2) if total > 0 else 0.0

    if total == 0:
        label = "NEUTRAL"
    elif score > 0.25:
        label = "BULLISH"
    elif score < -0.25:
        label = "BEARISH"
    else:
        label = "MIXED"

    top_headline = posts[0].get("title") if posts else None
    forward_catalyst = _detect_forward_catalyst(posts)
    social_buzz = fetch_social_buzz_count(symbol)

    return {"available": True, "label": label, "score": score,
            "headline_count": len(posts), "top_headline": top_headline,
            "forward_catalyst": forward_catalyst, "social_buzz_count": social_buzz}


def fetch_social_buzz_count(symbol: str, lookback_hours: int = None) -> Optional[int]:
    """Honest substitute for 'mostly tweeted' — CryptoPanic aggregates
    Twitter/Reddit-sourced posts alongside news under kind='media' and
    the unfiltered 'all' kind. This is a POST-VOLUME PROXY, not a raw
    tweet count (true tweet counting needs the paid X API, which this
    system does not use). Returns None on failure/no key, never a
    fabricated number."""
    if not ccfg.NEWS_SENTIMENT_ENABLED or not ccfg.CRYPTOPANIC_API_KEY:
        return None
    _throttle()
    try:
        resp = _session.get(f"{ccfg.CRYPTOPANIC_BASE}/posts/", params={
            "auth_token": ccfg.CRYPTOPANIC_API_KEY,
            "currencies": symbol.upper(),
            "public": "true",
            "kind": "media",  # social/community-sourced posts, distinct from 'news'
        }, timeout=15)
        if resp.status_code != 200:
            return None
        return len(resp.json().get("results", []))
    except Exception as e:
        log.debug(f"CryptoPanic social buzz error for {symbol}: {e}")
        return None

