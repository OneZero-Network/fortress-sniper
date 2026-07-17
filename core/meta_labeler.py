"""
FORTRESS_UNIFIED — core/meta_labeler.py
══════════════════════════════════════════════════════════════════════════════
Port of the legacy meta-labeler + Kelly sizing, honestly labeled this time:
the legacy code called itself "logistic regression via gradient descent"
but was actually a correlation-weighted linear score through a sigmoid —
which is fine as a veto heuristic, so that's what it's called here.

- record_meta_label(): store the feature vector for every pick at decision
  time (outcome NULL until the outcome engine resolves it).
- meta_labeler_veto(): once ≥ META_MIN_TRAINING_ROWS resolved rows exist,
  compute per-feature correlation with outcome, z-score the candidate,
  and veto if implied p(win) < META_VETO_PWIN. Below the row threshold it
  never vetoes — no fake confidence from tiny samples.
- compute_kelly_multiplier(): Kelly fraction from resolved outcomes,
  requiring KELLY_MIN_CLOSED_TRADES (20) before trusting it, defaulting
  to the conservative 0.5 half-Kelly cap otherwise. Applied ONCE via
  config.kelly_adjusted_size — never the legacy ×2.
"""
from __future__ import annotations
import logging
import math
from typing import Dict, List, Tuple

import numpy as np

from . import config
from .db import get_conn

log = logging.getLogger("fortress.meta")

FEATURE_COLS = ["fort_pts", "apex_comp", "fused", "bayes_pct", "rsi14", "adx14",
                "mfi", "whale_score", "vol_ratio", "rs_pct", "confidence_score",
                "vix_val", "pearl_pedigree", "ignition_detected"]


def record_meta_label(symbol: str, run_date: str, features: Dict) -> None:
    try:
        with get_conn(write=True) as con:
            con.execute(
                f"""INSERT INTO meta_labels
                    (symbol, run_date, {', '.join(FEATURE_COLS)}, outcome)
                    VALUES (?, ?, {', '.join('?' * len(FEATURE_COLS))}, NULL)""",
                (symbol.upper(), run_date,
                 *[float(features.get(c, 0) or 0) for c in FEATURE_COLS]),
            )
    except Exception as e:
        log.debug(f"record_meta_label {symbol}: {e}")


def resolve_meta_outcome(symbol: str, run_date: str, won: bool) -> None:
    try:
        with get_conn(write=True) as con:
            con.execute(
                "UPDATE meta_labels SET outcome=? WHERE symbol=? AND run_date=? "
                "AND outcome IS NULL",
                (1 if won else 0, symbol.upper(), run_date),
            )
    except Exception as e:
        log.debug(f"resolve_meta_outcome {symbol}: {e}")


def _load_training() -> Tuple[np.ndarray, np.ndarray]:
    try:
        with get_conn() as con:
            rows = con.execute(
                f"SELECT {', '.join(FEATURE_COLS)}, outcome FROM meta_labels "
                "WHERE outcome IS NOT NULL"
            ).fetchall()
        if not rows:
            return np.empty((0, len(FEATURE_COLS))), np.empty(0)
        arr = np.array(rows, dtype=float)
        return arr[:, :-1], arr[:, -1]
    except Exception as e:
        log.debug(f"_load_training: {e}")
        return np.empty((0, len(FEATURE_COLS))), np.empty(0)


def meta_labeler_veto(features: Dict) -> Tuple[bool, float, int]:
    """Returns (veto, p_win, n_training_rows). Never vetoes below the
    minimum-sample threshold."""
    X, y = _load_training()
    n = len(y)
    if n < config.META_MIN_TRAINING_ROWS or y.std() == 0:
        return False, 0.5, n
    try:
        mu, sd = X.mean(axis=0), X.std(axis=0)
        sd[sd == 0] = 1.0
        Xz = (X - mu) / sd
        yz = (y - y.mean()) / (y.std() or 1.0)
        weights = (Xz * yz[:, None]).mean(axis=0)   # per-feature correlation
        wsum = np.abs(weights).sum() or 1.0

        x = np.array([float(features.get(c, 0) or 0) for c in FEATURE_COLS])
        xz = (x - mu) / sd
        score = float(np.dot(xz, weights) / wsum)
        p_win = 1.0 / (1.0 + math.exp(-3.0 * score))
        # recentre around the empirical base rate
        base = float(y.mean())
        p_win = max(0.02, min(0.98, 0.5 * p_win + 0.5 * base))
        return (p_win < config.META_VETO_PWIN), round(p_win, 3), n
    except Exception as e:
        log.debug(f"meta_labeler_veto: {e}")
        return False, 0.5, n


def compute_kelly_multiplier() -> Tuple[float, Dict]:
    """Kelly fraction f = W - (1-W)/R from resolved outcomes' pnl_pct.
    Returns (multiplier clamped to [KELLY_FLOOR, KELLY_CEILING], stats).
    Under KELLY_MIN_CLOSED_TRADES → conservative default, empty stats."""
    try:
        with get_conn() as con:
            rows = con.execute(
                "SELECT pnl_pct FROM outcomes WHERE status != 'open' "
                "AND pnl_pct IS NOT NULL"
            ).fetchall()
        pnls = [float(r[0]) for r in rows]
    except Exception as e:
        log.debug(f"compute_kelly_multiplier: {e}")
        pnls = []

    if len(pnls) < config.KELLY_MIN_CLOSED_TRADES:
        return config.KELLY_DEFAULT_MULT, {"n": len(pnls), "note": "insufficient history"}

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    W = len(wins) / len(pnls)
    avg_w = float(np.mean(wins)) if wins else 0.0
    avg_l = abs(float(np.mean(losses))) if losses else 1e-9
    R = avg_w / avg_l if avg_l > 0 else 1.0
    f = W - (1.0 - W) / R if R > 0 else 0.0
    mult = max(config.KELLY_FLOOR, min(config.KELLY_CEILING, f))
    stats = {"n": len(pnls), "win_rate": round(W * 100, 1),
             "avg_win": round(avg_w, 2), "avg_loss": round(avg_l, 2),
             "payoff_R": round(R, 2), "kelly_f": round(f, 3), "mult": round(mult, 3)}
    return mult, stats
