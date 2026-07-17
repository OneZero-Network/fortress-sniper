"""
FORTRESS_UNIFIED — core/llm_client.py
══════════════════════════════════════════════════════════════════════════════
OpenAI wrapper for all PER-TRADE / PER-SYMBOL LLM calls (Shariah audits,
insider-friend narrative audits, pick enrichment). This stays OpenAI,
unchanged from the legacy behavior, per your instruction that Anthropic is
for the Monday weekly review only (see core/weekly_review.py for that).

Includes a SQLite-backed cache (text hash -> result) so repeated prompts
(e.g. re-running the same symbol same day) don't re-spend tokens.
"""
from __future__ import annotations
import hashlib
import logging
import time
from typing import Optional

from . import config
from .db import get_conn

log = logging.getLogger("fortress.llm")

try:
    from openai import OpenAI
    _client = OpenAI(api_key=config.OPENAI_API_KEY) if config.OPENAI_API_KEY else None
except ImportError:
    _client = None


def _cache_get(text_hash: str) -> Optional[str]:
    try:
        with get_conn() as con:
            row = con.execute(
                "SELECT result FROM llm_cache WHERE text_hash = ? AND "
                "created_at > datetime('now', '-7 days')",
                (text_hash,),
            ).fetchone()
            return row[0] if row else None
    except Exception:
        return None


def _cache_put(text_hash: str, prompt_type: str, result: str) -> None:
    try:
        with get_conn(write=True) as con:
            con.execute(
                "INSERT OR REPLACE INTO llm_cache (text_hash, prompt_type, result, created_at) "
                "VALUES (?, ?, ?, datetime('now'))",
                (text_hash, prompt_type, result),
            )
    except Exception as e:
        log.debug(f"llm cache put: {e}")


def call_openai(prompt: str, max_tokens: int = 200, prompt_type: str = "generic",
                 use_cache: bool = True) -> Optional[str]:
    """Call gpt-4o-mini with retry + cache. Returns None on total failure
    (callers must treat None as fail-safe-reject where compliance-relevant)."""
    text_hash = hashlib.md5(prompt.encode()).hexdigest()
    if use_cache:
        cached = _cache_get(text_hash)
        if cached:
            return cached

    if _client is None:
        log.debug("OpenAI client unavailable (no API key or package missing)")
        return None

    for attempt in range(3):
        try:
            resp = _client.chat.completions.create(
                model=config.OPENAI_MINI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.2,
            )
            text = resp.choices[0].message.content
            if text:
                _cache_put(text_hash, prompt_type, text)
                return text
        except Exception as e:
            log.debug(f"OpenAI call attempt {attempt}: {e}")
            time.sleep(1.5 ** attempt)
    return None


def call_openai_embed(text: str) -> Optional[list]:
    if _client is None:
        return None
    try:
        resp = _client.embeddings.create(model=config.OPENAI_EMBED_MODEL, input=text[:8000])
        return resp.data[0].embedding
    except Exception as e:
        log.debug(f"OpenAI embed: {e}")
        return None
