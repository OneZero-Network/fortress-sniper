-- Paste this INSIDE the init_crypto_tables() function's executescript("""...""")
-- block, right before the closing """) — same spot as the whale_snapshots
-- table you added last time.

CREATE TABLE IF NOT EXISTS crypto_signal_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol              TEXT,
    tier                TEXT,             -- FORTRESS | SWING
    run_date            TEXT,
    created_at          TEXT,
    entry_price         REAL,
    stop_loss           REAL,
    r1                  REAL,
    r2                  REAL,
    conviction          REAL,
    trigger_score       REAL,
    trend_label         TEXT,
    news_label          TEXT,
    forward_catalyst    TEXT,
    whale_label         TEXT,
    is_pearl            INTEGER DEFAULT 0,
    ignited             INTEGER DEFAULT 0,
    target_low_pct      REAL,
    target_high_pct     REAL,
    status              TEXT DEFAULT 'OPEN',  -- OPEN | WIN_T1 | WIN_T2 | LOSS_STOP | TIMEOUT
    exit_price          REAL,
    pnl_pct             REAL,
    days_held           REAL,
    resolved_at         TEXT,
    failure_reason      TEXT
);
