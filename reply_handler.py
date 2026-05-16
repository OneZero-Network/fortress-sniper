#!/usr/bin/env python3
"""
reply_handler.py — Telegram reply poller for SNIPER v4.0-M
Bismillah — In the name of Allah, the Most Gracious, the Most Merciful

WHAT CHANGED vs v3.0-M:
  CHANGE-1  No-response = SKIPPED. The SKIPPED command is removed entirely.
            Silence after market close is auto-logged as SKIPPED by sniper_unified_v2.py
            (_auto_log_skipped_picks). reply_handler only handles TAKEN / PARTIAL.
  CHANGE-2  No scheduler reminder for unanswered picks. Users are not pestered.
  CHANGE-3  Bare "SKIPPED" and "SKIPPED SYM" commands now return a helpful note
            explaining the new flow, instead of logging.
  CHANGE-4  HELP text updated to reflect new flow.
  CHANGE-5  Unrecognised commands still get a friendly nudge.

Run via GitHub Actions every 10 minutes during market hours:
  cron: "*/10 3-10 * * 1-5"   # 8:30 AM - 4 PM IST on weekdays

Supported reply formats:
  TAKEN TCS @ 3445           → logs TAKEN with entry price
  TAKEN TCS 3445             → same (@ optional)
  TAKEN TCS                  → logs TAKEN, entry = signal close price
  PARTIAL TCS @ 3440 50      → logs TAKEN with 50 shares
  HELP or ?                  → sends command reference back

REMOVED (v4.0-M):
  SKIPPED TCS                → NO LONGER NEEDED. Silence = skip.
  SKIPPED                    → NO LONGER NEEDED. Silence = skip.

FIXES RETAINED from v3.0-M:
  FIX-B  Symbol validation before every DB write.
  FIX-C  PARTIAL with shares=0 now warns the user.
  FIX-D  Added HELP / ? command.
  FIX-E  Unrecognised commands get a helpful nudge.
  FIX-H4 Input sanitization: symbols restricted to ^[A-Z&]{1,20}$.
"""

import os, re, sqlite3, logging, requests
from datetime import datetime
from pathlib import Path
from typing import List

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DB_PATH          = Path(os.getenv("CACHE_PATH", "outputs/sniper_cache.db"))

# ── Patterns (case-insensitive) ───────────────────────────────────────────────
_TAKEN   = re.compile(r"^TAKEN\s+([A-Z&]+)(?:\s+[@:]?\s*([\d.]+))?", re.I)
_SKIPPED = re.compile(r"^SKIPPED(?:\s+.*)?$", re.I)  # catch-all, send redirect msg
_PARTIAL = re.compile(r"^PARTIAL\s+([A-Z&]+)(?:\s+[@:]?\s*([\d.]+))?(?:\s+(\d+))?", re.I)
_HELP    = re.compile(r"^(HELP|\?)$", re.I)

# H4: Strict symbol and reason validators
_SYMBOL_RE  = re.compile(r"^[A-Z&]{1,20}$")
_CTRL_STRIP = re.compile(r"[\x00-\x1f\x7f]")

# CHANGE-1: Updated help text — no SKIPPED mention
_HELP_TEXT = (
    "📖 SNIPER v4.0-M reply commands:\n"
    "  TAKEN SYM [@price]              — log a trade entry\n"
    "  PARTIAL SYM [@price] [shares]   — log partial entry\n"
    "  HELP or ?                        — this message\n\n"
    "ℹ️ No reply needed to skip.\n"
    "Silence = SKIPPED, auto-logged at EOD by the system.\n"
    "No reminders will be sent."
)

# CHANGE-3: Redirect message for old SKIPPED command
_SKIPPED_REDIRECT = (
    "ℹ️ SKIPPED is no longer needed.\n"
    "Just don't reply — the system auto-logs silence as SKIPPED at EOD.\n"
    "Only reply if you TOOK or PARTIALLY took a position."
)


# ── H4: Input sanitization helpers ───────────────────────────────────────────

def _sanitize_symbol(raw: str) -> str:
    sym = raw.strip().upper()
    if not _SYMBOL_RE.match(sym):
        raise ValueError(f"Invalid symbol '{sym}' — must match ^[A-Z&]{{1,20}}$")
    return sym


# ── Offset persistence ────────────────────────────────────────────────────────

