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


# ══════════════════════════════════════════════════════════════════════════
# V5 — REGIME-GATED TECHNICAL CORE (frozen, per explicit mandate)
# ══════════════════════════════════════════════════════════════════════════
# GATE, not weight. V2 asked "does regime improve the score." V5 asks
# "should the strategy be ALLOWED TO TRADE AT ALL outside its favorable
# regime." These are different hypotheses and must not be conflated.
#
# FROZEN RULES (do not alter without re-declaring a new experiment):
#   ENTRY: existing technical trigger (min_conviction on include_regime=
#          False scoring, i.e. the V1 baseline signal) AND regime label
#          == the target regime (e.g. "BULL/NORMAL_VOL")
#   EXIT:  same as V1 — 1.5R/3R, TIMEOUT_DAYS=21
#   COSTS: same ROUND_TRIP_COST_PCT as every other variant
# NO threshold optimization, no exit changes, no coin-specific rules —
# any of those would mean V5 is no longer testing the frozen hypothesis,
# it would be curve-fitting to this exact dataset.

def backtest_coin_regime_gated(symbol: str, hist: pd.DataFrame, btc_hist: Optional[pd.DataFrame],
                                 target_regime_label: str, min_conviction: float,
                                 r1_mult: float = 1.5, r2_mult: float = 3.0) -> List[dict]:
    """V5: entry requires BOTH the V1 technical trigger AND the regime
    gate. Regime score contribution is disabled (include_regime=False)
    during trigger evaluation — the regime's only role here is the GATE,
    not an additive score component, to keep this a genuinely different
    test from V2."""
    if len(hist) < 60:
        return []

    trades = []
    next_eligible_idx = 30

    for t in range(30, len(hist) - 1):
        if t < next_eligible_idx:
            continue
        slice_ = hist.iloc[:t + 1]
        btc_slice = btc_hist.iloc[:t + 1] if btc_hist is not None and len(btc_hist) > t else None

        sig = _simulate_trigger_score(slice_, btc_slice, include_regime=False)
        if not sig["valid"] or sig["conviction"] < min_conviction:
            continue
        if sig["regime_label"] != target_regime_label:
            continue

        outcome = _resolve_simulated_signal(hist, t, sig["stop_loss"], r1_mult, r2_mult)
        stop_distance_pct = round(100.0 * (sig["close"] - sig["stop_loss"]) / sig["close"], 4)
        r_multiple_net = round(outcome["pnl_pct_net"] / stop_distance_pct, 3) if stop_distance_pct > 0 else None
        trades.append({
            "symbol": symbol, "entry_date": str(hist["date"].iloc[t].date()),
            "entry_idx": t, "entry_price": sig["close"], "conviction": sig["conviction"],
            "regime_label": sig["regime_label"], "stop_distance_pct": stop_distance_pct,
            "r_multiple_net": r_multiple_net, **outcome,
        })
        next_eligible_idx = t + outcome["days_held"] + 1

    return trades


