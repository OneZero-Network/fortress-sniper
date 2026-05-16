#!/usr/bin/env python3
"""
reply_handler.py — Telegram reply poller for SNIPER v3.0-M
Bismillah — In the name of Allah, the Most Gracious, the Most Merciful

Run via GitHub Actions every 10 minutes during market hours:
  cron: "*/10 3-10 * * 1-5"   # 8:30 AM - 4 PM IST on weekdays

Parses your Telegram replies and logs decisions to the DB.

Supported reply formats:
  TAKEN TCS @ 3445           → logs TAKEN with entry price
  TAKEN TCS 3445             → same (@ optional)
  TAKEN TCS                  → logs TAKEN, entry = signal close price
  SKIPPED TCS earnings        → logs SKIPPED with reason
  SKIPPED TCS                → logs SKIPPED, reason = "unspecified"
  PARTIAL TCS @ 3440 50       → logs TAKEN with 50 shares
"""

import os, re, sqlite3, logging, requests
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DB_PATH          = Path(os.getenv("CACHE_PATH", "outputs/sniper_cache.db"))

# Patterns (case-insensitive)
_TAKEN   = re.compile(r"^TAKEN\s+([A-Z]+)(?:\s+[@:]?\s*([\d.]+))?", re.I)
_SKIPPED = re.compile(r"^SKIPPED\s+([A-Z]+)(?:\s+(.+))?", re.I)
_PARTIAL = re.compile(r"^PARTIAL\s+([A-Z]+)(?:\s+[@:]?\s*([\d.]+))?(?:\s+(\d+))?", re.I)


def _get_updates(offset: int = 0):
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    resp = requests.get(url, params={"offset": offset, "timeout": 10}, timeout=15)
    if resp.status_code == 200:
        return resp.json().get("result", [])
    return []


def _save_offset(offset: int):
    try:
        Path("outputs/tg_offset.txt").write_text(str(offset))
    except Exception:
        pass


def _load_offset() -> int:
    try:
        return int(Path("outputs/tg_offset.txt").read_text().strip())
    except Exception:
        return 0


def _get_todays_signal(symbol: str) -> dict:
    """Look up today's signal for a symbol to get the original close price and confidence."""
    today = datetime.today().strftime("%Y-%m-%d")
    try:
        con = sqlite3.connect(DB_PATH, timeout=5)
        row = con.execute(
            "SELECT close, fused_score, grade FROM sniper_results WHERE symbol=? AND run_date=? LIMIT 1",
            (symbol.upper(), today)
        ).fetchone()
        meta = con.execute(
            "SELECT primary_fused_score FROM meta_features WHERE symbol=? AND run_date=? LIMIT 1",
            (symbol.upper(), today)
        ).fetchone()
        con.close()
        return {
            "close":     row[0] if row else None,
            "fused":     row[1] if row else None,
            "grade":     row[2] if row else None,
            "meta_prob": meta[0] if meta else None,
        }
    except Exception:
        return {}


def _log_decision(symbol: str, decision: str, entry_price=None,
                   shares=0, skip_reason=None):
    today = datetime.today().strftime("%Y-%m-%d")
    sig   = _get_todays_signal(symbol)

    if entry_price is None and sig.get("close"):
        entry_price = sig["close"]

    try:
        con = sqlite3.connect(DB_PATH, timeout=10)
        con.execute("""
            INSERT OR REPLACE INTO trade_decisions
              (run_date, symbol, decision, entry_price, shares_taken, skip_reason,
               ai_confidence, worth_flag)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            today, symbol.upper(), decision,
            entry_price, shares or 0, skip_reason,
            sig.get("meta_prob"), None
        ))
        con.commit(); con.close()
        log.info(f"✅ Decision logged: {symbol} → {decision} | "
                 f"₹{entry_price or '—'} | reason: {skip_reason or '—'}")
    except Exception as e:
        log.error(f"Decision log failed: {e}")


def _send_ack(chat_id: str, text: str):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=10
    )


def process_updates():
    offset  = _load_offset()
    updates = _get_updates(offset)

    if not updates:
        log.debug("No new updates")
        return

    for update in updates:
        uid     = update.get("update_id", 0)
        msg     = update.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text    = (msg.get("text") or "").strip().upper()

        # Only process from your chat
        if chat_id != TELEGRAM_CHAT_ID:
            _save_offset(uid + 1)
            continue

        if not text:
            _save_offset(uid + 1)
            continue

        log.info(f"Processing reply: {text}")

        m = _TAKEN.match(text)
        if m:
            sym   = m.group(1)
            price = float(m.group(2)) if m.group(2) else None
            _log_decision(sym, "TAKEN", entry_price=price)
            sig = _get_todays_signal(sym)
            ack = f"✅ TAKEN {sym} logged"
            if price: ack += f" @ ₹{price:.0f}"
            if sig.get("grade"): ack += f" | {sig['grade']}"
            _send_ack(chat_id, ack)
            _save_offset(uid + 1)
            continue

        m = _SKIPPED.match(text)
        if m:
            sym    = m.group(1)
            reason = m.group(2) or "unspecified"
            _log_decision(sym, "SKIPPED", skip_reason=reason.lower())
            _send_ack(chat_id, f"📋 SKIPPED {sym} logged — reason: {reason.lower()}")
            _save_offset(uid + 1)
            continue

        m = _PARTIAL.match(text)
        if m:
            sym    = m.group(1)
            price  = float(m.group(2)) if m.group(2) else None
            shares = int(m.group(3)) if m.group(3) else 0
            _log_decision(sym, "TAKEN", entry_price=price, shares=shares)
            ack = f"✅ PARTIAL {sym} logged"
            if price:  ack += f" @ ₹{price:.0f}"
            if shares: ack += f" | {shares} shares"
            _send_ack(chat_id, ack)
            _save_offset(uid + 1)
            continue

        # Unrecognized command
        _save_offset(uid + 1)

    log.info(f"Processed {len(updates)} update(s)")


if __name__ == "__main__":
    process_updates()
