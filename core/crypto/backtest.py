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


def _simulate_trigger_score(hist_slice: pd.DataFrame, btc_slice: Optional[pd.DataFrame],
                             include_regime: bool = True) -> dict:
    """Reproduces the TECHNICAL portion of score_symbol()'s scoring logic
    exactly, using only data available up to the slice's last row. This
    intentionally mirrors workflows/sniper_daily_crypto.py's math — if
    that scoring logic changes, this function should be updated to match,
    or the backtest silently drifts from what's actually live.

    include_regime=False disables the macro_score contribution (forces
    it to neutral 50.0) — this is the ablation toggle that lets the
    experiment matrix isolate 'does regime awareness itself add value'
    from 'is the base technical trigger any good at all'."""
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
    regime_label = "N/A"
    if include_regime and btc_slice is not None and len(btc_slice) >= 30:
        btc_ind = compute_indicators(btc_slice)
        t_state = _trend_state(btc_slice, btc_ind)
        v_state = _volatility_state(btc_slice, btc_ind)
        macro_score = _macro_score_from_regime(t_state["state"], v_state["state"])
        regime_label = f"{t_state['state']}/{v_state['state']}"
    elif btc_slice is not None and len(btc_slice) >= 30:
        # still compute the label for reporting even when its SCORE
        # contribution is disabled — needed for regime-conditioned
        # breakdown of the technical-only variant too
        btc_ind = compute_indicators(btc_slice)
        t_state = _trend_state(btc_slice, btc_ind)
        v_state = _volatility_state(btc_slice, btc_ind)
        regime_label = f"{t_state['state']}/{v_state['state']}"

    conviction = round(max(0.0, min(100.0, (
        50.0 * ccfg.CONVICTION_W_THESIS +
        trigger_adjusted * ccfg.CONVICTION_W_TRIGGER +
        macro_score * ccfg.CONVICTION_W_MACRO +
        100.0 * ccfg.CONVICTION_W_ENTRY
    ) / 100.0)), 1)

    stop_loss = round(max(close - atr14 * ccfg.ATR_MULT_TREND, close * 0.75), 6)

    return {"valid": True, "conviction": conviction, "close": close,
            "stop_loss": stop_loss, "atr14": atr14, "regime_label": regime_label}


# ══════════════════════════════════════════════════════════════════════════
# TRANSACTION COSTS — a backtest with zero fees/slippage can manufacture
# an edge that disappears the moment real money touches it. These are
# conservative, round-trip assumptions for a liquid-enough coin (the
# universe here is already liquidity-filtered by MIN_24H_VOLUME_USD), not
# a precise model of any specific exchange's actual fee schedule.
# ══════════════════════════════════════════════════════════════════════════
TAKER_FEE_PCT = 0.10      # per side, typical spot taker fee
SLIPPAGE_PCT = 0.15       # per side, conservative estimate for liquid-tier coins
ROUND_TRIP_COST_PCT = 2 * (TAKER_FEE_PCT + SLIPPAGE_PCT)  # entry + exit, both legs


def _resolve_simulated_signal(hist: pd.DataFrame, entry_idx: int, stop: float,
                               r1_mult: float, r2_mult: float) -> dict:
    """Walk forward from entry_idx+1. r1_mult/r2_mult are the R-multiples
    used for targets (e.g. 1.5/3.0), now a PARAMETER instead of hardcoded
    — this is what makes the exit-matrix experiment possible: same entry
    signal, different exit math, to isolate whether a bad result comes
    from the SIGNAL or the EXIT structure."""
    entry_price = float(hist["close"].iloc[entry_idx])
    risk_per_unit = entry_price - stop
    r1 = entry_price + risk_per_unit * r1_mult
    r2 = entry_price + risk_per_unit * r2_mult
    end_idx = min(entry_idx + TIMEOUT_DAYS, len(hist) - 1)
    hit_t1 = False

    for i in range(entry_idx + 1, end_idx + 1):
        low = float(hist["low"].iloc[i])
        high = float(hist["high"].iloc[i])
        if low <= stop:
            raw_pnl = 100.0 * (stop - entry_price) / entry_price
            return {"status": "LOSS_STOP", "pnl_pct_raw": round(raw_pnl, 2),
                    "pnl_pct_net": round(raw_pnl - ROUND_TRIP_COST_PCT, 2), "days_held": i - entry_idx}
        if high >= r2:
            raw_pnl = 100.0 * (r2 - entry_price) / entry_price
            return {"status": "WIN_T2", "pnl_pct_raw": round(raw_pnl, 2),
                    "pnl_pct_net": round(raw_pnl - ROUND_TRIP_COST_PCT, 2), "days_held": i - entry_idx}
        if high >= r1:
            hit_t1 = True

    exit_price = float(hist["close"].iloc[end_idx])
    raw_pnl = 100.0 * (exit_price - entry_price) / entry_price
    status = "WIN_T1_HELD" if hit_t1 else "TIMEOUT"
    return {"status": status, "pnl_pct_raw": round(raw_pnl, 2),
            "pnl_pct_net": round(raw_pnl - ROUND_TRIP_COST_PCT, 2), "days_held": end_idx - entry_idx}


