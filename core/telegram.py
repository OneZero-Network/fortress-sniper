"""
FORTRESS_UNIFIED — core/telegram.py
══════════════════════════════════════════════════════════════════════════════
Single Telegram sender shared by all entrypoints (sniper picks, incubator
pearls, weekly Claude review, ignition alerts from the bridge).

v3.3.1 FIX: send() used to fail SILENTLY on Telegram's 4096-character
message limit — 3 retries, then a bare `return False` with only a
log.debug line (invisible at the INFO level every workflow runs at).
As the Pearl Detection Machine's candidate lists grew (47 High-Potential
in one run), messages started exceeding that limit and simply vanished
with no trace in the logs. Fixed two ways: (1) long messages are now
auto-split into multiple sends at safe line boundaries, and (2) any
send that still fails is logged at WARNING, not debug, so a silent
Telegram failure can never happen again without at least a log entry.
"""
from __future__ import annotations
import logging
import time

import requests

from . import config

log = logging.getLogger("fortress.telegram")

# Telegram's actual hard limit is 4096 characters. Using a safety margin
# below that (not the exact limit) accounts for any HTML entity
# expansion and keeps a comfortable buffer.
MAX_MESSAGE_LENGTH = 3800


def _split_message(text: str, max_len: int = MAX_MESSAGE_LENGTH) -> list:
    """Splits on line boundaries where possible, to avoid breaking a
    message mid-HTML-tag (e.g. cutting through the middle of a <b>...
    </b> pair, which would leave Telegram's parser confused for the
    remainder of that chunk). If a single line is itself longer than
    max_len (rare, but possible with a very long detail line), it gets
    hard-split as a last resort rather than dropped."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    current = ""
    for line in text.split("\n"):
        candidate = current + ("\n" if current else "") + line
        if len(candidate) <= max_len:
            current = candidate
        else:
            if current:
                chunks.append(current)
            if len(line) > max_len:
                # single line too long on its own — hard split, last resort
                for i in range(0, len(line), max_len):
                    chunks.append(line[i:i + max_len])
                current = ""
            else:
                current = line
    if current:
        chunks.append(current)
    return chunks


def _send_single(text: str) -> bool:
    for attempt in range(3):
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
                timeout=15,
            )
            if resp.status_code == 200:
                return True
            if resp.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            # non-200, non-429 (e.g. 400 Bad Request for an oversized or
            # malformed message) — log it LOUDLY, this used to disappear
            # silently and cost a full day's Pearl scan going unseen
            log.warning(f"Telegram send failed: HTTP {resp.status_code} — {resp.text[:300]}")
            return False
        except Exception as e:
            log.warning(f"Telegram attempt {attempt+1}/3 raised: {e}")
            time.sleep(1)
    log.warning("Telegram send failed after 3 attempts — message was NOT delivered")
    return False


def send(text: str) -> bool:
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured — skipping send (message was NOT delivered)")
        return False

    chunks = _split_message(text)
    if len(chunks) > 1:
        log.info(f"Message exceeds {MAX_MESSAGE_LENGTH} chars ({len(text)} total) — "
                 f"splitting into {len(chunks)} parts")

    all_ok = True
    for i, chunk in enumerate(chunks):
        prefix = f"[{i+1}/{len(chunks)}]\n" if len(chunks) > 1 else ""
        ok = _send_single(prefix + chunk)
        all_ok = all_ok and ok
        if not ok:
            log.warning(f"Part {i+1}/{len(chunks)} of a split message failed to send")
    return all_ok
