"""
FORTRESS_CRYPTO — core/crypto/backtest.py
══════════════════════════════════════════════════════════════════════════════
Backtesting — your mentor's second "critical gap." This is a SIMULATION,
explicitly and permanently distinct from core/crypto/outcome_tracker.py's
live flywheel, which remains the only source of GROUND TRUTH in this
system. Every output from this module carries a "(SIMULATED)" label —
that label is not decoration, it's a hard boundary this system respects
everywhere its outputs are displayed.

WHAT THIS CAN AND CANNOT VALIDATE:
  CAN replay:     trend context, RSI/ADX/volume trigger, market regime,
                   ATR-based stop/target math — everything computed
                   purely from historical price/volume data.
  CANNOT replay:  news sentiment (CryptoPanic doesn't serve historical
                   posts free), whale accumulation (snapshots only exist
                   from the week this system started storing them
                   forward), the false-pearl risk engine (GoPlus gives
                   current contract state, not historical state).
  This means a backtest "win" only validates the TECHNICAL CORE of a
  signal — the full live system (with news/whale/risk layers active)
  is a DIFFERENT, richer signal than what gets backtested here. Treat
  backtest hit rates as a floor/sanity-check on the technical logic,
  not a prediction of live performance.

NO-LOOKAHEAD DISCIPLINE: at simulated day t, only hist.iloc[:t+1] (data
up to and including day t) is ever passed to compute_indicators() or any
scoring function — this mirrors exactly how compute_indicators() reads
data live (always .iloc[-1], the most recent row), so slicing a longer
history up to day t reproduces exactly what the live system would have
seen on that day, no future data leakage.
"""
from __future__ import annotations
import logging
from typing import List, Optional

import numpy as np
import pandas as pd

from . import config as ccfg
from ..indicators import compute_indicators
from .regime import _trend_state, _volatility_state, _macro_score_from_regime

log = logging.getLogger("fortress.crypto.backtest")

TIMEOUT_DAYS = 21  # same horizon as the live outcome_tracker


def _simulate_trigger_score(hist_slice: pd.DataFrame, btc_slice: Optional[pd.DataFrame]) -> dict:
    """Reproduces the TECHNICAL portion of score_symbol()'s scoring logic
    exactly, using only data available up to the slice's last row. This
    intentionally mirrors workflows/sniper_daily_crypto.py's math — if
    that scoring logic changes, this function should be updated to match,
    or the backtest silently drifts from what's actually live."""
    if len(hist_slice) < 25:
        return {"valid": False}

    ind = compute_indicators(hist_slice)
    close = float(hist_slice["close"].iloc[-1])
    atr14 = ind.get("atr14", 0.0)
    if atr14 <= 0:
        atr14 = close * 0.02

    box_high = ind.get("box_high_20", 0.0)
    adv20 = float(hist_slice["volume"].tail(20).mean()) if "volume" in hist_slice.columns else 0.0
    vol_today = float(hist_slice["volume"].iloc[-1]) if "volume" in hist_slice.columns else 0.0
    vol_ratio = (vol_today / adv20) if adv20 > 0 else 0.0

    rsi = ind.get("rsi14", 50.0)
    adx = ind.get("adx14", 0.0)
    trigger_raw = min(100.0, max(0.0,
        (min(rsi, 70) / 70 * 40) +
        (min(adx, 40) / 40 * 30) +
        (min(vol_ratio, 3.0) / 3.0 * 30)
    ))

    # trend context (self, using own 7d/30d return since we don't have a
    # separate coin_snapshot in backtest — derived directly from price)
    ret_7d = None
    ret_30d = None
    if len(hist_slice) >= 8:
        ret_7d = round(100.0 * (close - float(hist_slice["close"].iloc[-8])) / float(hist_slice["close"].iloc[-8]), 2)
    if len(hist_slice) >= 31:
        ret_30d = round(100.0 * (close - float(hist_slice["close"].iloc[-31])) / float(hist_slice["close"].iloc[-31]), 2)

    trend_adj = 0.0
    if ret_30d is not None and ret_7d is not None:
        if ret_30d > 5 and ret_7d > 0:
            trend_adj = ccfg.TREND_ALIGNED_BONUS
        elif ret_30d < -15:
            trend_adj = -ccfg.TREND_AGAINST_PENALTY

    trigger_adjusted = max(0.0, min(100.0, trigger_raw + trend_adj))

    macro_score = 50.0
    if btc_slice is not None and len(btc_slice) >= 30:
        btc_ind = compute_indicators(btc_slice)
        t_state = _trend_state(btc_slice, btc_ind)
        v_state = _volatility_state(btc_slice, btc_ind)
        macro_score = _macro_score_from_regime(t_state["state"], v_state["state"])

    # simplified conviction: thesis=50 (neutral, no pearl thesis in backtest),
    # trigger=trigger_adjusted, macro=macro_score, entry=100 — same weights
    # as core/crypto/bridge_crypto.py:unified_conviction()
    conviction = round(max(0.0, min(100.0, (
        50.0 * ccfg.CONVICTION_W_THESIS +
        trigger_adjusted * ccfg.CONVICTION_W_TRIGGER +
        macro_score * ccfg.CONVICTION_W_MACRO +
        100.0 * ccfg.CONVICTION_W_ENTRY
    ) / 100.0)), 1)

    stop_loss = round(max(close - atr14 * ccfg.ATR_MULT_TREND, close * 0.75), 6)
    risk_per_unit = close - stop_loss
    r1 = round(close + risk_per_unit * 1.5, 6)
    r2 = round(close + risk_per_unit * 3.0, 6)

    return {"valid": True, "conviction": conviction, "close": close,
            "stop_loss": stop_loss, "r1": r1, "r2": r2}