def backtest_coin(symbol: str, hist: pd.DataFrame, btc_hist: Optional[pd.DataFrame],
                   min_conviction: float, include_regime: bool = True,
                   r1_mult: float = 1.5, r2_mult: float = 3.0) -> List[dict]:
    """Walks forward day by day through hist, generating a simulated
    signal wherever conviction would have cleared min_conviction, then
    resolving it against actual subsequent price action. Skips days
    still within an open simulated position (no overlapping signals on
    the same coin). include_regime/r1_mult/r2_mult are the experiment-
    matrix parameters — same entry logic, different ablation/exit
    variants, to distinguish 'bad signal' from 'bad exit structure'
    from 'regime interaction matters'."""
    if len(hist) < 60:
        return []

    trades = []
    next_eligible_idx = 30

    for t in range(30, len(hist) - 1):
        if t < next_eligible_idx:
            continue
        slice_ = hist.iloc[:t + 1]
        btc_slice = btc_hist.iloc[:t + 1] if btc_hist is not None and len(btc_hist) > t else None
        sig = _simulate_trigger_score(slice_, btc_slice, include_regime=include_regime)
        if not sig["valid"] or sig["conviction"] < min_conviction:
            continue

        outcome = _resolve_simulated_signal(hist, t, sig["stop_loss"], r1_mult, r2_mult)
        trades.append({
            "symbol": symbol, "entry_date": str(hist["date"].iloc[t].date()),
            "entry_price": sig["close"], "conviction": sig["conviction"],
            "regime_label": sig["regime_label"],
            **outcome,
        })
        next_eligible_idx = t + outcome["days_held"] + 1

    return trades


def summarize_backtest(all_trades: List[dict]) -> dict:
    """Same statistical shape as core/db.py:signal_stats() for easy
    side-by-side comparison — sample size, hit rate, avg return — but
    this dict must NEVER be written into the same table as live signals.
    Kept in-memory / reported separately, always labeled SIMULATED.

    Reports BOTH raw and cost-adjusted (net of fees+slippage) average
    return — per your mentor's explicit warning that a backtest ignoring
    transaction costs can manufacture an edge that disappears live."""
    if not all_trades:
        return {"sample_size": 0, "hit_rate_pct": None, "avg_pnl_pct_raw": None,
                "avg_pnl_pct_net": None, "low_sample_warning": True}

    n = len(all_trades)
    wins = sum(1 for t in all_trades if t["status"] in ("WIN_T2", "WIN_T1_HELD"))
    raw_pnls = [t["pnl_pct_raw"] for t in all_trades if t.get("pnl_pct_raw") is not None]
    net_pnls = [t["pnl_pct_net"] for t in all_trades if t.get("pnl_pct_net") is not None]

    return {
        "sample_size": n,
        "hit_rate_pct": round(100.0 * wins / n, 1) if n > 0 else None,
        "avg_pnl_pct_raw": round(sum(raw_pnls) / len(raw_pnls), 2) if raw_pnls else None,
        "avg_pnl_pct_net": round(sum(net_pnls) / len(net_pnls), 2) if net_pnls else None,
        "low_sample_warning": n < 30,
        "status_breakdown": {s: sum(1 for t in all_trades if t["status"] == s)
                              for s in ("WIN_T2", "WIN_T1_HELD", "LOSS_STOP", "TIMEOUT")},
    }


def summarize_by_regime(all_trades: List[dict]) -> dict:
    """The regime-conditioned breakdown your mentor asked for explicitly:
    'your technical model isn't necessarily useless, it may be a
    bull-regime strategy incorrectly deployed across all regimes.' This
    is the function that would surface that if it's true."""
    by_regime: dict = {}
    for t in all_trades:
        label = t.get("regime_label", "N/A")
        by_regime.setdefault(label, []).append(t)

    out = {}
    for label, trades in by_regime.items():
        out[label] = summarize_backtest(trades)
    return out
