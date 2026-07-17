"""
FORTRESS_UNIFIED — core/outcomes.py
══════════════════════════════════════════════════════════════════════════════
The outcome engine — the piece whose absence the first Monday review
correctly flagged ("performance_rows is 0 … no conclusion possible").
Closes the learning loop:

  record_pick()             — every selected winner becomes an open outcome
                              row at decision time.
  evaluate_open_outcomes()  — at the start of each daily run, every open
                              row older than today is walked forward bar by
                              bar against its stop and R-targets.
  _evaluate_path()          — the pure, unit-testable resolution logic.

Conservative same-day rule (preserved from legacy): if a day's range
touches BOTH the stop and a target, the STOP is recorded — we never
credit ourselves a win on an ambiguous bar.

Resolution feeds: outcomes table (→ Kelly), meta_labels.outcome (→ veto
model), PERFORMANCE sheet tab (→ Monday Claude review + your own eyes).
"""
from __future__ import annotations
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

from . import config
from .db import get_conn
from .nse_data import fetch_history
from .meta_labeler import resolve_meta_outcome
from .sheets_client import append_rows

log = logging.getLogger("fortress.outcomes")


def record_pick(w: Dict, run_date: str, source: str) -> None:
    """Insert an open outcome row for a selected winner (idempotent per
    symbol+run_date — reruns of the same day don't duplicate)."""
    try:
        with get_conn(write=True) as con:
            dup = con.execute(
                "SELECT 1 FROM outcomes WHERE symbol=? AND run_date=?",
                (w["symbol"], run_date),
            ).fetchone()
            if dup:
                return
            con.execute(
                """INSERT INTO outcomes
                   (symbol, run_date, source, pearl_pedigree, entry_price,
                    stop_loss, r1, r2, r3, status, conviction_score)
                   VALUES (?,?,?,?,?,?,?,?,?, 'open', ?)""",
                (w["symbol"], run_date, source, int(bool(w.get("is_pearl"))),
                 w["close"], w["stop_loss"], w["r1"], w["r2"], w["r3"],
                 w.get("conviction_score", 0)),
            )
    except Exception as e:
        log.debug(f"record_pick {w.get('symbol')}: {e}")


def _evaluate_path(hist_after: pd.DataFrame, entry: float, stop: float,
                    r1: float, r2: float, r3: float,
                    timeout_days: int) -> Optional[Tuple[str, float, str]]:
    """
    Pure resolution logic (unit-tested in scripts/test_all.py).
    Walks bars AFTER the entry date. Returns (status, exit_price, exit_date)
    or None if still open.
    Same-day ambiguity: stop is checked FIRST on every bar.
    Targets are checked highest-first so a monster bar credits the best
    target actually reached, exits at that target's price (not the bar high).
    """
    for i, (_, bar) in enumerate(hist_after.iterrows()):
        lo, hi = float(bar["low"]), float(bar["high"])
        d = str(bar.get("date", ""))
        if lo <= stop:
            return "stopped", stop, d
        if hi >= r3:
            return "hit_r3", r3, d
        if hi >= r2:
            return "hit_r2", r2, d
        if hi >= r1:
            return "hit_r1", r1, d
        if i + 1 >= timeout_days:
            return "timeout", float(bar["close"]), d
    return None


def evaluate_open_outcomes() -> List[Dict]:
    """Resolve matured open picks. Returns list of newly closed dicts."""
    today = datetime.today().strftime("%Y-%m-%d")
    try:
        with get_conn() as con:
            rows = con.execute(
                "SELECT id, symbol, run_date, source, pearl_pedigree, entry_price, "
                "stop_loss, r1, r2, r3 FROM outcomes "
                "WHERE status='open' AND run_date < ?", (today,),
            ).fetchall()
    except Exception as e:
        log.warning(f"evaluate_open_outcomes read: {e}")
        return []

    closed: List[Dict] = []
    for (oid, sym, run_date, source, pedigree, entry, stop, r1, r2, r3) in rows:
        try:
            hist = fetch_history(sym, days=config.OUTCOME_TIMEOUT_DAYS + 40)
            if hist.empty or "date" not in hist.columns:
                continue
            hist_after = hist[hist["date"] > run_date]
            if hist_after.empty:
                continue
            res = _evaluate_path(hist_after, entry, stop, r1, r2, r3,
                                  config.OUTCOME_TIMEOUT_DAYS)
            if res is None:
                continue
            status, exit_price, exit_date = res
            pnl_pct = round((exit_price - entry) / entry * 100, 2) if entry > 0 else 0.0
            with get_conn(write=True) as con:
                con.execute(
                    "UPDATE outcomes SET status=?, exit_price=?, exit_date=?, "
                    "pnl_pct=? WHERE id=?",
                    (status, exit_price, exit_date, pnl_pct, oid),
                )
            resolve_meta_outcome(sym, run_date, won=pnl_pct > 0)
            closed.append({"symbol": sym, "run_date": run_date, "source": source,
                            "pearl_pedigree": pedigree, "status": status,
                            "entry": entry, "exit": exit_price,
                            "exit_date": exit_date, "pnl_pct": pnl_pct})
            log.info(f"  OUTCOME {sym:12s} {status:8s} pnl={pnl_pct:+.2f}% "
                     f"({'pearl' if pedigree else 'cold'})")
        except Exception as e:
            log.debug(f"evaluate outcome {sym}: {e}")

    if closed:
        try:
            hdr_needed = False
            from .sheets_client import read_sheet
            if not read_sheet("PERFORMANCE"):
                hdr_needed = True
            rows_out = ([["ClosedDate", "Symbol", "RunDate", "Source", "Pearl",
                          "Status", "Entry", "Exit", "PnL%"]] if hdr_needed else [])
            for c in closed:
                rows_out.append([today, c["symbol"], c["run_date"], c["source"],
                                 "YES" if c["pearl_pedigree"] else "",
                                 c["status"], c["entry"], c["exit"], c["pnl_pct"]])
            append_rows("PERFORMANCE", rows_out)
        except Exception as e:
            log.debug(f"PERFORMANCE append: {e}")
    return closed