def sample_regime_matched_control(symbol: str, hist: pd.DataFrame, btc_hist: Optional[pd.DataFrame],
                                   target_regime_label: str, r1_mult: float = 1.5, r2_mult: float = 3.0,
                                   rng: Optional[np.random.Generator] = None) -> List[dict]:
    """V5-Control: EVERY eligible day in the target regime (no technical
    trigger required) becomes a candidate entry — random selection down
    to a matched sample size happens at the aggregation layer (see
    scripts/backtest_v5.py), not here, so this function stays a pure
    'what are all the possible regime-matched entries' enumerator.
    HONEST SIMPLIFICATION: unlike V5, control entries are allowed to
    overlap (no next_eligible_idx skip) since this is a statistical
    benchmark, not a capital-constrained portfolio simulation — flagged
    here rather than silently matching V5's non-overlap behavior and
    implying more rigor than exists."""
    if len(hist) < 60:
        return []

    candidates = []
    for t in range(30, len(hist) - 1):
        slice_ = hist.iloc[:t + 1]
        btc_slice = btc_hist.iloc[:t + 1] if btc_hist is not None and len(btc_hist) > t else None
        if btc_slice is None or len(btc_slice) < 30:
            continue
        btc_ind = compute_indicators(btc_slice)
        t_state = _trend_state(btc_slice, btc_ind)
        v_state = _volatility_state(btc_slice, btc_ind)
        label = f"{t_state['state']}/{v_state['state']}"
        if label != target_regime_label:
            continue

        close = float(hist["close"].iloc[t])
        ind = compute_indicators(slice_)
        atr14 = ind.get("atr14", 0.0) or close * 0.02
        stop_loss = round(max(close - atr14 * ccfg.ATR_MULT_TREND, close * 0.75), 6)
        outcome = _resolve_simulated_signal(hist, t, stop_loss, r1_mult, r2_mult)
        candidates.append({
            "symbol": symbol, "entry_date": str(hist["date"].iloc[t].date()),
            "entry_idx": t, "entry_price": close, "regime_label": label, **outcome,
        })

    return candidates


def matched_btc_return(btc_hist: Optional[pd.DataFrame], entry_idx: int, days_held: int) -> Optional[float]:
    """BTC's own buy-and-hold return over the SAME entry index and
    holding period as a given trade — the benchmark your mentor
    specifically asked for: 'is this strategy beating the market it's
    priced in, or just riding a bull market up.'"""
    if btc_hist is None or entry_idx >= len(btc_hist):
        return None
    exit_idx = min(entry_idx + days_held, len(btc_hist) - 1)
    if exit_idx <= entry_idx:
        return None
    entry_price = float(btc_hist["close"].iloc[entry_idx])
    exit_price = float(btc_hist["close"].iloc[exit_idx])
    if entry_price <= 0:
        return None
    return round(100.0 * (exit_price - entry_price) / entry_price, 2)


