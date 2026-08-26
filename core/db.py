"""
FORTRESS_UNIFIED — core/db.py
══════════════════════════════════════════════════════════════════════════════
Single SQLite database shared by all three entrypoints. Consolidates what
were previously two separate DBs (sniper_cache.db, incubator's own tables)
into one schema so the meta-labeler, outcome tracker, and pearl watchlist
all see the same history.

New table vs. either legacy script: `pearl_watchlist` — the persistent
bridge between Incubator (writer) and Sniper (reader) described in the
architecture plan.
"""
from __future__ import annotations
import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger("fortress.db")

DB_PATH = Path(os.getenv("FORTRESS_DB_PATH", "outputs/fortress_unified.db"))


@contextmanager
def get_conn(write: bool = False, timeout: int = 10):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH), timeout=timeout)
    try:
        yield con
        if write:
            con.commit()
    finally:
        con.close()


def init_db() -> None:
    with get_conn(write=True) as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS llm_cache (
            text_hash   TEXT PRIMARY KEY,
            prompt_type TEXT,
            result      TEXT,
            created_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS score_cache (
            symbol      TEXT,
            date_label  TEXT,
            close       REAL,
            intel_hash  TEXT,
            result_json TEXT,
            created_at  TEXT,
            PRIMARY KEY (symbol, date_label)
        );

        CREATE TABLE IF NOT EXISTS meta_labels (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol            TEXT, run_date TEXT,
            fort_pts REAL, apex_comp REAL, fused REAL, bayes_pct REAL,
            rsi14 REAL, adx14 REAL, mfi REAL, atr14 REAL, atr_mult REAL,
            whale_score REAL, delivery_pct REAL, vol_ratio REAL, rs_pct REAL,
            at_vpoc INTEGER, whale_flag INTEGER, has_catalyst INTEGER,
            vix_val REAL, advance_ratio REAL, confidence_score REAL,
            pearl_pedigree INTEGER DEFAULT 0, ignition_detected INTEGER DEFAULT 0,
            outcome INTEGER
        );

        -- ═══ THE BRIDGE ═══ Incubator writes here; Sniper reads here daily.
        CREATE TABLE IF NOT EXISTS pearl_watchlist (
            symbol            TEXT PRIMARY KEY,
            added_date        TEXT,
            last_confirmed    TEXT,
            thesis            TEXT,
            box_high          REAL,
            box_low           REAL,
            high_52w          REAL,
            low_52w           REAL,
            ma200             REAL,
            incubator_score   REAL,
            pearl_grade       TEXT,
            sector            TEXT,
            quality_flags     TEXT,
            sharia_compliant  INTEGER,
            status            TEXT DEFAULT 'ACTIVE',   -- ACTIVE | IGNITED | STALE | REMOVED
            ignited_date      TEXT,
            ignited_price     REAL
        );

        CREATE TABLE IF NOT EXISTS outcomes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol          TEXT, run_date TEXT, source TEXT,  -- source: SNIPER | INCUBATOR
            pearl_pedigree  INTEGER DEFAULT 0,
            entry_price     REAL, stop_loss REAL, r1 REAL, r2 REAL, r3 REAL,
            exit_price      REAL, exit_date TEXT, status TEXT DEFAULT 'open',
            pnl_pct         REAL, conviction_score REAL
        );
        """)
    log.info(f"DB initialized at {DB_PATH}")


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

        CREATE TABLE IF NOT EXISTS crypto_whale_snapshots (
            symbol          TEXT,
            chain           TEXT,
            snapshot_date   TEXT,
            top1_pct        REAL,
            top10_pct       REAL,
            PRIMARY KEY (symbol, snapshot_date)
        );

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

        CREATE TABLE IF NOT EXISTS crypto_layer_observations (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol                TEXT,
            coin_id               TEXT,
            observed_date         TEXT,
            price_at_observation  REAL,
            whale_label           TEXT,
            whale_top10_delta_pct REAL,
            news_label            TEXT,
            news_score            REAL,
            forward_return_7d_pct  REAL,
            forward_return_14d_pct REAL,
            forward_return_21d_pct REAL,
            resolved_7d           INTEGER DEFAULT 0,
            resolved_14d          INTEGER DEFAULT 0,
            resolved_21d          INTEGER DEFAULT 0,
            UNIQUE(symbol, observed_date)
        );

        -- ═══ PEARL FLYWHEEL (v2.8) ═══ The discovery snapshot columns
        -- (everything through invalidation_conditions) are IMMUTABLE —
        -- written once at INSERT, never UPDATEd. Only the resolution
        -- columns (price_Nd/return_Nd/resolved_Nd) and lifecycle_state/
        -- failure_reason are ever touched after creation. This is
        -- deliberate: overwriting a discovery score with hindsight would
        -- silently corrupt the very dataset this table exists to build.
        CREATE TABLE IF NOT EXISTS crypto_pearl_observations (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol                  TEXT,
            coin_id                 TEXT,
            observed_at             TEXT,
            price_at_observation    REAL,
            discovery_score         REAL,
            evidence_level          INTEGER,
            evidence_label          TEXT,
            whale_score             REAL,
            whale_label_at_discovery TEXT,
            news_score              REAL,
            news_label_at_discovery TEXT,
            liquidity_score         REAL,
            structure_score         REAL,
            onchain_score           REAL,
            false_pearl_risk_pct    INTEGER,
            risk_severity_at_discovery TEXT,
            status_at_discovery     TEXT,
            tier_at_discovery       TEXT,
            pearl_type_at_discovery TEXT,
            why_it_surfaced         TEXT,
            invalidation_conditions TEXT,
            -- resolution columns — appended over time, never backfilled early
            price_24h               REAL, return_24h_pct  REAL, resolved_24h INTEGER DEFAULT 0,
            price_3d                REAL, return_3d_pct   REAL, resolved_3d  INTEGER DEFAULT 0,
            price_7d                REAL, return_7d_pct   REAL, resolved_7d  INTEGER DEFAULT 0,
            price_14d               REAL, return_14d_pct  REAL, resolved_14d INTEGER DEFAULT 0,
            price_30d               REAL, return_30d_pct  REAL, resolved_30d INTEGER DEFAULT 0,
            -- lifecycle — the only mutable narrative fields
            lifecycle_state         TEXT DEFAULT 'UNDER_OBSERVATION',
            -- DISCOVERED -> CANDIDATE -> UNDER_OBSERVATION -> (THESIS_HOLDS|INVALIDATED) -> (CONFIRMED|FAILED)
            invalidated_at          TEXT,
            failure_reason          TEXT,
            terminal_return_pct     REAL
        );

        -- ═══ v3.1 MEASUREMENT SCAFFOLD ═══ One row per calendar day.
        -- data_period_label lets you tag which days belong to which
        -- experiment ('FREE_BASELINE', 'PAID_WHALE', etc) — set via the
        -- CRYPTO_DATA_PERIOD_LABEL env var, defaults to FREE_BASELINE.
        CREATE TABLE IF NOT EXISTS crypto_daily_metrics (
            date                        TEXT PRIMARY KEY,
            data_period_label           TEXT DEFAULT 'FREE_BASELINE',
            assets_scanned              INTEGER,
            entered_scorer              INTEGER,
            avg_completeness_pct        REAL,
            median_completeness_pct     REAL,
            high_potential_count        INTEGER,
            pearl_count                 INTEGER,
            candidate_count             INTEGER,
            watch_count                 INTEGER,
            false_pearl_count           INTEGER,
            missing_data_rejection_count INTEGER,
            insufficient_evidence_count INTEGER,
            top_pearl_score             REAL,
            top_high_potential_score    REAL,
            avg_discovery_score         REAL
        );

        -- ═══ v4.6 BASE DEX FIRST-SEEN TRACKING ═══ Records the EXACT
        -- first moment Fortress's DEX lens detected a pair — this is
        -- what makes "could the DEX lens have found PONS earlier than
        -- CoinGecko" an answerable question rather than a guess.
        -- INSERT OR IGNORE semantics: only the true first detection is
        -- ever stored, never overwritten by later scans.
        CREATE TABLE IF NOT EXISTS crypto_dex_first_seen (
            pair_address        TEXT PRIMARY KEY,
            symbol              TEXT,
            chain               TEXT,
            first_seen_at       TEXT,
            first_seen_price    REAL,
            first_seen_liquidity_usd REAL,
            first_seen_volume_24h_usd REAL,
            first_seen_buys     INTEGER,
            first_seen_sells    INTEGER,
            first_seen_txns     INTEGER,
            first_seen_pair_age_hours REAL,
            first_seen_vol_accel_ratio REAL,
            first_seen_flow_label TEXT,
            first_seen_security_status TEXT,
            is_early_move_at_discovery INTEGER DEFAULT 0,
            -- v4.7 resolution columns — appended over time, mirroring the
            -- proven crypto_pearl_observations pattern. Running max/min
            -- are updated at each check, never backfilled early.
            price_1h  REAL, return_1h_pct  REAL, resolved_1h  INTEGER DEFAULT 0,
            price_6h  REAL, return_6h_pct  REAL, resolved_6h  INTEGER DEFAULT 0,
            price_24h REAL, return_24h_pct REAL, resolved_24h INTEGER DEFAULT 0,
            price_3d  REAL, return_3d_pct  REAL, resolved_3d  INTEGER DEFAULT 0,
            price_7d  REAL, return_7d_pct  REAL, resolved_7d  INTEGER DEFAULT 0,
            max_upside_pct       REAL,
            max_drawdown_pct     REAL,
            liquidity_change_pct REAL,
            volume_change_pct    REAL,
            security_status_changed INTEGER DEFAULT 0,
            last_checked_at      TEXT
        );

        -- ═══ v4.7.6 STAGE HISTORY LOG ═══ Unlike crypto_dex_first_seen
        -- (immutable, one row EVER per pair), this logs EVERY scan's
        -- classification for EVERY candidate that passes activity+
        -- security — not just Early Moves. This is what makes 'did a
        -- BUILDING candidate later graduate to EARLY_MOVE' an answerable
        -- question instead of a guess: if AERO shows BUILDING at 10am
        -- and EARLY_MOVE at 4pm, both rows exist here, in order.
        CREATE TABLE IF NOT EXISTS crypto_dex_stage_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            pair_address    TEXT,
            symbol          TEXT,
            observed_at     TEXT,
            stage           TEXT,
            conditions_met  INTEGER,
            pct_24h         REAL,
            liquidity_usd   REAL
        );

        -- ═══ v4.9.8 CHAIN-EVENT DISCOVERY CURSOR ═══ Single-row table
        -- tracking the last Base block number scanned for new-pool
        -- creation events. This is what makes chain-native discovery
        -- incremental — each run only looks at blocks since the last
        -- scan, not the whole chain history every time.
        CREATE TABLE IF NOT EXISTS crypto_dex_chain_cursor (
            id                  INTEGER PRIMARY KEY CHECK (id = 1),
            last_scanned_block  INTEGER,
            last_scanned_at     TEXT
        );

        -- ═══ v4.9.13 MULTI-DEX CURSOR ═══ The v4.9.8 singleton cursor
        -- table only supported ONE chain-event source (Uniswap V3).
        -- Aerodrome needs its own independent cursor — a new table,
        -- keyed by dex_name, rather than a risky schema change to the
        -- existing singleton (which stays in place, harmlessly unused
        -- going forward).
        CREATE TABLE IF NOT EXISTS crypto_dex_chain_cursor_v2 (
            dex_name            TEXT PRIMARY KEY,
            last_scanned_block  INTEGER,
            last_scanned_at     TEXT
        );

        -- ═══ v4.9.15 FULL LIFECYCLE LEDGER ═══ Reverse-engineered from
        -- the actual target question: "does Fortress detect assets
        -- before they move, and by how much lead time — with nothing
        -- silently dropped?" INSERT-ONLY, one row per (candidate, scan),
        -- so no scoring event can ever vanish between discovery and
        -- final disposition. discovery_id is the permanent handle a
        -- report can follow across every table this candidate touches.
        CREATE TABLE IF NOT EXISTS crypto_dex_lifecycle (
            discovery_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            pair_address         TEXT,
            symbol               TEXT,
            source               TEXT,          -- CHAIN_EVENT_UNISWAP_V3 | CHAIN_EVENT_AERODROME | SEARCH | BOOSTED | ...
            observed_at          TEXT,
            pool_age_hours       REAL,           -- discovery latency: how old was the pool when Fortress first saw it
            liquidity_usd        REAL,
            volume_24h_usd       REAL,
            pct_24h              REAL,
            pair_new             INTEGER,        -- 1/0 — was the "new pair" condition met
            liquidity_accel      INTEGER,        -- 1/0
            volume_accel         INTEGER,        -- 1/0
            tx_accel             INTEGER,        -- 1/0
            buy_pressure         INTEGER,        -- 1/0
            price_near_base      INTEGER,        -- 1/0
            already_extended     INTEGER,        -- 1/0
            security_severity    TEXT,
            pre_pearl_score      REAL,
            classification       TEXT,           -- 🟢 PRE-PEARL | 🟡 BUILDING | 👀 WATCH | ⚫ IGNORE | 🚫 BLOCKED
            breakdown_json       TEXT            -- the full human-readable scoring breakdown, verbatim
        );
        """)
        # Self-migrating column addition for databases created before this
        # column existed — avoids another manual paste-into-GitHub step.
        # Safe no-op if the column is already present.
        try:
            con.execute("ALTER TABLE crypto_pearl_observations ADD COLUMN tier_at_discovery TEXT")
            con.commit()
            log.info("Migrated: added tier_at_discovery column to crypto_pearl_observations")
        except Exception:
            pass  # column already exists — expected on every run after the first
        try:
            con.execute("ALTER TABLE crypto_pearl_observations ADD COLUMN pearl_type_at_discovery TEXT")
            con.commit()
            log.info("Migrated: added pearl_type_at_discovery column to crypto_pearl_observations")
        except Exception:
            pass  # column already exists — expected on every run after the first

        # v4.7 — new columns on crypto_dex_first_seen (table introduced in
        # v4.6, so existing deployments need these added, not just created)
        dex_new_columns = [
            ("is_early_move_at_discovery", "INTEGER DEFAULT 0"),
            ("first_seen_volume_24h_usd", "REAL"), ("first_seen_buys", "INTEGER"),
            ("first_seen_sells", "INTEGER"), ("first_seen_txns", "INTEGER"),
            ("first_seen_security_status", "TEXT"),
            ("price_1h", "REAL"), ("return_1h_pct", "REAL"), ("resolved_1h", "INTEGER DEFAULT 0"),
            ("price_6h", "REAL"), ("return_6h_pct", "REAL"), ("resolved_6h", "INTEGER DEFAULT 0"),
            ("price_24h", "REAL"), ("return_24h_pct", "REAL"), ("resolved_24h", "INTEGER DEFAULT 0"),
            ("price_3d", "REAL"), ("return_3d_pct", "REAL"), ("resolved_3d", "INTEGER DEFAULT 0"),
            ("price_7d", "REAL"), ("return_7d_pct", "REAL"), ("resolved_7d", "INTEGER DEFAULT 0"),
            ("max_upside_pct", "REAL"), ("max_drawdown_pct", "REAL"),
            ("liquidity_change_pct", "REAL"), ("volume_change_pct", "REAL"),
            ("security_status_changed", "INTEGER DEFAULT 0"), ("last_checked_at", "TEXT"),
        ]
        for col_name, col_type in dex_new_columns:
            try:
                con.execute(f"ALTER TABLE crypto_dex_first_seen ADD COLUMN {col_name} {col_type}")
                con.commit()
            except Exception:
                pass  # column already exists — expected on every run after the first

        # v4.9.12 — liquidity tracking on crypto_dex_stage_log (table
        # introduced in v4.7.6, needs this added for existing deployments)
        try:
            con.execute("ALTER TABLE crypto_dex_stage_log ADD COLUMN liquidity_usd REAL")
            con.commit()
        except Exception:
            pass  # column already exists — expected on every run after the first
    log.info(f"Crypto tables initialized in {DB_PATH}")


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


