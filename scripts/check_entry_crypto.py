#!/usr/bin/env python3
"""
FORTRESS_CRYPTO — scripts/check_entry_crypto.py
══════════════════════════════════════════════════════════════════════════════
Crypto analogue of scripts/check_entry.py. Same "ghost entry" problem
applies MORE severely here — a 24/7, higher-volatility market means the
scan-vs-action staleness gap the ASPINWALL case exposed is a near-daily
risk with crypto, not an edge case. Run this immediately before entering
any position from a Telegram alert / CRYPTO_SCREENER row.

Usage:
    python scripts/check_entry_crypto.py SOL
    python scripts/check_entry_crypto.py SOL --entry 145.20 --stop 138.00 --r1 158.00

Exit codes: 0 = still VALID, 1 = BROKEN/CRITICAL, 2 = couldn't fetch data.
"""
from __future__ import annotations
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.crypto import data as cdata
from core.sheets_client import read_sheet


def _lookup_screener_row(symbol: str) -> dict:
    raw = read_sheet("CRYPTO_SCREENER")
    if not raw or len(raw) < 2:
        return {}
    header = raw[0]
    idx = {h: i for i, h in enumerate(header)}
    for row in reversed(raw[1:]):
        if len(row) > idx.get("symbol", 0) and str(row[idx["symbol"]]).upper() == symbol.upper():
            return {
                "entry": float(row[idx["close"]]) if "close" in idx else None,
            }
    return {}


def classify(live: float, entry: float, stop: float, r1: float = None) -> str:
    if stop and live <= stop:
        return "BROKEN"
    if stop and entry and abs(live - stop) / entry <= 0.015:
        return "CRITICAL"
    if r1 and live >= r1:
        return "TARGET_HIT"
    if entry and abs(live - entry) / entry > 0.05:
        return "DRIFTED"
    return "VALID"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--entry", type=float, default=None)
    ap.add_argument("--stop", type=float, default=None)
    ap.add_argument("--r1", type=float, default=None)
    args = ap.parse_args()

    entry, stop, r1 = args.entry, args.stop, args.r1
    if entry is None:
        looked_up = _lookup_screener_row(args.symbol)
        entry = looked_up.get("entry")

    live = cdata.fetch_live_price_binance(args.symbol)
    if live is None:
        print(f"❌ Could not fetch live Binance price for {args.symbol} — cannot validate entry.")
        return 2

    if entry is None:
        print(f"ℹ️  Live price for {args.symbol}: ${live:,.4f} (no entry/stop provided or found — nothing to validate against)")
        return 0

    status = classify(live, entry, stop, r1)
    print(f"{args.symbol}: live=${live:,.4f} entry=${entry:,.4f} "
          f"stop={f'${stop:,.4f}' if stop else 'n/a'} -> {status}")

    return 0 if status in ("VALID", "TARGET_HIT") else (1 if status in ("BROKEN", "CRITICAL") else 0)


if __name__ == "__main__":
    sys.exit(main())
