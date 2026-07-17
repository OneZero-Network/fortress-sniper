#!/usr/bin/env python3
"""
FORTRESS_UNIFIED — workflows/pine_sync.py
══════════════════════════════════════════════════════════════════════════════
Pine Script runs inside TradingView's sandbox and cannot call our GHA
pipeline directly — there is no webhook-in for Pine, only webhook-out
(alert() -> Telegram, which both legacy scripts already used). So "sync"
here means: export today's Sniper winners + active pearl watchlist to a
PINE_SYNC sheet tab in a flat, human-typeable format, so you can paste the
top symbol/T1/T2/T3/stop levels into Pine's manual watch or a multi-symbol
version of the strategy, and so the levels Pine draws match what Sniper
computed rather than being recomputed independently on the chart.

Run this immediately after sniper_daily.py in the same GHA job (see
.github/workflows/daily.yml) — it reads what sniper just wrote.
"""
from __future__ import annotations
import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.sheets_client import read_sheet, push_sheet
from core.bridge import load_active_watchlist

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                     datefmt="%H:%M:%S")
log = logging.getLogger("fortress.pine_sync")


def run() -> None:
    date_label = datetime.today().strftime("%Y-%m-%d")
    screener = read_sheet("SCREENER")
    watchlist = load_active_watchlist()

    header = ["Date", "Symbol", "Status", "Conviction", "Close", "StopLoss",
              "R1", "R2", "R3", "PearlThesis"]
    rows = [header]

    if screener and len(screener) > 1:
        sc_header = [h.lower() for h in screener[0]]

        def idx(name, default=None):
            return sc_header.index(name.lower()) if name.lower() in sc_header else default

        today_rows = [r for r in screener[1:] if r and r[0] == date_label]
        for r in today_rows:
            def g(name, default=""):
                i = idx(name)
                return r[i] if i is not None and i < len(r) else default
            rows.append([date_label, g("Symbol"), "TODAY_PICK", g("Conviction"),
                        g("Close"), g("StopLoss"), g("R1"), g("R2"), g("R3"), ""])

    picked_syms = {r[1] for r in rows[1:]}
    for pearl in watchlist:
        if pearl["symbol"] not in picked_syms:
            rows.append([date_label, pearl["symbol"], pearl["status"], "",
                        "", "", "", "", "", pearl.get("thesis", "")[:100]])

    push_sheet("PINE_SYNC", rows)
    log.info(f"PINE_SYNC: {len(rows)-1} rows written for {date_label}")


if __name__ == "__main__":
    run()