def save_layer_observation(symbol: str, coin_id: str, price: float,
                            whale_label: str = None, whale_top10_delta_pct: float = None,
                            news_label: str = None, news_score: float = None) -> None:
    """W1/N1 forward-observation logger — one row per (symbol, date),
    recording whale/news signal state independent of whether the
    technical trigger fired. This is how the predictive-value question
    ('does whale accumulation forecast forward returns') gets answered
    honestly: no historical whale/news data exists to backtest against
    (CryptoPanic doesn't serve history free, whale snapshots only exist
    forward from when this system started storing them), so the dataset
    has to be built going forward from today, one day at a time."""
    from datetime import datetime as _dt
    today = _dt.today().strftime("%Y-%m-%d")
    with get_conn(write=True) as con:
        con.execute("""
            INSERT INTO crypto_layer_observations
                (symbol, coin_id, observed_date, price_at_observation,
                 whale_label, whale_top10_delta_pct, news_label, news_score)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol, observed_date) DO UPDATE SET
                price_at_observation=excluded.price_at_observation,
                whale_label=excluded.whale_label, whale_top10_delta_pct=excluded.whale_top10_delta_pct,
                news_label=excluded.news_label, news_score=excluded.news_score
        """, (symbol.upper(), coin_id, today, price, whale_label, whale_top10_delta_pct,
              news_label, news_score))


