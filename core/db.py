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
