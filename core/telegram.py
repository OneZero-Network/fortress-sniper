"""
FORTRESS_UNIFIED — core/telegram.py
══════════════════════════════════════════════════════════════════════════════
Single Telegram sender shared by all entrypoints (sniper picks, incubator
pearls, weekly Claude review, ignition alerts from the bridge).
"""
from __future__ import annotations
import logging
import time

import requests

from . import config

log = logging.getLogger("fortress.telegram")


def send(text: str) -> bool:
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
        log.debug("Telegram not configured — skipping send")
        return False
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
        except Exception as e:
            log.debug(f"Telegram attempt {attempt}: {e}")
            time.sleep(1)
    return False
