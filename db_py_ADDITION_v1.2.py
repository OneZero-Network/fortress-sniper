def save_whale_snapshot(symbol: str, chain: str, top1_pct: float, top10_pct: float) -> None:
    """One row per (symbol, date) — lets whale_accumulation_delta() compare
    this week's holder concentration against the most recent prior
    snapshot to detect real accumulation/distribution, not just a
    single-point-in-time read."""
    from datetime import datetime as _dt
    today = _dt.today().strftime("%Y-%m-%d")
    with get_conn(write=True) as con:
        con.execute("""
            INSERT INTO crypto_whale_snapshots (symbol, chain, snapshot_date, top1_pct, top10_pct)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(symbol, snapshot_date) DO UPDATE SET
                chain=excluded.chain, top1_pct=excluded.top1_pct, top10_pct=excluded.top10_pct
        """, (symbol.upper(), chain, today, top1_pct, top10_pct))


def get_previous_whale_snapshot(symbol: str, before_date: str = None) -> dict:
    """Most recent snapshot strictly before today (or before_date), for
    delta comparison. Returns {} if no prior snapshot exists (first time
    seeing this symbol — accumulation delta can't be computed yet, and
    the caller must treat that as 'no signal', not 'no accumulation')."""
    from datetime import datetime as _dt
    cutoff = before_date or _dt.today().strftime("%Y-%m-%d")
    with get_conn() as con:
        row = con.execute("""
            SELECT snapshot_date, top1_pct, top10_pct FROM crypto_whale_snapshots
            WHERE symbol = ? AND snapshot_date < ?
            ORDER BY snapshot_date DESC LIMIT 1
        """, (symbol.upper(), cutoff)).fetchone()
    if not row:
        return {}
    return {"snapshot_date": row[0], "top1_pct": row[1], "top10_pct": row[2]}