def compute_extended_stats(trades: List[dict], btc_hist: Optional[pd.DataFrame] = None) -> dict:
    """The full metrics list your mentor demanded — hit rate alone is
    not sufficient. Median return specifically matters because an
    average can hide '33 mediocre trades + 1 lucky +50%' behind a
    number that looks like broad success."""
    if not trades:
        return {"n": 0, "available": False}

    trades_sorted = sorted(trades, key=lambda t: t["entry_date"])
    net_returns = [t["pnl_pct_net"] for t in trades_sorted]
    n = len(net_returns)

    wins = [r for r in net_returns if r > 0]
    losses = [r for r in net_returns if r <= 0]
    hit_rate = round(100.0 * len(wins) / n, 1)

    gross_returns = [t["pnl_pct_raw"] for t in trades_sorted]
    gross_avg = round(float(np.mean(gross_returns)), 3)
    net_avg = round(float(np.mean(net_returns)), 3)
    net_median = round(float(np.median(net_returns)), 3)
    avg_winner = round(float(np.mean(wins)), 3) if wins else None
    avg_loser = round(float(np.mean(losses)), 3) if losses else None

    gross_win_sum = sum(r for r in net_returns if r > 0)
    gross_loss_sum = abs(sum(r for r in net_returns if r <= 0))
    profit_factor = round(gross_win_sum / gross_loss_sum, 2) if gross_loss_sum > 0 else None

    # Equity curve: equal-weighted, un-compounded cumulative sum of net
    # returns in entry-date order — a simplification (real position
    # sizing/compounding not modeled), stated plainly.
    cum = np.cumsum(net_returns)
    running_max = np.maximum.accumulate(cum)
    drawdown = cum - running_max
    max_drawdown = round(float(drawdown.min()), 2) if len(drawdown) else 0.0

    # Longest losing streak (consecutive net-negative trades, entry-date order)
    longest_losing_streak = 0
    current_streak = 0
    for r in net_returns:
        if r <= 0:
            current_streak += 1
            longest_losing_streak = max(longest_losing_streak, current_streak)
        else:
            current_streak = 0

    # Dispersion ratios — PER-TRADE, NOT time-annualized (trades aren't
    # evenly spaced in crypto backtests), flagged explicitly so this is
    # never mistaken for a conventional annualized Sharpe.
    std = float(np.std(net_returns)) if n > 1 else 0.0
    sharpe_per_trade = round(net_avg / std, 3) if std > 0 else None
    downside = [r for r in net_returns if r < 0]
    downside_std = float(np.std(downside)) if len(downside) > 1 else 0.0
    sortino_per_trade = round(net_avg / downside_std, 3) if downside_std > 0 else None

    avg_exposure_days = round(float(np.mean([t["days_held"] for t in trades_sorted])), 1)

    btc_relative = None
    if btc_hist is not None:
        btc_rets = []
        for t in trades_sorted:
            if "entry_idx" in t:
                br = matched_btc_return(btc_hist, t["entry_idx"], t["days_held"])
                if br is not None:
                    btc_rets.append(t["pnl_pct_net"] - br)
        if btc_rets:
            btc_relative = round(float(np.mean(btc_rets)), 3)

    by_coin = {}
    for t in trades_sorted:
        by_coin.setdefault(t["symbol"], []).append(t["pnl_pct_net"])
    per_coin_avg = {sym: round(float(np.mean(rets)), 2) for sym, rets in by_coin.items()}

    return {
        "n": n, "available": True,
        "hit_rate_pct": hit_rate,
        "gross_avg_pct": gross_avg, "net_avg_pct": net_avg, "net_median_pct": net_median,
        "avg_winner_pct": avg_winner, "avg_loser_pct": avg_loser,
        "profit_factor": profit_factor,
        "max_drawdown_pct": max_drawdown,
        "longest_losing_streak": longest_losing_streak,
        "sharpe_per_trade": sharpe_per_trade, "sortino_per_trade": sortino_per_trade,
        "avg_exposure_days": avg_exposure_days,
        "btc_relative_avg_pct": btc_relative,
        "per_coin_avg_pct": per_coin_avg,
        "low_sample_warning": n < 30,
    }


def leave_one_coin_out(trades: List[dict], btc_hist: Optional[pd.DataFrame] = None) -> dict:
    """For each coin present in the trade set, recompute stats with that
    coin excluded. If removing ONE coin swings net_avg_pct dramatically,
    the 'edge' is that coin's idiosyncratic performance, not a general
    regime effect — exactly the check your mentor demanded before
    trusting any conditional result with n<50."""
    symbols = sorted({t["symbol"] for t in trades})
    out = {}
    for sym in symbols:
        remaining = [t for t in trades if t["symbol"] != sym]
        out[sym] = compute_extended_stats(remaining, btc_hist)
    return out


# ══════════════════════════════════════════════════════════════════════════
# BACKTEST MECHANICS AUDIT — the -96%/-76% drawdowns needed inspection
# before being trusted, per explicit instruction. This is a research
# infrastructure check, not strategy optimization.
# ══════════════════════════════════════════════════════════════════════════
# ROOT CAUSE, confirmed: the original max_drawdown_pct in
# compute_extended_stats() sums each trade's PERCENT RETURN ON ITS OWN
# ENTRY PRICE arithmetically — i.e. it implicitly assumes every trade
# risks a FULL, EQUAL-SIZED unit of capital, with no position sizing and
# no compounding. 18 trades averaging -5% arithmetically sum to -90%,
# which is exactly what produced the -96% figure. That is NOT a
# portfolio simulation bug (no double-counting, no leverage error) — it
# is a METHODOLOGY GAP: the original metric never modeled position
# sizing at all. This function fixes that by converting each trade to an
# R-multiple (return relative to its OWN stop distance, i.e. genuine risk
# unit) and applying a fixed-fractional COMPOUNDED equity curve at
# ACCOUNT_RISK_PCT per trade (0.75%, same value already used for live
# position sizing — not a new number invented for this audit).