def _get_updates(offset: int = 0):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    try:
        resp = requests.get(url, params={"offset": offset, "timeout": 10}, timeout=15)
        if resp.status_code == 200:
            return resp.json().get("result", [])
    except Exception as e:
        log.warning(f"Telegram getUpdates failed: {e}")
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


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_todays_signal(symbol: str) -> dict:
    today = datetime.today().strftime("%Y-%m-%d")
    try:
        con = sqlite3.connect(DB_PATH, timeout=5)
        row = con.execute(
            "SELECT close, fused_score, grade FROM sniper_results "
            "WHERE symbol=? AND run_date=? LIMIT 1",
            (symbol.upper(), today)
        ).fetchone()
        meta = con.execute(
            "SELECT primary_fused_score FROM meta_features "
            "WHERE symbol=? AND run_date=? LIMIT 1",
            (symbol.upper(), today)
        ).fetchone()
        # v4.0-M: also fetch calibrated confidence if available
        cal = con.execute(
            "SELECT calibrated_confidence, position_size_tier, halal_tier "
            "FROM judged_picks WHERE symbol=? AND run_date=? LIMIT 1",
            (symbol.upper(), today)
        ).fetchone() if _has_judged_picks_table(con) else None
        con.close()
        return {
            "close":                row[0] if row else None,
            "fused":                row[1] if row else None,
            "grade":                row[2] if row else None,
            "meta_prob":            meta[0] if meta else None,
            "calibrated_confidence": cal[0] if cal else None,
            "position_size_tier":   cal[1] if cal else None,
            "halal_tier":           cal[2] if cal else None,
        }
    except Exception as e:
        log.warning(f"Signal lookup {symbol}: {e}")
        return {}


def _has_judged_picks_table(con) -> bool:
    try:
        con.execute("SELECT 1 FROM judged_picks LIMIT 1")
        return True
    except Exception:
        return False


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
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10
        )
    except Exception as e:
        log.warning(f"Telegram sendMessage failed: {e}")


# ── Main poller ───────────────────────────────────────────────────────────────

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

        if chat_id != TELEGRAM_CHAT_ID:
            _save_offset(uid + 1)
            continue

        if not text:
            _save_offset(uid + 1)
            continue

        log.info(f"Processing reply: {text}")

        # ── HELP ─────────────────────────────────────────────────────────────
        if _HELP.match(text):
            _send_ack(chat_id, _HELP_TEXT)
            _save_offset(uid + 1)
            continue

        # ── TAKEN ─────────────────────────────────────────────────────────────
        m = _TAKEN.match(text)
        if m:
            try:
                sym = _sanitize_symbol(m.group(1))
            except ValueError as ve:
                _send_ack(chat_id, f"⚠️ {ve}")
                _save_offset(uid + 1)
                continue
            price = float(m.group(2)) if m.group(2) else None

            sig = _get_todays_signal(sym)
            if sig.get("close") is None:
                _send_ack(chat_id,
                    f"⚠️ {sym} not in today's picks — check ticker and try again.")
                _save_offset(uid + 1)
                continue

            _log_decision(sym, "TAKEN", entry_price=price)
            ack = f"✅ TAKEN {sym} logged"
            if price:
                ack += f" @ ₹{price:.0f}"
            if sig.get("grade"):
                ack += f" | {sig['grade']}"
            # v4.0-M: show calibrated confidence + position size tier
            if sig.get("calibrated_confidence"):
                ack += f"\n   Cal. confidence: {sig['calibrated_confidence']:.0%}"
            if sig.get("position_size_tier"):
                ack += f" | Size: {sig['position_size_tier']}"
            if sig.get("halal_tier"):
                ack += f" | Halal: {sig['halal_tier']}"
            _send_ack(chat_id, ack)
            _save_offset(uid + 1)
            continue

        # ── SKIPPED (CHANGE-1: redirect, do not log) ──────────────────────────
        # In v4.0-M, SKIPPED is auto-handled at EOD. Redirecting the user.
        if _SKIPPED.match(text):
            _send_ack(chat_id, _SKIPPED_REDIRECT)
            _save_offset(uid + 1)
            continue

        # ── PARTIAL ───────────────────────────────────────────────────────────
        m = _PARTIAL.match(text)
        if m:
            try:
                sym = _sanitize_symbol(m.group(1))
            except ValueError as ve:
                _send_ack(chat_id, f"⚠️ {ve}")
                _save_offset(uid + 1)
                continue
            price  = float(m.group(2)) if m.group(2) else None
            shares = int(m.group(3)) if m.group(3) else 0

            sig = _get_todays_signal(sym)
            if sig.get("close") is None:
                _send_ack(chat_id,
                    f"⚠️ {sym} not in today's picks — check ticker and try again.")
                _save_offset(uid + 1)
                continue

            if shares == 0:
                _send_ack(chat_id,
                    f"⚠️ PARTIAL {sym}: no share count given. "
                    f"Logging anyway — reply 'PARTIAL {sym} @price shares' to correct.")

            _log_decision(sym, "TAKEN", entry_price=price, shares=shares)
            ack = f"✅ PARTIAL {sym} logged"
            if price:   ack += f" @ ₹{price:.0f}"
            if shares:  ack += f" | {shares} shares"
            if shares == 0: ack += " | ⚠️ shares=0"
            # v4.0-M: show position tier
            if sig.get("position_size_tier"):
                ack += f"\n   Recommended size tier: {sig['position_size_tier']}"
            _send_ack(chat_id, ack)
            _save_offset(uid + 1)
            continue

        # ── Unrecognised ──────────────────────────────────────────────────────
        _send_ack(chat_id,
            f"❓ Unknown command: {text[:40]}\n"
            "Reply HELP or ? for commands.\n"
            "ℹ️ No reply needed to skip — silence is auto-logged at EOD.")
        _save_offset(uid + 1)

    log.info(f"Processed {len(updates)} update(s)")


if __name__ == "__main__":
    process_updates()
