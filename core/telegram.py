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

v3.9.3 FIX: the v3.3.1 splitter was NOT actually HTML-tag-safe despite
its own docstring's claim — it split on raw line boundaries with no
awareness of open <b>/<i> tags. Once Pearl Radar entries grew to
multiple lines ending in <i>why_now text</i>, a split landing between
the opening <i> and its closing </i> (now common, since a single
candidate entry can span 6+ lines) produced two INVALID HTML fragments —
confirmed directly from a production 400 error: "can't parse entities:
Can't find end tag corresponding to start tag \"i\"" on part 1, and
"Unexpected end tag" on part 2. Fixed by making the splitter track open
tags and properly close/reopen them across a forced split, so every
chunk is independently valid HTML regardless of where the split lands.
"""
from __future__ import annotations
import logging
import re
import time

import requests

from . import config

log = logging.getLogger("fortress.telegram")

# Telegram's actual hard limit is 4096 characters. Using a safety margin
# below that (not the exact limit) accounts for any HTML entity
# expansion and keeps a comfortable buffer.
MAX_MESSAGE_LENGTH = 3800

_TAG_PATTERN = re.compile(r"</?([bi])>")


def _tags_delta(line: str) -> list:
    """Returns the sequence of tag events in a line, in order:
    ('open', 'b'), ('close', 'i'), etc. — used to maintain a running
    stack of currently-open tags as we walk through the text."""
    events = []
    for m in _TAG_PATTERN.finditer(line):
        tag = m.group(1)
        is_close = m.group(0).startswith("</")
        events.append(("close" if is_close else "open", tag))
    return events


def _split_message(text: str, max_len: int = MAX_MESSAGE_LENGTH) -> list:
    """Splits on line boundaries, tracking which <b>/<i> tags are
    currently open as it goes. If a split is forced while tags are open,
    the CURRENT chunk gets those tags closed at its end, and the NEXT
    chunk gets them re-opened at its start — guaranteeing every chunk is
    independently valid HTML, regardless of where the split lands. If a
    single line is itself longer than max_len (rare), it gets hard-split
    as a last resort."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    current = ""
    open_stack = []  # tags currently open, in order opened

    def _finalize_chunk():
        nonlocal current
        # close any tags still open, in reverse order, so the chunk is valid HTML
        closer = "".join(f"</{t}>" for t in reversed(open_stack))
        chunks.append(current + closer)
        current = ""

    def _reopen_prefix() -> str:
        return "".join(f"<{t}>" for t in open_stack)

    for line in text.split("\n"):
        candidate = current + ("\n" if current else "") + line
        if len(candidate) <= max_len:
            current = candidate
            for kind, tag in _tags_delta(line):
                if kind == "open":
                    open_stack.append(tag)
                elif kind == "close" and open_stack and open_stack[-1] == tag:
                    open_stack.pop()
        else:
            if current:
                _finalize_chunk()
                current = _reopen_prefix()
            if len(line) > max_len:
                # single line too long even on its own — hard split as a
                # last resort; strip tags here rather than risk another
                # malformed fragment from mid-tag hard-splitting
                plain_line = _TAG_PATTERN.sub("", line)
                for i in range(0, len(plain_line), max_len):
                    chunks.append(plain_line[i:i + max_len])
                current = ""
                open_stack = []
            else:
                current = (current + "\n" + line) if current else line
                for kind, tag in _tags_delta(line):
                    if kind == "open":
                        open_stack.append(tag)
                    elif kind == "close" and open_stack and open_stack[-1] == tag:
                        open_stack.pop()
    if current:
        _finalize_chunk()
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