def compute_risk_adjusted_drawdown(trades: List[dict], account_risk_pct: float = None) -> dict:
    """Returns BOTH the naive arithmetic-sum drawdown (kept for
    comparison, explicitly labeled as NOT representing real portfolio
    risk) and a risk-adjusted compounded equity curve assuming a fixed
    account_risk_pct per trade.

    HONEST LIMITATION stated directly: this still does not cap
    simultaneous open positions across different coins — if V5 fires on
    5 coins at once, this treats them as sequential risk draws on the
    same equity curve, not as concurrent exposure. That overstates
    diversification benefit and understates real simultaneous-position
    risk. A true portfolio simulation needs max-concurrent-exposure
    limits, which is a further, larger build not done here."""
    from . import config as ccfg
    account_risk_pct = account_risk_pct or ccfg.ACCOUNT_RISK_PCT * 100  # config stores as fraction (0.0075), audit reports in %

    valid_trades = [t for t in trades if t.get("r_multiple_net") is not None]
    if not valid_trades:
        return {"available": False, "reason": "no trades with stop_distance_pct recorded"}

    trades_sorted = sorted(valid_trades, key=lambda t: t["entry_date"])
    net_returns = [t["pnl_pct_net"] for t in trades_sorted]

    # naive (original) method — kept for direct comparison
    naive_cum = np.cumsum(net_returns)
    naive_max_dd = round(float((naive_cum - np.maximum.accumulate(naive_cum)).min()), 2) if len(naive_cum) else 0.0

    # risk-adjusted, compounded equity curve at fixed fractional risk
    equity = 100.0
    equity_curve = [equity]
    for t in trades_sorted:
        account_return_pct = account_risk_pct * t["r_multiple_net"]  # % of ACCOUNT, not of trade notional
        equity *= (1 + account_return_pct / 100.0)
        equity_curve.append(equity)
    equity_arr = np.array(equity_curve)
    running_max = np.maximum.accumulate(equity_arr)
    dd_pct = (equity_arr - running_max) / running_max * 100.0
    risk_adjusted_max_dd = round(float(dd_pct.min()), 2)
    final_equity_return_pct = round(equity - 100.0, 2)

    return {
        "available": True,
        "naive_arithmetic_max_dd_pct": naive_max_dd,
        "naive_method_caveat": "sums trade returns as if each risks 100% of a full equal-sized unit — NOT a real portfolio metric",
        "risk_adjusted_max_dd_pct": risk_adjusted_max_dd,
        "risk_adjusted_final_return_pct": final_equity_return_pct,
        "risk_adjusted_assumption": f"{account_risk_pct:.2f}% account risk per trade, compounded, sequential (no concurrent-position cap)",
        "n_trades": len(trades_sorted),
    }


# ══════════════════════════════════════════════════════════════════════════
# REGIME CLASSIFIER AUDIT — "don't ask the classifier if the market is
# BULL, ask the market directly." For every gated entry, checks what
# actually happened to BTC over the SAME forward window the trade was
# held — this is safe to compute with future data for AUDIT purposes
# (we are not trading on it, only evaluating the classifier's own past
# calibration).
# ══════════════════════════════════════════════════════════════════════════

