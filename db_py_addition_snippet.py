def init_crypto_tables() -> None:
    """Crypto tables live in the SAME SQLite file as the equity tables
    (shared outputs/fortress_unified.db) but under a distinct prefix
    (crypto_*) — no shared rows, deliberately kept separate schemas since
    a 'symbol' collision between an NSE ticker and a crypto symbol must
    never cross-contaminate either bridge. Call this once at the start of
    any crypto workflow, same pattern as init_db() for equity tables."""
    with get_conn(write=True) as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS crypto_pearl_watchlist (
            symbol              TEXT PRIMARY KEY,
            coin_id             TEXT,
            added_date          TEXT,
            last_confirmed      TEXT,
            thesis              TEXT,
            box_high            REAL,
            box_low             REAL,
            ath                 REAL,
            ath_change_pct      REAL,
            incubator_score     REAL,
            pearl_grade         TEXT,
            category_tags       TEXT,
            onchain_flags       TEXT,
            sharia_compliant    INTEGER,
            status              TEXT DEFAULT 'ACTIVE',
            ignited_date        TEXT,
            ignited_price       REAL
        );

        CREATE TABLE IF NOT EXISTS crypto_outcomes (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol              TEXT, run_date TEXT, source TEXT,
            pearl_pedigree      INTEGER DEFAULT 0,
            entry_price         REAL, stop_loss REAL, r1 REAL, r2 REAL, r3 REAL,
            exit_price          REAL, exit_date TEXT, status TEXT DEFAULT 'open',
            pnl_pct             REAL, conviction_score REAL
        );

        CREATE TABLE IF NOT EXISTS crypto_score_cache (
            symbol      TEXT,
            date_label  TEXT,
            close       REAL,
            result_json TEXT,
            created_at  TEXT,
            PRIMARY KEY (symbol, date_label)
        );
        """)
    log.info(f"Crypto tables initialized in {DB_PATH}")
