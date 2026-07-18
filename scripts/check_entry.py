#!/usr/bin/env python3
"""
FORTRESS_UNIFIED — scripts/check_entry.py
══════════════════════════════════════════════════════════════════════════════
Run this right before you act on a pick from today's Telegram alert or the
SCREENER sheet. It fetches the LIVE price and tells you plainly whether the
scan-time entry/stop is still valid — this is the direct fix for the
ASPINWALL "ghost entry" problem your mentor caught: the scan ran on
yesterday's EOD close (₹257, stop ₹240), but by the time of manual review
the live price had already drifted down onto the stop-loss line. A smarter
alert message can't catch that — only a live re-check at the moment of
action can.

Usage:
    python scripts/check_entry.py ASPINWALL
    python scripts/check_entry.py ASPINWALL --entry 257 --stop 240 --r1 280

If --entry/--stop/--r1 are omitted, it looks up today's row for that
symbol in the SCREENER sheet and uses those values.

Exit codes: 0 = still valid, 1 = broken/invalid, 2 = couldn't fetch data
(never silently reports "valid" when data is missing).
"""
from __future__ import annotations
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.nse_data import fetch_live_price
from core.sheets_client import read_sheet


def _lookup_screener_row(symbol: str) -> dict:
    """Pull today's (or most recent) SCREENER row for this symbol."""
    raw = read_sheet("SCREENER")
    if not raw or len(raw) < 2:
        return {}
    header = [h.lower() for h in raw[0]]

    def idx(name):
        return header.index(name.lower()) if name.lower() in header else None

    sym_i = idx("symbol")
    if sym_i is None:
        return {}
    matches = [r for r in raw[1:] if len(r) > sym_i and r[sym_i].upper() == symbol.upper()]
    if not matches:
        return {}
    row = matches[-1]  # most recent occurrence

    def get(name, cast=float, default=0.0):
        i = idx(name)
        if i is None or i >= len(row) or row[i] == "":
            return default
        try:
            return cast(row[i])
        except (ValueError, TypeError):
            return default

    return {
        "close": get("Close"), "stop_loss": get("StopLoss"),
        "r1": get("R1"), "r2": get("R2"), "r3": get("R3"),
        "date": row[idx("Date")] if idx("Date") is not None else "",
    }


def check_entry(symbol: str, entry: float, stop: float, r1: float = 0.0) -> dict:
    """Returns {status, live_price, room_to_stop_pct, message}."""
    live = fetch_live_price(symbol)
    if live is None:
        return {"status": "NO_DATA", "live_price": None, "room_to_stop_pct": None,
                "message": f"⚠️ Could not fetch live price for {symbol} — "
                          f"cannot confirm this setup is still valid. Check manually before acting."}

    lp = live["last_price"]
    room_pct = ((lp - stop) / lp * 100) if lp > 0 else 0.0

    if lp <= stop:
        status = "BROKEN"
        msg = (f"🛑 BROKEN: live price ₹{lp:.2f} has already hit or breached the "
              f"stop-loss ₹{stop:.2f}. This setup is dead — do NOT enter.")
    elif room_pct < 1.5:
        status = "CRITICAL"
        msg = (f"🔴 CRITICAL: live price ₹{lp:.2f} is only {room_pct:.1f}% above stop "
              f"₹{stop:.2f} — essentially sitting on the line, exactly like ASPINWALL. "
              f"Entering here means almost no room before you're stopped out.")
    elif lp < entry * 0.98:
        status = "DRIFTED"
        drift_pct = (entry - lp) / entry * 100
        msg = (f"🟡 DRIFTED: live price ₹{lp:.2f} is {drift_pct:.1f}% below the scan-time "
              f"entry ₹{entry:.2f}. Room to stop is {room_pct:.1f}% — still technically "
              f"valid but re-check your risk math at this price, not the scan-time entry.")
    elif r1 and lp >= r1:
        status = "TARGET_HIT"
        msg = (f"✅ TARGET ALREADY HIT: live price ₹{lp:.2f} has already reached/passed "
              f"R1 ₹{r1:.2f}. Entering fresh here changes your risk/reward significantly "
              f"— you'd be buying near a target, not at the original entry zone.")
    else:
        status = "VALID"
        msg = (f"✅ VALID: live price ₹{lp:.2f}, {room_pct:.1f}% room above stop ₹{stop:.2f}. "
              f"Setup still matches scan-time conditions.")

    return {"status": status, "live_price": lp, "room_to_stop_pct": round(room_pct, 2),
            "change_pct": live.get("change_pct"), "source": live.get("source"), "message": msg}


def main():
    ap = argparse.ArgumentParser(description="Re-validate a scan pick against live price")
    ap.add_argument("symbol", help="NSE symbol, e.g. ASPINWALL")
    ap.add_argument("--entry", type=float, default=None, help="Scan-time entry price")
    ap.add_argument("--stop", type=float, default=None, help="Scan-time stop-loss")
    ap.add_argument("--r1", type=float, default=None, help="Scan-time R1 target")
    args = ap.parse_args()

    symbol = args.symbol.upper()
    entry, stop, r1 = args.entry, args.stop, args.r1

    if entry is None or stop is None:
        looked_up = _lookup_screener_row(symbol)
        if not looked_up:
            print(f"❌ No --entry/--stop given and no SCREENER row found for {symbol}. "
                  f"Pass them explicitly: --entry 257 --stop 240")
            sys.exit(2)
        entry = entry or looked_up["close"]
        stop = stop or looked_up["stop_loss"]
        r1 = r1 or looked_up.get("r1", 0.0)
        print(f"(Using SCREENER row from {looked_up.get('date', '?')}: "
              f"entry=₹{entry:.2f} stop=₹{stop:.2f} r1=₹{r1:.2f})\n")

    result = check_entry(symbol, entry, stop, r1 or 0.0)
    print(f"{'='*60}")
    print(f"  {symbol} — Entry Re-Validation ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    print(f"{'='*60}")
    print(f"  Scan-time entry: ₹{entry:.2f}  |  Stop: ₹{stop:.2f}"
          + (f"  |  R1: ₹{r1:.2f}" if r1 else ""))
    if result["live_price"] is not None:
        print(f"  Live price: ₹{result['live_price']:.2f} "
              f"({result.get('change_pct', 0):+.2f}% today, source={result.get('source')})")
    print()
    print(f"  {result['message']}")
    print()

    sys.exit({"VALID": 0, "TARGET_HIT": 0, "DRIFTED": 0,
              "CRITICAL": 1, "BROKEN": 1, "NO_DATA": 2}[result["status"]])


if __name__ == "__main__":
    main()