def get_unresolved_observations(horizon: str) -> list:
    """horizon: '7d' | '14d' | '21d'. Returns observations old enough for
    that horizon to have elapsed but not yet resolved."""
    from datetime import datetime as _dt, timedelta as _td
    days = {"7d": 7, "14d": 14, "21d": 21}[horizon]
    cutoff = (_dt.today() - _td(days=days)).strftime("%Y-%m-%d")
    col = f"resolved_{horizon}"
    cols = ["id", "symbol", "coin_id", "observed_date", "price_at_observation",
            "whale_label", "news_label"]
    with get_conn() as con:
        rows = con.execute(
            f"SELECT {', '.join(cols)} FROM crypto_layer_observations "
            f"WHERE observed_date <= ? AND {col} = 0",
            (cutoff,)
        ).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def resolve_layer_observation(obs_id: int, horizon: str, forward_return_pct: float) -> None:
    col_val = f"forward_return_{horizon}_pct"
    col_flag = f"resolved_{horizon}"
    with get_conn(write=True) as con:
        con.execute(f"UPDATE crypto_layer_observations SET {col_val}=?, {col_flag}=1 WHERE id=?",
                     (forward_return_pct, obs_id))


def get_resolved_observations(horizon: str) -> list:
    col_val = f"forward_return_{horizon}_pct"
    col_flag = f"resolved_{horizon}"
    with get_conn() as con:
        rows = con.execute(
            f"SELECT symbol, whale_label, news_label, {col_val} FROM crypto_layer_observations "
            f"WHERE {col_flag} = 1 AND {col_val} IS NOT NULL"
        ).fetchall()
    return [{"symbol": r[0], "whale_label": r[1], "news_label": r[2], "forward_return_pct": r[3]} for r in rows]