def _resolve_simulated_signal(hist: pd.DataFrame, entry_idx: int, stop: float, r1: float, r2: float) -> dict:
    """Walk forward from entry_idx+1, same resolution rules as the live
    outcome_tracker: stop -> LOSS_STOP, r2 -> WIN_T2, r1 (without r2) held
    to timeout -> WIN_T1_HELD, neither within TIMEOUT_DAYS -> TIMEOUT."""
    entry_price = float(hist["close"].iloc[entry_idx])
    end_idx = min(entry_idx + TIMEOUT_DAYS, len(hist) - 1)
    hit_t1 = False

    for i in range(entry_idx + 1, end_idx + 1):
        low = float(hist["low"].iloc[i])
        high = float(hist["high"].iloc[i])
        if low <= stop:
            pnl = round(100.0 * (stop - entry_price) / entry_price, 2)
            return {"status": "LOSS_STOP", "pnl_pct": pnl, "days_held": i - entry_idx}
        if high >= r2:
            pnl = round(100.0 * (r2 - entry_price) / entry_price, 2)
            return {"status": "WIN_T2", "pnl_pct": pnl, "days_held": i - entry_idx}
        if high >= r1:
            hit_t1 = True

    exit_price = float(hist["close"].iloc[end_idx])
    pnl = round(100.0 * (exit_price - entry_price) / entry_price, 2)
    status = "WIN_T1_HELD" if hit_t1 else "TIMEOUT"
    return {"status": status, "pnl_pct": pnl, "days_held": end_idx - entry_idx}


def backtest_coin(symbol: str, hist: pd.DataFrame, btc_hist: Optional[pd.DataFrame],
                   min_conviction: float) -> List[dict]:
    """Walks forward day by day through hist, generating a simulated
    signal wherever conviction would have cleared min_conviction, then
    resolving it against actual subsequent price action. Skips days
    still within an open simulated position (no overlapping signals on
    the same coin) — matches how the live system wouldn't re-alert an
    already-active watchlist ignition."""
    if len(hist) < 60:
        return []

    trades = []
    next_eligible_idx = 30  # need enough history for indicators before first signal

    for t in range(30, len(hist) - 1):
        if t < next_eligible_idx:
            continue
        slice_ = hist.iloc[:t + 1]
        btc_slice = btc_hist.iloc[:t + 1] if btc_hist is not None and len(btc_hist) > t else None
        sig = _simulate_trigger_score(slice_, btc_slice)
        if not sig["valid"] or sig["conviction"] < min_conviction:
            continue

        outcome = _resolve_simulated_signal(hist, t, sig["stop_loss"], sig["r1"], sig["r2"])
        trades.append({
            "symbol": symbol, "entry_date": str(hist["date"].iloc[t].date()),
            "entry_price": sig["close"], "conviction": sig["conviction"],
            **outcome,
        })
        next_eligible_idx = t + outcome["days_held"] + 1  # no overlapping signals

    return trades


def summarize_backtest(all_trades: List[dict]) -> dict:
    """Same statistical shape as core/db.py:signal_stats() for easy
    side-by-side comparison — sample size, hit rate, avg return — but
    this dict must NEVER be written into the same table as live signals.
    Kept in-memory / reported separately, always labeled SIMULATED."""
    if not all_trades:
        return {"sample_size": 0, "hit_rate_pct": None, "avg_pnl_pct": None, "low_sample_warning": True}

    n = len(all_trades)
    wins = sum(1 for t in all_trades if t["status"] in ("WIN_T2", "WIN_T1_HELD"))
    pnls = [t["pnl_pct"] for t in all_trades if t.get("pnl_pct") is not None]

    return {
        "sample_size": n,
        "hit_rate_pct": round(100.0 * wins / n, 1) if n > 0 else None,
        "avg_pnl_pct": round(sum(pnls) / len(pnls), 2) if pnls else None,
        "low_sample_warning": n < 30,
        "status_breakdown": {s: sum(1 for t in all_trades if t["status"] == s)
                              for s in ("WIN_T2", "WIN_T1_HELD", "LOSS_STOP", "TIMEOUT")},
    }
