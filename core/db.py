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
                 status_at_discovery, tier_at_discovery, why_it_surfaced, invalidation_conditions)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            snapshot["symbol"], snapshot["coin_id"], now, snapshot["price_at_observation"],
            snapshot["discovery_score"], snapshot["evidence_level"], snapshot["evidence_label"],
            snapshot.get("whale_score"), snapshot.get("whale_label_at_discovery"),
            snapshot.get("news_score"), snapshot.get("news_label_at_discovery"),
            snapshot.get("liquidity_score"), snapshot.get("structure_score"),
            snapshot.get("onchain_score"), snapshot["false_pearl_risk_pct"],
            snapshot["risk_severity_at_discovery"], snapshot["status_at_discovery"],
            snapshot.get("tier_at_discovery"),
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