def regime_classifier_audit(trades: List[dict], btc_hist: Optional[pd.DataFrame]) -> dict:
    """For every trade gated as target_regime (e.g. BULL/NORMAL_VOL),
    checks whether BTC's OWN price actually rose over that trade's
    holding window. Reports what fraction of 'favorable' classifications
    were followed by BTC actually going up — a calibration check, not a
    full confusion matrix (a true confusion matrix would need an
    equal-effort audit of days the classifier called UNFAVORABLE too,
    which is a larger scope not built here — flagged, not silently
    skipped)."""
    if btc_hist is None or not trades:
        return {"available": False, "reason": "no BTC history or no trades to audit"}

    rows = []
    for t in trades:
        if "entry_idx" not in t:
            continue
        entry_idx = t["entry_idx"]
        days_held = t["days_held"]
        if entry_idx >= len(btc_hist):
            continue
        exit_idx = min(entry_idx + days_held, len(btc_hist) - 1)
        if exit_idx <= entry_idx:
            continue
        btc_entry = float(btc_hist["close"].iloc[entry_idx])
        btc_exit = float(btc_hist["close"].iloc[exit_idx])
        btc_fwd_return_pct = round(100.0 * (btc_exit - btc_entry) / btc_entry, 2) if btc_entry > 0 else None
        if btc_fwd_return_pct is None:
            continue
        rows.append({
            "symbol": t["symbol"], "entry_date": t["entry_date"],
            "regime_label_at_entry": t.get("regime_label"),
            "btc_fwd_return_pct": btc_fwd_return_pct,
            "btc_actually_rose": btc_fwd_return_pct > 0,
        })

    if not rows:
        return {"available": False, "reason": "no matchable BTC forward windows"}

    n = len(rows)
    btc_rose_count = sum(1 for r in rows if r["btc_actually_rose"])
    avg_btc_fwd_return = round(float(np.mean([r["btc_fwd_return_pct"] for r in rows])), 2)
    median_btc_fwd_return = round(float(np.median([r["btc_fwd_return_pct"] for r in rows])), 2)

    return {
        "available": True, "n": n,
        "pct_where_btc_actually_rose": round(100.0 * btc_rose_count / n, 1),
        "avg_btc_forward_return_pct": avg_btc_fwd_return,
        "median_btc_forward_return_pct": median_btc_fwd_return,
        "interpretation": ("classifier's BULL/NORMAL_VOL call was followed by BTC actually falling "
                            "more often than not — the regime label itself may be miscalibrated"
                            if btc_rose_count < n / 2 else
                            "classifier's BULL/NORMAL_VOL call was followed by BTC rising more often "
                            "than not — regime detection appears directionally reasonable, though this "
                            "is a partial audit (favorable calls only, no confusion matrix vs unfavorable calls)"),
    }


# ══════════════════════════════════════════════════════════════════════════
# DISTRIBUTION / TOP-WINNER-REMOVAL ANALYSIS — "is the apparent edge a
# few lucky big winners, or broad-based." Removes the top N winners and
# recomputes the average each time; if the edge evaporates quickly, it
# was concentrated in a handful of outlier trades, not real breadth.
# ══════════════════════════════════════════════════════════════════════════

def top_winner_removal_analysis(trades: List[dict], remove_ns: List[int] = None) -> dict:
    remove_ns = remove_ns or [1, 2, 5]
    valid = [t for t in trades if t.get("pnl_pct_net") is not None]
    if not valid:
        return {"available": False}

    sorted_desc = sorted(valid, key=lambda t: t["pnl_pct_net"], reverse=True)
    baseline_avg = round(float(np.mean([t["pnl_pct_net"] for t in valid])), 3)

    results = {"baseline_avg_pct": baseline_avg, "baseline_n": len(valid), "after_removal": {}}
    for k in remove_ns:
        if k >= len(sorted_desc):
            results["after_removal"][k] = None
            continue
        remaining = sorted_desc[k:]
        avg_after = round(float(np.mean([t["pnl_pct_net"] for t in remaining])), 3) if remaining else None
        results["after_removal"][k] = {
            "n_remaining": len(remaining), "avg_pct": avg_after,
            "top_removed_returns": [round(t["pnl_pct_net"], 2) for t in sorted_desc[:k]],
        }
    results["available"] = True
    return results