def save_pearl_observation(snapshot: dict) -> int:
    """The immutable discovery snapshot. Written ONCE. Every field here
    (discovery_score, whale_score, news_score, etc.) is a fact about what
    the machine believed AT THE MOMENT OF DISCOVERY — it must never be
    updated later, or the dataset silently becomes hindsight-biased.
    Returns the new row's id, used to attach resolutions later."""
    from datetime import datetime as _dt
    now = _dt.today().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn(write=True) as con:
        cur = con.execute("""
            INSERT INTO crypto_pearl_observations
                (symbol, coin_id, observed_at, price_at_observation, discovery_score,
                 evidence_level, evidence_label, whale_score, whale_label_at_discovery,
                 news_score, news_label_at_discovery, liquidity_score, structure_score,
                 onchain_score, false_pearl_risk_pct, risk_severity_at_discovery,
                 status_at_discovery, tier_at_discovery, pearl_type_at_discovery,
                 why_it_surfaced, invalidation_conditions)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            snapshot["symbol"], snapshot["coin_id"], now, snapshot["price_at_observation"],
            snapshot["discovery_score"], snapshot["evidence_level"], snapshot["evidence_label"],
            snapshot.get("whale_score"), snapshot.get("whale_label_at_discovery"),
            snapshot.get("news_score"), snapshot.get("news_label_at_discovery"),
            snapshot.get("liquidity_score"), snapshot.get("structure_score"),
            snapshot.get("onchain_score"), snapshot["false_pearl_risk_pct"],
            snapshot["risk_severity_at_discovery"], snapshot["status_at_discovery"],
            snapshot.get("tier_at_discovery"), snapshot.get("pearl_type_at_discovery"),
            snapshot["why_it_surfaced"], snapshot["invalidation_conditions"],
        ))
        return cur.lastrowid


def get_pearl_observations_due(horizon: str) -> list:
    """horizon: '24h'|'3d'|'7d'|'14d'|'30d'. Returns snapshots old enough
    for this horizon but not yet resolved AND not already terminally
    INVALIDATED (once invalidated, we stop re-checking — the thesis
    already failed, further price wobbling doesn't un-invalidate it)."""
    from datetime import datetime as _dt, timedelta as _td
    hours = {"24h": 1, "3d": 3, "7d": 7, "14d": 14, "30d": 30}
    days = hours[horizon] if horizon != "24h" else 1
    cutoff = (_dt.today() - _td(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    col = f"resolved_{horizon}"
    cols = ["id", "symbol", "coin_id", "observed_at", "price_at_observation",
            "whale_label_at_discovery", "risk_severity_at_discovery", "lifecycle_state"]
    with get_conn() as con:
        rows = con.execute(
            f"SELECT {', '.join(cols)} FROM crypto_pearl_observations "
            f"WHERE observed_at <= ? AND {col} = 0 AND lifecycle_state != 'INVALIDATED'",
            (cutoff,)
        ).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def resolve_pearl_observation(obs_id: int, horizon: str, price: float, return_pct: float,
                               new_lifecycle_state: str = None, failure_reason: str = None,
                               terminal_return_pct: float = None) -> None:
    """Appends a resolution — never touches the immutable discovery
    columns. lifecycle_state/failure_reason/invalidated_at are the ONLY
    narrative fields allowed to change after creation, and only forward
    (see core/crypto/pearl_flywheel.py for the state-transition rules)."""
    from datetime import datetime as _dt
    price_col, return_col, resolved_col = f"price_{horizon}", f"return_{horizon}_pct", f"resolved_{horizon}"
    with get_conn(write=True) as con:
        if new_lifecycle_state == "INVALIDATED":
            con.execute(f"""
                UPDATE crypto_pearl_observations
                SET {price_col}=?, {return_col}=?, {resolved_col}=1,
                    lifecycle_state=?, failure_reason=?, invalidated_at=?
                WHERE id=?
            """, (price, return_pct, new_lifecycle_state, failure_reason,
                  _dt.today().strftime("%Y-%m-%d %H:%M:%S"), obs_id))
        elif new_lifecycle_state:
            con.execute(f"""
                UPDATE crypto_pearl_observations
                SET {price_col}=?, {return_col}=?, {resolved_col}=1,
                    lifecycle_state=?, terminal_return_pct=?
                WHERE id=?
            """, (price, return_pct, new_lifecycle_state, terminal_return_pct, obs_id))
        else:
            con.execute(f"""
                UPDATE crypto_pearl_observations
                SET {price_col}=?, {return_col}=?, {resolved_col}=1
                WHERE id=?
            """, (price, return_pct, obs_id))


def get_pearl_flywheel_stats() -> dict:
    """Aggregate lifecycle outcomes — the honest answer to 'was the
    machine right,' built from real resolved history, not assumption."""
    with get_conn() as con:
        rows = con.execute(
            "SELECT lifecycle_state, COUNT(*) FROM crypto_pearl_observations GROUP BY lifecycle_state"
        ).fetchall()
    return {state: count for state, count in rows}


def save_daily_metrics(metrics: dict) -> None:
    """One row per calendar day — INSERT OR REPLACE so a re-run on the
    same day overwrites rather than duplicates. data_period_label is the
    tag that lets the rollup compare 'FREE_BASELINE' days against
    'PAID_WHALE' (or whichever) days later."""
    from datetime import datetime as _dt
    today = _dt.today().strftime("%Y-%m-%d")
    with get_conn(write=True) as con:
        con.execute("""
            INSERT INTO crypto_daily_metrics
                (date, data_period_label, assets_scanned, entered_scorer,
                 avg_completeness_pct, median_completeness_pct, high_potential_count,
                 pearl_count, candidate_count, watch_count, false_pearl_count,
                 missing_data_rejection_count, insufficient_evidence_count,
                 top_pearl_score, top_high_potential_score, avg_discovery_score)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(date) DO UPDATE SET
                data_period_label=excluded.data_period_label,
                assets_scanned=excluded.assets_scanned, entered_scorer=excluded.entered_scorer,
                avg_completeness_pct=excluded.avg_completeness_pct,
                median_completeness_pct=excluded.median_completeness_pct,
                high_potential_count=excluded.high_potential_count, pearl_count=excluded.pearl_count,
                candidate_count=excluded.candidate_count, watch_count=excluded.watch_count,
                false_pearl_count=excluded.false_pearl_count,
                missing_data_rejection_count=excluded.missing_data_rejection_count,
                insufficient_evidence_count=excluded.insufficient_evidence_count,
                top_pearl_score=excluded.top_pearl_score, top_high_potential_score=excluded.top_high_potential_score,
                avg_discovery_score=excluded.avg_discovery_score
        """, (today, metrics.get("data_period_label", "FREE_BASELINE"),
              metrics["assets_scanned"], metrics["entered_scorer"],
              metrics.get("avg_completeness_pct"), metrics.get("median_completeness_pct"),
              metrics["high_potential_count"], metrics["pearl_count"], metrics["candidate_count"],
              metrics["watch_count"], metrics["false_pearl_count"],
              metrics["missing_data_rejection_count"], metrics["insufficient_evidence_count"],
              metrics.get("top_pearl_score"), metrics.get("top_high_potential_score"),
              metrics.get("avg_discovery_score")))


def get_daily_metrics_by_period(period_label: str) -> list:
    cols = ["date", "assets_scanned", "entered_scorer", "avg_completeness_pct",
            "median_completeness_pct", "high_potential_count", "pearl_count", "candidate_count",
            "watch_count", "false_pearl_count", "missing_data_rejection_count",
            "insufficient_evidence_count", "top_pearl_score", "top_high_potential_score",
            "avg_discovery_score"]
    with get_conn() as con:
        rows = con.execute(
            f"SELECT {', '.join(cols)} FROM crypto_daily_metrics WHERE data_period_label=? ORDER BY date",
            (period_label,)
        ).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def get_pearl_quality_by_tier() -> dict:
    """The metric your mentor specifically warned we'd be missing
    without it: does a higher tier actually perform better forward, or
    are we just relabeling? Groups resolved pearl observations by
    tier_at_discovery and reports average return at each horizon."""
    with get_conn() as con:
        rows = con.execute("""
            SELECT tier_at_discovery, return_24h_pct, return_3d_pct, return_7d_pct,
                   resolved_24h, resolved_3d, resolved_7d, lifecycle_state
            FROM crypto_pearl_observations
            WHERE tier_at_discovery IS NOT NULL
        """).fetchall()

    by_tier: dict = {}
    for tier, r24, r3d, r7d, res24, res3d, res7d, lifecycle in rows:
        d = by_tier.setdefault(tier, {"n": 0, "r24": [], "r3d": [], "r7d": [], "invalidated": 0})
        d["n"] += 1
        if res24 and r24 is not None:
            d["r24"].append(r24)
        if res3d and r3d is not None:
            d["r3d"].append(r3d)
        if res7d and r7d is not None:
            d["r7d"].append(r7d)
        if lifecycle == "INVALIDATED":
            d["invalidated"] += 1

    out = {}
    for tier, d in by_tier.items():
        out[tier] = {
            "n": d["n"], "invalidated_count": d["invalidated"],
            "avg_return_24h": round(sum(d["r24"]) / len(d["r24"]), 2) if d["r24"] else None,
            "avg_return_3d": round(sum(d["r3d"]) / len(d["r3d"]), 2) if d["r3d"] else None,
            "avg_return_7d": round(sum(d["r7d"]) / len(d["r7d"]), 2) if d["r7d"] else None,
            "n_resolved_24h": len(d["r24"]), "n_resolved_3d": len(d["r3d"]), "n_resolved_7d": len(d["r7d"]),
        }
    return out


def get_symbol_persistence(symbol: str) -> dict:
    """v3.9 — Persistence + Time-to-Discovery. Built entirely from data
    already being logged by save_pearl_observation() — no new table.
    Answers: has this symbol kept reappearing on the radar, and for how
    long? A Pearl may not look like 'high score today, price up
    tomorrow' — it may look like an asset that PERSISTS on the radar
    across many days before a catalyst or the market catches up. This
    is pure measurement, not a scoring input — nothing here feeds
    discovery_score or Pearl Priority."""
    with get_conn() as con:
        rows = con.execute("""
            SELECT observed_at, discovery_score, tier_at_discovery FROM crypto_pearl_observations
            WHERE symbol = ? ORDER BY observed_at ASC
        """, (symbol.upper(),)).fetchall()

    if not rows:
        return {"times_seen": 0, "first_seen": None, "days_in_radar": 0, "tier_trend": []}

    from datetime import datetime as _dt
    first_seen = rows[0][0]
    last_seen = rows[-1][0]
    try:
        first_dt = _dt.strptime(first_seen.split(" ")[0], "%Y-%m-%d")
        last_dt = _dt.strptime(last_seen.split(" ")[0], "%Y-%m-%d")
        days_in_radar = (last_dt - first_dt).days
    except Exception:
        days_in_radar = None

    return {
        "times_seen": len(rows),
        "first_seen": first_seen,
        "days_in_radar": days_in_radar,
        "tier_trend": [r[2] for r in rows[-5:]],  # last 5 tier classifications, oldest->newest
        "score_trend": [r[1] for r in rows[-5:]],
    }


def get_pearl_type_outcomes(days_back: int = 14) -> dict:
    """v4.4 — Pearl Validation Report data source #1. Groups resolved
    observations by pearl_type_at_discovery (Early Pearl / Emergence /
    Momentum) and reports outcome buckets: hit +20%/+10% within 7d,
    thesis held (not invalidated) vs invalidated. This is the report
    your mentor asked for BEFORE any threshold tuning — evidence, not
    another feature."""
    from datetime import datetime as _dt, timedelta as _td
    cutoff = (_dt.today() - _td(days=days_back)).strftime("%Y-%m-%d")
    with get_conn() as con:
        rows = con.execute("""
            SELECT pearl_type_at_discovery, return_7d_pct, resolved_7d, lifecycle_state
            FROM crypto_pearl_observations
            WHERE observed_at >= ? AND pearl_type_at_discovery IS NOT NULL
        """, (cutoff,)).fetchall()

    by_type: dict = {}
    for ptype, r7d, resolved, lifecycle in rows:
        d = by_type.setdefault(ptype, {"n": 0, "n_resolved_7d": 0, "hit_20pct": 0, "hit_10pct": 0,
                                        "held_thesis": 0, "invalidated": 0})
        d["n"] += 1
        if lifecycle == "INVALIDATED":
            d["invalidated"] += 1
        elif lifecycle in ("CONFIRMED", "UNDER_OBSERVATION"):
            d["held_thesis"] += 1
        if resolved and r7d is not None:
            d["n_resolved_7d"] += 1
            if r7d >= 20:
                d["hit_20pct"] += 1
            if r7d >= 10:
                d["hit_10pct"] += 1

    out = {}
    for ptype, d in by_type.items():
        n7 = d["n_resolved_7d"]
        out[ptype] = {
            "n_discovered": d["n"],
            "n_resolved_7d": n7,
            "pct_hit_20": round(100.0 * d["hit_20pct"] / n7, 1) if n7 else None,
            "pct_hit_10": round(100.0 * d["hit_10pct"] / n7, 1) if n7 else None,
            "pct_held_thesis": round(100.0 * d["held_thesis"] / d["n"], 1) if d["n"] else None,
            "pct_invalidated": round(100.0 * d["invalidated"] / d["n"], 1) if d["n"] else None,
        }
    return out


def get_emergence_conversion_rate(days_back: int = 14) -> dict:
    """v4.4 — Pearl Validation Report data source #2. For every symbol
    that FIRST appeared as an EMERGENCE ALERT, checks whether it EVER
    later appeared as an EARLY PEARL or HIGH_POTENTIAL — answering
    'how often does an Emergence Alert become something genuinely
    interesting.' This is a real, if approximate, conversion-funnel
    measurement built entirely from data already logged."""
    from datetime import datetime as _dt, timedelta as _td
    cutoff = (_dt.today() - _td(days=days_back)).strftime("%Y-%m-%d")
    with get_conn() as con:
        rows = con.execute("""
            SELECT symbol, observed_at, pearl_type_at_discovery, tier_at_discovery
            FROM crypto_pearl_observations
            WHERE observed_at >= ?
            ORDER BY symbol, observed_at ASC
        """, (cutoff,)).fetchall()

    by_symbol: dict = {}
    for symbol, observed_at, ptype, tier in rows:
        by_symbol.setdefault(symbol, []).append({"observed_at": observed_at, "pearl_type": ptype, "tier": tier})

    emergence_first = [sym for sym, history in by_symbol.items()
                       if history and history[0]["pearl_type"] == "⚡ EMERGENCE ALERT"]
    converted = 0
    for sym in emergence_first:
        history = by_symbol[sym]
        if any(h["pearl_type"] == "💎 EARLY PEARL" or h["tier"] == "HIGH_POTENTIAL" for h in history[1:]):
            converted += 1

    n = len(emergence_first)
    return {
        "n_emergence_first_seen": n,
        "n_converted": converted,
        "conversion_rate_pct": round(100.0 * converted / n, 1) if n else None,
    }


def log_dex_first_seen(pair_address: str, symbol: str, chain: str, price: float, liquidity_usd: float,
                        volume_24h_usd: float, buys: int, sells: int, pair_age_hours: float,
                        vol_accel_ratio: float, flow_label: str, security_status: str,
                        is_early_move: bool = False) -> bool:
    """v4.7 — full first-seen snapshot, per explicit instruction: 'we
    need to know exactly what Fortress knew at the moment of discovery'
    — otherwise a later look at PONS would falsely claim early detection
    without the receipts. INSERT OR IGNORE: only the TRUE first
    detection is ever stored. Returns True if this was genuinely new.

    v4.7.4: is_early_move records whether THIS candidate was classified
    as a full DEX EARLY MOVE at the moment of discovery — needed to
    later classify outcomes as SUCCESS/NO EDGE (an asset that moved a
    lot but was NEVER called an early move is 'no edge,' not a failure
    of the early-move thesis, since no thesis was ever made)."""
    from datetime import datetime as _dt
    now = _dt.today().strftime("%Y-%m-%d %H:%M:%S")
    txns = (buys or 0) + (sells or 0)
    with get_conn(write=True) as con:
        cur = con.execute("""
            INSERT OR IGNORE INTO crypto_dex_first_seen
                (pair_address, symbol, chain, first_seen_at, first_seen_price,
                 first_seen_liquidity_usd, first_seen_volume_24h_usd, first_seen_buys,
                 first_seen_sells, first_seen_txns, first_seen_pair_age_hours,
                 first_seen_vol_accel_ratio, first_seen_flow_label, first_seen_security_status,
                 is_early_move_at_discovery)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (pair_address, symbol.upper(), chain, now, price, liquidity_usd, volume_24h_usd,
              buys, sells, txns, pair_age_hours, vol_accel_ratio, flow_label, security_status,
              int(is_early_move)))
        return cur.rowcount > 0


def get_dex_first_seen(pair_address: str = None, symbol: str = None) -> Optional[dict]:
    """Look up by pair_address (preferred, unique) or symbol (may match
    multiple pairs — returns the earliest)."""
    cols = ["pair_address", "symbol", "chain", "first_seen_at", "first_seen_price",
            "first_seen_liquidity_usd", "first_seen_volume_24h_usd", "first_seen_buys",
            "first_seen_sells", "first_seen_txns", "first_seen_pair_age_hours",
            "first_seen_vol_accel_ratio", "first_seen_flow_label", "first_seen_security_status",
            "return_1h_pct", "return_6h_pct", "return_24h_pct", "return_3d_pct", "return_7d_pct",
            "max_upside_pct", "max_drawdown_pct", "security_status_changed"]
    with get_conn() as con:
        if pair_address:
            row = con.execute(
                f"SELECT {', '.join(cols)} FROM crypto_dex_first_seen WHERE pair_address = ?",
                (pair_address,)
            ).fetchone()
        elif symbol:
            row = con.execute(
                f"SELECT {', '.join(cols)} FROM crypto_dex_first_seen WHERE symbol = ? "
                f"ORDER BY first_seen_at ASC LIMIT 1",
                (symbol.upper(),)
            ).fetchone()
        else:
            return None
    return dict(zip(cols, row)) if row else None


def get_dex_pairs_due_for_resolution(horizon: str) -> list:
    """horizon: '1h'|'6h'|'24h'|'3d'|'7d'. Returns first-seen records old
    enough for this horizon but not yet resolved at it."""
    from datetime import datetime as _dt, timedelta as _td
    hours = {"1h": 1, "6h": 6, "24h": 24, "3d": 72, "7d": 168}
    cutoff = (_dt.today() - _td(hours=hours[horizon])).strftime("%Y-%m-%d %H:%M:%S")
    col = f"resolved_{horizon}"
    cols = ["pair_address", "symbol", "chain", "first_seen_at", "first_seen_price",
            "first_seen_liquidity_usd", "first_seen_volume_24h_usd", "first_seen_security_status",
            "max_upside_pct", "max_drawdown_pct", "is_early_move_at_discovery"]
    with get_conn() as con:
        rows = con.execute(
            f"SELECT {', '.join(cols)} FROM crypto_dex_first_seen WHERE first_seen_at <= ? AND {col} = 0",
            (cutoff,)
        ).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def resolve_dex_pair(pair_address: str, horizon: str, price: float, return_pct: float,
                      liquidity_usd: float = None, volume_24h_usd: float = None,
                      security_status: str = None) -> None:
    """v4.7 — appends a resolution AND updates running max_upside/
    max_drawdown across the pair's whole tracked history — these are
    running extremes, not point-in-time values, so they're read-modify-
    written here rather than computed fresh each time."""
    from datetime import datetime as _dt
    now = _dt.today().strftime("%Y-%m-%d %H:%M:%S")
    price_col, return_col, resolved_col = f"price_{horizon}", f"return_{horizon}_pct", f"resolved_{horizon}"

    with get_conn() as con:
        row = con.execute(
            "SELECT max_upside_pct, max_drawdown_pct, first_seen_liquidity_usd, "
            "first_seen_volume_24h_usd, first_seen_security_status FROM crypto_dex_first_seen "
            "WHERE pair_address = ?", (pair_address,)
        ).fetchone()
    if not row:
        return
    prev_max_up, prev_max_dd, first_liq, first_vol, first_security = row
    new_max_up = max(prev_max_up or 0, return_pct)
    new_max_dd = min(prev_max_dd or 0, return_pct)

    liq_change_pct = round(100.0 * (liquidity_usd - first_liq) / first_liq, 1) if liquidity_usd and first_liq else None
    vol_change_pct = round(100.0 * (volume_24h_usd - first_vol) / first_vol, 1) if volume_24h_usd and first_vol else None
    security_changed = 1 if (security_status and first_security and security_status != first_security) else 0

    with get_conn(write=True) as con:
        con.execute(f"""
            UPDATE crypto_dex_first_seen
            SET {price_col}=?, {return_col}=?, {resolved_col}=1,
                max_upside_pct=?, max_drawdown_pct=?, last_checked_at=?,
                liquidity_change_pct=COALESCE(?, liquidity_change_pct),
                volume_change_pct=COALESCE(?, volume_change_pct),
                security_status_changed=CASE WHEN ?=1 THEN 1 ELSE security_status_changed END
            WHERE pair_address=?
        """, (price, return_pct, new_max_up, new_max_dd, now,
              liq_change_pct, vol_change_pct, security_changed, pair_address))


def get_dex_lead_time_vs_coingecko(symbol: str) -> dict:
    """v4.7 — the specific comparison your mentor asked for: did the DEX
    lens detect this symbol BEFORE the CoinGecko-sourced Pearl engine
    did? Compares first_seen_at (DEX) against the earliest observed_at
    for the same symbol in crypto_pearl_observations (CoinGecko lens).
    Positive lead_time_hours means DEX detected it first."""
    with get_conn() as con:
        dex_row = con.execute(
            "SELECT first_seen_at FROM crypto_dex_first_seen WHERE symbol = ? "
            "ORDER BY first_seen_at ASC LIMIT 1", (symbol.upper(),)
        ).fetchone()
        cg_row = con.execute(
            "SELECT observed_at FROM crypto_pearl_observations WHERE symbol = ? "
            "ORDER BY observed_at ASC LIMIT 1", (symbol.upper(),)
        ).fetchone()

    if not dex_row or not cg_row:
        return {"available": False, "detail": "missing data from one or both lenses"}

    from datetime import datetime as _dt
    dex_time = _dt.strptime(dex_row[0], "%Y-%m-%d %H:%M:%S")
    cg_time = _dt.strptime(cg_row[0], "%Y-%m-%d %H:%M:%S")
    lead_hours = round((cg_time - dex_time).total_seconds() / 3600.0, 1)

    return {"available": True, "dex_first_seen": dex_row[0], "coingecko_first_seen": cg_row[0],
            "lead_time_hours": lead_hours,
            "detail": (f"DEX detected {lead_hours}h before CoinGecko lens" if lead_hours > 0
                       else f"CoinGecko detected {-lead_hours}h before DEX lens" if lead_hours < 0
                       else "both lenses detected at the same time")}


def log_dex_stage(pair_address: str, symbol: str, stage: str, conditions_met: int, pct_24h: float,
                   liquidity_usd: float = None) -> None:
    """v4.7.6 — one row per scan, per candidate that passes activity+
    security (not just Early Moves). This is the append-only log the
    near-miss flywheel needs — INSERT only, never updated, so the full
    stage history for a pair is reconstructable in order.

    v4.9.12: now also records liquidity_usd, so a genuine liquidity-
    growth signal can be computed from real prior scans instead of
    guessed at on first sight (there's no baseline to compare against
    the very first time a pair is seen)."""
    from datetime import datetime as _dt
    now = _dt.today().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn(write=True) as con:
        con.execute("""
            INSERT INTO crypto_dex_stage_log (pair_address, symbol, observed_at, stage, conditions_met, pct_24h, liquidity_usd)
            VALUES (?,?,?,?,?,?,?)
        """, (pair_address, symbol.upper(), now, stage, conditions_met, pct_24h, liquidity_usd))


def get_dex_prior_liquidity(pair_address: str) -> Optional[float]:
    """v4.9.12 — most recent PRIOR liquidity reading for this pair, used
    to compute a genuine liquidity-growth-rate signal. Returns None if
    this pair has never been scanned before — the caller must treat that
    as 'unknown,' not 'liquidity is not growing.'

    Orders by id DESC, not just observed_at DESC — same-second scans
    (a real occurrence, second-precision timestamps can tie) would
    otherwise make 'most recent' ambiguous; id is a monotonically
    increasing autoincrement key, so it always breaks ties correctly."""
    with get_conn() as con:
        row = con.execute("""
            SELECT liquidity_usd FROM crypto_dex_stage_log
            WHERE pair_address = ? AND liquidity_usd IS NOT NULL
            ORDER BY observed_at DESC, id DESC LIMIT 1
        """, (pair_address,)).fetchone()
    return row[0] if row else None


def get_dex_stage_history(pair_address: str) -> list:
    """Full stage history for one pair, oldest first — lets you see the
    BUILDING → EARLY_MOVE progression (or lack of it) directly."""
    cols = ["observed_at", "stage", "conditions_met", "pct_24h"]
    with get_conn() as con:
        rows = con.execute(
            f"SELECT {', '.join(cols)} FROM crypto_dex_stage_log WHERE pair_address = ? ORDER BY observed_at ASC",
            (pair_address,)
        ).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def get_dex_graduations(days_back: int = 7) -> list:
    """v4.7.6 — the specific question the near-miss flywheel exists to
    answer: which pairs were classified BUILDING at some point and LATER
    showed EARLY_MOVE for the SAME pair. This is direct evidence about
    whether the BUILDING state is a real precursor signal or just noise —
    built from data already being logged, no new API calls."""
    from datetime import datetime as _dt, timedelta as _td
    cutoff = (_dt.today() - _td(days=days_back)).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as con:
        rows = con.execute("""
            SELECT pair_address, symbol, observed_at, stage FROM crypto_dex_stage_log
            WHERE observed_at >= ? ORDER BY pair_address, observed_at ASC
        """, (cutoff,)).fetchall()

    by_pair: dict = {}
    for pair_address, symbol, observed_at, stage in rows:
        by_pair.setdefault(pair_address, {"symbol": symbol, "history": []})
        by_pair[pair_address]["history"].append({"observed_at": observed_at, "stage": stage})

    graduations = []
    for pair_address, data in by_pair.items():
        history = data["history"]
        first_building_idx = next((i for i, h in enumerate(history) if h["stage"] == "BUILDING"), None)
        if first_building_idx is None:
            continue
        later_early_move = any(h["stage"] == "EARLY_MOVE" for h in history[first_building_idx + 1:])
        if later_early_move:
            graduations.append({"pair_address": pair_address, "symbol": data["symbol"],
                                "first_building_at": history[first_building_idx]["observed_at"],
                                "history": history})
    return graduations


def get_dex_unchanged_streak(pair_address: str, current_stage: str, current_conditions_met: int) -> int:
    """v4.9.1 — 'on each hourly run it's giving the same outcome, then
    what's the use.' AERO/BRETT/TOSHI's pool age only ever increases —
    'pair not fresh enough' can NEVER resolve for an existing pool, so
    repeating that exact rejection every hour is genuinely zero new
    information. This counts how many CONSECUTIVE prior scans showed
    the identical (stage, conditions_met) as right now — the caller uses
    this to stop repeating a candidate that hasn't changed in hours."""
    with get_conn() as con:
        rows = con.execute("""
            SELECT stage, conditions_met FROM crypto_dex_stage_log
            WHERE pair_address = ? ORDER BY observed_at DESC LIMIT 10
        """, (pair_address,)).fetchall()

    streak = 0
    for stage, conditions_met in rows:
        if stage == current_stage and conditions_met == current_conditions_met:
            streak += 1
        else:
            break
    return streak


def get_dex_chain_cursor() -> Optional[int]:
    """Last Base block number scanned for new-pool events. None if
    never scanned before (first run — caller should pick a reasonable
    starting point, e.g. current_block - N, not genesis)."""
    with get_conn() as con:
        row = con.execute("SELECT last_scanned_block FROM crypto_dex_chain_cursor WHERE id = 1").fetchone()
    return row[0] if row else None


def set_dex_chain_cursor(block_number: int) -> None:
    from datetime import datetime as _dt
    now = _dt.today().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn(write=True) as con:
        con.execute("""
            INSERT INTO crypto_dex_chain_cursor (id, last_scanned_block, last_scanned_at)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET last_scanned_block=excluded.last_scanned_block,
                last_scanned_at=excluded.last_scanned_at
        """, (block_number, now))


def get_dex_chain_cursor_v2(dex_name: str) -> Optional[int]:
    """v4.9.13 — per-DEX cursor (e.g. 'uniswap_v3', 'aerodrome'), each
    tracked independently. None if this specific DEX has never been
    scanned before."""
    with get_conn() as con:
        row = con.execute(
            "SELECT last_scanned_block FROM crypto_dex_chain_cursor_v2 WHERE dex_name = ?", (dex_name,)
        ).fetchone()
    return row[0] if row else None


def set_dex_chain_cursor_v2(dex_name: str, block_number: int) -> None:
    from datetime import datetime as _dt
    now = _dt.today().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn(write=True) as con:
        con.execute("""
            INSERT INTO crypto_dex_chain_cursor_v2 (dex_name, last_scanned_block, last_scanned_at)
            VALUES (?, ?, ?)
            ON CONFLICT(dex_name) DO UPDATE SET last_scanned_block=excluded.last_scanned_block,
                last_scanned_at=excluded.last_scanned_at
        """, (dex_name, block_number, now))


def log_dex_lifecycle(pair_address: str, symbol: str, source: str, pool_age_hours,
                       liquidity_usd, volume_24h_usd, pct_24h, pair_new: bool, liquidity_accel: bool,
                       volume_accel: bool, tx_accel: bool, buy_pressure: bool, price_near_base: bool,
                       already_extended: bool, security_severity: str, pre_pearl_score: float,
                       classification: str, breakdown: list) -> int:
    """v4.9.15 — INSERT-ONLY, one row per (candidate, scan). This is the
    ledger that makes 'nothing disappears silently' a provable claim
    rather than an assertion — every candidate that reaches scoring gets
    a permanent row here, regardless of its final disposition, including
    IGNORE and BLOCKED. Returns the new discovery_id."""
    import json
    from datetime import datetime as _dt
    now = _dt.today().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn(write=True) as con:
        cur = con.execute("""
            INSERT INTO crypto_dex_lifecycle
                (pair_address, symbol, source, observed_at, pool_age_hours, liquidity_usd,
                 volume_24h_usd, pct_24h, pair_new, liquidity_accel, volume_accel, tx_accel,
                 buy_pressure, price_near_base, already_extended, security_severity,
                 pre_pearl_score, classification, breakdown_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (pair_address, symbol.upper(), source, now, pool_age_hours, liquidity_usd, volume_24h_usd,
              pct_24h, int(pair_new), int(liquidity_accel), int(volume_accel), int(tx_accel),
              int(buy_pressure), int(price_near_base), int(already_extended), security_severity,
              pre_pearl_score, classification, json.dumps(breakdown)))
        return cur.lastrowid


def get_dex_lifecycle_report(days_back: int = 1, source_filter: str = None) -> dict:
    """v4.9.15 — REVERSE-ENGINEERED FROM THE TARGET QUESTION: 'we
    examined X genuinely new pools and Y awakening assets, Z reached
    precursor scoring, here are the rejection reasons, here's what
    happened after.' Joins the lifecycle ledger against
    crypto_dex_first_seen's own resolution columns (by pair_address) to
    attach forward outcomes (1h/6h/24h) wherever they've resolved.

    v4.9.16 FIXES, both confirmed as real from production logs:
    1. NO IMPLICIT TIME AMBIGUITY — returns requested_period_days,
       actual_cutoff, and 'now' explicitly, so a caller (or the
       Telegram message) can never silently misreport what window was
       actually used. This doesn't prevent someone from passing 100 when
       they meant 1 — GitHub Actions' manual dispatch dialog remembers
       the LAST entered value, which is almost certainly what happened
       in production — but it makes the ACTUAL window used impossible
       to miss or misread.
    2. DEDUPLICATION — the raw ledger correctly logs every scan of every
       candidate (that's the right behavior for full traceability), but
       a SUMMARY of '28 candidates examined' when it's actually the same
       2 tokens observed 14 times each is misleading. Now reports BOTH:
       total_raw_observations (the full ledger count, for transparency)
       AND unique_tokens_examined (deduplicated by symbol+pair_address,
       showing only the MOST RECENT scoring per token) — the caller can
       use whichever framing fits."""
    from datetime import datetime as _dt, timedelta as _td
    now = _dt.today()
    cutoff_dt = now - _td(days=days_back)
    cutoff = cutoff_dt.strftime("%Y-%m-%d %H:%M:%S")

    lifecycle_cols = ["discovery_id", "pair_address", "symbol", "source", "observed_at",
                      "pool_age_hours", "pair_new", "liquidity_accel", "volume_accel", "tx_accel",
                      "buy_pressure", "price_near_base", "already_extended", "security_severity",
                      "pre_pearl_score", "classification", "breakdown_json"]
    query = f"SELECT {', '.join(lifecycle_cols)} FROM crypto_dex_lifecycle WHERE observed_at >= ?"
    params = [cutoff]
    if source_filter:
        query += " AND source = ?"
        params.append(source_filter)
    query += " ORDER BY observed_at DESC"

    with get_conn() as con:
        rows = con.execute(query, params).fetchall()

    import json
    entries = []
    for r in rows:
        entry = dict(zip(lifecycle_cols, r))
        entry["breakdown"] = json.loads(entry.pop("breakdown_json") or "[]")
        # attach forward outcomes from the SAME pair's first-seen record, if resolved
        with get_conn() as con:
            outcome_row = con.execute("""
                SELECT return_1h_pct, resolved_1h, return_6h_pct, resolved_6h,
                       return_24h_pct, resolved_24h, first_seen_at
                FROM crypto_dex_first_seen WHERE pair_address = ?
            """, (entry["pair_address"],)).fetchone()
        if outcome_row:
            entry["return_1h_pct"] = outcome_row[0] if outcome_row[1] else None
            entry["return_6h_pct"] = outcome_row[2] if outcome_row[3] else None
            entry["return_24h_pct"] = outcome_row[4] if outcome_row[5] else None
            entry["first_seen_at"] = outcome_row[6]
        else:
            entry["return_1h_pct"] = entry["return_6h_pct"] = entry["return_24h_pct"] = None
            entry["first_seen_at"] = None
        entries.append(entry)

    # ── v4.9.17 fix: v4.9.16 deduplicated by (symbol, pair_address),
    # which STILL treats every different POOL of the same token as a
    # separate "unique token" — AERO alone has 7+ distinct pools, so
    # this fixed the TIME-repetition (same pool, many hourly scans) but
    # NOT the POOL-repetition (same token, many pools), which is exactly
    # why AERO still appeared ~10 times in the confirmed real output.
    # Deduplicating by SYMBOL ALONE now — that's what "how many distinct
    # tokens did we examine" actually means. Keeps the highest-scoring
    # pool per symbol as the representative (most informative one to show).
    by_symbol: dict = {}
    for e in entries:
        by_symbol.setdefault(e["symbol"], []).append(e)
    unique_entries = [max(pools, key=lambda e: e["pre_pearl_score"]) for pools in by_symbol.values()]
    unique_entries.sort(key=lambda e: e["observed_at"], reverse=True)
    total_pools_examined = len(set((e["symbol"], e["pair_address"]) for e in entries))

    # summary counts, exactly matching the requested success-criteria
    # language — computed on the DEDUPLICATED-BY-SYMBOL set, since
    # "14 candidates" that are really one token across 14 pools/scans
    # is not 14 opportunities.
    new_pool_entries = [e for e in unique_entries if (e["source"] or "").startswith("CHAIN_EVENT")]
    awakening_entries = [e for e in unique_entries if not (e["source"] or "").startswith("CHAIN_EVENT")]
    by_classification = {}
    for e in unique_entries:
        by_classification.setdefault(e["classification"], 0)
        by_classification[e["classification"]] += 1

    return {
        "entries": unique_entries,
        "total_raw_observations": len(entries),
        "total_pools_examined": total_pools_examined,
        "total_examined": len(unique_entries),
        "new_pool_count": len(new_pool_entries),
        "awakening_count": len(awakening_entries),
        "by_classification": by_classification,
        "requested_period_days": days_back,
        "actual_cutoff": cutoff,
        "report_generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    }


def get_dex_milestone_timeline(symbol: str, days_back: int = 30) -> dict:
    """v4.9.19 — answers the exact gap flagged: 'the system doesn't know
    when it first encountered the pool... we need persistent first-seen
    timestamps.' Built entirely from data ALREADY BEING COLLECTED
    (crypto_dex_lifecycle logs a classification for every scan) — no new
    data collection needed, just the query that was never written to
    assemble it into a timeline.

    Returns the FIRST timestamp each milestone was ever reached, in
    chronological order: first_seen_at, first_building_at,
    first_pre_pearl_at, first_early_move_at (via crypto_dex_first_seen's
    own is_early_move_at_discovery flag). Then computes the deltas
    between them — 'time_from_discovery → acceleration' becomes a real,
    queryable number instead of 'unknown.'

    Returns None values for any milestone never reached — honestly, not
    guessed."""
    from datetime import datetime as _dt, timedelta as _td
    cutoff = (_dt.today() - _td(days=days_back)).strftime("%Y-%m-%d %H:%M:%S")

    with get_conn() as con:
        rows = con.execute("""
            SELECT observed_at, classification, pool_age_hours FROM crypto_dex_lifecycle
            WHERE symbol = ? AND observed_at >= ? ORDER BY observed_at ASC
        """, (symbol.upper(), cutoff)).fetchall()

    if not rows:
        return {"symbol": symbol.upper(), "found": False}

    first_seen_at = rows[0][0]
    first_seen_pool_age_hours = rows[0][2]

    milestones = {"first_seen_at": first_seen_at, "first_building_at": None,
                  "first_pre_pearl_at": None, "first_early_move_at": None}
    for observed_at, classification, _ in rows:
        if classification == "🟡 BUILDING" and milestones["first_building_at"] is None:
            milestones["first_building_at"] = observed_at
        if classification == "🟢 PRE-PEARL" and milestones["first_pre_pearl_at"] is None:
            milestones["first_pre_pearl_at"] = observed_at

    # early-move flag lives on crypto_dex_first_seen, not the lifecycle
    # log (early move is checked via a different code path) — join it in
    with get_conn() as con:
        early_row = con.execute("""
            SELECT first_seen_at FROM crypto_dex_first_seen
            WHERE symbol = ? AND is_early_move_at_discovery = 1
            ORDER BY first_seen_at ASC LIMIT 1
        """, (symbol.upper(),)).fetchone()
    if early_row:
        milestones["first_early_move_at"] = early_row[0]

    # compute deltas — the actual "how early" answer, in hours
    def _hours_between(t1: str, t2: str) -> Optional[float]:
        if not t1 or not t2:
            return None
        try:
            dt1 = _dt.strptime(t1, "%Y-%m-%d %H:%M:%S")
            dt2 = _dt.strptime(t2, "%Y-%m-%d %H:%M:%S")
            return round((dt2 - dt1).total_seconds() / 3600.0, 2)
        except (ValueError, TypeError):
            return None

    deltas = {
        "discovery_latency_hours": first_seen_pool_age_hours,  # pool creation -> Fortress first saw it
        "discovery_to_building_hours": _hours_between(milestones["first_seen_at"], milestones["first_building_at"]),
        "discovery_to_pre_pearl_hours": _hours_between(milestones["first_seen_at"], milestones["first_pre_pearl_at"]),
        "discovery_to_early_move_hours": _hours_between(milestones["first_seen_at"], milestones["first_early_move_at"]),
    }

    return {"symbol": symbol.upper(), "found": True, "total_observations": len(rows),
            "milestones": milestones, "deltas": deltas}
