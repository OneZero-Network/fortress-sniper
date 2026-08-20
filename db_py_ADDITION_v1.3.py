def log_signal(signal: dict) -> int:
    """Called ONCE per alerted candidate, at the moment the Telegram alert
    fires. This is the top of the flywheel described by your mentor's
    item 7: Signal -> Prediction -> Actual outcome -> Why it failed ->
    Market regime -> Features responsible -> Model update. Everything
    that INFORMED the decision (trend label, news label, whale label,
    conviction, tier) is captured here at signal time — not reconstructed
    later from memory, which is how most systems quietly lose the ability
    to learn from their own mistakes. Returns the new row's id."""
    from datetime import datetime as _dt
    now = _dt.today().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn(write=True) as con:
        cur = con.execute("""
            INSERT INTO crypto_signal_log
                (symbol, tier, run_date, created_at, entry_price, stop_loss, r1, r2,
                 conviction, trigger_score, trend_label, news_label, forward_catalyst,
                 whale_label, is_pearl, ignited, status, target_low_pct, target_high_pct)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'OPEN',?,?)
        """, (
            signal["symbol"], signal["tier"], _dt.today().strftime("%Y-%m-%d"), now,
            signal["entry_price"], signal["stop_loss"], signal["r1"], signal["r2"],
            signal["conviction"], signal.get("trigger_score"), signal.get("trend_label"),
            signal.get("news_label"), signal.get("forward_catalyst"), signal.get("whale_label"),
            int(signal.get("is_pearl", False)), int(signal.get("ignited", False)),
            signal.get("target_low_pct"), signal.get("target_high_pct"),
        ))
        return cur.lastrowid


def get_open_signals() -> list:
    """All signals still awaiting resolution (haven't hit stop, T1, T2, or
    the timeout window). Checked and updated every run BEFORE new signals
    are scored — see outcome_tracker.py."""
    cols = ["id", "symbol", "tier", "run_date", "created_at", "entry_price", "stop_loss",
            "r1", "r2", "conviction", "trigger_score", "trend_label", "news_label",
            "forward_catalyst", "whale_label", "is_pearl", "ignited", "status",
            "target_low_pct", "target_high_pct"]
    with get_conn() as con:
        rows = con.execute(
            f"SELECT {', '.join(cols)} FROM crypto_signal_log WHERE status = 'OPEN'"
        ).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def resolve_signal(signal_id: int, status: str, exit_price: float, pnl_pct: float,
                    days_held: float, failure_reason: str = None) -> None:
    """status: WIN_T1 | WIN_T2 | LOSS_STOP | TIMEOUT. failure_reason is
    ONLY populated for LOSS/TIMEOUT — this is the 'Why it failed' step of
    the flywheel, filled in with whatever context is available (regime/
    trend at resolution time vs. at signal time), not left blank."""
    from datetime import datetime as _dt
    with get_conn(write=True) as con:
        con.execute("""
            UPDATE crypto_signal_log SET status=?, exit_price=?, pnl_pct=?,
                days_held=?, resolved_at=?, failure_reason=?
            WHERE id=?
        """, (status, exit_price, pnl_pct, days_held,
              _dt.today().strftime("%Y-%m-%d %H:%M:%S"), failure_reason, signal_id))


def signal_stats(lookback_days: int = 30) -> dict:
    """The honest numbers behind any probabilistic claim ('X% of similar
    setups won') — sample size, hit rate, avg return, by tier. Returns
    zeros/empty with a low sample-size flag rather than a confident stat
    when there isn't enough resolved history yet to say anything real."""
    from datetime import datetime as _dt, timedelta as _td
    cutoff = (_dt.today() - _td(days=lookback_days)).strftime("%Y-%m-%d")
    with get_conn() as con:
        rows = con.execute("""
            SELECT tier, status, pnl_pct FROM crypto_signal_log
            WHERE run_date >= ? AND status != 'OPEN'
        """, (cutoff,)).fetchall()

    by_tier = {}
    for tier, status, pnl in rows:
        by_tier.setdefault(tier, {"n": 0, "wins": 0, "pnls": []})
        by_tier[tier]["n"] += 1
        if status in ("WIN_T1", "WIN_T2"):
            by_tier[tier]["wins"] += 1
        if pnl is not None:
            by_tier[tier]["pnls"].append(pnl)

    out = {}
    for tier, d in by_tier.items():
        n = d["n"]
        out[tier] = {
            "sample_size": n,
            "hit_rate_pct": round(100.0 * d["wins"] / n, 1) if n > 0 else None,
            "avg_pnl_pct": round(sum(d["pnls"]) / len(d["pnls"]), 2) if d["pnls"] else None,
            "low_sample_warning": n < 20,
        }
    return out
